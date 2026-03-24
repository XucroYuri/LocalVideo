from typing import Any, Literal
from urllib.parse import urlparse

from app.config import settings
from app.image_catalog import (
    IMAGE_PROVIDER_TYPE_GEMINI_API,
    IMAGE_PROVIDER_TYPE_OPENAI_CHAT,
    IMAGE_PROVIDER_TYPE_VOLCENGINE_SEEDREAM,
    default_image_providers,
)
from app.providers.image.minimax import (
    normalize_minimax_api_key,
    normalize_minimax_base_url,
    normalize_minimax_image_aspect_ratio,
    normalize_minimax_image_model,
    normalize_minimax_image_size,
)

ImageScene = Literal["reference", "frame"]
KLING_IMAGE_MODELS = {"kling-v3", "kling-v3-omni"}
KLING_IMAGE_ASPECT_RATIOS = {"16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "21:9"}
KLING_IMAGE_SIZES_BY_MODEL = {
    "kling-v3": {"1K", "2K", "4K"},
    "kling-v3-omni": {"1K", "2K"},
}


def _normalize_kling_model(raw_model: Any) -> str:
    normalized = str(raw_model or "").strip()
    return normalized if normalized in KLING_IMAGE_MODELS else "kling-v3"


def _normalize_kling_aspect_ratio(raw_value: Any, *, default: str) -> str:
    normalized = str(raw_value or "").strip().lower().replace("：", ":")
    return normalized if normalized in KLING_IMAGE_ASPECT_RATIOS else default


def _normalize_kling_image_size(raw_value: Any, *, model: str, default: str = "1K") -> str:
    normalized = str(raw_value or "").strip().upper()
    allowed = KLING_IMAGE_SIZES_BY_MODEL.get(_normalize_kling_model(model), {"1K", "2K", "4K"})
    if normalized in allowed:
        return normalized
    normalized_default = str(default or "1K").strip().upper()
    if normalized_default in allowed:
        return normalized_default
    return sorted(allowed)[0]


def _normalize_image_provider_id(provider_name: str | None) -> str:
    return str(provider_name or "").strip()


def _normalize_image_provider_pool() -> list[dict[str, Any]]:
    raw_pool = settings.image_providers or default_image_providers()
    if not isinstance(raw_pool, list) or not raw_pool:
        raw_pool = default_image_providers()

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in raw_pool:
        if not isinstance(item, dict):
            continue
        provider_id = _normalize_image_provider_id(item.get("id"))
        if provider_id == "builtin_openai_image":
            continue
        if not provider_id or provider_id in seen_ids:
            continue
        seen_ids.add(provider_id)
        normalized.append(
            {
                "id": provider_id,
                "name": str(item.get("name") or provider_id).strip() or provider_id,
                "provider_type": str(item.get("provider_type") or "openai_chat").strip()
                or "openai_chat",
                "base_url": str(item.get("base_url") or "").strip(),
                "api_key": str(item.get("api_key") or "").strip(),
                "default_model": str(item.get("default_model") or "").strip(),
                "enabled_models": [
                    str(model).strip()
                    for model in list(item.get("enabled_models") or [])
                    if str(model).strip()
                ],
                "reference_aspect_ratio": str(item.get("reference_aspect_ratio") or "1:1").strip()
                or "1:1",
                "reference_size": str(item.get("reference_size") or "1K").strip() or "1K",
                "frame_aspect_ratio": str(item.get("frame_aspect_ratio") or "9:16").strip()
                or "9:16",
                "frame_size": str(item.get("frame_size") or "1K").strip() or "1K",
            }
        )
    if not normalized:
        return default_image_providers()
    return normalized


def _resolve_image_provider_config(provider_name: str | None) -> dict[str, Any] | None:
    provider_id = _normalize_image_provider_id(provider_name)
    for provider in _normalize_image_provider_pool():
        if str(provider.get("id") or "").strip() == provider_id:
            return provider
    return None


def _normalize_seedream_base_url(raw_base_url: str) -> str:
    normalized = raw_base_url.strip().rstrip("/")
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


def resolve_provider_runtime_name(provider_name: str | None) -> str:
    normalized = str(provider_name or "").strip()
    if normalized == "wan2gp":
        return "wan2gp"
    if normalized == "kling":
        return "kling"
    if normalized == "vidu":
        return "vidu"
    if normalized == "minimax":
        return "minimax"
    provider_config = _resolve_image_provider_config(provider_name)
    if provider_config:
        provider_type = str(provider_config.get("provider_type") or "openai_chat").strip()
        if provider_type == IMAGE_PROVIDER_TYPE_VOLCENGINE_SEEDREAM:
            return "volcengine_seedream"
        if provider_type == IMAGE_PROVIDER_TYPE_GEMINI_API:
            return "gemini_api"
        return "openai_chat"
    return normalized


def get_provider_image_defaults(provider_name: str, scene: ImageScene) -> tuple[str, str]:
    if provider_name == "kling":
        if scene == "reference":
            model = _normalize_kling_model(settings.image_kling_t2i_model)
            return (
                _normalize_kling_aspect_ratio(
                    settings.image_kling_reference_aspect_ratio, default="1:1"
                ),
                _normalize_kling_image_size(
                    settings.image_kling_reference_size, model=model, default="1K"
                ),
            )
        model = _normalize_kling_model(settings.image_kling_i2i_model)
        return (
            _normalize_kling_aspect_ratio(settings.image_kling_frame_aspect_ratio, default="9:16"),
            _normalize_kling_image_size(settings.image_kling_frame_size, model=model, default="1K"),
        )
    if provider_name == "vidu":
        if scene == "reference":
            return "1:1", ""
        return "9:16", ""
    if provider_name == "minimax":
        if scene == "reference":
            return (
                normalize_minimax_image_aspect_ratio(
                    settings.image_minimax_reference_aspect_ratio,
                    model=settings.image_minimax_model,
                    default="1:1",
                ),
                normalize_minimax_image_size(settings.image_minimax_reference_size, default="2K"),
            )
        return (
            normalize_minimax_image_aspect_ratio(
                settings.image_minimax_frame_aspect_ratio,
                model=settings.image_minimax_model,
                default="9:16",
            ),
            normalize_minimax_image_size(settings.image_minimax_frame_size, default="2K"),
        )

    provider_config = _resolve_image_provider_config(provider_name)
    if provider_config:
        if scene == "reference":
            return (
                str(provider_config.get("reference_aspect_ratio") or "1:1"),
                str(provider_config.get("reference_size") or "1K"),
            )
        return (
            str(provider_config.get("frame_aspect_ratio") or "9:16"),
            str(provider_config.get("frame_size") or "1K"),
        )

    if scene == "reference":
        return "1:1", "1K"
    return "9:16", "1K"


def get_provider_kwargs(
    provider_name: str,
    scene: ImageScene,
    input_data: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    payload = input_data or {}

    if provider_name == "kling":
        access_key = str(settings.kling_access_key or "").strip()
        secret_key = str(settings.kling_secret_key or "").strip()
        if not (access_key and secret_key):
            return None
        use_reference_consistency = bool(payload.get("use_reference_consistency", False))
        default_model = (
            settings.image_kling_i2i_model
            if scene == "frame" and use_reference_consistency
            else settings.image_kling_t2i_model
        )
        model = _normalize_kling_model(payload.get("image_model") or default_model or "kling-v3")
        if not model:
            return None
        if scene == "reference":
            aspect_ratio_default = _normalize_kling_aspect_ratio(
                settings.image_kling_reference_aspect_ratio,
                default="1:1",
            )
            image_size_default = _normalize_kling_image_size(
                settings.image_kling_reference_size,
                model=model,
                default="1K",
            )
        else:
            aspect_ratio_default = _normalize_kling_aspect_ratio(
                settings.image_kling_frame_aspect_ratio,
                default="9:16",
            )
            image_size_default = _normalize_kling_image_size(
                settings.image_kling_frame_size,
                model=model,
                default="1K",
            )
        aspect_ratio = _normalize_kling_aspect_ratio(
            payload.get("aspect_ratio") or payload.get("image_aspect_ratio"),
            default=aspect_ratio_default,
        )
        image_size = _normalize_kling_image_size(
            payload.get("image_size") or payload.get("image_resolution"),
            model=model,
            default=image_size_default,
        )
        return {
            "access_key": access_key,
            "secret_key": secret_key,
            "base_url": str(settings.kling_base_url or "").strip(),
            "model": model,
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
        }
    if provider_name == "vidu":
        api_key = str(settings.vidu_api_key or "").strip()
        if not api_key:
            return None
        use_reference_consistency = bool(payload.get("use_reference_consistency", False))
        default_model = (
            settings.image_vidu_i2i_model
            if scene == "frame" and use_reference_consistency
            else settings.image_vidu_t2i_model
        )
        model = str(payload.get("image_model") or default_model or "viduq2").strip() or "viduq2"
        aspect_ratio_default = (
            str(settings.image_vidu_reference_aspect_ratio or "1:1").strip()
            if scene == "reference"
            else str(settings.image_vidu_frame_aspect_ratio or "9:16").strip()
        )
        aspect_ratio = (
            str(
                payload.get("aspect_ratio")
                or payload.get("image_aspect_ratio")
                or aspect_ratio_default
            ).strip()
            or aspect_ratio_default
        )
        resolution_default = (
            str(settings.image_vidu_reference_size or "1080p").strip()
            if scene == "reference"
            else str(settings.image_vidu_frame_size or "1080p").strip()
        )
        resolution = str(
            payload.get("image_size") or payload.get("image_resolution") or resolution_default
        ).strip()
        if resolution.upper() == "1K":
            resolution = "1080p"
        return {
            "api_key": api_key,
            "base_url": str(settings.vidu_base_url or "").strip(),
            "model": model,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
        }
    if provider_name == "minimax":
        api_key = normalize_minimax_api_key(settings.minimax_api_key)
        if not api_key:
            return None
        default_model = settings.image_minimax_model or "image-01"
        model = normalize_minimax_image_model(payload.get("image_model") or default_model)
        if scene == "reference":
            aspect_ratio_default = normalize_minimax_image_aspect_ratio(
                settings.image_minimax_reference_aspect_ratio,
                model=model,
                default="1:1",
            )
            image_size_default = normalize_minimax_image_size(
                settings.image_minimax_reference_size,
                default="2K",
            )
        else:
            aspect_ratio_default = normalize_minimax_image_aspect_ratio(
                settings.image_minimax_frame_aspect_ratio,
                model=model,
                default="9:16",
            )
            image_size_default = normalize_minimax_image_size(
                settings.image_minimax_frame_size,
                default="2K",
            )
        return {
            "api_key": api_key,
            "base_url": normalize_minimax_base_url(settings.minimax_base_url),
            "model": model,
            "aspect_ratio": normalize_minimax_image_aspect_ratio(
                payload.get("aspect_ratio") or payload.get("image_aspect_ratio"),
                model=model,
                default=aspect_ratio_default,
            ),
            "image_size": normalize_minimax_image_size(
                payload.get("image_size") or payload.get("image_resolution"),
                default=image_size_default,
            ),
        }

    provider_config = _resolve_image_provider_config(provider_name)
    if provider_config:
        api_key = str(provider_config.get("api_key") or "").strip()
        base_url = str(provider_config.get("base_url") or "").strip()
        provider_type = str(
            provider_config.get("provider_type") or IMAGE_PROVIDER_TYPE_OPENAI_CHAT
        ).strip()
        enabled_models = [
            str(item).strip()
            for item in list(provider_config.get("enabled_models") or [])
            if str(item).strip()
        ]
        model = str(
            payload.get("image_model")
            or provider_config.get("default_model")
            or (enabled_models[0] if enabled_models else "")
        ).strip()
        if enabled_models and model not in enabled_models:
            model = enabled_models[0]
        if not api_key or not model:
            return None
        if scene == "reference":
            aspect_ratio = str(provider_config.get("reference_aspect_ratio") or "1:1")
            image_size = str(provider_config.get("reference_size") or "1K")
        else:
            aspect_ratio = str(provider_config.get("frame_aspect_ratio") or "9:16")
            image_size = str(provider_config.get("frame_size") or "1K")

        if provider_type == IMAGE_PROVIDER_TYPE_GEMINI_API:
            return {
                "api_key": api_key,
                "model": model,
                "aspect_ratio": aspect_ratio,
                "image_size": image_size,
            }

        if not base_url:
            return None
        if provider_type == IMAGE_PROVIDER_TYPE_VOLCENGINE_SEEDREAM:
            base_url = _normalize_seedream_base_url(base_url)
        return {
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
            "aspect_ratio": aspect_ratio,
            "image_size": image_size,
        }

    if provider_name == "wan2gp":
        if not settings.wan2gp_path:
            return None

        if scene == "reference":
            selected_preset = (
                payload.get("image_wan2gp_preset")
                or settings.image_wan2gp_preset
                or "qwen_image_2512"
            )
            default_resolution = settings.image_wan2gp_reference_resolution or "1024x1024"
        else:
            use_reference_consistency = bool(payload.get("use_reference_consistency", False))
            selected_preset = payload.get("image_wan2gp_preset")
            if not selected_preset:
                selected_preset = (
                    settings.image_wan2gp_preset_i2i
                    if use_reference_consistency
                    else settings.image_wan2gp_preset
                )
            if not selected_preset:
                selected_preset = (
                    "qwen_image_edit_plus2" if use_reference_consistency else "qwen_image_2512"
                )
            default_resolution = settings.image_wan2gp_frame_resolution or "1088x1920"

        return {
            "wan2gp_path": settings.wan2gp_path,
            "python_executable": settings.local_model_python_path,
            "image_preset": selected_preset,
            "image_resolution": payload.get("image_resolution") or default_resolution,
            "image_inference_steps": payload.get("image_wan2gp_inference_steps")
            or settings.image_wan2gp_inference_steps
            or 0,
            "image_guidance_scale": payload.get("image_wan2gp_guidance_scale")
            or settings.image_wan2gp_guidance_scale
            or 0.0,
            "seed": settings.image_wan2gp_seed,
            "negative_prompt": settings.image_wan2gp_negative_prompt or "",
        }

    return None
