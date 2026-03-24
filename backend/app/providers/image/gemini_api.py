"""
Gemini API Image Provider

使用 Google Gemini API 生成图像
"""

import asyncio
import os
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


def _is_flash_model(model: str | None) -> bool:
    return str(model or "").strip().lower() == GEMINI_FLASH_IMAGE_MODEL


class GeminiAPIImageProvider(ImageProvider):
    """Google Gemini API 图像生成 Provider"""

    name = "gemini_api"
    supports_reference = True

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-3-pro-image-preview",
        aspect_ratio: str = "9:16",
        image_size: str = "2K",
        timeout: int = 600000,
        max_retries: int = 3,
        retry_interval: int = 5,
    ):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.model = model
        self.aspect_ratio = aspect_ratio
        self.image_size = image_size
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_interval = retry_interval

    def _validate_config(self) -> None:
        if not self.api_key:
            raise ValueError("Gemini API Provider 需要配置 api_key 或设置 GEMINI_API_KEY 环境变量")

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
            from google import genai
            from google.genai import types
        except ImportError:
            raise ImportError("请安装 google-genai 库: pip install google-genai")

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

        def _create_client():
            return genai.Client(
                # Force Gemini Developer API mode for this provider.
                # Some environments set GOOGLE_GENAI_USE_VERTEXAI=True globally,
                # which would route requests to Vertex and reject API keys.
                vertexai=False,
                api_key=self.api_key,
                http_options=types.HttpOptions(timeout=self.timeout),
            )

        client = await asyncio.to_thread(_create_client)

        contents = []

        if reference_images:
            for ref_img in reference_images:
                if ref_img and ref_img.exists():
                    try:
                        img_data = await asyncio.to_thread(ref_img.read_bytes)
                        ext = ref_img.suffix.lower()
                        mime_map = {
                            ".png": "image/png",
                            ".jpg": "image/jpeg",
                            ".jpeg": "image/jpeg",
                            ".webp": "image/webp",
                            ".gif": "image/gif",
                        }
                        mime_type = mime_map.get(ext, "image/png")
                        contents.append(types.Part.from_bytes(data=img_data, mime_type=mime_type))
                    except Exception as e:
                        print(f"  警告: 加载参考图像失败 {ref_img}: {e}")

        contents.append(prompt)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        last_error = None
        for attempt in range(self.max_retries):
            try:

                def _generate():
                    return client.models.generate_content(
                        model=self.model,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            response_modalities=[types.Modality.TEXT, types.Modality.IMAGE],
                            image_config=types.ImageConfig(
                                aspect_ratio=aspect_ratio,
                                image_size=image_size,
                            ),
                        ),
                    )

                response = await asyncio.to_thread(_generate)

                for part in response.candidates[0].content.parts:
                    if part.inline_data:
                        image = Image.open(BytesIO(part.inline_data.data))
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

                raise ValueError("响应中未找到图像数据")

            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                retryable = any(
                    x in error_str
                    for x in [
                        "rate_limit",
                        "quota",
                        "429",
                        "capacity",
                        "timeout",
                        "connection",
                        "network",
                        "unavailable",
                        "503",
                        "500",
                    ]
                )

                if retryable and attempt < self.max_retries - 1:
                    sleep_time = self.retry_interval * (2**attempt)
                    print(
                        f"  重试 {attempt + 1}/{self.max_retries}，"
                        f"等待 {sleep_time}s...，失败原因: {e}"
                    )
                    await asyncio.sleep(sleep_time)
                else:
                    break

        raise RuntimeError(f"Gemini API 图像生成失败: {last_error}")

    def get_supported_aspect_ratios(self) -> list[str]:
        return SUPPORTED_ASPECT_RATIOS
