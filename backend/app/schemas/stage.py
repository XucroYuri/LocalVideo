from datetime import datetime
from typing import Any, Literal

from fastapi import Form
from pydantic import BaseModel, ConfigDict, Field

from app.models.stage import StageStatus, StageType


class StageBase(BaseModel):
    stage_type: StageType
    stage_number: int


class StageResponse(StageBase):
    """Single stage execution response"""

    id: int
    project_id: int
    status: StageStatus
    progress: int = 0
    total_items: int | None = None
    completed_items: int | None = None
    skipped_items: int | None = None
    last_item_complete: int | None = None
    input_data: dict[str, Any] | None = None
    output_data: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StageListItem(BaseModel):
    """Stage item for list view"""

    stage_type: StageType
    stage_number: int
    status: StageStatus
    progress: int = 0
    is_applicable: bool = True
    is_optional: bool = False
    error_message: str | None = None

    model_config = {"from_attributes": True}


class StageListResponse(BaseModel):
    """List of all stages for a project"""

    items: list[StageListItem]
    current_stage: int | None = None


class StageRunRequest(BaseModel):
    """Request to run a stage"""

    input_data: dict[str, Any] | None = None
    force: bool = Field(default=False, description="Force re-run even if already completed")


class StageProgressEvent(BaseModel):
    """SSE progress event"""

    stage_type: StageType
    progress: int
    message: str
    status: StageStatus | None = None
    data: dict[str, Any] | None = None
    item_complete: int | None = None
    total_items: int | None = None
    completed_items: int | None = None
    skipped_items: int | None = None
    generating_shots: dict[str, dict] | None = None


class PipelineRunRequest(BaseModel):
    """Request to run pipeline (multiple stages)"""

    from_stage: StageType | None = None
    to_stage: StageType | None = None


# ---------------------------------------------------------------------------
# Domain-specific request models (moved from api/v1/stages.py)
# ---------------------------------------------------------------------------


class ContentUpdateRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    script_mode: str | None = None
    roles: list[dict] | None = None
    dialogue_lines: list[dict] | None = None


class ReferenceUpdateRequest(BaseModel):
    name: str
    setting: str = ""
    appearance_description: str = ""
    can_speak: bool
    voice_audio_provider: str | None = None
    voice_name: str | None = None
    voice_speed: float | None = None
    voice_wan2gp_preset: str | None = None
    voice_wan2gp_alt_prompt: str | None = None
    voice_wan2gp_audio_guide: str | None = None
    voice_wan2gp_temperature: float | None = None
    voice_wan2gp_top_k: int | None = None
    voice_wan2gp_seed: int | None = None


class CreateReferenceForm:
    """Form-data model for create_reference (multipart upload with file)."""

    def __init__(
        self,
        name: str = Form(default=""),
        setting: str = Form(default=""),
        appearance_description: str = Form(default=""),
        can_speak: bool = Form(default=True),
        voice_audio_provider: str = Form(default=""),
        voice_name: str = Form(default=""),
        voice_speed: float | None = Form(default=None),
        voice_wan2gp_preset: str = Form(default=""),
        voice_wan2gp_alt_prompt: str = Form(default=""),
        voice_wan2gp_audio_guide: str = Form(default=""),
        voice_wan2gp_temperature: float | None = Form(default=None),
        voice_wan2gp_top_k: int | None = Form(default=None),
        voice_wan2gp_seed: int | None = Form(default=None),
    ):
        self.name = name
        self.setting = setting
        self.appearance_description = appearance_description
        self.can_speak = can_speak
        self.voice_audio_provider = voice_audio_provider
        self.voice_name = voice_name
        self.voice_speed = voice_speed
        self.voice_wan2gp_preset = voice_wan2gp_preset
        self.voice_wan2gp_alt_prompt = voice_wan2gp_alt_prompt
        self.voice_wan2gp_audio_guide = voice_wan2gp_audio_guide
        self.voice_wan2gp_temperature = voice_wan2gp_temperature
        self.voice_wan2gp_top_k = voice_wan2gp_top_k
        self.voice_wan2gp_seed = voice_wan2gp_seed


class DescribeFromImageRequest(BaseModel):
    target_language: str | None = None
    prompt_complexity: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None


class ImportReferencesFromLibraryRequest(BaseModel):
    library_reference_ids: list[int]
    start_reference_index: int = 0
    import_setting: bool = True
    import_appearance_description: bool = True
    import_image: bool = True
    import_voice: bool = True


class FrameShotUpdateRequest(BaseModel):
    description: str | None = None
    first_frame_reference_slots: list[dict[str, Any]] | None = None


class ImageRegenerateRequest(BaseModel):
    image_provider: str | None = None
    image_aspect_ratio: str = "9:16"
    image_size: str = "1K"
    image_resolution: str | None = None
    image_wan2gp_preset: str | None = None
    image_wan2gp_inference_steps: int | None = None
    image_wan2gp_guidance_scale: float | None = None
    image_style: str | None = None
    use_reference_consistency: bool = False


class VideoDescUpdateRequest(BaseModel):
    description: str | None = None
    video_reference_slots: list[dict[str, Any]] | None = None


class VideoRegenerateRequest(BaseModel):
    video_provider: str | None = None
    video_model: str | None = None
    aspect_ratio: str = "9:16"
    resolution: str = "1080"
    use_first_frame_ref: bool = False
    use_reference_image_ref: bool = False
    video_wan2gp_t2v_preset: str | None = None
    video_wan2gp_i2v_preset: str | None = None
    video_wan2gp_resolution: str | None = None
    video_wan2gp_inference_steps: int | None = None
    video_wan2gp_sliding_window_size: int | None = None


class AudioRegenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audio_provider: str | None = None
    voice: str | None = None
    speed: float | None = None
    audio_wan2gp_preset: str | None = None
    audio_wan2gp_model_mode: str | None = None
    audio_wan2gp_alt_prompt: str | None = None
    audio_wan2gp_duration_seconds: int | None = None
    audio_wan2gp_temperature: float | None = None
    audio_wan2gp_top_k: int | None = None
    audio_wan2gp_seed: int | None = None
    audio_wan2gp_audio_guide: str | None = None
    audio_wan2gp_split_strategy: str | None = None
    audio_wan2gp_local_stitch_keep_artifacts: bool | None = None


class ShotAssetBulkDeleteRequest(BaseModel):
    shot_indices: list[int] = Field(default_factory=list)


class ShotInsertRequest(BaseModel):
    anchor_index: int = 0
    direction: Literal["before", "after"] = "after"
    count: int = 1


class ShotUpdateRequest(BaseModel):
    voice_content: str | None = None
    speaker_id: str | None = None
    speaker_name: str | None = None


class ShotReorderRequest(BaseModel):
    ordered_shot_ids: list[str]


class ShotMoveRequest(BaseModel):
    shot_id: str
    direction: Literal["up", "down"]
    step: int = 1
