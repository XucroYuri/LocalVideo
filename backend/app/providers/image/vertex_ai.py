"""
Vertex AI Image Provider

使用 Google Vertex AI (Gemini) 生成图像
"""

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from io import BytesIO
from pathlib import Path

from app.providers.base.image import ImageProvider, ImageResult

# 支持的宽高比
SUPPORTED_ASPECT_RATIOS = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]

# 支持的图像尺寸
SUPPORTED_IMAGE_SIZES = ["1K", "2K", "4K"]

logger = logging.getLogger(__name__)


class VertexAIImageProvider(ImageProvider):
    """Google Vertex AI 图像生成 Provider"""

    name = "vertex_ai"
    supports_reference = True

    def __init__(
        self,
        project_id: str | None = None,
        location: str = "global",
        model: str = "gemini-3-pro-image-preview",
        aspect_ratio: str = "9:16",
        image_size: str = "2K",
        timeout: int = 600000,  # 整体超时预算（毫秒）
        max_retries: int = 3,
        retry_interval: int = 5,
    ):
        self.project_id = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        self.location = location
        self.model = model
        self.aspect_ratio = aspect_ratio
        self.image_size = image_size
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_interval = retry_interval
        trust_env_raw = os.environ.get("VERTEX_AI_IMAGE_TRUST_ENV", "false").strip().lower()
        self.trust_env = trust_env_raw not in {"0", "false", "no", "off"}
        try:
            self.request_timeout_ms = int(
                os.environ.get("VERTEX_AI_IMAGE_REQUEST_TIMEOUT_MS", "300000")
            )
        except ValueError:
            self.request_timeout_ms = 300000
        self.request_timeout_ms = max(1000, self.request_timeout_ms)
        try:
            self.sdk_retry_attempts = int(os.environ.get("VERTEX_AI_IMAGE_SDK_RETRY_ATTEMPTS", "1"))
        except ValueError:
            self.sdk_retry_attempts = 1
        self.sdk_retry_attempts = max(1, self.sdk_retry_attempts)

    def _validate_config(self) -> None:
        if not self.project_id:
            raise ValueError(
                "Vertex AI Provider 需要配置 project_id 或设置 GOOGLE_CLOUD_PROJECT 环境变量"
            )

    @staticmethod
    def _format_exception(exc: Exception | None) -> str:
        if exc is None:
            return "Unknown error"
        parts = [f"{type(exc).__name__}: {exc}"]
        cause = exc.__cause__ or exc.__context__
        depth = 0
        while cause is not None and depth < 3:
            parts.append(f"{type(cause).__name__}: {cause}")
            cause = cause.__cause__ or cause.__context__
            depth += 1
        return " <- ".join(parts)

    @staticmethod
    def _is_retryable_error(exc: Exception) -> tuple[bool, str]:
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int):
            if status_code in {408, 409, 425, 429, 500, 502, 503, 504}:
                return True, f"status_code={status_code}"

        error_text = str(exc).lower()
        retryable_tokens = [
            "rate_limit",
            "quota",
            "resource_exhausted",
            "deadline_exceeded",
            "deadline expired",
            "429",
            "500",
            "502",
            "503",
            "504",
            "capacity",
            "timeout",
            "timed out",
            "connection",
            "network",
            "unavailable",
            "remoteprotocolerror",
            "disconnected without sending a response",
            "connection reset",
            "connection aborted",
            "broken pipe",
            "eof",
        ]
        for token in retryable_tokens:
            if token in error_text:
                return True, f"matched_token={token}"

        return False, "no_retryable_signal"

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
        """
        生成图像

        Args:
            prompt: 图像描述
            output_path: 输出路径
            width: 可选宽度（当前 provider 不使用）
            height: 可选高度（当前 provider 不使用）
            reference_images: 参考图像路径列表
            aspect_ratio: 宽高比
        """
        try:
            from google import genai
            from google.genai.types import (
                GenerateContentConfig,
                HttpOptions,
                HttpRetryOptions,
                ImageConfig,
                Modality,
                Part,
            )
        except ImportError:
            raise ImportError("请安装 google-genai 库: pip install google-genai")

        try:
            from PIL import Image
        except ImportError:
            raise ImportError("请安装 Pillow 库: pip install Pillow")

        self._validate_config()

        # 使用传入的参数或默认值
        if aspect_ratio is None:
            aspect_ratio = self.aspect_ratio
        if aspect_ratio not in SUPPORTED_ASPECT_RATIOS:
            aspect_ratio = "9:16"

        if image_size is None:
            image_size = self.image_size
        if image_size not in SUPPORTED_IMAGE_SIZES:
            image_size = "2K"

        # 构建内容列表
        contents = []

        # 添加参考图像（如果有）
        if reference_images:
            for ref_img in reference_images:
                if ref_img and ref_img.exists():
                    try:
                        img_data = await asyncio.to_thread(ref_img.read_bytes)
                        # 检测 MIME 类型
                        ext = ref_img.suffix.lower()
                        mime_map = {
                            ".png": "image/png",
                            ".jpg": "image/jpeg",
                            ".jpeg": "image/jpeg",
                            ".webp": "image/webp",
                            ".gif": "image/gif",
                        }
                        mime_type = mime_map.get(ext, "image/png")
                        contents.append(Part.from_bytes(data=img_data, mime_type=mime_type))
                    except Exception as e:
                        logger.warning("[VertexAI Image] 加载参考图像失败 %s: %s", ref_img, str(e))

        # 添加文本提示
        contents.append(prompt)

        # 创建输出目录
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 带重试的生成
        last_error = None
        proxy_env = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        if proxy_env:
            logger.warning(
                "[VertexAI Image] 检测到代理环境 HTTPS_PROXY=%s，若频繁断连可尝试设置 "
                "VERTEX_AI_IMAGE_TRUST_ENV=false 或将 *.googleapis.com 加入 NO_PROXY。",
                proxy_env,
            )

        for attempt in range(self.max_retries):
            progress_task = None
            progress_stop = asyncio.Event()
            try:
                logger.info(
                    "[VertexAI Image] 开始生成尝试 (%d/%d), request_timeout=%sms, sdk_retry_attempts=%d",
                    attempt + 1,
                    self.max_retries,
                    self.request_timeout_ms,
                    self.sdk_retry_attempts,
                )

                # 每次重试都新建 client，避免复用已断开的底层连接池
                def _create_client():
                    return genai.Client(
                        vertexai=True,
                        project=self.project_id,
                        location=self.location,
                        http_options=HttpOptions(
                            timeout=self.request_timeout_ms,
                            client_args={"trust_env": self.trust_env},
                            retry_options=HttpRetryOptions(
                                attempts=self.sdk_retry_attempts,
                                http_status_codes=[429, 500, 502, 503, 504],
                            ),
                        ),
                    )

                client = await asyncio.to_thread(_create_client)

                if progress_callback:

                    async def _pulse() -> None:
                        start = time.time()
                        timeout_sec = max(self.request_timeout_ms / 1000, 1)
                        while not progress_stop.is_set():
                            elapsed = time.time() - start
                            est = int(min(99, max(5, (elapsed / timeout_sec) * 94 + 5)))
                            try:
                                await progress_callback(est)
                            except Exception:
                                pass
                            try:
                                await asyncio.wait_for(progress_stop.wait(), timeout=1.5)
                            except TimeoutError:
                                pass

                    progress_task = asyncio.create_task(_pulse())

                def _generate():
                    return client.models.generate_content(
                        model=self.model,
                        contents=contents,
                        config=GenerateContentConfig(
                            response_modalities=[Modality.TEXT, Modality.IMAGE],
                            image_config=ImageConfig(
                                aspect_ratio=aspect_ratio,
                                image_size=image_size,
                            ),
                        ),
                    )

                response = await asyncio.to_thread(_generate)

                # 解析响应
                for part in response.candidates[0].content.parts:
                    if part.inline_data:
                        # 使用 PIL 读取图片获取实际尺寸
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
                retryable, retry_reason = self._is_retryable_error(e)

                if retryable and attempt < self.max_retries - 1:
                    sleep_time = self.retry_interval * (2**attempt)
                    logger.warning(
                        "[VertexAI Image] 生成失败，将重试 (%d/%d)，等待 %ss，判定: %s，原因: %s",
                        attempt + 1,
                        self.max_retries,
                        sleep_time,
                        retry_reason,
                        self._format_exception(e),
                    )
                    await asyncio.sleep(sleep_time)
                else:
                    logger.error(
                        "[VertexAI Image] 生成失败（不再重试）: retryable=%s, reason=%s, detail=%s",
                        retryable,
                        retry_reason,
                        self._format_exception(e),
                        exc_info=True,
                    )
                    break
            finally:
                progress_stop.set()
                if progress_task:
                    try:
                        await progress_task
                    except Exception:
                        pass

        raise RuntimeError(
            f"Vertex AI 图像生成失败: {self._format_exception(last_error)}"
        ) from last_error

    def get_supported_aspect_ratios(self) -> list[str]:
        return SUPPORTED_ASPECT_RATIOS
