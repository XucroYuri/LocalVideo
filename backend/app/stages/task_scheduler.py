import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.concurrent import ConcurrentProgress, TaskItem, TaskResult, run_concurrent_tasks
from app.models.stage import StageExecution

from ._wan2gp_progress import extract_runtime_percent, resolve_runtime_status
from .base import StageResult

logger = logging.getLogger(__name__)

TSpec = TypeVar("TSpec")
TRawResult = TypeVar("TRawResult")


def _is_download_status(message: str | None) -> bool:
    return bool(message and message.startswith("模型下载中"))


def _is_loading_status(message: str | None) -> bool:
    return bool(message and message.startswith("模型加载中"))


def _is_non_generation_runtime_status(message: str | None) -> bool:
    return _is_download_status(message) or _is_loading_status(message)


def _quantize_running_progress(value: float) -> int:
    clamped = max(0.0, min(99.0, value))
    if clamped <= 0:
        return 0
    return max(1, int(clamped))


@dataclass
class SchedulerTaskSpec:
    index: int
    key: str
    skip: bool = False
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class SchedulerSettings:
    provider_name: str
    max_concurrency: int
    allow_batch: bool = True
    batch_min_items: int = 2
    fail_on_partial: bool = True
    stop_on_error: bool = False
    default_start_message: str | None = None


class SchedulerAdapter(Protocol[TSpec]):
    def build_missing_result(self, spec: TSpec) -> dict[str, Any]: ...

    def build_success_result(self, spec: TSpec, raw_result: Any) -> dict[str, Any]: ...

    def build_error_result(self, spec: TSpec, error: str) -> dict[str, Any]: ...

    def build_stage_output(
        self,
        current_items: list[dict[str, Any]],
        generating_shots: dict[str, dict[str, Any]],
        provider_name: str,
        progress_message: str | None,
    ) -> dict[str, Any]: ...

    def build_final_data(
        self,
        final_items: list[dict[str, Any]],
        failed_items: list[dict[str, Any]],
    ) -> dict[str, Any]: ...

    def build_partial_failure_error(self, failed_items: list[dict[str, Any]]) -> str: ...


def _recompute_stage_progress(
    stage: StageExecution,
    generating_shots: dict[str, dict[str, Any]],
    *,
    completed_count: int | None = None,
) -> int:
    total = stage.total_items or 0
    if total <= 0:
        return 99
    completed = completed_count if completed_count is not None else (stage.completed_items or 0)
    in_progress = sum(
        ((shot.get("progress", 0) or 0) / 100.0)
        for shot in generating_shots.values()
        if isinstance(shot, dict)
    )
    return _quantize_running_progress(((completed + in_progress) / total) * 99)


def _collect_failed_items(results: list[TaskResult[dict[str, Any]]]) -> list[dict[str, Any]]:
    failed_items: list[dict[str, Any]] = []
    for result in results:
        if result.success:
            continue
        result_error = result.error
        if not result_error and isinstance(result.data, dict):
            result_error = str(result.data.get("error") or "Unknown error")

        item_key = None
        if isinstance(result.data, dict):
            for key in ("id", "shot_index", "item_key"):
                if key not in result.data:
                    continue
                value = result.data.get(key)
                if value is None or value == "":
                    continue
                item_key = value
                break

        failed_items.append(
            {
                "item_index": result.index,
                "item_key": item_key,
                "error": result_error or "Unknown error",
            }
        )
    return failed_items


async def run_scheduled_tasks(
    *,
    db: AsyncSession,
    stage: StageExecution,
    task_specs: list[TSpec],
    all_results: list[dict[str, Any] | None],
    adapter: SchedulerAdapter[TSpec],
    settings: SchedulerSettings,
    is_batch_eligible: Callable[[TSpec], bool] | None,
    is_missing: Callable[[TSpec], bool],
    generate_single: Callable[
        [TSpec, Callable[[int], Awaitable[None]], Callable[[str], Awaitable[None]]],
        Awaitable[TRawResult],
    ],
    generate_batch: Callable[
        [
            list[TSpec],
            Callable[[str, int, TRawResult | None], Awaitable[None]],
            Callable[[str], Awaitable[None]],
        ],
        Awaitable[dict[str, TRawResult]],
    ]
    | None = None,
) -> StageResult:
    provider_name = settings.provider_name
    db_lock = asyncio.Lock()
    runtime_commit_interval_seconds = 0.25
    last_runtime_commit_at = 0.0

    to_generate_specs = [spec for spec in task_specs if not spec.skip]
    to_generate_count = len(to_generate_specs)
    skipped_count = sum(1 for spec in task_specs if spec.skip)

    batch_specs: list[TSpec] = []
    can_use_batch = (
        settings.allow_batch
        and generate_batch is not None
        and to_generate_count >= settings.batch_min_items
    )
    if can_use_batch:
        if is_batch_eligible is None:
            batch_specs = list(to_generate_specs)
        else:
            batch_specs = [spec for spec in to_generate_specs if is_batch_eligible(spec)]
        can_use_batch = len(batch_specs) >= settings.batch_min_items

    if settings.default_start_message is not None:
        runtime_status_message = settings.default_start_message
    else:
        runtime_status_message: str | None = (
            "准备中..."
            if provider_name == "wan2gp" and to_generate_count > 0
            else ("启动中..." if to_generate_count > 0 else None)
        )

    if can_use_batch:
        first_spec = batch_specs[0] if batch_specs else None
        initial_generating_shots = (
            {first_spec.key: {"status": "pending", "progress": 0}} if first_spec else {}
        )
    else:
        # Non-batch mode should only expose tasks that are actively running.
        # If we pre-seed all pending tasks here, the frontend treats every pending
        # shot as "current" and emits warnings too early.
        initial_generating_shots = {}

    stage.total_items = to_generate_count
    stage.completed_items = 0
    stage.skipped_items = skipped_count
    stage.output_data = adapter.build_stage_output(
        [item for item in all_results if item is not None],
        initial_generating_shots,
        provider_name,
        runtime_status_message,
    )
    flag_modified(stage, "output_data")
    await db.commit()
    last_runtime_commit_at = time.monotonic()

    async def commit_stage_state(*, force: bool = False) -> bool:
        nonlocal last_runtime_commit_at
        now = time.monotonic()
        if not force and (now - last_runtime_commit_at) < runtime_commit_interval_seconds:
            return False
        flag_modified(stage, "output_data")
        await db.commit()
        last_runtime_commit_at = now
        return True

    async def update_runtime_status(message: str) -> None:
        nonlocal runtime_status_message
        next_status = resolve_runtime_status(runtime_status_message, message)
        if not next_status or next_status == runtime_status_message:
            return

        runtime_status_message = next_status
        async with db_lock:
            generating_shots = (
                stage.output_data.get("generating_shots", {}) if stage.output_data else {}
            )
            runtime_percent = extract_runtime_percent(next_status)
            if (
                runtime_percent is not None
                and generating_shots
                and not _is_non_generation_runtime_status(next_status)
            ):
                for shot_key, shot_state in list(generating_shots.items()):
                    if not isinstance(shot_state, dict):
                        shot_state = {"status": "generating", "progress": 0}
                    current_progress = int(shot_state.get("progress", 0) or 0)
                    shot_state["status"] = "generating"
                    shot_state["progress"] = max(current_progress, runtime_percent)
                    generating_shots[shot_key] = shot_state
                stage.progress = _recompute_stage_progress(stage, generating_shots)

            stage.output_data = adapter.build_stage_output(
                [item for item in all_results if item is not None],
                generating_shots,
                provider_name,
                runtime_status_message,
            )
            await commit_stage_state()

    batch_failed_items: list[dict[str, Any]] = []
    batch_success_count = 0
    batched_task_keys: set[str] = set()

    if can_use_batch and generate_batch is not None:
        spec_by_key = {spec.key: spec for spec in batch_specs}
        pending_task_keys = [spec.key for spec in batch_specs]
        succeeded_task_keys: set[str] = set()
        active_task_key: str | None = pending_task_keys[0] if pending_task_keys else None

        def _completed_snapshot() -> list[dict[str, Any]]:
            return [item for item in all_results if item is not None]

        def _recompute_batch(generating_shots: dict[str, dict[str, Any]]) -> int:
            total = to_generate_count
            if total <= 0:
                return 99
            in_progress = sum(
                (shot.get("progress", 0) or 0) / 100.0 for shot in generating_shots.values()
            )
            return _quantize_running_progress(
                (((len(succeeded_task_keys)) + in_progress) / total) * 99
            )

        async def on_batch_progress(
            task_key: str, progress: int, raw_result: TRawResult | None
        ) -> None:
            nonlocal active_task_key
            spec = spec_by_key.get(task_key)
            if spec is None:
                return

            async with db_lock:
                generating_shots: dict[str, dict[str, Any]] = {}
                if raw_result is not None:
                    succeeded_task_keys.add(task_key)
                    all_results[spec.index] = adapter.build_success_result(spec, raw_result)
                    stage.last_item_complete = spec.index
                    if task_key in pending_task_keys:
                        pending_task_keys.remove(task_key)
                    active_task_key = pending_task_keys[0] if pending_task_keys else None

                    if active_task_key:
                        base_progress = extract_runtime_percent(runtime_status_message) or 0
                        generating_shots[active_task_key] = {
                            "status": "pending",
                            "progress": max(0, min(99, int(base_progress))),
                        }
                else:
                    active_task_key = task_key
                    generating_shots[task_key] = {
                        "status": "generating",
                        "progress": max(0, min(99, int(progress))),
                    }

                stage.progress = _recompute_batch(generating_shots)
                stage.total_items = to_generate_count
                stage.completed_items = len(succeeded_task_keys)
                stage.skipped_items = skipped_count
                stage.output_data = adapter.build_stage_output(
                    _completed_snapshot(),
                    generating_shots,
                    provider_name,
                    runtime_status_message,
                )
                await commit_stage_state(force=raw_result is not None)

        async def on_batch_status(message: str) -> None:
            nonlocal active_task_key
            await update_runtime_status(message)
            runtime_percent = extract_runtime_percent(message)

            async with db_lock:
                if not active_task_key and pending_task_keys:
                    active_task_key = pending_task_keys[0]

                generating_shots: dict[str, dict[str, Any]] = {}
                active_spec = spec_by_key.get(active_task_key) if active_task_key else None
                if active_spec:
                    current_progress = 0
                    if stage.output_data and isinstance(
                        stage.output_data.get("generating_shots"), dict
                    ):
                        current = stage.output_data["generating_shots"].get(active_spec.key)
                        if isinstance(current, dict):
                            current_progress = int(current.get("progress", 0) or 0)
                    if runtime_percent is not None and not _is_non_generation_runtime_status(
                        message
                    ):
                        current_progress = max(current_progress, runtime_percent)
                    generating_shots[active_spec.key] = {
                        "status": "generating",
                        "progress": max(0, min(99, int(current_progress))),
                    }

                if generating_shots:
                    stage.progress = _recompute_batch(generating_shots)
                    stage.output_data = adapter.build_stage_output(
                        _completed_snapshot(),
                        generating_shots,
                        provider_name,
                        message,
                    )
                    await commit_stage_state()

        try:
            batch_results = await generate_batch(batch_specs, on_batch_progress, on_batch_status)
        except Exception as e:  # noqa: BLE001
            return StageResult(success=False, error=str(e))

        success_count = 0
        for spec in batch_specs:
            raw = batch_results.get(spec.key)
            if raw is not None:
                success_count += 1
                all_results[spec.index] = adapter.build_success_result(spec, raw)
            else:
                error_text = "Batch run did not return output for this item"
                all_results[spec.index] = adapter.build_error_result(spec, error_text)
                batch_failed_items.append(
                    {
                        "item_key": spec.key,
                        "item_index": spec.index,
                        "error": error_text,
                    }
                )

        batch_success_count = success_count
        batched_task_keys = {spec.key for spec in batch_specs}
        final_items = [item for item in all_results if item is not None]
        total = to_generate_count
        stage.progress = int((success_count / total) * 99) if total > 0 else 99
        stage.total_items = total
        stage.completed_items = success_count
        stage.skipped_items = skipped_count
        stage.output_data = adapter.build_stage_output(final_items, {}, provider_name, None)
        await commit_stage_state(force=True)

        remaining_generate_specs = [
            spec for spec in to_generate_specs if spec.key not in batched_task_keys
        ]
        if not remaining_generate_specs:
            if settings.fail_on_partial and batch_failed_items:
                return StageResult(
                    success=False,
                    error=adapter.build_partial_failure_error(batch_failed_items),
                    data=adapter.build_final_data(final_items, batch_failed_items),
                )
            return StageResult(
                success=True,
                data=adapter.build_final_data(final_items, batch_failed_items),
            )

        if settings.fail_on_partial and batch_failed_items and settings.stop_on_error:
            return StageResult(
                success=False,
                error=adapter.build_partial_failure_error(batch_failed_items),
                data=adapter.build_final_data(final_items, batch_failed_items),
            )

    completed_offset = batch_success_count
    remaining_task_specs = [
        spec for spec in task_specs if spec.skip or spec.key not in batched_task_keys
    ]
    spec_by_index = {spec.index: spec for spec in remaining_task_specs}

    async def run_single(item: TaskItem[TSpec]) -> TaskResult[dict[str, Any]]:
        nonlocal runtime_status_message
        spec = item.data
        if is_missing(spec):
            return TaskResult(
                index=item.index, success=True, data=adapter.build_missing_result(spec)
            )

        async with db_lock:
            generating_shots = (
                stage.output_data.get("generating_shots", {}) if stage.output_data else {}
            )
            shot_state = generating_shots.get(spec.key, {"status": "pending", "progress": 0})
            shot_state["status"] = "generating"
            shot_state["progress"] = max(int(shot_state.get("progress", 0) or 0), 1)
            generating_shots[spec.key] = shot_state
            stage.progress = _recompute_stage_progress(stage, generating_shots)
            stage.output_data = adapter.build_stage_output(
                [item for item in all_results if item is not None],
                generating_shots,
                provider_name,
                runtime_status_message,
            )
            await commit_stage_state(force=True)

        async def progress_callback(value: int) -> None:
            nonlocal runtime_status_message
            async with db_lock:
                generating_shots = (
                    stage.output_data.get("generating_shots", {}) if stage.output_data else {}
                )
                shot_state = generating_shots.get(spec.key, {"status": "generating", "progress": 0})
                next_progress = max(0, min(100, int(value)))
                current_progress = int(shot_state.get("progress", 0) or 0)
                shot_state["status"] = "generating"
                shot_state["progress"] = max(current_progress, next_progress)
                generating_shots[spec.key] = shot_state

                if provider_name != "wan2gp" and runtime_status_message in (
                    None,
                    "",
                    "启动中...",
                    "准备中...",
                ):
                    runtime_status_message = "生成中..."

                stage.progress = _recompute_stage_progress(stage, generating_shots)
                stage.output_data = adapter.build_stage_output(
                    [item for item in all_results if item is not None],
                    generating_shots,
                    provider_name,
                    runtime_status_message,
                )
                await commit_stage_state()

        try:
            raw_result = await generate_single(spec, progress_callback, update_runtime_status)
            return TaskResult(
                index=item.index,
                success=True,
                data=adapter.build_success_result(spec, raw_result),
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("[TaskScheduler] Failed item index=%s key=%s", spec.index, spec.key)
            error_text = str(e)
            return TaskResult(
                index=item.index,
                success=False,
                data=adapter.build_error_result(spec, error_text),
                error=error_text,
            )

    async def on_complete(result: TaskResult[dict[str, Any]], progress: ConcurrentProgress) -> None:
        spec = spec_by_index.get(result.index)
        async with db_lock:
            if result.data is not None:
                all_results[result.index] = result.data

            generating_shots = (
                stage.output_data.get("generating_shots", {}) if stage.output_data else {}
            )
            if spec:
                generating_shots.pop(spec.key, None)

            stage.last_item_complete = result.index
            stage.total_items = to_generate_count
            stage.completed_items = completed_offset + progress.completed
            stage.skipped_items = skipped_count
            stage.progress = _recompute_stage_progress(
                stage,
                generating_shots,
                completed_count=completed_offset + progress.completed,
            )
            stage.output_data = adapter.build_stage_output(
                [item for item in all_results if item is not None],
                generating_shots,
                provider_name,
                runtime_status_message,
            )
            await commit_stage_state(force=True)

    task_items = [
        TaskItem(index=spec.index, data=spec, skip=spec.skip) for spec in remaining_task_specs
    ]
    results, _ = await run_concurrent_tasks(
        items=task_items,
        task_fn=run_single,
        max_concurrency=settings.max_concurrency,
        on_complete=on_complete,
        stop_on_error=settings.stop_on_error,
    )

    final_items = [item for item in all_results if item is not None]
    failed_items = batch_failed_items + _collect_failed_items(results)
    if settings.fail_on_partial and failed_items:
        return StageResult(
            success=False,
            error=adapter.build_partial_failure_error(failed_items),
            data=adapter.build_final_data(final_items, failed_items),
        )
    return StageResult(success=True, data=adapter.build_final_data(final_items, failed_items))
