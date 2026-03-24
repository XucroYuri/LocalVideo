from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey, Integer, Text, event
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.storage_path import normalize_storage_payload_for_persistence

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .project import Project


class StageType(StrEnum):
    RESEARCH = "research"  # Information collection
    CONTENT = "content"  # Content generation
    STORYBOARD = "storyboard"  # Shot planning and video prompt generation
    AUDIO = "audio"  # Audio generation
    REFERENCE = "reference"  # Reference image generation (I2V)
    FIRST_FRAME_DESC = "first_frame_desc"  # First frame description generation
    FRAME = "frame"  # First frame image generation (I2V)
    VIDEO = "video"  # Video generation
    COMPOSE = "compose"  # Compose subtitle-free master video
    SUBTITLE = "subtitle"  # Final subtitle generation
    BURN_SUBTITLE = "burn_subtitle"  # Burn subtitles into the master video
    FINALIZE = "finalize"  # Select the final delivery asset


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StageExecution(Base, TimestampMixin):
    __tablename__ = "stage_executions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    stage_type: Mapped[StageType] = mapped_column(SQLEnum(StageType), nullable=False)
    stage_number: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[StageStatus] = mapped_column(SQLEnum(StageStatus), default=StageStatus.PENDING)
    progress: Mapped[int] = mapped_column(default=0)

    # Input/output data
    input_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Track the last completed item index for batch operations (-1 means no item complete yet)
    last_item_complete: Mapped[int] = mapped_column(Integer, default=-1)

    # Progress tracking for concurrent tasks
    total_items: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_items: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skipped_items: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationship
    project: Mapped["Project"] = relationship(back_populates="stages")


@event.listens_for(StageExecution, "before_insert")
@event.listens_for(StageExecution, "before_update")
def _normalize_stage_execution_storage_paths(
    _mapper,  # noqa: ANN001
    _connection,  # noqa: ANN001
    target: StageExecution,
) -> None:
    state = sa_inspect(target)

    if state.persistent:
        input_changed = state.attrs.input_data.history.has_changes()
        output_changed = state.attrs.output_data.history.has_changes()
        if not input_changed and not output_changed:
            return
        if input_changed:
            target.input_data = normalize_storage_payload_for_persistence(target.input_data)
        if output_changed:
            target.output_data = normalize_storage_payload_for_persistence(target.output_data)
        return

    target.input_data = normalize_storage_payload_for_persistence(target.input_data)
    target.output_data = normalize_storage_payload_for_persistence(target.output_data)
