import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.progress_stream import ProgressChangeTracker, parse_stage_snapshot
from app.core.types import StageProgress, StageResult
from app.db.session import AsyncSessionLocal
from app.domain.stage_contracts import normalize_stage_output
from app.models.project import Project, ProjectStatus
from app.models.stage import StageExecution, StageStatus, StageType
from app.services.project_cover_service import ProjectCoverService
from app.workflow.stage_registry import stage_registry

logger = logging.getLogger(__name__)


class PipelineEngine:
    def __init__(self, db: AsyncSession, project: Project):
        self.db = db
        self.project = project

    def get_stage_number(self, stage_type: StageType) -> int:
        return stage_registry.get_stage_number(stage_type)

    def get_applicable_stages(self) -> list[StageType]:
        return stage_registry.list_stage_types()

    def is_optional_stage(self, stage_type: StageType) -> bool:
        return stage_registry.is_optional(stage_type)

    async def get_or_create_stage(self, stage_type: StageType) -> StageExecution:
        result = await self.db.execute(
            select(StageExecution).where(
                StageExecution.project_id == self.project.id,
                StageExecution.stage_type == stage_type,
            )
        )
        stage = result.scalar_one_or_none()

        if not stage:
            stage = StageExecution(
                project_id=self.project.id,
                stage_type=stage_type,
                stage_number=self.get_stage_number(stage_type),
                status=StageStatus.PENDING,
            )
            self.db.add(stage)
            await self.db.commit()
            await self.db.refresh(stage)

        return stage

    async def run_stage(
        self, stage_type: StageType, input_data: dict[str, Any] | None = None
    ) -> AsyncIterator[StageProgress]:
        stage = await self.get_or_create_stage(stage_type)
        stage_id = stage.id

        self.project.status = ProjectStatus.RUNNING
        self.project.current_stage = self.get_stage_number(stage_type)
        await self.db.commit()

        stage.status = StageStatus.RUNNING
        stage.progress = 0
        stage.last_item_complete = -1  # Reset for batch operations
        stage.input_data = input_data
        stage.error_message = None
        self.project.error_message = None
        await self.db.commit()

        yield StageProgress(stage_type=stage_type, progress=0, message="开始执行")

        # 使用队列来传递进度更新
        progress_queue: asyncio.Queue[StageProgress | None] = asyncio.Queue()
        stop_polling = asyncio.Event()  # 用于通知 poll_progress 停止

        async def execute_and_signal():
            """执行阶段并在完成后发送信号"""
            should_schedule_project_cover = False
            try:
                result = await self._execute_stage(stage_type, stage, input_data)
                # 先停止轮询，再操作数据库
                stop_polling.set()
                # 执行完成，发送最终结果
                if result.success:
                    stage.progress = 100
                    stage.output_data = normalize_stage_output(stage_type, result.data)
                    stage.error_message = None
                    self.project.error_message = None
                    if result.skipped:
                        stage.status = StageStatus.SKIPPED
                        await progress_queue.put(
                            StageProgress(
                                stage_type=stage_type,
                                progress=100,
                                message=result.message or "执行已跳过",
                            )
                        )
                    else:
                        stage.status = StageStatus.COMPLETED
                        if (
                            stage_type == StageType.CONTENT
                            and not bool(self.project.cover_generation_attempted)
                            and ProjectCoverService.has_usable_content_payload(stage.output_data)
                        ):
                            self.project.cover_generation_attempted = True
                            should_schedule_project_cover = True
                        await progress_queue.put(
                            StageProgress(stage_type=stage_type, progress=100, message="执行完成")
                        )
                else:
                    stage.status = StageStatus.FAILED
                    stage.error_message = result.error
                    self.project.status = ProjectStatus.FAILED
                    self.project.error_message = result.error
                    await progress_queue.put(
                        StageProgress(
                            stage_type=stage_type,
                            progress=stage.progress,
                            message=f"执行失败: {result.error}",
                        )
                    )
            except asyncio.CancelledError:
                stop_polling.set()
                if stage.status == StageStatus.RUNNING:
                    stage.status = StageStatus.FAILED
                    stage.error_message = "执行已取消"
                    if self.project.status == ProjectStatus.RUNNING:
                        self.project.status = ProjectStatus.FAILED
                        self.project.error_message = "执行已取消"
                try:
                    await progress_queue.put(
                        StageProgress(
                            stage_type=stage_type,
                            progress=stage.progress,
                            message="执行已取消",
                        )
                    )
                except Exception:
                    pass
                raise
            except Exception as e:
                stop_polling.set()
                stage.status = StageStatus.FAILED
                stage.error_message = str(e)
                self.project.status = ProjectStatus.FAILED
                self.project.error_message = str(e)
                await progress_queue.put(
                    StageProgress(
                        stage_type=stage_type, progress=stage.progress, message=f"执行错误: {e}"
                    )
                )
            finally:
                await self.db.commit()
                if should_schedule_project_cover:
                    await ProjectCoverService.schedule_initial_generation(self.project.id)
                # 发送 None 表示结束
                await progress_queue.put(None)

        async def poll_progress():
            """定期轮询数据库中的进度"""
            tracker = ProgressChangeTracker(initial_progress=0)
            async with AsyncSessionLocal() as poll_db:
                while not stop_polling.is_set():
                    try:
                        # 使用 wait_for 来允许提前退出
                        await asyncio.wait_for(stop_polling.wait(), timeout=0.5)
                        break  # stop_polling 被设置，退出循环
                    except TimeoutError:
                        pass  # 超时，继续轮询

                    if stop_polling.is_set():
                        break

                    try:
                        # 关键点：轮询使用独立 session 时，若一直处于同一读事务，
                        # SQLite 可能持续读取到旧快照，导致前端进度长时间不更新。
                        # 每轮先 rollback 结束上一次事务，再用 populate_existing 强制读取最新值。
                        try:
                            await poll_db.rollback()
                        except Exception:
                            pass

                        result = await poll_db.execute(
                            select(StageExecution)
                            .where(StageExecution.id == stage_id)
                            .execution_options(populate_existing=True)
                        )
                        stage_row = result.scalar_one_or_none()
                        if not stage_row:
                            break
                    except Exception as e:
                        # SQLite 在高频读写时可能出现瞬时锁冲突。
                        # 不应直接停止轮询，否则前端会一直停在初始进度。
                        logger.warning("poll_progress query failed, will retry: %s", e)
                        try:
                            await poll_db.rollback()
                        except Exception:
                            pass
                        continue

                    snap = parse_stage_snapshot(stage_row, stage_type)
                    if not tracker.detect_change(snap):
                        continue

                    # Determine message based on what changed
                    if (
                        snap.last_item_complete is not None
                        and snap.last_item_complete >= 0
                        and snap.last_item_complete != tracker.last_item_complete
                    ):
                        message = f"完成第 {snap.last_item_complete + 1} 项"
                        item_complete = snap.last_item_complete
                    else:
                        message = snap.progress_message or snap.fallback_message
                        item_complete = None
                        if snap.progress > tracker.last_progress and snap.progress < 100:
                            logger.info(
                                "poll_progress update: stage=%s id=%s progress=%s"
                                " generating_shots=%s",
                                stage_type.value,
                                stage_id,
                                snap.progress,
                                len(snap.generating_shots)
                                if isinstance(snap.generating_shots, dict)
                                else 0,
                            )

                    await progress_queue.put(
                        StageProgress(
                            stage_type=stage_type,
                            progress=snap.progress,
                            message=message,
                            item_complete=item_complete,
                            total_items=snap.total_items,
                            completed_items=snap.completed_items,
                            skipped_items=snap.skipped_items,
                            generating_shots=snap.generating_shots,
                        )
                    )
                    tracker.accept(snap)

        # 启动执行任务
        execute_task = asyncio.create_task(execute_and_signal())
        # 启动进度轮询任务
        poll_task = asyncio.create_task(poll_progress())

        try:
            # 从队列中读取进度更新并 yield
            while True:
                progress = await progress_queue.get()
                if progress is None:
                    break
                yield progress
        finally:
            # 确保任务被清理
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass
            # 连接断开/服务停机时不要等待长任务自然结束，主动取消以尽快释放资源（如 GPU 显存）
            if not execute_task.done():
                execute_task.cancel()
            try:
                await asyncio.wait_for(execute_task, timeout=5.0)
            except TimeoutError:
                logger.warning(
                    "execute_task did not stop within timeout: stage=%s id=%s",
                    stage_type.value,
                    stage_id,
                )
            except asyncio.CancelledError:
                pass

    async def _execute_stage(
        self, stage_type: StageType, stage: StageExecution, input_data: dict[str, Any] | None
    ) -> StageResult:
        from app.stages import get_stage_handler

        handler = get_stage_handler(stage_type)
        if not handler:
            return StageResult(success=False, error=f"No handler for stage {stage_type}")

        error = await handler.validate_prerequisites(self.db, self.project)
        if error:
            return StageResult(success=False, error=error)
        return await handler.execute(self.db, self.project, stage, input_data)

    async def run_pipeline(
        self,
        from_stage: StageType | None = None,
        to_stage: StageType | None = None,
        input_data: dict[str, Any] | None = None,
    ) -> AsyncIterator[StageProgress]:
        stages = stage_registry.resolve_execution_subset(
            from_stage=from_stage,
            to_stage=to_stage,
        )

        for stage_type in stages:
            async for progress in self.run_stage(stage_type, input_data):
                yield progress

            stage = await self.get_or_create_stage(stage_type)
            if stage.status == StageStatus.FAILED and not self.is_optional_stage(stage_type):
                break

        if self.project.status == ProjectStatus.RUNNING:
            self.project.status = ProjectStatus.COMPLETED
            self.project.error_message = None
            await self.db.commit()
