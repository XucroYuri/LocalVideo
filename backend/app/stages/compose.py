import asyncio
import logging
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import StageRuntimeError, StageValidationError
from app.core.project_mode import resolve_script_mode_from_video_type
from app.models.project import Project
from app.models.stage import StageExecution, StageType
from app.stages.common.data_access import get_latest_stage_output
from app.stages.common.paths import (
    get_output_dir,
    resolve_existing_path_for_io,
    resolve_path_for_io,
    to_storage_public_path,
)
from app.stages.common.validators import (
    is_audio_data_usable,
    is_storyboard_data_usable,
    is_video_data_usable,
)

from . import register_stage
from ._asset_swap import build_temporary_output_path, cleanup_temp_file, replace_generated_file
from .base import StageHandler, StageResult

logger = logging.getLogger(__name__)

AUDIO_DATA_REQUIRED_ERROR = "音频数据为空或不可用，请先生成音频"
VIDEO_DATA_REQUIRED_ERROR = "视频数据为空或不可用，请先生成视频"
COMPOSE_ASSET_INCOMPLETE_ERROR = "合成资源不完整"
COMPOSE_CANVAS_STRATEGY_MAX_SIZE = "max_size"
COMPOSE_CANVAS_STRATEGY_MOST_COMMON = "most_common"
COMPOSE_CANVAS_STRATEGY_FIRST_SHOT = "first_shot"
COMPOSE_CANVAS_STRATEGY_FIXED = "fixed"
SUPPORTED_COMPOSE_CANVAS_STRATEGIES = {
    COMPOSE_CANVAS_STRATEGY_MAX_SIZE,
    COMPOSE_CANVAS_STRATEGY_MOST_COMMON,
    COMPOSE_CANVAS_STRATEGY_FIRST_SHOT,
    COMPOSE_CANVAS_STRATEGY_FIXED,
}


@register_stage(StageType.COMPOSE)
class ComposeHandler(StageHandler):
    async def execute(
        self,
        db: AsyncSession,
        project: Project,
        stage: StageExecution,
        input_data: dict[str, Any] | None = None,
    ) -> StageResult:
        requested_video_fit_mode = str((input_data or {}).get("video_fit_mode") or "truncate")
        audio_gap_seconds = self._to_float((input_data or {}).get("audio_gap_seconds"), 0.2)
        audio_gap_seconds = max(audio_gap_seconds, 0.0)
        requested_concat_canvas_strategy = (
            str(
                (input_data or {}).get("concat_canvas_strategy") or COMPOSE_CANVAS_STRATEGY_MAX_SIZE
            )
            .strip()
            .lower()
        )
        concat_canvas_strategy = (
            requested_concat_canvas_strategy
            if requested_concat_canvas_strategy in SUPPORTED_COMPOSE_CANVAS_STRATEGIES
            else COMPOSE_CANVAS_STRATEGY_MAX_SIZE
        )
        concat_target_resolution = str(
            (input_data or {}).get("concat_target_resolution") or ""
        ).strip()

        audio_data = await self._get_audio_data(db, project)
        video_data = await self._get_video_data(db, project)
        storyboard_data = await self._get_storyboard_data(db, project)

        script_mode = (
            str(
                (input_data or {}).get("script_mode")
                or (storyboard_data or {}).get("script_mode")
                or resolve_script_mode_from_video_type(project.video_type)
                or ""
            )
            .strip()
            .lower()
        )
        single_take_enabled = bool(
            (input_data or {}).get("single_take", False) or script_mode == "duo_podcast"
        )
        video_fit_mode = "scale" if single_take_enabled else requested_video_fit_mode

        logger.info(
            "[Compose] script_mode=%s single_take=%s video_fit_mode=%s",
            script_mode or "single",
            single_take_enabled,
            video_fit_mode,
        )
        logger.info(
            "[Compose] concat_canvas_strategy=%s concat_target_resolution=%s",
            concat_canvas_strategy,
            concat_target_resolution or None,
        )

        if not audio_data:
            return StageResult(success=False, error=AUDIO_DATA_REQUIRED_ERROR)
        if not video_data:
            return StageResult(success=False, error=VIDEO_DATA_REQUIRED_ERROR)

        audio_assets = audio_data.get("audio_assets", [])
        video_assets = video_data.get("video_assets", [])
        if not audio_assets:
            return StageResult(success=False, error=AUDIO_DATA_REQUIRED_ERROR)
        if not video_assets:
            return StageResult(success=False, error=VIDEO_DATA_REQUIRED_ERROR)

        expected_shot_indices = self._get_expected_shot_indices(
            storyboard_data, audio_assets, video_assets
        )
        if not expected_shot_indices:
            return StageResult(success=False, error=VIDEO_DATA_REQUIRED_ERROR)

        (
            audio_assets_by_index,
            audio_duration_map,
            missing_audio_details,
        ) = self._analyze_assets(expected_shot_indices, audio_assets, "音频")
        (
            video_assets_by_index,
            video_duration_map,
            missing_video_details,
        ) = self._analyze_assets(expected_shot_indices, video_assets, "视频")

        if missing_audio_details or missing_video_details:
            error_parts: list[str] = []
            if missing_audio_details:
                error_parts.append(f"音频异常: {'；'.join(missing_audio_details)}")
            if missing_video_details:
                error_parts.append(f"视频异常: {'；'.join(missing_video_details)}")
            return StageResult(
                success=False,
                error=(
                    f"{COMPOSE_ASSET_INCOMPLETE_ERROR}。"
                    f"预期分镜位: {self._format_shot_indices(expected_shot_indices)}。"
                    f"{'；'.join(error_parts)}"
                ),
            )

        output_dir = self._get_output_dir(project)
        merged_dir = output_dir / "merged"
        merged_dir.mkdir(parents=True, exist_ok=True)
        master_video_path = output_dir / "master_video.mp4"
        tmp_master_video_path = build_temporary_output_path(master_video_path)

        try:
            total_runtime_steps = len(expected_shot_indices) + 1
            completed_runtime_steps = 0
            await self._update_runtime_progress(
                db=db,
                stage=stage,
                progress=1,
                total_items=total_runtime_steps,
                completed_items=completed_runtime_steps,
                message="正在合成分镜...",
                generating_shot_key=(
                    str(expected_shot_indices[0]) if expected_shot_indices else None
                ),
            )

            merged_files: list[dict[str, Any]] = []
            for shot_index in expected_shot_indices:
                video_path = resolve_existing_path_for_io(
                    video_assets_by_index[shot_index]["file_path"]
                )
                audio_path = resolve_existing_path_for_io(
                    audio_assets_by_index[shot_index]["file_path"]
                )
                if video_path is None or audio_path is None:
                    raise StageValidationError(f"分镜位{shot_index}资源路径无效")

                merged_path = merged_dir / f"merged_{shot_index:03d}.mp4"
                await self._merge_video_audio(
                    video_path=video_path,
                    audio_path=audio_path,
                    output_path=merged_path,
                    shot_index=shot_index,
                    audio_duration=audio_duration_map.get(shot_index),
                    video_duration=video_duration_map.get(shot_index),
                    video_fit_mode=video_fit_mode,
                    audio_gap_seconds=audio_gap_seconds,
                )

                merged_files.append({"shot_index": shot_index, "file_path": str(merged_path)})
                completed_runtime_steps += 1
                merge_progress = int((completed_runtime_steps / total_runtime_steps) * 95)
                next_shot_index = next(
                    (idx for idx in expected_shot_indices if idx > shot_index),
                    None,
                )
                await self._update_runtime_progress(
                    db=db,
                    stage=stage,
                    progress=merge_progress,
                    total_items=total_runtime_steps,
                    completed_items=completed_runtime_steps,
                    message="正在合成分镜...",
                    generating_shot_key=(
                        str(next_shot_index) if next_shot_index is not None else None
                    ),
                    last_item_complete=shot_index,
                )

            concat_inputs: list[Path] = []
            for item in merged_files:
                merged_file_path = resolve_existing_path_for_io(item.get("file_path"))
                if merged_file_path is None:
                    raise StageValidationError("合成分镜路径无效，无法拼接最终视频")
                concat_inputs.append(merged_file_path)

            await self._update_runtime_progress(
                db=db,
                stage=stage,
                progress=max(stage.progress or 0, 95),
                total_items=total_runtime_steps,
                completed_items=completed_runtime_steps,
                message="正在拼接母版视频...",
                generating_shot_key="concat",
            )

            concat_width, concat_height = await self._concat_videos(
                video_files=concat_inputs,
                output_path=tmp_master_video_path,
                canvas_strategy=concat_canvas_strategy,
                target_resolution=concat_target_resolution,
            )
            completed_runtime_steps += 1
            await self._update_runtime_progress(
                db=db,
                stage=stage,
                progress=99,
                total_items=total_runtime_steps,
                completed_items=completed_runtime_steps,
                message="拼接完成，正在整理输出...",
                generating_shot_key=None,
            )

            merged_total_duration = 0.0
            merged_duration_count = 0
            for merged in merged_files:
                merged_path = resolve_path_for_io(merged.get("file_path"))
                if merged_path is None:
                    continue
                duration = await self._probe_media_duration(merged_path)
                if duration is None:
                    continue
                merged_total_duration += duration
                merged_duration_count += 1

            final_duration = await self._probe_media_duration(tmp_master_video_path)
            replace_generated_file(tmp_master_video_path, master_video_path)
            project.output_dir = to_storage_public_path(output_dir)
            await db.commit()

            if final_duration is not None:
                logger.info(
                    "[Compose] Duration summary: merged_total=%.3fs (probed=%s/%s) final=%.3fs delta=%.3fs",
                    merged_total_duration,
                    merged_duration_count,
                    len(merged_files),
                    final_duration,
                    final_duration - merged_total_duration,
                )
            else:
                logger.info(
                    "[Compose] Duration summary: merged_total=%.3fs (probed=%s/%s) final=unknown",
                    merged_total_duration,
                    merged_duration_count,
                    len(merged_files),
                )

            return StageResult(
                success=True,
                data={
                    "merged_files": merged_files,
                    "master_video_path": str(master_video_path),
                    "duration": float(final_duration) if final_duration is not None else None,
                    "width": concat_width,
                    "height": concat_height,
                    "concat_canvas_strategy": concat_canvas_strategy,
                    "shot_count": len(merged_files),
                    "updated_at": int(time.time()),
                },
            )
        except Exception as exc:
            return StageResult(success=False, error=str(exc))
        finally:
            cleanup_temp_file(tmp_master_video_path)

    async def _merge_video_audio(
        self,
        video_path: Path,
        audio_path: Path,
        output_path: Path,
        *,
        shot_index: int | None = None,
        audio_duration: float | None = None,
        video_duration: float | None = None,
        video_fit_mode: str = "truncate",
        audio_gap_seconds: float = 0.2,
    ) -> None:
        target_duration = None
        if audio_duration is not None:
            target_duration = max(audio_duration + max(audio_gap_seconds, 0.0), 0.1)

        adjust_action = None
        if target_duration is not None and video_duration is not None:
            if video_duration + 1e-3 < target_duration:
                adjust_action = "scale"
            elif video_fit_mode == "truncate":
                adjust_action = "truncate"
            elif video_fit_mode == "scale":
                adjust_action = "scale"

        if target_duration is not None and video_duration is not None:
            logger.info(
                "[Compose] Shot timing: shot=%s video=%.3fs audio=%.3fs target=%.3fs mode=%s action=%s",
                shot_index if shot_index is not None else "unknown",
                video_duration,
                audio_duration if audio_duration is not None else -1.0,
                target_duration,
                video_fit_mode,
                adjust_action or "none",
            )

        vf_filters: list[str] = []
        if adjust_action == "truncate" and target_duration is not None:
            vf_filters.append(f"trim=0:{target_duration:.3f}")
            vf_filters.append("setpts=PTS-STARTPTS")
        elif adjust_action == "scale" and target_duration is not None and video_duration:
            scale_factor = target_duration / max(video_duration, 0.001)
            vf_filters.append(f"setpts=PTS*{scale_factor:.6f}")

        cmd = ["ffmpeg", "-y", "-i", str(video_path), "-i", str(audio_path)]
        if vf_filters:
            cmd += ["-vf", ",".join(vf_filters), "-c:v", "libx264"]
        else:
            cmd += ["-c:v", "copy"]
        cmd += ["-c:a", "aac", str(output_path)]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise StageRuntimeError(
                f"ffmpeg merge failed (code={process.returncode}): "
                f"{stderr.decode(errors='ignore').strip()}"
            )
        if not output_path.exists():
            raise StageRuntimeError("ffmpeg merge finished but output file was not created")

    async def _update_runtime_progress(
        self,
        db: AsyncSession,
        stage: StageExecution,
        *,
        progress: int,
        total_items: int | None,
        completed_items: int | None,
        message: str | None,
        generating_shot_key: str | None = None,
        last_item_complete: int | None = None,
    ) -> None:
        stage.progress = max(0, min(99, int(progress)))
        stage.total_items = total_items
        stage.completed_items = completed_items
        stage.skipped_items = 0
        if last_item_complete is not None:
            stage.last_item_complete = int(last_item_complete)

        output_data = dict(stage.output_data or {})
        if message:
            output_data["progress_message"] = message
        else:
            output_data.pop("progress_message", None)
        if generating_shot_key is None:
            output_data["generating_shots"] = {}
        else:
            output_data["generating_shots"] = {
                str(generating_shot_key): {"status": "generating", "progress": stage.progress}
            }
        stage.output_data = output_data
        flag_modified(stage, "output_data")
        await db.commit()

    async def _concat_videos(
        self,
        video_files: list[Path],
        output_path: Path,
        *,
        canvas_strategy: str = COMPOSE_CANVAS_STRATEGY_MAX_SIZE,
        target_resolution: str | None = None,
    ) -> tuple[int, int]:
        if not video_files:
            raise StageValidationError("No merged video files to concat")

        resolved_inputs: list[Path] = []
        for video_file in video_files:
            if not video_file.exists():
                raise StageValidationError(f"Concat source missing: {video_file}")
            resolved_inputs.append(video_file.resolve())

        target_width, target_height = await self._resolve_concat_canvas(
            resolved_inputs,
            canvas_strategy=canvas_strategy,
            target_resolution=target_resolution,
        )

        if len(resolved_inputs) == 1:
            source_dimensions = await self._probe_video_dimensions(resolved_inputs[0])
            if source_dimensions == (target_width, target_height):
                import shutil

                shutil.copy(resolved_inputs[0], output_path)
                return target_width, target_height

            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(resolved_inputs[0]),
                "-vf",
                (
                    f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
                    f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
                ),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
            if process.returncode != 0:
                raise StageRuntimeError(
                    f"ffmpeg single-file normalize failed (code={process.returncode}): "
                    f"{stderr.decode(errors='ignore').strip()}"
                )
            if not output_path.exists():
                raise StageRuntimeError(
                    "ffmpeg single-file normalize finished but output file was not created"
                )
            return target_width, target_height

        video_filter_parts: list[str] = []
        concat_inputs: list[str] = []
        for idx in range(len(resolved_inputs)):
            video_filter_parts.append(
                f"[{idx}:v:0]"
                f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
                f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2,"
                "setsar=1"
                f"[v{idx}]"
            )
            concat_inputs.append(f"[v{idx}][{idx}:a:0]")

        filter_complex = (
            ";".join(video_filter_parts)
            + ";"
            + "".join(concat_inputs)
            + f"concat=n={len(resolved_inputs)}:v=1:a=1[v][a]"
        )

        cmd = ["ffmpeg", "-y"]
        for abs_path in resolved_inputs:
            cmd += ["-i", str(abs_path)]
        cmd += [
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise StageRuntimeError(
                f"ffmpeg concat failed (code={process.returncode}): "
                f"{stderr.decode(errors='ignore').strip()}"
            )
        if not output_path.exists():
            raise StageRuntimeError("ffmpeg concat finished but output file was not created")
        return target_width, target_height

    async def _resolve_concat_canvas(
        self,
        video_files: list[Path],
        *,
        canvas_strategy: str = COMPOSE_CANVAS_STRATEGY_MAX_SIZE,
        target_resolution: str | None = None,
    ) -> tuple[int, int]:
        if canvas_strategy == COMPOSE_CANVAS_STRATEGY_FIXED:
            parsed_resolution = self._parse_resolution_text(target_resolution)
            if parsed_resolution is None:
                raise StageValidationError("固定目标分辨率无效，无法拼接最终视频")
            return self._normalize_even_dimensions(*parsed_resolution)

        probed_sizes: list[tuple[int, int]] = []
        for video_file in video_files:
            dimensions = await self._probe_video_dimensions(video_file)
            if dimensions is not None:
                probed_sizes.append(dimensions)
        if not probed_sizes:
            return 1080, 1920

        if canvas_strategy == COMPOSE_CANVAS_STRATEGY_FIRST_SHOT:
            return self._normalize_even_dimensions(*probed_sizes[0])

        if canvas_strategy == COMPOSE_CANVAS_STRATEGY_MOST_COMMON:
            counts = Counter(probed_sizes)
            width, height = max(
                counts.items(),
                key=lambda item: (item[1], item[0][0] * item[0][1], -probed_sizes.index(item[0])),
            )[0]
            return self._normalize_even_dimensions(width, height)

        width, height = max(probed_sizes, key=lambda item: item[0] * item[1])
        return self._normalize_even_dimensions(width, height)

    @staticmethod
    def _normalize_even_dimensions(width: int, height: int) -> tuple[int, int]:
        safe_width = int(width)
        safe_height = int(height)
        if safe_width % 2 != 0:
            safe_width -= 1
        if safe_height % 2 != 0:
            safe_height -= 1
        return max(safe_width, 2), max(safe_height, 2)

    @classmethod
    def _parse_resolution_text(cls, value: str | None) -> tuple[int, int] | None:
        text = str(value or "").strip()
        match = re.fullmatch(r"(\d+)\s*x\s*(\d+)", text, flags=re.IGNORECASE)
        if not match:
            return None
        try:
            width = int(match.group(1))
            height = int(match.group(2))
        except (TypeError, ValueError):
            return None
        if width <= 0 or height <= 0:
            return None
        return width, height

    async def _probe_media_duration(self, media_path: Path) -> float | None:
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
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            logger.warning(
                "[Compose] Failed to probe duration for %s: %s",
                media_path,
                stderr.decode(errors="ignore").strip()
                or f"ffprobe returncode={process.returncode}",
            )
            return None
        output_text = stdout.decode(errors="ignore").strip()
        if not output_text:
            return None
        try:
            duration = float(output_text.splitlines()[-1].strip())
        except (TypeError, ValueError):
            logger.warning("[Compose] Invalid duration output for %s: %s", media_path, output_text)
            return None
        return duration if duration > 0 else None

    async def _probe_video_dimensions(self, media_path: Path) -> tuple[int, int] | None:
        if not media_path.exists():
            return None
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
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            logger.warning(
                "[Compose] Failed to probe video dimensions for %s: %s",
                media_path,
                stderr.decode(errors="ignore").strip()
                or f"ffprobe returncode={process.returncode}",
            )
            return None
        output_text = stdout.decode(errors="ignore").strip()
        if not output_text:
            return None
        try:
            width_text, height_text = output_text.split("x", maxsplit=1)
            width = int(width_text.strip())
            height = int(height_text.strip())
        except (TypeError, ValueError):
            logger.warning(
                "[Compose] Invalid video dimension output for %s: %s",
                media_path,
                output_text,
            )
            return None
        if width <= 0 or height <= 0:
            return None
        return width, height

    def _get_output_dir(self, project: Project) -> Path:
        return get_output_dir(project)

    async def _get_audio_data(self, db: AsyncSession, project: Project) -> dict | None:
        return await get_latest_stage_output(
            db,
            project.id,
            StageType.AUDIO,
            usable_check=is_audio_data_usable,
        )

    async def _get_storyboard_data(self, db: AsyncSession, project: Project) -> dict | None:
        return await get_latest_stage_output(
            db,
            project.id,
            StageType.STORYBOARD,
            usable_check=is_storyboard_data_usable,
        )

    async def _get_video_data(self, db: AsyncSession, project: Project) -> dict | None:
        return await get_latest_stage_output(
            db,
            project.id,
            StageType.VIDEO,
            usable_check=is_video_data_usable,
        )

    async def validate_prerequisites(
        self,
        db: AsyncSession,
        project: Project,
    ) -> str | None:
        if not await self._get_audio_data(db, project):
            return AUDIO_DATA_REQUIRED_ERROR
        if not await self._get_video_data(db, project):
            return VIDEO_DATA_REQUIRED_ERROR
        return None

    @staticmethod
    def _format_shot_indices(indices: list[int]) -> str:
        return ", ".join(str(i) for i in sorted(set(indices)))

    def _get_expected_shot_indices(
        self,
        storyboard_data: dict[str, Any] | None,
        audio_assets: list[Any],
        video_assets: list[Any],
    ) -> list[int]:
        if isinstance(storyboard_data, dict):
            shots = storyboard_data.get("shots")
            if isinstance(shots, list) and shots:
                return list(range(len(shots)))

        indices: set[int] = set()
        for asset in audio_assets + video_assets:
            if not isinstance(asset, dict):
                continue
            shot_index = asset.get("shot_index")
            if shot_index is None:
                continue
            try:
                indices.add(int(shot_index))
            except (TypeError, ValueError):
                continue
        return sorted(indices)

    def _analyze_assets(
        self,
        expected_shot_indices: list[int],
        assets: list[Any],
        asset_label: str,
    ) -> tuple[dict[int, dict[str, Any]], dict[int, float], list[str]]:
        assets_by_index: dict[int, dict[str, Any]] = {}
        duration_map: dict[int, float] = {}
        grouped_assets: dict[int, list[dict[str, Any]]] = {}

        for asset in assets:
            if not isinstance(asset, dict):
                continue
            shot_index = asset.get("shot_index")
            if shot_index is None:
                continue
            try:
                idx = int(shot_index)
            except (TypeError, ValueError):
                continue
            grouped_assets.setdefault(idx, []).append(asset)

        missing_details: list[str] = []
        for idx in expected_shot_indices:
            candidates = grouped_assets.get(idx, [])
            if not candidates:
                missing_details.append(f"分镜位{idx}无{asset_label}记录")
                continue

            missing_reasons: list[str] = []
            valid_asset: dict[str, Any] | None = None
            for candidate in candidates:
                file_path = candidate.get("file_path")
                if not file_path:
                    missing_reasons.append("文件路径为空")
                    continue
                file_path_str = str(file_path)
                path = resolve_path_for_io(file_path_str)
                if path is None or not path.exists():
                    missing_reasons.append(f"文件不存在({file_path_str})")
                    continue
                valid_asset = candidate
                break

            if valid_asset is None:
                reason_text = (
                    " / ".join(dict.fromkeys(missing_reasons)) if missing_reasons else "文件不可用"
                )
                missing_details.append(f"分镜位{idx}{reason_text}")
                continue

            assets_by_index[idx] = valid_asset
            duration = valid_asset.get("duration")
            if duration is not None:
                duration_value = self._to_float(duration, 0.0)
                if duration_value > 0:
                    duration_map[idx] = duration_value

        return assets_by_index, duration_map, missing_details

    @staticmethod
    def _to_int(value: Any) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _to_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
