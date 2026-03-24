from datetime import datetime

from pydantic import BaseModel, Field

from app.models.text_library import (
    TextImportJobStatus,
    TextImportTaskStatus,
    TextItemFieldStatus,
    TextSourceChannel,
)


class TextLibraryItemResponse(BaseModel):
    id: int
    name: str
    content: str
    source_channel: TextSourceChannel
    title_status: TextItemFieldStatus
    content_status: TextItemFieldStatus
    processing_stage: str | None = None
    processing_message: str | None = None
    error_message: str | None = None
    source_url: str | None = None
    source_file_name: str | None = None
    source_post_id: str | None = None
    source_post_updated_at: str | None = None
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


class TextLibraryListResponse(BaseModel):
    items: list[TextLibraryItemResponse]
    total: int
    page: int | None = None
    page_size: int | None = None


class TextLibraryUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1)
    is_enabled: bool | None = None


class TextLibraryImportCopyRequest(BaseModel):
    content: str = Field(..., min_length=1)


class TextLibraryImportLinksRequest(BaseModel):
    urls_text: str = Field(..., min_length=1)


class TextLibraryImportLinksCreateResponse(BaseModel):
    job_id: str
    job_ids: list[str] = Field(default_factory=list)
    item_ids: list[int] = Field(default_factory=list)


class TextLibraryImportTaskResponse(BaseModel):
    id: int
    source_url: str
    source_channel: TextSourceChannel
    status: TextImportTaskStatus
    stage: str | None = None
    stage_message: str | None = None
    cache_hit: bool = False
    error_message: str | None = None
    cancel_requested: bool = False
    cancel_requested_at: datetime | None = None
    cancel_reason: str | None = None
    retry_of_task_id: int | None = None
    retry_no: int = 0
    text_library_item_id: int | None = None
    source_post_id: str | None = None
    source_post_updated_at: str | None = None


class TextLibraryImportJobResponse(BaseModel):
    id: str
    status: TextImportJobStatus
    total_count: int
    completed_count: int
    success_count: int
    failed_count: int
    canceled_count: int = 0
    cancel_requested: bool = False
    cancel_requested_at: datetime | None = None
    cancel_requested_by: str | None = None
    terminal_at: datetime | None = None
    error_message: str | None = None
    tasks: list[TextLibraryImportTaskResponse]
    created_at: datetime
    updated_at: datetime


class TextLibraryCancelResponse(BaseModel):
    affected_jobs: int = 0
    affected_tasks: int = 0
