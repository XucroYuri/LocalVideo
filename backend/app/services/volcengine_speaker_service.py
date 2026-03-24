from __future__ import annotations

from typing import Any

from app.providers.audio.volcengine_tts_models import (
    VOLCENGINE_TTS_DEFAULT_MODEL_NAME,
    VOLCENGINE_TTS_DEFAULT_RESOURCE_ID,
    VOLCENGINE_TTS_MODEL_VOICE_MAP,
    list_volcengine_tts_voices,
    normalize_volcengine_tts_model_name,
)

VOLCENGINE_TTS_FALLBACK_VOICES: tuple[dict[str, str], ...] = VOLCENGINE_TTS_MODEL_VOICE_MAP[
    VOLCENGINE_TTS_DEFAULT_MODEL_NAME
]


class VolcengineSpeakerService:
    def __init__(
        self,
        *,
        app_key: str = "",
        access_key: str = "",
        resource_id: str = VOLCENGINE_TTS_DEFAULT_RESOURCE_ID,
        model_name: str = VOLCENGINE_TTS_DEFAULT_MODEL_NAME,
        timeout_seconds: float = 20.0,
    ) -> None:
        del app_key, access_key, resource_id, timeout_seconds
        self.model_name = normalize_volcengine_tts_model_name(model_name)

    async def list_speakers(
        self,
        *,
        force_refresh: bool = False,
        model_name: Any | None = None,
    ) -> list[dict[str, str]]:
        del force_refresh
        target_model = (
            normalize_volcengine_tts_model_name(model_name)
            if model_name is not None
            else self.model_name
        )
        return list_volcengine_tts_voices(target_model)
