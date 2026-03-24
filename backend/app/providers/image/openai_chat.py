"""
OpenAI Chat Compatible Image Provider

使用 OpenAI Chat Completions 兼容接口生成图像（兼容 Gemini API 风格返回）
"""

import asyncio
import base64
import json
from collections.abc import Awaitable, Callable
from io import BytesIO
from pathlib import Path

from app.providers.base.image import ImageProvider, ImageResult

GEMINI_FLASH_IMAGE_MODEL = "gemini-3.1-flash-image-preview"

BASE_SUPPORTED_ASPECT_RATIOS = [
    "1:1",
    "2:3",
    "3:2",
    "3:4",
    "4:3",
    "4:5",
    "5:4",
    "9:16",
    "16:9",
    "21:9",
]

SUPPORTED_ASPECT_RATIOS = [
    *BASE_SUPPORTED_ASPECT_RATIOS,
    "1:4",
    "1:8",
    "4:1",
    "8:1",
]

BASE_SUPPORTED_IMAGE_SIZES = ["1K", "2K", "4K"]
SUPPORTED_IMAGE_SIZES = ["512px", *BASE_SUPPORTED_IMAGE_SIZES]

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _is_flash_model(model: str | None) -> bool:
    return str(model or "").strip().lower() == GEMINI_FLASH_IMAGE_MODEL


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


def _shorten_text(value: object, max_len: int = 240) -> str:
    text = str(value or "").strip().replace("\n", " ")
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 3]}..."


def _decode_base64(data: str | None) -> bytes | None:
    if not isinstance(data, str) or not data.strip():
        return None
    try:
        return base64.b64decode(data)
    except Exception:
        return None


def _decode_data_url(url: str | None) -> bytes | None:
    if not isinstance(url, str):
        return None
    text = url.strip()
    if not text.startswith("data:"):
        return None
    marker = ";base64,"
    if marker not in text:
        return None
    _, encoded = text.split(marker, 1)
    return _decode_base64(encoded)


def _extract_text_snippets(payload: dict, limit: int = 3) -> list[str]:
    snippets: list[str] = []

    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if len(snippets) >= limit:
                break
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            if not isinstance(content, dict):
                continue
            parts = content.get("parts")
            if not isinstance(parts, list):
                continue
            for part in parts:
                if len(snippets) >= limit:
                    break
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    snippets.append(_shorten_text(text, 180))

    choices = payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if len(snippets) >= limit:
                break
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                snippets.append(_shorten_text(content, 180))
                continue
            if isinstance(content, list):
                for item in content:
                    if len(snippets) >= limit:
                        break
                    if not isinstance(item, dict):
                        continue
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        snippets.append(_shorten_text(text, 180))

    return snippets


def _build_no_image_diagnostic(payload: dict) -> str:
    parts: list[str] = []
    keys = [str(k) for k in payload.keys()]
    if keys:
        parts.append(f"top_keys={','.join(keys[:8])}")

    error_obj = payload.get("error")
    if error_obj:
        parts.append(f"error={_shorten_text(error_obj, 300)}")

    prompt_feedback = payload.get("promptFeedback") or payload.get("prompt_feedback")
    if prompt_feedback:
        parts.append(f"prompt_feedback={_shorten_text(prompt_feedback, 220)}")

    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        parts.append(f"candidates={len(candidates)}")
        finish_reasons: list[str] = []
        part_keys: list[str] = []
        for candidate in candidates[:3]:
            if not isinstance(candidate, dict):
                continue
            finish_reason = candidate.get("finishReason") or candidate.get("finish_reason")
            if finish_reason:
                finish_reasons.append(str(finish_reason))
            content = candidate.get("content")
            if isinstance(content, dict):
                candidate_parts = content.get("parts")
                if isinstance(candidate_parts, list):
                    for part in candidate_parts[:3]:
                        if isinstance(part, dict):
                            part_keys.append(",".join(sorted(str(k) for k in part.keys())))
        if finish_reasons:
            parts.append(f"finish_reason={','.join(finish_reasons)}")
        if part_keys:
            parts.append(f"part_keys={';'.join(part_keys[:6])}")

    choices = payload.get("choices")
    if isinstance(choices, list):
        parts.append(f"choices={len(choices)}")
        finish_reasons = []
        for choice in choices[:3]:
            if not isinstance(choice, dict):
                continue
            finish_reason = choice.get("finish_reason")
            if finish_reason:
                finish_reasons.append(str(finish_reason))
        if finish_reasons:
            parts.append(f"choice_finish_reason={','.join(finish_reasons)}")

    text_snippets = _extract_text_snippets(payload, limit=3)
    if text_snippets:
        parts.append(f"text_snippets={' | '.join(text_snippets)}")

    return "；".join(parts) if parts else "响应结构不包含可识别图像字段"


async def _extract_image_bytes(payload: dict, client) -> bytes | None:
    # Gemini generateContent style
    candidates = payload.get("candidates", [])
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content", {})
            if not isinstance(content, dict):
                continue
            parts = content.get("parts", [])
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict):
                    continue
                inline_data = part.get("inlineData") or part.get("inline_data")
                if not isinstance(inline_data, dict):
                    continue
                image_bytes = _decode_base64(inline_data.get("data"))
                if image_bytes:
                    return image_bytes

    # OpenAI images style
    data_items = payload.get("data", [])
    if isinstance(data_items, list):
        for item in data_items:
            if not isinstance(item, dict):
                continue
            image_bytes = _decode_base64(item.get("b64_json"))
            if image_bytes:
                return image_bytes
            url = item.get("url")
            image_bytes = _decode_data_url(url)
            if image_bytes:
                return image_bytes
            if isinstance(url, str) and url.strip().startswith(("http://", "https://")):
                try:
                    response = await client.get(url.strip())
                    if response.status_code < 400 and response.content:
                        return response.content
                except Exception:
                    pass

    # OpenAI chat style with image_url content block
    choices = payload.get("choices", [])
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for item in content:
                if not isinstance(item, dict):
                    continue
                image_url = item.get("image_url")
                url = image_url.get("url") if isinstance(image_url, dict) else image_url
                image_bytes = _decode_data_url(url)
                if image_bytes:
                    return image_bytes
                if isinstance(url, str) and url.strip().startswith(("http://", "https://")):
                    try:
                        response = await client.get(url.strip())
                        if response.status_code < 400 and response.content:
                            return response.content
                    except Exception:
                        pass

    return None


class OpenAIChatImageProvider(ImageProvider):
    """OpenAI Chat Completions 兼容图像生成 Provider"""

    name = "openai_chat"
    supports_reference = True

    def __init__(
        self,
        base_url: str = "https://sanbeimao-cliproxyapi.hf.space",
        api_key: str = "",
        model: str = "gemini-3-pro-image-preview",
        aspect_ratio: str = "9:16",
        image_size: str = "2K",
        timeout: float = 600.0,
        max_retries: int = 4,
        retry_interval: int = 2,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.aspect_ratio = aspect_ratio
        self.image_size = image_size
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_interval = retry_interval

    def _validate_config(self) -> None:
        if not self.base_url:
            raise ValueError("OpenAI Chat Image Provider 需要配置 base_url")

    def _build_request(
        self,
        prompt: str,
        reference_images: list[Path] | None = None,
        aspect_ratio: str = "9:16",
        image_size: str = "2K",
    ) -> dict:
        parts: list = []

        # Add all reference images
        if reference_images:
            for ref_img in reference_images:
                if ref_img.exists():
                    img_data = base64.b64encode(ref_img.read_bytes()).decode("utf-8")
                    parts.append(
                        {"inlineData": {"mimeType": _get_mime_type(ref_img), "data": img_data}}
                    )

        parts.append({"text": prompt})

        return {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "responseModalities": ["IMAGE", "TEXT"],
                "imageConfig": {"aspectRatio": aspect_ratio, "imageSize": image_size},
            },
        }

    async def generate(
        self,
        prompt: str,
        output_path: Path,
        width: int | None = None,
        height: int | None = None,
        reference_images: list[Path] | None = None,
        aspect_ratio: str | None = None,
        image_size: str | None = None,
        progress_callback: Callable[[int], Awaitable[None]] | None = None,
        **kwargs,
    ) -> ImageResult:
        if progress_callback:
            try:
                await progress_callback(1)
            except Exception:
                pass
        try:
            import httpx
        except ImportError:
            raise ImportError("请安装 httpx 库: pip install httpx")

        try:
            from PIL import Image
        except ImportError:
            raise ImportError("请安装 Pillow 库: pip install Pillow")

        self._validate_config()
        is_flash_model = _is_flash_model(self.model)
        allowed_aspect_ratios = (
            SUPPORTED_ASPECT_RATIOS if is_flash_model else BASE_SUPPORTED_ASPECT_RATIOS
        )
        allowed_image_sizes = (
            SUPPORTED_IMAGE_SIZES if is_flash_model else BASE_SUPPORTED_IMAGE_SIZES
        )

        if aspect_ratio is None:
            aspect_ratio = self.aspect_ratio
        if aspect_ratio not in allowed_aspect_ratios:
            aspect_ratio = "9:16"

        if image_size is None:
            image_size = self.image_size
        if image_size not in allowed_image_sizes:
            image_size = "2K"

        # Remove common suffixes like /v1 or /v1/ from base_url before building endpoint
        base = self.base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        endpoint = f"{base}/v1beta/models/{self.model}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request_body = self._build_request(prompt, reference_images, aspect_ratio, image_size)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        timeout = httpx.Timeout(self.timeout, connect=30.0)
        limits = httpx.Limits(max_keepalive_connections=0, max_connections=10)

        last_error = None
        async with httpx.AsyncClient(http2=False, timeout=timeout, limits=limits) as client:
            for attempt in range(self.max_retries):
                try:
                    response = await client.post(endpoint, headers=headers, json=request_body)

                    if response.status_code >= 400:
                        error_msg = response.text[:500]
                        try:
                            error_json = response.json()
                            error_msg = json.dumps(error_json, ensure_ascii=False)
                        except json.JSONDecodeError:
                            pass

                        if response.status_code in RETRYABLE_STATUS_CODES:
                            if attempt < self.max_retries - 1:
                                sleep_time = self.retry_interval * (2**attempt)
                                print(
                                    f"  HTTP {response.status_code}，重试 {attempt + 1}/{self.max_retries}，等待 {sleep_time}s..."
                                )
                                await asyncio.sleep(sleep_time)
                                continue

                        raise RuntimeError(f"HTTP {response.status_code}: {error_msg}")

                    try:
                        payload = response.json()
                    except json.JSONDecodeError:
                        raise ValueError(
                            f"响应不是合法 JSON，body={_shorten_text(response.text, 500)}"
                        )

                    image_bytes = await _extract_image_bytes(payload, client)
                    if image_bytes:
                        image = Image.open(BytesIO(image_bytes))
                        actual_width, actual_height = image.size
                        image.save(output_path)

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

                    diagnostic = _build_no_image_diagnostic(payload)
                    raise ValueError(f"响应中未找到图像数据。{diagnostic}")

                except httpx.TimeoutException as e:
                    last_error = e
                    if attempt < self.max_retries - 1:
                        sleep_time = self.retry_interval * (2**attempt)
                        print(
                            f"  超时，重试 {attempt + 1}/{self.max_retries}，等待 {sleep_time}s..."
                        )
                        await asyncio.sleep(sleep_time)
                    else:
                        break

                except (httpx.ConnectError, httpx.NetworkError, httpx.RemoteProtocolError) as e:
                    last_error = e
                    if attempt < self.max_retries - 1:
                        sleep_time = self.retry_interval * (2**attempt)
                        print(
                            f"  网络错误 ({type(e).__name__})，重试 {attempt + 1}/{self.max_retries}，等待 {sleep_time}s..."
                        )
                        await asyncio.sleep(sleep_time)
                    else:
                        break

                except Exception as e:
                    last_error = e
                    error_str = str(e).lower()

                    retryable = any(
                        x in error_str
                        for x in [
                            "rate_limit",
                            "quota",
                            "capacity",
                            "timeout",
                            "connection",
                            "network",
                            "unavailable",
                        ]
                    )

                    if retryable and attempt < self.max_retries - 1:
                        sleep_time = self.retry_interval * (2**attempt)
                        print(
                            f"  重试 {attempt + 1}/{self.max_retries}，等待 {sleep_time}s...，失败原因: {e}"
                        )
                        await asyncio.sleep(sleep_time)
                    else:
                        break

        raise RuntimeError(f"OpenAI Chat 图像生成失败: {last_error}")

    def get_supported_aspect_ratios(self) -> list[str]:
        return SUPPORTED_ASPECT_RATIOS
