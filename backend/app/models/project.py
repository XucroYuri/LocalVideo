from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .asset import Asset
    from .source import Source
    from .stage import StageExecution


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    keywords: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Configuration
    style: Mapped[str] = mapped_column(String(50), default="")
    target_duration: Mapped[int] = mapped_column(default=60)
    video_mode: Mapped[str] = mapped_column(
        String(64), nullable=False, default="oral_script_driven"
    )
    video_type: Mapped[str] = mapped_column(String(64), nullable=False, default="custom")
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Status
    status: Mapped[ProjectStatus] = mapped_column(
        SQLEnum(ProjectStatus), default=ProjectStatus.DRAFT
    )
    current_stage: Mapped[int | None] = mapped_column(nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_emoji: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cover_generation_attempted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cover_generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Output directory
    output_dir: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Relationships
    stages: Mapped[list["StageExecution"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    assets: Mapped[list["Asset"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    sources: Mapped[list["Source"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
