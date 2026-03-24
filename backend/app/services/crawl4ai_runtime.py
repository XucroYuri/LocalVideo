from __future__ import annotations

import asyncio
import shutil
from typing import Any


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("fit_markdown", "raw_markdown", "markdown"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate
        return str(value)

    for key in ("fit_markdown", "raw_markdown", "markdown"):
        candidate = getattr(value, key, None)
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return str(value)


async def extract_text_with_crawl4ai(
    source_url: str,
    *,
    ignore_images: bool,
    ignore_links: bool,
) -> str:
    try:
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
        from crawl4ai.content_filter_strategy import PruningContentFilter
        from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
    except Exception as exc:  # pragma: no cover - dependency validated separately
        raise RuntimeError("后端主环境未安装 crawl4ai。") from exc

    prune = PruningContentFilter(
        threshold=0.45,
        threshold_type="dynamic",
        min_word_threshold=5,
    )
    mdgen = DefaultMarkdownGenerator(
        content_filter=prune,
        options={
            "ignore_images": ignore_images,
            "ignore_links": ignore_links,
        },
    )
    config = CrawlerRunConfig(
        markdown_generator=mdgen,
        word_count_threshold=10,
        excluded_tags=["header", "nav", "footer", "form", "aside"],
        excluded_selector=".sidebar, .related, .recommend, .topbar, #comment, #footer",
    )

    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=source_url, config=config)

    if not bool(getattr(result, "success", False)):
        error_message = _to_text(getattr(result, "error_message", "")) or "crawl4ai 执行失败"
        raise RuntimeError(error_message)

    text = _to_text(getattr(result, "markdown", None)).strip()
    if not text:
        raise RuntimeError("网页可见文本为空，可能是动态渲染失败或目标页面不可访问")
    return text


async def validate_crawl4ai_installation() -> tuple[str, str]:
    try:
        import crawl4ai  # noqa: F401
    except Exception as exc:  # pragma: no cover - dependency validated separately
        raise RuntimeError("后端主环境未安装 crawl4ai。") from exc

    doctor_path = shutil.which("crawl4ai-doctor")
    if not doctor_path:
        raise RuntimeError("未找到 crawl4ai-doctor，请确认已在主环境执行 crawl4ai-setup。")

    try:
        process = await asyncio.create_subprocess_exec(
            doctor_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
    except TimeoutError as exc:
        raise RuntimeError("Crawl4AI 校验超时（crawl4ai-doctor > 300s）。") from exc
    except FileNotFoundError as exc:
        raise RuntimeError("未找到 crawl4ai-doctor，请确认已在主环境执行 crawl4ai-setup。") from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"无法执行 crawl4ai-doctor: {exc}") from exc

    output_lines: list[str] = []
    if stdout:
        output_lines.extend(stdout.decode(errors="ignore").splitlines())
    if stderr:
        output_lines.extend(stderr.decode(errors="ignore").splitlines())
    output_preview = "\n".join(output_lines[-12:]) if output_lines else "<no output>"

    if process.returncode != 0:
        raise RuntimeError(f"Crawl4AI 校验失败。\n输出：\n{output_preview}")
    return doctor_path, output_preview
