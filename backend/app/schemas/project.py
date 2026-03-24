from datetime import datetime

from pydantic import BaseModel, Field

from app.core.project_mode import (
    VIDEO_MODE_ORAL_SCRIPT_DRIVEN,
    VIDEO_TYPE_CUSTOM,
)
from app.models.project import ProjectStatus


class ProjectBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    keywords: str | None = None
    input_text: str | None = None
    style: str = ""
    target_duration: int = Field(default=60, ge=10, le=600)
    video_mode: str = VIDEO_MODE_ORAL_SCRIPT_DRIVEN
    video_type: str = VIDEO_TYPE_CUSTOM
    config: dict | None = None


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=255)
    keywords: str | None = None
    input_text: str | None = None
    style: str | None = None
    target_duration: int | None = Field(None, ge=10, le=600)
    video_mode: str | None = None
    video_type: str | None = None
    config: dict | None = None


class ProjectResponse(ProjectBase):
    id: int
    status: ProjectStatus
    current_stage: int | None = None
    error_message: str | None = None
    output_dir: str | None = None
    cover_emoji: str | None = None
    dialogue_preview: str | None = None
    first_video_url: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]
    total: int
    page: int
    page_size: int
