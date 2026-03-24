"""First frame image generation stage handler."""

import asyncio
import logging
import shutil
import time as time_module
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.core.project_mode import resolve_script_mode_from_video_type
from app.core.reference_slots import extract_reference_slot_ids
from app.models.project import Project
from app.models.stage import StageExecution, StageType
from app.providers import get_image_provider
from app.providers.image.wan2gp import get_wan2gp_image_preset
from app.stages.common.log_utils import log_stage_separator
from app.stages.common.paths import (
    get_output_dir,
    resolve_existing_path_for_io,
    resolve_stage_payload_for_io,
)
from app.stages.common.validators import is_shot_data_usable

from . import register_stage
from ._visual_prompt import (
    ensure_no_text_overlay_requirement,
    log_full_generation_prompt,
)
from ._wan2gp_progress import extract_runtime_percent, resolve_runtime_status
from .base import StageHandler, StageResult
from .image_provider_utils import (
    get_provider_image_defaults,
    get_provider_kwargs,
    resolve_provider_runtime_name,
)
from .image_task_engine import (
    ImageTaskAdapter,
    ImageTaskRunSettings,
    ImageTaskSpec,
    run_image_tasks,
)
from .reference import get_image_prompt_template, normalize_image_style

logger = logging.getLogger(__name__)
STORYBOARD_SHOTS_REQUIRED_ERROR = "分镜为空或不可用，请先生成分镜"
FRAME_PROMPT_REQUIRED_ERROR = "首帧提示词为空或不可用，请先生成视频描述或首帧描述"


def _resolve_wan2gp_no_reference_fallback_preset(current_preset: str) -> str | None:
    normalized_current = str(current_preset or "").strip()
    if not normalized_current:
        return None

    try:
        current_preset_info = get_wan2gp_image_preset(normalized_current)
    except Exception:
        current_preset_info = {}

    supported_modes = {
        str(mode).strip()
        for mode in list(current_preset_info.get("supported_modes") or [])
        if str(mode).strip()
    }
    if "t2i" in supported_modes:
        return None

    fallback_preset = str(settings.image_wan2gp_preset or "qwen_image_2512").strip()
    if not fallback_preset or fallback_preset == normalized_current:
        return None
    return fallback_preset


def _build_wan2gp_no_reference_fallback_warning(
    shot_index: int,
    target_preset: str,
    *,
    switched_preset: bool,
) -> str:
    if switched_preset:
        return (
            f"分镜 {shot_index + 1} 未找到可用参考图，已从 i2i 自动回退到 t2i 模型"
            f" `{target_preset}` 继续生成。"
        )
    return (
        f"分镜 {shot_index + 1} 未找到可用参考图，当前模型 `{target_preset}`"
        " 将按 t2i 方式继续生成。"
    )


def _resolve_wan2gp_preset_default_inference_steps(preset_name: str) -> int | None:
    normalized_preset = str(preset_name or "").strip()
    if not normalized_preset:
        return None
    try:
        preset = get_wan2gp_image_preset(normalized_preset)
    except Exception:
        return None
    try:
        steps = int(preset.get("inference_steps", 0) or 0)
    except Exception:
        return None
    return steps if steps > 0 else None


class FrameImageTaskAdapter(ImageTaskAdapter):
    def __init__(
        self,
        shots: list[dict[str, Any]],
        provider_name: str,
        existing_frames_by_index: dict[int, dict[str, Any]] | None = None,
        task_warnings_by_key: dict[str, list[str]] | None = None,
    ):
        self.shots = shots
        self.provider_name = provider_name
        self.existing_frames_by_index = existing_frames_by_index or {}
        self.task_warnings_by_key = task_warnings_by_key or {}

    def _collect_output_warnings(
        self,
        generating_shots: dict[str, dict[str, Any]],
    ) -> list[str]:
        warnings: list[str] = []
        seen: set[str] = set()

        def append_warning(value: str) -> None:
            normalized = str(value or "").strip()
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            warnings.append(normalized)

        for task_key in generating_shots:
            for warning in self.task_warnings_by_key.get(str(task_key), []):
                append_warning(warning)

        return warnings

    def _collect_all_task_warnings(self) -> list[str]:
        warnings: list[str] = []
        seen: set[str] = set()

        for task_warning_list in self.task_warnings_by_key.values():
            for warning in task_warning_list:
                normalized = str(warning or "").strip()
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                warnings.append(normalized)

        return warnings

    def build_missing_prompt_result(self, spec: ImageTaskSpec) -> dict[str, Any]:
        return {
            "shot_index": spec.payload["shot_index"],
            "prompt": spec.payload.get("prompt", ""),
            "file_path": None,
            "first_frame_description": spec.payload.get("first_frame_description"),
            "generated": False,
            "error": "No prompt available",
        }

    def build_success_result(self, spec: ImageTaskSpec, file_path: str) -> dict[str, Any]:
        return {
            "shot_index": spec.payload["shot_index"],
            "prompt": spec.payload.get("prompt", ""),
            "file_path": file_path,
            "first_frame_description": spec.payload.get("first_frame_description"),
            "generated": True,
            "updated_at": int(time_module.time()),
        }

    def build_error_result(self, spec: ImageTaskSpec, error: str) -> dict[str, Any]:
        shot_index = int(spec.payload["shot_index"])
        existing = self.existing_frames_by_index.get(shot_index)
        if isinstance(existing, dict):
            existing_file_path = str(existing.get("file_path") or "").strip()
            existing_file = resolve_existing_path_for_io(
                existing_file_path,
                allowed_suffixes={".png", ".jpg", ".jpeg", ".webp"},
            )
            if existing_file_path and existing_file is not None and existing_file.exists():
                preserved = dict(existing)
                preserved["shot_index"] = shot_index
                preserved["prompt"] = spec.payload.get("prompt", preserved.get("prompt", ""))
                preserved["first_frame_description"] = spec.payload.get(
                    "first_frame_description",
                    preserved.get("first_frame_description"),
                )
                # Regeneration failure should not wipe previously usable frame assets.
                preserved["generated"] = bool(
                    preserved.get("generated") or preserved.get("uploaded") or existing_file_path
                )
                preserved["error"] = error
                return preserved

        return {
            "shot_index": shot_index,
            "prompt": spec.payload.get("prompt", ""),
            "file_path": None,
            "first_frame_description": spec.payload.get("first_frame_description"),
            "generated": False,
            "error": error,
        }

    def build_stage_output(
        self,
        current_items: list[dict[str, Any]],
        generating_shots: dict[str, dict[str, Any]],
        provider_name: str,
        progress_message: str | None,
    ) -> dict[str, Any]:
        success_count = sum(1 for item in current_items if item.get("generated"))
        output = {
            "frame_images": current_items,
            "frame_count": len(self.shots),
            "success_count": success_count,
            "generating_shots": generating_shots,
            "runtime_provider": provider_name,
            "image_provider": provider_name,
        }
        warnings = self._collect_output_warnings(generating_shots)
        if warnings:
            output["warnings"] = warnings
        if progress_message and generating_shots:
            output["progress_message"] = progress_message
        return output

    def build_final_data(
        self,
        final_items: list[dict[str, Any]],
        failed_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        data = {
            "frame_images": final_items,
            "frame_count": len(self.shots),
            "success_count": sum(1 for item in final_items if item.get("generated")),
            "runtime_provider": self.provider_name,
            "image_provider": self.provider_name,
        }
        if failed_items:
            data["failed_items"] = failed_items
        return data

    def build_partial_failure_error(self, failed_items: list[dict[str, Any]]) -> str:
        summary = "; ".join(
            f"Shot {item.get('item_key', item.get('item_index'))}: {item.get('error', 'Unknown error')}"
            for item in failed_items
        )
        return f"首帧图生成失败: {summary}"


@register_stage(StageType.FRAME)
class FrameHandler(StageHandler):
    """Generate first frame images for each shot using Image Provider."""

    async def execute(
        self,
        db: AsyncSession,
        project: Project,
        stage: StageExecution,
        input_data: dict[str, Any] | None = None,
    ) -> StageResult:
        storyboard_data = await self._get_storyboard_data(db, project)
        if not storyboard_data:
            return StageResult(success=False, error=STORYBOARD_SHOTS_REQUIRED_ERROR)

        shots = storyboard_data.get("shots") or []
        if not shots:
            return StageResult(success=False, error=STORYBOARD_SHOTS_REQUIRED_ERROR)

        existing_output = resolve_stage_payload_for_io(stage.output_data) or {}
        existing_frames = existing_output.get("frame_images", [])

        only_shot_index = (
            (input_data or {}).get("only_shot_index")
            if (input_data or {}).get("only_shot_index") is not None
            else None
        )
        force_regenerate = bool((input_data or {}).get("force_regenerate", False))
        script_mode = (
            str(
                (input_data or {}).get("script_mode")
                or storyboard_data.get("script_mode")
                or resolve_script_mode_from_video_type(project.video_type)
                or ""
            )
            .strip()
            .lower()
        )
        single_take = bool(
            (input_data or {}).get("single_take", False) or script_mode == "duo_podcast"
        )
        target_indices = list(range(len(shots)))
        if only_shot_index is not None:
            if (
                not isinstance(only_shot_index, int)
                or only_shot_index < 0
                or only_shot_index >= len(shots)
            ):
                return StageResult(
                    success=False, error=f"Shot index {only_shot_index} out of range"
                )
            target_indices = [only_shot_index]

        provider_name = (input_data or {}).get("image_provider", settings.default_image_provider)
        image_aspect_ratio = (input_data or {}).get("image_aspect_ratio")
        image_size = (input_data or {}).get("image_size")
        image_resolution = (input_data or {}).get("image_resolution")

        default_aspect_ratio, default_size = get_provider_image_defaults(provider_name, "frame")
        if not image_aspect_ratio:
            image_aspect_ratio = default_aspect_ratio
        if not image_size:
            image_size = default_size
        if not image_resolution:
            image_resolution = settings.image_wan2gp_frame_resolution or "1088x1920"

        image_style = normalize_image_style((input_data or {}).get("image_style"))
        max_concurrency = int((input_data or {}).get("max_concurrency", 4))
        if provider_name == "wan2gp":
            max_concurrency = 1

        logger.info(
            "[Frame][Image] provider=%s model=%s style=%s target=%d only_shot_index=%s force=%s max_concurrency=%d",
            provider_name,
            (input_data or {}).get("image_model"),
            image_style,
            len(target_indices),
            only_shot_index,
            force_regenerate,
            max_concurrency,
        )
        logger.info(
            "[Frame][Image] single_take=%s script_mode=%s", single_take, script_mode or "single"
        )

        use_reference_consistency = (input_data or {}).get("use_reference_consistency", False)
        reference_image_items: list[dict[str, Any]] = []
        if use_reference_consistency:
            reference_data = await self._get_reference_data(db, project)
            if reference_data:
                reference_image_items = reference_data.get("reference_images", [])

        provider_kwargs = get_provider_kwargs(provider_name, "frame", input_data=input_data)
        if provider_kwargs is None:
            return StageResult(
                success=False,
                error=f"Image provider '{provider_name}' is not configured. Check settings.",
            )

        try:
            runtime_provider_name = resolve_provider_runtime_name(provider_name)
            image_provider = get_image_provider(runtime_provider_name, **provider_kwargs)
        except Exception as e:  # noqa: BLE001
            return StageResult(success=False, error=str(e))

        output_dir = self._get_output_dir(project)
        frame_dir = output_dir / "frames"
        frame_dir.mkdir(parents=True, exist_ok=True)

        existing_frames_by_index = {
            int(item.get("shot_index")): item
            for item in existing_frames
            if isinstance(item, dict) and item.get("shot_index") is not None
        }

        # 双人播客的一镜到底批量入口：只确保第一个分镜位有首帧图，然后复用到所有分镜位。
        if single_take and script_mode == "duo_podcast" and only_shot_index is None:
            return await self._run_duo_podcast_reuse_flow(
                db=db,
                stage=stage,
                shots=shots,
                provider_name=provider_name,
                image_provider=image_provider,
                provider_kwargs=provider_kwargs,
                frame_dir=frame_dir,
                existing_frames_by_index=existing_frames_by_index,
                force_regenerate=force_regenerate,
                image_aspect_ratio=image_aspect_ratio,
                image_size=image_size,
                image_resolution=image_resolution,
                image_style=image_style,
                use_reference_consistency=bool(use_reference_consistency),
                reference_image_items=reference_image_items,
            )

        all_results: list[dict[str, Any] | None] = [None] * len(shots)
        for i in range(len(shots)):
            existing = existing_frames_by_index.get(i)
            if existing:
                all_results[i] = existing

        task_specs: list[ImageTaskSpec] = []
        task_warnings_by_key: dict[str, list[str]] = {}
        missing_prompt_indices: list[int] = []
        for i in target_indices:
            shot = shots[i]
            prompt = str(shot.get("first_frame_description") or shot.get("video_prompt") or "")
            existing = existing_frames_by_index.get(i)

            should_skip = (
                not force_regenerate
                and existing is not None
                and existing.get("generated")
                and (
                    (
                        existing_path := resolve_existing_path_for_io(
                            existing.get("file_path"),
                            allowed_suffixes={".png", ".jpg", ".jpeg", ".webp"},
                        )
                    )
                    is not None
                    and existing_path.exists()
                )
            )

            if not should_skip and not prompt.strip():
                missing_prompt_indices.append(i)
                continue

            full_prompt, reference_paths = self._build_shot_prompt_and_refs(
                shot=shot,
                prompt=prompt,
                image_style=image_style,
                use_reference_consistency=bool(use_reference_consistency),
                reference_image_items=reference_image_items,
            )
            task_payload = {
                "shot_index": i,
                "prompt": prompt,
                "first_frame_description": shot.get("first_frame_description"),
            }
            if not should_skip and (
                provider_name == "wan2gp"
                and bool(use_reference_consistency)
                and not reference_paths
            ):
                current_preset = str(provider_kwargs.get("image_preset") or "").strip()
                fallback_preset = _resolve_wan2gp_no_reference_fallback_preset(current_preset)
                if fallback_preset:
                    task_payload["wan2gp_image_preset_override"] = fallback_preset
                    fallback_steps = _resolve_wan2gp_preset_default_inference_steps(fallback_preset)
                    if fallback_steps is not None:
                        task_payload["wan2gp_image_inference_steps_override"] = fallback_steps
                    task_warnings_by_key[str(i)] = [
                        _build_wan2gp_no_reference_fallback_warning(
                            i,
                            fallback_preset,
                            switched_preset=True,
                        )
                    ]
                elif current_preset:
                    task_warnings_by_key[str(i)] = [
                        _build_wan2gp_no_reference_fallback_warning(
                            i,
                            current_preset,
                            switched_preset=False,
                        )
                    ]

            task_specs.append(
                ImageTaskSpec(
                    index=i,
                    key=str(i),
                    prompt=full_prompt,
                    output_path=frame_dir / f"frame_{i:03d}.png",
                    skip=should_skip,
                    payload=task_payload,
                    reference_images=reference_paths,
                )
            )

        if missing_prompt_indices:
            return StageResult(success=False, error=FRAME_PROMPT_REQUIRED_ERROR)

        adapter = FrameImageTaskAdapter(
            shots=shots,
            provider_name=provider_name,
            existing_frames_by_index=existing_frames_by_index,
            task_warnings_by_key=task_warnings_by_key,
        )
        run_settings = ImageTaskRunSettings(
            provider_name=provider_name,
            image_provider=image_provider,
            provider_kwargs=provider_kwargs,
            max_concurrency=max_concurrency,
            image_aspect_ratio=image_aspect_ratio,
            image_size=image_size,
            image_resolution=image_resolution,
            force_regenerate=force_regenerate,
            allow_wan2gp_batch=True,
            fail_on_partial=True,
        )

        return await run_image_tasks(
            db=db,
            stage=stage,
            task_specs=task_specs,
            all_results=all_results,
            adapter=adapter,
            settings=run_settings,
        )

    async def _run_duo_podcast_reuse_flow(
        self,
        *,
        db: AsyncSession,
        stage: StageExecution,
        shots: list[dict[str, Any]],
        provider_name: str,
        image_provider: Any,
        provider_kwargs: dict[str, Any],
        frame_dir: Path,
        existing_frames_by_index: dict[int, dict[str, Any]],
        force_regenerate: bool,
        image_aspect_ratio: str | None,
        image_size: str | None,
        image_resolution: str | None,
        image_style: str | None,
        use_reference_consistency: bool,
        reference_image_items: list[dict[str, Any]],
    ) -> StageResult:
        if not shots:
            return StageResult(success=False, error=STORYBOARD_SHOTS_REQUIRED_ERROR)

        first_shot = shots[0] if isinstance(shots[0], dict) else {}
        first_prompt = str(
            first_shot.get("first_frame_description") or first_shot.get("video_prompt") or ""
        ).strip()
        first_existing = existing_frames_by_index.get(0) or {}

        source_path: Path | None = None
        if not first_prompt:
            return StageResult(success=False, error=FRAME_PROMPT_REQUIRED_ERROR)
        full_prompt, reference_paths = self._build_shot_prompt_and_refs(
            shot=first_shot,
            prompt=first_prompt,
            image_style=image_style,
            use_reference_consistency=use_reference_consistency,
            reference_image_items=reference_image_items,
        )
        task_image_provider = image_provider
        runtime_warnings: list[str] = []
        if provider_name == "wan2gp" and use_reference_consistency and not reference_paths:
            current_preset = str(provider_kwargs.get("image_preset") or "").strip()
            fallback_preset = _resolve_wan2gp_no_reference_fallback_preset(current_preset)
            if fallback_preset:
                task_provider_kwargs = dict(provider_kwargs)
                task_provider_kwargs["image_preset"] = fallback_preset
                fallback_steps = _resolve_wan2gp_preset_default_inference_steps(fallback_preset)
                if fallback_steps is not None:
                    task_provider_kwargs["image_inference_steps"] = fallback_steps
                task_image_provider = get_image_provider("wan2gp", **task_provider_kwargs)
                runtime_warnings.append(
                    _build_wan2gp_no_reference_fallback_warning(
                        0,
                        fallback_preset,
                        switched_preset=True,
                    )
                )
            elif current_preset:
                runtime_warnings.append(
                    _build_wan2gp_no_reference_fallback_warning(
                        0,
                        current_preset,
                        switched_preset=False,
                    )
                )
        output_path = frame_dir / "frame_000.png"
        db_lock = asyncio.Lock()
        runtime_status_message = "准备中..." if provider_name == "wan2gp" else "启动中..."
        generating_shots: dict[str, dict[str, Any]] = {"0": {"status": "pending", "progress": 0}}

        existing_items: list[dict[str, Any]] = []
        for idx in range(len(shots)):
            existing_item = existing_frames_by_index.get(idx)
            if isinstance(existing_item, dict):
                existing_items.append(existing_item)

        async def persist_runtime_state() -> None:
            success_count = sum(1 for item in existing_items if item.get("generated"))
            stage.total_items = 1
            stage.completed_items = 0
            stage.skipped_items = 0
            if generating_shots:
                stage.progress = max(
                    1,
                    min(99, int(generating_shots.get("0", {}).get("progress", 0) or 0)),
                )
            stage.output_data = {
                "frame_images": existing_items,
                "frame_count": len(shots),
                "success_count": success_count,
                "generating_shots": generating_shots,
                "runtime_provider": provider_name,
                "image_provider": provider_name,
                "progress_message": runtime_status_message,
            }
            if runtime_warnings:
                stage.output_data["warnings"] = runtime_warnings
            flag_modified(stage, "output_data")
            await db.commit()

        async def on_status(message: str) -> None:
            nonlocal runtime_status_message
            next_status = resolve_runtime_status(runtime_status_message, message)
            if not next_status:
                return
            async with db_lock:
                runtime_status_message = next_status
                shot_state = generating_shots.get("0", {"status": "generating", "progress": 0})
                runtime_percent = extract_runtime_percent(next_status)
                if runtime_percent is not None:
                    next_progress = max(1, min(99, int(runtime_percent)))
                    if next_status.startswith("模型下载中"):
                        shot_state["progress"] = next_progress
                    else:
                        shot_state["progress"] = max(
                            int(shot_state.get("progress", 0) or 0),
                            next_progress,
                        )
                shot_state["status"] = "generating"
                generating_shots["0"] = shot_state
                await persist_runtime_state()

        async def on_progress(value: int) -> None:
            nonlocal runtime_status_message
            async with db_lock:
                next_progress = max(1, min(99, int(value)))
                shot_state = generating_shots.get("0", {"status": "generating", "progress": 0})
                shot_state["status"] = "generating"
                shot_state["progress"] = max(int(shot_state.get("progress", 0) or 0), next_progress)
                generating_shots["0"] = shot_state
                if provider_name != "wan2gp" and runtime_status_message in (
                    "启动中...",
                    "准备中...",
                    "",
                ):
                    runtime_status_message = "生成中..."
                await persist_runtime_state()

        await persist_runtime_state()
        generate_kwargs: dict[str, Any] = {
            "prompt": full_prompt,
            "output_path": output_path,
            "progress_callback": on_progress,
        }
        if reference_paths:
            generate_kwargs["reference_images"] = reference_paths
        if provider_name == "wan2gp":
            generate_kwargs["resolution"] = image_resolution
            generate_kwargs["status_callback"] = on_status
        else:
            generate_kwargs["aspect_ratio"] = image_aspect_ratio
            generate_kwargs["image_size"] = image_size
        log_stage_separator(logger)
        logger.info(
            "[Frame][Reuse][Input] provider=%s shot=0 output=%s force_regenerate=%s",
            provider_name,
            str(output_path),
            force_regenerate,
        )
        log_full_generation_prompt(logger, "[Frame][Reuse][Input] prompt:", full_prompt)
        if reference_paths:
            logger.info(
                "[Frame][Reuse][Input] reference_images=%s",
                [str(path) for path in reference_paths],
            )
        log_stage_separator(logger)
        result = await task_image_provider.generate(**generate_kwargs)
        source_path = Path(str(result.file_path))
        if not source_path.exists():
            fallback_output = Path(str(output_path))
            if fallback_output.exists():
                source_path = fallback_output
            else:
                return StageResult(success=False, error="首帧图生成成功但输出文件不存在")
        logger.info(
            "[Frame][Reuse][Output] provider=%s shot=0 file_path=%s",
            provider_name,
            str(source_path),
        )

        if source_path is None or not source_path.exists():
            return StageResult(success=False, error="首帧图不存在，无法复用")

        source_suffix = source_path.suffix or ".png"
        updated_at = int(time_module.time())
        frame_items: list[dict[str, Any]] = []
        for idx, shot in enumerate(shots):
            if idx == 0:
                target_path = source_path
            else:
                target_path = frame_dir / f"frame_{idx:03d}{source_suffix}"
                shutil.copy2(source_path, target_path)
            item = {
                "shot_index": idx,
                "prompt": str(
                    shot.get("first_frame_description") or shot.get("video_prompt") or ""
                ),
                "file_path": str(target_path),
                "first_frame_description": shot.get("first_frame_description"),
                "generated": True,
                "updated_at": updated_at,
            }
            if idx == 0 and first_existing.get("uploaded"):
                item["uploaded"] = True
            frame_items.append(item)
        logger.info(
            "[Frame][Reuse] replicated first frame to all shots: source=%s shot_count=%d",
            str(source_path),
            len(frame_items),
        )
        return StageResult(
            success=True,
            data={
                "frame_images": frame_items,
                "frame_count": len(shots),
                "success_count": len(frame_items),
                "runtime_provider": provider_name,
                "image_provider": provider_name,
            },
        )

    def _build_shot_prompt_and_refs(
        self,
        shot: dict[str, Any],
        prompt: str,
        image_style: str | None,
        use_reference_consistency: bool,
        reference_image_items: list[dict[str, Any]],
    ) -> tuple[str, list[Path] | None]:
        resolved_reference_images: list[Path] = []

        if use_reference_consistency and reference_image_items:
            reference_slot_ids = extract_reference_slot_ids(shot.get("first_frame_reference_slots"))
            if reference_slot_ids:
                for reference_id in reference_slot_ids:
                    for reference_item in reference_image_items:
                        if reference_item.get("id") != reference_id:
                            continue
                        file_path = reference_item.get("file_path")
                        if file_path and (
                            reference_item.get("generated") or reference_item.get("uploaded")
                        ):
                            ref_path = resolve_existing_path_for_io(
                                file_path,
                                allowed_suffixes={".png", ".jpg", ".jpeg", ".webp"},
                            )
                            if ref_path is not None and ref_path.exists():
                                resolved_reference_images.append(ref_path)
                        break

        parts: list[str] = []
        parts.append(ensure_no_text_overlay_requirement(prompt))

        if image_style:
            style_template = get_image_prompt_template(image_style)
            if style_template and "Style requirements:" in style_template:
                style_part = style_template.split("Style requirements:", maxsplit=1)[1].strip()
                parts.append(f"Style requirements:\n{style_part}")

        return "\n\n".join(parts), (resolved_reference_images or None)

    def _get_output_dir(self, project: Project) -> Path:
        return get_output_dir(project)

    async def _get_storyboard_data(
        self, db: AsyncSession, project: Project
    ) -> dict[str, Any] | None:
        result = await db.execute(
            select(StageExecution)
            .where(
                StageExecution.project_id == project.id,
                StageExecution.stage_type == StageType.STORYBOARD,
            )
            .order_by(StageExecution.updated_at.desc(), StageExecution.id.desc())
        )
        storyboard_data, _ = self._pick_latest_usable_shot_data(list(result.scalars()))
        return storyboard_data

    async def _get_reference_data(
        self, db: AsyncSession, project: Project
    ) -> dict[str, Any] | None:
        result = await db.execute(
            select(StageExecution)
            .where(
                StageExecution.project_id == project.id,
                StageExecution.stage_type == StageType.REFERENCE,
            )
            .order_by(StageExecution.updated_at.desc(), StageExecution.id.desc())
        )
        for reference_stage in result.scalars():
            output_data = resolve_stage_payload_for_io(reference_stage.output_data)
            if not isinstance(output_data, dict):
                continue
            reference_images = output_data.get("reference_images")
            if isinstance(reference_images, list) and reference_images:
                return output_data
        return None

    async def validate_prerequisites(
        self,
        db: AsyncSession,
        project: Project,
    ) -> str | None:
        storyboard_data = await self._get_storyboard_data(db, project)
        if not storyboard_data:
            return STORYBOARD_SHOTS_REQUIRED_ERROR
        return None

    @staticmethod
    def _is_shot_payload_usable(shot: dict[str, Any]) -> bool:
        if not isinstance(shot, dict):
            return False
        voice_content = shot.get("voice_content")
        return isinstance(voice_content, str) and voice_content.strip() != ""

    def _is_shot_data_usable(self, output_data: Any) -> bool:
        return is_shot_data_usable(output_data)

    def _pick_latest_usable_shot_data(
        self, stages: list[StageExecution]
    ) -> tuple[dict[str, Any] | None, Any]:
        for stage in stages:
            output_data = stage.output_data
            if self._is_shot_data_usable(output_data):
                return output_data, stage.updated_at
        return None, None
