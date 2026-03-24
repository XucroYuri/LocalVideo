import math
from typing import Any

from app.config import settings

EMPTY_REFERENCE_VOICE_PAYLOAD: dict[str, Any] = {
    "voice_audio_provider": None,
    "voice_name": None,
    "voice_speed": None,
    "voice_wan2gp_preset": None,
    "voice_wan2gp_alt_prompt": None,
    "voice_wan2gp_audio_guide": None,
    "voice_wan2gp_temperature": None,
    "voice_wan2gp_top_k": None,
    "voice_wan2gp_seed": None,
}


def normalize_reference_voice_audio_provider(value: Any) -> str | None:
    provider = str(value or "").strip().lower()
    if provider in {
        "edge_tts",
        "wan2gp",
        "volcengine_tts",
        "kling_tts",
        "vidu_tts",
        "minimax_tts",
        "xiaomi_mimo_tts",
    }:
        return provider
    return None


def normalize_reference_voice_payload(
    *,
    can_speak: bool,
    voice_audio_provider: Any,
    voice_name: Any,
    voice_speed: Any = None,
    voice_wan2gp_preset: Any = None,
    voice_wan2gp_alt_prompt: Any = None,
    voice_wan2gp_audio_guide: Any = None,
    voice_wan2gp_temperature: Any = None,
    voice_wan2gp_top_k: Any = None,
    voice_wan2gp_seed: Any = None,
    default_wan2gp_preset: str | None = None,
) -> dict[str, Any]:
    def _normalize_text(value: Any) -> str:
        return str(value or "").strip()

    def _normalize_float(value: Any) -> float | None:
        try:
            if value is None:
                return None
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(parsed):
            return None
        return parsed

    def _normalize_int(value: Any) -> int | None:
        try:
            if value is None:
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    if not can_speak:
        return dict(EMPTY_REFERENCE_VOICE_PAYLOAD)

    provider = normalize_reference_voice_audio_provider(voice_audio_provider)
    normalized_voice_name = _normalize_text(voice_name)
    if not provider or not normalized_voice_name:
        return dict(EMPTY_REFERENCE_VOICE_PAYLOAD)

    normalized_speed = _normalize_float(voice_speed)
    if normalized_speed is not None:
        normalized_speed = max(0.5, min(2.0, normalized_speed))

    if provider in {
        "edge_tts",
        "volcengine_tts",
        "kling_tts",
        "vidu_tts",
        "minimax_tts",
        "xiaomi_mimo_tts",
    }:
        return {
            "voice_audio_provider": provider,
            "voice_name": normalized_voice_name,
            "voice_speed": normalized_speed,
            "voice_wan2gp_preset": None,
            "voice_wan2gp_alt_prompt": None,
            "voice_wan2gp_audio_guide": None,
            "voice_wan2gp_temperature": None,
            "voice_wan2gp_top_k": None,
            "voice_wan2gp_seed": None,
        }

    normalized_preset = (
        _normalize_text(voice_wan2gp_preset)
        or default_wan2gp_preset
        or settings.audio_wan2gp_preset
        or "qwen3_tts_base"
    )
    normalized_alt_prompt = _normalize_text(voice_wan2gp_alt_prompt)
    normalized_audio_guide = _normalize_text(voice_wan2gp_audio_guide)
    normalized_temperature = _normalize_float(voice_wan2gp_temperature)
    if normalized_temperature is not None:
        normalized_temperature = max(0.1, min(1.5, normalized_temperature))
    normalized_top_k = _normalize_int(voice_wan2gp_top_k)
    if normalized_top_k is not None:
        normalized_top_k = max(1, min(100, normalized_top_k))
    normalized_seed = _normalize_int(voice_wan2gp_seed)

    return {
        "voice_audio_provider": provider,
        "voice_name": normalized_voice_name,
        "voice_speed": normalized_speed,
        "voice_wan2gp_preset": normalized_preset,
        "voice_wan2gp_alt_prompt": normalized_alt_prompt,
        "voice_wan2gp_audio_guide": normalized_audio_guide,
        "voice_wan2gp_temperature": normalized_temperature,
        "voice_wan2gp_top_k": normalized_top_k,
        "voice_wan2gp_seed": normalized_seed,
    }
