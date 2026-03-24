"""Shared types used across core, stages, and services layers."""

from dataclasses import dataclass
from typing import Any

from app.models.stage import StageType


@dataclass
class StageResult:
    """Result returned by a stage handler execution."""

    success: bool
    data: dict[str, Any] | None = None
    error: str | None = None
    skipped: bool = False
    message: str | None = None


@dataclass
class StageProgress:
    """Progress update emitted during stage execution."""

    stage_type: StageType
    progress: int
    message: str
    item_complete: int | None = None
    total_items: int | None = None
    completed_items: int | None = None
    skipped_items: int | None = None
    generating_shots: dict[str, dict] | None = None
