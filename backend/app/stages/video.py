import asyncio
import logging
import time as time_module
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.core.dialogue import DUO_ROLE_1_ID, DUO_ROLE_2_ID
from app.core.errors import StageRuntimeError, StageValidationError
from app.core.project_mode import resolve_script_mode_from_video_type
from app.core.reference_slots import extract_reference_slot_ids, normalize_reference_slots
from app.db.session import AsyncSessionLocal
from app.models.project import Project
from app.models.stage import StageExecution, StageType
from app.providers import get_video_provider
from app.providers.video.volcengine_seedance import (
    get_seedance_duration_control_mode,
    get_seedance_frame_duration_bounds_seconds,
)
from app.providers.video_capabilities import (
    get_supported_durations_seconds,
    resolve_requested_duration_seconds,
)
from app.stages.common.data_access import get_latest_stage_output
from app.stages.common.log_utils import log_stage_separator
from app.stages.common.paths import (
    get_output_dir,
    resolve_existing_path_for_io,
    resolve_path_for_io,
    resolve_stage_payload_for_io,
)
from app.stages.common.validators import is_audio_data_usable_strict, is_storyboard_data_usable

from . import register_stage
from ._asset_swap import build_temporary_output_path, cleanup_temp_file, replace_generated_file
from ._video_config import VideoConfigResolver
from ._video_types import (
    AUDIO_DATA_REQUIRED_ERROR,
    COMBINED_REFERENCE_UNSUPPORTED_ERROR,
    FIRST_FRAME_DATA_REQUIRED_ERROR,
    REFERENCE_IMAGE_DATA_REQUIRED_ERROR,
    REFERENCE_IMAGE_UNSUPPORTED_ERROR,
    SINGLE_TAKE_PREVIOUS_VIDEO_REQUIRED_ERROR,
    VIDEO_PROMPT_REQUIRED_ERROR,
    VideoSchedulerAdapter,
    VideoTaskSpec,
    append_last_frame_lock_instruction,
    dedupe_reasons,
    max_reference_images_per_shot,
    supports_combined_references,
    supports_last_frame,
    supports_reference_images,
)
from ._visual_prompt import (
    ensure_duo_podcast_speaking_requirement,
    ensure_no_text_overlay_requirement,
    log_full_generation_prompt,
)
from .base import StageHandler, StageResult
from .task_scheduler import SchedulerSettings, run_scheduled_tasks

logger = logging.getLogger(__name__)


@register_stage(StageType.VIDEO)
class VideoHandler(StageHandler):
    async def execute(
        self,
        db: AsyncSession,
        project: Project,
        stage: StageExecution,
        input_data: dict[str, Any] | None = None,
    ) -> StageResult:
        storyboard_data = await self._get_storyboard_data(db, project)
        audio_data = await self._get_audio_data(db, project)

        if not storyboard_data:
            return StageResult(success=False, error=VIDEO_PROMPT_REQUIRED_ERROR)
        if not audio_data:
            return StageResult(success=False, error=AUDIO_DATA_REQUIRED_ERROR)

        shots = storyboard_data.get("shots") or []
        audio_assets = audio_data.get("audio_assets", [])
        if not shots:
            return StageResult(success=False, error=VIDEO_PROMPT_REQUIRED_ERROR)
        project_config = project.config if isinstance(project.config, dict) else {}
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
        single_take_enabled = bool(
            (input_data or {}).get("single_take", False) or script_mode == "duo_podcast"
        )
        content_data = (
            await self._get_content_data(db, project) if script_mode == "duo_podcast" else None
        )
        duo_podcast_speaker_side_by_id = self._build_duo_podcast_speaker_side_map(content_data)

        existing_output = resolve_stage_payload_for_io(stage.output_data) or {}
        existing_videos = existing_output.get("video_assets", [])

        only_shot_index = (
            (input_data or {}).get("only_shot_index")
            if (input_data or {}).get("only_shot_index") is not None
            else None
        )
        force_regenerate = bool((input_data or {}).get("force_regenerate", False))
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

        invalid_prompt_indices = [
            idx for idx in target_indices if not self._is_video_prompt_valid(shots[idx])
        ]
        if invalid_prompt_indices:
            return StageResult(success=False, error=VIDEO_PROMPT_REQUIRED_ERROR)

        audio_analysis_indices = list(target_indices)
        if single_take_enabled:
            for idx in target_indices:
                if idx <= 0:
                    continue
                previous_idx = idx - 1
                if previous_idx not in audio_analysis_indices:
                    audio_analysis_indices.append(previous_idx)

        duration_map, missing_audio_details = self._analyze_audio_assets(
            target_indices=audio_analysis_indices,
            audio_assets=audio_assets,
            shot_count=len(shots),
        )
        if missing_audio_details:
            return StageResult(
                success=False,
                error=f"{AUDIO_DATA_REQUIRED_ERROR}。{'；'.join(missing_audio_details)}",
            )

        try:
            output_dir = self._get_output_dir(project)
            video_dir = output_dir / "videos"
            video_dir.mkdir(parents=True, exist_ok=True)
            frame_dir = output_dir / "frames"
            frame_dir.mkdir(parents=True, exist_ok=True)

            config = project_config
            stage_input = input_data or {}

            video_cfg = VideoConfigResolver.resolve(
                input_data,
                project_config,
                single_take_enabled=single_take_enabled,
            )
            video_provider_name = video_cfg.video_provider_name
            video_model = video_cfg.video_model
            audio_gap_seconds = video_cfg.audio_gap_seconds
            max_concurrency = video_cfg.max_concurrency
            effective_video_fit_mode = video_cfg.effective_video_fit_mode
            wan2gp_t2v_preset = video_cfg.wan2gp_t2v_preset
            wan2gp_i2v_preset = video_cfg.wan2gp_i2v_preset
            provider_kwargs = video_cfg.provider_kwargs

            use_first_frame_ref = bool(
                (input_data or {}).get(
                    "use_first_frame_ref",
                    (project.config or {}).get("use_first_frame_ref", False),
                )
            )
            if single_take_enabled:
                use_first_frame_ref = True
            use_reference_image_ref = bool(
                (input_data or {}).get(
                    "use_reference_image_ref",
                    (project.config or {}).get("use_reference_image_ref", False),
                )
            )
            logger.info(
                "[Video] script_mode=%s single_take=%s use_first_frame_ref=%s max_concurrency=%d fit_mode=%s",
                script_mode or "single",
                single_take_enabled,
                use_first_frame_ref,
                max_concurrency,
                effective_video_fit_mode,
            )

            def _resolve_runtime_model(
                provider_name: str,
                runtime_kwargs: dict[str, Any],
            ) -> str:
                if provider_name == "volcengine_seedance":
                    return str(
                        runtime_kwargs.get("model")
                        or video_model
                        or settings.video_seedance_model
                        or "seedance-2-0"
                    ).strip()
                return str(wan2gp_i2v_preset if use_first_frame_ref else wan2gp_t2v_preset).strip()

            def _build_wan2gp_provider_kwargs() -> dict[str, Any]:
                try:
                    fit_canvas = int(settings.wan2gp_fit_canvas)
                except (TypeError, ValueError):
                    fit_canvas = 0
                if fit_canvas not in (0, 1, 2):
                    fit_canvas = 0
                return {
                    "wan2gp_path": settings.wan2gp_path,
                    "python_executable": settings.local_model_python_path,
                    "t2v_preset": str(wan2gp_t2v_preset),
                    "i2v_preset": str(wan2gp_i2v_preset),
                    "resolution": str(video_cfg.wan2gp_resolution or ""),
                    "negative_prompt": str(video_cfg.wan2gp_negative_prompt or ""),
                    "inference_steps": video_cfg.wan2gp_inference_steps,
                    "sliding_window_size": video_cfg.wan2gp_sliding_window_size,
                    "fit_canvas": fit_canvas,
                }

            video_provider = get_video_provider(video_provider_name, **provider_kwargs)
            effective_video_model = _resolve_runtime_model(video_provider_name, provider_kwargs)
            fallback_provider_name = (
                "wan2gp"
                if (
                    video_provider_name == "volcengine_seedance"
                    and str(settings.wan2gp_path or "").strip()
                )
                else None
            )
            fallback_provider_kwargs = (
                _build_wan2gp_provider_kwargs() if fallback_provider_name == "wan2gp" else None
            )
            fallback_video_provider = (
                get_video_provider(fallback_provider_name, **fallback_provider_kwargs)
                if fallback_provider_name and fallback_provider_kwargs is not None
                else None
            )
            fallback_video_model = (
                _resolve_runtime_model(fallback_provider_name, fallback_provider_kwargs)
                if fallback_provider_name and fallback_provider_kwargs is not None
                else ""
            )
            supports_last_frame_flag = supports_last_frame(
                provider_name=video_provider_name,
                model=effective_video_model,
            )
            requested_model_hint = (
                str(stage_input.get("video_model") or config.get("video_model") or "").strip()
                or str(
                    stage_input.get("video_wan2gp_i2v_preset")
                    or config.get("video_wan2gp_i2v_preset")
                    or ""
                ).strip()
                or str(
                    stage_input.get("video_wan2gp_t2v_preset")
                    or config.get("video_wan2gp_t2v_preset")
                    or ""
                ).strip()
            )
            logger.info(
                "[Video][ModelResolve] requested_provider=%s requested_model=%s resolved_provider=%s "
                "resolved_model=%s single_take=%s use_first_frame_ref=%s supports_last_frame=%s",
                str(stage_input.get("video_provider") or config.get("video_provider") or "")
                .strip()
                .lower()
                or None,
                requested_model_hint or None,
                video_provider_name,
                effective_video_model or None,
                single_take_enabled,
                use_first_frame_ref,
                supports_last_frame_flag,
            )
            logger.info(
                "[Video] model=%s supports_last_frame=%s",
                effective_video_model or "unknown",
                supports_last_frame_flag,
            )
            if fallback_provider_name and fallback_video_provider is not None:
                logger.info(
                    "[Video][FallbackReady] primary_provider=%s primary_model=%s fallback_provider=%s fallback_model=%s",
                    video_provider_name,
                    effective_video_model or None,
                    fallback_provider_name,
                    fallback_video_model or None,
                )
            video_mode = "i2v" if use_first_frame_ref else "t2v"
            supported_durations = get_supported_durations_seconds(
                video_provider_name,
                effective_video_model,
                video_mode,
            )
            duration_control_mode = (
                get_seedance_duration_control_mode(effective_video_model)
                if video_provider_name == "volcengine_seedance"
                else "duration"
            )
            if single_take_enabled and not supports_last_frame_flag:
                logger.warning(
                    "[Video][SingleTake] model does not support last_frame guidance: provider=%s model=%s",
                    video_provider_name,
                    effective_video_model or "unknown",
                )
            if use_reference_image_ref and not supports_reference_images(
                provider_name=video_provider_name,
                model=effective_video_model,
            ):
                return StageResult(
                    success=False,
                    error=f"{REFERENCE_IMAGE_UNSUPPORTED_ERROR}（provider={video_provider_name}, model={effective_video_model or 'unknown'}）",
                )
            if (
                use_reference_image_ref
                and use_first_frame_ref
                and not supports_combined_references(
                    provider_name=video_provider_name,
                    model=effective_video_model,
                )
            ):
                return StageResult(
                    success=False,
                    error=f"{COMBINED_REFERENCE_UNSUPPORTED_ERROR}（provider={video_provider_name}, model={effective_video_model or 'unknown'}）",
                )

            frame_paths_by_index: dict[int, Path] = {}
            if use_first_frame_ref:
                frame_data = await self._get_frame_data(db, project)
                if single_take_enabled:
                    frame_collect_indices = set(target_indices)
                    for idx in target_indices:
                        next_idx = idx + 1
                        if next_idx < len(shots):
                            frame_collect_indices.add(next_idx)
                    frame_paths_by_index = self._collect_first_frame_assets(
                        target_indices=sorted(frame_collect_indices),
                        frame_data=frame_data,
                    )
                    required_single_take_indices: list[int] = []
                    if 0 in target_indices:
                        required_single_take_indices.append(0)
                    missing_single_take_frames = [
                        f"分镜位{idx}无首帧图记录"
                        for idx in required_single_take_indices
                        if idx not in frame_paths_by_index
                    ]
                    if missing_single_take_frames:
                        return StageResult(
                            success=False,
                            error=f"{FIRST_FRAME_DATA_REQUIRED_ERROR}。{'；'.join(missing_single_take_frames)}",
                        )
                else:
                    frame_paths_by_index, missing_frame_details = self._analyze_first_frame_assets(
                        target_indices=list(target_indices),
                        frame_data=frame_data,
                    )
                    if missing_frame_details:
                        return StageResult(
                            success=False,
                            error=f"{FIRST_FRAME_DATA_REQUIRED_ERROR}。{'；'.join(missing_frame_details)}",
                        )

            reference_image_paths_by_index: dict[int, list[Path]] = {}
            allowed_video_reference_ids: set[str] | None = None
            if use_reference_image_ref:
                reference_data = await self._get_reference_data(db, project)
                if isinstance(reference_data, dict):
                    raw_reference_images = reference_data.get("reference_images")
                    if isinstance(raw_reference_images, list):
                        allowed_video_reference_ids = {
                            str(item.get("id") or "").strip()
                            for item in raw_reference_images
                            if isinstance(item, dict) and str(item.get("id") or "").strip()
                        }
                reference_image_paths_by_index, missing_reference_details = (
                    self._analyze_reference_image_assets(
                        target_indices=target_indices,
                        shots=shots,
                        reference_data=reference_data,
                        max_images_per_shot=max_reference_images_per_shot(
                            provider_name=video_provider_name,
                            model=effective_video_model,
                        ),
                    )
                )
                if missing_reference_details:
                    return StageResult(
                        success=False,
                        error=f"{REFERENCE_IMAGE_DATA_REQUIRED_ERROR}。{'；'.join(missing_reference_details)}",
                    )

            existing_videos_by_index = {
                int(v.get("shot_index")): v
                for v in existing_videos
                if isinstance(v, dict) and v.get("shot_index") is not None
            }

            all_results: list[dict[str, Any] | None] = [None] * len(shots)
            for i in range(len(shots)):
                existing = existing_videos_by_index.get(i)
                if existing:
                    all_results[i] = existing

            def resolve_precomputed_last_frame(
                shot_index: int,
            ) -> tuple[Path | None, str]:
                if not (single_take_enabled and use_first_frame_ref):
                    return None, "single_take_disabled_or_first_frame_ref_disabled"
                if not supports_last_frame_flag:
                    return None, "model_not_supported"

                next_shot_index = shot_index + 1
                if next_shot_index >= len(shots):
                    return None, "no_next_shot"

                candidate_last_frame = frame_paths_by_index.get(next_shot_index)
                if candidate_last_frame is None:
                    return None, "next_shot_frame_missing"
                if not candidate_last_frame.exists():
                    return None, "next_shot_frame_file_missing"
                return candidate_last_frame, "applied_from_next_shot_frame"

            task_specs: list[VideoTaskSpec] = []
            for i in target_indices:
                shot = shots[i]
                video_prompt = str(shot.get("video_prompt") or "")
                requested_duration = float(duration_map[i] + audio_gap_seconds)
                duration = requested_duration
                if supported_durations:
                    selected_duration = resolve_requested_duration_seconds(
                        video_provider_name,
                        effective_video_model,
                        video_mode,
                        requested_duration,
                    )
                    if selected_duration is None:
                        supported_text = ", ".join(f"{item}s" for item in supported_durations)
                        if (
                            video_provider_name == "volcengine_seedance"
                            and duration_control_mode == "frames"
                        ):
                            frame_bounds = get_seedance_frame_duration_bounds_seconds(
                                effective_video_model
                            )
                            if frame_bounds is not None:
                                min_seconds, max_seconds = frame_bounds
                                return StageResult(
                                    success=False,
                                    error=(
                                        f"第{i + 1}个分镜音频时长 {requested_duration:.3f}s 超出当前视频模型可选帧控范围。"
                                        f"provider={video_provider_name}, model={effective_video_model or 'unknown'}, "
                                        f"range=[{min_seconds:.3f}s, {max_seconds:.3f}s]。"
                                    ),
                                )
                        return StageResult(
                            success=False,
                            error=(
                                f"第{i + 1}个分镜音频时长 {requested_duration:.1f}s 超出当前视频模型可选时长。"
                                f"provider={video_provider_name}, model={effective_video_model or 'unknown'}, "
                                f"supported=[{supported_text}]。请重新规划分镜或更换视频模型。"
                            ),
                        )
                    duration = float(selected_duration)
                output_path = video_dir / f"shot_{i:03d}.mp4"
                first_frame = frame_paths_by_index.get(i) if use_first_frame_ref else None
                reference_images = reference_image_paths_by_index.get(i)
                existing = existing_videos_by_index.get(i)
                existing_video_path = (
                    resolve_path_for_io(existing.get("file_path"))
                    if isinstance(existing, dict)
                    else None
                )
                should_skip = (
                    not force_regenerate
                    and existing is not None
                    and existing.get("file_path")
                    and existing_video_path is not None
                    and existing_video_path.exists()
                )
                last_frame, last_frame_reason = resolve_precomputed_last_frame(i)
                task_specs.append(
                    VideoTaskSpec(
                        index=i,
                        key=str(i),
                        video_prompt=video_prompt,
                        duration=duration,
                        output_path=output_path,
                        first_frame=first_frame,
                        last_frame=last_frame,
                        reference_images=reference_images,
                        skip=should_skip,
                        payload={
                            "video_reference_slots": normalize_reference_slots(
                                shot.get("video_reference_slots"),
                                allowed_reference_ids=allowed_video_reference_ids,
                            ),
                            "speaker_id": str(shot.get("speaker_id") or "").strip(),
                            "last_frame_reason": last_frame_reason,
                            # Preserve previous successful asset for UI fallback during regenerate.
                            "existing_video_asset": dict(existing)
                            if isinstance(existing, dict)
                            else None,
                        },
                    )
                )

            # Shot indexes that are actually being regenerated in this run.
            regenerating_indices = {spec.index for spec in task_specs if not spec.skip}

            if single_take_enabled and use_first_frame_ref:
                ready_with_first_frame_count = 0
                ready_with_first_last_frame_count = 0
                wait_prev_tail_count = 0
                for idx in target_indices:
                    has_first_frame = idx in frame_paths_by_index
                    if has_first_frame:
                        ready_with_first_frame_count += 1
                        if (
                            idx < len(shots) - 1
                            and supports_last_frame_flag
                            and (idx + 1) in frame_paths_by_index
                        ):
                            ready_with_first_last_frame_count += 1
                    elif idx > 0:
                        wait_prev_tail_count += 1
                logger.info(
                    "[Video][SingleTakeScheduling] requested_concurrency=%d ready_with_first_frame=%d "
                    "ready_with_first_last_frame=%d wait_prev_tail=%d target_shots=%s",
                    max_concurrency,
                    ready_with_first_frame_count,
                    ready_with_first_last_frame_count,
                    wait_prev_tail_count,
                    sorted(target_indices),
                )

            def is_batch_eligible(spec: VideoTaskSpec) -> bool:
                if not spec.video_prompt.strip():
                    return False
                if not (single_take_enabled and use_first_frame_ref):
                    return True
                return spec.first_frame is not None

            def resolve_batch_eligibility(spec: VideoTaskSpec) -> tuple[bool, str]:
                if not spec.video_prompt.strip():
                    return False, "empty_prompt"
                if not (single_take_enabled and use_first_frame_ref):
                    return True, "batch_supported_without_single_take_tail_constraints"
                if spec.first_frame is None:
                    if spec.index > 0:
                        return False, "wait_prev_tail"
                    return False, "first_frame_missing"
                if spec.last_frame is None:
                    if not supports_last_frame_flag:
                        return True, "static_first_frame_ready_model_without_last_frame"
                    last_frame_reason = str(
                        (spec.payload or {}).get("last_frame_reason") or "last_frame_missing"
                    )
                    if last_frame_reason == "no_next_shot":
                        return True, "static_first_frame_ready_no_next_shot"
                    return True, "static_first_frame_ready"
                return True, "static_first_last_ready"

            batch_provider_available = video_provider_name == "wan2gp" and callable(
                getattr(video_provider, "generate_batch", None)
            )
            batch_candidate_specs = [
                spec for spec in task_specs if not spec.skip and resolve_batch_eligibility(spec)[0]
            ]
            batch_enabled = batch_provider_available and len(batch_candidate_specs) >= 2
            logger.info(
                "[Video][BatchScheduling] provider_batch_available=%s batch_enabled=%s "
                "batch_candidates=%s batch_min_items=%d",
                batch_provider_available,
                batch_enabled,
                sorted(int(spec.key) for spec in batch_candidate_specs if str(spec.key).isdigit()),
                2,
            )
            for spec in task_specs:
                if spec.skip:
                    mode = "skip"
                    reason = "existing_asset_reused"
                    detail = None
                else:
                    eligible_for_batch, eligibility_reason = resolve_batch_eligibility(spec)
                    detail = eligibility_reason
                    if batch_enabled and eligible_for_batch:
                        mode = "batch"
                        reason = eligibility_reason
                    else:
                        mode = "single"
                        if eligible_for_batch and not batch_provider_available:
                            reason = "provider_batch_unavailable"
                        elif eligible_for_batch and len(batch_candidate_specs) < 2:
                            reason = "batch_min_items_not_met"
                        else:
                            reason = eligibility_reason
                logger.info(
                    "[Video][SchedulingDecision] shot=%d mode=%s reason=%s detail=%s first_frame=%s last_frame=%s",
                    spec.index,
                    mode,
                    reason,
                    detail,
                    str(spec.first_frame) if spec.first_frame else None,
                    str(spec.last_frame) if spec.last_frame else None,
                )

            adapter = VideoSchedulerAdapter(
                shot_count=len(shots),
                provider_name=video_provider_name,
            )
            auto_extracted_frame_paths: dict[int, Path] = {}
            live_frame_sync_lock = asyncio.Lock()

            async def generate_single(
                spec: VideoTaskSpec, progress_callback, status_callback
            ) -> dict[str, Any]:
                tmp_output_path = build_temporary_output_path(spec.output_path)
                effective_first_frame = spec.first_frame
                effective_last_frame = spec.last_frame
                last_frame_reason = str(
                    (spec.payload or {}).get("last_frame_reason")
                    or "single_take_disabled_or_first_frame_ref_disabled"
                )
                if single_take_enabled and use_first_frame_ref:
                    if spec.index > 0 and effective_first_frame is None:
                        previous_index = spec.index - 1
                        waited_rounds = 0
                        previous_video_path: Path | None = None
                        while previous_video_path is None:
                            previous_item = (
                                all_results[previous_index]
                                if 0 <= previous_index < len(all_results)
                                else None
                            )
                            if isinstance(previous_item, dict):
                                previous_error = str(previous_item.get("error") or "").strip()
                                if previous_error:
                                    raise StageValidationError(
                                        f"{SINGLE_TAKE_PREVIOUS_VIDEO_REQUIRED_ERROR}"
                                        f"（shot={spec.index}, prev={previous_index}, reason={previous_error}）"
                                    )

                            previous_video_path = self._resolve_previous_video_path(
                                previous_index=previous_index,
                                all_results=all_results,
                                existing_videos_by_index=existing_videos_by_index,
                                ignore_existing_for_indices=regenerating_indices,
                            )
                            if previous_video_path is not None:
                                break

                            if isinstance(previous_item, dict):
                                raise StageValidationError(
                                    f"{SINGLE_TAKE_PREVIOUS_VIDEO_REQUIRED_ERROR}"
                                    f"（shot={spec.index}, prev={previous_index}）"
                                )

                            if previous_index not in regenerating_indices:
                                raise StageValidationError(
                                    f"{SINGLE_TAKE_PREVIOUS_VIDEO_REQUIRED_ERROR}"
                                    f"（shot={spec.index}, prev={previous_index}）"
                                )

                            waited_rounds += 1
                            if waited_rounds == 1 or waited_rounds % 20 == 0:
                                logger.info(
                                    "[Video][SingleTake] shot=%d waiting_prev_shot=%d pending_rounds=%d",
                                    spec.index,
                                    previous_index,
                                    waited_rounds,
                                )
                            await asyncio.sleep(0.5)

                        if waited_rounds > 0:
                            logger.info(
                                "[Video][SingleTake] shot=%d resolved_prev_shot=%d after_wait_rounds=%d prev_video=%s",
                                spec.index,
                                previous_index,
                                waited_rounds,
                                str(previous_video_path),
                            )
                        if previous_video_path is None:
                            raise StageValidationError(
                                f"{SINGLE_TAKE_PREVIOUS_VIDEO_REQUIRED_ERROR}（shot={spec.index}, prev={previous_index}）"
                            )
                        previous_audio_duration = duration_map.get(previous_index)
                        if previous_audio_duration is None or previous_audio_duration <= 0:
                            raise StageValidationError(
                                f"{AUDIO_DATA_REQUIRED_ERROR}（一镜到底需要分镜位{previous_index}的音频时长）"
                            )
                        previous_video_duration = await self._probe_media_duration(
                            previous_video_path
                        )
                        if previous_video_duration is None or previous_video_duration <= 0:
                            raise StageValidationError(
                                f"无法获取分镜位{previous_index}视频时长，无法提取一镜到底首帧"
                            )
                        frame_timestamp = self._resolve_single_take_frame_timestamp(
                            audio_duration=previous_audio_duration,
                            video_duration=previous_video_duration,
                            video_fit_mode=effective_video_fit_mode,
                            audio_gap_seconds=audio_gap_seconds,
                        )
                        extracted_frame_path = frame_dir / f"frame_{spec.index:03d}.png"
                        await self._extract_video_frame(
                            video_path=previous_video_path,
                            timestamp=frame_timestamp,
                            output_path=extracted_frame_path,
                        )
                        logger.info(
                            "[Video][SingleTake] shot=%d prev_shot=%d frame_ts=%.3f frame_path=%s prev_video=%s",
                            spec.index,
                            previous_index,
                            frame_timestamp,
                            str(extracted_frame_path),
                            str(previous_video_path),
                        )
                        frame_paths_by_index[spec.index] = extracted_frame_path
                        auto_extracted_frame_paths[spec.index] = extracted_frame_path
                        try:
                            async with live_frame_sync_lock:
                                await self._sync_auto_extracted_frames_live(
                                    project_id=project.id,
                                    shots=shots,
                                    extracted_frames={spec.index: extracted_frame_path},
                                )
                        except Exception:
                            logger.warning(
                                "[Video][SingleTake] failed to sync live auto-extracted frame: "
                                "shot=%d frame_path=%s",
                                spec.index,
                                str(extracted_frame_path),
                                exc_info=True,
                            )
                        effective_first_frame = extracted_frame_path
                base_video_prompt = self._ensure_runtime_video_prompt_requirements(
                    prompt=str(spec.video_prompt or ""),
                    script_mode=script_mode,
                    speaker_id=str((spec.payload or {}).get("speaker_id") or "").strip(),
                    duo_podcast_speaker_side_by_id=duo_podcast_speaker_side_by_id,
                )
                reference_images = spec.reference_images or None

                def _build_video_prompt(last_frame: Path | None) -> str:
                    prompt_text = base_video_prompt
                    if last_frame is not None:
                        prompt_text = append_last_frame_lock_instruction(prompt_text)
                    return ensure_no_text_overlay_requirement(prompt_text)

                async def _run_provider_generation(
                    runtime_provider_name: str,
                    runtime_provider: Any,
                    runtime_provider_kwargs: dict[str, Any],
                    runtime_model: str,
                    *,
                    runtime_last_frame: Path | None,
                    reason: str,
                ) -> dict[str, Any]:
                    runtime_supports_last_frame = supports_last_frame(
                        provider_name=runtime_provider_name,
                        model=runtime_model,
                    )
                    runtime_video_prompt = _build_video_prompt(runtime_last_frame)
                    logger.info(
                        "[Video][LastFrameResolve] shot=%d single_take=%s supports_last_frame=%s "
                        "last_frame_applied=%s last_frame_path=%s reason=%s provider=%s model=%s",
                        spec.index,
                        single_take_enabled and use_first_frame_ref,
                        runtime_supports_last_frame,
                        runtime_last_frame is not None,
                        str(runtime_last_frame) if runtime_last_frame else None,
                        reason,
                        runtime_provider_name,
                        runtime_model or "unknown",
                    )

                    log_stage_separator(logger)
                    logger.info(
                        "[Video][Input] provider=%s shot=%d output=%s duration=%.3fs first_frame=%s last_frame=%s reference_images=%s",
                        runtime_provider_name,
                        spec.index,
                        str(spec.output_path),
                        float(spec.duration),
                        str(effective_first_frame) if effective_first_frame else None,
                        str(runtime_last_frame) if runtime_last_frame else None,
                        [str(path) for path in (reference_images or [])],
                    )
                    log_full_generation_prompt(
                        logger, "[Video][Input] video_prompt:", runtime_video_prompt
                    )
                    log_stage_separator(logger)

                    generate_kwargs: dict[str, Any] = {
                        "prompt": runtime_video_prompt,
                        "output_path": tmp_output_path,
                        "duration": spec.duration,
                        "first_frame": effective_first_frame,
                        "last_frame": runtime_last_frame,
                        "reference_images": reference_images,
                        "progress_callback": progress_callback,
                    }
                    if runtime_provider_name == "volcengine_seedance":
                        generate_kwargs["resolution"] = str(
                            runtime_provider_kwargs.get("resolution")
                            or settings.video_seedance_resolution
                            or "720p"
                        )
                        generate_kwargs["aspect_ratio"] = str(
                            runtime_provider_kwargs.get("aspect_ratio")
                            or settings.video_seedance_aspect_ratio
                            or "adaptive"
                        )
                    else:
                        if runtime_provider_kwargs.get("resolution"):
                            generate_kwargs["resolution"] = runtime_provider_kwargs["resolution"]
                        generate_kwargs["status_callback"] = status_callback

                    try:
                        result = await runtime_provider.generate(**generate_kwargs)
                        final_path = replace_generated_file(
                            Path(str(result.file_path)), spec.output_path
                        )
                    finally:
                        cleanup_temp_file(tmp_output_path)
                    logger.info(
                        "[Video][Output] provider=%s shot=%d file_path=%s duration=%.3fs size=%dx%d fps=%d",
                        runtime_provider_name,
                        spec.index,
                        str(final_path),
                        float(result.duration),
                        int(result.width),
                        int(result.height),
                        int(result.fps),
                    )
                    return {
                        "shot_index": spec.index,
                        "file_path": str(final_path),
                        "duration": float(result.duration),
                        "width": int(result.width),
                        "height": int(result.height),
                        "fps": int(result.fps),
                        "runtime_provider": runtime_provider_name,
                        "video_provider": runtime_provider_name,
                        "video_model": runtime_model,
                        "updated_at": int(time_module.time()),
                    }

                primary_last_frame = (
                    effective_last_frame if supports_last_frame_flag else None
                )
                try:
                    return await _run_provider_generation(
                        video_provider_name,
                        video_provider,
                        provider_kwargs,
                        effective_video_model,
                        runtime_last_frame=primary_last_frame,
                        reason=last_frame_reason,
                    )
                except Exception as primary_error:
                    if (
                        video_provider_name != "volcengine_seedance"
                        or fallback_provider_name != "wan2gp"
                        or fallback_video_provider is None
                        or fallback_provider_kwargs is None
                    ):
                        raise

                    if reference_images and not supports_reference_images(
                        provider_name=fallback_provider_name,
                        model=fallback_video_model,
                    ):
                        raise primary_error
                    if (
                        reference_images
                        and effective_first_frame is not None
                        and not supports_combined_references(
                            provider_name=fallback_provider_name,
                            model=fallback_video_model,
                        )
                    ):
                        raise primary_error

                    fallback_supports_last_frame = supports_last_frame(
                        provider_name=fallback_provider_name,
                        model=fallback_video_model,
                    )
                    fallback_last_frame = (
                        effective_last_frame if fallback_supports_last_frame else None
                    )
                    logger.warning(
                        "[Video][Fallback] primary_provider=%s primary_model=%s fallback_provider=%s fallback_model=%s shot=%d error=%s",
                        video_provider_name,
                        effective_video_model or "unknown",
                        fallback_provider_name,
                        fallback_video_model or "unknown",
                        spec.index,
                        str(primary_error),
                        exc_info=True,
                    )
                    if effective_last_frame is not None and fallback_last_frame is None:
                        logger.warning(
                            "[Video][Fallback] dropping last_frame for fallback provider: shot=%d provider=%s model=%s",
                            spec.index,
                            fallback_provider_name,
                            fallback_video_model or "unknown",
                        )
                    return await _run_provider_generation(
                        fallback_provider_name,
                        fallback_video_provider,
                        fallback_provider_kwargs,
                        fallback_video_model,
                        runtime_last_frame=fallback_last_frame,
                        reason="fallback_after_seedance_failure",
                    )

            async def generate_batch(
                specs: list[VideoTaskSpec], progress_callback, status_callback
            ):
                from app.providers.video.wan2gp import Wan2GPVideoBatchTask

                spec_by_key = {spec.key: spec for spec in specs}
                tmp_output_by_key: dict[str, Path] = {}
                finalized_output_by_key: dict[str, Path] = {}
                batch_tasks: list[Wan2GPVideoBatchTask] = []
                for spec in specs:
                    tmp_output_path = build_temporary_output_path(spec.output_path)
                    tmp_output_by_key[spec.key] = tmp_output_path
                    effective_video_prompt = self._ensure_runtime_video_prompt_requirements(
                        prompt=str(spec.video_prompt or ""),
                        script_mode=script_mode,
                        speaker_id=str((spec.payload or {}).get("speaker_id") or "").strip(),
                        duo_podcast_speaker_side_by_id=duo_podcast_speaker_side_by_id,
                    )
                    if spec.last_frame is not None:
                        effective_video_prompt = append_last_frame_lock_instruction(
                            effective_video_prompt
                        )
                    effective_video_prompt = ensure_no_text_overlay_requirement(
                        effective_video_prompt
                    )
                    log_stage_separator(logger)
                    logger.info(
                        "[Video][Batch][Input] provider=%s task=%s shot=%d output=%s duration=%.3fs first_frame=%s last_frame=%s reference_images=%s",
                        video_provider_name,
                        spec.key,
                        spec.index,
                        str(spec.output_path),
                        float(spec.duration),
                        str(spec.first_frame) if spec.first_frame else None,
                        str(spec.last_frame) if spec.last_frame else None,
                        [str(path) for path in (spec.reference_images or [])],
                    )
                    log_full_generation_prompt(
                        logger,
                        "[Video][Batch][Input] video_prompt:",
                        effective_video_prompt,
                    )
                    log_stage_separator(logger)
                    batch_tasks.append(
                        Wan2GPVideoBatchTask(
                            task_id=spec.key,
                            prompt=effective_video_prompt,
                            output_path=tmp_output_path,
                            duration=spec.duration,
                            resolution=str(provider_kwargs.get("resolution") or "").strip() or None,
                            first_frame=spec.first_frame,
                            last_frame=spec.last_frame,
                        )
                    )

                async def on_provider_progress(
                    task_id: str, progress: int, file_path: str | None
                ) -> None:
                    task_key = str(task_id)
                    spec = spec_by_key.get(task_key)
                    payload = None
                    if file_path and spec is not None and int(progress) >= 100:
                        generated_path = Path(str(file_path))
                        final_path: Path | None = None
                        detected_duration: float | None = None
                        detected_width: int | None = None
                        detected_height: int | None = None
                        try:
                            if generated_path.exists():
                                final_path = replace_generated_file(
                                    generated_path, spec.output_path
                                )
                            elif spec.output_path.exists():
                                final_path = spec.output_path
                        except Exception:
                            logger.warning(
                                "[Video][Batch] failed to finalize callback output: task=%s shot=%d file=%s",
                                task_key,
                                spec.index,
                                str(generated_path),
                                exc_info=True,
                            )
                        target_probe_path = final_path or (
                            generated_path if generated_path.exists() else None
                        )
                        if target_probe_path is not None:
                            try:
                                detected_duration = await self._probe_media_duration(
                                    target_probe_path
                                )
                            except Exception:
                                detected_duration = None
                            try:
                                (
                                    detected_width,
                                    detected_height,
                                ) = await self._probe_media_dimensions(target_probe_path)
                            except Exception:
                                detected_width = None
                                detected_height = None
                        if final_path is not None:
                            finalized_output_by_key[task_key] = final_path
                            payload = {
                                "shot_index": spec.index,
                                "file_path": str(final_path),
                                "duration": float(detected_duration)
                                if isinstance(detected_duration, (int, float))
                                and detected_duration is not None
                                else None,
                                "width": detected_width,
                                "height": detected_height,
                                "runtime_provider": video_provider_name,
                                "video_provider": video_provider_name,
                                "video_model": effective_video_model,
                                "updated_at": int(time_module.time()),
                            }
                        else:
                            payload = {
                                "shot_index": spec.index,
                                "duration": float(detected_duration)
                                if isinstance(detected_duration, (int, float))
                                and detected_duration is not None
                                else None,
                                "width": detected_width,
                                "height": detected_height,
                                "runtime_provider": video_provider_name,
                                "video_provider": video_provider_name,
                                "video_model": effective_video_model,
                                "updated_at": int(time_module.time()),
                            }
                    await progress_callback(task_key, progress, payload)

                try:
                    results = await video_provider.generate_batch(
                        batch_tasks,
                        progress_callback=on_provider_progress,
                        status_callback=status_callback,
                    )

                    mapped: dict[str, dict[str, Any]] = {}
                    for task_id, result in results.items():
                        task_key = str(task_id)
                        spec = spec_by_key.get(task_key)
                        if spec is None:
                            continue
                        generated_path = Path(str(result.file_path))
                        if generated_path.exists():
                            final_path = replace_generated_file(generated_path, spec.output_path)
                        else:
                            pre_finalized_path = finalized_output_by_key.get(task_key)
                            if pre_finalized_path is not None and pre_finalized_path.exists():
                                final_path = pre_finalized_path
                            elif spec.output_path.exists():
                                final_path = spec.output_path
                            else:
                                raise FileNotFoundError(
                                    f"Batch output missing for task={task_key}: {generated_path}"
                                )
                        logger.info(
                            "[Video][Batch][Output] provider=%s task=%s shot=%d file_path=%s duration=%.3fs size=%dx%d fps=%d",
                            video_provider_name,
                            task_key,
                            spec.index,
                            str(final_path),
                            float(result.duration),
                            int(result.width),
                            int(result.height),
                            int(result.fps),
                        )
                        mapped[task_key] = {
                            "shot_index": spec.index,
                            "file_path": str(final_path),
                            "duration": float(result.duration),
                            "width": int(result.width),
                            "height": int(result.height),
                            "fps": int(result.fps),
                            "runtime_provider": video_provider_name,
                            "video_provider": video_provider_name,
                            "video_model": effective_video_model,
                            "updated_at": int(time_module.time()),
                        }
                    return mapped
                finally:
                    for tmp_path in tmp_output_by_key.values():
                        cleanup_temp_file(tmp_path)

            stage_result = await run_scheduled_tasks(
                db=db,
                stage=stage,
                task_specs=task_specs,
                all_results=all_results,
                adapter=adapter,
                settings=SchedulerSettings(
                    provider_name=video_provider_name,
                    max_concurrency=max_concurrency,
                    allow_batch=batch_provider_available,
                    batch_min_items=2,
                    fail_on_partial=True,
                    stop_on_error=single_take_enabled,
                ),
                is_batch_eligible=is_batch_eligible,
                is_missing=lambda spec: not spec.video_prompt.strip(),
                generate_single=generate_single,
                generate_batch=generate_batch,
            )
            if auto_extracted_frame_paths:
                await self._sync_auto_extracted_frames_to_frame_stage(
                    db=db,
                    project=project,
                    shots=shots,
                    extracted_frames=auto_extracted_frame_paths,
                )
            return stage_result
        except Exception as e:  # noqa: BLE001
            logger.error("[Video] Stage failed with error: %s", str(e), exc_info=True)
            return StageResult(success=False, error=str(e))

    def _get_output_dir(self, project: Project) -> Path:
        return get_output_dir(project)

    @staticmethod
    def _build_duo_podcast_speaker_side_map(
        content_data: dict[str, Any] | None,
    ) -> dict[str, str]:
        side_by_id: dict[str, str] = {
            DUO_ROLE_1_ID: "left",
            DUO_ROLE_2_ID: "right",
        }
        if not isinstance(content_data, dict):
            return side_by_id
        roles = content_data.get("roles")
        if not isinstance(roles, list):
            return side_by_id
        for item in roles:
            if not isinstance(item, dict):
                continue
            role_id = str(item.get("id") or "").strip()
            normalized_side = str(item.get("seat_side") or "").strip().lower()
            if role_id and normalized_side in {"left", "right"}:
                side_by_id[role_id] = normalized_side
        return side_by_id

    def _ensure_runtime_video_prompt_requirements(
        self,
        *,
        prompt: str,
        script_mode: str,
        speaker_id: str,
        duo_podcast_speaker_side_by_id: dict[str, str],
    ) -> str:
        effective_prompt = str(prompt or "").strip()
        if not effective_prompt:
            return effective_prompt
        if str(script_mode or "").strip().lower() != "duo_podcast":
            return effective_prompt
        speaker_side = duo_podcast_speaker_side_by_id.get(str(speaker_id or "").strip())
        return ensure_duo_podcast_speaking_requirement(effective_prompt, speaker_side)

    async def _get_storyboard_data(self, db: AsyncSession, project: Project) -> dict | None:
        return await get_latest_stage_output(
            db,
            project.id,
            StageType.STORYBOARD,
            usable_check=is_storyboard_data_usable,
        )

    async def _get_content_data(self, db: AsyncSession, project: Project) -> dict | None:
        return await get_latest_stage_output(db, project.id, StageType.CONTENT)

    async def _get_audio_data(self, db: AsyncSession, project: Project) -> dict | None:
        return await get_latest_stage_output(
            db,
            project.id,
            StageType.AUDIO,
            usable_check=is_audio_data_usable_strict,
        )

    async def _get_frame_data(self, db: AsyncSession, project: Project) -> dict | None:
        return await get_latest_stage_output(db, project.id, StageType.FRAME)

    async def _get_frame_stage(self, db: AsyncSession, project: Project) -> StageExecution | None:
        result = await db.execute(
            select(StageExecution)
            .where(
                StageExecution.project_id == project.id,
                StageExecution.stage_type == StageType.FRAME,
            )
            .order_by(StageExecution.updated_at.desc(), StageExecution.id.desc())
        )
        return result.scalars().first()

    async def _sync_auto_extracted_frames_to_frame_stage(
        self,
        db: AsyncSession,
        project: Project,
        shots: list[dict[str, Any]],
        extracted_frames: dict[int, Path],
    ) -> None:
        if not extracted_frames:
            return
        frame_stage = await self._get_frame_stage(db, project)
        if frame_stage is None:
            logger.warning(
                "[Video][SingleTake] auto-extracted frames produced but FRAME stage not found: shots=%s",
                sorted(extracted_frames.keys()),
            )
            return

        output_data = frame_stage.output_data if isinstance(frame_stage.output_data, dict) else {}
        frame_images = output_data.get("frame_images")
        existing_items = frame_images if isinstance(frame_images, list) else []

        by_index: dict[int, dict[str, Any]] = {}
        extra_items: list[dict[str, Any]] = []
        for item in existing_items:
            if not isinstance(item, dict):
                continue
            shot_index = item.get("shot_index")
            try:
                idx = int(shot_index)
            except (TypeError, ValueError):
                extra_items.append(dict(item))
                continue
            by_index[idx] = dict(item)

        updated_at = int(time_module.time())
        for idx, frame_path in sorted(extracted_frames.items()):
            if not frame_path.exists():
                continue
            shot = shots[idx] if 0 <= idx < len(shots) and isinstance(shots[idx], dict) else {}
            item = by_index.get(idx, {})
            item["shot_index"] = idx
            item["prompt"] = str(
                shot.get("first_frame_description") or shot.get("video_prompt") or ""
            )
            item["file_path"] = str(frame_path)
            item["first_frame_description"] = shot.get("first_frame_description")
            item["generated"] = True
            item["updated_at"] = updated_at
            by_index[idx] = item

        merged_items = [by_index[idx] for idx in sorted(by_index.keys())] + extra_items
        output_data["frame_images"] = merged_items
        output_data["frame_count"] = len(shots)
        output_data["success_count"] = sum(1 for item in merged_items if item.get("generated"))
        if "runtime_provider" not in output_data:
            output_data["runtime_provider"] = "auto_single_take"
        if "image_provider" not in output_data:
            output_data["image_provider"] = (
                output_data.get("runtime_provider") or "auto_single_take"
            )

        frame_stage.output_data = output_data
        flag_modified(frame_stage, "output_data")
        await db.commit()
        logger.info(
            "[Video][SingleTake] synced auto-extracted frames to FRAME stage: shots=%s",
            sorted(extracted_frames.keys()),
        )

    async def _sync_auto_extracted_frames_live(
        self,
        project_id: int,
        shots: list[dict[str, Any]],
        extracted_frames: dict[int, Path],
    ) -> None:
        if not extracted_frames:
            return
        max_attempts = 8
        base_delay = 0.05
        for attempt in range(max_attempts):
            try:
                async with AsyncSessionLocal() as sync_db:
                    project = await sync_db.get(Project, project_id)
                    if project is None:
                        logger.warning(
                            "[Video][SingleTake] skip live frame sync because project is missing: "
                            "project_id=%s shots=%s",
                            project_id,
                            sorted(extracted_frames.keys()),
                        )
                        return
                    await self._sync_auto_extracted_frames_to_frame_stage(
                        db=sync_db,
                        project=project,
                        shots=shots,
                        extracted_frames=extracted_frames,
                    )
                    return
            except OperationalError as exc:
                message = str(exc).lower()
                is_locked = "database is locked" in message
                if not is_locked or attempt == max_attempts - 1:
                    raise
                delay = base_delay * (2**attempt)
                logger.warning(
                    "[Video][SingleTake] live frame sync database locked, retrying (%d/%d) in %.2fs: shots=%s",
                    attempt + 1,
                    max_attempts,
                    delay,
                    sorted(extracted_frames.keys()),
                )
                await asyncio.sleep(delay)

    async def _get_reference_data(self, db: AsyncSession, project: Project) -> dict | None:
        result = await db.execute(
            select(StageExecution)
            .where(
                StageExecution.project_id == project.id,
                StageExecution.stage_type == StageType.REFERENCE,
            )
            .order_by(StageExecution.updated_at.desc(), StageExecution.id.desc())
        )
        for stage in result.scalars():
            output_data = resolve_stage_payload_for_io(stage.output_data)
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
            return VIDEO_PROMPT_REQUIRED_ERROR

        audio_data = await self._get_audio_data(db, project)
        if not audio_data:
            return AUDIO_DATA_REQUIRED_ERROR

        return None

    @staticmethod
    def _is_video_prompt_valid(shot: dict[str, Any]) -> bool:
        video_prompt = shot.get("video_prompt")
        return isinstance(video_prompt, str) and video_prompt.strip() != ""

    def _is_storyboard_data_usable(self, output_data: Any) -> bool:
        return is_storyboard_data_usable(output_data)

    def _is_audio_data_usable(self, output_data: Any) -> bool:
        return is_audio_data_usable_strict(output_data)

    @staticmethod
    def _format_shot_indices(indices: list[int]) -> str:
        return ", ".join(str(i) for i in sorted(set(indices)))

    def _analyze_audio_assets(
        self,
        target_indices: list[int],
        audio_assets: list[Any],
        shot_count: int,
    ) -> tuple[dict[int, float], list[str]]:
        grouped_assets: dict[int, list[dict[str, Any]]] = {}
        for asset in audio_assets:
            if not isinstance(asset, dict):
                continue
            shot_index = asset.get("shot_index")
            if shot_index is None:
                continue
            try:
                idx = int(shot_index)
            except (TypeError, ValueError):
                continue
            if idx < 0 or idx >= shot_count:
                continue
            grouped_assets.setdefault(idx, []).append(asset)

        duration_map: dict[int, float] = {}
        missing_details: list[str] = []
        for idx in target_indices:
            candidates = grouped_assets.get(idx, [])
            if not candidates:
                missing_details.append(f"分镜位{idx}无音频记录")
                continue

            missing_reasons: list[str] = []
            found_valid = False
            for candidate in candidates:
                file_path = candidate.get("file_path")
                duration = candidate.get("duration")
                if not file_path:
                    missing_reasons.append("文件路径为空")
                    continue

                file_path_str = str(file_path)
                path = resolve_existing_path_for_io(file_path_str)
                if path is None or not path.exists():
                    missing_reasons.append(f"文件不存在({file_path_str})")
                    continue

                try:
                    duration_value = float(duration)
                except (TypeError, ValueError):
                    missing_reasons.append(f"时长无效({duration})")
                    continue
                if duration_value <= 0:
                    missing_reasons.append(f"时长无效({duration_value})")
                    continue

                duration_map[idx] = duration_value
                found_valid = True
                break

            if not found_valid:
                reason_text = (
                    " / ".join(dedupe_reasons(missing_reasons)) if missing_reasons else "资源不可用"
                )
                missing_details.append(f"分镜位{idx}{reason_text}")

        return duration_map, missing_details

    def _analyze_first_frame_assets(
        self,
        target_indices: list[int],
        frame_data: dict[str, Any] | None,
    ) -> tuple[dict[int, Path], list[str]]:
        frame_paths_by_index: dict[int, Path] = {}
        missing_details: list[str] = []
        if not isinstance(frame_data, dict):
            return frame_paths_by_index, [f"分镜位{idx}无首帧图记录" for idx in target_indices]

        frame_images = frame_data.get("frame_images", [])
        if not isinstance(frame_images, list):
            return frame_paths_by_index, [f"分镜位{idx}无首帧图记录" for idx in target_indices]

        grouped_frames: dict[int, list[dict[str, Any]]] = {}
        for frame in frame_images:
            if not isinstance(frame, dict):
                continue
            shot_index = frame.get("shot_index")
            if shot_index is None:
                continue
            try:
                idx = int(shot_index)
            except (TypeError, ValueError):
                continue
            grouped_frames.setdefault(idx, []).append(frame)

        for idx in target_indices:
            candidates = grouped_frames.get(idx, [])
            if not candidates:
                missing_details.append(f"分镜位{idx}无首帧图记录")
                continue

            missing_reasons: list[str] = []
            found_valid = False
            for candidate in candidates:
                file_path = candidate.get("file_path")
                if not file_path:
                    missing_reasons.append("文件路径为空")
                    continue
                file_path_str = str(file_path)
                path = resolve_existing_path_for_io(
                    file_path_str,
                    allowed_suffixes={".png", ".jpg", ".jpeg", ".webp"},
                )
                if path is None or not path.exists():
                    missing_reasons.append(f"文件不存在({file_path_str})")
                    continue
                frame_paths_by_index[idx] = path
                found_valid = True
                break

            if not found_valid:
                reason_text = (
                    " / ".join(dedupe_reasons(missing_reasons)) if missing_reasons else "资源不可用"
                )
                missing_details.append(f"分镜位{idx}{reason_text}")

        return frame_paths_by_index, missing_details

    def _collect_first_frame_assets(
        self,
        target_indices: list[int],
        frame_data: dict[str, Any] | None,
    ) -> dict[int, Path]:
        frame_paths_by_index, _missing_details = self._analyze_first_frame_assets(
            target_indices=target_indices,
            frame_data=frame_data,
        )
        return frame_paths_by_index

    def _analyze_reference_image_assets(
        self,
        target_indices: list[int],
        shots: list[dict[str, Any]],
        reference_data: dict[str, Any] | None,
        max_images_per_shot: int,
    ) -> tuple[dict[int, list[Path]], list[str]]:
        result: dict[int, list[Path]] = {}
        missing_details: list[str] = []

        reference_images = []
        if isinstance(reference_data, dict):
            maybe_images = reference_data.get("reference_images")
            if isinstance(maybe_images, list):
                reference_images = [item for item in maybe_images if isinstance(item, dict)]
        if not reference_images:
            return result, [f"分镜位{idx}无可用参考图记录" for idx in target_indices]

        by_reference_id: dict[str, dict[str, Any]] = {}
        for item in reference_images:
            ref_id = str(item.get("id") or "").strip()
            if not ref_id:
                continue
            by_reference_id[ref_id] = item
        allowed_reference_ids = set(by_reference_id.keys())

        for idx in target_indices:
            shot = shots[idx] if 0 <= idx < len(shots) else {}
            raw_reference_slots = shot.get("video_reference_slots")
            raw_reference_ids = extract_reference_slot_ids(raw_reference_slots)
            dedupe_ref_ids = extract_reference_slot_ids(
                raw_reference_slots,
                allowed_reference_ids=allowed_reference_ids,
            )
            if not dedupe_ref_ids:
                invalid_ids = [
                    item for item in raw_reference_ids if item not in allowed_reference_ids
                ]
                if invalid_ids:
                    missing_details.append(f"分镜位{idx}存在无效参考ID：{','.join(invalid_ids)}")
                else:
                    missing_details.append(f"分镜位{idx}未配置video_reference_slots")
                continue

            resolved_paths: list[Path] = []
            unresolved_reasons: list[str] = []
            for reference_id in dedupe_ref_ids:
                payload = by_reference_id.get(reference_id)
                if payload is None:
                    unresolved_reasons.append(f"{reference_id}缺少记录")
                    continue
                if not (payload.get("generated") or payload.get("uploaded")):
                    unresolved_reasons.append(f"{reference_id}未生成")
                    continue
                file_path = payload.get("file_path")
                if not file_path:
                    unresolved_reasons.append(f"{reference_id}文件路径为空")
                    continue
                path = resolve_existing_path_for_io(
                    file_path,
                    allowed_suffixes={".png", ".jpg", ".jpeg", ".webp"},
                )
                if path is None or not path.exists():
                    unresolved_reasons.append(f"{reference_id}文件不存在")
                    continue
                resolved_paths.append(path)

            if not resolved_paths:
                reason_text = (
                    " / ".join(dedupe_reasons(unresolved_reasons))
                    if unresolved_reasons
                    else "资源不可用"
                )
                missing_details.append(f"分镜位{idx}{reason_text}")
                continue

            if max_images_per_shot > 0 and len(resolved_paths) > max_images_per_shot:
                logger.warning(
                    "[Video] Shot %d reference images exceed limit %d, truncated from %d",
                    idx,
                    max_images_per_shot,
                    len(resolved_paths),
                )
                resolved_paths = resolved_paths[:max_images_per_shot]

            result[idx] = resolved_paths

        return result, missing_details

    @staticmethod
    def _resolve_previous_video_path(
        previous_index: int,
        all_results: list[dict[str, Any] | None],
        existing_videos_by_index: dict[int, dict[str, Any]],
        ignore_existing_for_indices: set[int] | None = None,
    ) -> Path | None:
        if previous_index < 0:
            return None

        candidates: list[Any] = []
        if previous_index < len(all_results):
            current_item = all_results[previous_index]
            if isinstance(current_item, dict):
                candidates.append(current_item.get("file_path"))
        should_ignore_existing = bool(
            ignore_existing_for_indices is not None
            and previous_index in ignore_existing_for_indices
        )
        if not should_ignore_existing:
            existing_item = existing_videos_by_index.get(previous_index)
            if isinstance(existing_item, dict):
                candidates.append(existing_item.get("file_path"))

        for file_path in candidates:
            if not file_path:
                continue
            path = resolve_existing_path_for_io(file_path)
            if path is not None and path.exists():
                return path
        return None

    @staticmethod
    async def _probe_media_duration(media_path: Path) -> float | None:
        if not media_path.exists():
            return None
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            logger.error("[Video] ffprobe not found when probing: %s", media_path)
            return None

        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            logger.warning(
                "[Video] ffprobe failed for %s: %s",
                media_path,
                (stderr.decode("utf-8", errors="ignore") or "").strip(),
            )
            return None

        text = stdout.decode("utf-8", errors="ignore").strip()
        if not text:
            return None
        try:
            value = float(text.splitlines()[-1].strip())
        except ValueError:
            return None
        if value <= 0:
            return None
        return value

    @staticmethod
    async def _probe_media_dimensions(media_path: Path) -> tuple[int | None, int | None]:
        if not media_path.exists():
            return None, None
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            str(media_path),
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            logger.error("[Video] ffprobe not found when probing dimensions: %s", media_path)
            return None, None

        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            logger.warning(
                "[Video] ffprobe dimension probe failed for %s: %s",
                media_path,
                (stderr.decode("utf-8", errors="ignore") or "").strip(),
            )
            return None, None

        text = stdout.decode("utf-8", errors="ignore").strip()
        if not text:
            return None, None
        try:
            width_text, height_text = text.split("x", maxsplit=1)
            width = int(width_text.strip())
            height = int(height_text.strip())
        except (TypeError, ValueError):
            return None, None
        if width <= 0 or height <= 0:
            return None, None
        return width, height

    @staticmethod
    def _resolve_single_take_frame_timestamp(
        audio_duration: float,
        video_duration: float,
        video_fit_mode: str,
        audio_gap_seconds: float,
    ) -> float:
        safe_video_duration = max(float(video_duration), 0.0)
        if safe_video_duration <= 0:
            return 0.0
        target_duration = max(float(audio_duration) + max(float(audio_gap_seconds), 0.0), 0.1)

        if safe_video_duration + 1e-3 < target_duration:
            return max(safe_video_duration - 0.04, 0.0)
        if str(video_fit_mode or "").strip().lower() == "truncate":
            return max(min(target_duration, safe_video_duration) - 0.04, 0.0)
        return max(safe_video_duration - 0.04, 0.0)

    @staticmethod
    async def _extract_video_frame(
        video_path: Path,
        timestamp: float,
        output_path: Path,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            try:
                output_path.unlink()
            except Exception:
                pass

        # 兜底多次尝试，避免时间戳贴近结尾导致 ffmpeg 成功但不出图。
        clamped_timestamp = max(timestamp, 0.0)
        attempts: list[tuple[str, list[str]]] = [
            (
                f"seek_exact_{clamped_timestamp:.3f}",
                [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-i",
                    str(video_path),
                    "-ss",
                    f"{clamped_timestamp:.3f}",
                    "-map",
                    "0:v:0",
                    "-frames:v",
                    "1",
                    str(output_path),
                ],
            ),
            (
                f"seek_fallback_{max(clamped_timestamp - 0.2, 0.0):.3f}",
                [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-i",
                    str(video_path),
                    "-ss",
                    f"{max(clamped_timestamp - 0.2, 0.0):.3f}",
                    "-map",
                    "0:v:0",
                    "-frames:v",
                    "1",
                    str(output_path),
                ],
            ),
            (
                "seek_last_frame",
                [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-sseof",
                    "-0.05",
                    "-i",
                    str(video_path),
                    "-map",
                    "0:v:0",
                    "-frames:v",
                    "1",
                    str(output_path),
                ],
            ),
        ]

        last_error = ""
        for attempt_name, cmd in attempts:
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError as exc:
                raise StageRuntimeError("未找到 ffmpeg，无法提取一镜到底首帧") from exc

            _, stderr = await process.communicate()
            error_text = (stderr.decode("utf-8", errors="ignore") or "").strip()
            if process.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                if attempt_name != attempts[0][0]:
                    logger.warning(
                        "[Video][SingleTake] frame extraction fallback succeeded: attempt=%s video=%s ts=%.3f output=%s",
                        attempt_name,
                        str(video_path),
                        clamped_timestamp,
                        str(output_path),
                    )
                return

            if output_path.exists():
                try:
                    output_path.unlink()
                except Exception:
                    pass
            last_error = (
                f"attempt={attempt_name} code={process.returncode} error={error_text}"
                if error_text
                else f"attempt={attempt_name} code={process.returncode} no_output"
            )

        raise StageRuntimeError(f"ffmpeg 提取首帧失败（多次尝试均未生成输出文件）: {last_error}")
