import asyncio
import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.config import settings
from app.providers import get_audio_provider
from app.providers.audio.minimax_tts import (
    MINIMAX_TTS_FALLBACK_VOICES,
    normalize_minimax_api_key,
    normalize_minimax_audio_model,
    normalize_minimax_audio_speed,
    normalize_minimax_base_url,
    normalize_minimax_voice_id,
)
from app.providers.audio.volcengine_tts_models import (
    VOLCENGINE_TTS_DEFAULT_MODEL_NAME,
    is_volcengine_tts_voice_supported,
    list_volcengine_tts_voices,
    normalize_volcengine_tts_model_name,
    resolve_default_volcengine_tts_voice_type,
    resolve_volcengine_tts_resource_id,
)
from app.providers.audio.wan2gp import get_wan2gp_audio_presets
from app.providers.audio.xiaomi_mimo_tts import (
    normalize_xiaomi_mimo_style_preset,
    normalize_xiaomi_mimo_voice,
)
from app.providers.kling_auth import is_kling_configured
from app.providers.wan2gp import STATUS_GENERATING, STATUS_PREPARING
from app.services.voice_library_service import VoiceLibraryService
from app.services.volcengine_speaker_service import VolcengineSpeakerService
from app.stages._audio_cache import (
    SOURCE_AUDIO_SPEED,
    build_audio_render_signature,
    build_audio_source_signature,
    render_audio_from_source,
    resolve_audio_cache_reuse,
    resolve_audio_output_extension,
)
from app.stages._audio_split import probe_audio_duration

from ._common import (
    DEFAULT_AUDIO_PREVIEW_TEXT,
    EDGE_TTS_VOICES,
    _coerce_float,
    _coerce_int,
    _mask_key,
    _normalize_audio_speed,
    _normalize_kling_access_key,
    _normalize_kling_base_url,
    _normalize_kling_secret_key,
    _normalize_openai_like_base_url,
    _normalize_optional_path,
    _normalize_vidu_api_key,
    _normalize_vidu_base_url,
    logger,
    normalize_audio_preview_locale,
    resolve_audio_preview_text_for_locale,
)

router = APIRouter()

REMOVED_WAN2GP_SPLIT_INPUT_KEYS = {
    "audio_wan2gp_sentence_split_every_seconds",
    "audio_wan2gp_anchor_split_every_seconds",
}


class VoiceInfo(BaseModel):
    id: str
    name: str
    locale: str


class VoicesResponse(BaseModel):
    voices: list[VoiceInfo]


class Wan2GPAudioModeInfo(BaseModel):
    id: str
    label: str


class Wan2GPAudioPresetInfo(BaseModel):
    id: str
    display_name: str
    description: str
    model_type: str
    supports_reference_audio: bool
    model_mode_label: str
    model_mode_choices: list[Wan2GPAudioModeInfo]
    default_model_mode: str
    default_alt_prompt: str
    default_duration_seconds: int
    default_temperature: float
    default_top_k: int


class Wan2GPAudioPresetsResponse(BaseModel):
    presets: list[Wan2GPAudioPresetInfo]


def _resolve_audio_preview_provider(provider: str | None) -> str:
    resolved = str(provider or "edge_tts").strip().lower() or "edge_tts"
    if resolved in {
        "edge_tts",
        "wan2gp",
        "volcengine_tts",
        "kling_tts",
        "vidu_tts",
        "minimax_tts",
        "xiaomi_mimo_tts",
    }:
        return resolved
    raise HTTPException(status_code=400, detail=f"Unknown audio provider: {provider}")


def _parse_audio_preview_input_data(input_data: str | None) -> dict[str, object]:
    if not input_data:
        return {}
    try:
        payload = json.loads(input_data)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid input_data JSON format")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="input_data 必须为 JSON 对象")
    removed_keys = sorted(REMOVED_WAN2GP_SPLIT_INPUT_KEYS.intersection(payload.keys()))
    if removed_keys:
        raise HTTPException(
            status_code=400,
            detail=("以下字段已删除，请移除后重试: " + ", ".join(removed_keys)),
        )
    return payload


def _resolve_preview_output_path(provider_name: str) -> Path:
    storage_root = Path(settings.storage_path).expanduser()
    output_dir = storage_root / "_settings_preview" / provider_name
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / f"preview_{int(time.time() * 1000)}_{uuid4().hex[:8]}.mp3"


def _resolve_preview_cache_dir(provider_name: str) -> Path:
    storage_root = Path(settings.storage_path).expanduser()
    cache_dir = storage_root / "_settings_preview" / provider_name / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _build_preview_cache_paths(
    provider_name: str,
    *,
    audio_source_signature: str,
    audio_render_signature: str,
) -> tuple[Path, Path]:
    cache_dir = _resolve_preview_cache_dir(provider_name)
    extension = resolve_audio_output_extension(provider_name)
    source_hash = (
        uuid4().hex
        if not audio_source_signature
        else hashlib.sha1(audio_source_signature.encode("utf-8")).hexdigest()
    )
    render_hash = (
        uuid4().hex
        if not audio_render_signature
        else hashlib.sha1(audio_render_signature.encode("utf-8")).hexdigest()
    )
    source_path = cache_dir / f"source_{source_hash}{extension}"
    render_path = cache_dir / f"render_{render_hash}{extension}"
    return source_path, render_path


def _to_storage_public_url(file_path: Path) -> str:
    storage_root = Path(settings.storage_path).expanduser().resolve()
    resolved = file_path.expanduser().resolve()
    try:
        relative_path = resolved.relative_to(storage_root)
    except ValueError:
        raise HTTPException(status_code=500, detail=f"文件不在 storage 目录下: {resolved}")
    return f"/storage/{relative_path.as_posix()}"


def _resolve_preview_wan2gp_path(input_payload: dict[str, object]) -> str:
    raw_value = input_payload.get("wan2gp_path")
    if raw_value is None:
        resolved = _normalize_optional_path(settings.wan2gp_path)
    else:
        resolved = _normalize_optional_path(str(raw_value))
    if not resolved:
        raise HTTPException(status_code=400, detail="请先填写 wan2gp_path。")
    return resolved


def _resolve_preview_wan2gp_python(input_payload: dict[str, object]) -> str | None:
    raw_value = input_payload.get("local_model_python_path")
    if raw_value is None:
        return _normalize_optional_path(settings.local_model_python_path)
    return _normalize_optional_path(str(raw_value))


def _resolve_preview_edge_rate(input_payload: dict[str, object]) -> str:
    raw_rate = input_payload.get("edge_tts_rate")
    if raw_rate is None:
        raw_rate = settings.edge_tts_rate
    rate = str(raw_rate or "").strip()
    return rate or "+0%"


def _resolve_locale_from_voice_catalog(
    voices: list[dict[str, str]] | tuple[dict[str, str], ...],
    voice_id: str | None,
    *,
    fallback_locale: str = "zh-CN",
) -> str:
    normalized_voice_id = str(voice_id or "").strip()
    for voice in voices:
        if str(voice.get("id") or "").strip() != normalized_voice_id:
            continue
        return normalize_audio_preview_locale(str(voice.get("locale") or fallback_locale))
    return normalize_audio_preview_locale(fallback_locale)


def _resolve_audio_preview_locale(
    provider_name: str,
    input_payload: dict[str, object],
) -> str:
    if provider_name == "edge_tts":
        return _resolve_locale_from_voice_catalog(
            EDGE_TTS_VOICES,
            str(input_payload.get("edge_tts_voice") or settings.edge_tts_voice or "").strip(),
        )
    if provider_name == "volcengine_tts":
        selected_model_name = _resolve_preview_volcengine_model_name(input_payload)
        selected_voice_type = _resolve_preview_volcengine_voice_type(input_payload)
        return _resolve_locale_from_voice_catalog(
            list_volcengine_tts_voices(selected_model_name),
            selected_voice_type,
        )
    if provider_name == "kling_tts":
        kling_language = (
            str(
                input_payload.get("audio_kling_voice_language")
                or settings.audio_kling_voice_language
                or "zh"
            )
            .strip()
            .lower()
        )
        return "en-US" if kling_language == "en" else "zh-CN"
    if provider_name == "vidu_tts":
        return "zh-CN"
    if provider_name == "minimax_tts":
        selected_voice_id = normalize_minimax_voice_id(
            input_payload.get("audio_minimax_voice_id")
            or input_payload.get("voice")
            or settings.audio_minimax_voice_id
        )
        return _resolve_locale_from_voice_catalog(
            MINIMAX_TTS_FALLBACK_VOICES,
            selected_voice_id,
        )
    if provider_name == "xiaomi_mimo_tts":
        style_preset = normalize_xiaomi_mimo_style_preset(
            input_payload.get("audio_xiaomi_mimo_style_preset")
            or settings.audio_xiaomi_mimo_style_preset
        )
        if style_preset == "tai_wan_qiang":
            return "zh-TW"
        if style_preset in {"yue_yu_zhu_bo", "gang_pu_kong_jie"}:
            return "zh-HK"
        selected_voice = normalize_xiaomi_mimo_voice(
            input_payload.get("audio_xiaomi_mimo_voice")
            or input_payload.get("voice")
            or settings.audio_xiaomi_mimo_voice
        )
        return "en-US" if selected_voice == "default_en" else "zh-CN"
    return "zh-CN"


def _resolve_audio_preview_text(
    provider_name: str,
    input_payload: dict[str, object],
) -> str:
    raw_preview_text = input_payload.get("preview_text")
    preview_text = str(raw_preview_text or "").strip()
    if preview_text:
        return preview_text
    resolved_locale = _resolve_audio_preview_locale(provider_name, input_payload)
    return resolve_audio_preview_text_for_locale(resolved_locale) or DEFAULT_AUDIO_PREVIEW_TEXT


def _resolve_preview_volcengine_app_key(input_payload: dict[str, object]) -> str:
    app_key = str(
        input_payload.get("volcengine_tts_app_id")
        or input_payload.get("app_id")
        or input_payload.get("volcengine_tts_app_key")
        or settings.volcengine_tts_app_key
        or ""
    ).strip()
    if not app_key:
        raise HTTPException(status_code=400, detail="请先填写 APP ID。")
    return app_key


def _resolve_preview_volcengine_access_key(input_payload: dict[str, object]) -> str:
    access_key = str(
        input_payload.get("volcengine_tts_access_token")
        or input_payload.get("access_token")
        or input_payload.get("volcengine_tts_access_key")
        or settings.volcengine_tts_access_key
        or ""
    ).strip()
    if not access_key:
        raise HTTPException(status_code=400, detail="请先填写 Access Token。")
    return access_key


def _resolve_preview_volcengine_model_name(input_payload: dict[str, object]) -> str:
    return normalize_volcengine_tts_model_name(
        input_payload.get("volcengine_tts_model_name")
        or settings.volcengine_tts_model_name
        or VOLCENGINE_TTS_DEFAULT_MODEL_NAME
    )


def _resolve_preview_volcengine_voice_type(input_payload: dict[str, object]) -> str:
    resolved_model_name = _resolve_preview_volcengine_model_name(input_payload)
    fallback_voice = resolve_default_volcengine_tts_voice_type(resolved_model_name)
    candidate = (
        str(
            input_payload.get("audio_volcengine_tts_voice_type")
            or input_payload.get("voice")
            or settings.audio_volcengine_tts_voice_type
            or fallback_voice
        ).strip()
        or fallback_voice
    )
    has_explicit_voice = (
        input_payload.get("audio_volcengine_tts_voice_type") is not None
        or input_payload.get("voice") is not None
    )
    if not has_explicit_voice and not is_volcengine_tts_voice_supported(
        resolved_model_name, candidate
    ):
        return fallback_voice
    return candidate


def _resolve_preview_volcengine_encoding(input_payload: dict[str, object]) -> str:
    encoding = (
        str(
            input_payload.get("audio_volcengine_tts_encoding")
            or settings.audio_volcengine_tts_encoding
            or "mp3"
        )
        .strip()
        .lower()
        or "mp3"
    )
    return encoding if encoding in {"mp3", "wav", "pcm", "ogg_opus"} else "mp3"


def _resolve_preview_volcengine_ratio(
    input_payload: dict[str, object],
    *,
    input_key: str,
    setting_value: float,
) -> float:
    return max(
        0.5,
        min(
            2.0,
            _coerce_float(
                input_payload.get(input_key),
                setting_value,
            ),
        ),
    )


def _resolve_preview_kling_auth(input_payload: dict[str, object]) -> dict[str, str]:
    access_key = _normalize_kling_access_key(
        str(input_payload.get("kling_access_key") or settings.kling_access_key or "")
    )
    secret_key = _normalize_kling_secret_key(
        str(input_payload.get("kling_secret_key") or settings.kling_secret_key or "")
    )
    if not is_kling_configured(
        access_key=access_key,
        secret_key=secret_key,
    ):
        raise HTTPException(status_code=400, detail="请先填写可灵 Access Key 和 Secret Key。")
    return {
        "access_key": access_key,
        "secret_key": secret_key,
    }


def _resolve_preview_kling_base_url(input_payload: dict[str, object]) -> str:
    return _normalize_kling_base_url(
        str(input_payload.get("kling_base_url") or settings.kling_base_url or "")
    )


def _resolve_preview_vidu_api_key(input_payload: dict[str, object]) -> str:
    api_key = _normalize_vidu_api_key(input_payload.get("vidu_api_key") or settings.vidu_api_key)
    if not api_key:
        raise HTTPException(status_code=400, detail="请先填写 Vidu API Key。")
    return api_key


def _resolve_preview_vidu_base_url(input_payload: dict[str, object]) -> str:
    return _normalize_vidu_base_url(
        str(input_payload.get("vidu_base_url") or settings.vidu_base_url or "")
    )


def _resolve_preview_xiaomi_mimo_api_key(input_payload: dict[str, object]) -> str:
    api_key = str(
        input_payload.get("xiaomi_mimo_api_key") or settings.xiaomi_mimo_api_key or ""
    ).strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="请先填写小米 MiMo API Key。")
    return api_key


def _resolve_preview_minimax_api_key(input_payload: dict[str, object]) -> str:
    api_key = normalize_minimax_api_key(
        input_payload.get("minimax_api_key") or settings.minimax_api_key or ""
    )
    if not api_key:
        raise HTTPException(status_code=400, detail="请先填写 MiniMax API Key。")
    return api_key


def _resolve_preview_minimax_base_url(input_payload: dict[str, object]) -> str:
    return normalize_minimax_base_url(
        str(input_payload.get("minimax_base_url") or settings.minimax_base_url or "")
    )


def _resolve_preview_xiaomi_mimo_base_url(input_payload: dict[str, object]) -> str:
    return _normalize_openai_like_base_url(
        str(input_payload.get("xiaomi_mimo_base_url") or settings.xiaomi_mimo_base_url or "")
    )


@router.get("/voices", response_model=VoicesResponse)
async def get_voices(
    provider: str = "edge_tts",
    force_refresh: bool = False,
    model_name: str | None = None,
):
    if provider == "edge_tts":
        return VoicesResponse(voices=[VoiceInfo(**v) for v in EDGE_TTS_VOICES])
    if provider == "wan2gp":
        return VoicesResponse(voices=[])
    if provider == "kling_tts":
        return VoicesResponse(voices=[])
    if provider == "vidu_tts":
        return VoicesResponse(voices=[])
    if provider == "minimax_tts":
        return VoicesResponse(voices=[VoiceInfo(**item) for item in MINIMAX_TTS_FALLBACK_VOICES])
    if provider == "xiaomi_mimo_tts":
        return VoicesResponse(voices=[])
    if provider == "volcengine_tts":
        resolved_model_name = normalize_volcengine_tts_model_name(
            model_name or settings.volcengine_tts_model_name or VOLCENGINE_TTS_DEFAULT_MODEL_NAME
        )
        service = VolcengineSpeakerService(
            model_name=resolved_model_name,
        )
        voices_payload = await service.list_speakers(
            force_refresh=bool(force_refresh),
            model_name=resolved_model_name,
        )
        voices = [VoiceInfo(**item) for item in voices_payload if isinstance(item, dict)]
        return VoicesResponse(voices=voices)
    raise HTTPException(status_code=400, detail=f"Unknown audio provider: {provider}")


@router.get("/audio/wan2gp/presets", response_model=Wan2GPAudioPresetsResponse)
async def get_wan2gp_audio_presets_api():
    return Wan2GPAudioPresetsResponse(
        presets=[
            Wan2GPAudioPresetInfo(**item) for item in get_wan2gp_audio_presets(settings.wan2gp_path)
        ]
    )


@router.get("/audio/preview/stream")
async def stream_audio_preview(
    provider: str = Query("edge_tts"),
    input_data: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    provider_name = _resolve_audio_preview_provider(provider)
    input_payload = _parse_audio_preview_input_data(input_data)
    preview_text = _resolve_audio_preview_text(provider_name, input_payload)

    async def event_generator():
        queue: asyncio.Queue[str] = asyncio.Queue()

        async def emit_event(payload: dict[str, object]) -> None:
            await queue.put(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n")

        async def emit_done() -> None:
            await queue.put("data: [DONE]\n\n")

        async def run_preview() -> None:
            last_status_message: str | None = None

            async def emit_status(message: str) -> None:
                nonlocal last_status_message
                normalized = str(message or "").strip()
                if not normalized or normalized == last_status_message:
                    return
                last_status_message = normalized
                logger.info(
                    "[Settings][AudioPreview] provider=%s status=%s",
                    provider_name,
                    normalized,
                )
                await emit_event({"type": "status", "message": normalized})

            async def emit_progress(value: int) -> None:
                await emit_event(
                    {
                        "type": "progress",
                        "progress": max(0, min(100, _coerce_int(value, 0))),
                    }
                )

            try:
                provider_kwargs: dict[str, object] = {}
                synthesize_kwargs: dict[str, object] = {}

                if provider_name == "wan2gp":
                    await emit_status(STATUS_PREPARING)
                    provider_kwargs["wan2gp_path"] = _resolve_preview_wan2gp_path(input_payload)
                    local_model_python_path = _resolve_preview_wan2gp_python(input_payload)
                    if local_model_python_path:
                        provider_kwargs["python_executable"] = local_model_python_path
                    synthesize_kwargs = {
                        "preset": str(
                            input_payload.get("audio_wan2gp_preset")
                            or settings.audio_wan2gp_preset
                            or "qwen3_tts_base"
                        ).strip(),
                        "model_mode": str(
                            input_payload.get("audio_wan2gp_model_mode")
                            or settings.audio_wan2gp_model_mode
                            or ""
                        ).strip(),
                        "alt_prompt": str(
                            input_payload.get("audio_wan2gp_alt_prompt")
                            or settings.audio_wan2gp_alt_prompt
                            or ""
                        ),
                        "duration_seconds": _coerce_int(
                            input_payload.get("audio_wan2gp_duration_seconds"),
                            settings.audio_wan2gp_duration_seconds,
                        ),
                        "temperature": _coerce_float(
                            input_payload.get("audio_wan2gp_temperature"),
                            settings.audio_wan2gp_temperature,
                        ),
                        "top_k": _coerce_int(
                            input_payload.get("audio_wan2gp_top_k"),
                            settings.audio_wan2gp_top_k,
                        ),
                        "seed": _coerce_int(
                            input_payload.get("audio_wan2gp_seed"),
                            settings.audio_wan2gp_seed,
                        ),
                        "audio_guide": str(
                            input_payload.get("audio_wan2gp_audio_guide")
                            or settings.audio_wan2gp_audio_guide
                            or ""
                        ).strip(),
                        "speed": _normalize_audio_speed(
                            input_payload.get("audio_wan2gp_speed"),
                            settings.audio_wan2gp_speed,
                        ),
                        "split_strategy": str(
                            input_payload.get("audio_wan2gp_split_strategy")
                            or settings.audio_wan2gp_split_strategy
                            or "sentence_punct"
                        ).strip(),
                        "status_callback": emit_status,
                        "progress_callback": emit_progress,
                    }
                    if synthesize_kwargs["preset"] == "qwen3_tts_base":
                        audio_guide = str(synthesize_kwargs.get("audio_guide") or "").strip()
                        if not audio_guide:
                            raise ValueError("Wan2GP Base 需要从语音库选择参考语音。")
                        voice_library_service = VoiceLibraryService(db)
                        matched_voice = (
                            await voice_library_service.resolve_active_voice_by_audio_path(
                                audio_guide
                            )
                        )
                        if not matched_voice:
                            raise ValueError("Wan2GP Base 仅支持语音库中已启用且有音频文件的预设。")
                        synthesize_kwargs["audio_guide"] = str(
                            matched_voice.audio_file_path or ""
                        ).strip()
                        synthesize_kwargs["alt_prompt"] = str(matched_voice.reference_text or "")
                elif provider_name == "kling_tts":
                    await emit_status(STATUS_GENERATING)
                    voice_speed = _normalize_audio_speed(
                        input_payload.get("audio_kling_voice_speed"),
                        settings.audio_kling_voice_speed,
                    )
                    rate_percent = int((voice_speed - 1.0) * 100)
                    kling_auth = _resolve_preview_kling_auth(input_payload)
                    provider_kwargs = {
                        "access_key": kling_auth["access_key"],
                        "secret_key": kling_auth["secret_key"],
                        "base_url": _resolve_preview_kling_base_url(input_payload),
                        "voice_id": str(
                            input_payload.get("audio_kling_voice_id")
                            or input_payload.get("voice")
                            or settings.audio_kling_voice_id
                            or "zh_male_qn_qingse"
                        ).strip()
                        or "zh_male_qn_qingse",
                        "voice_language": str(
                            input_payload.get("audio_kling_voice_language")
                            or settings.audio_kling_voice_language
                            or "zh"
                        )
                        .strip()
                        .lower()
                        or "zh",
                        "voice_speed": voice_speed,
                    }
                    synthesize_kwargs = {
                        "voice": str(provider_kwargs["voice_id"]),
                        "voice_language": str(provider_kwargs["voice_language"]),
                        "voice_speed": voice_speed,
                        "rate": f"+{rate_percent}%" if rate_percent >= 0 else f"{rate_percent}%",
                    }
                elif provider_name == "vidu_tts":
                    await emit_status(STATUS_GENERATING)
                    voice_speed = _normalize_audio_speed(
                        input_payload.get("audio_vidu_speed"),
                        settings.audio_vidu_speed,
                    )
                    provider_kwargs = {
                        "api_key": _resolve_preview_vidu_api_key(input_payload),
                        "base_url": _resolve_preview_vidu_base_url(input_payload),
                        "voice_id": str(
                            input_payload.get("audio_vidu_voice_id")
                            or input_payload.get("voice")
                            or settings.audio_vidu_voice_id
                            or "female-shaonv"
                        ).strip()
                        or "female-shaonv",
                        "speed": voice_speed,
                        "volume": max(
                            0.0,
                            min(
                                10.0,
                                _coerce_float(
                                    input_payload.get("audio_vidu_volume"),
                                    float(settings.audio_vidu_volume or 1.0),
                                ),
                            ),
                        ),
                        "pitch": max(
                            -12.0,
                            min(
                                12.0,
                                _coerce_float(
                                    input_payload.get("audio_vidu_pitch"),
                                    float(settings.audio_vidu_pitch or 0.0),
                                ),
                            ),
                        ),
                        "emotion": str(
                            input_payload.get("audio_vidu_emotion")
                            or settings.audio_vidu_emotion
                            or ""
                        ).strip(),
                    }
                    synthesize_kwargs = {
                        "voice": str(provider_kwargs["voice_id"]),
                        "speed": float(provider_kwargs["speed"]),
                        "volume": float(provider_kwargs["volume"]),
                        "pitch": float(provider_kwargs["pitch"]),
                        "emotion": str(provider_kwargs["emotion"]),
                    }
                elif provider_name == "minimax_tts":
                    await emit_status(STATUS_GENERATING)
                    voice_speed = normalize_minimax_audio_speed(
                        input_payload.get("audio_minimax_speed"),
                        settings.audio_minimax_speed,
                    )
                    provider_kwargs = {
                        "api_key": _resolve_preview_minimax_api_key(input_payload),
                        "base_url": _resolve_preview_minimax_base_url(input_payload),
                        "model": normalize_minimax_audio_model(
                            input_payload.get("audio_minimax_model") or settings.audio_minimax_model
                        ),
                        "voice_id": normalize_minimax_voice_id(
                            input_payload.get("audio_minimax_voice_id")
                            or input_payload.get("voice")
                            or settings.audio_minimax_voice_id
                        ),
                        "speed": voice_speed,
                    }
                    synthesize_kwargs = {
                        "voice": str(provider_kwargs["voice_id"]),
                        "model": str(provider_kwargs["model"]),
                        "speed": float(provider_kwargs["speed"]),
                    }
                elif provider_name == "volcengine_tts":
                    await emit_status(STATUS_GENERATING)
                    resolved_model_name = _resolve_preview_volcengine_model_name(input_payload)
                    provider_kwargs = {
                        "app_key": _resolve_preview_volcengine_app_key(input_payload),
                        "access_key": _resolve_preview_volcengine_access_key(input_payload),
                        "model_name": resolved_model_name,
                    }
                    synthesize_kwargs = {
                        "voice": _resolve_preview_volcengine_voice_type(input_payload),
                        "speed_ratio": _resolve_preview_volcengine_ratio(
                            input_payload,
                            input_key="audio_volcengine_tts_speed_ratio",
                            setting_value=float(settings.audio_volcengine_tts_speed_ratio or 1.0),
                        ),
                        "volume_ratio": _resolve_preview_volcengine_ratio(
                            input_payload,
                            input_key="audio_volcengine_tts_volume_ratio",
                            setting_value=float(settings.audio_volcengine_tts_volume_ratio or 1.0),
                        ),
                        "pitch_ratio": _resolve_preview_volcengine_ratio(
                            input_payload,
                            input_key="audio_volcengine_tts_pitch_ratio",
                            setting_value=float(settings.audio_volcengine_tts_pitch_ratio or 1.0),
                        ),
                        "encoding": _resolve_preview_volcengine_encoding(input_payload),
                        "model_name": resolved_model_name,
                        "resource_id": resolve_volcengine_tts_resource_id(resolved_model_name),
                    }
                elif provider_name == "xiaomi_mimo_tts":
                    await emit_status(STATUS_GENERATING)
                    audio_format = (
                        str(
                            input_payload.get("audio_xiaomi_mimo_format")
                            or settings.audio_xiaomi_mimo_format
                            or "wav"
                        )
                        .strip()
                        .lower()
                        or "wav"
                    )
                    if audio_format not in {"wav", "mp3"}:
                        audio_format = "wav"
                    provider_kwargs = {
                        "api_key": _resolve_preview_xiaomi_mimo_api_key(input_payload),
                        "base_url": _resolve_preview_xiaomi_mimo_base_url(input_payload),
                    }
                    synthesize_kwargs = {
                        "voice": normalize_xiaomi_mimo_voice(
                            input_payload.get("audio_xiaomi_mimo_voice")
                            or input_payload.get("voice")
                            or settings.audio_xiaomi_mimo_voice
                            or "mimo_default"
                        ),
                        "audio_xiaomi_mimo_style_preset": normalize_xiaomi_mimo_style_preset(
                            input_payload.get("audio_xiaomi_mimo_style_preset")
                            or settings.audio_xiaomi_mimo_style_preset
                        ),
                        "audio_format": audio_format,
                    }
                else:
                    await emit_status(STATUS_GENERATING)
                    synthesize_kwargs = {
                        "voice": str(
                            input_payload.get("edge_tts_voice")
                            or settings.edge_tts_voice
                            or "zh-CN-YunjianNeural"
                        ).strip(),
                        "rate": _resolve_preview_edge_rate(input_payload),
                    }

                target_speed = SOURCE_AUDIO_SPEED
                source_signature_config: dict[str, object] = {}
                if provider_name == "wan2gp":
                    target_speed = float(synthesize_kwargs.get("speed") or SOURCE_AUDIO_SPEED)
                    source_signature_config = {
                        "preset": synthesize_kwargs.get("preset"),
                        "model_mode": synthesize_kwargs.get("model_mode"),
                        "alt_prompt": synthesize_kwargs.get("alt_prompt"),
                        "duration_seconds": synthesize_kwargs.get("duration_seconds"),
                        "temperature": synthesize_kwargs.get("temperature"),
                        "top_k": synthesize_kwargs.get("top_k"),
                        "seed": synthesize_kwargs.get("seed"),
                        "audio_guide": synthesize_kwargs.get("audio_guide"),
                        "split_strategy": synthesize_kwargs.get("split_strategy"),
                    }
                    synthesize_kwargs["speed"] = SOURCE_AUDIO_SPEED
                elif provider_name == "kling_tts":
                    target_speed = float(synthesize_kwargs.get("voice_speed") or SOURCE_AUDIO_SPEED)
                    source_signature_config = {
                        "voice": synthesize_kwargs.get("voice"),
                        "voice_language": synthesize_kwargs.get("voice_language"),
                    }
                    synthesize_kwargs["voice_speed"] = SOURCE_AUDIO_SPEED
                    synthesize_kwargs["rate"] = "+0%"
                    provider_kwargs["voice_speed"] = SOURCE_AUDIO_SPEED
                elif provider_name == "vidu_tts":
                    target_speed = float(synthesize_kwargs.get("speed") or SOURCE_AUDIO_SPEED)
                    source_signature_config = {
                        "voice": synthesize_kwargs.get("voice"),
                        "volume": synthesize_kwargs.get("volume"),
                        "pitch": synthesize_kwargs.get("pitch"),
                        "emotion": synthesize_kwargs.get("emotion"),
                    }
                    synthesize_kwargs["speed"] = SOURCE_AUDIO_SPEED
                    provider_kwargs["speed"] = SOURCE_AUDIO_SPEED
                elif provider_name == "volcengine_tts":
                    target_speed = float(synthesize_kwargs.get("speed_ratio") or SOURCE_AUDIO_SPEED)
                    source_signature_config = {
                        "voice": synthesize_kwargs.get("voice"),
                        "volume_ratio": synthesize_kwargs.get("volume_ratio"),
                        "pitch_ratio": synthesize_kwargs.get("pitch_ratio"),
                        "encoding": synthesize_kwargs.get("encoding"),
                        "model_name": synthesize_kwargs.get("model_name"),
                        "resource_id": synthesize_kwargs.get("resource_id"),
                    }
                    synthesize_kwargs["speed_ratio"] = SOURCE_AUDIO_SPEED
                elif provider_name == "xiaomi_mimo_tts":
                    target_speed = _normalize_audio_speed(
                        input_payload.get("speed"),
                        SOURCE_AUDIO_SPEED,
                    )
                    source_signature_config = {
                        "voice": synthesize_kwargs.get("voice"),
                        "style_preset": synthesize_kwargs.get("audio_xiaomi_mimo_style_preset"),
                        "audio_format": synthesize_kwargs.get("audio_format"),
                    }
                elif provider_name == "minimax_tts":
                    target_speed = normalize_minimax_audio_speed(
                        synthesize_kwargs.get("speed"),
                        SOURCE_AUDIO_SPEED,
                    )
                    source_signature_config = {
                        "voice": synthesize_kwargs.get("voice"),
                        "model": synthesize_kwargs.get("model"),
                    }
                    synthesize_kwargs["speed"] = SOURCE_AUDIO_SPEED
                    provider_kwargs["speed"] = SOURCE_AUDIO_SPEED
                else:
                    edge_rate = str(synthesize_kwargs.get("rate") or "+0%").strip() or "+0%"
                    matched = edge_rate.rstrip("%")
                    try:
                        target_speed = 1.0 + (float(matched) / 100.0)
                    except ValueError:
                        target_speed = SOURCE_AUDIO_SPEED
                    source_signature_config = {
                        "voice": synthesize_kwargs.get("voice"),
                    }
                    synthesize_kwargs["rate"] = "+0%"

                audio_source_signature = build_audio_source_signature(
                    provider_name=provider_name,
                    text=preview_text,
                    config=source_signature_config,
                )
                audio_render_signature = build_audio_render_signature(
                    audio_source_signature=audio_source_signature,
                    speed=target_speed,
                )
                if provider_name == "xiaomi_mimo_tts":
                    cache_dir = _resolve_preview_cache_dir(provider_name)
                    extension = (
                        ".mp3"
                        if str(synthesize_kwargs.get("audio_format") or "wav").strip().lower()
                        == "mp3"
                        else ".wav"
                    )
                    source_path = cache_dir / (
                        f"source_{hashlib.sha1(audio_source_signature.encode('utf-8')).hexdigest()}{extension}"
                    )
                    render_path = cache_dir / (
                        f"render_{hashlib.sha1(audio_render_signature.encode('utf-8')).hexdigest()}{extension}"
                    )
                else:
                    source_path, render_path = _build_preview_cache_paths(
                        provider_name,
                        audio_source_signature=audio_source_signature,
                        audio_render_signature=audio_render_signature,
                    )
                reuse = resolve_audio_cache_reuse(
                    existing_asset={
                        "file_path": str(render_path),
                        "source_file_path": str(source_path),
                        "audio_source_signature": audio_source_signature,
                        "audio_render_signature": audio_render_signature,
                    },
                    audio_source_signature=audio_source_signature,
                    audio_render_signature=audio_render_signature,
                    force_regenerate=False,
                )

                logger.info(
                    "[Settings][AudioPreview] start provider=%s render=%s app_key=%s access_key=%s",
                    provider_name,
                    render_path,
                    _mask_key(str(provider_kwargs.get("app_key") or ""))
                    if provider_name == "volcengine_tts"
                    else "-",
                    _mask_key(str(provider_kwargs.get("access_key") or ""))
                    if provider_name == "volcengine_tts"
                    else "-",
                )

                if reuse.reuse_render:
                    await emit_status("复用最终音频")
                elif reuse.reuse_source and reuse.source_file_path is not None:
                    await emit_status("变速中...")
                    await render_audio_from_source(
                        source_file_path=reuse.source_file_path,
                        output_path=render_path,
                        speed=target_speed,
                    )
                else:
                    audio_provider = get_audio_provider(provider_name, **provider_kwargs)
                    tmp_source_output = source_path.with_name(
                        f"{source_path.stem}.tmp_{uuid4().hex[:8]}{source_path.suffix}"
                    )
                    result = await audio_provider.synthesize(
                        text=preview_text,
                        output_path=tmp_source_output,
                        **synthesize_kwargs,
                    )
                    rendered_candidate = Path(str(result.file_path))
                    source_candidate = (
                        Path(str(result.source_file_path))
                        if result.source_file_path is not None
                        else rendered_candidate
                    )
                    source_path.parent.mkdir(parents=True, exist_ok=True)
                    if source_path.exists():
                        source_path.unlink()
                    source_candidate.replace(source_path)
                    if rendered_candidate.exists() and rendered_candidate != source_path:
                        rendered_candidate.unlink(missing_ok=True)
                    if target_speed != SOURCE_AUDIO_SPEED:
                        await emit_status("变速中...")
                    await render_audio_from_source(
                        source_file_path=source_path,
                        output_path=render_path,
                        speed=target_speed,
                    )

                public_url = _to_storage_public_url(render_path)
                duration = await probe_audio_duration(render_path)
                await emit_event(
                    {
                        "type": "result",
                        "message": "生成完成",
                        "audio_url": public_url,
                        "duration": round(float(duration or 0.0), 3),
                        "sample_rate": 0,
                    }
                )
            except HTTPException as exc:
                detail = exc.detail
                message = (
                    detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
                )
                await emit_event({"type": "error", "message": message})
            except Exception as exc:
                logger.exception("[Settings][AudioPreview] failed provider=%s", provider_name)
                await emit_event({"type": "error", "message": str(exc) or "音频试用失败"})
            finally:
                await emit_done()

        worker = asyncio.create_task(run_preview())
        try:
            while True:
                chunk = await queue.get()
                yield chunk
                if chunk.strip() == "data: [DONE]":
                    break
        finally:
            if not worker.done():
                worker.cancel()
                try:
                    await worker
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
