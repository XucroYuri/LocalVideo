from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class TextSourceChannel(StrEnum):
    COPY = "copy"
    FILE = "file"
    WEB = "web"
    XIAOHONGSHU = "xiaohongshu"
    DOUYIN = "douyin"
    KUAISHOU = "kuaishou"


class TextImportJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class TextImportTaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class TextItemFieldStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"
    CANCELED = "canceled"


def _enum_values(enum_cls: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_cls]


class TextLibraryItem(Base, TimestampMixin):
    __tablename__ = "text_library_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_channel: Mapped[TextSourceChannel] = mapped_column(
        SQLEnum(TextSourceChannel),
        nullable=False,
    )
    title_status: Mapped[TextItemFieldStatus] = mapped_column(
        SQLEnum(TextItemFieldStatus, values_callable=_enum_values),
        nullable=False,
        default=TextItemFieldStatus.READY,
    )
    content_status: Mapped[TextItemFieldStatus] = mapped_column(
        SQLEnum(TextItemFieldStatus, values_callable=_enum_values),
        nullable=False,
        default=TextItemFieldStatus.READY,
    )
    processing_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processing_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    source_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_post_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    source_post_updated_at: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class TextLibraryPostCache(Base, TimestampMixin):
    __tablename__ = "text_library_post_cache"
    __table_args__ = (
        UniqueConstraint(
            "source_channel", "post_id", name="uq_text_library_post_cache_channel_post_id"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_channel: Mapped[TextSourceChannel] = mapped_column(
        SQLEnum(TextSourceChannel),
        nullable=False,
    )
    post_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    post_updated_at: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    media_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    media_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    title_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    note_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    combined_content: Mapped[str] = mapped_column(Text, nullable=False)
    generated_title: Mapped[str | None] = mapped_column(String(255), nullable=True)


class TextLibraryImportJob(Base, TimestampMixin):
    __tablename__ = "text_library_import_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[TextImportJobStatus] = mapped_column(
        SQLEnum(TextImportJobStatus),
        nullable=False,
        default=TextImportJobStatus.PENDING,
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

    tasks: Mapped[list[TextLibraryImportTask]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )


class TextLibraryImportTask(Base, TimestampMixin):
    __tablename__ = "text_library_import_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("text_library_import_jobs.id"), nullable=False, index=True
    )
    source_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    source_channel: Mapped[TextSourceChannel] = mapped_column(
        SQLEnum(TextSourceChannel),
        nullable=False,
    )
    status: Mapped[TextImportTaskStatus] = mapped_column(
        SQLEnum(TextImportTaskStatus),
        nullable=False,
        default=TextImportTaskStatus.PENDING,
    )
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stage_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retry_of_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    retry_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text_library_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("text_library_items.id"),
        nullable=True,
        index=True,
    )
    source_post_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    source_post_updated_at: Mapped[str | None] = mapped_column(String(128), nullable=True)

    job: Mapped[TextLibraryImportJob] = relationship(back_populates="tasks")
    item: Mapped[TextLibraryItem | None] = relationship()
