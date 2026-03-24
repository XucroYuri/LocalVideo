import asyncio
import time
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.stage import StageExecution, StageType
from app.stages.common.data_access import get_latest_stage_output
from app.stages.common.paths import resolve_path_for_io
from app.stages.common.validators import (
    is_burn_subtitle_data_usable,
    is_compose_data_usable,
    is_subtitle_data_usable,
)

from . import register_stage
from .base import StageHandler, StageResult

COMPOSE_DATA_REQUIRED_ERROR = "母版视频为空或不可用，请先执行母版合成"


@register_stage(StageType.FINALIZE)
class FinalizeHandler(StageHandler):
    async def execute(
        self,
        db: AsyncSession,
        project: Project,
        stage: StageExecution,
        input_data: dict[str, Any] | None = None,
    ) -> StageResult:
        compose_data = await self._get_compose_data(db, project)
        if not compose_data:
            return StageResult(success=False, error=COMPOSE_DATA_REQUIRED_ERROR)

        include_subtitle = (input_data or {}).get("include_subtitle") is not False
        burn_data = await self._get_burn_subtitle_data(db, project)
        subtitle_data = await self._get_subtitle_data(db, project)

        source_stage = "compose"
        final_video_path = str(compose_data.get("master_video_path") or "").strip()
        has_subtitle = False

        if include_subtitle and burn_data and str(burn_data.get("burned_video_path") or "").strip():
            source_stage = "burn_subtitle"
            final_video_path = str(burn_data.get("burned_video_path") or "").strip()
            has_subtitle = True

        resolved_final_path = resolve_path_for_io(final_video_path)
        if resolved_final_path is None or not resolved_final_path.exists():
            return StageResult(success=False, error="最终输出视频不存在")

        duration = self._safe_float(
            (burn_data or {}).get("duration")
            if source_stage == "burn_subtitle"
            else compose_data.get("duration")
        )
        if duration <= 0:
            duration = await self._probe_media_duration(resolved_final_path)
        width = self._safe_int(
            (burn_data or {}).get("width")
            if source_stage == "burn_subtitle"
            else compose_data.get("width")
        )
        height = self._safe_int(
            (burn_data or {}).get("height")
            if source_stage == "burn_subtitle"
            else compose_data.get("height")
        )
        if width is None or height is None:
            width, height = await self._probe_video_dimensions(resolved_final_path)

        subtitle_file_path = None
        if subtitle_data:
            subtitle_file_path = str(subtitle_data.get("subtitle_file_path") or "").strip() or None

        return StageResult(
            success=True,
            data={
                "final_video_path": final_video_path,
                "source_stage": source_stage,
                "duration": duration if duration > 0 else None,
                "width": width,
                "height": height,
                "has_subtitle": has_subtitle,
                "subtitle_file_path": subtitle_file_path,
                "updated_at": int(time.time()),
            },
        )

    async def validate_prerequisites(
        self,
        db: AsyncSession,
        project: Project,
    ) -> str | None:
        if not await self._get_compose_data(db, project):
            return COMPOSE_DATA_REQUIRED_ERROR
        return None

    async def _get_compose_data(self, db: AsyncSession, project: Project) -> dict | None:
        return await get_latest_stage_output(
            db,
            project.id,
            StageType.COMPOSE,
            usable_check=is_compose_data_usable,
        )

    async def _get_burn_subtitle_data(self, db: AsyncSession, project: Project) -> dict | None:
        return await get_latest_stage_output(
            db,
            project.id,
            StageType.BURN_SUBTITLE,
            usable_check=is_burn_subtitle_data_usable,
        )

    async def _get_subtitle_data(self, db: AsyncSession, project: Project) -> dict | None:
        return await get_latest_stage_output(
            db,
            project.id,
            StageType.SUBTITLE,
            usable_check=is_subtitle_data_usable,
        )

    async def _probe_media_duration(self, media_path: Path) -> float:
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
            return 0.0
        try:
            return max(0.0, float(stdout.decode(errors="ignore").strip() or 0.0))
        except (TypeError, ValueError):
            return 0.0

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

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None
