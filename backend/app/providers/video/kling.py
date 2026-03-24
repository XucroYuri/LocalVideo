"""Kling video generation provider (Kling-V3)."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from app.providers.base.video import VideoProvider, VideoResult
from app.providers.kling_auth import (
    build_kling_auth_headers,
    is_kling_configured,
    normalize_kling_access_key,
    normalize_kling_base_url,
    normalize_kling_secret_key,
)

logger = logging.getLogger(__name__)

DEFAULT_KLING_BASE_URL = "https://api-beijing.klingai.com"
DEFAULT_KLING_VIDEO_MODEL = "kling-v3"
KLING_VIDEO_MODEL_PRESETS: dict[str, dict[str, Any]] = {
    "kling-v3": {
        "display_name": "Kling V3",
        "description": "Kling V3 视频生成模型",
        "supports_t2v": True,
        "supports_i2v": True,
        "supports_last_frame": True,
        "supports_reference_image": False,
        "supports_combined_reference": False,
        "max_reference_images": 0,
        "aspect_ratios": ["16:9", "9:16", "1:1"],
        "resolutions": ["1080p"],
        "default_aspect_ratio": "9:16",
        "default_resolution": "1080p",
        "supported_durations": list(range(3, 16)),
        "default_duration": 5,
    },
}
SUPPORTED_MODELS = set(KLING_VIDEO_MODEL_PRESETS.keys())
SUPPORTED_ASPECT_RATIOS = {
    ratio
    for preset in KLING_VIDEO_MODEL_PRESETS.values()
    for ratio in preset.get("aspect_ratios", [])
}
TERMINAL_SUCCESS_STATUSES = {"succeed", "success", "succeeded", "completed", "finished"}
TERMINAL_FAILED_STATUSES = {"failed", "error", "cancelled", "canceled", "rejected"}


def _normalize_base_url(raw_base_url: str | None) -> str:
    return normalize_kling_base_url(raw_base_url or DEFAULT_KLING_BASE_URL)


def _normalize_model(model: str | None) -> str:
    normalized = str(model or "").strip()
    if not normalized:
        return DEFAULT_KLING_VIDEO_MODEL
    return normalized if normalized in SUPPORTED_MODELS else DEFAULT_KLING_VIDEO_MODEL


def get_kling_video_preset(model: str | None) -> dict[str, Any]:
    resolved_model = _normalize_model(model)
    preset = (
        KLING_VIDEO_MODEL_PRESETS.get(resolved_model)
        or KLING_VIDEO_MODEL_PRESETS[DEFAULT_KLING_VIDEO_MODEL]
    )
    return dict(preset)


def list_kling_video_presets() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model_id in sorted(KLING_VIDEO_MODEL_PRESETS.keys()):
        preset = get_kling_video_preset(model_id)
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
                "default_resolution": str(preset.get("default_resolution") or ""),
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
    preset = get_kling_video_preset(model)
    fallback = str(default or preset.get("default_aspect_ratio") or "9:16").strip() or "9:16"
    normalized = str(value or fallback).strip().replace("：", ":")
    supported = {
        str(item).strip() for item in preset.get("aspect_ratios") or [] if str(item).strip()
    } or SUPPORTED_ASPECT_RATIOS
    if normalized in supported:
        return normalized
    return fallback


def _resolve_duration_value(
    duration: float | None,
    *,
    model: str | None = None,
    default_seconds: int | None = None,
) -> str:
    preset = get_kling_video_preset(model)
    supported = sorted(
        {
            int(item)
            for item in preset.get("supported_durations") or []
            if isinstance(item, int | float) and int(item) > 0
        }
    )
    fallback = int(default_seconds or preset.get("default_duration") or 5)
    try:
        parsed = float(duration or fallback)
    except (TypeError, ValueError):
        parsed = float(fallback)
    rounded = int(round(max(parsed, 0.0)))
    if supported:
        for candidate in supported:
            if candidate >= rounded:
                return str(candidate)
        return str(supported[-1])
    return str(fallback)


def _coerce_code(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _extract_payload_error_message(payload: dict[str, Any]) -> str:
    message = str(payload.get("message") or payload.get("msg") or "").strip()
    if message:
        return message
    data = payload.get("data")
    if isinstance(data, dict):
        status_message = str(data.get("task_status_msg") or "").strip()
        if status_message:
            return status_message
    return ""


def _extract_http_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            return _extract_payload_error_message(payload) or response.text.strip()
    except Exception:
        pass
    return response.text.strip() or f"HTTP {response.status_code}"


def _extract_task_id(payload: dict[str, Any]) -> str:
    data = payload.get("data")
    if isinstance(data, dict):
        task_id = str(data.get("task_id") or data.get("id") or "").strip()
        if task_id:
            return task_id
    return str(payload.get("task_id") or payload.get("id") or "").strip()


def _extract_task_status(payload: dict[str, Any]) -> str:
    data = payload.get("data")
    if isinstance(data, dict):
        return str(data.get("task_status") or data.get("status") or "").strip().lower()
    return str(payload.get("task_status") or payload.get("status") or "").strip().lower()


def _extract_task_videos(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    task_result = data.get("task_result")
    if not isinstance(task_result, dict):
        return []
    videos = task_result.get("videos")
    if not isinstance(videos, list):
        return []
    return [item for item in videos if isinstance(item, dict)]


def _encode_image_to_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def _resolve_dimensions_from_aspect_ratio(aspect_ratio: str) -> tuple[int, int]:
    if aspect_ratio == "16:9":
        return 1920, 1080
    if aspect_ratio == "1:1":
        return 1080, 1080
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


class KlingVideoProvider(VideoProvider):
    """Kling 视频生成 Provider。"""

    name = "kling"

    def __init__(
        self,
        access_key: str = "",
        secret_key: str = "",
        base_url: str = DEFAULT_KLING_BASE_URL,
        model: str = DEFAULT_KLING_VIDEO_MODEL,
        aspect_ratio: str = "9:16",
        mode: str = "std",
        poll_interval: float = 5.0,
        max_wait_time: float = 1800.0,
        request_timeout: float = 60.0,
    ) -> None:
        self.access_key = normalize_kling_access_key(access_key)
        self.secret_key = normalize_kling_secret_key(secret_key)
        self.base_url = _normalize_base_url(base_url)
        self.model = _normalize_model(model)
        self._preset = get_kling_video_preset(self.model)
        self.aspect_ratio = _normalize_aspect_ratio(aspect_ratio, model=self.model)
        self.mode = "pro" if str(mode or "").strip().lower() == "pro" else "std"
        self.poll_interval = max(float(poll_interval or 5.0), 1.0)
        self.max_wait_time = max(float(max_wait_time or 1800.0), self.poll_interval)
        self.request_timeout = max(float(request_timeout or 60.0), 15.0)

    def _validate_config(self) -> None:
        if not is_kling_configured(
            access_key=self.access_key,
            secret_key=self.secret_key,
        ):
            raise ValueError("Kling 视频生成需要配置 Access Key 和 Secret Key")

    def _build_headers(self) -> dict[str, str]:
        return {
            **build_kling_auth_headers(
                access_key=self.access_key,
                secret_key=self.secret_key,
            ),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _query_task(
        self,
        client: httpx.AsyncClient,
        *,
        endpoint: str,
        task_id: str,
    ) -> dict[str, Any]:
        response = await client.get(
            f"{self.base_url}{endpoint}/{task_id}",
            headers=self._build_headers(),
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Kling 视频查询响应结构异常: {payload}")
        code = _coerce_code(payload.get("code"))
        if code != 0:
            message = _extract_payload_error_message(payload) or f"code={code}"
            raise RuntimeError(f"Kling 视频查询任务失败: {message}")
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
        del width, height, fps, resolution
        self._validate_config()

        content = str(prompt or "").strip()
        if not content:
            raise ValueError("提示词为空，无法生成视频")
        if reference_images:
            raise ValueError("Kling-V3 暂不支持参考图模式（reference_images）")

        use_i2v = first_frame is not None
        endpoint = "/v1/videos/image2video" if use_i2v else "/v1/videos/text2video"
        resolved_aspect_ratio = _normalize_aspect_ratio(
            aspect_ratio or self.aspect_ratio,
            model=self.model,
            default=str(self._preset.get("default_aspect_ratio") or "9:16"),
        )
        resolved_duration = _resolve_duration_value(
            duration,
            model=self.model,
            default_seconds=int(self._preset.get("default_duration") or 5),
        )

        request_payload: dict[str, Any] = {
            "model_name": self.model,
            "prompt": content,
            "duration": resolved_duration,
            "mode": self.mode,
        }
        if use_i2v:
            if first_frame is None or not first_frame.exists():
                raise ValueError("Kling 图生视频需要提供有效的首帧图")
            request_payload["image"] = _encode_image_to_base64(first_frame)
            if last_frame is not None and last_frame.exists():
                request_payload["image_tail"] = _encode_image_to_base64(last_frame)
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
                raise RuntimeError(f"Kling 视频请求失败: {_extract_http_error_message(response)}")
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError(f"Kling 视频响应结构异常: {payload}")
            code = _coerce_code(payload.get("code"))
            if code != 0:
                message = _extract_payload_error_message(payload) or f"code={code}"
                raise RuntimeError(f"Kling 视频创建任务失败: {message}")

            task_id = _extract_task_id(payload)
            if not task_id:
                raise RuntimeError(f"Kling 视频响应缺少 task_id: {payload}")

            await self._emit_progress(progress_callback, 15)
            await self._emit_status(status_callback, "排队处理中")

            task_videos = _extract_task_videos(payload)
            task_status = _extract_task_status(payload)
            poll_count = 0
            deadline = time.monotonic() + self.max_wait_time
            while (not task_videos) and time.monotonic() <= deadline:
                if task_status in TERMINAL_FAILED_STATUSES:
                    message = _extract_payload_error_message(payload)
                    raise RuntimeError(f"Kling 视频任务失败: {message or task_status}")
                if task_status in TERMINAL_SUCCESS_STATUSES:
                    break
                await asyncio.sleep(self.poll_interval)
                payload = await self._query_task(client, endpoint=endpoint, task_id=task_id)
                task_status = _extract_task_status(payload)
                task_videos = _extract_task_videos(payload)
                poll_count += 1
                await self._emit_progress(progress_callback, min(15 + poll_count * 5, 90))
                await self._emit_status(status_callback, "生成中")

            if not task_videos:
                message = _extract_payload_error_message(payload)
                raise RuntimeError(
                    f"Kling 视频任务未返回结果(status={task_status or 'unknown'}): {message}"
                )

            first_video = task_videos[0]
            video_url = str(
                first_video.get("url") or first_video.get("watermark_url") or ""
            ).strip()
            if not video_url:
                raise RuntimeError(f"Kling 视频响应中缺少下载地址: {first_video}")
            await self._download_video(client, video_url, output_path)

        await self._emit_progress(progress_callback, 100)
        await self._emit_status(status_callback, "下载完成")

        duration_seconds = 0.0
        try:
            duration_seconds = float(first_video.get("duration") or 0.0)
        except (TypeError, ValueError):
            duration_seconds = 0.0
        if duration_seconds <= 0:
            duration_seconds = float(resolved_duration)

        dimensions = _resolve_dimensions_from_image(first_frame if use_i2v else None)
        if dimensions is None:
            dimensions = _resolve_dimensions_from_aspect_ratio(resolved_aspect_ratio)

        return VideoResult(
            file_path=output_path,
            duration=float(duration_seconds),
            width=int(dimensions[0]),
            height=int(dimensions[1]),
            fps=24,
        )
