from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .stage import StageType

if TYPE_CHECKING:
    from .pipeline_task import PipelineTask
    from .project import Project


class PipelineRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PipelineRun(Base, TimestampMixin):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    status: Mapped[PipelineRunStatus] = mapped_column(
        SQLEnum(PipelineRunStatus),
        default=PipelineRunStatus.RUNNING,
        nullable=False,
        index=True,
    )

    from_stage: Mapped[StageType | None] = mapped_column(SQLEnum(StageType), nullable=True)
    to_stage: Mapped[StageType | None] = mapped_column(SQLEnum(StageType), nullable=True)
    current_stage: Mapped[StageType | None] = mapped_column(SQLEnum(StageType), nullable=True)
    worker_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped[Project] = relationship()
    tasks: Mapped[list[PipelineTask]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
