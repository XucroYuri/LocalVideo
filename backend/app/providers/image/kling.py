"""Kling image generation provider (t2i / i2i)."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from app.providers.base.image import ImageProvider, ImageResult
from app.providers.kling_auth import (
    build_kling_auth_headers,
    is_kling_configured,
    normalize_kling_access_key,
    normalize_kling_base_url,
    normalize_kling_secret_key,
)

logger = logging.getLogger(__name__)

DEFAULT_KLING_BASE_URL = "https://api-beijing.klingai.com"
SUPPORTED_KLING_IMAGE_MODELS = {
    "kling-v3",
    "kling-v3-omni",
}
SUPPORTED_ASPECT_RATIOS = {
    "1:1",
    "16:9",
    "4:3",
    "3:2",
    "2:3",
    "3:4",
    "9:16",
    "21:9",
}
AUTO_ASPECT_RATIO_SUPPORTED_MODELS = {"kling-v3", "kling-v3-omni"}
SUPPORTED_IMAGE_SIZES_BY_MODEL = {
    "kling-v3": {"1K", "2K", "4K"},
    "kling-v3-omni": {"1K", "2K"},
}
TERMINAL_SUCCESS_STATUSES = {"succeed", "success", "succeeded", "completed", "finished"}
TERMINAL_FAILED_STATUSES = {"failed", "error", "cancelled", "canceled", "rejected"}


def _normalize_base_url(raw_base_url: str | None) -> str:
    return normalize_kling_base_url(raw_base_url or DEFAULT_KLING_BASE_URL)


def _normalize_model(model: str | None) -> str:
    normalized = str(model or "").strip()
    if not normalized:
        return "kling-v3"
    return normalized


def _normalize_aspect_ratio(
    value: Any,
    *,
    model: str,
    has_reference_image: bool,
    default: str = "9:16",
) -> str:
    normalized = str(value or "").strip().lower().replace("：", ":")
    if normalized == "auto":
        if model in AUTO_ASPECT_RATIO_SUPPORTED_MODELS:
            return "auto"
        if has_reference_image and model == "kling-image-o1":
            return "auto"
    if normalized in SUPPORTED_ASPECT_RATIOS:
        return normalized
    return default


def _normalize_image_size(
    value: Any,
    *,
    model: str,
    default: str = "1K",
) -> str:
    normalized = str(value or "").strip().upper()
    allowed = SUPPORTED_IMAGE_SIZES_BY_MODEL.get(model, {"1K", "2K", "4K"})
    if normalized in allowed:
        return normalized
    normalized_default = str(default or "1K").strip().upper()
    if normalized_default in allowed:
        return normalized_default
    return sorted(allowed)[0]


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


def _extract_task_images(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    task_result = data.get("task_result")
    if not isinstance(task_result, dict):
        return []
    images = task_result.get("images")
    if not isinstance(images, list):
        return []
    return [item for item in images if isinstance(item, dict)]


def _encode_image_to_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


class KlingImageProvider(ImageProvider):
    """Kling image generation provider."""

    name = "kling"
    supports_reference = True

    def __init__(
        self,
        access_key: str = "",
        secret_key: str = "",
        base_url: str = DEFAULT_KLING_BASE_URL,
        model: str = "kling-v3",
        aspect_ratio: str = "9:16",
        image_size: str = "1K",
        timeout: float = 300.0,
        poll_interval: float = 2.0,
        max_wait_time: float = 600.0,
    ) -> None:
        self.access_key = normalize_kling_access_key(access_key)
        self.secret_key = normalize_kling_secret_key(secret_key)
        self.base_url = _normalize_base_url(base_url)
        self.model = _normalize_model(model)
        self.aspect_ratio = str(aspect_ratio or "9:16").strip() or "9:16"
        self.image_size = str(image_size or "1K").strip().upper() or "1K"
        self.timeout = max(float(timeout or 300.0), 30.0)
        self.poll_interval = max(float(poll_interval or 2.0), 0.5)
        self.max_wait_time = max(float(max_wait_time or 600.0), self.poll_interval)

    def _validate_config(self) -> None:
        if not is_kling_configured(
            access_key=self.access_key,
            secret_key=self.secret_key,
        ):
            raise ValueError("Kling 图像生成需要配置 Access Key 和 Secret Key")

    def _build_headers(self) -> dict[str, str]:
        return {
            **build_kling_auth_headers(
                access_key=self.access_key,
                secret_key=self.secret_key,
            ),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _query_task(self, client: httpx.AsyncClient, task_id: str) -> dict[str, Any]:
        response = await client.get(
            f"{self.base_url}/v1/images/generations/{task_id}",
            headers=self._build_headers(),
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Kling 图像查询响应结构异常: {payload}")
        code = _coerce_code(payload.get("code"))
        if code != 0:
            message = _extract_payload_error_message(payload) or f"code={code}"
            raise RuntimeError(f"Kling 图像查询任务失败: {message}")
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
        del width, height
        self._validate_config()
        content = str(prompt or "").strip()
        if not content:
            raise ValueError("提示词为空，无法生成图像")

        reference_image: Path | None = None
        if isinstance(reference_images, list):
            for candidate in reference_images:
                if isinstance(candidate, Path) and candidate.exists():
                    reference_image = candidate
                    break

        resolved_model = _normalize_model(self.model)
        if resolved_model not in SUPPORTED_KLING_IMAGE_MODELS:
            logger.warning(
                "[Kling Image] model=%s 不在内置支持列表，按透传模式继续调用",
                resolved_model,
            )

        resolved_aspect_ratio = _normalize_aspect_ratio(
            aspect_ratio or self.aspect_ratio,
            model=resolved_model,
            has_reference_image=reference_image is not None,
            default=self.aspect_ratio,
        )
        resolved_image_size = _normalize_image_size(
            image_size or self.image_size,
            model=resolved_model,
            default=self.image_size,
        )

        request_payload: dict[str, Any] = {
            "model_name": resolved_model,
            "prompt": content,
            "n": 1,
        }
        if resolved_aspect_ratio:
            request_payload["aspect_ratio"] = resolved_aspect_ratio
        if resolved_image_size:
            request_payload["image_size"] = resolved_image_size
        if reference_image is not None:
            request_payload["image"] = _encode_image_to_base64(reference_image)

        if progress_callback is not None:
            await progress_callback(5)

        timeout = httpx.Timeout(self.timeout, connect=20.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=True) as client:
            response = await client.post(
                f"{self.base_url}/v1/images/generations",
                headers=self._build_headers(),
                json=request_payload,
            )
            if response.status_code >= 400:
                raise RuntimeError(f"Kling 图像请求失败: {_extract_http_error_message(response)}")
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError(f"Kling 图像响应结构异常: {payload}")
            code = _coerce_code(payload.get("code"))
            if code != 0:
                message = _extract_payload_error_message(payload) or f"code={code}"
                raise RuntimeError(f"Kling 图像创建任务失败: {message}")

            if progress_callback is not None:
                await progress_callback(20)

            task_id = _extract_task_id(payload)
            if not task_id:
                raise RuntimeError(f"Kling 图像响应缺少 task_id: {payload}")

            task_images = _extract_task_images(payload)
            task_status = _extract_task_status(payload)
            poll_count = 0
            deadline = time.monotonic() + self.max_wait_time
            while (not task_images) and time.monotonic() <= deadline:
                if task_status in TERMINAL_FAILED_STATUSES:
                    message = _extract_payload_error_message(payload)
                    raise RuntimeError(f"Kling 图像任务失败: {message or task_status}")
                if task_status in TERMINAL_SUCCESS_STATUSES:
                    break
                await asyncio.sleep(self.poll_interval)
                payload = await self._query_task(client, task_id)
                task_images = _extract_task_images(payload)
                task_status = _extract_task_status(payload)
                poll_count += 1
                if progress_callback is not None:
                    await progress_callback(min(20 + poll_count * 8, 90))

            if not task_images:
                message = _extract_payload_error_message(payload)
                raise RuntimeError(
                    f"Kling 图像任务未返回结果(status={task_status or 'unknown'}): {message}"
                )

            first_image = task_images[0]
            image_url = str(
                first_image.get("url") or first_image.get("watermark_url") or ""
            ).strip()
            if not image_url:
                raise RuntimeError(f"Kling 图像响应中缺少下载地址: {first_image}")

            await self._download_image(client, image_url, output_path)

        if progress_callback is not None:
            await progress_callback(100)

        image_width, image_height = self._resolve_dimensions(output_path)
        return ImageResult(
            file_path=output_path,
            width=image_width,
            height=image_height,
        )
