import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession

from app.core.errors import ServiceError
from app.core.pipeline import PipelineEngine
from app.core.progress_stream import (
    ProgressChangeTracker,
    build_status_message,
    parse_stage_snapshot,
)
from app.db.session import AsyncSessionLocal
from app.models.pipeline_run import PipelineRun, PipelineRunStatus
from app.models.pipeline_task import PipelineTask, PipelineTaskKind, PipelineTaskStatus
from app.models.project import Project, ProjectStatus
from app.models.stage import StageExecution, StageStatus, StageType
from app.schemas.stage import (
    PipelineRunRequest,
    StageListItem,
    StageListResponse,
    StageProgressEvent,
    StageResponse,
    StageRunRequest,
)
from app.workflow.stage_registry import stage_registry

logger = logging.getLogger(__name__)

_STAGE_BACKGROUND_TASKS: dict[tuple[int, StageType], asyncio.Task[None]] = {}
_STAGE_BACKGROUND_TASK_META: dict[tuple[int, StageType], int] = {}
_STAGE_BACKGROUND_TASKS_LOCK = asyncio.Lock()
_PIPELINE_BACKGROUND_TASKS: dict[int, asyncio.Task[None]] = {}
_PIPELINE_BACKGROUND_TASK_META: dict[int, tuple[StageType | None, StageType | None, int]] = {}
_PIPELINE_BACKGROUND_TASKS_LOCK = asyncio.Lock()
_TASK_STALE_TIMEOUT = timedelta(minutes=10)


class StageOrchestrationMixin:
    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    async def recover_stale_state_on_startup(db: _AsyncSession) -> tuple[int, int]:
        """Reset all RUNNING stages/projects to FAILED after process restart.

        Returns (recovered_projects, recovered_stages).
        """
        stage_result = await db.execute(
            select(StageExecution).where(StageExecution.status == StageStatus.RUNNING)
        )
        running_stages = list(stage_result.scalars().all())

        project_result = await db.execute(
            select(Project).where(Project.status == ProjectStatus.RUNNING)
        )
        running_projects = list(project_result.scalars().all())

        for stage in running_stages:
            stage.status = StageStatus.FAILED
            stage.error_message = "检测到服务重启，中断任务已自动结束"

        for project in running_projects:
            project.status = ProjectStatus.FAILED
            project.current_stage = None
            if not project.error_message:
                project.error_message = "检测到服务重启，中断任务已自动结束"

        run_result = await db.execute(
            select(PipelineRun).where(PipelineRun.status == PipelineRunStatus.RUNNING)
        )
        running_runs = list(run_result.scalars().all())
        task_result = await db.execute(
            select(PipelineTask).where(
                PipelineTask.status.in_([PipelineTaskStatus.PENDING, PipelineTaskStatus.RUNNING])
            )
        )
        running_tasks = list(task_result.scalars().all())

        finished_at = StageOrchestrationMixin._now_utc()
        for row in running_runs:
            row.status = PipelineRunStatus.FAILED
            row.finished_at = finished_at
            row.heartbeat_at = finished_at
            if not row.error_message:
                row.error_message = "检测到服务重启，中断任务已自动结束"

        for row in running_tasks:
            row.status = PipelineTaskStatus.CANCELLED
            row.finished_at = finished_at
            row.heartbeat_at = finished_at
            if not row.error_message:
                row.error_message = "检测到服务重启，中断任务已自动结束"

        if running_stages or running_projects or running_runs or running_tasks:
            await db.commit()

        return len(running_projects), len(running_stages)

    async def _create_stage_task_record(
        self,
        *,
        project_id: int,
        stage_type: StageType,
        worker_name: str,
    ) -> int:
        now = self._now_utc()
        task = PipelineTask(
            run_id=None,
            project_id=project_id,
            stage_type=stage_type,
            task_kind=PipelineTaskKind.STAGE,
            status=PipelineTaskStatus.RUNNING,
            attempt=1,
            worker_name=worker_name,
            started_at=now,
            heartbeat_at=now,
        )
        self.db.add(task)
        await self._commit_with_retry()
        await self.db.refresh(task)
        return task.id

    @staticmethod
    async def _update_stage_task_record(
        task_id: int,
        *,
        status: PipelineTaskStatus,
        error_message: str | None = None,
        heartbeat: bool = True,
    ) -> None:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(PipelineTask).where(PipelineTask.id == task_id))
            row = result.scalar_one_or_none()
            if row is None:
                return
            now = StageOrchestrationMixin._now_utc()
            row.status = status
            if heartbeat:
                row.heartbeat_at = now
            if status in {
                PipelineTaskStatus.COMPLETED,
                PipelineTaskStatus.FAILED,
                PipelineTaskStatus.CANCELLED,
                PipelineTaskStatus.SKIPPED,
            }:
                row.finished_at = now
            if error_message:
                row.error_message = error_message
            await db.commit()

    async def _create_pipeline_run_record(
        self,
        *,
        project_id: int,
        from_stage: StageType | None,
        to_stage: StageType | None,
        worker_name: str,
    ) -> int:
        now = self._now_utc()
        run = PipelineRun(
            project_id=project_id,
            status=PipelineRunStatus.RUNNING,
            from_stage=from_stage,
            to_stage=to_stage,
            current_stage=None,
            worker_name=worker_name,
            started_at=now,
            heartbeat_at=now,
        )
        self.db.add(run)
        await self._commit_with_retry()
        await self.db.refresh(run)
        return run.id

    async def _create_pipeline_stage_task_records(
        self,
        *,
        run_id: int,
        project_id: int,
        stages: list[StageType],
        worker_name: str,
    ) -> None:
        now = self._now_utc()
        for stage_type in stages:
            self.db.add(
                PipelineTask(
                    run_id=run_id,
                    project_id=project_id,
                    stage_type=stage_type,
                    task_kind=PipelineTaskKind.PIPELINE_STAGE,
                    status=PipelineTaskStatus.PENDING,
                    attempt=1,
                    worker_name=worker_name,
                    started_at=now,
                    heartbeat_at=now,
                )
            )
        await self._commit_with_retry()

    @staticmethod
    async def _update_pipeline_run_record(
        run_id: int,
        *,
        status: PipelineRunStatus | None = None,
        current_stage: StageType | None = None,
        error_message: str | None = None,
        finish: bool = False,
    ) -> None:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))
            row = result.scalar_one_or_none()
            if row is None:
                return
            now = StageOrchestrationMixin._now_utc()
            row.heartbeat_at = now
            if current_stage is not None:
                row.current_stage = current_stage
            if status is not None:
                row.status = status
            if error_message:
                row.error_message = error_message
            if finish:
                row.finished_at = now
            await db.commit()

    @staticmethod
    async def _sync_pipeline_task_records_with_stage_rows(
        *,
        run_id: int,
        project_id: int,
        stage_rows: list[StageExecution],
    ) -> None:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(PipelineTask).where(PipelineTask.run_id == run_id))
            task_rows = list(result.scalars().all())
            stage_status_map = {one.stage_type: one for one in stage_rows}
            now = StageOrchestrationMixin._now_utc()
            for row in task_rows:
                stage_row = stage_status_map.get(row.stage_type)
                if stage_row is None:
                    row.status = PipelineTaskStatus.SKIPPED
                    row.finished_at = now
                    row.heartbeat_at = now
                    continue
                row.heartbeat_at = now
                if stage_row.status == StageStatus.COMPLETED:
                    row.status = PipelineTaskStatus.COMPLETED
                    row.finished_at = now
                elif stage_row.status == StageStatus.FAILED:
                    row.status = PipelineTaskStatus.FAILED
                    row.error_message = stage_row.error_message
                    row.finished_at = now
                elif stage_row.status == StageStatus.SKIPPED:
                    row.status = PipelineTaskStatus.SKIPPED
                    row.finished_at = now
                elif stage_row.status == StageStatus.RUNNING:
                    row.status = PipelineTaskStatus.RUNNING
            await db.commit()

    @staticmethod
    async def _update_pipeline_stage_task_record(
        *,
        run_id: int,
        stage_type: StageType,
        status: PipelineTaskStatus,
        error_message: str | None = None,
    ) -> None:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PipelineTask).where(
                    PipelineTask.run_id == run_id,
                    PipelineTask.stage_type == stage_type,
                    PipelineTask.task_kind == PipelineTaskKind.PIPELINE_STAGE,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return
            now = StageOrchestrationMixin._now_utc()
            row.status = status
            row.heartbeat_at = now
            if error_message:
                row.error_message = error_message
            if status in {
                PipelineTaskStatus.COMPLETED,
                PipelineTaskStatus.FAILED,
                PipelineTaskStatus.CANCELLED,
                PipelineTaskStatus.SKIPPED,
            }:
                row.finished_at = now
            await db.commit()

    @staticmethod
    async def _finalize_pipeline_stage_tasks_for_run(
        *,
        run_id: int,
        status: PipelineTaskStatus,
        error_message: str | None = None,
    ) -> None:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PipelineTask).where(
                    PipelineTask.run_id == run_id,
                    PipelineTask.status.in_(
                        [PipelineTaskStatus.PENDING, PipelineTaskStatus.RUNNING]
                    ),
                )
            )
            rows = list(result.scalars().all())
            if not rows:
                return
            now = StageOrchestrationMixin._now_utc()
            for row in rows:
                row.status = status
                row.heartbeat_at = now
                row.finished_at = now
                if error_message and not row.error_message:
                    row.error_message = error_message
            await db.commit()

    async def list_stages(self, project_id: int) -> StageListResponse:
        project = await self.get_project_or_404(project_id)
        await self._recover_stale_running_stages(project_id)
        await self._recover_stale_pipeline_runtime(project_id)
        pipeline = PipelineEngine(self.db, project)
        applicable_stages = set(pipeline.get_applicable_stages())

        result = await self._execute_with_retry(
            select(StageExecution)
            .where(StageExecution.project_id == project_id)
            .order_by(StageExecution.stage_number)
        )
        existing_stages = {s.stage_type: s for s in result.scalars().all()}

        items = []
        for stage_type in pipeline.get_applicable_stages():
            existing = existing_stages.get(stage_type)
            items.append(
                StageListItem(
                    stage_type=stage_type,
                    stage_number=pipeline.get_stage_number(stage_type),
                    status=existing.status if existing else StageStatus.PENDING,
                    progress=existing.progress if existing else 0,
                    is_applicable=stage_type in applicable_stages,
                    is_optional=pipeline.is_optional_stage(stage_type),
                    error_message=(
                        existing.error_message
                        if existing and existing.status == StageStatus.FAILED
                        else None
                    ),
                )
            )

        return StageListResponse(items=items, current_stage=project.current_stage)

    async def get_stage(self, project_id: int, stage_type: StageType) -> StageResponse:
        project = await self.get_project_or_404(project_id)
        await self._recover_stale_running_stages(project_id, stage_type=stage_type)
        await self._recover_stale_pipeline_runtime(project_id)
        pipeline = PipelineEngine(self.db, project)

        result = await self._execute_with_retry(
            select(StageExecution).where(
                StageExecution.project_id == project_id,
                StageExecution.stage_type == stage_type,
            )
        )
        stage = result.scalar_one_or_none()
        if not stage:
            stage = StageExecution(
                project_id=project_id,
                stage_type=stage_type,
                stage_number=pipeline.get_stage_number(stage_type),
                status=StageStatus.PENDING,
                progress=0,
            )
            self.db.add(stage)
            await self._commit_with_retry()
            await self.db.refresh(stage)
        return stage

    async def run_stage(
        self,
        project_id: int,
        stage_type: StageType,
        request: StageRunRequest,
    ) -> StageResponse:
        project = await self.get_project_or_404(project_id)
        await self._recover_stale_running_stages(project_id, stage_type=stage_type)
        await self._recover_stale_pipeline_runtime(project_id)
        pipeline = PipelineEngine(self.db, project)

        applicable_stages = pipeline.get_applicable_stages()
        if stage_type not in applicable_stages:
            raise ServiceError(400, f"Stage {stage_type} is not applicable")

        existing = await self._execute_with_retry(
            select(StageExecution).where(
                StageExecution.project_id == project_id,
                StageExecution.stage_type == stage_type,
            )
        )
        stage = existing.scalar_one_or_none()

        if stage and stage.status == StageStatus.COMPLETED and not request.force:
            raise ServiceError(400, "Stage already completed. Use force=true to re-run.")

        if stage and stage.status == StageStatus.RUNNING:
            raise ServiceError(400, "Stage is already running")

        async for _ in pipeline.run_stage(stage_type, request.input_data):
            pass

        stage = await pipeline.get_or_create_stage(stage_type)
        return stage

    async def stream_stage(
        self,
        project_id: int,
        stage_type: StageType,
        force: bool,
        input_data: str | None,
    ) -> StreamingResponse:
        project = await self.get_project_or_404(project_id)
        await self._recover_stale_running_stages(project_id, stage_type=stage_type)
        await self._recover_stale_pipeline_runtime(project_id)
        pipeline = PipelineEngine(self.db, project)
        applicable_stages = pipeline.get_applicable_stages()
        if stage_type not in applicable_stages:
            raise ServiceError(400, f"Stage {stage_type} is not applicable")

        parsed_input_data = None
        if input_data:
            try:
                parsed_input_data = json.loads(input_data)
            except json.JSONDecodeError:
                raise ServiceError(400, "Invalid input_data JSON format")

        if stage_type == StageType.FINALIZE:
            existing_finalize_result = await self._execute_with_retry(
                select(StageExecution).where(
                    StageExecution.project_id == project_id,
                    StageExecution.stage_type == stage_type,
                )
            )
            existing_finalize_stage = existing_finalize_result.scalar_one_or_none()
            if (
                existing_finalize_stage
                and existing_finalize_stage.status == StageStatus.COMPLETED
                and not force
            ):
                raise ServiceError(400, "Stage already completed. Use force=true to re-run.")
            stage_range = stage_registry.resolve_execution_subset(
                from_stage=StageType.COMPOSE,
                to_stage=StageType.FINALIZE,
            )
            await self._ensure_background_pipeline_task(
                project_id,
                StageType.COMPOSE,
                StageType.FINALIZE,
                parsed_input_data,
                force_restart=force,
            )

            async def finalize_event_generator():
                tracker = ProgressChangeTracker()
                last_status: StageStatus | None = None
                last_stage_type: StageType | None = None

                async with AsyncSessionLocal() as poll_db:
                    while True:
                        try:
                            await poll_db.rollback()
                        except Exception:
                            pass

                        result = await poll_db.execute(
                            select(StageExecution)
                            .where(
                                StageExecution.project_id == project_id,
                                StageExecution.stage_type.in_(stage_range),
                            )
                            .order_by(StageExecution.stage_number)
                            .execution_options(populate_existing=True)
                        )
                        stage_rows = list(result.scalars().all())
                        running_row = next(
                            (row for row in stage_rows if row.status == StageStatus.RUNNING),
                            None,
                        )
                        current_row = running_row
                        if current_row is None and stage_rows:
                            current_row = next(
                                (
                                    row
                                    for row in reversed(stage_rows)
                                    if row.status != StageStatus.PENDING
                                ),
                                stage_rows[-1],
                            )

                        if not current_row:
                            if not await self._has_active_pipeline_background_task(project_id):
                                break
                            await asyncio.sleep(0.5)
                            continue

                        snap = parse_stage_snapshot(current_row, current_row.stage_type)
                        should_emit = (
                            current_row.stage_type != last_stage_type
                            or tracker.detect_change(snap)
                            or current_row.status != last_status
                        )

                        if should_emit:
                            event = StageProgressEvent(
                                stage_type=current_row.stage_type,
                                progress=snap.progress,
                                message=build_status_message(
                                    snap, current_row.status, current_row.error_message
                                ),
                                status=current_row.status,
                                item_complete=snap.last_item_complete,
                                total_items=snap.total_items,
                                completed_items=snap.completed_items,
                                skipped_items=snap.skipped_items,
                                generating_shots=snap.generating_shots,
                            )
                            yield f"data: {event.model_dump_json()}\n\n"
                            tracker.accept(snap)
                            last_status = current_row.status
                            last_stage_type = current_row.stage_type

                        if (
                            not await self._has_active_pipeline_background_task(project_id)
                            and running_row is None
                        ):
                            break

                        await asyncio.sleep(0.5)

                yield "data: [DONE]\n\n"

            return StreamingResponse(
                finalize_event_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        existing_result = await self._execute_with_retry(
            select(StageExecution).where(
                StageExecution.project_id == project_id,
                StageExecution.stage_type == stage_type,
            )
        )
        existing_stage = existing_result.scalar_one_or_none()
        task_key = (project_id, stage_type)
        async with _STAGE_BACKGROUND_TASKS_LOCK:
            active_task = _STAGE_BACKGROUND_TASKS.get(task_key)
            if active_task and active_task.done():
                _STAGE_BACKGROUND_TASKS.pop(task_key, None)
                active_task = None
        has_active_background_task = active_task is not None and not active_task.done()

        def reset_stage_runtime_state(stage_row: StageExecution) -> bool:
            changed = False
            if stage_row.status != StageStatus.PENDING:
                stage_row.status = StageStatus.PENDING
                changed = True
            if stage_row.error_message is not None:
                stage_row.error_message = None
                changed = True
            if stage_row.progress != 0:
                stage_row.progress = 0
                changed = True
            if stage_row.last_item_complete != -1:
                stage_row.last_item_complete = -1
                changed = True
            if stage_row.total_items is not None:
                stage_row.total_items = None
                changed = True
            if stage_row.completed_items is not None:
                stage_row.completed_items = None
                changed = True
            if stage_row.skipped_items is not None:
                stage_row.skipped_items = None
                changed = True
            if isinstance(stage_row.output_data, dict):
                cleaned_output = dict(stage_row.output_data)
                runtime_field_changed = False
                if "progress_message" in cleaned_output:
                    cleaned_output.pop("progress_message", None)
                    runtime_field_changed = True
                if "generating_shots" in cleaned_output:
                    cleaned_output.pop("generating_shots", None)
                    runtime_field_changed = True
                if "warnings" in cleaned_output:
                    cleaned_output.pop("warnings", None)
                    runtime_field_changed = True
                partial_keys = [
                    key for key in cleaned_output.keys() if str(key).startswith("partial_")
                ]
                for key in partial_keys:
                    cleaned_output.pop(key, None)
                    runtime_field_changed = True
                if runtime_field_changed:
                    stage_row.output_data = cleaned_output
                    changed = True
            return changed

        if existing_stage and existing_stage.status == StageStatus.COMPLETED and not force:
            raise ServiceError(400, "Stage already completed. Use force=true to re-run.")

        if (
            existing_stage
            and existing_stage.status == StageStatus.RUNNING
            and not has_active_background_task
        ):
            # Safety net: if stale row is observed between recovery and here, recover inline.
            reset_stage_runtime_state(existing_stage)
            logger.warning(
                "Detected stale RUNNING stage before stream start, reset to PENDING and restart: "
                "project_id=%s stage=%s",
                project_id,
                stage_type.value,
            )
            await self._commit_with_retry()

        should_start = (
            force
            or not existing_stage
            or existing_stage.status != StageStatus.RUNNING
            or not has_active_background_task
        )
        if should_start:
            if existing_stage and reset_stage_runtime_state(existing_stage):
                logger.info(
                    "Reset stage runtime state before (re)start: project_id=%s stage=%s force=%s",
                    project_id,
                    stage_type.value,
                    force,
                )
                await self._commit_with_retry()
            await self._ensure_background_stage_task(
                project_id,
                stage_type,
                parsed_input_data,
                force_restart=force,
            )

        async def event_generator():
            tracker = ProgressChangeTracker()
            last_status: StageStatus | None = None

            async with AsyncSessionLocal() as poll_db:
                while True:
                    try:
                        await poll_db.rollback()
                    except Exception:
                        pass

                    result = await poll_db.execute(
                        select(StageExecution)
                        .where(
                            StageExecution.project_id == project_id,
                            StageExecution.stage_type == stage_type,
                        )
                        .execution_options(populate_existing=True)
                    )
                    stage_row = result.scalar_one_or_none()

                    if not stage_row:
                        await asyncio.sleep(0.5)
                        continue

                    snap = parse_stage_snapshot(stage_row, stage_type)
                    should_emit = tracker.detect_change(snap) or stage_row.status != last_status

                    if should_emit:
                        event_data: dict[str, Any] | None = None
                        output_data = stage_row.output_data
                        if isinstance(output_data, str):
                            try:
                                output_data = json.loads(output_data)
                            except Exception:
                                output_data = None
                        if isinstance(output_data, dict):
                            if stage_type == StageType.RESEARCH:
                                partial_report = output_data.get("partial_report")
                                if isinstance(partial_report, str) and partial_report.strip():
                                    event_data = {
                                        "partial_report": partial_report,
                                    }
                            elif stage_type == StageType.CONTENT:
                                payload: dict[str, Any] = {}
                                partial_title = output_data.get("partial_title")
                                partial_lines = output_data.get("partial_dialogue_lines")
                                partial_content = output_data.get("content")
                                if isinstance(partial_title, str) and partial_title.strip():
                                    payload["partial_title"] = partial_title
                                if isinstance(partial_lines, list):
                                    payload["partial_dialogue_lines"] = partial_lines
                                if isinstance(partial_content, str) and partial_content.strip():
                                    payload["partial_content"] = partial_content
                                if payload:
                                    event_data = payload
                            elif stage_type == StageType.STORYBOARD:
                                partial_shots = output_data.get("partial_storyboard_shots")
                                if isinstance(partial_shots, list):
                                    event_data = {"partial_storyboard_shots": partial_shots}
                            elif stage_type == StageType.FIRST_FRAME_DESC:
                                partial_shots = output_data.get("partial_first_frame_shots")
                                if isinstance(partial_shots, list):
                                    event_data = {"partial_first_frame_shots": partial_shots}
                            elif stage_type == StageType.REFERENCE:
                                payload: dict[str, Any] = {}
                                partial_references = output_data.get("partial_references")
                                if isinstance(partial_references, list):
                                    payload["partial_references"] = partial_references
                                partial_reference_id = output_data.get("partial_reference_id")
                                if (
                                    isinstance(partial_reference_id, str)
                                    and partial_reference_id.strip()
                                ):
                                    payload["partial_reference_id"] = partial_reference_id.strip()
                                partial_reference_description = output_data.get(
                                    "partial_reference_description"
                                )
                                if (
                                    isinstance(partial_reference_description, str)
                                    and partial_reference_description.strip()
                                ):
                                    payload["partial_reference_description"] = (
                                        partial_reference_description
                                    )
                                if payload:
                                    event_data = payload
                            warnings = output_data.get("warnings")
                            if isinstance(warnings, list):
                                warning_texts = [
                                    str(item).strip()
                                    for item in warnings
                                    if isinstance(item, str) and str(item).strip()
                                ]
                                if warning_texts:
                                    payload = (
                                        dict(event_data) if isinstance(event_data, dict) else {}
                                    )
                                    payload["warnings"] = warning_texts
                                    event_data = payload
                        event = StageProgressEvent(
                            stage_type=stage_type,
                            progress=snap.progress,
                            message=build_status_message(
                                snap, stage_row.status, stage_row.error_message
                            ),
                            status=stage_row.status,
                            data=event_data,
                            item_complete=snap.last_item_complete,
                            total_items=snap.total_items,
                            completed_items=snap.completed_items,
                            skipped_items=snap.skipped_items,
                            generating_shots=snap.generating_shots,
                        )
                        yield f"data: {event.model_dump_json()}\n\n"
                        tracker.accept(snap)
                        last_status = stage_row.status

                    if stage_row.status in {
                        StageStatus.COMPLETED,
                        StageStatus.FAILED,
                        StageStatus.SKIPPED,
                    }:
                        break

                    if stage_row.status in {StageStatus.RUNNING, StageStatus.PENDING} and not (
                        await self._has_local_background_task(project_id, stage_type)
                    ):
                        synthetic_error = (
                            stage_row.error_message
                            or "后台任务已结束，但阶段状态未成功写回数据库；通常是数据库、磁盘或临时目录异常"
                        )
                        synthetic_event = StageProgressEvent(
                            stage_type=stage_type,
                            progress=snap.progress,
                            message=build_status_message(
                                snap,
                                StageStatus.FAILED,
                                synthetic_error,
                            ),
                            status=StageStatus.FAILED,
                            item_complete=snap.last_item_complete,
                            total_items=snap.total_items,
                            completed_items=snap.completed_items,
                            skipped_items=snap.skipped_items,
                            generating_shots=snap.generating_shots,
                        )
                        yield f"data: {synthetic_event.model_dump_json()}\n\n"
                        logger.warning(
                            "Stage stream detected missing local background task; emitted synthetic FAILED event: "
                            "project_id=%s stage=%s",
                            project_id,
                            stage_type.value,
                        )
                        break

                    await asyncio.sleep(0.5)

            yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async def _ensure_background_stage_task(
        self,
        project_id: int,
        stage_type: StageType,
        input_data: dict[str, Any] | None,
        force_restart: bool = False,
    ) -> None:
        key = (project_id, stage_type)
        async with _STAGE_BACKGROUND_TASKS_LOCK:
            existing = _STAGE_BACKGROUND_TASKS.get(key)
            if existing and not existing.done():
                if not force_restart:
                    logger.info(
                        "Background stage task already running, reusing: project_id=%s stage=%s",
                        project_id,
                        stage_type.value,
                    )
                    return
                logger.warning(
                    "Force restarting background stage task: project_id=%s stage=%s",
                    project_id,
                    stage_type.value,
                )
                existing.cancel()
                try:
                    await asyncio.wait_for(existing, timeout=2.0)
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
                _STAGE_BACKGROUND_TASKS.pop(key, None)
                stage_task_id = _STAGE_BACKGROUND_TASK_META.pop(key, None)
                if stage_task_id is not None:
                    asyncio.create_task(
                        self._update_stage_task_record(
                            stage_task_id,
                            status=PipelineTaskStatus.CANCELLED,
                            error_message="任务已被强制重启",
                        )
                    )
            if existing and existing.done():
                _STAGE_BACKGROUND_TASKS.pop(key, None)
                _STAGE_BACKGROUND_TASK_META.pop(key, None)

            # Pre-launch duplicate check: ensure no stale RUNNING record in DB
            cutoff = self._now_utc() - _TASK_STALE_TIMEOUT
            dup_result = await self._execute_with_retry(
                select(PipelineTask).where(
                    PipelineTask.project_id == project_id,
                    PipelineTask.stage_type == stage_type,
                    PipelineTask.task_kind == PipelineTaskKind.STAGE,
                    PipelineTask.status == PipelineTaskStatus.RUNNING,
                    PipelineTask.heartbeat_at >= cutoff,
                )
            )
            dup_row = dup_result.scalars().first()
            if dup_row is not None:
                logger.warning(
                    "Pre-launch: found active DB task record, skip duplicate launch: "
                    "project_id=%s stage=%s task_id=%s",
                    project_id,
                    stage_type.value,
                    dup_row.id,
                )
                return

            task_name = f"stage-bg-{project_id}-{stage_type.value}"
            stage_task_id = await self._create_stage_task_record(
                project_id=project_id,
                stage_type=stage_type,
                worker_name=task_name,
            )

            task = asyncio.create_task(
                self._run_stage_in_background(
                    project_id,
                    stage_type,
                    input_data,
                    stage_task_id,
                ),
                name=task_name,
            )
            _STAGE_BACKGROUND_TASKS[key] = task
            _STAGE_BACKGROUND_TASK_META[key] = stage_task_id
            logger.info(
                "Started background stage task: project_id=%s stage=%s task=%s",
                project_id,
                stage_type.value,
                task.get_name(),
            )

            def _cleanup(
                done_task: asyncio.Task[None], task_key: tuple[int, StageType] = key
            ) -> None:
                current = _STAGE_BACKGROUND_TASKS.get(task_key)
                if current is done_task:
                    _STAGE_BACKGROUND_TASKS.pop(task_key, None)
                    task_id = _STAGE_BACKGROUND_TASK_META.pop(task_key, None)
                else:
                    task_id = None
                try:
                    done_task.result()
                except asyncio.CancelledError:
                    logger.warning(
                        "Background stage task cancelled: project_id=%s stage=%s",
                        task_key[0],
                        task_key[1].value,
                    )
                    if task_id is not None:
                        asyncio.create_task(
                            self._update_stage_task_record(
                                task_id,
                                status=PipelineTaskStatus.CANCELLED,
                                error_message="后台任务取消",
                            )
                        )
                except Exception:
                    logger.exception(
                        "Background stage task crashed: project_id=%s stage=%s",
                        task_key[0],
                        task_key[1].value,
                    )
                    if task_id is not None:
                        asyncio.create_task(
                            self._update_stage_task_record(
                                task_id,
                                status=PipelineTaskStatus.FAILED,
                                error_message="后台任务异常退出",
                            )
                        )

            task.add_done_callback(_cleanup)

    async def _run_stage_in_background(
        self,
        project_id: int,
        stage_type: StageType,
        input_data: dict[str, Any] | None,
        stage_task_id: int,
    ) -> None:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()
            if not project:
                logger.warning(
                    "Skip background stage run because project is missing: project_id=%s stage=%s",
                    project_id,
                    stage_type.value,
                )
                await self._update_stage_task_record(
                    stage_task_id,
                    status=PipelineTaskStatus.FAILED,
                    error_message="项目不存在",
                )
                return

            pipeline = PipelineEngine(db, project)
            async for _ in pipeline.run_stage(stage_type, input_data):
                pass
            stage_row = await pipeline.get_or_create_stage(stage_type)
            final_status = PipelineTaskStatus.COMPLETED
            if stage_row.status == StageStatus.FAILED:
                final_status = PipelineTaskStatus.FAILED
            elif stage_row.status == StageStatus.SKIPPED:
                final_status = PipelineTaskStatus.SKIPPED
            await self._update_stage_task_record(
                stage_task_id,
                status=final_status,
                error_message=stage_row.error_message,
            )

    async def _has_active_background_task(self, project_id: int, stage_type: StageType) -> bool:
        key = (project_id, stage_type)
        async with _STAGE_BACKGROUND_TASKS_LOCK:
            task = _STAGE_BACKGROUND_TASKS.get(key)
            if task and task.done():
                _STAGE_BACKGROUND_TASKS.pop(key, None)
                _STAGE_BACKGROUND_TASK_META.pop(key, None)
                task = None
            if task is not None and not task.done():
                return True
        cutoff = self._now_utc() - _TASK_STALE_TIMEOUT
        result = await self._execute_with_retry(
            select(PipelineTask).where(
                PipelineTask.project_id == project_id,
                PipelineTask.stage_type == stage_type,
                PipelineTask.task_kind == PipelineTaskKind.STAGE,
                PipelineTask.status == PipelineTaskStatus.RUNNING,
                PipelineTask.heartbeat_at >= cutoff,
            )
        )
        if result.scalar_one_or_none() is not None:
            return True
        return await self._has_active_pipeline_background_task(project_id)

    @staticmethod
    async def _has_local_background_task(project_id: int, stage_type: StageType) -> bool:
        key = (project_id, stage_type)
        async with _STAGE_BACKGROUND_TASKS_LOCK:
            task = _STAGE_BACKGROUND_TASKS.get(key)
            if task and task.done():
                _STAGE_BACKGROUND_TASKS.pop(key, None)
                _STAGE_BACKGROUND_TASK_META.pop(key, None)
                task = None
            if task is not None and not task.done():
                return True

        async with _PIPELINE_BACKGROUND_TASKS_LOCK:
            pipeline_task = _PIPELINE_BACKGROUND_TASKS.get(project_id)
            if pipeline_task and pipeline_task.done():
                _PIPELINE_BACKGROUND_TASKS.pop(project_id, None)
                _PIPELINE_BACKGROUND_TASK_META.pop(project_id, None)
                pipeline_task = None
            if pipeline_task is not None and not pipeline_task.done():
                return True

        return False

    async def _has_active_pipeline_background_task(self, project_id: int) -> bool:
        async with _PIPELINE_BACKGROUND_TASKS_LOCK:
            task = _PIPELINE_BACKGROUND_TASKS.get(project_id)
            if task and task.done():
                _PIPELINE_BACKGROUND_TASKS.pop(project_id, None)
                _PIPELINE_BACKGROUND_TASK_META.pop(project_id, None)
                task = None
            if task is not None and not task.done():
                return True

        cutoff = self._now_utc() - _TASK_STALE_TIMEOUT
        result = await self._execute_with_retry(
            select(PipelineRun).where(
                PipelineRun.project_id == project_id,
                PipelineRun.status == PipelineRunStatus.RUNNING,
                PipelineRun.heartbeat_at >= cutoff,
            )
        )
        return result.scalar_one_or_none() is not None

    async def _recover_stale_running_stages(
        self,
        project_id: int,
        stage_type: StageType | None = None,
    ) -> int:
        query = select(StageExecution).where(
            StageExecution.project_id == project_id,
            StageExecution.status == StageStatus.RUNNING,
        )
        if stage_type is not None:
            query = query.where(StageExecution.stage_type == stage_type)

        result = await self._execute_with_retry(query)
        running_rows = list(result.scalars().all())
        if not running_rows:
            return 0
        if await self._has_active_pipeline_background_task(project_id):
            return 0

        recovered_count = 0
        for row in running_rows:
            if await self._has_active_background_task(project_id, row.stage_type):
                continue
            row.status = StageStatus.PENDING
            row.error_message = None
            row.progress = 0
            row.last_item_complete = -1
            row.total_items = None
            row.completed_items = None
            row.skipped_items = None
            if isinstance(row.output_data, dict):
                cleaned_output = dict(row.output_data)
                cleaned_output.pop("progress_message", None)
                cleaned_output.pop("generating_shots", None)
                for key in list(cleaned_output.keys()):
                    if str(key).startswith("partial_"):
                        cleaned_output.pop(key, None)
                row.output_data = cleaned_output
            recovered_count += 1
            logger.warning(
                "Detected stale RUNNING stage without active worker, reset to PENDING: "
                "project_id=%s stage=%s",
                project_id,
                row.stage_type.value,
            )

        if recovered_count:
            await self._commit_with_retry()
            cutoff = self._now_utc() - _TASK_STALE_TIMEOUT
            task_query = select(PipelineTask).where(
                PipelineTask.project_id == project_id,
                PipelineTask.task_kind == PipelineTaskKind.STAGE,
                PipelineTask.status == PipelineTaskStatus.RUNNING,
                PipelineTask.heartbeat_at < cutoff,
            )
            if stage_type is not None:
                task_query = task_query.where(PipelineTask.stage_type == stage_type)
            stale_task_result = await self._execute_with_retry(task_query)
            stale_rows = list(stale_task_result.scalars().all())
            if stale_rows:
                now = self._now_utc()
                for one in stale_rows:
                    one.status = PipelineTaskStatus.FAILED
                    one.finished_at = now
                    one.heartbeat_at = now
                    if not one.error_message:
                        one.error_message = "检测到僵尸任务，已自动标记失败"
                await self._commit_with_retry()
        return recovered_count

    async def _recover_stale_pipeline_runtime(self, project_id: int) -> tuple[int, int]:
        if await self._has_active_pipeline_background_task(project_id):
            return 0, 0
        cutoff = self._now_utc() - _TASK_STALE_TIMEOUT
        run_result = await self._execute_with_retry(
            select(PipelineRun).where(
                PipelineRun.project_id == project_id,
                PipelineRun.status == PipelineRunStatus.RUNNING,
                PipelineRun.heartbeat_at < cutoff,
            )
        )
        stale_runs = list(run_result.scalars().all())

        task_result = await self._execute_with_retry(
            select(PipelineTask).where(
                PipelineTask.project_id == project_id,
                PipelineTask.status == PipelineTaskStatus.RUNNING,
                PipelineTask.heartbeat_at < cutoff,
            )
        )
        stale_tasks = list(task_result.scalars().all())

        if not stale_runs and not stale_tasks:
            return 0, 0

        now = self._now_utc()
        for row in stale_runs:
            row.status = PipelineRunStatus.FAILED
            row.finished_at = now
            row.heartbeat_at = now
            if not row.error_message:
                row.error_message = "检测到僵尸 pipeline 任务，已自动标记失败"

        for row in stale_tasks:
            row.status = PipelineTaskStatus.FAILED
            row.finished_at = now
            row.heartbeat_at = now
            if not row.error_message:
                row.error_message = "检测到僵尸任务，已自动标记失败"

        await self._commit_with_retry()
        return len(stale_runs), len(stale_tasks)

    async def run_pipeline(
        self,
        project_id: int,
        request: PipelineRunRequest,
    ) -> StreamingResponse:
        await self.get_project_or_404(project_id)
        await self._recover_stale_running_stages(project_id)
        await self._recover_stale_pipeline_runtime(project_id)
        try:
            stage_range = stage_registry.resolve_execution_subset(
                from_stage=request.from_stage,
                to_stage=request.to_stage,
            )
        except ValueError as exc:
            raise ServiceError(400, str(exc))
        await self._ensure_background_pipeline_task(
            project_id,
            request.from_stage,
            request.to_stage,
            None,
        )

        async def event_generator():
            tracker = ProgressChangeTracker()
            last_status: StageStatus | None = None
            last_stage_type: StageType | None = None

            async with AsyncSessionLocal() as poll_db:
                while True:
                    try:
                        await poll_db.rollback()
                    except Exception:
                        pass

                    result = await poll_db.execute(
                        select(StageExecution)
                        .where(
                            StageExecution.project_id == project_id,
                            StageExecution.stage_type.in_(stage_range),
                        )
                        .order_by(StageExecution.stage_number)
                        .execution_options(populate_existing=True)
                    )
                    stage_rows = list(result.scalars().all())

                    running_row = next(
                        (s for s in stage_rows if s.status == StageStatus.RUNNING), None
                    )
                    current_row = running_row
                    if current_row is None and stage_rows:
                        current_row = next(
                            (s for s in reversed(stage_rows) if s.status != StageStatus.PENDING),
                            stage_rows[-1],
                        )

                    if not current_row:
                        if not await self._has_active_pipeline_background_task(project_id):
                            break
                        await asyncio.sleep(0.5)
                        continue

                    snap = parse_stage_snapshot(current_row, current_row.stage_type)
                    should_emit = (
                        current_row.stage_type != last_stage_type
                        or tracker.detect_change(snap)
                        or current_row.status != last_status
                    )

                    if should_emit:
                        event = StageProgressEvent(
                            stage_type=current_row.stage_type,
                            progress=snap.progress,
                            message=build_status_message(
                                snap, current_row.status, current_row.error_message
                            ),
                            status=current_row.status,
                            item_complete=snap.last_item_complete,
                            total_items=snap.total_items,
                            completed_items=snap.completed_items,
                            skipped_items=snap.skipped_items,
                            generating_shots=snap.generating_shots,
                        )
                        yield f"data: {event.model_dump_json()}\n\n"
                        tracker.accept(snap)
                        last_status = current_row.status
                        last_stage_type = current_row.stage_type

                    if (
                        not await self._has_active_pipeline_background_task(project_id)
                        and running_row is None
                    ):
                        break

                    await asyncio.sleep(0.5)

            yield "data: [DONE]\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async def cancel_project_tasks(self, project_id: int) -> dict[str, Any]:
        project = await self.get_project_or_404(project_id)
        cancelled_stage_tasks = 0
        cancelled_pipeline_tasks = 0
        tasks_to_wait: list[asyncio.Task[None]] = []
        stage_task_record_ids: list[int] = []
        pipeline_run_ids: list[int] = []

        async with _STAGE_BACKGROUND_TASKS_LOCK:
            for key, task in list(_STAGE_BACKGROUND_TASKS.items()):
                pid, _ = key
                if pid != project_id:
                    continue
                if not task.done():
                    task.cancel()
                    cancelled_stage_tasks += 1
                    tasks_to_wait.append(task)
                _STAGE_BACKGROUND_TASKS.pop(key, None)
                task_id = _STAGE_BACKGROUND_TASK_META.pop(key, None)
                if task_id is not None:
                    stage_task_record_ids.append(task_id)

        async with _PIPELINE_BACKGROUND_TASKS_LOCK:
            pipeline_task = _PIPELINE_BACKGROUND_TASKS.get(project_id)
            if pipeline_task is not None:
                if not pipeline_task.done():
                    pipeline_task.cancel()
                    cancelled_pipeline_tasks += 1
                    tasks_to_wait.append(pipeline_task)
                _PIPELINE_BACKGROUND_TASKS.pop(project_id, None)
                meta = _PIPELINE_BACKGROUND_TASK_META.pop(project_id, None)
                if meta is not None:
                    pipeline_run_ids.append(meta[2])

        for task in tasks_to_wait:
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        for task_id in stage_task_record_ids:
            await self._update_stage_task_record(
                task_id,
                status=PipelineTaskStatus.CANCELLED,
                error_message="任务已手动中断",
            )
        for run_id in pipeline_run_ids:
            await self._update_pipeline_run_record(
                run_id,
                status=PipelineRunStatus.CANCELLED,
                error_message="任务已手动中断",
                finish=True,
            )

        now = self._now_utc()
        stale_run_result = await self._execute_with_retry(
            select(PipelineRun).where(
                PipelineRun.project_id == project_id,
                PipelineRun.status == PipelineRunStatus.RUNNING,
            )
        )
        stale_runs = list(stale_run_result.scalars().all())
        for row in stale_runs:
            row.status = PipelineRunStatus.CANCELLED
            row.error_message = "任务已手动中断"
            row.heartbeat_at = now
            row.finished_at = now

        stale_task_result = await self._execute_with_retry(
            select(PipelineTask).where(
                PipelineTask.project_id == project_id,
                PipelineTask.status.in_([PipelineTaskStatus.PENDING, PipelineTaskStatus.RUNNING]),
            )
        )
        stale_tasks = list(stale_task_result.scalars().all())
        for row in stale_tasks:
            row.status = PipelineTaskStatus.CANCELLED
            row.error_message = "任务已手动中断"
            row.heartbeat_at = now
            row.finished_at = now

        stage_result = await self._execute_with_retry(
            select(StageExecution).where(
                StageExecution.project_id == project_id,
                StageExecution.status == StageStatus.RUNNING,
            )
        )
        running_rows = list(stage_result.scalars().all())
        for row in running_rows:
            row.status = StageStatus.FAILED
            row.error_message = "任务已手动中断"

        project_changed = False
        if project.status == ProjectStatus.RUNNING:
            project.status = ProjectStatus.FAILED
            project.current_stage = None
            project.error_message = "任务已手动中断"
            project_changed = True

        if running_rows or project_changed or stale_runs or stale_tasks:
            await self._commit_with_retry()

        logger.warning(
            "Manual cancel requested: project_id=%s cancelled_stage_tasks=%s cancelled_pipeline_tasks=%s recovered_stages=%s",
            project_id,
            cancelled_stage_tasks,
            cancelled_pipeline_tasks,
            len(running_rows),
        )

        return {
            "success": True,
            "cancelled_stage_tasks": cancelled_stage_tasks,
            "cancelled_pipeline_tasks": cancelled_pipeline_tasks,
            "recovered_running_stages": len(running_rows),
        }

    async def _ensure_background_pipeline_task(
        self,
        project_id: int,
        from_stage: StageType | None,
        to_stage: StageType | None,
        input_data: dict[str, Any] | None,
        force_restart: bool = False,
    ) -> None:
        async with _PIPELINE_BACKGROUND_TASKS_LOCK:
            existing = _PIPELINE_BACKGROUND_TASKS.get(project_id)
            existing_meta = _PIPELINE_BACKGROUND_TASK_META.get(project_id)
            if existing and existing.done():
                _PIPELINE_BACKGROUND_TASKS.pop(project_id, None)
                _PIPELINE_BACKGROUND_TASK_META.pop(project_id, None)
                existing = None
                existing_meta = None

            if existing and not existing.done():
                if existing_meta and existing_meta[:2] != (from_stage, to_stage):
                    raise ServiceError(
                        400, "Pipeline is already running with different stage range"
                    )
                if force_restart:
                    existing.cancel()
                    try:
                        await asyncio.wait_for(existing, timeout=2.0)
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        pass
                    _PIPELINE_BACKGROUND_TASKS.pop(project_id, None)
                    _PIPELINE_BACKGROUND_TASK_META.pop(project_id, None)
                else:
                    logger.info(
                        "Background pipeline task already running, reusing: project_id=%s",
                        project_id,
                    )
                    return

            task_name = f"pipeline-bg-{project_id}"
            run_id = await self._create_pipeline_run_record(
                project_id=project_id,
                from_stage=from_stage,
                to_stage=to_stage,
                worker_name=task_name,
            )
            stage_range = stage_registry.resolve_execution_subset(
                from_stage=from_stage,
                to_stage=to_stage,
            )
            await self._create_pipeline_stage_task_records(
                run_id=run_id,
                project_id=project_id,
                stages=stage_range,
                worker_name=task_name,
            )

            task = asyncio.create_task(
                self._run_pipeline_in_background(
                    project_id,
                    from_stage,
                    to_stage,
                    input_data,
                    run_id,
                    stage_range,
                ),
                name=task_name,
            )
            _PIPELINE_BACKGROUND_TASKS[project_id] = task
            _PIPELINE_BACKGROUND_TASK_META[project_id] = (from_stage, to_stage, run_id)
            logger.info(
                "Started background pipeline task: project_id=%s task=%s from=%s to=%s",
                project_id,
                task.get_name(),
                from_stage.value if from_stage else None,
                to_stage.value if to_stage else None,
            )

            def _cleanup(done_task: asyncio.Task[None], pid: int = project_id) -> None:
                current = _PIPELINE_BACKGROUND_TASKS.get(pid)
                if current is done_task:
                    _PIPELINE_BACKGROUND_TASKS.pop(pid, None)
                    meta = _PIPELINE_BACKGROUND_TASK_META.pop(pid, None)
                    run_id_from_meta = meta[2] if meta else None
                else:
                    run_id_from_meta = None
                try:
                    done_task.result()
                except asyncio.CancelledError:
                    logger.warning("Background pipeline task cancelled: project_id=%s", pid)
                    if run_id_from_meta is not None:
                        asyncio.create_task(
                            self._update_pipeline_run_record(
                                run_id_from_meta,
                                status=PipelineRunStatus.CANCELLED,
                                error_message="后台任务取消",
                                finish=True,
                            )
                        )
                except Exception:
                    logger.exception("Background pipeline task crashed: project_id=%s", pid)
                    if run_id_from_meta is not None:
                        asyncio.create_task(
                            self._update_pipeline_run_record(
                                run_id_from_meta,
                                status=PipelineRunStatus.FAILED,
                                error_message="后台任务异常退出",
                                finish=True,
                            )
                        )

            task.add_done_callback(_cleanup)

    async def _run_pipeline_in_background(
        self,
        project_id: int,
        from_stage: StageType | None,
        to_stage: StageType | None,
        input_data: dict[str, Any] | None,
        run_id: int,
        stage_range: list[StageType],
    ) -> None:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()
            if not project:
                logger.warning(
                    "Skip background pipeline run because project is missing: project_id=%s",
                    project_id,
                )
                await self._update_pipeline_run_record(
                    run_id,
                    status=PipelineRunStatus.FAILED,
                    error_message="项目不存在",
                    finish=True,
                )
                return

            pipeline = PipelineEngine(db, project)
            try:
                last_stage_type: StageType | None = None
                async for _ in pipeline.run_pipeline(
                    from_stage=from_stage,
                    to_stage=to_stage,
                    input_data=input_data,
                ):
                    if project.current_stage is None:
                        continue
                    current_stage = stage_registry.get_stage_type_by_number(project.current_stage)
                    if current_stage is not None and current_stage != last_stage_type:
                        await self._update_pipeline_stage_task_record(
                            run_id=run_id,
                            stage_type=current_stage,
                            status=PipelineTaskStatus.RUNNING,
                        )
                        last_stage_type = current_stage
                    await self._update_pipeline_run_record(
                        run_id,
                        current_stage=current_stage,
                    )
            except asyncio.CancelledError:
                await self._finalize_pipeline_stage_tasks_for_run(
                    run_id=run_id,
                    status=PipelineTaskStatus.CANCELLED,
                    error_message="任务已取消",
                )
                await self._update_pipeline_run_record(
                    run_id,
                    status=PipelineRunStatus.CANCELLED,
                    error_message="任务已取消",
                    finish=True,
                )
                raise
            except Exception as exc:
                await self._finalize_pipeline_stage_tasks_for_run(
                    run_id=run_id,
                    status=PipelineTaskStatus.FAILED,
                    error_message=str(exc),
                )
                await self._update_pipeline_run_record(
                    run_id,
                    status=PipelineRunStatus.FAILED,
                    error_message=str(exc),
                    finish=True,
                )
                raise

            stage_result = await db.execute(
                select(StageExecution)
                .where(
                    StageExecution.project_id == project_id,
                    StageExecution.stage_type.in_(stage_range),
                )
                .order_by(StageExecution.stage_number)
            )
            stage_rows = list(stage_result.scalars().all())
            await self._sync_pipeline_task_records_with_stage_rows(
                run_id=run_id,
                project_id=project_id,
                stage_rows=stage_rows,
            )
            failed_required_stage = next(
                (
                    one
                    for one in stage_rows
                    if one.status == StageStatus.FAILED
                    and not stage_registry.is_optional(one.stage_type)
                ),
                None,
            )
            final_status = (
                PipelineRunStatus.FAILED
                if failed_required_stage is not None
                else PipelineRunStatus.COMPLETED
            )
            final_error = next(
                (
                    one.error_message
                    for one in stage_rows
                    if one.status == StageStatus.FAILED
                    and not stage_registry.is_optional(one.stage_type)
                    and one.error_message
                ),
                None,
            )
            await self._update_pipeline_run_record(
                run_id,
                status=final_status,
                error_message=final_error,
                finish=True,
            )
