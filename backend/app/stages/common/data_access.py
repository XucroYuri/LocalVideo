from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stage import StageExecution, StageType
from app.stages.common.paths import resolve_stage_payload_for_io


async def get_latest_stage_output(
    db: AsyncSession,
    project_id: int,
    stage_type: StageType,
    *,
    usable_check: Any | None = None,
) -> dict | None:
    result = await db.execute(
        select(StageExecution)
        .where(
            StageExecution.project_id == project_id,
            StageExecution.stage_type == stage_type,
        )
        .order_by(StageExecution.updated_at.desc(), StageExecution.id.desc())
    )
    for stage_row in result.scalars():
        output_data = resolve_stage_payload_for_io(stage_row.output_data)
        if usable_check is not None:
            if usable_check(output_data):
                return output_data
        else:
            if isinstance(output_data, dict):
                return output_data
    return None


async def get_content_data(db: AsyncSession, project_id: int) -> dict | None:
    result = await db.execute(
        select(StageExecution)
        .where(
            StageExecution.project_id == project_id,
            StageExecution.stage_type == StageType.CONTENT,
        )
        .order_by(StageExecution.updated_at.desc(), StageExecution.id.desc())
    )
    for stage_row in result.scalars():
        output_data = resolve_stage_payload_for_io(stage_row.output_data) or {}
        content = output_data.get("content")
        if isinstance(content, str) and content.strip():
            return output_data
    return None
