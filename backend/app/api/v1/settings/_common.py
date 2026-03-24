import logging
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlparse

from app.config import settings
from app.image_catalog import (
    IMAGE_PROVIDER_TYPE_OPENAI_CHAT,
    IMAGE_PROVIDER_TYPE_VOLCENGINE_SEEDREAM,
    IMAGE_PROVIDER_TYPES,
    default_image_providers,
)
from app.llm.catalog import (
    LLM_PROVIDER_TYPE_GEMINI,
    LLM_PROVIDER_TYPE_OPENAI_CHAT,
    LLM_PROVIDER_TYPE_OPENAI_RESPONSES,
    LLM_PROVIDER_TYPES,
    canonicalize_llm_model,
    default_llm_providers,
)
from app.providers.kling_auth import (
    normalize_kling_access_key,
    normalize_kling_base_url,
    normalize_kling_secret_key,
)
from app.schemas.settings import (
    ImageProviderConfig,
    LLMProviderConfig,
)

logger = logging.getLogger(__name__)

_normalize_kling_access_key = normalize_kling_access_key
_normalize_kling_base_url = normalize_kling_base_url
_normalize_kling_secret_key = normalize_kling_secret_key

EDGE_TTS_VOICES = [
    {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓 (女声)", "locale": "zh-CN"},
    {"id": "zh-CN-XiaoyiNeural", "name": "晓伊 (女声)", "locale": "zh-CN"},
    {"id": "zh-CN-YunjianNeural", "name": "云健 (男声)", "locale": "zh-CN"},
    {"id": "zh-CN-YunxiNeural", "name": "云希 (男声)", "locale": "zh-CN"},
    {"id": "zh-CN-YunxiaNeural", "name": "云夏 (男声)", "locale": "zh-CN"},
    {"id": "zh-CN-YunyangNeural", "name": "云扬 (男声)", "locale": "zh-CN"},
    {"id": "zh-CN-liaoning-XiaobeiNeural", "name": "晓北 (东北女声)", "locale": "zh-CN-liaoning"},
    {"id": "zh-CN-shaanxi-XiaoniNeural", "name": "晓妮 (陕西女声)", "locale": "zh-CN-shaanxi"},
    {"id": "zh-TW-HsiaoChenNeural", "name": "曉臻 (台湾女声)", "locale": "zh-TW"},
    {"id": "zh-TW-YunJheNeural", "name": "雲哲 (台湾男声)", "locale": "zh-TW"},
    {"id": "zh-TW-HsiaoYuNeural", "name": "曉雨 (台湾女声)", "locale": "zh-TW"},
]

AUDIO_PREVIEW_TEXT_BY_LOCALE = {
    "zh-CN": "您好，欢迎使用影流，祝您创作愉快。",
    "zh-TW": "哈囉，歡迎使用影流，祝你創作順利。",
    "zh-HK": "你好，歡迎使用影流，祝你創作順利。",
    "en-US": "Hello, welcome to LocalVideo. Wishing you an inspiring creative session.",
    "en-GB": "Hello, welcome to LocalVideo. Wishing you a smooth and inspiring creative session.",
    "ja-JP": "こんにちは、LocalVideoへようこそ。創作を楽しんでください。",
    "es-ES": "Hola, bienvenido a LocalVideo. Que disfrutes creando.",
    "es-MX": "Hola, bienvenido a LocalVideo. Que disfrutes mucho creando.",
    "id-ID": "Halo, selamat datang di LocalVideo. Semoga proses kreatifmu lancar.",
}

FASTER_WHISPER_MODELS = {
    "tiny",
    "base",
    "small",
    "medium",
    "large-v1",
    "large-v2",
    "large-v3",
}

RUNTIME_VALIDATION_STATUS_NOT_READY = "not_ready"
RUNTIME_VALIDATION_STATUS_PENDING = "pending"
RUNTIME_VALIDATION_STATUS_FAILED = "failed"
RUNTIME_VALIDATION_STATUS_READY = "ready"
RUNTIME_VALIDATION_STATUSES = {
    RUNTIME_VALIDATION_STATUS_NOT_READY,
    RUNTIME_VALIDATION_STATUS_PENDING,
    RUNTIME_VALIDATION_STATUS_FAILED,
    RUNTIME_VALIDATION_STATUS_READY,
}

DEFAULT_AUDIO_PREVIEW_TEXT = AUDIO_PREVIEW_TEXT_BY_LOCALE["zh-CN"]
DEFAULT_CUSTOM_IMAGE_MODEL = "gemini-3-pro-image-preview"
DEFAULT_CUSTOM_IMAGE_MODELS = [
    "gemini-3.1-flash-image-preview",
    DEFAULT_CUSTOM_IMAGE_MODEL,
]


def _is_wan2gp_available() -> bool:
    if str(settings.deployment_profile or "").strip().lower() != "gpu":
        return False
    if not settings.wan2gp_path:
        return False
    if not settings.local_model_python_path:
        return False
    if (
        _normalize_runtime_validation_status(settings.wan2gp_validation_status)
        != RUNTIME_VALIDATION_STATUS_READY
    ):
        return False
    wgp_path = Path(settings.wan2gp_path).expanduser()
    python_path = Path(settings.local_model_python_path).expanduser()
    return (
        wgp_path.exists()
        and (wgp_path / "wgp.py").exists()
        and python_path.exists()
        and python_path.is_file()
    )


def _normalize_runtime_validation_status(value: str | None) -> str:
    candidate = str(value or "").strip().lower()
    if candidate in RUNTIME_VALIDATION_STATUSES:
        return candidate
    return RUNTIME_VALIDATION_STATUS_NOT_READY


def _resolve_runtime_validation_status(value: str | None, *, ready: bool) -> str:
    if not ready:
        return RUNTIME_VALIDATION_STATUS_NOT_READY
    normalized = _normalize_runtime_validation_status(value)
    if normalized == RUNTIME_VALIDATION_STATUS_NOT_READY:
        return RUNTIME_VALIDATION_STATUS_PENDING
    return normalized


def _normalize_optional_path(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def normalize_audio_preview_locale(value: str | None) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        return "zh-CN"

    candidates = [
        candidate.strip().lower()
        for candidate in raw_value.replace(",", "/").split("/")
        if candidate.strip()
    ]
    if not candidates:
        candidates = [raw_value.lower()]

    for candidate in candidates:
        if candidate.startswith("zh-hk") or candidate.startswith("yue"):
            return "zh-HK"
        if candidate.startswith("zh-tw"):
            return "zh-TW"
        if candidate.startswith("zh"):
            return "zh-CN"
        if candidate.startswith("en-gb"):
            return "en-GB"
        if candidate.startswith("en"):
            return "en-US"
        if candidate.startswith("ja"):
            return "ja-JP"
        if candidate.startswith("es-mx"):
            return "es-MX"
        if candidate.startswith("es"):
            return "es-ES"
        if candidate.startswith("id"):
            return "id-ID"

    return "zh-CN"


def resolve_audio_preview_text_for_locale(locale: str | None) -> str:
    normalized_locale = normalize_audio_preview_locale(locale)
    return AUDIO_PREVIEW_TEXT_BY_LOCALE.get(normalized_locale, DEFAULT_AUDIO_PREVIEW_TEXT)


def _normalize_model_strings(models: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for item in models:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _normalize_openai_like_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    parsed = urlparse(normalized)
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/v1") or path.endswith("/v4") or path.endswith("/api/v3"):
        return normalized
    if not path:
        return f"{normalized}/v1"
    if path.startswith("/api/paas/v4"):
        return normalized
    return f"{normalized}/v1"


def _normalize_gemini_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    parsed = urlparse(normalized)
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/v1beta/openai"):
        return normalized
    if path.endswith("/v1beta"):
        return f"{normalized}/openai"
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}/v1beta/openai"
    return "https://generativelanguage.googleapis.com/v1beta/openai"


def _normalize_anthropic_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    parsed = urlparse(normalized)
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/v1"):
        return normalized
    if not path:
        return f"{normalized}/v1"
    return normalized


def _normalize_llm_providers(raw_providers: list[dict | LLMProviderConfig]) -> list[dict]:
    builtin_defaults = default_llm_providers()
    default_map = {item["id"]: item for item in builtin_defaults}
    normalized: list[dict] = []
    seen_ids: set[str] = set()

    for raw_item in raw_providers:
        item = raw_item.model_dump() if isinstance(raw_item, LLMProviderConfig) else dict(raw_item)
        provider_id = str(item.get("id") or "").strip()
        if not provider_id or provider_id in seen_ids:
            continue
        seen_ids.add(provider_id)

        name = str(item.get("name") or provider_id).strip()
        provider_type = str(item.get("provider_type") or "").strip()
        if provider_type not in LLM_PROVIDER_TYPES:
            fallback = default_map.get(provider_id)
            if fallback:
                provider_type = fallback["provider_type"]
            else:
                provider_type = LLM_PROVIDER_TYPE_OPENAI_CHAT

        is_builtin = bool(item.get("is_builtin"))
        fallback = default_map.get(provider_id)
        if fallback:
            is_builtin = True
            name = fallback["name"]
            provider_type = fallback["provider_type"]

        if fallback:
            raw_base_url = item.get("base_url") or fallback.get("base_url") or ""
        else:
            raw_base_url = item.get("base_url") or ""
        base_url = str(raw_base_url).strip()
        if provider_type == LLM_PROVIDER_TYPE_GEMINI and base_url:
            base_url = _normalize_gemini_base_url(base_url)
        elif (
            provider_type
            in {
                LLM_PROVIDER_TYPE_OPENAI_CHAT,
                LLM_PROVIDER_TYPE_OPENAI_RESPONSES,
            }
            and base_url
        ):
            base_url = _normalize_openai_like_base_url(base_url)
        api_key = str(item.get("api_key") or "").strip()

        raw_catalog_models = item.get("catalog_models")
        if fallback and is_builtin:
            raw_catalog_source = fallback.get("catalog_models") or []
        else:
            raw_catalog_source = (
                raw_catalog_models
                if raw_catalog_models is not None
                else (fallback.get("catalog_models") if fallback else [])
            )
        raw_catalog = _normalize_model_strings(raw_catalog_source)
        catalog_models = _normalize_model_strings(
            [
                canonicalize_llm_model(
                    model,
                    provider_id=provider_id,
                    provider_name=name,
                    base_url=base_url,
                )
                for model in raw_catalog
            ]
        )
        raw_enabled_models = item.get("enabled_models")
        raw_enabled = _normalize_model_strings(
            raw_enabled_models
            if raw_enabled_models is not None
            else (fallback.get("enabled_models") if fallback else [])
        )
        enabled_models = _normalize_model_strings(
            [
                canonicalize_llm_model(
                    model,
                    provider_id=provider_id,
                    provider_name=name,
                    base_url=base_url,
                )
                for model in raw_enabled
            ]
        )
        if raw_enabled_models is None and not enabled_models and catalog_models:
            enabled_models = list(catalog_models)
        if fallback and catalog_models and enabled_models:
            catalog_set = set(catalog_models)
            enabled_models = [model for model in enabled_models if model in catalog_set]
        if not fallback and enabled_models:
            # Preserve user-enabled models for custom providers even if upstream
            # model discovery no longer returns them.
            catalog_set = set(catalog_models)
            missing_models = [model for model in enabled_models if model not in catalog_set]
            if missing_models:
                catalog_models = [*catalog_models, *missing_models]

        default_model = canonicalize_llm_model(
            item.get("default_model"),
            provider_id=provider_id,
            provider_name=name,
            base_url=base_url,
        )
        if default_model and default_model not in enabled_models:
            default_model = ""
        if not default_model and enabled_models:
            default_model = enabled_models[0]

        supports_vision = bool(item.get("supports_vision"))
        if fallback:
            supports_vision = bool(fallback.get("supports_vision"))

        normalized.append(
            {
                "id": provider_id,
                "name": name,
                "is_builtin": is_builtin,
                "provider_type": provider_type,
                "base_url": base_url,
                "api_key": api_key,
                "catalog_models": catalog_models,
                "enabled_models": enabled_models,
                "default_model": default_model,
                "supports_vision": supports_vision,
            }
        )

    if not normalized:
        return builtin_defaults

    normalized_by_id = {
        str(item.get("id") or "").strip(): item
        for item in normalized
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    builtin_ids = {
        str(item.get("id") or "").strip()
        for item in builtin_defaults
        if str(item.get("id") or "").strip()
    }

    # Keep builtin providers in builtin order, then append custom providers.
    ordered: list[dict] = []
    for builtin in builtin_defaults:
        provider_id = str(builtin.get("id") or "").strip()
        if not provider_id:
            continue
        ordered.append(normalized_by_id.get(provider_id, dict(builtin)))

    for item in normalized:
        provider_id = str(item.get("id") or "").strip()
        if not provider_id or provider_id in builtin_ids:
            continue
        ordered.append(item)

    return ordered


def _normalize_image_provider_id(raw_id: str | None) -> str:
    return str(raw_id or "").strip()


def _normalize_video_provider_id(raw_id: str | None) -> str:
    return str(raw_id or "").strip().lower()


def _normalize_seedream_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    parsed = urlparse(normalized)
    if not parsed.scheme or not parsed.netloc:
        return "https://ark.cn-beijing.volces.com/api/v3"

    host = parsed.netloc
    path = (parsed.path or "").rstrip("/")
    lower_host = host.lower()
    if lower_host.startswith("operator.las.") and lower_host.endswith(".volces.com"):
        host = f"ark.{host[len('operator.las.') :]}"

    if path.endswith("/api/v1/online"):
        final_path = "/api/v3"
    elif path.endswith("/api/v3"):
        final_path = "/api/v3"
    elif path.endswith("/api/v1"):
        final_path = "/api/v3"
    elif path.endswith("/api"):
        final_path = "/api/v3"
    elif path == "/v3":
        final_path = "/api/v3"
    elif path == "/v1":
        final_path = "/api/v3"
    elif not path:
        final_path = "/api/v3"
    else:
        final_path = path
    return f"{parsed.scheme}://{host}{final_path}"


def _normalize_seedance_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    parsed = urlparse(normalized)
    if not parsed.scheme or not parsed.netloc:
        return "https://ark.cn-beijing.volces.com/api/v3"

    path = (parsed.path or "").rstrip("/")
    if path.endswith("/api/v3"):
        final_path = "/api/v3"
    elif path.endswith("/api/v1/online"):
        final_path = "/api/v3"
    elif path.endswith("/api/v1"):
        final_path = "/api/v3"
    elif path.endswith("/api"):
        final_path = "/api/v3"
    elif not path:
        final_path = "/api/v3"
    else:
        final_path = path
    return f"{parsed.scheme}://{parsed.netloc}{final_path}"


def _normalize_seedance_api_key(api_key: str | None) -> str:
    value = str(api_key or "").strip().strip("\"'").strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    return value


def _normalize_vidu_base_url(base_url: str) -> str:
    normalized = str(base_url or "").strip().rstrip("/")
    parsed = urlparse(normalized)
    if not parsed.scheme or not parsed.netloc:
        return "https://api.vidu.cn"
    return f"{parsed.scheme}://{parsed.netloc}"


def _normalize_vidu_api_key(api_key: str | None) -> str:
    value = str(api_key or "").strip().strip("\"'").strip()
    if value.lower().startswith("token "):
        value = value[6:].strip()
    return value


def _normalize_minimax_base_url(base_url: str) -> str:
    normalized = str(base_url or "").strip().rstrip("/")
    parsed = urlparse(normalized)
    if not parsed.scheme or not parsed.netloc:
        return "https://api.minimaxi.com/v1"
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/v1"):
        return normalized
    if path:
        return f"{normalized}/v1"
    return f"{normalized}/v1"


def _normalize_image_providers(raw_providers: list[dict | ImageProviderConfig]) -> list[dict]:
    builtin_defaults = default_image_providers()
    default_map = {item["id"]: item for item in builtin_defaults}
    normalized: list[dict] = []
    seen_ids: set[str] = set()

    for raw_item in raw_providers:
        item = (
            raw_item.model_dump() if isinstance(raw_item, ImageProviderConfig) else dict(raw_item)
        )
        provider_id = _normalize_image_provider_id(item.get("id"))
        if provider_id == "builtin_openai_image":
            continue
        if not provider_id or provider_id in seen_ids:
            continue
        seen_ids.add(provider_id)

        fallback = default_map.get(provider_id)
        name = str(item.get("name") or provider_id).strip() or provider_id
        provider_type = (
            str(item.get("provider_type") or IMAGE_PROVIDER_TYPE_OPENAI_CHAT).strip()
            or IMAGE_PROVIDER_TYPE_OPENAI_CHAT
        )
        if provider_type not in IMAGE_PROVIDER_TYPES:
            provider_type = (
                str(fallback.get("provider_type") or IMAGE_PROVIDER_TYPE_OPENAI_CHAT)
                if fallback
                else IMAGE_PROVIDER_TYPE_OPENAI_CHAT
            )
        is_builtin = bool(item.get("is_builtin"))
        if fallback:
            is_builtin = True
            name = str(fallback.get("name") or name).strip() or name
            provider_type = (
                str(fallback.get("provider_type") or provider_type).strip() or provider_type
            )

        if fallback:
            raw_base_url = item.get("base_url") or fallback.get("base_url") or ""
        else:
            raw_base_url = item.get("base_url") or ""
        base_url = str(raw_base_url or "").strip()
        if provider_type == IMAGE_PROVIDER_TYPE_VOLCENGINE_SEEDREAM and base_url:
            base_url = _normalize_seedream_base_url(base_url)
        api_key = str(item.get("api_key") or "").strip()

        raw_enabled_models = item.get("enabled_models")
        if fallback and is_builtin:
            raw_catalog_source = fallback.get("catalog_models") or []
            if raw_enabled_models is None:
                raw_enabled_source = fallback.get("enabled_models") or raw_catalog_source
            else:
                raw_enabled_source = raw_enabled_models
            raw_default_model = item.get("default_model") or fallback.get("default_model") or ""
        else:
            raw_catalog_source = item.get("catalog_models")
            if raw_catalog_source is None:
                raw_catalog_source = list(DEFAULT_CUSTOM_IMAGE_MODELS)
            if raw_enabled_models is None:
                raw_enabled_source = raw_catalog_source
            else:
                raw_enabled_source = raw_enabled_models
            raw_default_model = item.get("default_model") or ""

        catalog_models = _normalize_model_strings(raw_catalog_source)
        if not catalog_models:
            catalog_models = list(DEFAULT_CUSTOM_IMAGE_MODELS)
        enabled_models = _normalize_model_strings(raw_enabled_source)
        catalog_set = set(catalog_models)
        enabled_models = [model for model in enabled_models if model in catalog_set]
        if raw_enabled_models is None and not enabled_models and catalog_models:
            enabled_models = list(catalog_models)
        default_model = str(raw_default_model or "").strip()
        if default_model and default_model not in enabled_models:
            default_model = ""
        if not default_model and enabled_models:
            default_model = enabled_models[0]

        reference_aspect_ratio = (
            str(
                item.get("reference_aspect_ratio")
                or (fallback.get("reference_aspect_ratio") if fallback else "1:1")
            ).strip()
            or "1:1"
        )
        reference_size = (
            str(
                item.get("reference_size") or (fallback.get("reference_size") if fallback else "1K")
            ).strip()
            or "1K"
        )
        frame_aspect_ratio = (
            str(
                item.get("frame_aspect_ratio")
                or (fallback.get("frame_aspect_ratio") if fallback else "9:16")
            ).strip()
            or "9:16"
        )
        frame_size = (
            str(
                item.get("frame_size") or (fallback.get("frame_size") if fallback else "1K")
            ).strip()
            or "1K"
        )

        normalized.append(
            {
                "id": provider_id,
                "name": name,
                "is_builtin": is_builtin,
                "provider_type": provider_type,
                "base_url": base_url,
                "api_key": api_key,
                "catalog_models": catalog_models,
                "enabled_models": enabled_models,
                "default_model": default_model,
                "reference_aspect_ratio": reference_aspect_ratio,
                "reference_size": reference_size,
                "frame_aspect_ratio": frame_aspect_ratio,
                "frame_size": frame_size,
            }
        )

    for builtin in default_image_providers():
        provider_id = _normalize_image_provider_id(builtin.get("id"))
        if not provider_id or provider_id in seen_ids:
            continue
        seen_ids.add(provider_id)
        normalized.append(
            {
                "id": provider_id,
                "name": str(builtin.get("name") or provider_id).strip() or provider_id,
                "is_builtin": True,
                "provider_type": str(
                    builtin.get("provider_type") or IMAGE_PROVIDER_TYPE_OPENAI_CHAT
                ).strip()
                or IMAGE_PROVIDER_TYPE_OPENAI_CHAT,
                "base_url": str(builtin.get("base_url") or "").strip(),
                "api_key": "",
                "catalog_models": _normalize_model_strings(builtin.get("catalog_models") or []),
                "enabled_models": _normalize_model_strings(
                    builtin.get("enabled_models") or builtin.get("catalog_models") or []
                ),
                "default_model": str(builtin.get("default_model") or "").strip(),
                "reference_aspect_ratio": str(
                    builtin.get("reference_aspect_ratio") or "1:1"
                ).strip()
                or "1:1",
                "reference_size": str(builtin.get("reference_size") or "1K").strip() or "1K",
                "frame_aspect_ratio": str(builtin.get("frame_aspect_ratio") or "9:16").strip()
                or "9:16",
                "frame_size": str(builtin.get("frame_size") or "1K").strip() or "1K",
            }
        )

    if not normalized:
        return default_image_providers()

    # Keep builtin providers in default catalog order, then custom providers.
    builtin_order = [str(item.get("id") or "").strip() for item in builtin_defaults]
    builtin_by_id = {
        str(item.get("id") or "").strip(): item
        for item in normalized
        if bool(item.get("is_builtin"))
    }
    ordered_builtins: list[dict] = []
    seen_builtin_ids: set[str] = set()
    for provider_id in builtin_order:
        if provider_id and provider_id in builtin_by_id:
            ordered_builtins.append(builtin_by_id[provider_id])
            seen_builtin_ids.add(provider_id)
    for item in normalized:
        provider_id = str(item.get("id") or "").strip()
        if bool(item.get("is_builtin")) and provider_id and provider_id not in seen_builtin_ids:
            ordered_builtins.append(item)
            seen_builtin_ids.add(provider_id)

    custom_providers = [item for item in normalized if not bool(item.get("is_builtin"))]
    return ordered_builtins + custom_providers


def _mask_key(api_key: str | None) -> str:
    if not api_key:
        return "<empty>"
    key = api_key.strip()
    if len(key) <= 10:
        return f"{key[:2]}***{key[-2:]}"
    return f"{key[:6]}***{key[-4:]}"


def _coerce_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_audio_speed(value: object, default: float = 1.0) -> float:
    speed = _coerce_float(value, default)
    return max(0.5, min(2.0, speed))
