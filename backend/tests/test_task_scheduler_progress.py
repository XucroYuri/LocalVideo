import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.project import Project
from app.models.stage import StageExecution, StageStatus, StageType
from app.stages.base import StageResult
from app.stages.task_scheduler import (
    SchedulerSettings,
    SchedulerTaskSpec,
    run_scheduled_tasks,
)


class _Adapter:
    def build_missing_result(self, spec: SchedulerTaskSpec) -> dict:
        return {"item_key": spec.key, "missing": True}

    def build_success_result(self, spec: SchedulerTaskSpec, raw_result: dict) -> dict:
        return {"item_key": spec.key, **raw_result}

    def build_error_result(self, spec: SchedulerTaskSpec, error: str) -> dict:
        return {"item_key": spec.key, "error": error}

    def build_stage_output(
        self,
        current_items: list[dict],
        generating_shots: dict[str, dict[str, int | str]],
        provider_name: str,
        progress_message: str | None,
    ) -> dict:
        return {
            "items": current_items,
            "generating_shots": generating_shots,
            "provider": provider_name,
            "progress_message": progress_message,
        }

    def build_final_data(
        self,
        final_items: list[dict],
        failed_items: list[dict],
    ) -> dict:
        return {"items": final_items, "failed_items": failed_items}

    def build_partial_failure_error(self, failed_items: list[dict]) -> str:
        return str(failed_items)


@pytest.mark.asyncio
async def test_wan2gp_download_status_does_not_push_generation_progress_to_99() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        project = Project(
            title="progress-test",
            video_type="custom",
            output_dir="/tmp/localvideo-progress-test",
            config={},
        )
        session.add(project)
        await session.flush()

        stage = StageExecution(
            project_id=project.id,
            project=project,
            stage_type=StageType.FRAME,
            stage_number=7,
            status=StageStatus.RUNNING,
            input_data={"only_shot_index": 13},
        )
        session.add(stage)
        await session.commit()

        snapshots: dict[str, tuple[int, int, str | None]] = {}

        async def _generate_single(
            spec: SchedulerTaskSpec,
            progress_callback,
            status_callback,
        ) -> dict:
            await status_callback("模型下载中... flux2-dev-nvfp4-mixed.safetensors (99%)")
            download_state = (stage.output_data or {}).get("generating_shots", {}).get(spec.key, {})
            snapshots["after_download"] = (
                int(download_state.get("progress", 0) or 0),
                int(stage.progress or 0),
                (stage.output_data or {}).get("progress_message"),
            )

            await status_callback("模型加载中...")
            await status_callback("生成中...")
            await progress_callback(1)
            generation_state = (
                (stage.output_data or {}).get("generating_shots", {}).get(spec.key, {})
            )
            snapshots["after_generation"] = (
                int(generation_state.get("progress", 0) or 0),
                int(stage.progress or 0),
                (stage.output_data or {}).get("progress_message"),
            )
            return {"url": "/tmp/frame.png"}

        result = await run_scheduled_tasks(
            db=session,
            stage=stage,
            task_specs=[SchedulerTaskSpec(index=0, key="0")],
            all_results=[None],
            adapter=_Adapter(),
            settings=SchedulerSettings(
                provider_name="wan2gp",
                max_concurrency=1,
                allow_batch=False,
            ),
            is_batch_eligible=None,
            is_missing=lambda spec: False,
            generate_single=_generate_single,
        )

    await engine.dispose()

    assert isinstance(result, StageResult)
    assert result.success is True
    assert snapshots["after_download"] == (
        1,
        1,
        "模型下载中... flux2-dev-nvfp4-mixed.safetensors (99%)",
    )
    assert snapshots["after_generation"] == (
        1,
        1,
        "生成中...",
    )


@pytest.mark.asyncio
async def test_non_batch_scheduler_only_exposes_current_running_task() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        project = Project(
            title="current-task-only",
            video_type="custom",
            output_dir="/tmp/localvideo-current-task-only",
            config={},
        )
        session.add(project)
        await session.flush()

        stage = StageExecution(
            project_id=project.id,
            project=project,
            stage_type=StageType.FRAME,
            stage_number=7,
            status=StageStatus.RUNNING,
        )
        session.add(stage)
        await session.commit()

        snapshots: dict[str, list[str]] = {}

        async def _generate_single(
            spec: SchedulerTaskSpec,
            progress_callback,
            status_callback,  # noqa: ARG001
        ) -> dict:
            current_keys = sorted(((stage.output_data or {}).get("generating_shots") or {}).keys())
            snapshots[f"task_{spec.key}_start"] = current_keys
            await progress_callback(5)
            current_keys_after_progress = sorted(
                ((stage.output_data or {}).get("generating_shots") or {}).keys()
            )
            snapshots[f"task_{spec.key}_progress"] = current_keys_after_progress
            return {"url": f"/tmp/frame_{spec.key}.png"}

        result = await run_scheduled_tasks(
            db=session,
            stage=stage,
            task_specs=[
                SchedulerTaskSpec(index=0, key="0"),
                SchedulerTaskSpec(index=1, key="1"),
            ],
            all_results=[None, None],
            adapter=_Adapter(),
            settings=SchedulerSettings(
                provider_name="wan2gp",
                max_concurrency=1,
                allow_batch=False,
            ),
            is_batch_eligible=None,
            is_missing=lambda spec: False,
            generate_single=_generate_single,
        )

    await engine.dispose()

    assert isinstance(result, StageResult)
    assert result.success is True
    assert snapshots["task_0_start"] == ["0"]
    assert snapshots["task_0_progress"] == ["0"]
    assert snapshots["task_1_start"] == ["1"]
    assert snapshots["task_1_progress"] == ["1"]
