"""MiniMax image generation provider."""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from PIL import Image

from app.providers.base.image import ImageProvider, ImageResult

logger = logging.getLogger(__name__)

TERMINAL_SUCCESS_CODE = 0
MAX_REFERENCE_IMAGES = 4
DEFAULT_MINIMAX_BASE_URL = "https://api.minimaxi.com/v1"
DEFAULT_MINIMAX_IMAGE_MODEL = "image-01"
MINIMAX_IMAGE_MODEL_OPTIONS = ["image-01", "image-01-live"]
MINIMAX_IMAGE_ASPECT_RATIOS = ["1:1", "16:9", "4:3", "3:2", "2:3", "3:4", "9:16", "21:9"]


def normalize_minimax_api_key(raw_api_key: str | None) -> str:
    value = str(raw_api_key or "").strip().strip("\"'").strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    return value


def normalize_minimax_base_url(raw_base_url: str | None) -> str:
    normalized = str(raw_base_url or DEFAULT_MINIMAX_BASE_URL).strip().rstrip("/")
    parsed = urlparse(normalized)
    if not parsed.scheme or not parsed.netloc:
        return DEFAULT_MINIMAX_BASE_URL
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/v1"):
        return normalized
    if path:
        return f"{normalized}/v1"
    return f"{normalized}/v1"


def normalize_minimax_image_model(value: Any, default: str = DEFAULT_MINIMAX_IMAGE_MODEL) -> str:
    normalized = str(value or default).strip() or default
    return normalized if normalized in MINIMAX_IMAGE_MODEL_OPTIONS else default


def normalize_minimax_image_aspect_ratio(
    value: Any,
    *,
    model: str | None = None,
    default: str = "1:1",
) -> str:
    normalized_model = normalize_minimax_image_model(model, DEFAULT_MINIMAX_IMAGE_MODEL)
    normalized = str(value or default).strip().replace("：", ":")
    allowed = (
        [ratio for ratio in MINIMAX_IMAGE_ASPECT_RATIOS if ratio != "21:9"]
        if normalized_model == "image-01-live"
        else MINIMAX_IMAGE_ASPECT_RATIOS
    )
    if normalized in allowed:
        return normalized
    fallback = str(default or "1:1").strip().replace("：", ":")
    return fallback if fallback in allowed else allowed[0]


def normalize_minimax_image_size(value: Any, default: str = "2K") -> str:
    normalized = str(value or default).strip().upper()
    if normalized in {"1K", "2K", "4K"}:
        return normalized
    fallback = str(default or "2K").strip().upper()
    return fallback if fallback in {"1K", "2K", "4K"} else "2K"


def _extract_error_message(payload: Any) -> str:
    if isinstance(payload, dict):
        base_resp = payload.get("base_resp")
        if isinstance(base_resp, dict):
            message = str(base_resp.get("status_msg") or "").strip()
            if message:
                return message
        for key in ("message", "msg", "error", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
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


def _is_success_payload(payload: dict[str, Any]) -> bool:
    base_resp = payload.get("base_resp")
    if isinstance(base_resp, dict):
        try:
            raw_status_code = base_resp.get("status_code")
            if raw_status_code is None:
                return False
            return int(raw_status_code) == TERMINAL_SUCCESS_CODE
        except (TypeError, ValueError):
            return False
    return True


def _extract_image_urls(payload: dict[str, Any]) -> list[str]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    urls = data.get("image_urls")
    if not isinstance(urls, list):
        return []
    return [str(item).strip() for item in urls if str(item).strip()]


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


class MiniMaxImageProvider(ImageProvider):
    name = "minimax"
    supports_reference = True

    def __init__(
        self,
        api_key: str = "",
        base_url: str = DEFAULT_MINIMAX_BASE_URL,
        model: str = DEFAULT_MINIMAX_IMAGE_MODEL,
        aspect_ratio: str = "1:1",
        timeout: float = 180.0,
    ) -> None:
        self.api_key = normalize_minimax_api_key(api_key)
        self.base_url = normalize_minimax_base_url(base_url)
        self.model = normalize_minimax_image_model(model)
        self.aspect_ratio = normalize_minimax_image_aspect_ratio(
            aspect_ratio,
            model=self.model,
            default="1:1",
        )
        self.timeout = max(float(timeout or 180.0), 30.0)

    def _validate_config(self) -> None:
        if not self.api_key:
            raise ValueError("MiniMax 图像生成需要配置 API Key")

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @staticmethod
    async def _download_image(
        client: httpx.AsyncClient,
        image_url: str,
        output_path: Path,
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
        del width, height, image_size, progress_callback
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

        resolved_model = normalize_minimax_image_model(self.model)
        resolved_aspect_ratio = normalize_minimax_image_aspect_ratio(
            aspect_ratio or self.aspect_ratio,
            model=resolved_model,
            default=self.aspect_ratio,
        )

        request_payload: dict[str, Any] = {
            "model": resolved_model,
            "prompt": content,
            "aspect_ratio": resolved_aspect_ratio,
            "response_format": "url",
        }
        if valid_references:
            request_payload["subject_reference"] = [
                {
                    "type": "character",
                    "image_file": _encode_image_to_data_uri(path),
                }
                for path in valid_references
            ]

        timeout = httpx.Timeout(self.timeout, connect=20.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=True) as client:
            response = await client.post(
                f"{self.base_url}/image_generation",
                headers=self._build_headers(),
                json=request_payload,
            )
            if response.status_code >= 400:
                raise RuntimeError(f"MiniMax 图像请求失败: {_extract_http_error_message(response)}")
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError(f"MiniMax 图像响应结构异常: {payload}")
            if not _is_success_payload(payload):
                message = _extract_error_message(payload)
                raise RuntimeError(f"MiniMax 图像生成失败: {message or payload}")

            image_urls = _extract_image_urls(payload)
            if not image_urls:
                raise RuntimeError(f"MiniMax 图像响应缺少 image_urls: {payload}")

            await self._download_image(client, image_urls[0], output_path)

        width_px, height_px = self._resolve_dimensions(output_path)
        return ImageResult(file_path=output_path, width=width_px, height=height_px)
