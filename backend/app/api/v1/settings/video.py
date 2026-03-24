import base64
import binascii
import json
import struct
import time
import zlib
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.providers.video.volcengine_seedance import resolve_seedance_model_id
from app.providers.video.wan2gp import (
    get_wan2gp_i2v_preset,
    get_wan2gp_t2v_preset,
    get_wan2gp_video_presets,
)
from app.providers.wan2gp import is_model_cached

from ._common import (
    _mask_key,
    _normalize_seedance_api_key,
    _normalize_seedance_base_url,
    _normalize_video_provider_id,
    logger,
)

router = APIRouter()


class SeedanceConnectivityTestRequest(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


class SeedanceConnectivityTestResponse(BaseModel):
    success: bool
    model: str
    latency_ms: int | None = None
    message: str | None = None
    error: str | None = None


class VideoModelConnectivityTestRequest(BaseModel):
    provider_id: str
    model: str
    api_key: str | None = None
    base_url: str | None = None
    wan2gp_path: str | None = None


class VideoModelConnectivityTestResponse(BaseModel):
    success: bool
    model: str
    latency_ms: int | None = None
    message: str | None = None
    error: str | None = None


class Wan2GPVideoPresetInfo(BaseModel):
    id: str
    mode: str
    display_name: str
    description: str
    model_type: str
    supports_chinese: bool
    prompt_language_preference: str
    supports_last_frame: bool
    default_resolution: str
    supported_resolutions: list[str]
    frames_per_second: int
    inference_steps: int
    guidance_scale: float
    flow_shift: float
    max_frames: int
    vram_min: int
    sliding_window_size: int | None = None
    sliding_window_size_min: int | None = None
    sliding_window_size_max: int | None = None
    sliding_window_size_step: int | None = None


class Wan2GPVideoPresetsResponse(BaseModel):
    t2v_presets: list[Wan2GPVideoPresetInfo]
    i2v_presets: list[Wan2GPVideoPresetInfo]


def _seedance_model_requires_image(model: str) -> bool:
    lowered = model.strip().lower()
    return "i2v" in lowered and "t2v" not in lowered


def _build_solid_png_data_uri(width: int, height: int) -> str:
    w = max(int(width), 1)
    h = max(int(height), 1)
    pixel = bytes((240, 240, 240, 255))
    # PNG scanline starts with one-byte filter method (0 = None).
    row = b"\x00" + pixel * w
    raw = row * h
    compressed = zlib.compress(raw, level=9)

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack("!I", len(data))
            + tag
            + data
            + struct.pack("!I", binascii.crc32(tag + data) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack("!IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + _chunk(b"IDAT", compressed)
        + _chunk(b"IEND", b"")
    )
    encoded = base64.b64encode(png).decode("ascii")
    return f"data:image/png;base64,{encoded}"


# Seedance i2v 联通性测试最小要求宽度 >= 300px。
_SEEDANCE_I2V_TEST_IMAGE_DATA_URI = _build_solid_png_data_uri(320, 320)


def _build_seedance_test_content(model: str) -> list[dict[str, object]]:
    content: list[dict[str, object]] = [
        {
            "type": "text",
            "text": "Seedance connectivity test. Generate a very short sample video.",
        }
    ]
    if _seedance_model_requires_image(model):
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": _SEEDANCE_I2V_TEST_IMAGE_DATA_URI},
            }
        )
    return content


def _extract_seedance_task_id(payload: dict) -> str:
    candidates = [
        payload.get("id"),
        payload.get("task_id"),
    ]
    data_block = payload.get("data")
    if isinstance(data_block, dict):
        candidates.append(data_block.get("id"))
        candidates.append(data_block.get("task_id"))

    for item in candidates:
        text = str(item or "").strip()
        if text:
            return text
    raise ValueError(f"Seedance create task response missing task id: {payload}")


async def _run_seedance_connectivity_test(
    *,
    api_key: str,
    base_url: str,
    model: str,
) -> SeedanceConnectivityTestResponse:
    resolved_model_id = resolve_seedance_model_id(model)
    request_payload = {
        "model": resolved_model_id,
        "content": _build_seedance_test_content(resolved_model_id),
        "ratio": "1:1",
        "resolution": "480p",
        "duration": 5,
        "watermark": False,
    }
    test_id = uuid4().hex[:8]
    started = time.perf_counter()
    task_id = ""
    logger.info(
        "[Seedance Model Test][%s] start model=%s resolved_model=%s base_url=%s api_key=%s",
        test_id,
        model,
        resolved_model_id,
        base_url,
        _mask_key(api_key),
    )

    try:
        timeout = httpx.Timeout(45.0, connect=20.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=True) as client:
            create_url = f"{base_url.rstrip('/')}/v1/videos/generations"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            response = await client.post(create_url, headers=headers, json=request_payload)
            response.raise_for_status()
            response_payload = response.json()
            if not isinstance(response_payload, dict):
                raise ValueError(f"Unexpected Seedance response: {response_payload}")
            task_id = _extract_seedance_task_id(response_payload)

            delete_url = f"{base_url.rstrip('/')}/v1/videos/generations/{task_id}"
            try:
                await client.delete(delete_url, headers=headers)
            except Exception:
                logger.warning(
                    "[Seedance Model Test][%s] failed to cleanup task %s",
                    test_id,
                    task_id,
                    exc_info=True,
                )

        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "[Seedance Model Test][%s] success model=%s latency_ms=%d task_id=%s",
            test_id,
            model,
            latency_ms,
            task_id,
        )
        return SeedanceConnectivityTestResponse(
            success=True,
            model=model,
            latency_ms=latency_ms,
            message="Seedance 任务创建成功，API Key 与模型可用。",
        )
    except httpx.HTTPStatusError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        response_text = ""
        try:
            body = exc.response.json()
            response_text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
        except Exception:
            response_text = str(exc.response.text or "").strip()
        response_preview = response_text[:600] if response_text else ""
        logger.exception(
            "[Seedance Model Test][%s] failed model=%s latency_ms=%d status=%s error=%s response_body=%s",
            test_id,
            model,
            latency_ms,
            exc.response.status_code,
            str(exc) or "Unknown error",
            response_preview,
        )
        error_message = str(exc) or "Unknown error"
        if response_preview:
            error_message = f"{error_message}; response_body={response_preview}"
        return SeedanceConnectivityTestResponse(
            success=False,
            model=model,
            latency_ms=latency_ms,
            error=error_message,
        )
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.exception(
            "[Seedance Model Test][%s] failed model=%s latency_ms=%d error=%s",
            test_id,
            model,
            latency_ms,
            str(exc) or "Unknown error",
        )
        return SeedanceConnectivityTestResponse(
            success=False,
            model=model,
            latency_ms=latency_ms,
            error=str(exc) or "Unknown error",
        )


@router.post("/video/volcengine_seedance/test", response_model=SeedanceConnectivityTestResponse)
async def test_seedance_connectivity(payload: SeedanceConnectivityTestRequest):
    resolved_api_key = _normalize_seedance_api_key(
        payload.api_key or settings.video_seedance_api_key
    )
    resolved_base_url = _normalize_seedance_base_url(
        str(payload.base_url or settings.video_seedance_base_url or "")
    )
    resolved_model = resolve_seedance_model_id(payload.model or settings.video_seedance_model or "")
    if not resolved_api_key:
        raise HTTPException(status_code=400, detail="Seedance API Key not configured")
    if not resolved_base_url:
        raise HTTPException(status_code=400, detail="Seedance Base URL not configured")
    if not resolved_model:
        raise HTTPException(status_code=400, detail="Seedance model not configured")
    return await _run_seedance_connectivity_test(
        api_key=resolved_api_key,
        base_url=resolved_base_url,
        model=resolved_model,
    )


@router.post("/video/models/test", response_model=VideoModelConnectivityTestResponse)
async def test_video_model_connectivity(payload: VideoModelConnectivityTestRequest):
    provider_id = _normalize_video_provider_id(payload.provider_id)
    model = str(payload.model or "").strip()
    if not provider_id:
        raise HTTPException(status_code=400, detail="provider_id not configured")
    if not model:
        raise HTTPException(status_code=400, detail="model not configured")

    test_id = uuid4().hex[:8]
    started = time.perf_counter()
    logger.info(
        "[Video Model Test][%s] start provider_id=%s model=%s",
        test_id,
        provider_id,
        model,
    )

    try:
        if provider_id == "volcengine_seedance":
            resolved_model = resolve_seedance_model_id(model)
            resolved_api_key = _normalize_seedance_api_key(
                payload.api_key or settings.video_seedance_api_key
            )
            resolved_base_url = _normalize_seedance_base_url(
                str(payload.base_url or settings.video_seedance_base_url or "")
            )
            if not resolved_api_key:
                raise ValueError("火山引擎 API Key 未配置")
            if not resolved_base_url:
                raise ValueError("火山引擎 Base URL 未配置")
            result = await _run_seedance_connectivity_test(
                api_key=resolved_api_key,
                base_url=resolved_base_url,
                model=resolved_model,
            )
            return VideoModelConnectivityTestResponse(**result.model_dump())

        if provider_id == "wan2gp":
            wan2gp_path = str(payload.wan2gp_path or settings.wan2gp_path or "").strip()
            if not wan2gp_path:
                raise ValueError("Wan2GP 路径未配置")
            wan2gp_root = Path(wan2gp_path).expanduser()
            if not wan2gp_root.exists() or not (wan2gp_root / "wgp.py").exists():
                raise ValueError(f"Wan2GP 未就绪：{wan2gp_root}")

            presets_payload = get_wan2gp_video_presets(str(wan2gp_root))
            t2v_ids = {
                str(item.get("id") or "").strip() for item in presets_payload.get("t2v_presets", [])
            }
            i2v_ids = {
                str(item.get("id") or "").strip() for item in presets_payload.get("i2v_presets", [])
            }

            model_type = ""
            model_mode = ""
            if model in t2v_ids:
                preset = get_wan2gp_t2v_preset(model)
                model_type = str(preset.get("model_type") or "").strip()
                model_mode = "t2v"
            elif model in i2v_ids:
                preset = get_wan2gp_i2v_preset(model)
                model_type = str(preset.get("model_type") or "").strip()
                model_mode = "i2v"
            else:
                raise ValueError(f"未知的 Wan2GP 视频模型: {model}")

            cached = is_model_cached(wan2gp_root, model_type)
            if cached is True:
                cache_message = "模型文件已缓存，可直接生成。"
            elif cached is False:
                cache_message = "模型文件未缓存，首次生成时会自动下载。"
            else:
                cache_message = "模型缓存状态未知。"

            latency_ms = int((time.perf_counter() - started) * 1000)
            return VideoModelConnectivityTestResponse(
                success=True,
                model=model,
                latency_ms=latency_ms,
                message=f"Wan2GP 运行时可用（{model_mode}）。{cache_message}",
            )

        raise ValueError(f"Unsupported video provider: {provider_id}")
    except httpx.HTTPStatusError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        response_text = ""
        try:
            body = exc.response.json()
            response_text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
        except Exception:
            response_text = str(exc.response.text or "").strip()
        response_preview = response_text[:600] if response_text else ""
        logger.exception(
            "[Video Model Test][%s] failed provider_id=%s model=%s latency_ms=%d status=%s error=%s response_body=%s",
            test_id,
            provider_id,
            model,
            latency_ms,
            exc.response.status_code,
            str(exc) or "Unknown error",
            response_preview,
        )
        error_message = str(exc) or "Unknown error"
        if response_preview:
            error_message = f"{error_message}; response_body={response_preview}"
        return VideoModelConnectivityTestResponse(
            success=False,
            model=model,
            latency_ms=latency_ms,
            error=error_message,
        )
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.exception(
            "[Video Model Test][%s] failed provider_id=%s model=%s latency_ms=%d error=%s",
            test_id,
            provider_id,
            model,
            latency_ms,
            str(exc) or "Unknown error",
        )
        return VideoModelConnectivityTestResponse(
            success=False,
            model=model,
            latency_ms=latency_ms,
            error=str(exc) or "Unknown error",
        )


@router.get("/video/wan2gp/presets", response_model=Wan2GPVideoPresetsResponse)
async def get_wan2gp_video_presets_api():
    payload = get_wan2gp_video_presets(settings.wan2gp_path)
    return Wan2GPVideoPresetsResponse(
        t2v_presets=[Wan2GPVideoPresetInfo(**item) for item in payload.get("t2v_presets", [])],
        i2v_presets=[Wan2GPVideoPresetInfo(**item) for item in payload.get("i2v_presets", [])],
    )
