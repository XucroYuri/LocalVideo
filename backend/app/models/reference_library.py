from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class ReferenceSourceChannel(StrEnum):
    MANUAL = "manual"
    IMAGE_BATCH = "image_batch"


class ReferenceImportJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class ReferenceImportTaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class ReferenceItemFieldStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"
    CANCELED = "canceled"


def _enum_values(enum_cls: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_cls]


class ReferenceLibraryItem(Base, TimestampMixin):
    __tablename__ = "reference_library_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    can_speak: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    setting: Mapped[str | None] = mapped_column(Text, nullable=True)
    appearance_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    voice_audio_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    voice_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    voice_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    voice_wan2gp_preset: Mapped[str | None] = mapped_column(String(128), nullable=True)
    voice_wan2gp_alt_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    voice_wan2gp_audio_guide: Mapped[str | None] = mapped_column(Text, nullable=True)
    voice_wan2gp_temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    voice_wan2gp_top_k: Mapped[int | None] = mapped_column(Integer, nullable=True)
    voice_wan2gp_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    image_updated_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_channel: Mapped[ReferenceSourceChannel | None] = mapped_column(
        SQLEnum(ReferenceSourceChannel),
        nullable=True,
    )
    source_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name_status: Mapped[ReferenceItemFieldStatus] = mapped_column(
        SQLEnum(ReferenceItemFieldStatus, values_callable=_enum_values),
        nullable=False,
        default=ReferenceItemFieldStatus.READY,
    )
    appearance_status: Mapped[ReferenceItemFieldStatus] = mapped_column(
        SQLEnum(ReferenceItemFieldStatus, values_callable=_enum_values),
        nullable=False,
        default=ReferenceItemFieldStatus.READY,
    )
    processing_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processing_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReferenceLibraryImportJob(Base, TimestampMixin):
    __tablename__ = "reference_library_import_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[ReferenceImportJobStatus] = mapped_column(
        SQLEnum(ReferenceImportJobStatus),
        nullable=False,
        default=ReferenceImportJobStatus.PENDING,
    )
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    canceled_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancel_requested_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    tasks: Mapped[list[ReferenceLibraryImportTask]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )


class ReferenceLibraryImportTask(Base, TimestampMixin):
    __tablename__ = "reference_library_import_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("reference_library_import_jobs.id"),
        nullable=False,
        index=True,
    )
    source_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    input_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    generate_description: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[ReferenceImportTaskStatus] = mapped_column(
        SQLEnum(ReferenceImportTaskStatus),
        nullable=False,
        default=ReferenceImportTaskStatus.PENDING,
    )
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stage_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retry_of_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    retry_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reference_library_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("reference_library_items.id"),
        nullable=True,
        index=True,
    )

    job: Mapped[ReferenceLibraryImportJob] = relationship(back_populates="tasks")
    item: Mapped[ReferenceLibraryItem | None] = relationship()
