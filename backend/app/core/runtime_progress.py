from __future__ import annotations

from typing import Any

from app.models.stage import StageType

_PROVIDER_KEY_BY_STAGE: dict[StageType, str] = {
    StageType.AUDIO: "audio_provider",
    StageType.FRAME: "image_provider",
    StageType.REFERENCE: "image_provider",
    StageType.VIDEO: "video_provider",
}


def _normalize_provider(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized or None


def is_wan2gp_runtime(
    stage_type: StageType,
    input_data: Any = None,
    output_data: Any = None,
) -> bool:
    provider_key = _PROVIDER_KEY_BY_STAGE.get(stage_type)
    if not provider_key:
        return False

    for source in (input_data, output_data):
        if not isinstance(source, dict):
            continue
        for key in (provider_key, "runtime_provider", "provider"):
            if _normalize_provider(source.get(key)) == "wan2gp":
                return True
    return False


def build_running_fallback_message(
    stage_type: StageType,
    progress: int,
    input_data: Any = None,
    output_data: Any = None,
) -> str:
    if is_wan2gp_runtime(stage_type, input_data=input_data, output_data=output_data):
        if int(progress or 0) <= 0:
            return "准备中..."
        return "生成中..."
    return f"执行中 ({progress}%)"
