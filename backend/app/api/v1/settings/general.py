import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.config import settings
from app.core.dialogue import normalize_dialogue_max_roles
from app.core.errors import ServiceError
from app.image_catalog import default_image_providers
from app.llm.catalog import (
    BUILTIN_MINIMAX_LLM_PROVIDER_ID,
    BUILTIN_XIAOMI_MIMO_LLM_PROVIDER_ID,
    default_llm_providers,
)
from app.providers.audio.minimax_tts import (
    normalize_minimax_api_key,
    normalize_minimax_audio_model,
    normalize_minimax_audio_speed,
    normalize_minimax_base_url,
    normalize_minimax_voice_id,
)
from app.providers.audio.volcengine_tts_models import (
    VOLCENGINE_TTS_DEFAULT_MODEL_NAME,
    is_volcengine_tts_voice_supported,
    normalize_volcengine_tts_model_name,
    resolve_default_volcengine_tts_voice_type,
    resolve_volcengine_tts_resource_id,
)
from app.providers.audio.xiaomi_mimo_tts import (
    normalize_xiaomi_mimo_style_preset,
    normalize_xiaomi_mimo_voice,
)
from app.providers.image.minimax import (
    MINIMAX_IMAGE_ASPECT_RATIOS,
    MINIMAX_IMAGE_MODEL_OPTIONS,
    normalize_minimax_image_aspect_ratio,
    normalize_minimax_image_model,
    normalize_minimax_image_size,
)
from app.providers.kling_auth import is_kling_configured
from app.schemas.settings import SettingsResponse, SettingsUpdate
from app.services.settings_store import PERSISTABLE_SETTING_KEYS, SettingsStoreService
from app.services.voice_library_service import VoiceLibraryService

from ._common import (
    FASTER_WHISPER_MODELS,
    RUNTIME_VALIDATION_STATUS_NOT_READY,
    _coerce_float,
    _is_wan2gp_available,
    _normalize_image_provider_id,
    _normalize_image_providers,
    _normalize_kling_access_key,
    _normalize_kling_base_url,
    _normalize_kling_secret_key,
    _normalize_llm_providers,
    _normalize_minimax_base_url,
    _normalize_model_strings,
    _normalize_openai_like_base_url,
    _normalize_optional_path,
    _normalize_seedance_base_url,
    _normalize_video_provider_id,
    _normalize_vidu_api_key,
    _normalize_vidu_base_url,
    _resolve_runtime_validation_status,
)

router = APIRouter()
WEB_URL_PARSER_PROVIDERS = {"jina_reader", "crawl4ai"}
SPEECH_RECOGNITION_PROVIDERS = {"faster_whisper", "volcengine_asr"}
DEFAULT_SPEECH_RECOGNITION_PROVIDER = "faster_whisper"
SPEECH_MODEL_BINDING_SEPARATOR = "::"
KLING_IMAGE_MODELS = {"kling-v3", "kling-v3-omni"}
KLING_IMAGE_ASPECT_RATIOS = {"16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "21:9"}
KLING_IMAGE_SIZES_BY_MODEL = {
    "kling-v3": {"1K", "2K", "4K"},
    "kling-v3-omni": {"1K", "2K"},
}
VIDU_IMAGE_ASPECT_RATIOS = {"16:9", "9:16", "1:1", "3:4", "4:3", "21:9", "2:3", "3:2"}
VIDU_VIDEO_ASPECT_RATIOS = {"16:9", "9:16", "3:4", "4:3", "1:1"}
MINIMAX_IMAGE_ASPECT_RATIO_SET = set(MINIMAX_IMAGE_ASPECT_RATIOS)
MINIMAX_IMAGE_MODEL_SET = set(MINIMAX_IMAGE_MODEL_OPTIONS)
BUILTIN_VOLCENGINE_LLM_PROVIDER_ID = "builtin_volcengine"
BUILTIN_VOLCENGINE_SEEDREAM_PROVIDER_ID = "builtin_volcengine_seedream"
CONTAINERIZED_LOCKED_PATH_KEYS = {
    "wan2gp_path",
    "local_model_python_path",
    "xhs_downloader_path",
    "tiktok_downloader_path",
    "ks_downloader_path",
}


class ProvidersResponse(BaseModel):
    llm: list[str]
    audio: list[str]
    speech: list[str]
    image: list[str]
    video: list[str]


def _resolve_google_credentials_dir() -> Path:
    storage_root = Path(settings.storage_path).expanduser().resolve()
    return storage_root.parent / "credentials"


def _sanitize_google_credentials_filename(filename: str | None) -> str:
    candidate = Path(str(filename or "").strip()).name
    if not candidate:
        candidate = "google-service-account.json"
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", candidate).strip(".-")
    if not sanitized:
        sanitized = "google-service-account"
    if Path(sanitized).suffix.lower() != ".json":
        sanitized = f"{sanitized}.json"
    return sanitized


def _load_google_credentials_project_id(credentials_path: str | Path) -> str:
    path = Path(credentials_path).expanduser().resolve()
    with path.open(encoding="utf-8") as file_obj:
        payload = json.load(file_obj)
    if not isinstance(payload, dict):
        raise ValueError("服务账号密钥内容必须是 JSON 对象")
    project_id = str(payload.get("project_id") or "").strip()
    if not project_id:
        raise ValueError("服务账号密钥缺少 project_id")
    return project_id


def _apply_google_credentials_path(payload: dict[str, object], raw_path: str | None) -> None:
    normalized_path = str(raw_path or "").strip()
    payload["google_credentials_path"] = normalized_path or None
    if not normalized_path:
        os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
        return

    credentials_path = Path(normalized_path).expanduser().resolve()
    if not credentials_path.exists():
        raise HTTPException(status_code=400, detail="Google 服务账号密钥文件不存在")

    try:
        _load_google_credentials_project_id(credentials_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail="Google 服务账号密钥不是有效的 JSON 文件"
        ) from exc

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(credentials_path)


def _clear_google_credentials() -> None:
    previous_path = str(settings.google_credentials_path or "").strip()
    previous_file = Path(previous_path).expanduser().resolve() if previous_path else None
    credentials_dir = _resolve_google_credentials_dir().resolve()
    if previous_file:
        try:
            if previous_file.parent == credentials_dir and previous_file.exists():
                previous_file.unlink()
        except OSError:
            pass

    settings.google_credentials_path = None
    os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)


def _normalize_speech_recognition_provider(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in SPEECH_RECOGNITION_PROVIDERS:
        return normalized
    return DEFAULT_SPEECH_RECOGNITION_PROVIDER


def _normalize_speech_model_binding(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if SPEECH_MODEL_BINDING_SEPARATOR not in text:
        return text
    provider, model = text.split(SPEECH_MODEL_BINDING_SEPARATOR, 1)
    normalized_provider = _normalize_speech_recognition_provider(provider)
    normalized_model = str(model or "").strip()
    if not normalized_model:
        return ""
    return f"{normalized_provider}{SPEECH_MODEL_BINDING_SEPARATOR}{normalized_model}"


def _normalize_kling_image_model(value: str | None) -> str:
    normalized = str(value or "").strip()
    return normalized if normalized in KLING_IMAGE_MODELS else "kling-v3"


def _is_containerized_runtime() -> bool:
    runtime_env = str(os.getenv("LOCALVIDEO_RUNTIME_ENV") or "").strip().lower()
    if runtime_env in {"docker", "container", "containerized"}:
        return True
    if Path("/.dockerenv").exists():
        return True
    return False


def _drop_containerized_locked_path_updates(payload: dict[str, object]) -> None:
    if not _is_containerized_runtime():
        return
    for key in CONTAINERIZED_LOCKED_PATH_KEYS:
        payload.pop(key, None)


def _normalize_kling_image_aspect_ratio(
    value: str | None,
    *,
    default: str,
) -> str:
    normalized = str(value or "").strip().lower().replace("：", ":")
    return normalized if normalized in KLING_IMAGE_ASPECT_RATIOS else default


def _normalize_kling_image_size(
    value: str | None,
    *,
    model: str,
    default: str = "1K",
) -> str:
    normalized = str(value or "").strip().upper()
    allowed = KLING_IMAGE_SIZES_BY_MODEL.get(
        _normalize_kling_image_model(model), {"1K", "2K", "4K"}
    )
    if normalized in allowed:
        return normalized
    normalized_default = str(default or "1K").strip().upper()
    if normalized_default in allowed:
        return normalized_default
    return sorted(allowed)[0]


def _normalize_vidu_image_aspect_ratio(
    value: str | None,
    *,
    default: str = "1:1",
) -> str:
    normalized = str(value or "").strip().lower().replace("：", ":")
    if normalized in VIDU_IMAGE_ASPECT_RATIOS:
        return normalized
    fallback = str(default or "1:1").strip().lower().replace("：", ":")
    return fallback if fallback in VIDU_IMAGE_ASPECT_RATIOS else "1:1"


def _normalize_vidu_image_size(
    value: str | None,
    *,
    default: str = "1080p",
) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"1080", "1080p", "1k"}:
        return "1080p"
    if normalized in {"2k", "2048"}:
        return "2K"
    if normalized in {"4k", "4096"}:
        return "4K"
    fallback = str(default or "1080p").strip().lower()
    if fallback in {"1080", "1080p", "1k"}:
        return "1080p"
    if fallback in {"2k", "2048"}:
        return "2K"
    if fallback in {"4k", "4096"}:
        return "4K"
    return "1080p"


def _normalize_vidu_video_aspect_ratio(
    value: str | None,
    *,
    default: str = "9:16",
) -> str:
    normalized = str(value or "").strip().lower().replace("：", ":")
    if normalized in VIDU_VIDEO_ASPECT_RATIOS:
        return normalized
    fallback = str(default or "9:16").strip().lower().replace("：", ":")
    return fallback if fallback in VIDU_VIDEO_ASPECT_RATIOS else "9:16"


def _normalize_vidu_video_resolution(
    value: str | None,
    *,
    default: str = "1080p",
) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"540", "540p"}:
        return "540p"
    if normalized in {"720", "720p"}:
        return "720p"
    if normalized in {"1080", "1080p"}:
        return "1080p"
    fallback = str(default or "1080p").strip().lower()
    if fallback in {"540", "540p"}:
        return "540p"
    if fallback in {"720", "720p"}:
        return "720p"
    if fallback in {"1080", "1080p"}:
        return "1080p"
    return "1080p"


def _is_volcengine_tts_configured(
    *,
    app_key: str | None = None,
    access_key: str | None = None,
) -> bool:
    resolved_app_key, resolved_access_key = _resolve_shared_volcengine_app_credentials(
        tts_app_key=app_key,
        tts_access_key=access_key,
    )
    return bool(resolved_app_key and resolved_access_key)


def _is_kling_configured(
    *,
    access_key: str | None = None,
    secret_key: str | None = None,
) -> bool:
    return is_kling_configured(
        access_key=settings.kling_access_key if access_key is None else access_key,
        secret_key=settings.kling_secret_key if secret_key is None else secret_key,
    )


def _is_vidu_configured(*, api_key: str | None = None) -> bool:
    resolved_api_key = str((settings.vidu_api_key if api_key is None else api_key) or "").strip()
    return bool(resolved_api_key)


def _is_xiaomi_mimo_configured(*, api_key: str | None = None) -> bool:
    resolved_api_key = str(
        (settings.xiaomi_mimo_api_key if api_key is None else api_key) or ""
    ).strip()
    return bool(resolved_api_key)


def _is_minimax_configured(*, api_key: str | None = None) -> bool:
    resolved_api_key = str((settings.minimax_api_key if api_key is None else api_key) or "").strip()
    return bool(resolved_api_key)


def _find_volcengine_seedream_provider(
    image_providers: list[dict[str, object]],
) -> dict[str, object] | None:
    for provider in image_providers:
        if str(provider.get("id") or "").strip() == BUILTIN_VOLCENGINE_SEEDREAM_PROVIDER_ID:
            return provider
    return None


def _find_volcengine_llm_provider(
    llm_providers: list[dict[str, object]],
) -> dict[str, object] | None:
    for provider in llm_providers:
        if str(provider.get("id") or "").strip() == BUILTIN_VOLCENGINE_LLM_PROVIDER_ID:
            return provider
    return None


def _find_xiaomi_mimo_llm_provider(
    llm_providers: list[dict[str, object]],
) -> dict[str, object] | None:
    for provider in llm_providers:
        if str(provider.get("id") or "").strip() == BUILTIN_XIAOMI_MIMO_LLM_PROVIDER_ID:
            return provider
    return None


def _find_minimax_llm_provider(
    llm_providers: list[dict[str, object]],
) -> dict[str, object] | None:
    for provider in llm_providers:
        if str(provider.get("id") or "").strip() == BUILTIN_MINIMAX_LLM_PROVIDER_ID:
            return provider
    return None


def _sync_volcengine_llm_provider(
    llm_providers: list[dict[str, object]],
    *,
    api_key: str | None = None,
) -> list[dict[str, object]]:
    next_providers = [dict(provider) for provider in llm_providers]
    provider = _find_volcengine_llm_provider(next_providers)
    if provider is None:
        return _normalize_llm_providers(next_providers)
    if api_key is not None:
        provider["api_key"] = str(api_key or "").strip()
    return _normalize_llm_providers(next_providers)


def _sync_xiaomi_mimo_llm_provider(
    llm_providers: list[dict[str, object]],
    *,
    api_key: str | None = None,
) -> list[dict[str, object]]:
    next_providers = [dict(provider) for provider in llm_providers]
    provider = _find_xiaomi_mimo_llm_provider(next_providers)
    if provider is None:
        return _normalize_llm_providers(next_providers)
    if api_key is not None:
        provider["api_key"] = str(api_key or "").strip()
    return _normalize_llm_providers(next_providers)


def _sync_minimax_llm_provider(
    llm_providers: list[dict[str, object]],
    *,
    api_key: str | None = None,
) -> list[dict[str, object]]:
    next_providers = [dict(provider) for provider in llm_providers]
    provider = _find_minimax_llm_provider(next_providers)
    if provider is None:
        return _normalize_llm_providers(next_providers)
    if api_key is not None:
        provider["api_key"] = normalize_minimax_api_key(api_key)
    return _normalize_llm_providers(next_providers)


def _sync_volcengine_seedream_provider(
    image_providers: list[dict[str, object]],
    *,
    api_key: str | None = None,
) -> list[dict[str, object]]:
    next_providers = [dict(provider) for provider in image_providers]
    provider = _find_volcengine_seedream_provider(next_providers)
    if provider is None:
        return _normalize_image_providers(next_providers)
    if api_key is not None:
        provider["api_key"] = str(api_key or "").strip()
    return _normalize_image_providers(next_providers)


def _resolve_shared_volcengine_app_credentials(
    *,
    tts_app_key: str | None = None,
    tts_access_key: str | None = None,
    speech_app_key: str | None = None,
    speech_access_key: str | None = None,
) -> tuple[str, str]:
    resolved_tts_app_key = str(
        (settings.volcengine_tts_app_key if tts_app_key is None else tts_app_key) or ""
    ).strip()
    resolved_tts_access_key = str(
        (settings.volcengine_tts_access_key if tts_access_key is None else tts_access_key) or ""
    ).strip()
    resolved_speech_app_key = str(
        (settings.speech_volcengine_app_key if speech_app_key is None else speech_app_key) or ""
    ).strip()
    resolved_speech_access_key = str(
        (settings.speech_volcengine_access_key if speech_access_key is None else speech_access_key)
        or ""
    ).strip()
    return (
        resolved_tts_app_key or resolved_speech_app_key,
        resolved_tts_access_key or resolved_speech_access_key,
    )


def _resolve_shared_volcengine_ark_credentials(
    *,
    video_api_key: str | None = None,
    image_providers: list[dict[str, object]] | None = None,
    llm_providers: list[dict[str, object]] | None = None,
) -> tuple[str, list[dict[str, object]], list[dict[str, object]]]:
    normalized_image_providers = _normalize_image_providers(
        image_providers
        if image_providers is not None
        else (settings.image_providers or default_image_providers())
    )
    normalized_llm_providers = _normalize_llm_providers(
        llm_providers
        if llm_providers is not None
        else (settings.llm_providers or default_llm_providers())
    )
    seedream_provider = _find_volcengine_seedream_provider(normalized_image_providers)
    volcengine_llm_provider = _find_volcengine_llm_provider(normalized_llm_providers)
    provider_api_key = (
        str(seedream_provider.get("api_key") or "").strip() if seedream_provider else ""
    )
    llm_api_key = (
        str(volcengine_llm_provider.get("api_key") or "").strip() if volcengine_llm_provider else ""
    )
    resolved_video_api_key = str(
        (settings.video_seedance_api_key if video_api_key is None else video_api_key) or ""
    ).strip()
    shared_api_key = resolved_video_api_key or provider_api_key or llm_api_key
    synced_image_providers = _sync_volcengine_seedream_provider(
        normalized_image_providers,
        api_key=shared_api_key,
    )
    synced_llm_providers = _sync_volcengine_llm_provider(
        normalized_llm_providers,
        api_key=shared_api_key,
    )
    return shared_api_key, synced_image_providers, synced_llm_providers


def _resolve_shared_xiaomi_mimo_api_key(
    *,
    api_key: str | None = None,
    llm_providers: list[dict[str, object]] | None = None,
) -> tuple[str, list[dict[str, object]]]:
    normalized_llm_providers = _normalize_llm_providers(
        llm_providers
        if llm_providers is not None
        else (settings.llm_providers or default_llm_providers())
    )
    xiaomi_mimo_provider = _find_xiaomi_mimo_llm_provider(normalized_llm_providers)
    llm_api_key = (
        str(xiaomi_mimo_provider.get("api_key") or "").strip() if xiaomi_mimo_provider else ""
    )
    resolved_api_key = str(
        (settings.xiaomi_mimo_api_key if api_key is None else api_key) or ""
    ).strip()
    shared_api_key = resolved_api_key or llm_api_key
    synced_llm_providers = _sync_xiaomi_mimo_llm_provider(
        normalized_llm_providers,
        api_key=shared_api_key,
    )
    return shared_api_key, synced_llm_providers


def _resolve_shared_minimax_api_key(
    *,
    api_key: str | None = None,
    llm_providers: list[dict[str, object]] | None = None,
) -> tuple[str, list[dict[str, object]]]:
    normalized_llm_providers = _normalize_llm_providers(
        llm_providers
        if llm_providers is not None
        else (settings.llm_providers or default_llm_providers())
    )
    minimax_provider = _find_minimax_llm_provider(normalized_llm_providers)
    llm_api_key = (
        normalize_minimax_api_key(minimax_provider.get("api_key")) if minimax_provider else ""
    )
    resolved_api_key = normalize_minimax_api_key(
        settings.minimax_api_key if api_key is None else api_key
    )
    shared_api_key = resolved_api_key or llm_api_key
    synced_llm_providers = _sync_minimax_llm_provider(
        normalized_llm_providers,
        api_key=shared_api_key,
    )
    return shared_api_key, synced_llm_providers


def _sync_volcengine_settings_payload(payload: dict[str, object]) -> None:
    if "volcengine_tts_app_key" in payload and "speech_volcengine_app_key" not in payload:
        payload["speech_volcengine_app_key"] = payload["volcengine_tts_app_key"]
    elif "speech_volcengine_app_key" in payload and "volcengine_tts_app_key" not in payload:
        payload["volcengine_tts_app_key"] = payload["speech_volcengine_app_key"]

    if "volcengine_tts_access_key" in payload and "speech_volcengine_access_key" not in payload:
        payload["speech_volcengine_access_key"] = payload["volcengine_tts_access_key"]
    elif "speech_volcengine_access_key" in payload and "volcengine_tts_access_key" not in payload:
        payload["volcengine_tts_access_key"] = payload["speech_volcengine_access_key"]

    normalized_image_providers = _normalize_image_providers(
        payload.get("image_providers")
        if "image_providers" in payload
        else (settings.image_providers or default_image_providers())
    )
    normalized_llm_providers = _normalize_llm_providers(
        payload.get("llm_providers")
        if "llm_providers" in payload
        else (settings.llm_providers or default_llm_providers())
    )
    seedream_provider = _find_volcengine_seedream_provider(normalized_image_providers)
    volcengine_llm_provider = _find_volcengine_llm_provider(normalized_llm_providers)

    if "video_seedance_api_key" in payload:
        payload["video_seedance_api_key"] = str(payload.get("video_seedance_api_key") or "").strip()
    elif "image_providers" in payload:
        payload["video_seedance_api_key"] = (
            str(seedream_provider.get("api_key") or "").strip() if seedream_provider else ""
        )
    elif "llm_providers" in payload:
        payload["video_seedance_api_key"] = (
            str(volcengine_llm_provider.get("api_key") or "").strip()
            if volcengine_llm_provider
            else ""
        )

    if "video_seedance_base_url" in payload:
        payload["video_seedance_base_url"] = _normalize_seedance_base_url(
            str(payload.get("video_seedance_base_url") or "")
        )

    if (
        "image_providers" in payload
        or "video_seedance_api_key" in payload
        or "llm_providers" in payload
    ):
        payload["image_providers"] = _sync_volcengine_seedream_provider(
            normalized_image_providers,
            api_key=(
                str(payload.get("video_seedance_api_key") or "").strip()
                if "video_seedance_api_key" in payload
                else None
            ),
        )
        payload["llm_providers"] = _sync_volcengine_llm_provider(
            normalized_llm_providers,
            api_key=(
                str(payload.get("video_seedance_api_key") or "").strip()
                if "video_seedance_api_key" in payload
                else None
            ),
        )


def _sync_xiaomi_mimo_settings_payload(payload: dict[str, object]) -> None:
    normalized_llm_providers = _normalize_llm_providers(
        payload.get("llm_providers")
        if "llm_providers" in payload
        else (settings.llm_providers or default_llm_providers())
    )
    xiaomi_mimo_provider = _find_xiaomi_mimo_llm_provider(normalized_llm_providers)

    if "xiaomi_mimo_api_key" in payload:
        payload["xiaomi_mimo_api_key"] = str(payload.get("xiaomi_mimo_api_key") or "").strip()
    elif "llm_providers" in payload:
        payload["xiaomi_mimo_api_key"] = (
            str(xiaomi_mimo_provider.get("api_key") or "").strip() if xiaomi_mimo_provider else ""
        )

    if "llm_providers" in payload or "xiaomi_mimo_api_key" in payload:
        shared_api_key, synced_llm_providers = _resolve_shared_xiaomi_mimo_api_key(
            api_key=(
                str(payload.get("xiaomi_mimo_api_key") or "").strip()
                if "xiaomi_mimo_api_key" in payload
                else None
            ),
            llm_providers=normalized_llm_providers,
        )
        payload["xiaomi_mimo_api_key"] = shared_api_key
        payload["llm_providers"] = synced_llm_providers


def _sync_minimax_settings_payload(payload: dict[str, object]) -> None:
    normalized_llm_providers = _normalize_llm_providers(
        payload.get("llm_providers")
        if "llm_providers" in payload
        else (settings.llm_providers or default_llm_providers())
    )
    minimax_provider = _find_minimax_llm_provider(normalized_llm_providers)

    if "minimax_api_key" in payload:
        payload["minimax_api_key"] = normalize_minimax_api_key(payload.get("minimax_api_key"))
    elif "llm_providers" in payload:
        payload["minimax_api_key"] = (
            normalize_minimax_api_key(minimax_provider.get("api_key")) if minimax_provider else ""
        )

    if "llm_providers" in payload or "minimax_api_key" in payload:
        shared_api_key, synced_llm_providers = _resolve_shared_minimax_api_key(
            api_key=(payload.get("minimax_api_key") if "minimax_api_key" in payload else None),
            llm_providers=normalized_llm_providers,
        )
        payload["minimax_api_key"] = shared_api_key
        payload["llm_providers"] = synced_llm_providers


def _runtime_validation_requirements():
    deployment_profile = str(settings.deployment_profile or "").strip().lower()
    wan2gp_path = _normalize_optional_path(settings.wan2gp_path)
    local_model_python_path = _normalize_optional_path(settings.local_model_python_path)
    xhs_downloader_path = _normalize_optional_path(settings.xhs_downloader_path)
    tiktok_downloader_path = _normalize_optional_path(settings.tiktok_downloader_path)
    ks_downloader_path = _normalize_optional_path(settings.ks_downloader_path)
    speech_app_key, speech_access_key = _resolve_shared_volcengine_app_credentials()
    return {
        "wan2gp_ready": deployment_profile == "gpu"
        and bool(wan2gp_path and local_model_python_path),
        "xhs_downloader_ready": bool(xhs_downloader_path),
        "tiktok_downloader_ready": bool(tiktok_downloader_path),
        "ks_downloader_ready": bool(ks_downloader_path),
        "faster_whisper_ready": deployment_profile != "gpu" or bool(local_model_python_path),
        "speech_volcengine_ready": bool(
            speech_app_key
            and speech_access_key
            and str(settings.speech_volcengine_resource_id or "").strip()
        ),
        "crawl4ai_ready": True,
    }


def _build_settings_response() -> SettingsResponse:
    llm_providers = _normalize_llm_providers(settings.llm_providers or default_llm_providers())
    llm_provider_ids = [str(item.get("id") or "").strip() for item in llm_providers]
    default_llm_provider = str(settings.default_llm_provider or "").strip()
    if default_llm_provider not in llm_provider_ids:
        default_llm_provider = llm_provider_ids[0] if llm_provider_ids else "builtin_openai"
    image_providers = _normalize_image_providers(
        settings.image_providers or default_image_providers()
    )
    (
        shared_volcengine_seedance_api_key,
        image_providers,
        llm_providers,
    ) = _resolve_shared_volcengine_ark_credentials(
        image_providers=image_providers,
        llm_providers=llm_providers,
    )
    shared_xiaomi_mimo_api_key, llm_providers = _resolve_shared_xiaomi_mimo_api_key(
        llm_providers=llm_providers,
    )
    shared_minimax_api_key, llm_providers = _resolve_shared_minimax_api_key(
        llm_providers=llm_providers,
    )
    (
        shared_volcengine_app_key,
        shared_volcengine_access_key,
    ) = _resolve_shared_volcengine_app_credentials()
    image_provider_ids = [str(item.get("id") or "").strip() for item in image_providers]
    allowed_default_image_providers = list(image_provider_ids)
    if _is_wan2gp_available():
        allowed_default_image_providers.append("wan2gp")
    if _is_kling_configured():
        allowed_default_image_providers.append("kling")
    if _is_vidu_configured():
        allowed_default_image_providers.append("vidu")
    if _is_minimax_configured(api_key=shared_minimax_api_key):
        allowed_default_image_providers.append("minimax")
    default_image_provider = _normalize_image_provider_id(settings.default_image_provider)
    if default_image_provider not in allowed_default_image_providers:
        default_image_provider = (
            allowed_default_image_providers[0] if allowed_default_image_providers else ""
        )
    default_speech_recognition_provider = _normalize_speech_recognition_provider(
        settings.default_speech_recognition_provider
    )
    available_audio_providers = ["edge_tts"]
    if _is_wan2gp_available():
        available_audio_providers.append("wan2gp")
    if _is_volcengine_tts_configured():
        available_audio_providers.append("volcengine_tts")
    if _is_kling_configured():
        available_audio_providers.append("kling_tts")
    if _is_vidu_configured():
        available_audio_providers.append("vidu_tts")
    if _is_minimax_configured(api_key=shared_minimax_api_key):
        available_audio_providers.append("minimax_tts")
    if _is_xiaomi_mimo_configured(api_key=shared_xiaomi_mimo_api_key):
        available_audio_providers.append("xiaomi_mimo_tts")
    default_audio_provider = (
        str(settings.default_audio_provider or "").strip().lower() or "edge_tts"
    )
    if default_audio_provider not in available_audio_providers:
        default_audio_provider = "edge_tts"
    available_video_providers: list[str] = []
    if shared_volcengine_seedance_api_key:
        available_video_providers.append("volcengine_seedance")
    if _is_wan2gp_available():
        available_video_providers.append("wan2gp")
    default_video_provider = _normalize_video_provider_id(settings.default_video_provider)
    if default_video_provider not in available_video_providers:
        default_video_provider = (
            available_video_providers[0] if available_video_providers else "volcengine_seedance"
        )
    requirements = _runtime_validation_requirements()
    wan2gp_validation_status = _resolve_runtime_validation_status(
        settings.wan2gp_validation_status,
        ready=requirements["wan2gp_ready"],
    )
    xhs_downloader_validation_status = _resolve_runtime_validation_status(
        settings.xhs_downloader_validation_status,
        ready=requirements["xhs_downloader_ready"],
    )
    tiktok_downloader_validation_status = _resolve_runtime_validation_status(
        settings.tiktok_downloader_validation_status,
        ready=requirements["tiktok_downloader_ready"],
    )
    ks_downloader_validation_status = _resolve_runtime_validation_status(
        settings.ks_downloader_validation_status,
        ready=requirements["ks_downloader_ready"],
    )
    faster_whisper_validation_status = _resolve_runtime_validation_status(
        settings.faster_whisper_validation_status,
        ready=requirements["faster_whisper_ready"],
    )
    speech_volcengine_validation_status = _resolve_runtime_validation_status(
        settings.speech_volcengine_validation_status,
        ready=requirements["speech_volcengine_ready"],
    )
    crawl4ai_validation_status = _resolve_runtime_validation_status(
        settings.crawl4ai_validation_status,
        ready=requirements["crawl4ai_ready"],
    )
    normalized_audio_guide = ""
    try:
        normalized_audio_guide = VoiceLibraryService.normalize_audio_guide_value(
            settings.audio_wan2gp_audio_guide,
            allow_empty=True,
        )
    except ServiceError:
        normalized_audio_guide = ""

    volcengine_model_name = normalize_volcengine_tts_model_name(settings.volcengine_tts_model_name)
    resolved_volcengine_voice = str(
        settings.audio_volcengine_tts_voice_type
        or resolve_default_volcengine_tts_voice_type(volcengine_model_name)
    ).strip()
    if not is_volcengine_tts_voice_supported(volcengine_model_name, resolved_volcengine_voice):
        resolved_volcengine_voice = resolve_default_volcengine_tts_voice_type(volcengine_model_name)
    kling_t2i_model = _normalize_kling_image_model(settings.image_kling_t2i_model)
    kling_i2i_model = _normalize_kling_image_model(settings.image_kling_i2i_model)

    return SettingsResponse(
        search_tavily_api_key_set=bool(settings.search_tavily_api_key),
        search_tavily_api_key=settings.search_tavily_api_key,
        jina_reader_api_key=settings.jina_reader_api_key,
        jina_reader_ignore_images=bool(settings.jina_reader_ignore_images),
        web_url_parser_provider=(
            settings.web_url_parser_provider
            if settings.web_url_parser_provider in WEB_URL_PARSER_PROVIDERS
            else "jina_reader"
        ),
        crawl4ai_ignore_images=bool(settings.crawl4ai_ignore_images),
        crawl4ai_ignore_links=bool(settings.crawl4ai_ignore_links),
        is_containerized_runtime=_is_containerized_runtime(),
        text_openai_api_key_set=bool(settings.text_openai_api_key),
        text_openai_api_key=settings.text_openai_api_key,
        text_openai_base_url=settings.text_openai_base_url,
        text_openai_model=settings.text_openai_model,
        llm_providers=llm_providers,
        image_providers=image_providers,
        edge_tts_voice=settings.edge_tts_voice,
        edge_tts_rate=settings.edge_tts_rate,
        volcengine_tts_app_key_set=bool(shared_volcengine_app_key),
        volcengine_tts_app_key=shared_volcengine_app_key or None,
        volcengine_tts_access_key_set=bool(shared_volcengine_access_key),
        volcengine_tts_access_key=shared_volcengine_access_key or None,
        volcengine_tts_model_name=volcengine_model_name,
        volcengine_tts_resource_id=resolve_volcengine_tts_resource_id(
            settings.volcengine_tts_model_name
        ),
        audio_volcengine_tts_voice_type=resolved_volcengine_voice,
        audio_volcengine_tts_speed_ratio=float(
            max(0.5, min(2.0, settings.audio_volcengine_tts_speed_ratio or 1.0))
        ),
        audio_volcengine_tts_volume_ratio=float(
            max(0.5, min(2.0, settings.audio_volcengine_tts_volume_ratio or 1.0))
        ),
        audio_volcengine_tts_pitch_ratio=float(
            max(0.5, min(2.0, settings.audio_volcengine_tts_pitch_ratio or 1.0))
        ),
        audio_volcengine_tts_encoding=str(settings.audio_volcengine_tts_encoding or "mp3").strip()
        or "mp3",
        audio_wan2gp_preset=settings.audio_wan2gp_preset,
        audio_wan2gp_model_mode=settings.audio_wan2gp_model_mode,
        audio_wan2gp_alt_prompt=settings.audio_wan2gp_alt_prompt,
        audio_wan2gp_duration_seconds=settings.audio_wan2gp_duration_seconds,
        audio_wan2gp_temperature=settings.audio_wan2gp_temperature,
        audio_wan2gp_top_k=settings.audio_wan2gp_top_k,
        audio_wan2gp_seed=settings.audio_wan2gp_seed,
        audio_wan2gp_audio_guide=normalized_audio_guide,
        audio_wan2gp_speed=settings.audio_wan2gp_speed,
        audio_wan2gp_split_strategy=str(settings.audio_wan2gp_split_strategy or "sentence_punct"),
        kling_access_key_set=bool(settings.kling_access_key),
        kling_access_key=settings.kling_access_key,
        kling_secret_key_set=bool(settings.kling_secret_key),
        kling_secret_key=settings.kling_secret_key,
        kling_base_url=_normalize_kling_base_url(settings.kling_base_url),
        audio_kling_voice_id=str(settings.audio_kling_voice_id or "zh_male_qn_qingse").strip()
        or "zh_male_qn_qingse",
        audio_kling_voice_language=str(settings.audio_kling_voice_language or "zh").strip().lower()
        or "zh",
        audio_kling_voice_speed=float(max(0.8, min(2.0, settings.audio_kling_voice_speed or 1.0))),
        vidu_api_key_set=bool(settings.vidu_api_key),
        vidu_api_key=settings.vidu_api_key,
        vidu_base_url=_normalize_vidu_base_url(settings.vidu_base_url),
        audio_vidu_voice_id=str(settings.audio_vidu_voice_id or "female-shaonv").strip()
        or "female-shaonv",
        audio_vidu_speed=float(max(0.5, min(2.0, settings.audio_vidu_speed or 1.0))),
        audio_vidu_volume=float(max(0.0, min(10.0, settings.audio_vidu_volume or 1.0))),
        audio_vidu_pitch=float(max(-12.0, min(12.0, settings.audio_vidu_pitch or 0.0))),
        audio_vidu_emotion=str(settings.audio_vidu_emotion or "").strip(),
        minimax_api_key_set=bool(shared_minimax_api_key),
        minimax_api_key=shared_minimax_api_key or None,
        minimax_base_url=normalize_minimax_base_url(settings.minimax_base_url),
        audio_minimax_model=normalize_minimax_audio_model(settings.audio_minimax_model),
        audio_minimax_voice_id=normalize_minimax_voice_id(settings.audio_minimax_voice_id),
        audio_minimax_speed=normalize_minimax_audio_speed(settings.audio_minimax_speed, 1.0),
        xiaomi_mimo_api_key_set=bool(shared_xiaomi_mimo_api_key),
        xiaomi_mimo_api_key=shared_xiaomi_mimo_api_key or None,
        xiaomi_mimo_base_url=_normalize_openai_like_base_url(settings.xiaomi_mimo_base_url),
        audio_xiaomi_mimo_voice=normalize_xiaomi_mimo_voice(settings.audio_xiaomi_mimo_voice),
        audio_xiaomi_mimo_style_preset=normalize_xiaomi_mimo_style_preset(
            settings.audio_xiaomi_mimo_style_preset
        ),
        audio_xiaomi_mimo_speed=float(max(0.5, min(2.0, settings.audio_xiaomi_mimo_speed or 1.0))),
        audio_xiaomi_mimo_format=(
            str(settings.audio_xiaomi_mimo_format or "wav").strip().lower() or "wav"
        ),
        deployment_profile=str(settings.deployment_profile or "cpu").strip().lower() or "cpu",
        wan2gp_path=settings.wan2gp_path,
        local_model_python_path=settings.local_model_python_path,
        wan2gp_fit_canvas=(
            int(settings.wan2gp_fit_canvas)
            if str(settings.wan2gp_fit_canvas).strip() in {"0", "1", "2"}
            else 0
        ),
        xhs_downloader_path=settings.xhs_downloader_path,
        tiktok_downloader_path=settings.tiktok_downloader_path,
        ks_downloader_path=settings.ks_downloader_path,
        speech_volcengine_app_key_set=bool(shared_volcengine_app_key),
        speech_volcengine_app_key=shared_volcengine_app_key or None,
        speech_volcengine_access_key_set=bool(shared_volcengine_access_key),
        speech_volcengine_access_key=shared_volcengine_access_key or None,
        speech_volcengine_resource_id=str(
            settings.speech_volcengine_resource_id or "volc.seedasr.auc"
        ).strip()
        or "volc.seedasr.auc",
        speech_volcengine_language=(
            str(settings.speech_volcengine_language).strip()
            if settings.speech_volcengine_language is not None
            else None
        )
        or None,
        faster_whisper_model=settings.faster_whisper_model,
        dialogue_script_max_roles=normalize_dialogue_max_roles(settings.dialogue_script_max_roles),
        wan2gp_validation_status=wan2gp_validation_status,
        xhs_downloader_validation_status=xhs_downloader_validation_status,
        tiktok_downloader_validation_status=tiktok_downloader_validation_status,
        ks_downloader_validation_status=ks_downloader_validation_status,
        faster_whisper_validation_status=faster_whisper_validation_status,
        speech_volcengine_validation_status=speech_volcengine_validation_status,
        crawl4ai_validation_status=crawl4ai_validation_status,
        wan2gp_available=_is_wan2gp_available(),
        card_scheduler_max_concurrent_tasks=max(
            1, int(settings.card_scheduler_max_concurrent_tasks or 6)
        ),
        card_scheduler_url_parse_concurrency=max(
            1, int(settings.card_scheduler_url_parse_concurrency or 4)
        ),
        card_scheduler_video_download_concurrency=max(
            1, int(settings.card_scheduler_video_download_concurrency or 1)
        ),
        card_scheduler_audio_transcribe_concurrency=max(
            1, int(settings.card_scheduler_audio_transcribe_concurrency or 1)
        ),
        card_scheduler_audio_prepare_concurrency=max(
            1, int(settings.card_scheduler_audio_prepare_concurrency or 1)
        ),
        card_scheduler_audio_proofread_concurrency=max(
            1, int(settings.card_scheduler_audio_proofread_concurrency or 2)
        ),
        card_scheduler_audio_name_concurrency=max(
            1, int(settings.card_scheduler_audio_name_concurrency or 2)
        ),
        card_scheduler_text_proofread_concurrency=max(
            1, int(settings.card_scheduler_text_proofread_concurrency or 2)
        ),
        card_scheduler_text_name_concurrency=max(
            1, int(settings.card_scheduler_text_name_concurrency or 3)
        ),
        card_scheduler_reference_describe_concurrency=max(
            1, int(settings.card_scheduler_reference_describe_concurrency or 2)
        ),
        card_scheduler_reference_name_concurrency=max(
            1, int(settings.card_scheduler_reference_name_concurrency or 2)
        ),
        image_openai_api_key_set=bool(settings.image_openai_api_key),
        image_openai_api_key=settings.image_openai_api_key,
        image_openai_base_url=settings.image_openai_base_url,
        image_openai_model=settings.image_openai_model,
        image_openai_reference_aspect_ratio=settings.image_openai_reference_aspect_ratio,
        image_openai_reference_size=settings.image_openai_reference_size,
        image_openai_frame_aspect_ratio=settings.image_openai_frame_aspect_ratio,
        image_openai_frame_size=settings.image_openai_frame_size,
        image_vertex_ai_project=settings.image_vertex_ai_project,
        image_vertex_ai_location=settings.image_vertex_ai_location,
        image_vertex_ai_model=settings.image_vertex_ai_model,
        image_vertex_ai_reference_aspect_ratio=settings.image_vertex_ai_reference_aspect_ratio,
        image_vertex_ai_reference_size=settings.image_vertex_ai_reference_size,
        image_vertex_ai_frame_aspect_ratio=settings.image_vertex_ai_frame_aspect_ratio,
        image_vertex_ai_frame_size=settings.image_vertex_ai_frame_size,
        image_gemini_api_key_set=bool(settings.image_gemini_api_key),
        image_gemini_api_key=settings.image_gemini_api_key,
        image_gemini_model=settings.image_gemini_model,
        image_gemini_reference_aspect_ratio=settings.image_gemini_reference_aspect_ratio,
        image_gemini_reference_size=settings.image_gemini_reference_size,
        image_gemini_frame_aspect_ratio=settings.image_gemini_frame_aspect_ratio,
        image_gemini_frame_size=settings.image_gemini_frame_size,
        image_wan2gp_preset=settings.image_wan2gp_preset,
        image_wan2gp_preset_i2i=settings.image_wan2gp_preset_i2i,
        image_wan2gp_reference_resolution=settings.image_wan2gp_reference_resolution,
        image_wan2gp_frame_resolution=settings.image_wan2gp_frame_resolution,
        image_wan2gp_inference_steps=settings.image_wan2gp_inference_steps,
        image_wan2gp_guidance_scale=settings.image_wan2gp_guidance_scale,
        image_wan2gp_seed=settings.image_wan2gp_seed,
        image_wan2gp_negative_prompt=settings.image_wan2gp_negative_prompt,
        image_wan2gp_enabled_models=(
            _normalize_model_strings(settings.image_wan2gp_enabled_models or [])
            if settings.image_wan2gp_enabled_models is not None
            else None
        ),
        image_kling_t2i_model=kling_t2i_model,
        image_kling_i2i_model=kling_i2i_model,
        image_kling_reference_aspect_ratio=_normalize_kling_image_aspect_ratio(
            settings.image_kling_reference_aspect_ratio,
            default="1:1",
        ),
        image_kling_reference_size=_normalize_kling_image_size(
            settings.image_kling_reference_size,
            model=kling_t2i_model,
            default="1K",
        ),
        image_kling_frame_aspect_ratio=_normalize_kling_image_aspect_ratio(
            settings.image_kling_frame_aspect_ratio,
            default="9:16",
        ),
        image_kling_frame_size=_normalize_kling_image_size(
            settings.image_kling_frame_size,
            model=kling_i2i_model,
            default="1K",
        ),
        image_kling_enabled_models=(
            _normalize_model_strings(settings.image_kling_enabled_models or [])
            if settings.image_kling_enabled_models is not None
            else None
        ),
        image_vidu_t2i_model=str(settings.image_vidu_t2i_model or "viduq2").strip() or "viduq2",
        image_vidu_i2i_model=str(settings.image_vidu_i2i_model or "viduq2").strip() or "viduq2",
        image_vidu_reference_aspect_ratio=_normalize_vidu_image_aspect_ratio(
            settings.image_vidu_reference_aspect_ratio,
            default="1:1",
        ),
        image_vidu_reference_size=_normalize_vidu_image_size(
            settings.image_vidu_reference_size,
            default="1080p",
        ),
        image_vidu_frame_aspect_ratio=_normalize_vidu_image_aspect_ratio(
            settings.image_vidu_frame_aspect_ratio,
            default="9:16",
        ),
        image_vidu_frame_size=_normalize_vidu_image_size(
            settings.image_vidu_frame_size,
            default="1080p",
        ),
        image_vidu_enabled_models=(
            _normalize_model_strings(settings.image_vidu_enabled_models or [])
            if settings.image_vidu_enabled_models is not None
            else None
        ),
        image_minimax_model=normalize_minimax_image_model(settings.image_minimax_model),
        image_minimax_reference_aspect_ratio=normalize_minimax_image_aspect_ratio(
            settings.image_minimax_reference_aspect_ratio,
            model=settings.image_minimax_model,
            default="1:1",
        ),
        image_minimax_reference_size=normalize_minimax_image_size(
            settings.image_minimax_reference_size,
            default="2K",
        ),
        image_minimax_frame_aspect_ratio=normalize_minimax_image_aspect_ratio(
            settings.image_minimax_frame_aspect_ratio,
            model=settings.image_minimax_model,
            default="9:16",
        ),
        image_minimax_frame_size=normalize_minimax_image_size(
            settings.image_minimax_frame_size,
            default="2K",
        ),
        image_minimax_enabled_models=(
            _normalize_model_strings(settings.image_minimax_enabled_models or [])
            if settings.image_minimax_enabled_models is not None
            else None
        ),
        google_credentials_path=settings.google_credentials_path,
        video_seedance_api_key_set=bool(shared_volcengine_seedance_api_key),
        video_seedance_api_key=shared_volcengine_seedance_api_key or None,
        video_seedance_base_url=_normalize_seedance_base_url(settings.video_seedance_base_url),
        video_seedance_model=settings.video_seedance_model,
        video_seedance_aspect_ratio=settings.video_seedance_aspect_ratio,
        video_seedance_resolution=settings.video_seedance_resolution,
        video_seedance_watermark=bool(settings.video_seedance_watermark),
        video_seedance_enabled_models=(
            _normalize_model_strings(settings.video_seedance_enabled_models or [])
            if settings.video_seedance_enabled_models is not None
            else None
        ),
        video_wan2gp_t2v_preset=settings.video_wan2gp_t2v_preset,
        video_wan2gp_i2v_preset=settings.video_wan2gp_i2v_preset,
        video_wan2gp_resolution=settings.video_wan2gp_resolution,
        video_wan2gp_negative_prompt=settings.video_wan2gp_negative_prompt,
        video_wan2gp_enabled_models=(
            _normalize_model_strings(settings.video_wan2gp_enabled_models or [])
            if settings.video_wan2gp_enabled_models is not None
            else None
        ),
        default_llm_provider=default_llm_provider,
        default_search_provider=settings.default_search_provider,
        default_audio_provider=default_audio_provider,
        default_speech_recognition_provider=default_speech_recognition_provider,
        default_image_provider=default_image_provider,
        default_video_provider=default_video_provider,
        default_speech_recognition_model=_normalize_speech_model_binding(
            settings.default_speech_recognition_model
        ),
        default_general_llm_model=str(settings.default_general_llm_model or "").strip(),
        default_fast_llm_model=str(settings.default_fast_llm_model or "").strip(),
        default_multimodal_llm_model=str(settings.default_multimodal_llm_model or "").strip(),
        default_image_t2i_model=str(settings.default_image_t2i_model or "").strip(),
        default_image_i2i_model=str(settings.default_image_i2i_model or "").strip(),
        default_video_t2v_model=str(settings.default_video_t2v_model or "").strip(),
        default_video_i2v_model=str(settings.default_video_i2v_model or "").strip(),
    )


@router.get("/", response_model=SettingsResponse)
async def get_settings():
    return _build_settings_response()


@router.patch("/", response_model=SettingsResponse)
async def update_settings(update: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    payload = update.model_dump(exclude_unset=True)
    _drop_containerized_locked_path_updates(payload)
    if "jina_reader_api_key" in payload:
        payload["jina_reader_api_key"] = (
            str(payload.get("jina_reader_api_key") or "").strip() or None
        )
    if "jina_reader_ignore_images" in payload:
        payload["jina_reader_ignore_images"] = bool(payload.get("jina_reader_ignore_images"))
    if "web_url_parser_provider" in payload:
        provider = str(payload.get("web_url_parser_provider") or "").strip().lower()
        if provider not in WEB_URL_PARSER_PROVIDERS:
            raise HTTPException(
                status_code=400,
                detail=(
                    "web_url_parser_provider 无效。"
                    f"可选值: {', '.join(sorted(WEB_URL_PARSER_PROVIDERS))}"
                ),
            )
        payload["web_url_parser_provider"] = provider
    if "crawl4ai_ignore_images" in payload:
        payload["crawl4ai_ignore_images"] = bool(payload.get("crawl4ai_ignore_images"))
    if "crawl4ai_ignore_links" in payload:
        payload["crawl4ai_ignore_links"] = bool(payload.get("crawl4ai_ignore_links"))
    previous_deployment_profile = str(settings.deployment_profile or "cpu").strip().lower() or "cpu"
    previous_wan2gp_path = _normalize_optional_path(settings.wan2gp_path)
    previous_local_model_python_path = _normalize_optional_path(settings.local_model_python_path)
    previous_xhs_downloader_path = _normalize_optional_path(settings.xhs_downloader_path)
    previous_tiktok_downloader_path = _normalize_optional_path(settings.tiktok_downloader_path)
    previous_ks_downloader_path = _normalize_optional_path(settings.ks_downloader_path)
    previous_speech_volcengine_app_key = str(settings.speech_volcengine_app_key or "").strip()
    previous_speech_volcengine_access_key = str(settings.speech_volcengine_access_key or "").strip()
    previous_speech_volcengine_resource_id = str(
        settings.speech_volcengine_resource_id or ""
    ).strip()
    previous_volcengine_tts_app_key = str(settings.volcengine_tts_app_key or "").strip()
    previous_volcengine_tts_access_key = str(settings.volcengine_tts_access_key or "").strip()
    previous_kling_access_key = str(settings.kling_access_key or "").strip()
    previous_kling_secret_key = str(settings.kling_secret_key or "").strip()
    previous_vidu_api_key = str(settings.vidu_api_key or "").strip()
    previous_minimax_api_key = str(settings.minimax_api_key or "").strip()
    previous_xiaomi_mimo_api_key = str(settings.xiaomi_mimo_api_key or "").strip()

    if "llm_providers" in payload:
        payload["llm_providers"] = _normalize_llm_providers(payload.get("llm_providers") or [])
        allowed_provider_ids = [
            str(item.get("id") or "").strip() for item in payload["llm_providers"]
        ]
        current_default = str(
            payload.get("default_llm_provider") or settings.default_llm_provider or ""
        ).strip()
        if current_default not in allowed_provider_ids:
            payload["default_llm_provider"] = (
                allowed_provider_ids[0] if allowed_provider_ids else "builtin_openai"
            )

    if "default_llm_provider" in payload:
        default_provider = str(payload.get("default_llm_provider") or "").strip()
        provider_pool = payload.get("llm_providers") or settings.llm_providers or []
        allowed_provider_ids = {
            str(item.get("id") or "").strip() for item in provider_pool if isinstance(item, dict)
        }
        if default_provider and default_provider not in allowed_provider_ids:
            raise HTTPException(
                status_code=400,
                detail=f"default_llm_provider 无效: {default_provider}",
            )

    if "image_providers" in payload:
        payload["image_providers"] = _normalize_image_providers(
            payload.get("image_providers") or []
        )
        allowed_provider_ids = [
            str(item.get("id") or "").strip() for item in payload["image_providers"]
        ]
        if _is_wan2gp_available():
            allowed_provider_ids.append("wan2gp")
        if _is_kling_configured(
            access_key=(
                payload.get("kling_access_key")
                if "kling_access_key" in payload
                else settings.kling_access_key
            ),
            secret_key=(
                payload.get("kling_secret_key")
                if "kling_secret_key" in payload
                else settings.kling_secret_key
            ),
        ):
            allowed_provider_ids.append("kling")
        if _is_vidu_configured(
            api_key=(
                payload.get("vidu_api_key") if "vidu_api_key" in payload else settings.vidu_api_key
            ),
        ):
            allowed_provider_ids.append("vidu")
        shared_minimax_api_key, _ = _resolve_shared_minimax_api_key(
            api_key=(payload.get("minimax_api_key") if "minimax_api_key" in payload else None),
            llm_providers=(
                payload.get("llm_providers")
                if "llm_providers" in payload
                else (settings.llm_providers or default_llm_providers())
            ),
        )
        if _is_minimax_configured(api_key=shared_minimax_api_key):
            allowed_provider_ids.append("minimax")
        current_default = _normalize_image_provider_id(
            payload.get("default_image_provider") or settings.default_image_provider or ""
        )
        if current_default not in allowed_provider_ids:
            payload["default_image_provider"] = (
                allowed_provider_ids[0] if allowed_provider_ids else ""
            )

    if "default_image_provider" in payload:
        default_provider = _normalize_image_provider_id(payload.get("default_image_provider"))
        provider_pool = payload.get("image_providers") or settings.image_providers or []
        normalized_provider_pool = _normalize_image_providers(provider_pool)
        allowed_provider_ids = {
            _normalize_image_provider_id(item.get("id"))
            for item in normalized_provider_pool
            if isinstance(item, dict)
        }
        if _is_wan2gp_available():
            allowed_provider_ids.add("wan2gp")
        if _is_kling_configured(
            access_key=(
                payload.get("kling_access_key")
                if "kling_access_key" in payload
                else settings.kling_access_key
            ),
            secret_key=(
                payload.get("kling_secret_key")
                if "kling_secret_key" in payload
                else settings.kling_secret_key
            ),
        ):
            allowed_provider_ids.add("kling")
        if _is_vidu_configured(
            api_key=(
                payload.get("vidu_api_key") if "vidu_api_key" in payload else settings.vidu_api_key
            ),
        ):
            allowed_provider_ids.add("vidu")
        shared_minimax_api_key, _ = _resolve_shared_minimax_api_key(
            api_key=(payload.get("minimax_api_key") if "minimax_api_key" in payload else None),
            llm_providers=(
                payload.get("llm_providers")
                if "llm_providers" in payload
                else (settings.llm_providers or default_llm_providers())
            ),
        )
        if _is_minimax_configured(api_key=shared_minimax_api_key):
            allowed_provider_ids.add("minimax")
        if default_provider and default_provider not in allowed_provider_ids:
            raise HTTPException(
                status_code=400,
                detail=f"default_image_provider 无效: {default_provider}",
            )
        payload["default_image_provider"] = default_provider

    if "deployment_profile" in payload:
        payload["deployment_profile"] = (
            str(payload.get("deployment_profile") or "cpu").strip().lower()
        )
        if payload["deployment_profile"] not in {"cpu", "gpu"}:
            payload["deployment_profile"] = "cpu"
    if "wan2gp_path" in payload:
        payload["wan2gp_path"] = _normalize_optional_path(payload.get("wan2gp_path"))
    if "local_model_python_path" in payload:
        payload["local_model_python_path"] = _normalize_optional_path(
            payload.get("local_model_python_path")
        )
    if "wan2gp_fit_canvas" in payload:
        try:
            fit_canvas = int(payload.get("wan2gp_fit_canvas"))
        except (TypeError, ValueError):
            fit_canvas = 0
        payload["wan2gp_fit_canvas"] = fit_canvas if fit_canvas in (0, 1, 2) else 0
    if "xhs_downloader_path" in payload:
        payload["xhs_downloader_path"] = _normalize_optional_path(
            payload.get("xhs_downloader_path")
        )
    if "tiktok_downloader_path" in payload:
        payload["tiktok_downloader_path"] = _normalize_optional_path(
            payload.get("tiktok_downloader_path")
        )
    if "ks_downloader_path" in payload:
        payload["ks_downloader_path"] = _normalize_optional_path(payload.get("ks_downloader_path"))
    if "volcengine_tts_app_key" in payload:
        payload["volcengine_tts_app_key"] = str(payload.get("volcengine_tts_app_key") or "").strip()
    if "volcengine_tts_access_key" in payload:
        payload["volcengine_tts_access_key"] = str(
            payload.get("volcengine_tts_access_key") or ""
        ).strip()
    if "volcengine_tts_model_name" in payload:
        normalized_tts_model_name = normalize_volcengine_tts_model_name(
            payload.get("volcengine_tts_model_name")
        )
        payload["volcengine_tts_model_name"] = normalized_tts_model_name
        payload["volcengine_tts_resource_id"] = resolve_volcengine_tts_resource_id(
            normalized_tts_model_name
        )
        if "audio_volcengine_tts_voice_type" not in payload:
            current_voice = str(
                settings.audio_volcengine_tts_voice_type
                or resolve_default_volcengine_tts_voice_type(settings.volcengine_tts_model_name)
            ).strip()
            if is_volcengine_tts_voice_supported(normalized_tts_model_name, current_voice):
                payload["audio_volcengine_tts_voice_type"] = current_voice
            else:
                payload["audio_volcengine_tts_voice_type"] = (
                    resolve_default_volcengine_tts_voice_type(normalized_tts_model_name)
                )
    elif "volcengine_tts_resource_id" in payload:
        payload["volcengine_tts_resource_id"] = resolve_volcengine_tts_resource_id(
            payload.get("volcengine_tts_model_name")
            or settings.volcengine_tts_model_name
            or VOLCENGINE_TTS_DEFAULT_MODEL_NAME
        )
    if "audio_volcengine_tts_voice_type" in payload:
        target_model = normalize_volcengine_tts_model_name(
            payload.get("volcengine_tts_model_name")
            or settings.volcengine_tts_model_name
            or VOLCENGINE_TTS_DEFAULT_MODEL_NAME
        )
        fallback_voice = resolve_default_volcengine_tts_voice_type(target_model)
        normalized_voice = (
            str(payload.get("audio_volcengine_tts_voice_type") or fallback_voice).strip()
            or fallback_voice
        )
        if not is_volcengine_tts_voice_supported(target_model, normalized_voice):
            raise HTTPException(
                status_code=400,
                detail=(f"音色不属于当前模型({target_model}): {normalized_voice}。"),
            )
        payload["audio_volcengine_tts_voice_type"] = normalized_voice
    for key in (
        "audio_volcengine_tts_speed_ratio",
        "audio_volcengine_tts_volume_ratio",
        "audio_volcengine_tts_pitch_ratio",
    ):
        if key in payload:
            payload[key] = max(0.5, min(2.0, _coerce_float(payload.get(key), 1.0)))
    if "audio_volcengine_tts_encoding" in payload:
        encoding = str(payload.get("audio_volcengine_tts_encoding") or "mp3").strip().lower()
        payload["audio_volcengine_tts_encoding"] = (
            encoding if encoding in {"mp3", "wav", "pcm", "ogg_opus"} else "mp3"
        )
    if "speech_volcengine_app_key" in payload:
        payload["speech_volcengine_app_key"] = str(
            payload.get("speech_volcengine_app_key") or ""
        ).strip()
    if "speech_volcengine_access_key" in payload:
        payload["speech_volcengine_access_key"] = str(
            payload.get("speech_volcengine_access_key") or ""
        ).strip()
    if "speech_volcengine_resource_id" in payload:
        payload["speech_volcengine_resource_id"] = (
            str(payload.get("speech_volcengine_resource_id") or "volc.seedasr.auc").strip()
            or "volc.seedasr.auc"
        )
    if "speech_volcengine_language" in payload:
        payload["speech_volcengine_language"] = (
            str(payload.get("speech_volcengine_language") or "").strip() or None
        )
    if "xiaomi_mimo_api_key" in payload:
        payload["xiaomi_mimo_api_key"] = str(payload.get("xiaomi_mimo_api_key") or "").strip()
    if "minimax_api_key" in payload:
        payload["minimax_api_key"] = normalize_minimax_api_key(payload.get("minimax_api_key"))
    if "minimax_base_url" in payload:
        payload["minimax_base_url"] = _normalize_minimax_base_url(
            str(payload.get("minimax_base_url") or "")
        )
    if "audio_minimax_model" in payload:
        payload["audio_minimax_model"] = normalize_minimax_audio_model(
            payload.get("audio_minimax_model")
        )
    if "audio_minimax_voice_id" in payload:
        payload["audio_minimax_voice_id"] = normalize_minimax_voice_id(
            payload.get("audio_minimax_voice_id")
        )
    if "audio_minimax_speed" in payload:
        payload["audio_minimax_speed"] = normalize_minimax_audio_speed(
            payload.get("audio_minimax_speed"),
            1.0,
        )
    if "xiaomi_mimo_base_url" in payload:
        payload["xiaomi_mimo_base_url"] = _normalize_openai_like_base_url(
            str(payload.get("xiaomi_mimo_base_url") or "").strip()
            or settings.xiaomi_mimo_base_url
            or "https://api.xiaomimimo.com/v1"
        )
    if "audio_xiaomi_mimo_voice" in payload:
        payload["audio_xiaomi_mimo_voice"] = normalize_xiaomi_mimo_voice(
            payload.get("audio_xiaomi_mimo_voice")
        )
    if "audio_xiaomi_mimo_style_preset" in payload:
        payload["audio_xiaomi_mimo_style_preset"] = normalize_xiaomi_mimo_style_preset(
            payload.get("audio_xiaomi_mimo_style_preset")
        )
    if "audio_xiaomi_mimo_speed" in payload:
        payload["audio_xiaomi_mimo_speed"] = max(
            0.5,
            min(2.0, _coerce_float(payload.get("audio_xiaomi_mimo_speed"), 1.0)),
        )
    if "audio_xiaomi_mimo_format" in payload:
        normalized_format = str(payload.get("audio_xiaomi_mimo_format") or "wav").strip().lower()
        payload["audio_xiaomi_mimo_format"] = (
            normalized_format if normalized_format in {"wav", "mp3"} else "wav"
        )
    if "faster_whisper_model" in payload:
        model = str(payload.get("faster_whisper_model") or "large-v3").strip().lower()
        if model not in FASTER_WHISPER_MODELS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"faster_whisper_model 无效。可选值: {', '.join(sorted(FASTER_WHISPER_MODELS))}"
                ),
            )
        payload["faster_whisper_model"] = model
    if "default_speech_recognition_provider" in payload:
        payload["default_speech_recognition_provider"] = _normalize_speech_recognition_provider(
            payload.get("default_speech_recognition_provider")
        )
    if "default_speech_recognition_model" in payload:
        payload["default_speech_recognition_model"] = _normalize_speech_model_binding(
            payload.get("default_speech_recognition_model")
        )
    if "dialogue_script_max_roles" in payload:
        payload["dialogue_script_max_roles"] = normalize_dialogue_max_roles(
            payload.get("dialogue_script_max_roles")
        )
    for key, default in (
        ("card_scheduler_max_concurrent_tasks", 6),
        ("card_scheduler_url_parse_concurrency", 4),
        ("card_scheduler_video_download_concurrency", 1),
        ("card_scheduler_audio_transcribe_concurrency", 1),
        ("card_scheduler_audio_prepare_concurrency", 1),
        ("card_scheduler_audio_proofread_concurrency", 2),
        ("card_scheduler_audio_name_concurrency", 2),
        ("card_scheduler_text_proofread_concurrency", 2),
        ("card_scheduler_text_name_concurrency", 3),
        ("card_scheduler_reference_describe_concurrency", 2),
        ("card_scheduler_reference_name_concurrency", 2),
    ):
        if key in payload:
            try:
                value = int(payload.get(key) or default)
            except (TypeError, ValueError):
                value = default
            payload[key] = max(1, min(32, value))
    if "audio_wan2gp_audio_guide" in payload:
        raw_audio_guide = str(payload.get("audio_wan2gp_audio_guide") or "").strip()
        try:
            payload["audio_wan2gp_audio_guide"] = VoiceLibraryService.normalize_audio_guide_value(
                raw_audio_guide,
                allow_empty=True,
            )
        except ServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc) or "语音文件路径不合法") from exc
    if "audio_wan2gp_split_strategy" in payload:
        raw_split_strategy = str(payload.get("audio_wan2gp_split_strategy") or "").strip().lower()
        if raw_split_strategy == "sentence_punct":
            payload["audio_wan2gp_split_strategy"] = "sentence_punct"
        elif raw_split_strategy == "anchor_tail":
            payload["audio_wan2gp_split_strategy"] = "anchor_tail"
        else:
            raise HTTPException(
                status_code=400,
                detail="audio_wan2gp_split_strategy 无效，可选值: sentence_punct, anchor_tail",
            )
    if "kling_access_key" in payload:
        payload["kling_access_key"] = _normalize_kling_access_key(payload.get("kling_access_key"))
    if "kling_secret_key" in payload:
        payload["kling_secret_key"] = _normalize_kling_secret_key(payload.get("kling_secret_key"))
    if "kling_base_url" in payload:
        payload["kling_base_url"] = _normalize_kling_base_url(
            str(payload.get("kling_base_url") or "")
        )
    if "audio_kling_voice_id" in payload:
        payload["audio_kling_voice_id"] = (
            str(payload.get("audio_kling_voice_id") or "zh_male_qn_qingse").strip()
            or "zh_male_qn_qingse"
        )
    if "audio_kling_voice_language" in payload:
        payload["audio_kling_voice_language"] = (
            str(payload.get("audio_kling_voice_language") or "zh").strip().lower() or "zh"
        )
    if "audio_kling_voice_speed" in payload:
        payload["audio_kling_voice_speed"] = max(
            0.8,
            min(2.0, _coerce_float(payload.get("audio_kling_voice_speed"), 1.0)),
        )
    if "vidu_api_key" in payload:
        payload["vidu_api_key"] = _normalize_vidu_api_key(payload.get("vidu_api_key"))
    if "vidu_base_url" in payload:
        payload["vidu_base_url"] = _normalize_vidu_base_url(str(payload.get("vidu_base_url") or ""))
    if "audio_vidu_voice_id" in payload:
        payload["audio_vidu_voice_id"] = (
            str(payload.get("audio_vidu_voice_id") or "female-shaonv").strip() or "female-shaonv"
        )
    if "audio_vidu_speed" in payload:
        payload["audio_vidu_speed"] = max(
            0.5,
            min(2.0, _coerce_float(payload.get("audio_vidu_speed"), 1.0)),
        )
    if "audio_vidu_volume" in payload:
        payload["audio_vidu_volume"] = max(
            0.0,
            min(10.0, _coerce_float(payload.get("audio_vidu_volume"), 1.0)),
        )
    if "audio_vidu_pitch" in payload:
        payload["audio_vidu_pitch"] = max(
            -12.0,
            min(12.0, _coerce_float(payload.get("audio_vidu_pitch"), 0.0)),
        )
    if "audio_vidu_emotion" in payload:
        payload["audio_vidu_emotion"] = str(payload.get("audio_vidu_emotion") or "").strip()
    if "image_kling_t2i_model" in payload:
        payload["image_kling_t2i_model"] = _normalize_kling_image_model(
            payload.get("image_kling_t2i_model")
        )
    if "image_kling_i2i_model" in payload:
        payload["image_kling_i2i_model"] = _normalize_kling_image_model(
            payload.get("image_kling_i2i_model")
        )
    kling_t2i_model = str(
        payload.get("image_kling_t2i_model") or settings.image_kling_t2i_model or "kling-v3"
    )
    kling_i2i_model = str(
        payload.get("image_kling_i2i_model") or settings.image_kling_i2i_model or "kling-v3"
    )
    if "image_kling_reference_aspect_ratio" in payload:
        payload["image_kling_reference_aspect_ratio"] = _normalize_kling_image_aspect_ratio(
            payload.get("image_kling_reference_aspect_ratio"),
            default="1:1",
        )
    if "image_kling_reference_size" in payload:
        payload["image_kling_reference_size"] = _normalize_kling_image_size(
            payload.get("image_kling_reference_size"),
            model=kling_t2i_model,
            default="1K",
        )
    if "image_kling_frame_aspect_ratio" in payload:
        payload["image_kling_frame_aspect_ratio"] = _normalize_kling_image_aspect_ratio(
            payload.get("image_kling_frame_aspect_ratio"),
            default="9:16",
        )
    if "image_kling_frame_size" in payload:
        payload["image_kling_frame_size"] = _normalize_kling_image_size(
            payload.get("image_kling_frame_size"),
            model=kling_i2i_model,
            default="1K",
        )
    if "image_vidu_t2i_model" in payload:
        payload["image_vidu_t2i_model"] = (
            str(payload.get("image_vidu_t2i_model") or "viduq2").strip() or "viduq2"
        )
    if "image_vidu_i2i_model" in payload:
        payload["image_vidu_i2i_model"] = (
            str(payload.get("image_vidu_i2i_model") or "viduq2").strip() or "viduq2"
        )
    if "image_vidu_reference_aspect_ratio" in payload:
        payload["image_vidu_reference_aspect_ratio"] = _normalize_vidu_image_aspect_ratio(
            payload.get("image_vidu_reference_aspect_ratio"),
            default="1:1",
        )
    if "image_vidu_reference_size" in payload:
        payload["image_vidu_reference_size"] = _normalize_vidu_image_size(
            payload.get("image_vidu_reference_size"),
            default="1080p",
        )
    if "image_vidu_frame_aspect_ratio" in payload:
        payload["image_vidu_frame_aspect_ratio"] = _normalize_vidu_image_aspect_ratio(
            payload.get("image_vidu_frame_aspect_ratio"),
            default="9:16",
        )
    if "image_vidu_frame_size" in payload:
        payload["image_vidu_frame_size"] = _normalize_vidu_image_size(
            payload.get("image_vidu_frame_size"),
            default="1080p",
        )
    if "image_kling_enabled_models" in payload:
        raw_enabled = payload.get("image_kling_enabled_models")
        payload["image_kling_enabled_models"] = (
            _normalize_model_strings(raw_enabled or []) if raw_enabled is not None else None
        )
    if "image_vidu_enabled_models" in payload:
        raw_enabled = payload.get("image_vidu_enabled_models")
        payload["image_vidu_enabled_models"] = (
            _normalize_model_strings(raw_enabled or []) if raw_enabled is not None else None
        )
    if "image_minimax_model" in payload:
        payload["image_minimax_model"] = normalize_minimax_image_model(
            payload.get("image_minimax_model")
        )
    minimax_image_model = str(
        payload.get("image_minimax_model") or settings.image_minimax_model or "image-01"
    )
    if "image_minimax_reference_aspect_ratio" in payload:
        payload["image_minimax_reference_aspect_ratio"] = normalize_minimax_image_aspect_ratio(
            payload.get("image_minimax_reference_aspect_ratio"),
            model=minimax_image_model,
            default="1:1",
        )
    if "image_minimax_reference_size" in payload:
        payload["image_minimax_reference_size"] = normalize_minimax_image_size(
            payload.get("image_minimax_reference_size"),
            default="2K",
        )
    if "image_minimax_frame_aspect_ratio" in payload:
        payload["image_minimax_frame_aspect_ratio"] = normalize_minimax_image_aspect_ratio(
            payload.get("image_minimax_frame_aspect_ratio"),
            model=minimax_image_model,
            default="9:16",
        )
    if "image_minimax_frame_size" in payload:
        payload["image_minimax_frame_size"] = normalize_minimax_image_size(
            payload.get("image_minimax_frame_size"),
            default="2K",
        )
    if "image_minimax_enabled_models" in payload:
        raw_enabled = payload.get("image_minimax_enabled_models")
        payload["image_minimax_enabled_models"] = (
            _normalize_model_strings(raw_enabled or []) if raw_enabled is not None else None
        )
    if "image_wan2gp_enabled_models" in payload:
        raw_enabled = payload.get("image_wan2gp_enabled_models")
        payload["image_wan2gp_enabled_models"] = (
            _normalize_model_strings(raw_enabled or []) if raw_enabled is not None else None
        )
    if "video_seedance_api_key" in payload:
        payload["video_seedance_api_key"] = str(payload.get("video_seedance_api_key") or "").strip()
    if "video_seedance_base_url" in payload:
        payload["video_seedance_base_url"] = _normalize_seedance_base_url(
            str(payload.get("video_seedance_base_url") or "")
        )
    if "video_seedance_model" in payload:
        payload["video_seedance_model"] = str(payload.get("video_seedance_model") or "").strip()
    if "video_seedance_aspect_ratio" in payload:
        payload["video_seedance_aspect_ratio"] = str(
            payload.get("video_seedance_aspect_ratio") or ""
        ).strip()
    if "video_seedance_resolution" in payload:
        payload["video_seedance_resolution"] = str(
            payload.get("video_seedance_resolution") or ""
        ).strip()
    if "video_seedance_watermark" in payload:
        payload["video_seedance_watermark"] = bool(payload.get("video_seedance_watermark"))
    if "video_seedance_enabled_models" in payload:
        raw_enabled = payload.get("video_seedance_enabled_models")
        payload["video_seedance_enabled_models"] = (
            _normalize_model_strings(raw_enabled or []) if raw_enabled is not None else None
        )
    _sync_volcengine_settings_payload(payload)
    _sync_xiaomi_mimo_settings_payload(payload)
    _sync_minimax_settings_payload(payload)
    if "video_wan2gp_enabled_models" in payload:
        raw_enabled = payload.get("video_wan2gp_enabled_models")
        payload["video_wan2gp_enabled_models"] = (
            _normalize_model_strings(raw_enabled or []) if raw_enabled is not None else None
        )
    if "default_audio_provider" in payload:
        payload["default_audio_provider"] = (
            str(payload.get("default_audio_provider") or "").strip().lower()
        )
    if "default_video_provider" in payload:
        payload["default_video_provider"] = _normalize_video_provider_id(
            payload.get("default_video_provider")
        )
    if "default_general_llm_model" in payload:
        payload["default_general_llm_model"] = str(
            payload.get("default_general_llm_model") or ""
        ).strip()
    if "default_fast_llm_model" in payload:
        payload["default_fast_llm_model"] = str(payload.get("default_fast_llm_model") or "").strip()
    if "default_multimodal_llm_model" in payload:
        payload["default_multimodal_llm_model"] = str(
            payload.get("default_multimodal_llm_model") or ""
        ).strip()
    if "default_image_t2i_model" in payload:
        payload["default_image_t2i_model"] = str(
            payload.get("default_image_t2i_model") or ""
        ).strip()
    if "default_image_i2i_model" in payload:
        payload["default_image_i2i_model"] = str(
            payload.get("default_image_i2i_model") or ""
        ).strip()
    if "default_video_t2v_model" in payload:
        payload["default_video_t2v_model"] = str(
            payload.get("default_video_t2v_model") or ""
        ).strip()
    if "default_video_i2v_model" in payload:
        payload["default_video_i2v_model"] = str(
            payload.get("default_video_i2v_model") or ""
        ).strip()

    next_deployment_profile = (
        payload["deployment_profile"]
        if "deployment_profile" in payload
        else previous_deployment_profile
    )
    next_wan2gp_path = payload["wan2gp_path"] if "wan2gp_path" in payload else previous_wan2gp_path
    next_local_model_python_path = (
        payload["local_model_python_path"]
        if "local_model_python_path" in payload
        else previous_local_model_python_path
    )
    next_xhs_downloader_path = (
        payload["xhs_downloader_path"]
        if "xhs_downloader_path" in payload
        else previous_xhs_downloader_path
    )
    next_tiktok_downloader_path = (
        payload["tiktok_downloader_path"]
        if "tiktok_downloader_path" in payload
        else previous_tiktok_downloader_path
    )
    next_ks_downloader_path = (
        payload["ks_downloader_path"]
        if "ks_downloader_path" in payload
        else previous_ks_downloader_path
    )
    next_speech_volcengine_app_key = (
        str(payload["speech_volcengine_app_key"]).strip()
        if "speech_volcengine_app_key" in payload
        else previous_speech_volcengine_app_key
    )
    next_speech_volcengine_access_key = (
        str(payload["speech_volcengine_access_key"]).strip()
        if "speech_volcengine_access_key" in payload
        else previous_speech_volcengine_access_key
    )
    next_speech_volcengine_resource_id = (
        str(payload["speech_volcengine_resource_id"]).strip()
        if "speech_volcengine_resource_id" in payload
        else previous_speech_volcengine_resource_id
    )
    next_volcengine_tts_app_key = (
        str(payload["volcengine_tts_app_key"]).strip()
        if "volcengine_tts_app_key" in payload
        else previous_volcengine_tts_app_key
    )
    next_volcengine_tts_access_key = (
        str(payload["volcengine_tts_access_key"]).strip()
        if "volcengine_tts_access_key" in payload
        else previous_volcengine_tts_access_key
    )
    (
        next_shared_volcengine_app_key,
        next_shared_volcengine_access_key,
    ) = _resolve_shared_volcengine_app_credentials(
        tts_app_key=next_volcengine_tts_app_key,
        tts_access_key=next_volcengine_tts_access_key,
        speech_app_key=next_speech_volcengine_app_key,
        speech_access_key=next_speech_volcengine_access_key,
    )
    next_speech_volcengine_app_key = next_shared_volcengine_app_key
    next_speech_volcengine_access_key = next_shared_volcengine_access_key
    next_volcengine_tts_app_key = next_shared_volcengine_app_key
    next_volcengine_tts_access_key = next_shared_volcengine_access_key
    next_kling_access_key = (
        _normalize_kling_access_key(payload["kling_access_key"])
        if "kling_access_key" in payload
        else previous_kling_access_key
    )
    next_kling_secret_key = (
        _normalize_kling_secret_key(payload["kling_secret_key"])
        if "kling_secret_key" in payload
        else previous_kling_secret_key
    )
    next_vidu_api_key = (
        _normalize_vidu_api_key(payload["vidu_api_key"])
        if "vidu_api_key" in payload
        else previous_vidu_api_key
    )
    next_minimax_api_key = (
        normalize_minimax_api_key(payload["minimax_api_key"])
        if "minimax_api_key" in payload
        else previous_minimax_api_key
    )
    next_minimax_api_key, _ = _resolve_shared_minimax_api_key(
        api_key=next_minimax_api_key,
        llm_providers=(
            payload.get("llm_providers")
            if "llm_providers" in payload
            else (settings.llm_providers or default_llm_providers())
        ),
    )
    next_xiaomi_mimo_api_key = (
        str(payload["xiaomi_mimo_api_key"]).strip()
        if "xiaomi_mimo_api_key" in payload
        else previous_xiaomi_mimo_api_key
    )
    next_default_audio_provider = (
        str(
            payload.get("default_audio_provider")
            if "default_audio_provider" in payload
            else settings.default_audio_provider
        ).strip()
        or "edge_tts"
    )
    if next_default_audio_provider not in {
        "edge_tts",
        "wan2gp",
        "volcengine_tts",
        "kling_tts",
        "vidu_tts",
        "minimax_tts",
        "xiaomi_mimo_tts",
    }:
        raise HTTPException(
            status_code=400, detail=f"default_audio_provider 无效: {next_default_audio_provider}"
        )
    if next_default_audio_provider == "volcengine_tts" and not _is_volcengine_tts_configured(
        app_key=next_volcengine_tts_app_key,
        access_key=next_volcengine_tts_access_key,
    ):
        raise HTTPException(
            status_code=400,
            detail="default_audio_provider 设为 volcengine_tts 前，请先配置火山 TTS 的 APP ID 和 Access Token。",
        )
    if next_default_audio_provider == "kling_tts" and not _is_kling_configured(
        access_key=next_kling_access_key,
        secret_key=next_kling_secret_key,
    ):
        raise HTTPException(
            status_code=400,
            detail="default_audio_provider 设为 kling_tts 前，请先配置可灵 Access Key 和 Secret Key。",
        )
    if next_default_audio_provider == "vidu_tts" and not _is_vidu_configured(
        api_key=next_vidu_api_key,
    ):
        raise HTTPException(
            status_code=400,
            detail="default_audio_provider 设为 vidu_tts 前，请先配置 Vidu API Key。",
        )
    if next_default_audio_provider == "minimax_tts" and not _is_minimax_configured(
        api_key=next_minimax_api_key,
    ):
        raise HTTPException(
            status_code=400,
            detail="default_audio_provider 设为 minimax_tts 前，请先配置 MiniMax API Key。",
        )
    shared_xiaomi_mimo_api_key, _ = _resolve_shared_xiaomi_mimo_api_key(
        api_key=next_xiaomi_mimo_api_key,
        llm_providers=(
            payload.get("llm_providers")
            if "llm_providers" in payload
            else (settings.llm_providers or default_llm_providers())
        ),
    )
    if next_default_audio_provider == "xiaomi_mimo_tts" and not _is_xiaomi_mimo_configured(
        api_key=shared_xiaomi_mimo_api_key,
    ):
        raise HTTPException(
            status_code=400,
            detail="default_audio_provider 设为 xiaomi_mimo_tts 前，请先配置小米 MiMo API Key。",
        )
    next_default_video_provider = (
        str(
            payload.get("default_video_provider")
            if "default_video_provider" in payload
            else settings.default_video_provider
        )
        .strip()
        .lower()
    )
    if next_default_video_provider:
        if next_default_video_provider not in {"volcengine_seedance", "wan2gp"}:
            raise HTTPException(
                status_code=400,
                detail=f"default_video_provider 无效: {next_default_video_provider}",
            )
        if next_default_video_provider == "wan2gp" and not _is_wan2gp_available():
            raise HTTPException(
                status_code=400,
                detail="default_video_provider 设为 wan2gp 前，请先配置本地 Wan2GP 并完成校验。",
            )

    deployment_profile_changed = (
        "deployment_profile" in payload and next_deployment_profile != previous_deployment_profile
    )
    wan2gp_path_changed = "wan2gp_path" in payload and next_wan2gp_path != previous_wan2gp_path
    local_model_python_path_changed = (
        "local_model_python_path" in payload
        and next_local_model_python_path != previous_local_model_python_path
    )
    xhs_downloader_path_changed = (
        "xhs_downloader_path" in payload
        and next_xhs_downloader_path != previous_xhs_downloader_path
    )
    tiktok_downloader_path_changed = (
        "tiktok_downloader_path" in payload
        and next_tiktok_downloader_path != previous_tiktok_downloader_path
    )
    ks_downloader_path_changed = (
        "ks_downloader_path" in payload and next_ks_downloader_path != previous_ks_downloader_path
    )
    speech_volcengine_changed = (
        (
            "speech_volcengine_app_key" in payload
            and next_speech_volcengine_app_key != previous_speech_volcengine_app_key
        )
        or (
            "speech_volcengine_access_key" in payload
            and next_speech_volcengine_access_key != previous_speech_volcengine_access_key
        )
        or (
            "speech_volcengine_resource_id" in payload
            and next_speech_volcengine_resource_id != previous_speech_volcengine_resource_id
        )
    )

    if deployment_profile_changed or wan2gp_path_changed or local_model_python_path_changed:
        payload["wan2gp_validation_status"] = _resolve_runtime_validation_status(
            RUNTIME_VALIDATION_STATUS_NOT_READY,
            ready=bool(
                next_deployment_profile == "gpu"
                and next_wan2gp_path
                and next_local_model_python_path
            ),
        )
    if xhs_downloader_path_changed:
        payload["xhs_downloader_validation_status"] = _resolve_runtime_validation_status(
            RUNTIME_VALIDATION_STATUS_NOT_READY,
            ready=bool(next_xhs_downloader_path),
        )
    if tiktok_downloader_path_changed:
        payload["tiktok_downloader_validation_status"] = _resolve_runtime_validation_status(
            RUNTIME_VALIDATION_STATUS_NOT_READY,
            ready=bool(next_tiktok_downloader_path),
        )
    if ks_downloader_path_changed:
        payload["ks_downloader_validation_status"] = _resolve_runtime_validation_status(
            RUNTIME_VALIDATION_STATUS_NOT_READY,
            ready=bool(next_ks_downloader_path),
        )
    if (
        deployment_profile_changed
        or local_model_python_path_changed
        or "faster_whisper_model" in payload
    ):
        payload["faster_whisper_validation_status"] = _resolve_runtime_validation_status(
            RUNTIME_VALIDATION_STATUS_NOT_READY,
            ready=(next_deployment_profile != "gpu" or bool(next_local_model_python_path)),
        )
    if deployment_profile_changed:
        payload["crawl4ai_validation_status"] = _resolve_runtime_validation_status(
            RUNTIME_VALIDATION_STATUS_NOT_READY,
            ready=True,
        )
    if speech_volcengine_changed:
        payload["speech_volcengine_validation_status"] = _resolve_runtime_validation_status(
            RUNTIME_VALIDATION_STATUS_NOT_READY,
            ready=bool(
                next_speech_volcengine_app_key
                and next_speech_volcengine_access_key
                and next_speech_volcengine_resource_id
            ),
        )

    if "google_credentials_path" in payload:
        _apply_google_credentials_path(
            payload,
            str(payload.get("google_credentials_path") or "").strip(),
        )

    for key, value in payload.items():
        if hasattr(settings, key):
            setattr(settings, key, value)

    persist_payload = {k: v for k, v in payload.items() if k in PERSISTABLE_SETTING_KEYS}
    if persist_payload:
        store = SettingsStoreService(db)
        await store.upsert_many(persist_payload)

    return _build_settings_response()


@router.post("/google-credentials/upload", response_model=SettingsResponse)
async def upload_google_credentials(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    filename = _sanitize_google_credentials_filename(file.filename)
    if Path(filename).suffix.lower() != ".json":
        raise HTTPException(status_code=400, detail="仅支持上传 JSON 格式的服务账号密钥")

    try:
        raw_bytes = await file.read()
    finally:
        await file.close()

    if not raw_bytes:
        raise HTTPException(status_code=400, detail="上传文件为空")

    try:
        credentials_payload = json.loads(raw_bytes.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400, detail="服务账号密钥必须为 UTF-8 编码的 JSON 文件"
        ) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="服务账号密钥不是有效的 JSON 文件") from exc

    if not isinstance(credentials_payload, dict):
        raise HTTPException(status_code=400, detail="服务账号密钥内容必须是 JSON 对象")

    if not str(credentials_payload.get("project_id") or "").strip():
        raise HTTPException(status_code=400, detail="服务账号密钥缺少 project_id")

    credentials_dir = _resolve_google_credentials_dir()
    credentials_dir.mkdir(parents=True, exist_ok=True)
    destination = credentials_dir / filename
    destination.write_text(
        json.dumps(credentials_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    previous_path = str(settings.google_credentials_path or "").strip()
    previous_file = Path(previous_path).expanduser().resolve() if previous_path else None
    if previous_file and previous_file != destination:
        try:
            if previous_file.parent == credentials_dir and previous_file.exists():
                previous_file.unlink()
        except OSError:
            pass

    payload: dict[str, object] = {}
    _apply_google_credentials_path(payload, str(destination))
    for key, value in payload.items():
        if hasattr(settings, key):
            setattr(settings, key, value)

    persist_payload = {k: v for k, v in payload.items() if k in PERSISTABLE_SETTING_KEYS}
    if persist_payload:
        store = SettingsStoreService(db)
        await store.upsert_many(persist_payload)

    return _build_settings_response()


@router.delete("/google-credentials", response_model=SettingsResponse)
async def delete_google_credentials(
    db: AsyncSession = Depends(get_db),
):
    _clear_google_credentials()

    store = SettingsStoreService(db)
    await store.delete_many(("google_credentials_path",))

    return _build_settings_response()


@router.get("/providers", response_model=ProvidersResponse)
async def get_available_providers():
    (
        shared_volcengine_seedance_api_key,
        normalized_image_providers,
        normalized_llm_providers,
    ) = _resolve_shared_volcengine_ark_credentials(
        image_providers=settings.image_providers or default_image_providers(),
        llm_providers=settings.llm_providers or default_llm_providers(),
    )
    shared_xiaomi_mimo_api_key, normalized_llm_providers = _resolve_shared_xiaomi_mimo_api_key(
        llm_providers=normalized_llm_providers,
    )
    shared_minimax_api_key, normalized_llm_providers = _resolve_shared_minimax_api_key(
        llm_providers=normalized_llm_providers,
    )
    llm_providers = []
    for provider in normalized_llm_providers:
        if str(provider.get("api_key") or "").strip():
            llm_providers.append(str(provider.get("id") or "").strip())

    audio_providers = ["edge_tts"]
    if _is_wan2gp_available():
        audio_providers.append("wan2gp")
    if _is_volcengine_tts_configured():
        audio_providers.append("volcengine_tts")
    if _is_kling_configured():
        audio_providers.append("kling_tts")
    if _is_vidu_configured():
        audio_providers.append("vidu_tts")
    if _is_minimax_configured(api_key=shared_minimax_api_key):
        audio_providers.append("minimax_tts")
    if _is_xiaomi_mimo_configured(api_key=shared_xiaomi_mimo_api_key):
        audio_providers.append("xiaomi_mimo_tts")

    speech_providers = ["faster_whisper"]
    if (
        _is_volcengine_tts_configured()
        and str(settings.speech_volcengine_resource_id or "").strip()
    ):
        speech_providers.append("volcengine_asr")

    image_providers = []
    for provider in normalized_image_providers:
        provider_id = str(provider.get("id") or "").strip()
        if not provider_id:
            continue
        has_key = bool(str(provider.get("api_key") or "").strip())
        enabled_models = _normalize_model_strings(provider.get("enabled_models") or [])
        if has_key and enabled_models:
            image_providers.append(provider_id)
    if _is_wan2gp_available():
        image_providers.append("wan2gp")
    if _is_kling_configured():
        image_providers.append("kling")
    if _is_vidu_configured():
        image_providers.append("vidu")
    if _is_minimax_configured(api_key=shared_minimax_api_key):
        image_providers.append("minimax")

    video_providers = []
    if shared_volcengine_seedance_api_key:
        video_providers.append("volcengine_seedance")
    if _is_wan2gp_available():
        video_providers.append("wan2gp")

    return ProvidersResponse(
        llm=llm_providers,
        audio=audio_providers,
        speech=speech_providers,
        image=image_providers,
        video=video_providers,
    )
