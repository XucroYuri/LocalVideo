"""Vidu video generation provider (t2v / i2v / start-end)."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from PIL import Image

from app.providers.base.video import VideoProvider, VideoResult

logger = logging.getLogger(__name__)

DEFAULT_VIDU_BASE_URL = "https://api.vidu.cn"
DEFAULT_VIDU_VIDEO_MODEL = "viduq3-turbo"
VIDU_VIDEO_MODEL_PRESETS: dict[str, dict[str, Any]] = {
    "viduq3-turbo": {
        "display_name": "Vidu Q3 Turbo",
        "description": "Vidu Q3 Turbo 视频生成模型",
        "supports_t2v": True,
        "supports_i2v": True,
        "supports_last_frame": True,
        "supports_reference_image": False,
        "supports_combined_reference": False,
        "max_reference_images": 0,
        "aspect_ratios": ["16:9", "9:16", "3:4", "4:3", "1:1"],
        "resolutions": ["540p", "720p", "1080p"],
        "default_aspect_ratio": "9:16",
        "default_resolution": "1080p",
        "supported_durations": list(range(1, 17)),
        "default_duration": 5,
    },
    "viduq3-pro": {
        "display_name": "Vidu Q3 Pro",
        "description": "Vidu Q3 Pro 视频生成模型",
        "supports_t2v": True,
        "supports_i2v": True,
        "supports_last_frame": True,
        "supports_reference_image": False,
        "supports_combined_reference": False,
        "max_reference_images": 0,
        "aspect_ratios": ["16:9", "9:16", "3:4", "4:3", "1:1"],
        "resolutions": ["540p", "720p", "1080p"],
        "default_aspect_ratio": "9:16",
        "default_resolution": "1080p",
        "supported_durations": list(range(1, 17)),
        "default_duration": 5,
    },
}
SUPPORTED_MODELS = set(VIDU_VIDEO_MODEL_PRESETS.keys())
SUPPORTED_ASPECT_RATIOS = {
    ratio
    for preset in VIDU_VIDEO_MODEL_PRESETS.values()
    for ratio in preset.get("aspect_ratios", [])
}
TERMINAL_SUCCESS_STATUSES = {"succeed", "success", "succeeded", "completed", "finished"}
TERMINAL_FAILED_STATUSES = {"failed", "error", "cancelled", "canceled", "rejected"}


def _normalize_api_key(raw_api_key: str | None) -> str:
    value = str(raw_api_key or "").strip().strip("\"'").strip()
    if value.lower().startswith("token "):
        value = value[6:].strip()
    return value


def _normalize_base_url(raw_base_url: str | None) -> str:
    normalized = str(raw_base_url or DEFAULT_VIDU_BASE_URL).strip().rstrip("/")
    parsed = urlparse(normalized)
    if not parsed.scheme or not parsed.netloc:
        return DEFAULT_VIDU_BASE_URL
    return f"{parsed.scheme}://{parsed.netloc}"


def _normalize_model(value: Any) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return DEFAULT_VIDU_VIDEO_MODEL
    return normalized if normalized in SUPPORTED_MODELS else normalized


def get_vidu_video_preset(model: str | None) -> dict[str, Any]:
    normalized = str(model or "").strip()
    preset = (
        VIDU_VIDEO_MODEL_PRESETS.get(normalized)
        or VIDU_VIDEO_MODEL_PRESETS[DEFAULT_VIDU_VIDEO_MODEL]
    )
    return dict(preset)


def list_vidu_video_presets() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model_id in sorted(VIDU_VIDEO_MODEL_PRESETS.keys()):
        preset = get_vidu_video_preset(model_id)
        rows.append(
            {
                "id": model_id,
                "label": str(preset.get("display_name") or model_id),
                "description": str(preset.get("description") or ""),
                "supports_t2v": bool(preset.get("supports_t2v", True)),
                "supports_i2v": bool(preset.get("supports_i2v", True)),
                "supports_last_frame": bool(preset.get("supports_last_frame", True)),
                "supports_reference_image": bool(preset.get("supports_reference_image", False)),
                "supports_combined_reference": bool(
                    preset.get("supports_combined_reference", False)
                ),
                "max_reference_images": int(preset.get("max_reference_images") or 0),
                "supported_aspect_ratios": list(preset.get("aspect_ratios") or []),
                "supported_resolutions": list(preset.get("resolutions") or []),
                "default_aspect_ratio": str(preset.get("default_aspect_ratio") or "9:16"),
                "default_resolution": str(preset.get("default_resolution") or "1080p"),
                "supported_durations_seconds": [
                    int(item) for item in preset.get("supported_durations") or [] if int(item) > 0
                ],
            }
        )
    return rows


def _normalize_aspect_ratio(
    value: Any,
    *,
    model: str | None = None,
    default: str | None = None,
) -> str:
    preset = get_vidu_video_preset(model)
    fallback = str(default or preset.get("default_aspect_ratio") or "9:16").strip() or "9:16"
    normalized = str(value or fallback).strip().replace("：", ":")
    supported = {
        str(item).strip() for item in preset.get("aspect_ratios") or [] if str(item).strip()
    } or SUPPORTED_ASPECT_RATIOS
    if normalized in supported:
        return normalized
    return fallback


def _normalize_duration(
    value: Any,
    *,
    model: str | None = None,
    default: int | None = None,
) -> int:
    preset = get_vidu_video_preset(model)
    supported = sorted(
        {
            int(item)
            for item in preset.get("supported_durations") or []
            if isinstance(item, int | float) and int(item) > 0
        }
    )
    fallback = int(default or preset.get("default_duration") or 5)
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError):
        parsed = fallback
    parsed = max(0, parsed)
    if supported:
        for candidate in supported:
            if candidate >= parsed:
                return candidate
        return supported[-1]
    return fallback


def _normalize_resolution(value: Any, *, model: str | None = None) -> str | None:
    preset = get_vidu_video_preset(model)
    normalized = str(value or "").strip()
    if not normalized:
        fallback = str(preset.get("default_resolution") or "").strip()
        return fallback or None
    lower = normalized.lower()
    candidate = (
        f"{lower.rstrip('p')}p"
        if lower in {"540", "540p", "720", "720p", "1080", "1080p"}
        else lower
    )
    supported = {
        str(item).strip().lower() for item in preset.get("resolutions") or [] if str(item).strip()
    }
    if candidate in supported:
        return candidate
    fallback = str(preset.get("default_resolution") or "").strip().lower()
    if fallback:
        return fallback
    return None


def _extract_error_message(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("message", "msg", "error", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        error = payload.get("error")
        if isinstance(error, dict):
            nested = _extract_error_message(error)
            if nested:
                return nested
    return ""


def _extract_http_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        payload = None
    message = _extract_error_message(payload)
    if message:
        return message
    return response.text.strip() or f"HTTP {response.status_code}"


def _extract_task_id(payload: dict[str, Any]) -> str:
    task_id = str(payload.get("task_id") or payload.get("id") or "").strip()
    if task_id:
        return task_id
    data = payload.get("data")
    if isinstance(data, dict):
        return str(data.get("task_id") or data.get("id") or "").strip()
    return ""


def _extract_state(payload: Any) -> str:
    if isinstance(payload, dict):
        state = str(payload.get("state") or payload.get("status") or "").strip().lower()
        if state:
            return state
        data = payload.get("data")
        if isinstance(data, dict):
            return str(data.get("state") or data.get("status") or "").strip().lower()
    return ""


def _extract_video_url(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""

    creations = payload.get("creations")
    if isinstance(creations, list):
        for item in creations:
            if not isinstance(item, dict):
                continue
            for key in ("url", "video_url", "watermarked_url"):
                value = str(item.get(key) or "").strip()
                if value:
                    return value

    for key in ("url", "video_url", "file_url"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value

    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_video_url(data)

    return ""


def _extract_duration(payload: Any) -> float | None:
    if not isinstance(payload, dict):
        return None

    for key in ("duration", "duration_seconds"):
        value = payload.get(key)
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = 0.0
        if parsed > 0:
            return parsed

    creations = payload.get("creations")
    if isinstance(creations, list):
        for item in creations:
            if not isinstance(item, dict):
                continue
            nested = _extract_duration(item)
            if nested and nested > 0:
                return nested

    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_duration(data)

    return None


def _guess_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def _encode_image_to_data_uri(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{_guess_mime_type(path)};base64,{encoded}"


def _resolve_dimensions_from_aspect_ratio(aspect_ratio: str) -> tuple[int, int]:
    if aspect_ratio == "16:9":
        return 1920, 1080
    if aspect_ratio == "1:1":
        return 1080, 1080
    if aspect_ratio == "4:3":
        return 1440, 1080
    if aspect_ratio == "3:4":
        return 1080, 1440
    if aspect_ratio == "3:2":
        return 1620, 1080
    if aspect_ratio == "2:3":
        return 1080, 1620
    if aspect_ratio == "21:9":
        return 2520, 1080
    return 1080, 1920


def _resolve_dimensions_from_image(path: Path | None) -> tuple[int, int] | None:
    if path is None or not path.exists():
        return None
    try:
        with Image.open(path) as image:
            width, height = image.size
        if width > 0 and height > 0:
            return int(width), int(height)
    except Exception:
        return None
    return None


class ViduVideoProvider(VideoProvider):
    name = "vidu"

    def __init__(
        self,
        api_key: str = "",
        base_url: str = DEFAULT_VIDU_BASE_URL,
        model: str = DEFAULT_VIDU_VIDEO_MODEL,
        aspect_ratio: str = "9:16",
        resolution: str | None = None,
        poll_interval: float = 3.0,
        max_wait_time: float = 1800.0,
        request_timeout: float = 60.0,
    ) -> None:
        self.api_key = _normalize_api_key(api_key)
        self.base_url = _normalize_base_url(base_url)
        self.model = _normalize_model(model)
        self._preset = get_vidu_video_preset(self.model)
        self.aspect_ratio = _normalize_aspect_ratio(aspect_ratio, model=self.model)
        self.resolution = _normalize_resolution(resolution, model=self.model)
        self.poll_interval = max(float(poll_interval or 3.0), 0.5)
        self.max_wait_time = max(float(max_wait_time or 1800.0), self.poll_interval)
        self.request_timeout = max(float(request_timeout or 60.0), 15.0)

    def _validate_config(self) -> None:
        if not self.api_key:
            raise ValueError("Vidu 视频生成需要配置 API Key")

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _query_task(self, client: httpx.AsyncClient, task_id: str) -> dict[str, Any]:
        response = await client.get(
            f"{self.base_url}/ent/v2/tasks/{task_id}/creations",
            headers=self._build_headers(),
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Vidu 视频查询任务失败: {_extract_http_error_message(response)}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Vidu 视频查询响应结构异常: {payload}")
        return payload

    @staticmethod
    async def _download_video(client: httpx.AsyncClient, video_url: str, output_path: Path) -> None:
        response = await client.get(video_url, follow_redirects=True)
        response.raise_for_status()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)

    @staticmethod
    async def _emit_progress(
        callback: Callable[[int], Awaitable[None]] | None,
        value: int,
    ) -> None:
        if callback is None:
            return
        await callback(max(0, min(100, int(value))))

    @staticmethod
    async def _emit_status(
        callback: Callable[[str], Awaitable[None]] | None,
        message: str,
    ) -> None:
        if callback is None:
            return
        await callback(str(message or "").strip())

    async def generate(
        self,
        prompt: str,
        output_path: Path,
        duration: float | None = None,
        width: int | None = None,
        height: int | None = None,
        fps: int | None = None,
        resolution: int | None = None,
        aspect_ratio: str | None = None,
        first_frame: Path | None = None,
        last_frame: Path | None = None,
        reference_images: list[Path] | None = None,
        progress_callback: Callable[[int], Awaitable[None]] | None = None,
        status_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> VideoResult:
        del width, height, fps
        self._validate_config()

        content = str(prompt or "").strip()
        if not content:
            raise ValueError("提示词为空，无法生成视频")
        if reference_images:
            raise ValueError("Vidu 暂不支持参考图模式（reference_images）")

        use_i2v = first_frame is not None and first_frame.exists()
        use_start_end = use_i2v and last_frame is not None and last_frame.exists()

        if use_start_end:
            endpoint = "/ent/v2/start-end2video"
        elif use_i2v:
            endpoint = "/ent/v2/img2video"
        else:
            endpoint = "/ent/v2/text2video"

        resolved_model = _normalize_model(self.model)
        resolved_duration = _normalize_duration(
            duration,
            model=self.model,
            default=int(self._preset.get("default_duration") or 5),
        )
        resolved_aspect_ratio = _normalize_aspect_ratio(
            aspect_ratio or self.aspect_ratio,
            model=self.model,
            default=str(self._preset.get("default_aspect_ratio") or "9:16"),
        )
        resolved_resolution = _normalize_resolution(
            resolution if resolution is not None else self.resolution,
            model=self.model,
        )

        request_payload: dict[str, Any] = {
            "model": resolved_model,
            "prompt": content,
            "duration": resolved_duration,
            "audio": False,
        }
        if resolved_resolution:
            request_payload["resolution"] = resolved_resolution

        if use_start_end:
            request_payload["images"] = [
                _encode_image_to_data_uri(first_frame),
                _encode_image_to_data_uri(last_frame),
            ]
        elif use_i2v:
            request_payload["images"] = [_encode_image_to_data_uri(first_frame)]
        else:
            request_payload["aspect_ratio"] = resolved_aspect_ratio

        await self._emit_status(status_callback, "提交任务中")
        await self._emit_progress(progress_callback, 5)

        timeout = httpx.Timeout(self.request_timeout, connect=20.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=True) as client:
            response = await client.post(
                f"{self.base_url}{endpoint}",
                headers=self._build_headers(),
                json=request_payload,
            )
            if response.status_code >= 400:
                raise RuntimeError(f"Vidu 视频请求失败: {_extract_http_error_message(response)}")

            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError(f"Vidu 视频响应结构异常: {payload}")

            task_id = _extract_task_id(payload)
            state = _extract_state(payload)
            video_url = _extract_video_url(payload)
            duration_hint = _extract_duration(payload)

            if not task_id and not video_url:
                raise RuntimeError(f"Vidu 视频响应缺少 task_id 与下载地址: {payload}")

            await self._emit_status(status_callback, "排队处理中")
            await self._emit_progress(progress_callback, 15)

            poll_count = 0
            deadline = time.monotonic() + self.max_wait_time
            while not video_url and task_id and time.monotonic() <= deadline:
                if state in TERMINAL_FAILED_STATUSES:
                    message = _extract_error_message(payload)
                    raise RuntimeError(f"Vidu 视频任务失败: {message or state}")
                if state in TERMINAL_SUCCESS_STATUSES and video_url:
                    break

                await asyncio.sleep(self.poll_interval)
                payload = await self._query_task(client, task_id)
                state = _extract_state(payload)
                video_url = _extract_video_url(payload)
                duration_hint = _extract_duration(payload) or duration_hint
                poll_count += 1
                await self._emit_progress(progress_callback, min(15 + poll_count * 5, 90))
                await self._emit_status(status_callback, "生成中")

            if not video_url:
                message = _extract_error_message(payload)
                raise RuntimeError(
                    f"Vidu 视频任务未返回结果(state={state or 'unknown'}): {message}"
                )

            await self._download_video(client, video_url, output_path)

        await self._emit_progress(progress_callback, 100)
        await self._emit_status(status_callback, "下载完成")

        duration_seconds = float(duration_hint or resolved_duration)
        dimensions = _resolve_dimensions_from_image(first_frame if use_i2v else None)
        if dimensions is None:
            dimensions = _resolve_dimensions_from_aspect_ratio(resolved_aspect_ratio)

        return VideoResult(
            file_path=output_path,
            duration=duration_seconds,
            width=int(dimensions[0]),
            height=int(dimensions[1]),
            fps=24,
        )
