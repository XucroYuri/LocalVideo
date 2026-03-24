from datetime import datetime

from pydantic import BaseModel, Field

from app.models.voice_library import (
    VoiceImportJobStatus,
    VoiceImportTaskStatus,
    VoiceItemFieldStatus,
    VoiceSourceChannel,
)


class VoiceLibraryItemBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    reference_text: str | None = None
    audio_file_path: str | None = None
    is_enabled: bool = True


class VoiceLibraryItemCreate(VoiceLibraryItemBase):
    pass


class VoiceLibraryItemUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    reference_text: str | None = None
    audio_file_path: str | None = None
    is_enabled: bool | None = None


class VoiceLibraryItemResponse(BaseModel):
    id: int
    name: str
    reference_text: str | None = None
    audio_file_path: str | None = None
    audio_url: str | None = None
    has_audio: bool = False
    is_enabled: bool
    is_builtin: bool
    source_channel: VoiceSourceChannel | None = None
    auto_parse_text: bool = True
    source_url: str | None = None
    source_file_name: str | None = None
    source_post_id: str | None = None
    source_post_updated_at: str | None = None
    clip_start_requested_sec: float | None = None
    clip_end_requested_sec: float | None = None
    clip_start_actual_sec: float | None = None
    clip_end_actual_sec: float | None = None
    name_status: VoiceItemFieldStatus
    reference_text_status: VoiceItemFieldStatus
    processing_stage: str | None = None
    processing_message: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class VoiceLibraryListResponse(BaseModel):
    items: list[VoiceLibraryItemResponse]
    total: int
    page: int | None = None
    page_size: int | None = None


class VoiceLibraryImportAudioFilesResponse(BaseModel):
    item_ids: list[int] = Field(default_factory=list)


class VoiceLibraryImportAudioRow(BaseModel):
    index: int = Field(..., ge=0)
    name: str | None = Field(default=None, max_length=255)
    auto_parse_text: bool = True


class VoiceLibraryImportVideoLinkRequest(BaseModel):
    url: str = Field(..., min_length=1)
    start_time: str | None = None
    end_time: str | None = None


class VoiceLibraryImportVideoLinkCreateResponse(BaseModel):
    job_id: str
    job_ids: list[str] = Field(default_factory=list)
    item_ids: list[int] = Field(default_factory=list)


class VoiceLibraryImportTaskResponse(BaseModel):
    id: int
    source_channel: VoiceSourceChannel
    source_url: str | None = None
    source_file_name: str | None = None
    auto_parse_text: bool = True
    clip_start_requested_sec: float | None = None
    clip_end_requested_sec: float | None = None
    clip_start_actual_sec: float | None = None
    clip_end_actual_sec: float | None = None
    status: VoiceImportTaskStatus
    stage: str | None = None
    stage_message: str | None = None
    error_message: str | None = None
    cancel_requested: bool = False
    cancel_requested_at: datetime | None = None
    cancel_reason: str | None = None
    retry_of_task_id: int | None = None
    retry_no: int = 0
    voice_library_item_id: int | None = None
    source_post_id: str | None = None
    source_post_updated_at: str | None = None


class VoiceLibraryImportJobResponse(BaseModel):
    id: str
    status: VoiceImportJobStatus
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
    tasks: list[VoiceLibraryImportTaskResponse]
    created_at: datetime
    updated_at: datetime


class VoiceLibraryCancelResponse(BaseModel):
    affected_jobs: int = 0
    affected_tasks: int = 0
