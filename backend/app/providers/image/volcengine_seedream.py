"""Volcengine Seedream image provider."""

import asyncio
import base64
import logging
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
from PIL import Image

from app.providers.base.image import ImageProvider, ImageResult

SUPPORTED_ASPECT_RATIOS = ["1:1", "2:3", "3:2", "3:4", "4:3", "9:16", "16:9", "21:9"]
SUPPORTED_IMAGE_SIZES = ["1K", "2K", "4K"]

MODEL_NAME_ALIASES = {
    "doubao-seedream-4.0": "doubao-seedream-4-0-250828",
    "doubao-seedream-4.5": "doubao-seedream-4-5-251128",
    "doubao-seedream-5.0": "doubao-seedream-5-0-260128",
}

MODEL_IMAGE_SIZE_LIMITS = {
    "doubao-seedream-5.0": {"2K", "4K"},
    "doubao-seedream-4.5": {"2K", "4K"},
    "doubao-seedream-4.0": {"1K", "2K", "4K"},
}
MAX_REFERENCE_IMAGES = 14

DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}
SEEDREAM_SIZE_MAP = {
    "1K": {
        "1:1": "1024x1024",
        "4:3": "1152x864",
        "3:4": "864x1152",
        "16:9": "1280x720",
        "9:16": "720x1280",
        "3:2": "1248x832",
        "2:3": "832x1248",
        "21:9": "1512x648",
    },
    "2K": {
        "1:1": "2048x2048",
        "4:3": "2304x1728",
        "3:4": "1728x2304",
        "16:9": "2560x1440",
        "9:16": "1440x2560",
        "3:2": "2496x1664",
        "2:3": "1664x2496",
        "21:9": "3024x1296",
    },
    "4K": {
        "1:1": "4096x4096",
        "4:3": "4704x3520",
        "3:4": "3520x4704",
        "16:9": "5504x3040",
        "9:16": "3040x5504",
        "3:2": "4992x3328",
        "2:3": "3328x4992",
        "21:9": "6240x2656",
    },
}

logger = logging.getLogger(__name__)


def _get_mime_type(path: Path) -> str:
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    return mime_map.get(path.suffix.lower(), "image/png")


def _normalize_api_key(raw_api_key: str | None) -> str:
    value = str(raw_api_key or "").strip().strip("\"'").strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    return value


def _normalize_base_url(raw_base_url: str | None) -> str:
    raw = (raw_base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    if not raw:
        return DEFAULT_BASE_URL

    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return DEFAULT_BASE_URL

    scheme = parsed.scheme
    host = parsed.netloc
    path = (parsed.path or "").rstrip("/")
    lower_host = host.lower()

    # Normalize LAS endpoint to Ark endpoint.
    if lower_host.startswith("operator.las.") and lower_host.endswith(".volces.com"):
        host = f"ark.{host[len('operator.las.') :]}"

    if path.endswith("/api/v1/online"):
        normalized_path = "/api/v3"
    elif path.endswith("/api/v3"):
        normalized_path = "/api/v3"
    elif path.endswith("/api/v1"):
        normalized_path = "/api/v3"
    elif path.endswith("/api"):
        normalized_path = "/api/v3"
    elif path == "/v3":
        normalized_path = "/api/v3"
    elif path == "/v1":
        normalized_path = "/api/v3"
    elif not path:
        normalized_path = "/api/v3"
    else:
        normalized_path = path

    return urlunparse((scheme, host, normalized_path, "", "", "")).rstrip("/")


def _build_endpoint_candidates(base_url: str) -> list[str]:
    base = base_url.rstrip("/")
    if base.endswith("/api/v3"):
        return [f"{base}/images/generations"]
    if base.endswith("/api/v1"):
        return [
            f"{base}/images/generations",
            f"{base}/online/images/generations",
        ]
    if base.endswith("/api/v1/online"):
        root = base[: -len("/online")]
        return [
            f"{root}/images/generations",
            f"{root}/online/images/generations",
        ]
    return [f"{base}/images/generations"]


def _format_http_status_error(exc: httpx.HTTPStatusError) -> str:
    status = exc.response.status_code
    body_text = ""
    try:
        payload = exc.response.json()
        if isinstance(payload, str):
            body_text = payload
        else:
            body_text = str(payload)
    except Exception:
        body_text = str(exc.response.text or "").strip()
    body_text = body_text[:600]
    if body_text:
        return f"HTTP {status}: {body_text}"
    return f"HTTP {status}: {exc}"


def _resolve_image_size_by_model(model: str, image_size: str) -> str:
    normalized_model = model.strip()
    allowed = MODEL_IMAGE_SIZE_LIMITS.get(normalized_model)
    if not allowed:
        return image_size if image_size in SUPPORTED_IMAGE_SIZES else "2K"
    if image_size in allowed:
        return image_size
    if "2K" in allowed:
        return "2K"
    return sorted(allowed)[0]


def _parse_aspect_ratio(value: str) -> tuple[int, int] | None:
    text = str(value or "").strip()
    if ":" not in text:
        return None
    left, right = text.split(":", maxsplit=1)
    try:
        width_ratio = int(left)
        height_ratio = int(right)
    except ValueError:
        return None
    if width_ratio <= 0 or height_ratio <= 0:
        return None
    return width_ratio, height_ratio


def _aspect_ratio_value(value: str) -> float | None:
    pair = _parse_aspect_ratio(value)
    if not pair:
        return None
    width_ratio, height_ratio = pair
    return float(width_ratio) / float(height_ratio)


def _resolve_payload_size(aspect_ratio: str, image_size: str) -> str:
    size_key = str(image_size or "").strip()
    ratio_key = str(aspect_ratio or "").strip().replace(" ", "")
    by_size = SEEDREAM_SIZE_MAP.get(size_key)
    if not by_size:
        return image_size
    return by_size.get(ratio_key, image_size)


class VolcengineSeedreamImageProvider(ImageProvider):
    """Volcengine Seedream image generation provider."""

    name = "volcengine_seedream"
    supports_reference = True

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = "",
        model: str = "doubao-seedream-5.0",
        aspect_ratio: str = "9:16",
        image_size: str = "2K",
        timeout: float = 300.0,
        max_retries: int = 3,
        retry_interval: int = 2,
        sequential_image_generation: str = "disabled",
        response_format: str = "b64_json",
        stream: bool = False,
        watermark: bool = False,
    ) -> None:
        self.base_url = _normalize_base_url(base_url)
        self.api_key = _normalize_api_key(api_key)
        self.model = model.strip() or "doubao-seedream-5.0"
        self.aspect_ratio = aspect_ratio if aspect_ratio in SUPPORTED_ASPECT_RATIOS else "9:16"
        self.image_size = image_size if image_size in SUPPORTED_IMAGE_SIZES else "2K"
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.retry_interval = max(1, retry_interval)
        self.sequential_image_generation = (
            sequential_image_generation
            if sequential_image_generation in {"enabled", "disabled"}
            else "disabled"
        )
        self.response_format = (
            response_format if response_format in {"url", "b64_json"} else "b64_json"
        )
        self.stream = bool(stream)
        self.watermark = bool(watermark)

    def _validate_config(self) -> None:
        if not self.api_key:
            raise ValueError("Volcengine Seedream 需要配置 API Key。")
        if not self.base_url:
            raise ValueError("Volcengine Seedream 需要配置 Base URL。")

    def _resolve_model(self) -> str:
        return MODEL_NAME_ALIASES.get(self.model, self.model)

    def _build_payload(
        self,
        prompt: str,
        aspect_ratio: str,
        image_size: str,
        reference_images: list[Path] | None = None,
        sequential_image_generation: str | None = None,
        response_format: str | None = None,
        stream: bool | None = None,
        watermark: bool | None = None,
    ) -> dict[str, Any]:
        resolved_sequential = (
            sequential_image_generation
            if sequential_image_generation in {"enabled", "disabled"}
            else self.sequential_image_generation
        )
        resolved_response_format = (
            response_format if response_format in {"url", "b64_json"} else self.response_format
        )
        resolved_stream = self.stream if stream is None else bool(stream)
        resolved_watermark = self.watermark if watermark is None else bool(watermark)
        payload_size = _resolve_payload_size(aspect_ratio, image_size)

        payload: dict[str, Any] = {
            "model": self._resolve_model(),
            "prompt": prompt,
            "size": payload_size,
            "response_format": resolved_response_format,
            "sequential_image_generation": resolved_sequential,
            "stream": resolved_stream,
            "watermark": resolved_watermark,
        }

        if reference_images:
            encoded_images: list[str] = []
            for image_path in reference_images:
                if not image_path.exists():
                    continue
                mime_type = _get_mime_type(image_path)
                encoded = base64.b64encode(image_path.read_bytes()).decode("utf-8")
                encoded_images.append(f"data:{mime_type};base64,{encoded}")
            if encoded_images:
                encoded_images = encoded_images[:MAX_REFERENCE_IMAGES]
                payload["image"] = encoded_images[0] if len(encoded_images) == 1 else encoded_images

        return payload

    async def _extract_image_bytes(
        self,
        client: httpx.AsyncClient,
        data_item: dict[str, Any],
    ) -> bytes:
        b64_json = data_item.get("b64_json")
        if isinstance(b64_json, str) and b64_json.strip():
            return base64.b64decode(b64_json)

        image_url = data_item.get("url")
        if isinstance(image_url, str) and image_url.strip():
            response = await client.get(image_url)
            response.raise_for_status()
            return response.content

        raise ValueError("响应中未找到可用图像数据（b64_json/url）。")

    async def generate(
        self,
        prompt: str,
        output_path: Path,
        width: int | None = None,
        height: int | None = None,
        reference_images: list[Path] | None = None,
        aspect_ratio: str | None = None,
        image_size: str | None = None,
        sequential_image_generation: str | None = None,
        response_format: str | None = None,
        stream: bool | None = None,
        watermark: bool | None = None,
        progress_callback=None,
        **kwargs,
    ) -> ImageResult:
        self._validate_config()

        resolved_aspect_ratio = (
            aspect_ratio if aspect_ratio in SUPPORTED_ASPECT_RATIOS else self.aspect_ratio
        )
        raw_image_size = image_size if image_size in SUPPORTED_IMAGE_SIZES else self.image_size
        resolved_image_size = _resolve_image_size_by_model(self.model, raw_image_size)
        resolved_ref_images = reference_images
        payload = self._build_payload(
            prompt=prompt,
            aspect_ratio=resolved_aspect_ratio,
            image_size=resolved_image_size,
            reference_images=resolved_ref_images,
            sequential_image_generation=sequential_image_generation,
            response_format=response_format,
            stream=stream,
            watermark=watermark,
        )
        logger.info(
            "[Seedream Image] model=%s aspect_ratio=%s image_size=%s payload_size=%s reference_count=%d",
            self.model,
            resolved_aspect_ratio,
            resolved_image_size,
            payload.get("size"),
            len(resolved_ref_images or []),
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        endpoint_candidates = _build_endpoint_candidates(self.base_url)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        timeout = httpx.Timeout(self.timeout, connect=20.0)

        if progress_callback:
            try:
                await progress_callback(1)
            except Exception:
                pass

        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=timeout) as client:
            for endpoint in endpoint_candidates:
                for attempt in range(self.max_retries):
                    try:
                        response = await client.post(endpoint, headers=headers, json=payload)
                        if response.status_code >= 400:
                            if (
                                response.status_code in RETRYABLE_STATUS_CODES
                                and attempt < self.max_retries - 1
                            ):
                                await asyncio.sleep(self.retry_interval * (2**attempt))
                                continue
                            response.raise_for_status()

                        data = response.json()
                        data_items = data.get("data")
                        if not isinstance(data_items, list) or len(data_items) == 0:
                            raise ValueError("Volcengine Seedream 响应缺少 data。")
                        first_item = data_items[0]
                        if not isinstance(first_item, dict):
                            raise ValueError("Volcengine Seedream 响应 data[0] 格式错误。")

                        image_bytes = await self._extract_image_bytes(client, first_item)
                        image = Image.open(BytesIO(image_bytes))
                        image.save(output_path)
                        actual_width, actual_height = image.size
                        target_ratio = _aspect_ratio_value(resolved_aspect_ratio)
                        if target_ratio and actual_height > 0:
                            actual_ratio = float(actual_width) / float(actual_height)
                            if abs(actual_ratio - target_ratio) > 0.03:
                                logger.warning(
                                    "[Seedream Image] output ratio mismatch: target=%s actual=%dx%d",
                                    resolved_aspect_ratio,
                                    actual_width,
                                    actual_height,
                                )

                        if progress_callback:
                            try:
                                await progress_callback(100)
                            except Exception:
                                pass

                        return ImageResult(
                            file_path=output_path,
                            width=actual_width,
                            height=actual_height,
                        )
                    except httpx.HTTPStatusError as exc:
                        last_error = exc
                        status_code = exc.response.status_code
                        if status_code == 404:
                            # Endpoint mismatch: try next candidate endpoint.
                            break
                        if status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries - 1:
                            await asyncio.sleep(self.retry_interval * (2**attempt))
                            continue
                        raise RuntimeError(_format_http_status_error(exc)) from exc
                    except Exception as exc:
                        last_error = exc
                        if attempt < self.max_retries - 1:
                            await asyncio.sleep(self.retry_interval * (2**attempt))
                            continue
                        break

        raise RuntimeError(f"Volcengine Seedream 图像生成失败: {last_error}")
