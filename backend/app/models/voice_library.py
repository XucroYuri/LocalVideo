from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class VoiceSourceChannel(StrEnum):
    AUDIO_WITH_TEXT = "audio_with_text"
    AUDIO_FILE = "audio_file"
    VIDEO_LINK = "video_link"
    BUILTIN = "builtin"


class VoiceImportJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class VoiceImportTaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class VoiceItemFieldStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"
    CANCELED = "canceled"


def _enum_values(enum_cls: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_cls]


class VoiceLibraryItem(Base, TimestampMixin):
    __tablename__ = "voice_library_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    reference_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    builtin_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)

    source_channel: Mapped[VoiceSourceChannel | None] = mapped_column(
        SQLEnum(VoiceSourceChannel),
        nullable=True,
    )
    auto_parse_text: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    source_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_post_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    source_post_updated_at: Mapped[str | None] = mapped_column(String(128), nullable=True)

    clip_start_requested_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    clip_end_requested_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    clip_start_actual_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    clip_end_actual_sec: Mapped[float | None] = mapped_column(Float, nullable=True)

    name_status: Mapped[VoiceItemFieldStatus] = mapped_column(
        SQLEnum(VoiceItemFieldStatus, values_callable=_enum_values),
        nullable=False,
        default=VoiceItemFieldStatus.READY,
    )
    reference_text_status: Mapped[VoiceItemFieldStatus] = mapped_column(
        SQLEnum(VoiceItemFieldStatus, values_callable=_enum_values),
        nullable=False,
        default=VoiceItemFieldStatus.READY,
    )
    processing_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processing_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class VoiceLibraryImportJob(Base, TimestampMixin):
    __tablename__ = "voice_library_import_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[VoiceImportJobStatus] = mapped_column(
        SQLEnum(VoiceImportJobStatus),
        nullable=False,
        default=VoiceImportJobStatus.PENDING,
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

    tasks: Mapped[list[VoiceLibraryImportTask]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )


class VoiceLibraryImportTask(Base, TimestampMixin):
    __tablename__ = "voice_library_import_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("voice_library_import_jobs.id"), nullable=False, index=True
    )
    source_channel: Mapped[VoiceSourceChannel] = mapped_column(
        SQLEnum(VoiceSourceChannel),
        nullable=False,
    )
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    source_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auto_parse_text: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    clip_start_requested_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    clip_end_requested_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    clip_start_actual_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    clip_end_actual_sec: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[VoiceImportTaskStatus] = mapped_column(
        SQLEnum(VoiceImportTaskStatus),
        nullable=False,
        default=VoiceImportTaskStatus.PENDING,
    )
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stage_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retry_of_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    retry_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    voice_library_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("voice_library_items.id"),
        nullable=True,
        index=True,
    )
    source_post_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    source_post_updated_at: Mapped[str | None] = mapped_column(String(128), nullable=True)

    job: Mapped[VoiceLibraryImportJob] = relationship(back_populates="tasks")
    item: Mapped[VoiceLibraryItem | None] = relationship()
