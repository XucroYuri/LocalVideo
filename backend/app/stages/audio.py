import asyncio
import hashlib
import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.dialogue import (
    DEFAULT_SINGLE_ROLE_ID,
)
from app.core.errors import StageRuntimeError, StageValidationError
from app.models.project import Project
from app.models.stage import StageExecution, StageStatus, StageType
from app.providers import get_audio_provider
from app.providers.audio.wan2gp import (
    WAN2GP_QWEN3_AUTO_DURATION_BUFFER_DEFAULT_SECONDS,
    WAN2GP_QWEN3_AUTO_DURATION_MAX_DEFAULT_SECONDS,
)
from app.services.voice_library_service import VoiceLibraryService
from app.stages.common.log_utils import log_stage_separator
from app.stages.common.paths import (
    get_output_dir,
    resolve_existing_path_for_io,
    resolve_path_for_io,
    resolve_stage_payload_for_io,
)
from app.stages.common.validators import is_shot_data_usable
from app.workflow.stage_registry import stage_registry

from . import register_stage
from ._asset_swap import build_temporary_output_path, cleanup_temp_file, replace_generated_file
from ._audio_cache import (
    SOURCE_AUDIO_SPEED,
    build_audio_render_signature,
    build_audio_source_signature,
    build_source_audio_path,
    cleanup_audio_file_variants,
    render_audio_from_source,
    resolve_audio_cache_reuse,
)
from ._audio_config import AudioConfigResolver, normalize_speed
from ._audio_split import probe_audio_duration
from ._audio_types import (
    STORYBOARD_SHOTS_REQUIRED_ERROR,
    AudioShotSchedulerAdapter,
    AudioShotTaskSpec,
    sanitize_tts_text,
)
from ._generation_log import truncate_generation_text
from .base import StageHandler, StageResult
from .task_scheduler import SchedulerSettings, run_scheduled_tasks

logger = logging.getLogger(__name__)


@register_stage(StageType.AUDIO)
class AudioHandler(StageHandler):
    async def execute(
        self,
        db: AsyncSession,
        project: Project,
        stage: StageExecution,
        input_data: dict[str, Any] | None = None,
    ) -> StageResult:
        input_data = input_data or {}
        only_shot_index = (
            input_data.get("only_shot_index")
            if input_data.get("only_shot_index") is not None
            else None
        )

        storyboard_data = await self._get_storyboard_data(db, project)
        if not storyboard_data:
            return StageResult(success=False, error=STORYBOARD_SHOTS_REQUIRED_ERROR)

        shots = storyboard_data.get("shots") or []
        if not shots:
            return StageResult(success=False, error=STORYBOARD_SHOTS_REQUIRED_ERROR)

        only_shot_index = (
            input_data.get("only_shot_index")
            if input_data.get("only_shot_index") is not None
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

        try:
            output_dir = self._get_output_dir(project)
            audio_dir = output_dir / "audio"
            audio_dir.mkdir(parents=True, exist_ok=True)

            config = project.config or {}
            audio_cfg = AudioConfigResolver.resolve(input_data, config)
            provider_name = audio_cfg.provider_name
            role_audio_configs = self._normalize_role_audio_configs(
                input_data.get("audio_role_configs")
            )
            runtime_context = await self._build_audio_runtime_context(
                db=db,
                audio_cfg=audio_cfg,
                input_data=input_data,
            )
            speaker_runtime_cache: dict[str, dict[str, Any]] = {}

            async def resolve_speaker_runtime(speaker_id: str) -> dict[str, Any]:
                normalized_speaker_id = str(speaker_id or DEFAULT_SINGLE_ROLE_ID).strip()
                if not normalized_speaker_id:
                    normalized_speaker_id = DEFAULT_SINGLE_ROLE_ID
                cached_runtime = speaker_runtime_cache.get(normalized_speaker_id)
                if cached_runtime is not None:
                    return cached_runtime
                role_audio_config = (
                    self._resolve_single_mode_role_audio_config(role_audio_configs)
                    if project.video_type == "single"
                    else dict(role_audio_configs.get(normalized_speaker_id, {}))
                )
                runtime = await self._build_speaker_runtime(
                    runtime_context=runtime_context,
                    role_audio_config=role_audio_config,
                    speaker_id=normalized_speaker_id,
                )
                speaker_runtime_cache[normalized_speaker_id] = runtime
                return runtime

            def _cleanup_shot_audio_variants(shot_index: int, keep_paths: set[Path]) -> None:
                if not force_regenerate:
                    return
                keep_path_set = {str(path) for path in keep_paths}
                patterns = (
                    f"shot_{shot_index:03d}.*",
                    f"shot_{shot_index:03d}.raw.*",
                )
                for pattern in patterns:
                    for candidate in audio_dir.glob(pattern):
                        if not candidate.is_file():
                            continue
                        if str(candidate) in keep_path_set:
                            continue
                        candidate.unlink(missing_ok=True)

            def _asset_file_exists(asset: dict[str, Any] | None) -> bool:
                if not isinstance(asset, dict):
                    return False
                file_path = str(asset.get("file_path") or "").strip()
                if not file_path:
                    return False
                path = resolve_existing_path_for_io(file_path)
                return path is not None and path.exists()

            def _coerce_int(value: Any) -> int | None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None

            wan2gp_effective_seed: int | None = None
            wan2gp_seed_anchor_shot: int | None = None

            def _next_random_seed(exclude: int | None = None) -> int:
                max_seed = 2_147_483_647
                for _ in range(8):
                    candidate = secrets.randbelow(max_seed - 1) + 1
                    if exclude is None or candidate != exclude:
                        return candidate
                return 1 if exclude is None or exclude != 1 else 2

            stage_runtime_provider_name = provider_name

            def _provider_runtime_fields() -> dict[str, Any]:
                if stage_runtime_provider_name == "mixed":
                    return {
                        "runtime_provider": "mixed",
                        "audio_provider": "mixed",
                    }
                if stage_runtime_provider_name != provider_name:
                    return {
                        "runtime_provider": stage_runtime_provider_name,
                        "audio_provider": stage_runtime_provider_name,
                    }
                if provider_name == "wan2gp":
                    return {
                        "runtime_provider": provider_name,
                        "audio_provider": provider_name,
                        "audio_wan2gp_preset": audio_cfg.wan2gp_preset,
                        "audio_wan2gp_model_mode": audio_cfg.wan2gp_model_mode,
                        "audio_wan2gp_alt_prompt": audio_cfg.wan2gp_alt_prompt,
                        "audio_wan2gp_duration_seconds": audio_cfg.wan2gp_duration_seconds,
                        "audio_wan2gp_temperature": audio_cfg.wan2gp_temperature,
                        "audio_wan2gp_top_k": audio_cfg.wan2gp_top_k,
                        "audio_wan2gp_seed": audio_cfg.wan2gp_seed,
                        "audio_wan2gp_audio_guide": audio_cfg.wan2gp_audio_guide,
                        "audio_wan2gp_speed": audio_cfg.speed,
                        "audio_wan2gp_split_strategy": audio_cfg.wan2gp_split_strategy,
                        "audio_wan2gp_local_stitch_keep_artifacts": (
                            audio_cfg.wan2gp_local_stitch_keep_artifacts
                        ),
                        "audio_wan2gp_effective_seed": wan2gp_effective_seed,
                        "audio_wan2gp_seed_anchor_shot_index": wan2gp_seed_anchor_shot,
                    }
                return {
                    "runtime_provider": provider_name,
                    "audio_provider": provider_name,
                    "voice": audio_cfg.voice,
                    "rate": audio_cfg.rate,
                    "speed": audio_cfg.speed,
                    "audio_kling_voice_id": (
                        audio_cfg.kling_voice_id if provider_name == "kling_tts" else None
                    ),
                    "audio_kling_voice_language": (
                        audio_cfg.kling_voice_language if provider_name == "kling_tts" else None
                    ),
                    "audio_vidu_voice_id": (
                        audio_cfg.vidu_voice_id if provider_name == "vidu_tts" else None
                    ),
                    "audio_vidu_speed": (
                        audio_cfg.vidu_voice_speed if provider_name == "vidu_tts" else None
                    ),
                    "audio_vidu_volume": (
                        audio_cfg.vidu_voice_volume if provider_name == "vidu_tts" else None
                    ),
                    "audio_vidu_pitch": (
                        audio_cfg.vidu_voice_pitch if provider_name == "vidu_tts" else None
                    ),
                    "audio_vidu_emotion": (
                        audio_cfg.vidu_voice_emotion if provider_name == "vidu_tts" else None
                    ),
                    "audio_minimax_model": (
                        audio_cfg.minimax_model if provider_name == "minimax_tts" else None
                    ),
                    "audio_minimax_voice_id": (
                        audio_cfg.minimax_voice_id if provider_name == "minimax_tts" else None
                    ),
                    "audio_minimax_speed": (
                        audio_cfg.minimax_voice_speed if provider_name == "minimax_tts" else None
                    ),
                    "audio_volcengine_tts_voice_type": (
                        audio_cfg.volcengine_tts_voice_type
                        if provider_name == "volcengine_tts"
                        else None
                    ),
                    "audio_volcengine_tts_speed_ratio": (
                        audio_cfg.volcengine_tts_speed_ratio
                        if provider_name == "volcengine_tts"
                        else None
                    ),
                    "audio_volcengine_tts_volume_ratio": (
                        audio_cfg.volcengine_tts_volume_ratio
                        if provider_name == "volcengine_tts"
                        else None
                    ),
                    "audio_volcengine_tts_pitch_ratio": (
                        audio_cfg.volcengine_tts_pitch_ratio
                        if provider_name == "volcengine_tts"
                        else None
                    ),
                    "audio_volcengine_tts_encoding": (
                        audio_cfg.volcengine_tts_encoding
                        if provider_name == "volcengine_tts"
                        else None
                    ),
                }

            existing_output = resolve_stage_payload_for_io(stage.output_data) or {}
            existing_audios = existing_output.get("audio_assets", [])
            existing_audios_by_index = {
                int(asset.get("shot_index")): asset
                for asset in existing_audios
                if isinstance(asset, dict) and asset.get("shot_index") is not None
            }

            if any(_asset_file_exists(asset) for asset in existing_audios_by_index.values()):
                saved_seed = _coerce_int(existing_output.get("audio_wan2gp_effective_seed"))
                if saved_seed is not None and saved_seed >= 0:
                    wan2gp_effective_seed = saved_seed

                saved_anchor = _coerce_int(
                    existing_output.get("audio_wan2gp_seed_anchor_shot_index")
                )
                if (
                    saved_anchor is not None
                    and 0 <= saved_anchor < len(shots)
                    and _asset_file_exists(existing_audios_by_index.get(saved_anchor))
                ):
                    wan2gp_seed_anchor_shot = saved_anchor

            def resolve_wan2gp_seed_for_shot(
                shot_index: int,
                has_existing_asset: bool,
                configured_seed: int,
            ) -> int:
                nonlocal wan2gp_effective_seed, wan2gp_seed_anchor_shot
                if configured_seed >= 0:
                    wan2gp_effective_seed = configured_seed
                    if wan2gp_seed_anchor_shot is None:
                        wan2gp_seed_anchor_shot = shot_index
                    return configured_seed

                if wan2gp_effective_seed is None:
                    wan2gp_effective_seed = _next_random_seed()
                    wan2gp_seed_anchor_shot = shot_index
                elif wan2gp_seed_anchor_shot == shot_index and has_existing_asset:
                    wan2gp_effective_seed = _next_random_seed(exclude=wan2gp_effective_seed)
                return wan2gp_effective_seed

            task_specs: list[AudioShotTaskSpec] = []
            for i in target_indices:
                shot = shots[i]
                voice_content = sanitize_tts_text(str(shot.get("voice_content") or ""))
                existing_asset = existing_audios_by_index.get(i)
                has_existing_asset = _asset_file_exists(existing_asset)
                should_skip = not force_regenerate and has_existing_asset
                if not should_skip and not voice_content.strip():
                    return StageResult(success=False, error=STORYBOARD_SHOTS_REQUIRED_ERROR)
                speaker_id = str(shot.get("speaker_id") or DEFAULT_SINGLE_ROLE_ID)
                speaker_name = str(shot.get("speaker_name") or "")
                runtime = await resolve_speaker_runtime(speaker_id)
                shot_provider_name = str(runtime.get("provider_name") or provider_name).strip()
                suffix = ".wav" if shot_provider_name == "wan2gp" else ".mp3"
                if shot_provider_name == "xiaomi_mimo_tts":
                    xiaomi_audio_format = (
                        str(
                            runtime.get("audio_format")
                            or settings.audio_xiaomi_mimo_format
                            or "wav"
                        )
                        .strip()
                        .lower()
                    )
                    suffix = ".mp3" if xiaomi_audio_format == "mp3" else ".wav"
                task_specs.append(
                    AudioShotTaskSpec(
                        index=i,
                        key=str(i),
                        voice_content=voice_content,
                        output_path=audio_dir / f"shot_{i:03d}{suffix}",
                        skip=should_skip,
                        payload={
                            "existing_asset": (
                                existing_asset if isinstance(existing_asset, dict) else None
                            ),
                            "has_existing_asset": has_existing_asset,
                            "speaker_id": speaker_id,
                            "speaker_name": speaker_name,
                            "provider_name": shot_provider_name,
                            "runtime": runtime,
                        },
                    )
                )

            active_provider_names = {
                str(spec.payload.get("provider_name") or "").strip()
                for spec in task_specs
                if not spec.skip
            }
            active_provider_names |= {
                str(asset.get("audio_provider") or "").strip()
                for asset in existing_audios_by_index.values()
                if isinstance(asset, dict)
            }
            active_provider_names.discard("")
            if len(active_provider_names) == 1:
                stage_runtime_provider_name = next(iter(active_provider_names))
            elif len(active_provider_names) > 1:
                stage_runtime_provider_name = "mixed"

            has_wan2gp_tasks = any(
                str(spec.payload.get("provider_name") or "").strip() == "wan2gp"
                for spec in task_specs
                if not spec.skip
            )
            if has_wan2gp_tasks:
                max_concurrency = 1
            else:
                raw_concurrency = input_data.get("max_concurrency", 4)
                try:
                    max_concurrency = max(1, int(raw_concurrency))
                except (TypeError, ValueError):
                    max_concurrency = 4

            wan2gp_batch_capable = False
            for spec in task_specs:
                if spec.skip or str(spec.payload.get("provider_name") or "").strip() != "wan2gp":
                    continue
                runtime = spec.payload.get("runtime")
                if not isinstance(runtime, dict):
                    runtime = await resolve_speaker_runtime(
                        str(spec.payload.get("speaker_id") or DEFAULT_SINGLE_ROLE_ID)
                    )
                    spec.payload["runtime"] = runtime
                batch_provider = self._get_audio_provider_cached(runtime)
                wan2gp_batch_capable = callable(getattr(batch_provider, "generate_batch", None))
                break

            all_results: list[dict[str, Any] | None] = [None] * len(shots)
            for i in range(len(shots)):
                existing_asset = existing_audios_by_index.get(i)
                if isinstance(existing_asset, dict):
                    all_results[i] = existing_asset

            adapter = AudioShotSchedulerAdapter(
                shot_count=len(shots),
                provider_runtime_fields=_provider_runtime_fields,
            )

            async def generate_single(
                spec: AudioShotTaskSpec,
                progress_callback,
                status_callback,
            ) -> dict[str, Any]:
                existing_asset = (
                    spec.payload.get("existing_asset")
                    if isinstance(spec.payload.get("existing_asset"), dict)
                    else None
                )
                has_existing_asset = bool(spec.payload.get("has_existing_asset"))
                tmp_output_path = build_temporary_output_path(spec.output_path)
                tmp_raw_output_path: Path | None = None

                speaker_id = str(spec.payload.get("speaker_id") or DEFAULT_SINGLE_ROLE_ID)
                runtime = spec.payload.get("runtime")
                if not isinstance(runtime, dict):
                    runtime = await resolve_speaker_runtime(speaker_id)
                    spec.payload["runtime"] = runtime
                shot_provider_name = str(runtime.get("provider_name") or provider_name).strip()
                audio_provider = self._get_audio_provider_cached(runtime)
                shot_speed = float(runtime.get("speed") or SOURCE_AUDIO_SPEED)
                shot_rate_percent = int((shot_speed - 1.0) * 100)
                shot_rate = (
                    f"+{shot_rate_percent}%" if shot_rate_percent >= 0 else f"{shot_rate_percent}%"
                )

                seed_for_shot = int(runtime.get("seed", -1))
                generation_config: dict[str, Any] | None = None
                generation_signature: str | None = None
                reusable_raw_path: Path | None = None
                if shot_provider_name == "wan2gp":
                    existing_seed = _coerce_int(
                        existing_asset.get("wan2gp_seed")
                        if isinstance(existing_asset, dict)
                        else None
                    )
                    if seed_for_shot < 0 and existing_seed is not None:
                        generation_config, generation_signature = (
                            self._build_wan2gp_generation_signature(
                                text=spec.voice_content,
                                preset=str(runtime["preset"]),
                                model_mode=str(runtime["model_mode"]),
                                alt_prompt=str(runtime["alt_prompt"]),
                                duration_seconds=runtime["duration_seconds"],
                                temperature=float(runtime["temperature"]),
                                top_k=int(runtime["top_k"]),
                                seed=existing_seed,
                                audio_guide=str(runtime["audio_guide"]),
                                split_strategy=str(runtime["split_strategy"]),
                            )
                        )
                        reusable_raw_path = self._can_reuse_wan2gp_raw_audio(
                            existing_asset,
                            expected_signature=str(generation_signature or ""),
                        )
                        if reusable_raw_path is not None:
                            seed_for_shot = existing_seed

                    if reusable_raw_path is None:
                        seed_for_shot = resolve_wan2gp_seed_for_shot(
                            spec.index,
                            has_existing_asset,
                            seed_for_shot,
                        )
                        generation_config, generation_signature = (
                            self._build_wan2gp_generation_signature(
                                text=spec.voice_content,
                                preset=str(runtime["preset"]),
                                model_mode=str(runtime["model_mode"]),
                                alt_prompt=str(runtime["alt_prompt"]),
                                duration_seconds=runtime["duration_seconds"],
                                temperature=float(runtime["temperature"]),
                                top_k=int(runtime["top_k"]),
                                seed=seed_for_shot,
                                audio_guide=str(runtime["audio_guide"]),
                                split_strategy=str(runtime["split_strategy"]),
                            )
                        )
                        reusable_raw_path = self._can_reuse_wan2gp_raw_audio(
                            existing_asset,
                            expected_signature=str(generation_signature or ""),
                        )

                log_stage_separator(logger)
                logger.info(
                    "[Audio][Input] provider=%s shot=%d output=%s",
                    shot_provider_name,
                    spec.index,
                    str(spec.output_path),
                )
                logger.info(
                    "[Audio][Input] voice_content: %s",
                    truncate_generation_text(spec.voice_content),
                )
                if shot_provider_name == "wan2gp":
                    logger.info(
                        "[Audio][Input] preset=%s mode=%s duration=%s temp=%.3f top_k=%d seed=%s speed=%.2fx guide=%s split_strategy=%s reusable_raw=%s",
                        str(runtime["preset"]),
                        str(runtime["model_mode"]),
                        runtime["duration_seconds"],
                        float(runtime["temperature"]),
                        int(runtime["top_k"]),
                        seed_for_shot,
                        float(shot_speed),
                        str(runtime["audio_guide"]),
                        str(runtime["split_strategy"]),
                        str(reusable_raw_path) if reusable_raw_path else None,
                    )
                else:
                    if shot_provider_name == "volcengine_tts":
                        logger.info(
                            "[Audio][Input] voice=%s speed_ratio=%.2f volume_ratio=%.2f pitch_ratio=%.2f encoding=%s",
                            str(runtime["voice"]),
                            float(shot_speed),
                            float(runtime["volume_ratio"]),
                            float(runtime["pitch_ratio"]),
                            str(runtime["encoding"]),
                        )
                    elif shot_provider_name == "xiaomi_mimo_tts":
                        logger.info(
                            "[Audio][Input] voice=%s audio_format=%s speed=%.2fx",
                            str(runtime["voice"]),
                            str(runtime["audio_format"]),
                            float(shot_speed),
                        )
                    elif shot_provider_name == "minimax_tts":
                        logger.info(
                            "[Audio][Input] voice=%s model=%s speed=%.2fx",
                            str(runtime["voice"]),
                            str(runtime["model"]),
                            float(shot_speed),
                        )
                    else:
                        logger.info(
                            "[Audio][Input] voice=%s rate=%s speed=%.2fx",
                            str(runtime["voice"]),
                            shot_rate,
                            float(shot_speed),
                        )
                log_stage_separator(logger)

                if shot_provider_name == "wan2gp":
                    tmp_raw_output_path = tmp_output_path.with_name(
                        f"{tmp_output_path.stem}.raw{tmp_output_path.suffix}"
                    )

                try:
                    if shot_provider_name == "wan2gp":
                        if reusable_raw_path is not None and callable(
                            getattr(audio_provider, "render_from_raw", None)
                        ):
                            await status_callback("变速中...")
                            result = await audio_provider.render_from_raw(
                                raw_file_path=reusable_raw_path,
                                output_path=tmp_output_path,
                                speed=float(shot_speed),
                            )
                        else:
                            result = await audio_provider.synthesize(
                                text=spec.voice_content,
                                output_path=tmp_output_path,
                                raw_output_path=tmp_raw_output_path,
                                preset=str(runtime["preset"]),
                                model_mode=str(runtime["model_mode"]),
                                alt_prompt=str(runtime["alt_prompt"]),
                                duration_seconds=runtime["duration_seconds"],
                                temperature=float(runtime["temperature"]),
                                top_k=int(runtime["top_k"]),
                                seed=seed_for_shot,
                                audio_guide=str(runtime["audio_guide"]),
                                speed=shot_speed,
                                split_strategy=str(runtime["split_strategy"]),
                                local_stitch_keep_artifacts=bool(
                                    runtime["local_stitch_keep_artifacts"]
                                ),
                                progress_callback=progress_callback,
                                status_callback=status_callback,
                            )
                    else:
                        await status_callback("生成中...")
                        if shot_provider_name == "volcengine_tts":
                            result = await audio_provider.synthesize(
                                text=spec.voice_content,
                                output_path=tmp_output_path,
                                voice=str(runtime["voice"]),
                                speed_ratio=float(shot_speed),
                                volume_ratio=float(runtime["volume_ratio"]),
                                pitch_ratio=float(runtime["pitch_ratio"]),
                                encoding=str(runtime["encoding"]),
                                resource_id=str(runtime["resource_id"]),
                                model_name=str(runtime["model_name"]),
                            )
                        elif shot_provider_name == "kling_tts":
                            result = await audio_provider.synthesize(
                                text=spec.voice_content,
                                output_path=tmp_output_path,
                                voice=str(runtime["voice"]),
                                rate=shot_rate,
                                voice_language=str(runtime["voice_language"]),
                                voice_speed=float(shot_speed),
                            )
                        elif shot_provider_name == "vidu_tts":
                            result = await audio_provider.synthesize(
                                text=spec.voice_content,
                                output_path=tmp_output_path,
                                voice=str(runtime["voice"]),
                                speed=float(shot_speed),
                                volume=float(runtime["volume"]),
                                pitch=float(runtime["pitch"]),
                                emotion=str(runtime["emotion"]),
                            )
                        elif shot_provider_name == "xiaomi_mimo_tts":
                            result = await audio_provider.synthesize(
                                text=spec.voice_content,
                                output_path=tmp_output_path,
                                voice=str(runtime["voice"]),
                                audio_format=str(runtime["audio_format"]),
                            )
                        elif shot_provider_name == "minimax_tts":
                            result = await audio_provider.synthesize(
                                text=spec.voice_content,
                                output_path=tmp_output_path,
                                voice=str(runtime["voice"]),
                                model=str(runtime["model"]),
                                speed=float(shot_speed),
                            )
                        else:
                            result = await audio_provider.synthesize(
                                text=spec.voice_content,
                                output_path=tmp_output_path,
                                voice=str(runtime["voice"]),
                                rate=shot_rate,
                            )
                        await progress_callback(99)

                    final_file_path = replace_generated_file(
                        Path(str(result.file_path)), spec.output_path
                    )
                    final_raw_path: Path | None = None
                    if shot_provider_name == "wan2gp":
                        result_raw_path = (
                            Path(str(result.source_file_path))
                            if result.source_file_path is not None
                            else None
                        )
                        if reusable_raw_path is not None and result_raw_path == reusable_raw_path:
                            final_raw_path = reusable_raw_path
                        elif result_raw_path is not None and result_raw_path.exists():
                            raw_target = final_file_path.with_name(
                                f"{final_file_path.stem}.raw{final_file_path.suffix}"
                            )
                            final_raw_path = replace_generated_file(result_raw_path, raw_target)
                        _cleanup_shot_audio_variants(
                            spec.index,
                            {
                                path
                                for path in (final_file_path, final_raw_path)
                                if path is not None
                            },
                        )
                finally:
                    cleanup_temp_file(tmp_output_path)
                    cleanup_temp_file(tmp_raw_output_path)

                logger.info(
                    "[Audio][Output] provider=%s shot=%d file_path=%s duration=%.3fs raw_file_path=%s",
                    shot_provider_name,
                    spec.index,
                    str(final_file_path),
                    float(result.duration),
                    (
                        str(final_raw_path)
                        if shot_provider_name == "wan2gp" and final_raw_path is not None
                        else None
                    ),
                )

                return {
                    "shot_index": spec.index,
                    "file_path": str(final_file_path),
                    "duration": float(result.duration),
                    "voice_content": spec.voice_content,
                    "audio_provider": shot_provider_name,
                    "wan2gp_seed": seed_for_shot if shot_provider_name == "wan2gp" else None,
                    "raw_file_path": (
                        str(final_raw_path)
                        if shot_provider_name == "wan2gp" and final_raw_path is not None
                        else None
                    ),
                    "wan2gp_generation_config": generation_config
                    if shot_provider_name == "wan2gp"
                    else None,
                    "wan2gp_generation_signature": (
                        generation_signature if shot_provider_name == "wan2gp" else None
                    ),
                    "audio_speed": float(shot_speed)
                    if shot_provider_name == "wan2gp"
                    else shot_speed,
                    "speaker_id": speaker_id,
                    "speaker_name": str(spec.payload.get("speaker_name") or ""),
                    "updated_at": int(time.time()),
                }

            async def generate_batch(
                specs: list[AudioShotTaskSpec],
                progress_callback,
                status_callback,
            ) -> dict[str, dict[str, Any]]:
                from app.providers.audio.wan2gp import Wan2GPAudioBatchTask

                spec_by_key = {spec.key: spec for spec in specs}
                batch_meta: dict[str, dict[str, Any]] = {}
                tmp_output_by_key: dict[str, Path] = {}
                batch_tasks: list[Wan2GPAudioBatchTask] = []
                batch_audio_provider = None
                for spec in specs:
                    speaker_id = str(spec.payload.get("speaker_id") or DEFAULT_SINGLE_ROLE_ID)
                    runtime = spec.payload.get("runtime")
                    if not isinstance(runtime, dict):
                        runtime = await resolve_speaker_runtime(speaker_id)
                        spec.payload["runtime"] = runtime
                    shot_provider_name = str(runtime.get("provider_name") or provider_name).strip()
                    if shot_provider_name != "wan2gp":
                        raise StageValidationError("批量音频仅支持 Wan2GP provider")
                    if batch_audio_provider is None:
                        batch_audio_provider = self._get_audio_provider_cached(runtime)
                    has_existing_asset = bool(spec.payload.get("has_existing_asset"))
                    seed_for_shot = resolve_wan2gp_seed_for_shot(
                        spec.index,
                        has_existing_asset,
                        int(runtime.get("seed", -1)),
                    )
                    generation_config, generation_signature = (
                        self._build_wan2gp_generation_signature(
                            text=spec.voice_content,
                            preset=str(runtime["preset"]),
                            model_mode=str(runtime["model_mode"]),
                            alt_prompt=str(runtime["alt_prompt"]),
                            duration_seconds=runtime["duration_seconds"],
                            temperature=float(runtime["temperature"]),
                            top_k=int(runtime["top_k"]),
                            seed=seed_for_shot,
                            audio_guide=str(runtime["audio_guide"]),
                            split_strategy=str(runtime["split_strategy"]),
                        )
                    )
                    tmp_output_path = build_temporary_output_path(spec.output_path)
                    tmp_output_by_key[spec.key] = tmp_output_path
                    batch_meta[spec.key] = {
                        "index": spec.index,
                        "voice_content": spec.voice_content,
                        "seed": seed_for_shot,
                        "speed": float(runtime["speed"]),
                        "speaker_id": speaker_id,
                        "speaker_name": str(spec.payload.get("speaker_name") or ""),
                        "audio_provider": shot_provider_name,
                        "generation_config": generation_config,
                        "generation_signature": generation_signature,
                    }
                    log_stage_separator(logger)
                    logger.info(
                        "[Audio][Batch][Input] provider=%s task=%s shot=%d output=%s",
                        shot_provider_name,
                        spec.key,
                        spec.index,
                        str(spec.output_path),
                    )
                    logger.info(
                        "[Audio][Batch][Input] voice_content: %s",
                        truncate_generation_text(spec.voice_content),
                    )
                    logger.info(
                        "[Audio][Batch][Input] preset=%s mode=%s duration=%s temp=%.3f top_k=%d seed=%s speed=%.2fx guide=%s split_strategy=%s",
                        str(runtime["preset"]),
                        str(runtime["model_mode"]),
                        runtime["duration_seconds"],
                        float(runtime["temperature"]),
                        int(runtime["top_k"]),
                        seed_for_shot,
                        float(runtime["speed"]),
                        str(runtime["audio_guide"]),
                        str(runtime["split_strategy"]),
                    )
                    log_stage_separator(logger)
                    batch_tasks.append(
                        Wan2GPAudioBatchTask(
                            task_id=spec.key,
                            text=spec.voice_content,
                            output_path=tmp_output_path,
                            preset=str(runtime["preset"]),
                            model_mode=str(runtime["model_mode"]),
                            alt_prompt=str(runtime["alt_prompt"]),
                            duration_seconds=runtime["duration_seconds"],
                            temperature=float(runtime["temperature"]),
                            top_k=int(runtime["top_k"]),
                            seed=seed_for_shot,
                            audio_guide=str(runtime["audio_guide"]),
                            speed=float(runtime["speed"]),
                            split_strategy=str(runtime["split_strategy"]),
                            local_stitch_keep_artifacts=bool(
                                runtime["local_stitch_keep_artifacts"]
                            ),
                        )
                    )

                async def on_provider_progress(
                    task_id: str,
                    progress: int,
                    file_path: str | None,
                ) -> None:
                    meta = batch_meta.get(str(task_id))
                    payload = None
                    if file_path and meta is not None:
                        detected_duration = 0.0
                        try:
                            detected_duration = await probe_audio_duration(Path(str(file_path)))
                        except Exception:
                            detected_duration = 0.0
                        payload = {
                            "shot_index": int(meta["index"]),
                            "file_path": str(file_path),
                            "duration": float(detected_duration),
                            "voice_content": str(meta["voice_content"] or ""),
                            "audio_provider": str(meta["audio_provider"] or ""),
                            "wan2gp_seed": int(meta["seed"]),
                            "wan2gp_generation_config": meta.get("generation_config"),
                            "wan2gp_generation_signature": meta.get("generation_signature"),
                            "audio_speed": float(meta.get("speed") or 1.0),
                            "speaker_id": str(meta["speaker_id"] or ""),
                            "speaker_name": str(meta["speaker_name"] or ""),
                            "updated_at": int(time.time()),
                        }
                    await progress_callback(str(task_id), progress, payload)

                try:
                    if batch_audio_provider is None:
                        raise StageValidationError("Wan2GP 批量 provider 初始化失败")
                    results = await batch_audio_provider.generate_batch(
                        batch_tasks,
                        progress_callback=on_provider_progress,
                        status_callback=status_callback,
                    )

                    mapped: dict[str, dict[str, Any]] = {}
                    for task_id, result in results.items():
                        key = str(task_id)
                        meta = batch_meta.get(key)
                        spec = spec_by_key.get(key)
                        if meta is None or spec is None:
                            continue

                        final_file_path = replace_generated_file(
                            Path(str(result.file_path)),
                            spec.output_path,
                        )
                        final_raw_path: Path | None = None
                        if result.source_file_path is not None:
                            raw_source = Path(str(result.source_file_path))
                            if raw_source.exists():
                                raw_target = final_file_path.with_name(
                                    f"{final_file_path.stem}.raw{final_file_path.suffix}"
                                )
                                final_raw_path = replace_generated_file(raw_source, raw_target)

                        _cleanup_shot_audio_variants(
                            spec.index,
                            {
                                path
                                for path in (final_file_path, final_raw_path)
                                if path is not None
                            },
                        )
                        logger.info(
                            "[Audio][Batch][Output] provider=%s task=%s shot=%d file_path=%s duration=%.3fs raw_file_path=%s",
                            str(meta["audio_provider"] or "wan2gp"),
                            key,
                            int(meta["index"]),
                            str(final_file_path),
                            float(result.duration),
                            str(final_raw_path) if final_raw_path is not None else None,
                        )
                        mapped[key] = {
                            "shot_index": int(meta["index"]),
                            "file_path": str(final_file_path),
                            "duration": float(result.duration),
                            "voice_content": str(meta["voice_content"] or ""),
                            "audio_provider": str(meta["audio_provider"] or "wan2gp"),
                            "wan2gp_seed": int(meta["seed"]),
                            "raw_file_path": str(final_raw_path)
                            if final_raw_path is not None
                            else None,
                            "wan2gp_generation_config": meta.get("generation_config"),
                            "wan2gp_generation_signature": meta.get("generation_signature"),
                            "audio_speed": float(meta.get("speed") or 1.0),
                            "speaker_id": str(meta["speaker_id"] or ""),
                            "speaker_name": str(meta["speaker_name"] or ""),
                            "updated_at": int(time.time()),
                        }
                    return mapped
                finally:
                    for tmp_path in tmp_output_by_key.values():
                        cleanup_temp_file(tmp_path)
                        cleanup_temp_file(
                            tmp_path.with_name(f"{tmp_path.stem}.raw{tmp_path.suffix}")
                        )

            return await run_scheduled_tasks(
                db=db,
                stage=stage,
                task_specs=task_specs,
                all_results=all_results,
                adapter=adapter,
                settings=SchedulerSettings(
                    provider_name=stage_runtime_provider_name,
                    max_concurrency=max_concurrency,
                    allow_batch=wan2gp_batch_capable,
                    batch_min_items=2,
                    fail_on_partial=True,
                    default_start_message=(
                        "准备中..." if stage_runtime_provider_name == "wan2gp" else "准备中..."
                    ),
                ),
                is_batch_eligible=lambda spec: (
                    bool(spec.voice_content.strip())
                    and str(spec.payload.get("provider_name") or "").strip() == "wan2gp"
                ),
                is_missing=lambda spec: not spec.voice_content.strip(),
                generate_single=generate_single,
                generate_batch=generate_batch,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("[Audio] Shot audio generation failed")
            return StageResult(success=False, error=str(e))

    async def _build_audio_runtime_context(
        self,
        *,
        db: AsyncSession,
        audio_cfg: AudioConfigResolver,
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "audio_cfg": audio_cfg,
            "provider_cache": {},
            "voice_library_service": VoiceLibraryService(db),
            "resolved_voice_cache": {},
            "input_data": input_data,
        }

    async def _build_speaker_runtime(
        self,
        *,
        runtime_context: dict[str, Any],
        role_audio_config: dict[str, Any],
        speaker_id: str,
    ) -> dict[str, Any]:
        audio_cfg: AudioConfigResolver = runtime_context["audio_cfg"]
        provider_name = (
            str(role_audio_config.get("audio_provider") or audio_cfg.provider_name or "edge_tts")
            .strip()
            .lower()
        )
        if provider_name not in {
            "edge_tts",
            "wan2gp",
            "volcengine_tts",
            "kling_tts",
            "vidu_tts",
            "minimax_tts",
            "xiaomi_mimo_tts",
        }:
            provider_name = "edge_tts"

        runtime: dict[str, Any] = {
            "provider_name": provider_name,
            "speaker_id": speaker_id,
            "speed": self._resolve_target_speed(
                role_audio_config=role_audio_config,
                provider_name=provider_name,
                audio_cfg=audio_cfg,
            ),
            "_provider_cache": runtime_context["provider_cache"],
        }
        if provider_name == "wan2gp":
            audio_guide = str(
                role_audio_config.get("audio_wan2gp_audio_guide")
                if role_audio_config.get("audio_wan2gp_audio_guide") is not None
                else audio_cfg.wan2gp_audio_guide
            ).strip()
            alt_prompt = (
                role_audio_config.get("audio_wan2gp_alt_prompt")
                if role_audio_config.get("audio_wan2gp_alt_prompt") is not None
                else audio_cfg.wan2gp_alt_prompt
            )
            preset = (
                str(role_audio_config.get("audio_wan2gp_preset") or audio_cfg.wan2gp_preset).strip()
                or "qwen3_tts_base"
            )
            model_mode = str(
                role_audio_config.get("audio_wan2gp_model_mode") or audio_cfg.wan2gp_model_mode
            ).strip()
            if preset == "qwen3_tts_base":
                audio_guide, alt_prompt = await self._resolve_wan2gp_base_voice(
                    runtime_context=runtime_context,
                    raw_audio_guide=audio_guide,
                )
            runtime.update(
                {
                    "preset": preset,
                    "model_mode": model_mode,
                    "alt_prompt": str(alt_prompt or ""),
                    "audio_guide": self._resolve_provider_audio_guide_path(audio_guide),
                    "duration_seconds": (
                        int(role_audio_config.get("audio_wan2gp_duration_seconds"))
                        if role_audio_config.get("audio_wan2gp_duration_seconds") is not None
                        else audio_cfg.wan2gp_duration_seconds
                    ),
                    "temperature": float(
                        role_audio_config.get("audio_wan2gp_temperature")
                        if role_audio_config.get("audio_wan2gp_temperature") is not None
                        else audio_cfg.wan2gp_temperature
                    ),
                    "top_k": int(
                        role_audio_config.get("audio_wan2gp_top_k")
                        if role_audio_config.get("audio_wan2gp_top_k") is not None
                        else audio_cfg.wan2gp_top_k
                    ),
                    "seed": int(
                        role_audio_config.get("audio_wan2gp_seed")
                        if role_audio_config.get("audio_wan2gp_seed") is not None
                        else audio_cfg.wan2gp_seed
                    ),
                    "split_strategy": str(
                        role_audio_config.get("audio_wan2gp_split_strategy")
                        if role_audio_config.get("audio_wan2gp_split_strategy") is not None
                        else audio_cfg.wan2gp_split_strategy
                    ).strip()
                    or "sentence_punct",
                    "local_stitch_keep_artifacts": (
                        role_audio_config.get("audio_wan2gp_local_stitch_keep_artifacts")
                        if role_audio_config.get("audio_wan2gp_local_stitch_keep_artifacts")
                        is not None
                        else audio_cfg.wan2gp_local_stitch_keep_artifacts
                    ),
                }
            )
            return runtime

        if provider_name == "volcengine_tts":
            runtime.update(
                {
                    "voice": str(
                        role_audio_config.get("voice")
                        or role_audio_config.get("audio_volcengine_tts_voice_type")
                        or audio_cfg.volcengine_tts_voice_type
                    ).strip(),
                    "volume_ratio": normalize_speed(
                        role_audio_config.get("audio_volcengine_tts_volume_ratio"),
                        audio_cfg.volcengine_tts_volume_ratio,
                    ),
                    "pitch_ratio": normalize_speed(
                        role_audio_config.get("audio_volcengine_tts_pitch_ratio"),
                        audio_cfg.volcengine_tts_pitch_ratio,
                    ),
                    "encoding": str(
                        role_audio_config.get("audio_volcengine_tts_encoding")
                        or audio_cfg.volcengine_tts_encoding
                        or "mp3"
                    ).strip()
                    or "mp3",
                    "resource_id": audio_cfg.volcengine_tts_resource_id,
                    "model_name": audio_cfg.volcengine_tts_model_name,
                }
            )
            return runtime

        if provider_name == "kling_tts":
            runtime.update(
                {
                    "voice": str(
                        role_audio_config.get("voice")
                        or role_audio_config.get("audio_kling_voice_id")
                        or audio_cfg.kling_voice_id
                    ).strip(),
                    "voice_language": str(
                        role_audio_config.get("audio_kling_voice_language")
                        or audio_cfg.kling_voice_language
                        or "zh"
                    ).strip()
                    or "zh",
                }
            )
            return runtime

        if provider_name == "vidu_tts":
            runtime.update(
                {
                    "voice": str(
                        role_audio_config.get("voice")
                        or role_audio_config.get("audio_vidu_voice_id")
                        or audio_cfg.vidu_voice_id
                    ).strip(),
                    "volume": float(
                        role_audio_config.get("audio_vidu_volume")
                        if role_audio_config.get("audio_vidu_volume") is not None
                        else audio_cfg.vidu_voice_volume
                    ),
                    "pitch": float(
                        role_audio_config.get("audio_vidu_pitch")
                        if role_audio_config.get("audio_vidu_pitch") is not None
                        else audio_cfg.vidu_voice_pitch
                    ),
                    "emotion": str(
                        role_audio_config.get("audio_vidu_emotion")
                        if role_audio_config.get("audio_vidu_emotion") is not None
                        else audio_cfg.vidu_voice_emotion
                    ).strip(),
                }
            )
            return runtime

        if provider_name == "minimax_tts":
            runtime.update(
                {
                    "voice": str(
                        role_audio_config.get("voice")
                        or role_audio_config.get("audio_minimax_voice_id")
                        or audio_cfg.minimax_voice_id
                    ).strip(),
                    "model": str(
                        role_audio_config.get("audio_minimax_model") or audio_cfg.minimax_model
                    ).strip()
                    or audio_cfg.minimax_model,
                }
            )
            return runtime

        if provider_name == "xiaomi_mimo_tts":
            runtime.update(
                {
                    "voice": str(
                        role_audio_config.get("voice")
                        or role_audio_config.get("audio_xiaomi_mimo_voice")
                        or audio_cfg.xiaomi_mimo_voice
                    ).strip()
                    or audio_cfg.xiaomi_mimo_voice,
                    "style_preset": str(
                        role_audio_config.get("audio_xiaomi_mimo_style_preset")
                        or audio_cfg.xiaomi_mimo_style_preset
                    ).strip(),
                    "audio_format": str(
                        role_audio_config.get("audio_xiaomi_mimo_format")
                        or settings.audio_xiaomi_mimo_format
                        or "wav"
                    )
                    .strip()
                    .lower()
                    or "wav",
                }
            )
            return runtime

        runtime.update(
            {
                "voice": str(role_audio_config.get("voice") or audio_cfg.voice).strip(),
                "rate": audio_cfg.rate,
            }
        )
        return runtime

    async def _resolve_wan2gp_base_voice(
        self,
        *,
        runtime_context: dict[str, Any],
        raw_audio_guide: Any,
    ) -> tuple[str, str]:
        key = str(raw_audio_guide or "").strip()
        if not key:
            raise StageValidationError(
                "Wan2GP Qwen3 Base 需要从语音库选择一个已启用且有音频的预设。"
            )
        resolved_cache: dict[str, tuple[str, str]] = runtime_context["resolved_voice_cache"]
        if key in resolved_cache:
            return resolved_cache[key]
        voice_library_service: VoiceLibraryService = runtime_context["voice_library_service"]
        matched = await voice_library_service.resolve_active_voice_by_audio_path(key)
        if not matched or not str(matched.audio_file_path or "").strip():
            raise StageValidationError("Wan2GP Qwen3 Base 仅支持语音库中已启用且有音频文件的预设。")
        resolved = (
            str(matched.audio_file_path or "").strip(),
            str(matched.reference_text or ""),
        )
        resolved_cache[key] = resolved
        return resolved

    def _resolve_target_speed(
        self,
        *,
        role_audio_config: dict[str, Any],
        provider_name: str,
        audio_cfg: AudioConfigResolver,
    ) -> float:
        if role_audio_config.get("speed") is not None:
            return normalize_speed(role_audio_config.get("speed"), SOURCE_AUDIO_SPEED)
        if provider_name == "edge_tts":
            return self._rate_to_speed(audio_cfg.rate)
        if provider_name == "volcengine_tts":
            return normalize_speed(audio_cfg.volcengine_tts_speed_ratio, SOURCE_AUDIO_SPEED)
        if provider_name == "kling_tts":
            return normalize_speed(audio_cfg.speed, SOURCE_AUDIO_SPEED)
        if provider_name == "vidu_tts":
            return normalize_speed(audio_cfg.vidu_voice_speed, SOURCE_AUDIO_SPEED)
        if provider_name == "minimax_tts":
            return normalize_speed(audio_cfg.minimax_voice_speed, SOURCE_AUDIO_SPEED)
        if provider_name == "xiaomi_mimo_tts":
            return normalize_speed(audio_cfg.speed, SOURCE_AUDIO_SPEED)
        return normalize_speed(audio_cfg.speed, SOURCE_AUDIO_SPEED)

    async def _render_or_reuse_audio_asset(
        self,
        *,
        existing_asset: dict[str, Any] | None,
        text: str,
        render_output_path: Path,
        runtime: dict[str, Any],
        force_regenerate: bool,
    ) -> tuple[dict[str, Any], bool]:
        provider_name = str(runtime["provider_name"])
        source_output_path = build_source_audio_path(render_output_path)
        source_signature = build_audio_source_signature(
            provider_name=provider_name,
            text=text,
            config=self._build_source_signature_config(runtime),
        )
        render_signature = build_audio_render_signature(
            audio_source_signature=source_signature,
            speed=float(runtime["speed"]),
        )
        reuse = resolve_audio_cache_reuse(
            existing_asset=existing_asset,
            audio_source_signature=source_signature,
            audio_render_signature=render_signature,
            force_regenerate=force_regenerate,
        )
        if reuse.reuse_render and isinstance(existing_asset, dict):
            existing_render_path = resolve_path_for_io(existing_asset.get("file_path"))
            existing_source_path = resolve_path_for_io(existing_asset.get("source_file_path"))
            cleanup_audio_file_variants(
                target_path=render_output_path,
                keep_path=existing_render_path,
            )
            cleanup_audio_file_variants(
                target_path=source_output_path,
                keep_path=existing_source_path,
            )
            asset = dict(existing_asset)
            asset["audio_source_signature"] = source_signature
            asset["audio_render_signature"] = render_signature
            asset["source_audio_speed"] = SOURCE_AUDIO_SPEED
            asset["audio_speed"] = float(runtime["speed"])
            return asset, False

        changed = True
        if reuse.reuse_source and reuse.source_file_path is not None:
            await render_audio_from_source(
                source_file_path=reuse.source_file_path,
                output_path=render_output_path,
                speed=float(runtime["speed"]),
            )
            source_file_path = reuse.source_file_path
            cleanup_audio_file_variants(
                target_path=source_output_path,
                keep_path=source_file_path,
            )
            cleanup_audio_file_variants(
                target_path=render_output_path,
                keep_path=render_output_path if render_output_path.exists() else None,
            )
        else:
            provider = self._get_audio_provider_cached(runtime)
            tmp_source_output_path = build_temporary_output_path(source_output_path)
            tmp_render_output_path = build_temporary_output_path(render_output_path)
            tmp_source_sidecar_path = build_source_audio_path(tmp_source_output_path)
            try:
                synthesis = await provider.synthesize(
                    text=text,
                    output_path=tmp_source_output_path,
                    **self._build_source_synthesize_kwargs(runtime),
                )
                source_candidate = (
                    Path(str(synthesis.source_file_path))
                    if synthesis.source_file_path is not None
                    else Path(str(synthesis.file_path))
                )
                final_source_output_path = replace_generated_file(
                    source_candidate, source_output_path
                )
                await render_audio_from_source(
                    source_file_path=final_source_output_path,
                    output_path=tmp_render_output_path,
                    speed=float(runtime["speed"]),
                )
                final_render_output_path = replace_generated_file(
                    tmp_render_output_path,
                    render_output_path,
                )
                cleanup_audio_file_variants(
                    target_path=source_output_path,
                    keep_path=final_source_output_path,
                )
                cleanup_audio_file_variants(
                    target_path=render_output_path,
                    keep_path=final_render_output_path,
                )
                source_file_path = final_source_output_path
            finally:
                cleanup_temp_file(tmp_source_output_path)
                cleanup_temp_file(tmp_source_sidecar_path)
                cleanup_temp_file(tmp_render_output_path)

        duration = await probe_audio_duration(render_output_path)
        return (
            {
                "file_path": str(render_output_path),
                "source_file_path": str(source_file_path),
                "audio_source_signature": source_signature,
                "audio_render_signature": render_signature,
                "source_audio_speed": SOURCE_AUDIO_SPEED,
                "audio_speed": float(runtime["speed"]),
                "duration": duration,
            },
            changed,
        )

    def _build_source_signature_config(self, runtime: dict[str, Any]) -> dict[str, Any]:
        provider_name = str(runtime["provider_name"])
        if provider_name == "wan2gp":
            return {
                "preset": runtime["preset"],
                "model_mode": runtime["model_mode"],
                "alt_prompt": runtime["alt_prompt"],
                "audio_guide": runtime["audio_guide"],
                "duration_seconds": runtime["duration_seconds"],
                "temperature": runtime["temperature"],
                "top_k": runtime["top_k"],
                "seed": runtime["seed"],
                "split_strategy": runtime["split_strategy"],
            }
        if provider_name == "volcengine_tts":
            return {
                "voice": runtime["voice"],
                "volume_ratio": runtime["volume_ratio"],
                "pitch_ratio": runtime["pitch_ratio"],
                "encoding": runtime["encoding"],
                "resource_id": runtime["resource_id"],
                "model_name": runtime["model_name"],
            }
        if provider_name == "kling_tts":
            return {
                "voice": runtime["voice"],
                "voice_language": runtime["voice_language"],
            }
        if provider_name == "vidu_tts":
            return {
                "voice": runtime["voice"],
                "volume": runtime["volume"],
                "pitch": runtime["pitch"],
                "emotion": runtime["emotion"],
            }
        if provider_name == "xiaomi_mimo_tts":
            return {
                "voice": runtime["voice"],
                "style_preset": runtime["style_preset"],
                "audio_format": runtime["audio_format"],
            }
        if provider_name == "minimax_tts":
            return {
                "voice": runtime["voice"],
                "model": runtime["model"],
            }
        return {"voice": runtime["voice"]}

    def _build_source_synthesize_kwargs(self, runtime: dict[str, Any]) -> dict[str, Any]:
        provider_name = str(runtime["provider_name"])
        if provider_name == "wan2gp":
            return {
                "preset": runtime["preset"],
                "model_mode": runtime["model_mode"],
                "alt_prompt": runtime["alt_prompt"],
                "duration_seconds": runtime["duration_seconds"],
                "temperature": runtime["temperature"],
                "top_k": runtime["top_k"],
                "seed": runtime["seed"],
                "audio_guide": runtime["audio_guide"],
                "speed": SOURCE_AUDIO_SPEED,
                "split_strategy": runtime["split_strategy"],
                "local_stitch_keep_artifacts": runtime["local_stitch_keep_artifacts"],
            }
        if provider_name == "volcengine_tts":
            return {
                "voice": runtime["voice"],
                "speed_ratio": SOURCE_AUDIO_SPEED,
                "volume_ratio": runtime["volume_ratio"],
                "pitch_ratio": runtime["pitch_ratio"],
                "encoding": runtime["encoding"],
                "resource_id": runtime["resource_id"],
                "model_name": runtime["model_name"],
            }
        if provider_name == "kling_tts":
            return {
                "voice": runtime["voice"],
                "rate": "+0%",
                "voice_language": runtime["voice_language"],
                "voice_speed": SOURCE_AUDIO_SPEED,
            }
        if provider_name == "vidu_tts":
            return {
                "voice": runtime["voice"],
                "speed": SOURCE_AUDIO_SPEED,
                "volume": runtime["volume"],
                "pitch": runtime["pitch"],
                "emotion": runtime["emotion"],
            }
        if provider_name == "xiaomi_mimo_tts":
            return {
                "voice": runtime["voice"],
                "audio_xiaomi_mimo_style_preset": runtime["style_preset"],
                "audio_format": runtime["audio_format"],
            }
        if provider_name == "minimax_tts":
            return {
                "voice": runtime["voice"],
                "model": runtime["model"],
                "speed": SOURCE_AUDIO_SPEED,
            }
        return {
            "voice": runtime["voice"],
            "rate": "+0%",
        }

    def _get_audio_provider_cached(self, runtime: dict[str, Any]):
        provider_name = str(runtime["provider_name"])
        provider_cache = runtime.setdefault("_provider_cache", {})
        cached = provider_cache.get(provider_name)
        if cached is not None:
            return cached
        provider_kwargs: dict[str, Any] = {}
        if provider_name == "wan2gp":
            provider_kwargs["wan2gp_path"] = settings.wan2gp_path
            provider_kwargs["python_executable"] = settings.local_model_python_path
            provider_kwargs["speed"] = SOURCE_AUDIO_SPEED
        elif provider_name == "volcengine_tts":
            provider_kwargs["app_key"] = settings.volcengine_tts_app_key or ""
            provider_kwargs["access_key"] = settings.volcengine_tts_access_key or ""
            provider_kwargs["model_name"] = runtime["model_name"]
        elif provider_name == "kling_tts":
            provider_kwargs["access_key"] = settings.kling_access_key or ""
            provider_kwargs["secret_key"] = settings.kling_secret_key or ""
            provider_kwargs["base_url"] = settings.kling_base_url
            provider_kwargs["voice_id"] = runtime["voice"]
            provider_kwargs["voice_language"] = runtime["voice_language"]
            provider_kwargs["voice_speed"] = SOURCE_AUDIO_SPEED
        elif provider_name == "vidu_tts":
            provider_kwargs["api_key"] = settings.vidu_api_key or ""
            provider_kwargs["base_url"] = settings.vidu_base_url
            provider_kwargs["voice_id"] = runtime["voice"]
            provider_kwargs["speed"] = SOURCE_AUDIO_SPEED
            provider_kwargs["volume"] = runtime["volume"]
            provider_kwargs["pitch"] = runtime["pitch"]
            provider_kwargs["emotion"] = runtime["emotion"]
        elif provider_name == "minimax_tts":
            provider_kwargs["api_key"] = settings.minimax_api_key or ""
            provider_kwargs["base_url"] = settings.minimax_base_url
            provider_kwargs["model"] = runtime["model"]
            provider_kwargs["voice_id"] = runtime["voice"]
            provider_kwargs["speed"] = SOURCE_AUDIO_SPEED
        elif provider_name == "xiaomi_mimo_tts":
            provider_kwargs["api_key"] = settings.xiaomi_mimo_api_key or ""
            provider_kwargs["base_url"] = settings.xiaomi_mimo_base_url
        cached = get_audio_provider(provider_name, **provider_kwargs)
        provider_cache[provider_name] = cached
        return cached

    @staticmethod
    def _resolve_runtime_provider_name(assets: list[dict[str, Any]]) -> str:
        providers = {
            str(asset.get("audio_provider") or "").strip()
            for asset in assets
            if isinstance(asset, dict)
        }
        providers.discard("")
        if len(providers) == 1:
            return next(iter(providers))
        if len(providers) > 1:
            return "mixed"
        return "edge_tts"

    @staticmethod
    def _resolve_single_mode_role_audio_config(
        role_audio_configs: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        single_role_config = (
            dict(role_audio_configs.get(DEFAULT_SINGLE_ROLE_ID, {}))
            if isinstance(role_audio_configs.get(DEFAULT_SINGLE_ROLE_ID), dict)
            else {}
        )
        if single_role_config:
            return single_role_config
        if len(role_audio_configs) == 1:
            only_value = next(iter(role_audio_configs.values()))
            if isinstance(only_value, dict):
                return dict(only_value)
        return {}

    @staticmethod
    def _rate_to_speed(rate: Any) -> float:
        text = str(rate or "").strip()
        if not text:
            return SOURCE_AUDIO_SPEED
        percent = 0.0
        if text.endswith("%"):
            try:
                percent = float(text[:-1])
            except ValueError:
                percent = 0.0
        return normalize_speed(1.0 + (percent / 100.0), SOURCE_AUDIO_SPEED)

    async def _concat_audio_files(
        self,
        *,
        input_paths: list[Path],
        output_path: Path,
        provider_name: str,
    ) -> None:
        if not input_paths:
            raise StageValidationError("没有可拼接的分镜音频")

        list_file = output_path.with_suffix(".concat.txt")
        lines: list[str] = []
        for path in input_paths:
            escaped = str(path).replace("'", "'\\''")
            lines.append(f"file '{escaped}'")
        list_file.write_text("\n".join(lines), encoding="utf-8")

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-vn",
        ]
        if provider_name == "wan2gp":
            cmd.extend(["-c:a", "pcm_s16le"])
        else:
            cmd.extend(["-c:a", "libmp3lame", "-q:a", "2"])
        cmd.append(str(output_path))

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise StageRuntimeError("未找到 ffmpeg，无法拼接多人音频") from exc

        _, stderr = await process.communicate()
        list_file.unlink(missing_ok=True)
        if process.returncode != 0 or not output_path.exists():
            message = stderr.decode(errors="ignore").strip()
            raise StageRuntimeError(f"多人音频拼接失败: {message}")

    async def _convert_audio_to_concat_wav(
        self,
        *,
        input_path: Path,
        output_path: Path,
    ) -> None:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-vn",
            "-acodec",
            "pcm_s16le",
            str(output_path),
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise StageRuntimeError("未找到 ffmpeg，无法处理多人音频") from exc

        _, stderr = await process.communicate()
        if process.returncode != 0 or not output_path.exists():
            message = stderr.decode(errors="ignore").strip()
            raise StageRuntimeError(f"多人音频转码失败: {message}")

    @staticmethod
    def _normalize_role_audio_configs(raw_value: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(raw_value, dict):
            return {}
        normalized: dict[str, dict[str, Any]] = {}
        for key, item in raw_value.items():
            speaker_id = str(key or "").strip()
            if not speaker_id or not isinstance(item, dict):
                continue
            normalized_item: dict[str, Any] = {}
            for raw_key, value in item.items():
                normalized_item[str(raw_key)] = value
            normalized[speaker_id] = normalized_item
        return normalized

    async def _get_or_create_subtitle_stage(
        self,
        db: AsyncSession,
        project: Project,
    ) -> StageExecution:
        result = await db.execute(
            select(StageExecution).where(
                StageExecution.project_id == project.id,
                StageExecution.stage_type == StageType.SUBTITLE,
            )
        )
        stage = result.scalar_one_or_none()
        if stage:
            return stage

        stage_number = stage_registry.get_stage_number(StageType.SUBTITLE)
        stage = StageExecution(
            project_id=project.id,
            stage_type=StageType.SUBTITLE,
            stage_number=stage_number,
            status=StageStatus.PENDING,
        )
        db.add(stage)
        await db.commit()
        await db.refresh(stage)
        return stage

    def _get_output_dir(self, project: Project) -> Path:
        return get_output_dir(project)

    async def _get_storyboard_data(self, db: AsyncSession, project: Project) -> dict | None:
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
    def _is_shot_voice_content_valid(shot: dict[str, Any]) -> bool:
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

    @staticmethod
    def _build_wan2gp_generation_signature(
        *,
        text: str,
        preset: str,
        model_mode: str,
        alt_prompt: str,
        duration_seconds: int | None,
        temperature: float,
        top_k: int,
        seed: int,
        audio_guide: str,
        split_strategy: str = "sentence_punct",
        auto_duration_buffer_seconds: int = WAN2GP_QWEN3_AUTO_DURATION_BUFFER_DEFAULT_SECONDS,
        auto_duration_max_seconds: int = WAN2GP_QWEN3_AUTO_DURATION_MAX_DEFAULT_SECONDS,
    ) -> tuple[dict[str, Any], str]:
        payload = {
            "text_sha256": hashlib.sha256((text or "").encode("utf-8")).hexdigest(),
            "preset": str(preset or ""),
            "model_mode": str(model_mode or ""),
            "alt_prompt": str(alt_prompt or ""),
            "duration_seconds": int(duration_seconds) if duration_seconds is not None else None,
            "temperature": round(float(temperature), 6),
            "top_k": int(top_k),
            "seed": int(seed),
            "audio_guide": str(audio_guide or "").strip(),
            "split_strategy": str(split_strategy or "sentence_punct"),
            "auto_duration_buffer_seconds": int(auto_duration_buffer_seconds),
            "auto_duration_max_seconds": int(auto_duration_max_seconds),
            "wan2gp_policy_version": "text_estimate_auto_duration_v4_progressive_split_window",
        }
        signature = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return payload, signature

    @staticmethod
    def _can_reuse_wan2gp_raw_audio(
        existing_asset: dict[str, Any] | None,
        *,
        expected_signature: str,
    ) -> Path | None:
        if not isinstance(existing_asset, dict):
            return None
        existing_signature = str(existing_asset.get("wan2gp_generation_signature") or "").strip()
        if not existing_signature or existing_signature != expected_signature:
            return None
        raw_path = str(existing_asset.get("raw_file_path") or "").strip()
        raw_file = resolve_path_for_io(raw_path)
        if raw_file is None:
            return None
        if not raw_file.exists():
            return None
        return raw_file

    @staticmethod
    def _resolve_provider_audio_guide_path(audio_guide: str | None) -> str:
        resolved = resolve_path_for_io(audio_guide)
        if resolved is not None:
            return str(resolved)
        return str(audio_guide or "").strip()
