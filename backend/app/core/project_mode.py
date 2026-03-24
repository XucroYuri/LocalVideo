from typing import Any

from app.core.dialogue import (
    SCRIPT_MODE_CUSTOM,
    SCRIPT_MODE_DIALOGUE_SCRIPT,
    SCRIPT_MODE_DUO_PODCAST,
    SCRIPT_MODE_SINGLE,
    resolve_script_mode,
)

VIDEO_MODE_ORAL_SCRIPT_DRIVEN = "oral_script_driven"
VIDEO_MODE_AUDIO_VISUAL_DRIVEN = "audio_visual_driven"
SUPPORTED_VIDEO_MODES = {
    VIDEO_MODE_ORAL_SCRIPT_DRIVEN,
    VIDEO_MODE_AUDIO_VISUAL_DRIVEN,
}

VIDEO_TYPE_CUSTOM = "custom"
VIDEO_TYPE_SINGLE_NARRATION = "single_narration"
VIDEO_TYPE_DUO_PODCAST = "duo_podcast"
VIDEO_TYPE_DIALOGUE_SCRIPT = "dialogue_script"

ORAL_SCRIPT_DRIVEN_VIDEO_TYPES = {
    VIDEO_TYPE_CUSTOM,
    VIDEO_TYPE_SINGLE_NARRATION,
    VIDEO_TYPE_DUO_PODCAST,
    VIDEO_TYPE_DIALOGUE_SCRIPT,
}


def resolve_video_mode(value: Any, default: str = VIDEO_MODE_ORAL_SCRIPT_DRIVEN) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in SUPPORTED_VIDEO_MODES:
        return normalized
    return default


def resolve_video_type(
    value: Any,
    *,
    video_mode: str = VIDEO_MODE_ORAL_SCRIPT_DRIVEN,
    default: str = VIDEO_TYPE_CUSTOM,
) -> str:
    normalized = str(value or "").strip().lower()
    resolved_video_mode = resolve_video_mode(video_mode)
    if resolved_video_mode == VIDEO_MODE_AUDIO_VISUAL_DRIVEN:
        return VIDEO_TYPE_CUSTOM
    if normalized in ORAL_SCRIPT_DRIVEN_VIDEO_TYPES:
        return normalized
    return default


def resolve_script_mode_from_video_type(video_type: Any) -> str:
    resolved_video_type = resolve_video_type(video_type)
    if resolved_video_type == VIDEO_TYPE_DUO_PODCAST:
        return SCRIPT_MODE_DUO_PODCAST
    if resolved_video_type == VIDEO_TYPE_DIALOGUE_SCRIPT:
        return SCRIPT_MODE_DIALOGUE_SCRIPT
    if resolved_video_type == VIDEO_TYPE_CUSTOM:
        return SCRIPT_MODE_CUSTOM
    return SCRIPT_MODE_SINGLE


def resolve_video_type_from_script_mode(script_mode: Any) -> str:
    resolved_script_mode = resolve_script_mode(script_mode)
    if resolved_script_mode == SCRIPT_MODE_CUSTOM:
        return VIDEO_TYPE_CUSTOM
    if resolved_script_mode == SCRIPT_MODE_DUO_PODCAST:
        return VIDEO_TYPE_DUO_PODCAST
    if resolved_script_mode == SCRIPT_MODE_DIALOGUE_SCRIPT:
        return VIDEO_TYPE_DIALOGUE_SCRIPT
    return VIDEO_TYPE_SINGLE_NARRATION
