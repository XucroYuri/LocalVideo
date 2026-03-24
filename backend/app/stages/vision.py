"""Vision module for generating reference descriptions from images using Vision API."""

import base64
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.llm.runtime import resolve_llm_runtime
from app.stages.common.log_utils import log_stage_separator
from app.stages.common.paths import resolve_path_for_io

from ._generation_log import truncate_generation_text
from .prompts import (
    format_prompt_complexity_for_log,
    format_target_language_for_log,
    get_vision_description_length_requirement,
    resolve_prompt_complexity,
    resolve_target_language,
)

logger = logging.getLogger(__name__)

# Prompt for generating reference description from image
VISION_DESCRIPTION_PROMPT_ZH = """你是一名专业参考描述生成助手。
请基于提供的参考图片，生成一段详细的中文可视参考描述。

尽量覆盖（按实际适用）：
- 主体类型（人物/生物/物体/标识）
- 结构与外形特征（轮廓、比例、形态）
- 关键视觉细节（颜色、材质、纹理、图案）
- 可见配件/标识与朝向姿态
- 显著辨识特征

{length_requirement} 只聚焦可见信息，不要扩展背景设定。
直接输出描述正文，不要添加前缀或解释。"""

VISION_DESCRIPTION_PROMPT_EN = """You are a professional reference description generator.
Based on the provided reference image, generate a detailed English visual reference description.

Cover these aspects when applicable:
- Subject type (person/creature/object/logo)
- Overall structure, proportions, and silhouette
- Key visual details (color, material, texture, patterns)
- Visible accessories/markings and orientation/posture
- Distinctive identifying traits

{length_requirement} Focus on visual appearance only.
Output the description directly without any prefix or explanation."""


def get_vision_description_prompt(language: str, prompt_complexity: str) -> str:
    length_requirement = get_vision_description_length_requirement(language, prompt_complexity)
    if language == "en":
        return VISION_DESCRIPTION_PROMPT_EN.format(length_requirement=length_requirement)
    return VISION_DESCRIPTION_PROMPT_ZH.format(length_requirement=length_requirement)


async def generate_description_from_image(
    file_path: str,
    target_language: Any = None,
    prompt_complexity: Any = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    use_stream: bool = False,
    on_stream_update: Callable[[str], Awaitable[None]] | None = None,
) -> str:
    """
    Generate reference description from image using Vision API.

    Args:
        file_path: Path to the reference image file
        target_language: Output language code ("zh" or "en")

    Returns:
        Generated description string

    Raises:
        FileNotFoundError: If image file not found
        ValueError: If LLM provider is not configured
        Exception: If LLM call fails
    """
    # Validate file exists
    path = resolve_path_for_io(file_path) or Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {file_path}")

    # Read and encode image
    with open(path, "rb") as f:
        image_data = f.read()
    image_base64 = base64.b64encode(image_data).decode("utf-8")

    llm_input_data: dict[str, Any] = {}
    provider_text = str(llm_provider or "").strip()
    model_text = str(llm_model or "").strip()
    if provider_text:
        llm_input_data["llm_provider"] = provider_text
    if model_text:
        llm_input_data["llm_model"] = model_text
    llm_runtime = resolve_llm_runtime(llm_input_data or None, require_vision=True)
    llm_provider = llm_runtime.provider

    language = resolve_target_language(target_language)
    language_log = format_target_language_for_log(language)
    complexity = resolve_prompt_complexity(prompt_complexity)
    complexity_log = format_prompt_complexity_for_log(complexity)
    prompt = get_vision_description_prompt(language, complexity)

    # Log input
    log_stage_separator(logger)
    logger.info("[Vision] LLM Generate - Reference Description from Image")
    logger.info(
        "[Input] llm_provider=%s(%s) llm_model=%s",
        llm_runtime.provider_name,
        llm_runtime.provider_type,
        llm_runtime.model,
    )
    logger.info("[Input] target_language=%s", language_log)
    logger.info("[Input] prompt_complexity=%s", complexity_log)
    logger.info("[Input] prompt: %s", truncate_generation_text(prompt))
    logger.info("[Input] image_path: %s", str(path))
    logger.info("[Input] image_size: %d bytes", len(image_data))
    log_stage_separator(logger)

    description = ""
    if use_stream:
        stream_chunks: list[str] = []
        chars_since_flush = 0
        try:
            async for chunk in llm_provider.generate_stream(
                prompt=prompt,
                temperature=0.7,
                max_tokens=500,
                image_base64=image_base64,
            ):
                text = str(chunk or "")
                if not text:
                    continue
                stream_chunks.append(text)
                if on_stream_update is not None:
                    chars_since_flush += len(text)
                    if chars_since_flush >= 280:
                        await on_stream_update("".join(stream_chunks))
                        chars_since_flush = 0
            description = "".join(stream_chunks).strip()
            if on_stream_update is not None and description:
                await on_stream_update(description)
        except Exception as stream_err:  # noqa: BLE001
            logger.warning(
                "[Vision] stream failed (%r), fallback to non-stream generate",
                stream_err,
            )

    if not description:
        response = await llm_provider.generate(
            prompt=prompt,
            temperature=0.7,
            max_tokens=500,
            image_base64=image_base64,
        )
        description = response.content.strip()
        if on_stream_update is not None and description:
            await on_stream_update(description)

    if not description:
        raise RuntimeError(
            "Vision model returned empty description content; please retry or switch to a more stable vision model."
        )

    # Log output
    logger.info(
        "[Output] response: %s",
        truncate_generation_text(description),
    )
    log_stage_separator(logger)

    return description
