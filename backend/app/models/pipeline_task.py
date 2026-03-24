from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .stage import StageType

if TYPE_CHECKING:
    from .pipeline_run import PipelineRun
    from .project import Project


class PipelineTaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class PipelineTaskKind(StrEnum):
    STAGE = "stage"
    PIPELINE_STAGE = "pipeline_stage"


class PipelineTask(Base, TimestampMixin):
    __tablename__ = "pipeline_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("pipeline_runs.id"), nullable=True, index=True
    )
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    stage_type: Mapped[StageType] = mapped_column(SQLEnum(StageType), nullable=False, index=True)
    task_kind: Mapped[PipelineTaskKind] = mapped_column(
        SQLEnum(PipelineTaskKind),
        default=PipelineTaskKind.STAGE,
        nullable=False,
    )
    status: Mapped[PipelineTaskStatus] = mapped_column(
        SQLEnum(PipelineTaskStatus),
        default=PipelineTaskStatus.PENDING,
        nullable=False,
        index=True,
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    worker_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[PipelineRun | None] = relationship(back_populates="tasks")
    project: Mapped[Project] = relationship()
