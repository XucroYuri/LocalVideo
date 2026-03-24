import time
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.image_catalog import (
    IMAGE_PROVIDER_TYPE_GEMINI_API,
    IMAGE_PROVIDER_TYPE_OPENAI_CHAT,
    IMAGE_PROVIDER_TYPE_VOLCENGINE_SEEDREAM,
    default_image_providers,
)
from app.providers import get_image_provider
from app.providers.image.wan2gp import get_wan2gp_image_preset, get_wan2gp_image_presets
from app.providers.kling_auth import is_kling_configured

from ._common import (
    _is_wan2gp_available,
    _normalize_image_provider_id,
    _normalize_image_providers,
    _normalize_kling_access_key,
    _normalize_kling_base_url,
    _normalize_kling_secret_key,
    _normalize_seedream_base_url,
    _normalize_vidu_base_url,
    logger,
)

router = APIRouter()


class ImageModelConnectivityTestRequest(BaseModel):
    provider_id: str
    model: str
    access_key: str | None = None
    secret_key: str | None = None


class ImageModelConnectivityTestResponse(BaseModel):
    success: bool
    model: str
    latency_ms: int | None = None
    message: str | None = None
    error: str | None = None


class Wan2GPPresetInfo(BaseModel):
    id: str
    display_name: str
    description: str
    preset_type: str
    supported_modes: list[str]
    supports_reference: bool
    supports_chinese: bool
    prompt_language_preference: str
    default_resolution: str
    supported_resolutions: list[str]
    inference_steps: int


class Wan2GPPresetsResponse(BaseModel):
    presets: list[Wan2GPPresetInfo]


@router.post("/image/models/test", response_model=ImageModelConnectivityTestResponse)
async def test_image_model_connectivity(payload: ImageModelConnectivityTestRequest):
    provider_id = _normalize_image_provider_id(payload.provider_id)
    model = str(payload.model or "").strip()
    if not provider_id:
        raise HTTPException(status_code=400, detail="provider_id not configured")
    if not model:
        raise HTTPException(status_code=400, detail="model not configured")

    test_id = uuid4().hex[:8]
    logger.info(
        "[Image Model Test][%s] start provider_id=%s model=%s",
        test_id,
        provider_id,
        model,
    )
    started = time.perf_counter()
    temp_path: Path | None = None

    try:
        temp_dir = Path(settings.storage_path).expanduser() / "_tests" / "image_model"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / f"{provider_id}_{test_id}.png"

        if provider_id == "wan2gp":
            if not _is_wan2gp_available():
                raise ValueError("Wan2GP 未就绪，请先完成本地模型路径校验。")
            preset = get_wan2gp_image_preset(model)
            provider = get_image_provider(
                "wan2gp",
                wan2gp_path=settings.wan2gp_path,
                python_executable=settings.local_model_python_path,
                image_preset=model,
                image_resolution=preset.get("default_resolution") or "1024x1024",
                image_inference_steps=8,
                image_guidance_scale=0.0,
                seed=-1,
            )
            await provider.generate(
                prompt="A simple test image of a blue circle on white background.",
                output_path=temp_path,
            )
        elif provider_id == "kling":
            access_key = _normalize_kling_access_key(
                payload.access_key if payload.access_key is not None else settings.kling_access_key
            )
            secret_key = _normalize_kling_secret_key(
                payload.secret_key if payload.secret_key is not None else settings.kling_secret_key
            )
            if not is_kling_configured(
                access_key=access_key,
                secret_key=secret_key,
            ):
                raise ValueError("可灵 Access Key / Secret Key 未配置")
            image_provider = get_image_provider(
                "kling",
                access_key=access_key,
                secret_key=secret_key,
                base_url=_normalize_kling_base_url(str(settings.kling_base_url or "")),
                model=model,
                aspect_ratio="1:1",
                timeout=90.0,
            )
            await image_provider.generate(
                prompt="A simple test image of a blue circle on white background.",
                output_path=temp_path,
            )
        elif provider_id == "vidu":
            api_key = str(settings.vidu_api_key or "").strip()
            if not api_key:
                raise ValueError("Vidu API Key 未配置")
            image_provider = get_image_provider(
                "vidu",
                api_key=api_key,
                base_url=_normalize_vidu_base_url(str(settings.vidu_base_url or "")),
                model=model,
                aspect_ratio="1:1",
                timeout=90.0,
            )
            await image_provider.generate(
                prompt="A simple test image of a blue circle on white background.",
                output_path=temp_path,
            )
        else:
            providers = _normalize_image_providers(
                settings.image_providers or default_image_providers()
            )
            provider = next(
                (
                    item
                    for item in providers
                    if _normalize_image_provider_id(item.get("id")) == provider_id
                ),
                None,
            )
            if not provider:
                raise ValueError(f"Image provider not found: {provider_id}")
            provider_type = str(
                provider.get("provider_type") or IMAGE_PROVIDER_TYPE_OPENAI_CHAT
            ).strip()
            api_key = str(provider.get("api_key") or "").strip()
            base_url = str(provider.get("base_url") or "").strip()
            if not api_key:
                raise ValueError("API Key not configured")
            if (
                provider_type
                in {IMAGE_PROVIDER_TYPE_OPENAI_CHAT, IMAGE_PROVIDER_TYPE_VOLCENGINE_SEEDREAM}
                and not base_url
            ):
                raise ValueError("Base URL not configured")
            if provider_type == IMAGE_PROVIDER_TYPE_VOLCENGINE_SEEDREAM:
                image_provider = get_image_provider(
                    "volcengine_seedream",
                    base_url=_normalize_seedream_base_url(base_url),
                    api_key=api_key,
                    model=model,
                    aspect_ratio=str(provider.get("reference_aspect_ratio") or "1:1"),
                    image_size=str(provider.get("reference_size") or "1K"),
                    timeout=90.0,
                )
            elif provider_type == IMAGE_PROVIDER_TYPE_GEMINI_API:
                image_provider = get_image_provider(
                    "gemini_api",
                    api_key=api_key,
                    model=model,
                    aspect_ratio=str(provider.get("reference_aspect_ratio") or "1:1"),
                    image_size=str(provider.get("reference_size") or "1K"),
                )
            elif provider_type == IMAGE_PROVIDER_TYPE_OPENAI_CHAT:
                image_provider = get_image_provider(
                    "openai_chat",
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    aspect_ratio=str(provider.get("reference_aspect_ratio") or "1:1"),
                    image_size=str(provider.get("reference_size") or "1K"),
                    timeout=90.0,
                )
            else:
                raise ValueError(f"Unsupported image provider_type: {provider_type}")
            await image_provider.generate(
                prompt="A simple test image of a blue circle on white background.",
                output_path=temp_path,
            )

        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "[Image Model Test][%s] success provider_id=%s model=%s latency_ms=%d output=%s",
            test_id,
            provider_id,
            model,
            latency_ms,
            temp_path,
        )
        return ImageModelConnectivityTestResponse(
            success=True,
            model=model,
            latency_ms=latency_ms,
            message="OK",
        )
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.exception(
            "[Image Model Test][%s] failed provider_id=%s model=%s latency_ms=%d error=%s",
            test_id,
            provider_id,
            model,
            latency_ms,
            str(exc) or "Unknown error",
        )
        return ImageModelConnectivityTestResponse(
            success=False,
            model=model,
            latency_ms=latency_ms,
            error=str(exc) or "Unknown error",
        )
    finally:
        if temp_path:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass


@router.get("/image/wan2gp/presets", response_model=Wan2GPPresetsResponse)
async def get_wan2gp_presets():
    return Wan2GPPresetsResponse(
        presets=[Wan2GPPresetInfo(**p) for p in get_wan2gp_image_presets(settings.wan2gp_path)]
    )
