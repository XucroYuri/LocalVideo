import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.providers import get_image_provider
from app.stages.common.log_utils import log_stage_separator

from ._asset_swap import build_temporary_output_path, cleanup_temp_file, replace_generated_file
from ._visual_prompt import ensure_no_text_overlay_requirement, log_full_generation_prompt
from .base import StageResult
from .task_scheduler import SchedulerSettings, run_scheduled_tasks

logger = logging.getLogger(__name__)


@dataclass
class ImageTaskSpec:
    index: int
    key: str
    prompt: str
    output_path: Path
    skip: bool = False
    payload: dict[str, Any] = field(default_factory=dict)
    reference_images: list[Path] | None = None


@dataclass
class ImageTaskRunSettings:
    provider_name: str
    image_provider: Any
    max_concurrency: int
    provider_kwargs: dict[str, Any] | None = None
    image_aspect_ratio: str | None = None
    image_size: str | None = None
    image_resolution: str | None = None
    force_regenerate: bool = False
    allow_wan2gp_batch: bool = True
    fail_on_partial: bool = True


class ImageTaskAdapter(Protocol):
    def build_missing_prompt_result(self, spec: ImageTaskSpec) -> dict[str, Any]: ...

    def build_success_result(self, spec: ImageTaskSpec, file_path: str) -> dict[str, Any]: ...

    def build_error_result(self, spec: ImageTaskSpec, error: str) -> dict[str, Any]: ...

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


class _SchedulerAdapter:
    def __init__(self, adapter: ImageTaskAdapter):
        self.adapter = adapter

    def build_missing_result(self, spec: ImageTaskSpec) -> dict[str, Any]:
        return self.adapter.build_missing_prompt_result(spec)

    def build_success_result(self, spec: ImageTaskSpec, raw_result: Any) -> dict[str, Any]:
        return self.adapter.build_success_result(spec, str(raw_result))

    def build_error_result(self, spec: ImageTaskSpec, error: str) -> dict[str, Any]:
        return self.adapter.build_error_result(spec, error)

    def build_stage_output(
        self,
        current_items: list[dict[str, Any]],
        generating_shots: dict[str, dict[str, Any]],
        provider_name: str,
        progress_message: str | None,
    ) -> dict[str, Any]:
        return self.adapter.build_stage_output(
            current_items,
            generating_shots,
            provider_name,
            progress_message,
        )

    def build_final_data(
        self,
        final_items: list[dict[str, Any]],
        failed_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self.adapter.build_final_data(final_items, failed_items)

    def build_partial_failure_error(self, failed_items: list[dict[str, Any]]) -> str:
        return self.adapter.build_partial_failure_error(failed_items)


async def run_image_tasks(
    db: AsyncSession,
    stage,
    task_specs: list[ImageTaskSpec],
    all_results: list[dict[str, Any] | None],
    adapter: ImageTaskAdapter,
    settings: ImageTaskRunSettings,
) -> StageResult:
    provider_name = settings.provider_name
    image_provider = settings.image_provider
    batch_capable = (
        settings.allow_wan2gp_batch
        and provider_name == "wan2gp"
        and callable(getattr(image_provider, "generate_batch", None))
        and not any(
            str(spec.payload.get("wan2gp_image_preset_override") or "").strip()
            for spec in task_specs
        )
    )

    async def generate_single(
        spec: ImageTaskSpec,
        progress_callback,
        status_callback,
    ) -> str:
        task_image_provider = image_provider
        effective_prompt = ensure_no_text_overlay_requirement(spec.prompt)
        override_preset = str(spec.payload.get("wan2gp_image_preset_override") or "").strip()
        if provider_name == "wan2gp" and override_preset and settings.provider_kwargs:
            task_provider_kwargs = dict(settings.provider_kwargs)
            task_provider_kwargs["image_preset"] = override_preset
            override_inference_steps = spec.payload.get("wan2gp_image_inference_steps_override")
            if override_inference_steps is not None:
                task_provider_kwargs["image_inference_steps"] = override_inference_steps
            task_image_provider = get_image_provider("wan2gp", **task_provider_kwargs)

        tmp_output_path = build_temporary_output_path(spec.output_path)
        log_stage_separator(logger)
        logger.info(
            "[Image][Input] provider=%s task=%s index=%d output=%s",
            provider_name,
            spec.key,
            spec.index,
            str(spec.output_path),
        )
        log_full_generation_prompt(logger, "[Image][Input] prompt:", effective_prompt)
        if spec.reference_images:
            logger.info(
                "[Image][Input] reference_images=%s",
                [str(path) for path in spec.reference_images],
            )
        if provider_name == "wan2gp":
            logger.info("[Image][Input] resolution=%s", settings.image_resolution)
        else:
            logger.info(
                "[Image][Input] aspect_ratio=%s image_size=%s",
                settings.image_aspect_ratio,
                settings.image_size,
            )
        log_stage_separator(logger)

        kwargs: dict[str, Any] = {
            "prompt": effective_prompt,
            "output_path": tmp_output_path,
            "progress_callback": progress_callback,
        }
        if spec.reference_images:
            kwargs["reference_images"] = spec.reference_images

        if provider_name == "wan2gp":
            kwargs["resolution"] = settings.image_resolution
            kwargs["status_callback"] = status_callback
        else:
            kwargs["aspect_ratio"] = settings.image_aspect_ratio
            kwargs["image_size"] = settings.image_size

        try:
            result = await task_image_provider.generate(**kwargs)
            final_path = replace_generated_file(Path(str(result.file_path)), spec.output_path)
        finally:
            cleanup_temp_file(tmp_output_path)
        logger.info(
            "[Image][Output] provider=%s task=%s index=%d file_path=%s",
            provider_name,
            spec.key,
            spec.index,
            str(final_path),
        )
        return str(final_path)

    async def generate_batch(
        specs: list[ImageTaskSpec],
        progress_callback,
        status_callback,
    ) -> dict[str, str]:
        from app.providers.image.wan2gp import Wan2GPBatchTask

        batch_tasks: list[Wan2GPBatchTask] = []
        spec_by_key = {spec.key: spec for spec in specs}
        temp_output_by_task: dict[str, Path] = {}
        finalized_output_by_task: dict[str, str] = {}
        for spec in specs:
            effective_prompt = ensure_no_text_overlay_requirement(spec.prompt)
            temp_output_path = build_temporary_output_path(spec.output_path)
            temp_output_by_task[spec.key] = temp_output_path
            log_stage_separator(logger)
            logger.info(
                "[Image][Batch][Input] provider=%s task=%s index=%d output=%s",
                provider_name,
                spec.key,
                spec.index,
                str(spec.output_path),
            )
            log_full_generation_prompt(logger, "[Image][Batch][Input] prompt:", effective_prompt)
            if spec.reference_images:
                logger.info(
                    "[Image][Batch][Input] reference_images=%s",
                    [str(path) for path in spec.reference_images],
                )
            log_stage_separator(logger)
            batch_tasks.append(
                Wan2GPBatchTask(
                    task_id=spec.key,
                    prompt=effective_prompt,
                    output_path=temp_output_path,
                    resolution=settings.image_resolution,
                    reference_images=spec.reference_images,
                )
            )

        def finalize_task_output(task_id: str, generated_file_path: str | None) -> str | None:
            if not generated_file_path:
                return None
            existing = finalized_output_by_task.get(task_id)
            if existing:
                return existing
            spec = spec_by_key.get(str(task_id))
            if spec is None:
                return None
            final_path = replace_generated_file(Path(str(generated_file_path)), spec.output_path)
            finalized_output_by_task[str(task_id)] = str(final_path)
            logger.info(
                "[Image][Batch][Output] provider=%s task=%s file_path=%s",
                provider_name,
                str(task_id),
                str(final_path),
            )
            return str(final_path)

        async def on_provider_progress(task_id: str, progress: int, file_path: str | None) -> None:
            finalized_path = finalize_task_output(str(task_id), file_path)
            await progress_callback(task_id, progress, finalized_path)

        try:
            results = await image_provider.generate_batch(
                batch_tasks,
                progress_callback=on_provider_progress,
                status_callback=status_callback,
            )

            mapped: dict[str, str] = {}
            for task_id, result in results.items():
                final_path = finalize_task_output(str(task_id), str(result.file_path))
                if final_path is not None:
                    mapped[str(task_id)] = final_path
            return mapped
        finally:
            for tmp_path in temp_output_by_task.values():
                cleanup_temp_file(tmp_path)

    return await run_scheduled_tasks(
        db=db,
        stage=stage,
        task_specs=task_specs,
        all_results=all_results,
        adapter=_SchedulerAdapter(adapter),
        settings=SchedulerSettings(
            provider_name=provider_name,
            max_concurrency=settings.max_concurrency,
            allow_batch=batch_capable,
            batch_min_items=2,
            fail_on_partial=settings.fail_on_partial,
        ),
        is_batch_eligible=lambda spec: bool(spec.prompt.strip()),
        is_missing=lambda spec: not spec.prompt.strip(),
        generate_single=generate_single,
        generate_batch=generate_batch,
    )
