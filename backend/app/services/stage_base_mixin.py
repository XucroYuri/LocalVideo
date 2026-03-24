"""Infrastructure mixin extracted from StageService.

Provides base helper methods (DB retry, project/stage lookups, output dir, etc.)
that are mixed into the main StageService class.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import ServiceError
from app.core.media_file import ImageScene
from app.core.pipeline import PipelineEngine
from app.models.project import Project
from app.models.stage import StageExecution, StageStatus, StageType
from app.stages.common.paths import resolve_output_dir_value

logger = logging.getLogger(__name__)


class StageBaseMixin:
    """Mixin providing infrastructure helpers for StageService.

    Assumes the composed class sets ``self.db: AsyncSession`` in its ``__init__``.
    """

    db: AsyncSession  # provided by the composed class

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_frame_reference_identity(reference_ids: list[str]) -> str:
        if not reference_ids:
            return ""
        lines = ["参考图顺序映射："]
        for idx, reference_id in enumerate(reference_ids):
            lines.append(f"@图片{idx + 1} = {reference_id}")
        lines.append("请在描述中使用“@图片N”引用对应参考图。")
        return "\n".join(lines)

    @staticmethod
    def _normalize_image_scene(scene: str) -> ImageScene:
        normalized = str(scene or "").strip().lower()
        if normalized not in {"reference", "frame"}:
            raise ServiceError(400, f"Unsupported image scene: {scene}")
        return cast(ImageScene, normalized)

    @staticmethod
    def _coerce_shot_index(item_id: str | int) -> int:
        try:
            return int(item_id)
        except (TypeError, ValueError):
            raise ServiceError(400, f"Invalid shot index: {item_id}")

    @staticmethod
    def _build_common_image_generation_input(request: Any) -> dict[str, Any]:
        return {
            "image_provider": getattr(request, "image_provider", None),
            "image_aspect_ratio": getattr(request, "image_aspect_ratio", None),
            "image_size": getattr(request, "image_size", None),
            "image_resolution": getattr(request, "image_resolution", None),
            "image_wan2gp_preset": getattr(request, "image_wan2gp_preset", None),
            "image_wan2gp_inference_steps": getattr(request, "image_wan2gp_inference_steps", None),
            "image_wan2gp_guidance_scale": getattr(request, "image_wan2gp_guidance_scale", None),
            "image_style": getattr(request, "image_style", None),
            "force_regenerate": True,
        }

    # ------------------------------------------------------------------
    # Async helpers – project / stage lookups
    # ------------------------------------------------------------------

    async def get_project_or_404(self, project_id: int) -> Project:
        result = await self._execute_with_retry(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if not project:
            raise ServiceError(404, "Project not found")
        return project

    async def _get_stage_or_404(
        self,
        project_id: int,
        stage_type: StageType,
        not_found_detail: str,
    ) -> StageExecution:
        result = await self.db.execute(
            select(StageExecution).where(
                StageExecution.project_id == project_id,
                StageExecution.stage_type == stage_type,
            )
        )
        stage = result.scalar_one_or_none()
        if not stage:
            raise ServiceError(404, not_found_detail)
        return stage

    async def _get_or_create_stage(
        self,
        project: Project,
        stage_type: StageType,
        default_output_data: dict[str, Any],
    ) -> StageExecution:
        result = await self.db.execute(
            select(StageExecution).where(
                StageExecution.project_id == project.id,
                StageExecution.stage_type == stage_type,
            )
        )
        stage = result.scalar_one_or_none()
        if stage:
            return stage

        pipeline = PipelineEngine(self.db, project)
        stage = StageExecution(
            project_id=project.id,
            stage_type=stage_type,
            stage_number=pipeline.get_stage_number(stage_type),
            status=StageStatus.COMPLETED,
            progress=100,
            output_data=default_output_data,
        )
        self.db.add(stage)
        await self.db.commit()
        await self.db.refresh(stage)
        return stage

    # ------------------------------------------------------------------
    # Output directory
    # ------------------------------------------------------------------

    def _get_output_dir(self, project: Project) -> Path:
        resolved = resolve_output_dir_value(project.output_dir)
        if resolved:
            resolved.mkdir(parents=True, exist_ok=True)
            return resolved
        base_dir = Path(settings.storage_path) / "projects" / str(project.id)
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir

    # ------------------------------------------------------------------
    # Stage execution helpers
    # ------------------------------------------------------------------

    async def _run_stage_transient(
        self, project: Project, stage_type: StageType, input_data: dict | None
    ) -> PipelineEngine:
        original_status = project.status
        original_current_stage = project.current_stage
        original_error_message = project.error_message

        pipeline = PipelineEngine(self.db, project)
        async for _ in pipeline.run_stage(stage_type, input_data):
            pass

        project.status = original_status
        project.current_stage = original_current_stage
        project.error_message = original_error_message
        await self._commit_with_retry()

        return pipeline

    # ------------------------------------------------------------------
    # DB retry helpers (SQLite lock conflicts)
    # ------------------------------------------------------------------

    async def _commit_with_retry(self, max_attempts: int = 5, base_delay: float = 0.1) -> None:
        """Commit with retry for transient SQLite lock conflicts."""
        for attempt in range(max_attempts):
            try:
                await self.db.commit()
                return
            except OperationalError as e:
                message = str(e).lower()
                is_locked = "database is locked" in message
                if not is_locked or attempt == max_attempts - 1:
                    raise
                try:
                    await self.db.rollback()
                except Exception:
                    pass
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Commit failed due to sqlite lock, retrying (%d/%d) in %.2fs",
                    attempt + 1,
                    max_attempts,
                    delay,
                )
                await asyncio.sleep(delay)

    async def _execute_with_retry(self, statement, max_attempts: int = 5, base_delay: float = 0.05):
        """Execute select/update statements with retry for transient SQLite lock conflicts."""
        for attempt in range(max_attempts):
            try:
                return await self.db.execute(statement)
            except OperationalError as e:
                message = str(e).lower()
                is_locked = "database is locked" in message
                if not is_locked or attempt == max_attempts - 1:
                    raise
                try:
                    await self.db.rollback()
                except Exception:
                    pass
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Execute failed due to sqlite lock, retrying (%d/%d) in %.2fs",
                    attempt + 1,
                    max_attempts,
                    delay,
                )
                await asyncio.sleep(delay)
