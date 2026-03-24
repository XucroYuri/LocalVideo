"""Vidu image generation provider (t2i / i2i)."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from PIL import Image

from app.providers.base.image import ImageProvider, ImageResult

logger = logging.getLogger(__name__)

DEFAULT_VIDU_BASE_URL = "https://api.vidu.cn"
DEFAULT_VIDU_IMAGE_MODEL = "viduq2"
SUPPORTED_ASPECT_RATIOS = {
    "16:9",
    "9:16",
    "1:1",
    "3:4",
    "4:3",
    "21:9",
    "2:3",
    "3:2",
    "auto",
}
SUPPORTED_RESOLUTIONS = {"1080p", "2k", "4k"}
TERMINAL_SUCCESS_STATUSES = {"succeed", "success", "succeeded", "completed", "finished"}
TERMINAL_FAILED_STATUSES = {"failed", "error", "cancelled", "canceled", "rejected"}
MAX_REFERENCE_IMAGES = 7


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


def _normalize_aspect_ratio(
    value: Any, default: str = "9:16", *, has_reference: bool = False
) -> str:
    normalized = str(value or default).strip().lower().replace("：", ":")
    if normalized == "auto" and has_reference:
        return "auto"
    if normalized in SUPPORTED_ASPECT_RATIOS and normalized != "auto":
        return normalized
    return default


def _normalize_resolution(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    if normalized in SUPPORTED_RESOLUTIONS:
        return normalized.upper() if normalized.endswith("k") else normalized
    if normalized in {"1k", "1024", "1080"}:
        return "1080p"
    if normalized in {"2k", "2048"}:
        return "2K"
    if normalized in {"4k", "4096"}:
        return "4K"
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


def _extract_image_url(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""

    creations = payload.get("creations")
    if isinstance(creations, list):
        for item in creations:
            if not isinstance(item, dict):
                continue
            for key in ("url", "watermarked_url", "image_url"):
                value = str(item.get(key) or "").strip()
                if value:
                    return value

    for key in ("url", "image_url", "file_url"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value

    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_image_url(data)

    return ""


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


class ViduImageProvider(ImageProvider):
    name = "vidu"
    supports_reference = True

    def __init__(
        self,
        api_key: str = "",
        base_url: str = DEFAULT_VIDU_BASE_URL,
        model: str = DEFAULT_VIDU_IMAGE_MODEL,
        aspect_ratio: str = "9:16",
        resolution: str | None = None,
        timeout: float = 300.0,
        poll_interval: float = 2.0,
        max_wait_time: float = 600.0,
    ) -> None:
        self.api_key = _normalize_api_key(api_key)
        self.base_url = _normalize_base_url(base_url)
        self.model = str(model or DEFAULT_VIDU_IMAGE_MODEL).strip() or DEFAULT_VIDU_IMAGE_MODEL
        self.aspect_ratio = str(aspect_ratio or "9:16").strip() or "9:16"
        self.resolution = _normalize_resolution(resolution)
        self.timeout = max(float(timeout or 300.0), 30.0)
        self.poll_interval = max(float(poll_interval or 2.0), 0.5)
        self.max_wait_time = max(float(max_wait_time or 600.0), self.poll_interval)

    def _validate_config(self) -> None:
        if not self.api_key:
            raise ValueError("Vidu 图像生成需要配置 API Key")

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
            raise RuntimeError(f"Vidu 图像查询任务失败: {_extract_http_error_message(response)}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Vidu 图像查询响应结构异常: {payload}")
        return payload

    @staticmethod
    async def _download_image(
        client: httpx.AsyncClient, image_url: str, output_path: Path
    ) -> bytes:
        response = await client.get(image_url, follow_redirects=True)
        response.raise_for_status()
        image_bytes = response.content
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_bytes)
        return image_bytes

    @staticmethod
    def _resolve_dimensions(output_path: Path) -> tuple[int, int]:
        try:
            with Image.open(output_path) as image:
                width, height = image.size
            return int(width), int(height)
        except Exception:
            return 0, 0

    async def generate(
        self,
        prompt: str,
        output_path: Path,
        width: int | None = None,
        height: int | None = None,
        reference_images: list[Path] | None = None,
        aspect_ratio: str | None = None,
        image_size: str | None = None,
        progress_callback=None,
    ) -> ImageResult:
        del width, height, progress_callback
        self._validate_config()
        content = str(prompt or "").strip()
        if not content:
            raise ValueError("提示词为空，无法生成图像")

        valid_references: list[Path] = []
        if isinstance(reference_images, list):
            for image_path in reference_images:
                if isinstance(image_path, Path) and image_path.exists():
                    valid_references.append(image_path)
                    if len(valid_references) >= MAX_REFERENCE_IMAGES:
                        break

        resolved_aspect_ratio = _normalize_aspect_ratio(
            aspect_ratio or self.aspect_ratio,
            default=self.aspect_ratio,
            has_reference=bool(valid_references),
        )
        resolved_resolution = _normalize_resolution(image_size or self.resolution)

        request_payload: dict[str, Any] = {
            "model": str(self.model or DEFAULT_VIDU_IMAGE_MODEL).strip()
            or DEFAULT_VIDU_IMAGE_MODEL,
            "prompt": content,
            "aspect_ratio": resolved_aspect_ratio,
        }
        if resolved_resolution:
            request_payload["resolution"] = resolved_resolution
        if valid_references:
            request_payload["images"] = [
                _encode_image_to_data_uri(path) for path in valid_references
            ]

        timeout = httpx.Timeout(self.timeout, connect=20.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=True) as client:
            response = await client.post(
                f"{self.base_url}/ent/v2/reference2image",
                headers=self._build_headers(),
                json=request_payload,
            )
            if response.status_code >= 400:
                raise RuntimeError(f"Vidu 图像请求失败: {_extract_http_error_message(response)}")

            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError(f"Vidu 图像响应结构异常: {payload}")

            image_url = _extract_image_url(payload)
            state = _extract_state(payload)
            task_id = _extract_task_id(payload)
            if not image_url and task_id:
                deadline = time.monotonic() + self.max_wait_time
                while time.monotonic() <= deadline:
                    if state in TERMINAL_FAILED_STATUSES:
                        message = _extract_error_message(payload)
                        raise RuntimeError(f"Vidu 图像任务失败: {message or state}")
                    if state in TERMINAL_SUCCESS_STATUSES and image_url:
                        break
                    await asyncio.sleep(self.poll_interval)
                    task_payload = await self._query_task(client, task_id)
                    state = _extract_state(task_payload)
                    image_url = _extract_image_url(task_payload)
                    if state in TERMINAL_SUCCESS_STATUSES and image_url:
                        break

            if not image_url:
                raise RuntimeError("Vidu 图像任务未返回可下载结果")

            await self._download_image(client, image_url, output_path)

        width_value, height_value = self._resolve_dimensions(output_path)
        return ImageResult(
            file_path=output_path,
            width=width_value,
            height=height_value,
        )
