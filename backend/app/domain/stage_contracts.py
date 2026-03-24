from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.stage import StageType
from app.stages.common.paths import normalize_stage_payload_for_persistence

CONTRACT_VERSION = 1


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ContentOutput(_ContractModel):
    title: str | None = None
    content: str | None = None
    char_count: int | None = None
    shots_locked: bool | None = None
    script_mode: str | None = None
    roles: list[dict[str, Any]] = Field(default_factory=list)
    dialogue_lines: list[dict[str, Any]] = Field(default_factory=list)
    chat_history: list[dict[str, Any]] = Field(default_factory=list)
    chat_summary: str | None = None
    last_user_message: str | None = None


class StoryboardOutput(_ContractModel):
    title: str | None = None
    script_mode: str | None = None
    roles: list[dict[str, Any]] = Field(default_factory=list)
    dialogue_lines: list[dict[str, Any]] = Field(default_factory=list)
    shots: list[dict[str, Any]] = Field(default_factory=list)
    shot_count: int | None = None
    references: list[dict[str, Any]] = Field(default_factory=list)


class AudioOutput(_ContractModel):
    audio_assets: list[dict[str, Any]] = Field(default_factory=list)
    shot_count: int | None = None
    total_duration: float | None = None
    generating_shots: dict[str, dict[str, Any]] | None = None
    progress_message: str | None = None
    runtime_provider: str | None = None
    audio_provider: str | None = None


class FrameOutput(_ContractModel):
    frame_images: list[dict[str, Any]] = Field(default_factory=list)
    shot_count: int | None = None
    success_count: int | None = None


class VideoOutput(_ContractModel):
    video_assets: list[dict[str, Any]] = Field(default_factory=list)
    shot_count: int | None = None


class ComposeOutput(_ContractModel):
    master_video_path: str | None = None
    merged_files: list[dict[str, Any]] = Field(default_factory=list)
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    shot_count: int | None = None


class SubtitleOutput(_ContractModel):
    subtitle_file_path: str | None = None
    subtitle_format: str | None = None
    duration: float | None = None
    line_count: int | None = None
    track_language: str | None = None
    correction_mode: str | None = None
    transcript_text: str | None = None
    corrected_text: str | None = None
    segments: list[dict[str, Any]] = Field(default_factory=list)


class BurnSubtitleOutput(_ContractModel):
    burned_video_path: str | None = None
    subtitle_file_path: str | None = None
    duration: float | None = None
    width: int | None = None
    height: int | None = None


class FinalizeOutput(_ContractModel):
    final_video_path: str | None = None
    source_stage: str | None = None
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    has_subtitle: bool | None = None
    subtitle_file_path: str | None = None


STAGE_OUTPUT_MODELS: dict[StageType, type[_ContractModel]] = {
    StageType.CONTENT: ContentOutput,
    StageType.STORYBOARD: StoryboardOutput,
    StageType.AUDIO: AudioOutput,
    StageType.FRAME: FrameOutput,
    StageType.VIDEO: VideoOutput,
    StageType.COMPOSE: ComposeOutput,
    StageType.SUBTITLE: SubtitleOutput,
    StageType.BURN_SUBTITLE: BurnSubtitleOutput,
    StageType.FINALIZE: FinalizeOutput,
}


def normalize_stage_output(
    stage_type: StageType,
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if payload is None:
        return None

    model_cls = STAGE_OUTPUT_MODELS.get(stage_type)
    if model_cls is None:
        normalized = dict(payload)
    else:
        normalized = model_cls.model_validate(payload).model_dump(mode="python")

    normalized["_contract_version"] = CONTRACT_VERSION
    normalized["_contract_stage"] = stage_type.value
    return normalize_stage_payload_for_persistence(normalized)
