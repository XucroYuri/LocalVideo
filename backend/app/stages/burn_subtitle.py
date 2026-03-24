import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import StageRuntimeError
from app.models.project import Project
from app.models.stage import StageExecution, StageType
from app.stages.common.data_access import get_latest_stage_output
from app.stages.common.paths import get_output_dir, resolve_path_for_io
from app.stages.common.validators import is_compose_data_usable, is_subtitle_data_usable

from . import register_stage
from ._asset_swap import build_temporary_output_path, cleanup_temp_file, replace_generated_file
from .base import StageHandler, StageResult

logger = logging.getLogger(__name__)

COMPOSE_DATA_REQUIRED_ERROR = "母版视频为空或不可用，请先执行母版合成"

PREFERRED_CJK_FONT_NAMES = [
    "Noto Sans CJK SC",
    "Noto Sans CJK JP",
    "Source Han Sans SC",
    "Source Han Sans CN",
    "Microsoft YaHei",
    "PingFang SC",
    "WenQuanYi Zen Hei",
]


@register_stage(StageType.BURN_SUBTITLE)
class BurnSubtitleHandler(StageHandler):
    async def execute(
        self,
        db: AsyncSession,
        project: Project,
        stage: StageExecution,
        input_data: dict[str, Any] | None = None,
    ) -> StageResult:
        if (input_data or {}).get("include_subtitle") is False:
            return StageResult(success=True, skipped=True, message="未启用字幕，已跳过")

        compose_data = await self._get_compose_data(db, project)
        subtitle_data = await self._get_subtitle_data(db, project)
        if not compose_data:
            return StageResult(success=False, error=COMPOSE_DATA_REQUIRED_ERROR)
        if not subtitle_data:
            return StageResult(success=True, skipped=True, message="字幕不可用，已跳过烧录")

        master_video_path = resolve_path_for_io(compose_data.get("master_video_path"))
        subtitle_file_path = resolve_path_for_io(subtitle_data.get("subtitle_file_path"))
        if master_video_path is None or not master_video_path.exists():
            return StageResult(success=False, error=COMPOSE_DATA_REQUIRED_ERROR)
        if subtitle_file_path is None or not subtitle_file_path.exists():
            return StageResult(success=True, skipped=True, message="字幕文件不存在，已跳过烧录")

        output_dir = self._get_output_dir(project)
        burned_video_path = output_dir / "burned_subtitle.mp4"
        tmp_burned_video_path = build_temporary_output_path(burned_video_path)

        subtitle_font_size = self._to_int((input_data or {}).get("subtitle_font_size"), 12)
        subtitle_position_percent = self._to_float(
            (input_data or {}).get("subtitle_position_percent"),
            80.0,
        )
        subtitle_font_name, subtitle_fonts_dir = await self._resolve_subtitle_font()
        try:
            width, height = await self._probe_video_dimensions(master_video_path)
            await self._burn_subtitle(
                video_path=master_video_path,
                subtitle_path=subtitle_file_path,
                output_path=tmp_burned_video_path,
                subtitle_font_size=subtitle_font_size,
                subtitle_position_percent=subtitle_position_percent,
                subtitle_font_name=subtitle_font_name,
                subtitle_fonts_dir=subtitle_fonts_dir,
                video_height=height,
            )
            duration = await self._probe_media_duration(tmp_burned_video_path)
            if width is None or height is None:
                width, height = await self._probe_video_dimensions(tmp_burned_video_path)
            replace_generated_file(tmp_burned_video_path, burned_video_path)
            return StageResult(
                success=True,
                data={
                    "burned_video_path": str(burned_video_path),
                    "subtitle_file_path": str(subtitle_file_path),
                    "duration": duration,
                    "width": width,
                    "height": height,
                    "updated_at": int(time.time()),
                },
            )
        except Exception as exc:
            return StageResult(success=False, error=str(exc))
        finally:
            cleanup_temp_file(tmp_burned_video_path)

    async def validate_prerequisites(
        self,
        db: AsyncSession,
        project: Project,
    ) -> str | None:
        if not await self._get_compose_data(db, project):
            return COMPOSE_DATA_REQUIRED_ERROR
        return None

    async def _burn_subtitle(
        self,
        *,
        video_path: Path,
        subtitle_path: Path,
        output_path: Path,
        subtitle_font_size: int,
        subtitle_position_percent: float,
        subtitle_font_name: str | None,
        subtitle_fonts_dir: Path | None,
        video_height: int | None,
    ) -> None:
        ass_canvas_height = 288
        safe_padding = 8
        desired_y = int(
            (max(0.0, min(100.0, float(subtitle_position_percent))) / 100.0) * ass_canvas_height
        )
        margin_v = int(
            max(
                safe_padding,
                min(ass_canvas_height - safe_padding, ass_canvas_height - desired_y),
            )
        )
        logger.info(
            "[BurnSubtitle] font_size=%s position=%.1f%% ass_canvas_h=%s video_h=%s margin_v=%s font_name=%s fonts_dir=%s",
            subtitle_font_size,
            subtitle_position_percent,
            ass_canvas_height,
            video_height,
            margin_v,
            subtitle_font_name,
            str(subtitle_fonts_dir) if subtitle_fonts_dir else None,
        )

        subtitle_filter = f"subtitles={self._escape_filter_value(str(subtitle_path))}:charenc=UTF-8"
        if subtitle_fonts_dir:
            subtitle_filter += f":fontsdir={self._escape_filter_value(str(subtitle_fonts_dir))}"
        style_parts = [
            f"FontSize={subtitle_font_size}",
            "PrimaryColour=&HFFFFFF&",
            "Alignment=2",
            f"MarginV={margin_v}",
        ]
        if subtitle_font_name:
            style_parts.append(f"FontName={self._escape_ass_style_value(subtitle_font_name)}")
        subtitle_filter += f":force_style='{','.join(style_parts)}'"

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            subtitle_filter,
            "-c:v",
            "libx264",
            "-c:a",
            "copy",
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
                f"ffmpeg burn subtitle failed (code={process.returncode}): "
                f"{stderr.decode(errors='ignore').strip()}"
            )
        if not output_path.exists():
            raise StageRuntimeError("字幕烧录完成但输出文件不存在")

    async def _resolve_subtitle_font(self) -> tuple[str | None, Path | None]:
        configured_font_file = str(settings.subtitle_font_file or "").strip()
        configured_font_name = str(settings.subtitle_font_name or "").strip()
        if configured_font_file:
            font_file_path = Path(configured_font_file).expanduser()
            if font_file_path.exists() and font_file_path.is_file():
                return configured_font_name or font_file_path.stem, font_file_path.parent
        if configured_font_name:
            return configured_font_name, None
        detected_font = await self._detect_system_cjk_font()
        if detected_font:
            return detected_font, None
        return None, None

    async def _detect_system_cjk_font(self) -> str | None:
        try:
            process = await asyncio.create_subprocess_exec(
                "fc-list",
                ":lang=zh",
                "family",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            logger.warning("[BurnSubtitle] fc-list not found, skip auto subtitle font detection")
            return None

        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            logger.warning(
                "[BurnSubtitle] fc-list detection failed (code=%s): %s",
                process.returncode,
                stderr.decode("utf-8", errors="ignore").strip(),
            )
            return None

        families: list[str] = []
        for raw_line in stdout.decode("utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            for item in line.split(":")[0].split(","):
                family = item.strip()
                if family:
                    families.append(family)

        deduped = list(dict.fromkeys(families))
        normalized = {name.lower(): name for name in deduped}
        for preferred in PREFERRED_CJK_FONT_NAMES:
            if preferred.lower() in normalized:
                return normalized[preferred.lower()]
        return deduped[0] if deduped else None

    async def _probe_media_duration(self, media_path: Path) -> float | None:
        process = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        if process.returncode != 0:
            return None
        try:
            duration = float(stdout.decode(errors="ignore").strip() or 0.0)
        except (TypeError, ValueError):
            return None
        return duration if duration > 0 else None

    async def _probe_video_dimensions(self, media_path: Path) -> tuple[int | None, int | None]:
        process = await asyncio.create_subprocess_exec(
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
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        if process.returncode != 0:
            return None, None
        try:
            width_text, height_text = stdout.decode(errors="ignore").strip().split("x", maxsplit=1)
            return int(width_text), int(height_text)
        except (TypeError, ValueError):
            return None, None

    async def _get_compose_data(self, db: AsyncSession, project: Project) -> dict | None:
        return await get_latest_stage_output(
            db,
            project.id,
            StageType.COMPOSE,
            usable_check=is_compose_data_usable,
        )

    async def _get_subtitle_data(self, db: AsyncSession, project: Project) -> dict | None:
        return await get_latest_stage_output(
            db,
            project.id,
            StageType.SUBTITLE,
            usable_check=is_subtitle_data_usable,
        )

    def _get_output_dir(self, project: Project) -> Path:
        return get_output_dir(project)

    @staticmethod
    def _escape_filter_value(value: str) -> str:
        escaped = str(value)
        escaped = escaped.replace("\\", "\\\\")
        escaped = escaped.replace(":", "\\:")
        escaped = escaped.replace(",", "\\,")
        escaped = escaped.replace("'", "\\'")
        escaped = escaped.replace("[", "\\[")
        escaped = escaped.replace("]", "\\]")
        return escaped

    @staticmethod
    def _escape_ass_style_value(value: str) -> str:
        escaped = str(value).replace("\\", "\\\\")
        escaped = escaped.replace(",", r"\,")
        escaped = escaped.replace("'", r"\'")
        return escaped

    @staticmethod
    def _to_int(value: Any, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    @staticmethod
    def _to_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
