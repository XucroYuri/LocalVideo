from datetime import datetime

from pydantic import BaseModel, Field

from app.models.reference_library import (
    ReferenceImportJobStatus,
    ReferenceImportTaskStatus,
    ReferenceItemFieldStatus,
    ReferenceSourceChannel,
)


class ReferenceLibraryBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    is_enabled: bool = True
    can_speak: bool = False
    setting: str | None = None
    appearance_description: str | None = None
    voice_audio_provider: str | None = None
    voice_name: str | None = None
    voice_speed: float | None = None
    voice_wan2gp_preset: str | None = None
    voice_wan2gp_alt_prompt: str | None = None
    voice_wan2gp_audio_guide: str | None = None
    voice_wan2gp_temperature: float | None = None
    voice_wan2gp_top_k: int | None = None
    voice_wan2gp_seed: int | None = None


class ReferenceLibraryCreate(ReferenceLibraryBase):
    pass


class ReferenceLibraryUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    is_enabled: bool | None = None
    can_speak: bool | None = None
    setting: str | None = None
    appearance_description: str | None = None
    voice_audio_provider: str | None = None
    voice_name: str | None = None
    voice_speed: float | None = None
    voice_wan2gp_preset: str | None = None
    voice_wan2gp_alt_prompt: str | None = None
    voice_wan2gp_audio_guide: str | None = None
    voice_wan2gp_temperature: float | None = None
    voice_wan2gp_top_k: int | None = None
    voice_wan2gp_seed: int | None = None


class ReferenceLibraryResponse(ReferenceLibraryBase):
    id: int
    image_file_path: str | None = None
    image_updated_at: int | None = None
    source_channel: ReferenceSourceChannel | None = None
    source_file_name: str | None = None
    name_status: ReferenceItemFieldStatus
    appearance_status: ReferenceItemFieldStatus
    processing_stage: str | None = None
    processing_message: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReferenceLibraryListResponse(BaseModel):
    items: list[ReferenceLibraryResponse]
    total: int
    page: int | None = None
    page_size: int | None = None


class ReferenceLibraryImportImageRow(BaseModel):
    index: int = Field(..., ge=0)
    name: str | None = Field(default=None, max_length=255)
    generate_description: bool = True


class ReferenceLibraryImportImagesCreateResponse(BaseModel):
    job_id: str
    job_ids: list[str] = Field(default_factory=list)
    item_ids: list[int] = Field(default_factory=list)


class ReferenceLibraryImportTaskResponse(BaseModel):
    id: int
    source_file_name: str
    input_name: str | None = None
    generate_description: bool
    status: ReferenceImportTaskStatus
    stage: str | None = None
    stage_message: str | None = None
    error_message: str | None = None
    cancel_requested: bool = False
    cancel_requested_at: datetime | None = None
    cancel_reason: str | None = None
    retry_of_task_id: int | None = None
    retry_no: int = 0
    reference_library_item_id: int | None = None


class ReferenceLibraryImportJobResponse(BaseModel):
    id: str
    status: ReferenceImportJobStatus
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
    tasks: list[ReferenceLibraryImportTaskResponse]
    created_at: datetime
    updated_at: datetime


class ReferenceLibraryCancelResponse(BaseModel):
    affected_jobs: int = 0
    affected_tasks: int = 0
