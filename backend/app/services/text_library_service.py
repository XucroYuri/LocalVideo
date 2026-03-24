from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import shutil
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import ServiceError
from app.db.session import AsyncSessionLocal
from app.llm.runtime import ResolvedLLMRuntime, resolve_llm_runtime
from app.models.text_library import (
    TextImportJobStatus,
    TextImportTaskStatus,
    TextItemFieldStatus,
    TextLibraryImportJob,
    TextLibraryImportTask,
    TextLibraryItem,
    TextLibraryPostCache,
    TextSourceChannel,
)
from app.services.crawl4ai_runtime import extract_text_with_crawl4ai
from app.services.library_import_limits import (
    get_library_batch_max_items,
    get_library_batch_max_total_upload_bytes,
    get_library_batch_max_total_upload_mb,
)
from app.services.library_task_scheduler import CardStage, run_card_stage
from app.stages._audio_split import transcribe_audio_words
from app.stages.common.log_utils import log_stage_separator

logger = logging.getLogger(__name__)

SUPPORTED_TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
MEDIA_CHANNELS = {
    TextSourceChannel.XIAOHONGSHU,
    TextSourceChannel.DOUYIN,
    TextSourceChannel.KUAISHOU,
}
URL_SPLIT_PATTERN = re.compile(r"[\s]+")
WEB_URL_PARSER_JINA_READER = "jina_reader"
WEB_URL_PARSER_CRAWL4AI = "crawl4ai"
JINA_READER_REMOVE_SELECTOR = (
    "header, nav, footer, aside, .sidebar, .related, .recommend, .topbar, "
    "#comment, #footer, .ad, .ads, .advertisement, [id*='ad']"
)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".avif"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv", ".flv", ".ts", ".m3u8"}
TITLE_PROMPT_TEMPLATE = (
    "请根据给定文本生成一个简短中文标题。\n"
    "文本内容：\n{content}\n\n"
    "要求：\n"
    "1) 最多 12 个汉字；\n"
    "2) 只输出标题本身，不要解释；\n"
    "3) 不使用书名号、引号、冒号。\n"
    "4) 严格输出 JSON，不要输出任何额外文本。\n\n"
    "输出格式：\n"
    '{{"title":"这里是标题"}}'
)
TITLE_SYSTEM_PROMPT = "你是擅长命名的中文编辑。"
TRANSCRIPT_PROOFREAD_PROMPT_TEMPLATE = (
    "请你对以下视频转写文本做中文校对和可读性整理。\n"
    "输入信息：\n"
    "帖子标题：{title}\n"
    "帖子文案：{note}\n"
    "待校对视频转写：\n{transcript}\n\n"
    "要求：\n"
    "1) 不改变原意，不编造事实；\n"
    "2) 修正明显识别错误和错别字；\n"
    "3) 补充标点并按语义适当分段，提升可读性；\n"
    "4) 删除明显无意义噪音词，但保留关键信息（时间、数字、品牌、专有名词）；\n"
    "5) 严格输出 JSON，不要输出任何额外文本。\n\n"
    "输出格式：\n"
    '{{"proofread_text":"这里是校对后的正文"}}'
)
TRANSCRIPT_PROOFREAD_SYSTEM_PROMPT = "你是严谨的中文口播文本校对编辑。"

XHS_DOWNLOADER_INLINE_SCRIPT = r"""
import asyncio
import json
import pathlib
import re
import sys

repo_path = pathlib.Path(sys.argv[1]).resolve()
source_url = str(sys.argv[2]).strip()
sys.path.insert(0, str(repo_path))

from source import XHS  # noqa: E402

async def _main() -> None:
    title = ""
    content = ""
    media_type = ""
    post_id = ""
    post_updated_at = ""
    async with XHS(
        work_path=str(repo_path / "Volume"),
        download_record=False,
        record_data=False,
        image_download=False,
        video_download=True,
        live_download=False,
        author_archive=False,
        folder_mode=False,
    ) as client:
        result = await client.extract(source_url, download=False)
    if isinstance(result, dict):
        item = result
    elif isinstance(result, list) and result:
        item = result[0]
    else:
        item = {}
    if isinstance(item, dict):
        title = str(item.get("作品标题") or item.get("title") or "").strip()
        content = str(item.get("作品描述") or item.get("desc") or "").strip()
        media_type = str(item.get("作品类型") or item.get("type") or "").strip()
        post_id = str(item.get("作品ID") or item.get("note_id") or item.get("id") or "").strip()
        post_updated_at = str(item.get("最后更新时间") or item.get("time") or "").strip()
    urls = item.get("下载地址") if isinstance(item, dict) else []
    if isinstance(urls, str):
        urls = [urls]
    media_url = ""
    for one in urls or []:
        parts = [part.strip() for part in str(one or "").split() if part.strip()]
        if parts:
            media_url = parts[0]
            break
    print(
        json.dumps(
            {
                "media_url": media_url,
                "title": title,
                "content": content,
                "media_type": media_type,
                "post_id": post_id,
                "post_updated_at": post_updated_at,
            },
            ensure_ascii=False,
        )
    )

asyncio.run(_main())
"""

TIKTOK_DOWNLOADER_INLINE_SCRIPT = r"""
import asyncio
import json
import pathlib
import sys

repo_path = pathlib.Path(sys.argv[1]).resolve()
source_url = str(sys.argv[2]).strip()
sys.path.insert(0, str(repo_path))

from src.application import TikTokDownloader  # noqa: E402
from src.application.main_terminal import TikTok  # noqa: E402

async def _main() -> None:
    media_url = ""
    title = ""
    content = ""
    media_type = ""
    post_id = ""
    post_updated_at = ""
    async with TikTokDownloader() as app:
        app.check_config()
        await app.check_settings(False)
        client = TikTok(app.parameter, app.database, server_mode=True)
        ids = await client.links.run(source_url, type_="detail")
        ids = [str(one).strip() for one in (ids or []) if str(one).strip()]
        if ids:
            root, params, logger = client.record.run(app.parameter)
            async with logger(root, console=client.console, **params) as record:
                details = await client._handle_detail(
                    ids[:1],
                    False,
                    record,
                    api=True,
                    source=False,
                    cookie="",
                    proxy=None,
                )
            if details and isinstance(details, list):
                item = details[0] or {}
                content = str(item.get("desc") or "").strip()
                title = ""
                media_type = str(item.get("type") or "").strip()
                post_id = str(item.get("id") or "").strip()
                post_updated_at = str(item.get("create_time") or item.get("create_timestamp") or "").strip()
                downloads = item.get("downloads")
                if isinstance(downloads, list):
                    for one in downloads:
                        parts = [part.strip() for part in str(one or "").split() if part.strip()]
                        if parts:
                            media_url = parts[0]
                            break
                else:
                    parts = [part.strip() for part in str(downloads or "").split() if part.strip()]
                    media_url = parts[0] if parts else ""
    print(
        json.dumps(
            {
                "media_url": media_url,
                "title": title,
                "content": content,
                "media_type": media_type,
                "post_id": post_id,
                "post_updated_at": post_updated_at,
            },
            ensure_ascii=False,
        )
    )

asyncio.run(_main())
"""

KS_DOWNLOADER_INLINE_SCRIPT = r"""
import asyncio
import json
import pathlib
import sys

repo_path = pathlib.Path(sys.argv[1]).resolve()
source_url = str(sys.argv[2]).strip()
sys.path.insert(0, str(repo_path))

from source import KS  # noqa: E402

async def _main() -> None:
    media_url = ""
    title = ""
    content = ""
    media_type = ""
    post_id = ""
    post_updated_at = ""
    async with KS(server_mode=True) as client:
        result = await client.detail_one(source_url, download=False, proxy="", cookie="")
    item = result if isinstance(result, dict) else {}
    if isinstance(item, dict):
        content = str(item.get("caption") or item.get("desc") or "").strip()
        media_type = str(item.get("photoType") or item.get("type") or "").strip()
        post_id = str(item.get("detailID") or item.get("id") or "").strip()
        post_updated_at = str(item.get("timestamp") or item.get("create_time") or "").strip()
    downloads = item.get("download") if isinstance(item, dict) else []
    if isinstance(downloads, str):
        downloads = [downloads]
    media_url = ""
    for one in downloads or []:
        parts = [part.strip() for part in str(one or "").split() if part.strip()]
        if parts:
            media_url = parts[0]
            break
    print(
        json.dumps(
            {
                "media_url": media_url,
                "title": title,
                "content": content,
                "media_type": media_type,
                "post_id": post_id,
                "post_updated_at": post_updated_at,
            },
            ensure_ascii=False,
        )
    )

asyncio.run(_main())
"""


ITEM_STAGE_PENDING = "pending"
ITEM_STAGE_EXTRACTING = "extracting"
ITEM_STAGE_TRANSCRIBING = "transcribing"
ITEM_STAGE_PROOFREADING = "proofreading"
ITEM_STAGE_GENERATING = "generating"
ITEM_STAGE_READY = "ready"
ITEM_STAGE_FAILED = "failed"
ITEM_STAGE_CANCELED = "canceled"

TASK_STAGE_PENDING = "pending"
TASK_STAGE_EXTRACTING = "extracting"
TASK_STAGE_TRANSCRIBING = "transcribing"
TASK_STAGE_PROOFREADING = "proofreading"
TASK_STAGE_GENERATING = "generating"
TASK_STAGE_COMPLETED = "completed"
TASK_STAGE_FAILED = "failed"
TASK_STAGE_CANCELED = "canceled"


@dataclass(slots=True)
class _TitleGenerationInput:
    task: TextLibraryImportTask | None
    item: TextLibraryItem
    content: str
    source_channel: TextSourceChannel
    source_url: str | None
    source_file_name: str | None
    post_cache_id: int | None = None


class TextLibraryService:
    _job_tasks: dict[str, asyncio.Task[None]] = {}
    _title_tasks: dict[int, asyncio.Task[None]] = {}

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        return str(value or "").strip()

    @classmethod
    def _normalize_name(cls, value: str | None) -> str:
        name = cls._normalize_text(value)
        if not name:
            raise ServiceError(400, "名称不能为空")
        return name[:255]

    @classmethod
    def _storage_root(cls) -> Path:
        path = Path(settings.storage_path).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def _text_library_storage_dir(cls) -> Path:
        path = cls._storage_root() / "text-library"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def _text_library_tmp_dir(cls) -> Path:
        path = cls._text_library_storage_dir() / "_tmp"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def _text_library_video_cache_dir(cls) -> Path:
        path = cls._storage_root() / "video-cache"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _truncate_log_text(text: str, limit: int = 5000) -> str:
        normalized = str(text or "")
        if len(normalized) <= limit:
            return normalized
        half = max(200, limit // 2)
        return f"{normalized[:half]}\n...\n{normalized[-half:]}"

    def _log_llm_generate_input(
        self,
        *,
        action: str,
        llm_runtime: ResolvedLLMRuntime,
        prompt: str,
        system_prompt: str,
        extra_inputs: dict[str, str] | None = None,
    ) -> None:
        log_stage_separator(logger)
        logger.info("[TextLibrary] LLM Generate - %s", action)
        logger.info(
            "[Input] llm_provider=%s(%s) llm_model=%s",
            llm_runtime.provider_name,
            llm_runtime.provider_type,
            llm_runtime.model,
        )
        for key, value in (extra_inputs or {}).items():
            logger.info("[Input] %s=%s", key, self._truncate_log_text(value, 500))
        logger.info("[Input] prompt: %s", self._truncate_log_text(prompt, 1000))
        logger.info("[Input] system_prompt: %s", self._truncate_log_text(system_prompt, 1000))
        log_stage_separator(logger)

    @staticmethod
    def _split_urls(urls_text: str) -> list[str]:
        raw_items = [item.strip() for item in URL_SPLIT_PATTERN.split(urls_text) if item.strip()]
        normalized: list[str] = []
        for item in raw_items:
            url = item
            if not re.match(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://", url):
                url = f"https://{url}"
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                continue
            if url not in normalized:
                normalized.append(url)
        return normalized

    @staticmethod
    def _detect_channel_by_url(url: str) -> TextSourceChannel:
        host = (urlparse(url).netloc or "").lower()
        if "xiaohongshu.com" in host or "xhslink.com" in host:
            return TextSourceChannel.XIAOHONGSHU
        if "douyin.com" in host or "iesdouyin.com" in host:
            return TextSourceChannel.DOUYIN
        if (
            "kuaishou.com" in host
            or "kuaishouapp.com" in host
            or "chenzhongtech.com" in host
            or "gifshow.com" in host
        ):
            return TextSourceChannel.KUAISHOU
        return TextSourceChannel.WEB

    @staticmethod
    def _decode_file_content(raw_bytes: bytes) -> str:
        if not raw_bytes:
            return ""
        encodings = ("utf-8-sig", "utf-8", "gb18030", "gbk")
        for encoding in encodings:
            try:
                return raw_bytes.decode(encoding).strip()
            except UnicodeDecodeError:
                continue
        return raw_bytes.decode("utf-8", errors="ignore").strip()

    @staticmethod
    def _join_whisper_words(words: list[dict[str, Any]]) -> str:
        def _append_token(current: str, token: str) -> str:
            if not current:
                return token
            if re.search(r"[A-Za-z0-9]$", current) and re.search(r"^[A-Za-z0-9]", token):
                return f"{current} {token}"
            return f"{current}{token}"

        sentences: list[str] = []
        current_sentence = ""
        current_utterance_index: int | None = None
        last_end: float | None = None
        for word in words:
            # 注意：normalized 仅用于对齐，不能用于最终文本输出。
            # 否则会把中文数字（如“一二三”）折叠成 "0"。
            token = str(
                word.get("word") or word.get("text") or word.get("normalized") or ""
            ).strip()
            if not token:
                continue

            utterance_index: int | None = None
            try:
                raw_utterance_index = word.get("utterance_index")
                if raw_utterance_index is not None:
                    utterance_index = int(raw_utterance_index)
            except (TypeError, ValueError):
                utterance_index = None

            start = 0.0
            end = 0.0
            try:
                start = float(word.get("start") or 0.0)
            except (TypeError, ValueError):
                start = 0.0
            try:
                end = float(word.get("end") or start)
            except (TypeError, ValueError):
                end = start

            need_break = False
            if current_sentence:
                if (
                    utterance_index is not None
                    and current_utterance_index is not None
                    and utterance_index != current_utterance_index
                ):
                    need_break = True
                elif (
                    utterance_index is None and last_end is not None and (start - last_end) >= 0.45
                ):
                    need_break = True

            if need_break:
                sentences.append(current_sentence.strip())
                current_sentence = ""

            current_sentence = _append_token(current_sentence, token)
            if utterance_index is not None:
                current_utterance_index = utterance_index
            last_end = max(last_end or 0.0, end)

        if current_sentence:
            sentences.append(current_sentence.strip())
        return " ".join(one for one in sentences if one).strip()

    @classmethod
    def _fallback_name(
        cls,
        *,
        content: str,
        source_channel: TextSourceChannel,
        source_url: str | None = None,
        source_file_name: str | None = None,
    ) -> str:
        if source_file_name:
            stem = Path(source_file_name).stem.strip()
            if stem:
                return stem[:24]

        if source_url:
            host = (urlparse(source_url).netloc or "").strip()
            if host:
                return host[:24]

        prefix_map = {
            TextSourceChannel.COPY: "复制文本",
            TextSourceChannel.FILE: "文件文本",
            TextSourceChannel.WEB: "网页文本",
            TextSourceChannel.XIAOHONGSHU: "小红书转写",
            TextSourceChannel.DOUYIN: "抖音转写",
            TextSourceChannel.KUAISHOU: "快手转写",
        }
        prefix = prefix_map.get(source_channel, "文本")
        compact = re.sub(r"\s+", " ", content).strip()
        if compact:
            return f"{prefix}-{compact[:18]}"
        return prefix

    async def _auto_name_text(
        self,
        *,
        content: str,
        source_channel: TextSourceChannel,
        source_url: str | None = None,
        source_file_name: str | None = None,
    ) -> str:
        fallback = self._fallback_name(
            content=content,
            source_channel=source_channel,
            source_url=source_url,
            source_file_name=source_file_name,
        )
        prompt = TITLE_PROMPT_TEMPLATE.format(content=self._truncate_log_text(content, 2600))
        try:
            llm_runtime = resolve_llm_runtime(default_mode="fast_first")
            self._log_llm_generate_input(
                action="Text Title",
                llm_runtime=llm_runtime,
                prompt=prompt,
                system_prompt=TITLE_SYSTEM_PROMPT,
                extra_inputs={
                    "channel": source_channel.value,
                    "source_url": source_url or "-",
                    "source_file": source_file_name or "-",
                    "raw_text_len": str(len(self._normalize_text(content))),
                },
            )
            generated = await llm_runtime.provider.generate(
                prompt=prompt,
                system_prompt=TITLE_SYSTEM_PROMPT,
                temperature=0.2,
            )
            if hasattr(generated, "content"):
                raw_text = str(getattr(generated, "content") or "").strip()
            else:
                raw_text = str(generated or "").strip()
            if not raw_text:
                raise ValueError("empty llm title response")

            payload = self._extract_json_object_from_text(raw_text)
            candidate = self._normalize_text(str(payload.get("title") or payload.get("name") or ""))
            if not candidate:
                candidate = raw_text.splitlines()[0].strip()
                candidate = re.sub(
                    r"^\s*LLMResponse\s*\(\s*content\s*=\s*", "", candidate, flags=re.IGNORECASE
                )
                candidate = re.sub(
                    r"^\s*LLMResponsecontent\s*=\s*", "", candidate, flags=re.IGNORECASE
                )
                candidate = re.sub(r"^\s*(标题|题目)\s*[：:]\s*", "", candidate)
                candidate = re.sub(r"\)\s*,?\s*model\s*=.*$", "", candidate, flags=re.IGNORECASE)
                candidate = re.sub(r"[\"'“”‘’：:<>《》\[\](){}]", "", candidate).strip()
            if candidate:
                logger.info(
                    "[TextLibrary][Title] response channel=%s title=%s",
                    source_channel.value,
                    self._truncate_log_text(candidate, 120),
                )
                return candidate[:24]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Text library name generation fallback: %s", exc)
        logger.info(
            "[TextLibrary][Title] fallback channel=%s title=%s",
            source_channel.value,
            self._truncate_log_text(fallback, 120),
        )
        return fallback[:24]

    async def _proofread_transcript_text(
        self,
        *,
        source_channel: TextSourceChannel,
        source_url: str | None,
        title_text: str,
        note_text: str,
        transcript_text: str,
        on_partial_update: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        raw_transcript = self._normalize_text(transcript_text)
        if not raw_transcript:
            return ""

        prompt = TRANSCRIPT_PROOFREAD_PROMPT_TEMPLATE.format(
            title=self._truncate_log_text(self._normalize_text(title_text) or "（空）", 500),
            note=self._truncate_log_text(self._normalize_text(note_text) or "（空）", 1000),
            transcript=self._truncate_log_text(raw_transcript, 2600),
        )
        try:
            llm_runtime = resolve_llm_runtime()
            self._log_llm_generate_input(
                action="Transcript Proofread",
                llm_runtime=llm_runtime,
                prompt=prompt,
                system_prompt=TRANSCRIPT_PROOFREAD_SYSTEM_PROMPT,
                extra_inputs={
                    "channel": source_channel.value,
                    "source_url": source_url or "-",
                    "raw_text_len": str(len(raw_transcript)),
                },
            )
            provider = llm_runtime.provider
            raw_text = ""
            stream_chunks: list[str] = []
            stream_failed: Exception | None = None
            last_partial = ""

            try:
                async for chunk in provider.generate_stream(
                    prompt=prompt,
                    system_prompt=TRANSCRIPT_PROOFREAD_SYSTEM_PROMPT,
                    temperature=0.1,
                ):
                    one = str(chunk or "")
                    if not one:
                        continue
                    stream_chunks.append(one)
                    partial = self._extract_partial_json_string_field(
                        "".join(stream_chunks), ("proofread_text", "content", "text")
                    )
                    partial = re.sub(r"\n{3,}", "\n\n", self._normalize_text(partial)).strip()
                    if on_partial_update and partial and partial != last_partial:
                        last_partial = partial
                        await on_partial_update(partial)
            except Exception as exc:  # noqa: BLE001
                stream_failed = exc

            if stream_chunks:
                raw_text = self._normalize_text("".join(stream_chunks))
            else:
                generated = await provider.generate(
                    prompt=prompt,
                    system_prompt=TRANSCRIPT_PROOFREAD_SYSTEM_PROMPT,
                    temperature=0.1,
                )
                if hasattr(generated, "content"):
                    raw_text = str(getattr(generated, "content") or "").strip()
                else:
                    raw_text = str(generated or "").strip()

            if stream_failed:
                logger.warning(
                    "Text library transcript proofread stream degraded: %s", stream_failed
                )
            if not raw_text:
                raise ValueError("empty llm proofread response")

            payload = self._extract_json_object_from_text(raw_text)
            candidate = self._normalize_text(
                str(
                    payload.get("proofread_text")
                    or payload.get("content")
                    or payload.get("text")
                    or ""
                )
            )
            if not candidate:
                candidate = raw_text
                candidate = re.sub(
                    r"^\s*(校对后文本|校对后内容|润色后文本|整理后文本)\s*[：:]\s*",
                    "",
                    candidate,
                    flags=re.IGNORECASE,
                ).strip()
            candidate = re.sub(r"\n{3,}", "\n\n", candidate).strip()
            if candidate:
                if on_partial_update:
                    await on_partial_update(candidate)
                logger.info(
                    "[TextLibrary][Proofread] response channel=%s text_len=%s",
                    source_channel.value,
                    len(candidate),
                )
                return candidate
        except Exception as exc:  # noqa: BLE001
            logger.warning("Text library transcript proofread fallback: %s", exc)

        logger.info(
            "[TextLibrary][Proofread] fallback channel=%s text_len=%s",
            source_channel.value,
            len(raw_transcript),
        )
        return raw_transcript

    @staticmethod
    def _extract_partial_json_string_field(text: str, field_names: tuple[str, ...]) -> str:
        source = str(text or "")
        if not source:
            return ""

        for field in field_names:
            marker = re.search(rf'"{re.escape(field)}"\s*:\s*"', source)
            if not marker:
                continue

            idx = marker.end()
            chars: list[str] = []
            while idx < len(source):
                ch = source[idx]
                if ch == '"':
                    break
                if ch != "\\":
                    chars.append(ch)
                    idx += 1
                    continue

                idx += 1
                if idx >= len(source):
                    break
                esc = source[idx]
                if esc == "n":
                    chars.append("\n")
                elif esc == "r":
                    chars.append("\r")
                elif esc == "t":
                    chars.append("\t")
                elif esc == "b":
                    chars.append("\b")
                elif esc == "f":
                    chars.append("\f")
                elif esc in {'"', "\\", "/"}:
                    chars.append(esc)
                elif esc == "u":
                    if idx + 4 >= len(source):
                        break
                    hex_text = source[idx + 1 : idx + 5]
                    if re.fullmatch(r"[0-9a-fA-F]{4}", hex_text):
                        try:
                            chars.append(chr(int(hex_text, 16)))
                            idx += 4
                        except Exception:  # noqa: BLE001
                            pass
                else:
                    chars.append(esc)
                idx += 1

            partial = "".join(chars).strip()
            if partial:
                return partial

        return ""

    @staticmethod
    def _serialize_item(item: TextLibraryItem) -> dict[str, Any]:
        return {
            "id": item.id,
            "name": item.name,
            "content": item.content,
            "source_channel": item.source_channel,
            "title_status": item.title_status,
            "content_status": item.content_status,
            "processing_stage": item.processing_stage,
            "processing_message": item.processing_message,
            "error_message": item.error_message,
            "source_url": item.source_url,
            "source_file_name": item.source_file_name,
            "source_post_id": item.source_post_id,
            "source_post_updated_at": item.source_post_updated_at,
            "is_enabled": bool(item.is_enabled),
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }

    @staticmethod
    def _serialize_import_task(task: TextLibraryImportTask) -> dict[str, Any]:
        return {
            "id": task.id,
            "source_url": task.source_url,
            "source_channel": task.source_channel,
            "status": task.status,
            "stage": task.stage,
            "stage_message": task.stage_message,
            "cache_hit": bool(task.cache_hit),
            "error_message": task.error_message,
            "cancel_requested": bool(task.cancel_requested),
            "cancel_requested_at": task.cancel_requested_at,
            "cancel_reason": task.cancel_reason,
            "retry_of_task_id": task.retry_of_task_id,
            "retry_no": int(task.retry_no or 0),
            "text_library_item_id": task.text_library_item_id,
            "source_post_id": task.source_post_id,
            "source_post_updated_at": task.source_post_updated_at,
        }

    @staticmethod
    def _is_item_ready(item: TextLibraryItem) -> bool:
        return (
            item.title_status == TextItemFieldStatus.READY
            and item.content_status == TextItemFieldStatus.READY
            and not item.error_message
        )

    @staticmethod
    def _is_item_processing(item: TextLibraryItem) -> bool:
        return item.title_status in {
            TextItemFieldStatus.PENDING,
            TextItemFieldStatus.RUNNING,
        } or item.content_status in {
            TextItemFieldStatus.PENDING,
            TextItemFieldStatus.RUNNING,
        }

    def _set_item_state(
        self,
        item: TextLibraryItem,
        *,
        title_status: TextItemFieldStatus | None = None,
        content_status: TextItemFieldStatus | None = None,
        stage: str | None = None,
        message: str | None = None,
        error: str | None = None,
    ) -> None:
        if title_status is not None:
            item.title_status = title_status
        if content_status is not None:
            item.content_status = content_status
        item.processing_stage = stage
        item.processing_message = message
        item.error_message = error

    def _set_task_state(
        self,
        task: TextLibraryImportTask,
        *,
        status: TextImportTaskStatus,
        stage: str,
        message: str | None = None,
        error: str | None = None,
    ) -> None:
        task.status = status
        task.stage = stage
        task.stage_message = message
        task.error_message = error

    def _clear_item_failed_state_on_manual_edit(self, item: TextLibraryItem) -> None:
        if item.title_status == TextItemFieldStatus.FAILED:
            item.title_status = TextItemFieldStatus.READY
        if item.content_status == TextItemFieldStatus.FAILED:
            item.content_status = TextItemFieldStatus.READY
        item.processing_stage = None
        item.processing_message = None
        item.error_message = None

    @classmethod
    def _resolve_uv_path(self) -> str:
        uv_path = shutil.which("uv")
        if uv_path:
            return uv_path
        raise ServiceError(
            400,
            (
                "未找到 uv 命令。请先安装 uv（https://docs.astral.sh/uv/getting-started/installation/），"
                "并确保命令 `uv` 在 PATH 中可用。"
            ),
        )

    @classmethod
    def _resolve_downloader_repo_path(cls, source_channel: TextSourceChannel) -> tuple[Path, str]:
        if source_channel == TextSourceChannel.XIAOHONGSHU:
            path_text = cls._normalize_text(settings.xhs_downloader_path)
            project_name = "XHS-Downloader"
            package_dir = "source"
        elif source_channel == TextSourceChannel.DOUYIN:
            path_text = cls._normalize_text(settings.tiktok_downloader_path)
            project_name = "TikTokDownloader"
            package_dir = "src"
        elif source_channel == TextSourceChannel.KUAISHOU:
            path_text = cls._normalize_text(settings.ks_downloader_path)
            project_name = "KS-Downloader"
            package_dir = "source"
        else:
            raise ServiceError(400, f"不支持的视频链接类型: {source_channel.value}")

        if not path_text:
            raise ServiceError(400, f"未配置 {project_name} 路径，请先在设置页填写")
        repo_path = Path(path_text).expanduser().resolve()
        if not repo_path.is_dir():
            raise ServiceError(400, f"{project_name} 路径不存在: {repo_path}")
        if not (repo_path / "main.py").is_file():
            raise ServiceError(400, f"{project_name} 路径无效（缺少 main.py）: {repo_path}")
        if not (repo_path / package_dir).is_dir():
            raise ServiceError(400, f"{project_name} 路径无效（缺少 {package_dir}/）: {repo_path}")
        return repo_path, project_name

    @staticmethod
    def _extract_json_payload(output_text: str) -> dict[str, Any]:
        for line in reversed(output_text.splitlines()):
            one = line.strip()
            if not one.startswith("{") or not one.endswith("}"):
                continue
            try:
                payload = json.loads(one)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(payload, dict):
                return payload
        return {}

    @classmethod
    def _extract_json_object_from_text(cls, output_text: str) -> dict[str, Any]:
        text = cls._normalize_text(output_text)
        if not text:
            return {}

        # 兼容 ```json ... ``` 代码块
        fenced = re.sub(r"^\s*```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        fenced = re.sub(r"\s*```\s*$", "", fenced, flags=re.IGNORECASE).strip()

        candidates = [text]
        if fenced and fenced != text:
            candidates.append(fenced)

        for candidate in candidates:
            try:
                payload = json.loads(candidate)
                if isinstance(payload, dict):
                    return payload
            except Exception:  # noqa: BLE001
                pass

            payload = cls._extract_json_payload(candidate)
            if payload:
                return payload

            decoder = json.JSONDecoder()
            for idx, ch in enumerate(candidate):
                if ch != "{":
                    continue
                try:
                    parsed, end = decoder.raw_decode(candidate[idx:])
                except Exception:  # noqa: BLE001
                    continue
                if end <= 0:
                    continue
                if isinstance(parsed, dict):
                    return parsed

        return {}

    @staticmethod
    def _pick_downloader_script(source_channel: TextSourceChannel) -> str:
        if source_channel == TextSourceChannel.XIAOHONGSHU:
            return XHS_DOWNLOADER_INLINE_SCRIPT
        if source_channel == TextSourceChannel.DOUYIN:
            return TIKTOK_DOWNLOADER_INLINE_SCRIPT
        if source_channel == TextSourceChannel.KUAISHOU:
            return KS_DOWNLOADER_INLINE_SCRIPT
        raise ServiceError(400, f"不支持的视频链接类型: {source_channel.value}")

    @classmethod
    def _normalize_downloader_source_url(
        cls,
        *,
        source_url: str,
        source_channel: TextSourceChannel,
    ) -> str:
        normalized = cls._normalize_text(source_url)
        if not normalized or source_channel != TextSourceChannel.DOUYIN:
            return normalized

        parsed = urlparse(normalized)
        host = (parsed.netloc or "").lower()
        if "douyin.com" not in host and "iesdouyin.com" not in host:
            return normalized

        path = str(parsed.path or "")
        if re.search(r"/(video|note)/[0-9A-Za-z_-]+", path):
            return normalized

        query = parse_qs(parsed.query or "", keep_blank_values=False)
        for key in ("modal_id", "aweme_id", "group_id", "item_id"):
            candidate = cls._normalize_text((query.get(key) or [""])[0])
            if candidate and re.fullmatch(r"[0-9]{8,32}", candidate):
                return f"https://www.douyin.com/video/{candidate}"

        return normalized

    @classmethod
    def _infer_media_kind_by_url(cls, media_url: str) -> str:
        normalized = cls._normalize_text(media_url).lower()
        if not normalized:
            return "unknown"
        suffix = Path(urlparse(normalized).path or "").suffix.lower().strip()
        if suffix in IMAGE_SUFFIXES:
            return "image"
        if suffix in VIDEO_SUFFIXES:
            return "video"
        if "imageview2" in normalized or "format/jpeg" in normalized or "format/png" in normalized:
            return "image"
        return "unknown"

    @classmethod
    def _normalize_media_kind(cls, raw_kind: str, media_url: str) -> str:
        normalized = cls._normalize_text(raw_kind).lower()
        if any(token in normalized for token in ("video", "视频")):
            return "video"
        if any(token in normalized for token in ("image", "photo", "图文", "图集", "图片", "实况")):
            return "image"
        inferred = cls._infer_media_kind_by_url(media_url)
        return inferred

    @classmethod
    def _normalize_post_timestamp(cls, value: str | None) -> str | None:
        normalized = cls._normalize_text(value)
        return normalized or None

    @classmethod
    def _compose_media_content(
        cls,
        *,
        title: str,
        note_text: str,
        transcript_text: str,
    ) -> str:
        lines: list[str] = []
        clean_title = cls._normalize_text(title)
        clean_note = cls._normalize_text(note_text)
        clean_transcript = cls._normalize_text(transcript_text)
        if clean_title:
            lines.append(f"标题：{clean_title}")
        if clean_note:
            lines.append(f"文案：{clean_note}")
        if clean_transcript:
            lines.append(f"视频转写：{clean_transcript}")
        return "\n".join(lines).strip()

    async def _extract_media_url_by_downloader(
        self,
        *,
        source_url: str,
        source_channel: TextSourceChannel,
    ) -> dict[str, str]:
        normalized_source_url = self._normalize_downloader_source_url(
            source_url=source_url,
            source_channel=source_channel,
        )
        if normalized_source_url != source_url:
            logger.info(
                "[TextLibrary][Downloader] normalized channel=%s from=%s to=%s",
                source_channel.value,
                source_url,
                normalized_source_url,
            )
        repo_path, project_name = self._resolve_downloader_repo_path(source_channel)
        uv_path = self._resolve_uv_path()
        inline_script = self._pick_downloader_script(source_channel)

        command = [
            uv_path,
            "run",
            "python",
            "-c",
            inline_script,
            str(repo_path),
            normalized_source_url,
        ]
        logger.info(
            "[TextLibrary][Downloader] start channel=%s url=%s command=%s",
            source_channel.value,
            normalized_source_url,
            command[:3] + ["<inline_script>"] + command[4:],
        )
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(repo_path),
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=360)
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise ServiceError(500, f"{project_name} 执行超时，请检查链接或运行环境") from exc

        stdout_text = stdout.decode(errors="ignore").strip()
        stderr_text = stderr.decode(errors="ignore").strip()
        if process.returncode != 0:
            tail_output = self._truncate_log_text(f"{stdout_text}\n{stderr_text}", 1400)
            suffix = ""
            if source_channel == TextSourceChannel.DOUYIN:
                suffix = "。请确认设置页路径指向可运行版本（当前上游仓库部分版本存在语法问题）"
            raise ServiceError(
                500,
                f"{project_name} 执行失败（code={process.returncode}）: {tail_output}{suffix}",
            )

        output_payload = self._extract_json_payload(stdout_text)
        media_url = self._normalize_text(str(output_payload.get("media_url") or ""))
        title = self._normalize_text(str(output_payload.get("title") or ""))
        content = self._normalize_text(str(output_payload.get("content") or ""))
        media_kind = self._normalize_media_kind(
            str(output_payload.get("media_type") or ""), media_url
        )
        post_id = self._normalize_text(str(output_payload.get("post_id") or ""))
        post_updated_at = self._normalize_post_timestamp(
            str(output_payload.get("post_updated_at") or "")
        )

        if media_url:
            parsed = urlparse(media_url)
            if not parsed.scheme or not parsed.netloc:
                raise ServiceError(500, f"{project_name} 返回的媒体地址无效: {media_url}")
        if not title and not content and not media_url:
            raise ServiceError(500, f"{project_name} 未返回可用内容，请确认链接公开可访问")

        logger.info(
            "[TextLibrary][Downloader] done channel=%s media_kind=%s post_id=%s media_url=%s title=%s content_len=%s",
            source_channel.value,
            media_kind,
            post_id or "-",
            media_url,
            self._truncate_log_text(title, 80),
            len(content),
        )
        return {
            "media_url": media_url,
            "media_kind": media_kind,
            "title": title,
            "content": content,
            "post_id": post_id,
            "post_updated_at": post_updated_at or "",
        }

    @staticmethod
    def _guess_media_suffix(media_url: str) -> str:
        suffix = Path(urlparse(media_url).path or "").suffix.lower().strip()
        if not suffix:
            return ".mp4"
        if not re.match(r"^\.[a-z0-9]{1,8}$", suffix):
            return ".mp4"
        return suffix

    @staticmethod
    def _sanitize_path_part(value: str, *, default: str = "unknown", max_len: int = 80) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            return default
        cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", normalized)
        cleaned = cleaned.strip("._-")
        if not cleaned:
            return default
        return cleaned[:max_len]

    async def _download_media_file(
        self,
        *,
        media_url: str,
        source_channel: TextSourceChannel,
        task_id: int,
        post_id: str | None = None,
        post_updated_at: str | None = None,
    ) -> tuple[Path, bool]:
        channel_key = self._sanitize_path_part(source_channel.value, default="media", max_len=24)
        post_key = self._sanitize_path_part(post_id or "", default=f"task{task_id}", max_len=80)
        updated_key = self._sanitize_path_part(post_updated_at or "", default="latest", max_len=48)
        suffix = self._guess_media_suffix(media_url)
        output_path = (
            self._text_library_video_cache_dir() / channel_key / f"{updated_key}_{post_key}{suffix}"
        )

        if output_path.is_file():
            file_size = int(output_path.stat().st_size or 0)
            if file_size > 0:
                logger.info(
                    "[TextLibrary][Download] cache hit task_id=%s channel=%s path=%s size=%s",
                    task_id,
                    source_channel.value,
                    output_path,
                    file_size,
                )
                return output_path, True

        timeout = httpx.Timeout(timeout=300, connect=30)
        total_bytes = 0
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_output_path = output_path.with_name(f"{output_path.name}.part")
        if temp_output_path.exists():
            temp_output_path.unlink(missing_ok=True)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                async with client.stream("GET", media_url) as response:
                    response.raise_for_status()
                    with temp_output_path.open("wb") as file_obj:
                        async for chunk in response.aiter_bytes():
                            if not chunk:
                                continue
                            file_obj.write(chunk)
                            total_bytes += len(chunk)
        except httpx.HTTPError as exc:
            temp_output_path.unlink(missing_ok=True)
            raise ServiceError(500, f"媒体下载失败: {exc}") from exc

        if total_bytes <= 0:
            temp_output_path.unlink(missing_ok=True)
            raise ServiceError(500, "媒体下载结果为空，无法执行转写")
        temp_output_path.replace(output_path)
        if not output_path.is_file():
            raise ServiceError(500, "媒体下载结果为空，无法执行转写")

        logger.info(
            "[TextLibrary][Download] task_id=%s channel=%s path=%s size=%s",
            task_id,
            source_channel.value,
            output_path,
            total_bytes,
        )
        return output_path, False

    @classmethod
    async def _run_import_job_background(cls, job_id: str) -> None:
        async with AsyncSessionLocal() as db:
            service = cls(db)
            try:
                await service._execute_import_job(job_id)
            except asyncio.CancelledError:
                logger.info("[TextLibrary][ImportJob] runner canceled job_id=%s", job_id)
                try:
                    await db.rollback()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    await service._mark_import_job_canceled_after_abort(
                        job_id, reason="user_cancel_all"
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "[TextLibrary][ImportJob] failed to mark canceled after abort job_id=%s",
                        job_id,
                    )
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("Text library import job failed: %s", job_id)
                try:
                    await db.rollback()
                except Exception:  # noqa: BLE001
                    pass
                await service._mark_import_job_failed(job_id, str(exc))

    @classmethod
    def _launch_job_runner(cls, job_id: str) -> None:
        existing = cls._job_tasks.get(job_id)
        if existing and not existing.done():
            return
        task = asyncio.create_task(cls._run_import_job_background(job_id))
        cls._job_tasks[job_id] = task

        def _cleanup(done_task: asyncio.Task[None]) -> None:
            stored = cls._job_tasks.get(job_id)
            if stored is done_task:
                cls._job_tasks.pop(job_id, None)

        task.add_done_callback(_cleanup)

    @classmethod
    def _request_hard_cancel_job_runner(cls, job_id: str) -> bool:
        runner = cls._job_tasks.get(str(job_id))
        if not runner or runner.done():
            return False
        runner.cancel()
        return True

    @classmethod
    async def reconcile_stale_import_jobs(
        cls, *, stale_seconds: int | None = None
    ) -> dict[str, int]:
        timeout_seconds = int(
            stale_seconds or getattr(settings, "library_import_stale_timeout_seconds", 300) or 300
        )
        timeout_seconds = max(30, timeout_seconds)
        cutoff = datetime.utcnow() - timedelta(seconds=timeout_seconds)
        now = datetime.utcnow()

        async with AsyncSessionLocal() as db:
            service = cls(db)
            stale_task_result = await db.execute(
                select(TextLibraryImportTask)
                .join(
                    TextLibraryImportJob,
                    TextLibraryImportTask.job_id == TextLibraryImportJob.id,
                )
                .where(
                    TextLibraryImportJob.status.in_(
                        [TextImportJobStatus.PENDING, TextImportJobStatus.RUNNING]
                    ),
                    TextLibraryImportTask.status.in_(
                        [TextImportTaskStatus.PENDING, TextImportTaskStatus.RUNNING]
                    ),
                    TextLibraryImportTask.updated_at < cutoff,
                )
            )
            stale_tasks = list(stale_task_result.scalars().all())

            stale_job_result = await db.execute(
                select(TextLibraryImportJob).where(
                    TextLibraryImportJob.status.in_(
                        [TextImportJobStatus.PENDING, TextImportJobStatus.RUNNING]
                    ),
                    TextLibraryImportJob.updated_at < cutoff,
                )
            )
            stale_jobs = list(stale_job_result.scalars().all())

            running_job_ids = {
                job_id for job_id, runner in cls._job_tasks.items() if not runner.done()
            }
            if running_job_ids:
                stale_tasks = [one for one in stale_tasks if str(one.job_id) not in running_job_ids]
                stale_jobs = [one for one in stale_jobs if str(one.id) not in running_job_ids]

            if not stale_tasks and not stale_jobs:
                return {"reconciled_jobs": 0, "reconciled_tasks": 0}

            job_ids = {str(one.id) for one in stale_jobs}
            job_ids.update(str(one.job_id) for one in stale_tasks)

            jobs_result = await db.execute(
                select(TextLibraryImportJob).where(TextLibraryImportJob.id.in_(job_ids))
            )
            job_map = {str(one.id): one for one in jobs_result.scalars().all()}

            item_ids = {
                int(one.text_library_item_id) for one in stale_tasks if one.text_library_item_id
            }
            item_map: dict[int, TextLibraryItem] = {}
            if item_ids:
                item_result = await db.execute(
                    select(TextLibraryItem).where(TextLibraryItem.id.in_(item_ids))
                )
                item_map = {int(one.id): one for one in item_result.scalars().all()}

            reconciled_tasks = 0
            for task in stale_tasks:
                job = job_map.get(str(task.job_id))
                if not job:
                    continue
                if task.status not in {
                    TextImportTaskStatus.PENDING,
                    TextImportTaskStatus.RUNNING,
                }:
                    continue
                service._mark_task_and_item_canceled(
                    task=task,
                    item=item_map.get(int(task.text_library_item_id or 0)),
                    job=job,
                    reason="system_timeout",
                    stage_message="任务超时自动中断",
                )
                job.cancel_requested = True
                if job.cancel_requested_at is None:
                    job.cancel_requested_at = now
                if not job.cancel_requested_by:
                    job.cancel_requested_by = "system"
                reconciled_tasks += 1

            reconciled_jobs = 0
            for job_id in job_ids:
                job = job_map.get(job_id)
                if not job:
                    continue
                if job.status not in {
                    TextImportJobStatus.PENDING,
                    TextImportJobStatus.RUNNING,
                }:
                    continue

                active_result = await db.execute(
                    select(TextLibraryImportTask.id).where(
                        TextLibraryImportTask.job_id == job.id,
                        TextLibraryImportTask.status.in_(
                            [TextImportTaskStatus.PENDING, TextImportTaskStatus.RUNNING]
                        ),
                    )
                )
                if active_result.first() is not None:
                    continue

                if (
                    int(job.success_count or 0) == 0
                    and int(job.failed_count or 0) == 0
                    and int(job.canceled_count or 0) > 0
                ):
                    job.status = TextImportJobStatus.CANCELED
                    job.error_message = None
                elif int(job.success_count or 0) == 0 and int(job.failed_count or 0) > 0:
                    job.status = TextImportJobStatus.FAILED
                    if not job.error_message:
                        job.error_message = "所有链接导入均失败"
                else:
                    job.status = TextImportJobStatus.COMPLETED
                    job.error_message = None
                job.terminal_at = now
                reconciled_jobs += 1

            if reconciled_tasks > 0 or reconciled_jobs > 0:
                await db.commit()
                logger.warning(
                    "[TextLibrary][Reconciler] reconciled stale tasks=%s jobs=%s timeout=%ss",
                    reconciled_tasks,
                    reconciled_jobs,
                    timeout_seconds,
                )
            return {"reconciled_jobs": reconciled_jobs, "reconciled_tasks": reconciled_tasks}

    @classmethod
    async def _run_item_title_background(
        cls,
        *,
        item_id: int,
        content: str,
        source_channel: TextSourceChannel,
        source_url: str | None,
        source_file_name: str | None,
    ) -> None:
        async with AsyncSessionLocal() as db:
            service = cls(db)
            result = await db.execute(select(TextLibraryItem).where(TextLibraryItem.id == item_id))
            item = result.scalar_one_or_none()
            if not item:
                return

            service._set_item_state(
                item,
                title_status=TextItemFieldStatus.RUNNING,
                stage=ITEM_STAGE_GENERATING,
                message="生成中：正在生成标题",
                error=None,
            )
            await db.commit()

            try:
                title = await run_card_stage(
                    stage=CardStage.TEXT_NAME,
                    label=f"text:title:item:{item_id}",
                    priority=220,
                    coro_factory=lambda: service._auto_name_text(
                        content=content,
                        source_channel=source_channel,
                        source_url=source_url,
                        source_file_name=source_file_name,
                    ),
                )
                item.name = service._normalize_name(title)
                service._set_item_state(
                    item,
                    title_status=TextItemFieldStatus.READY,
                    stage=ITEM_STAGE_READY
                    if item.content_status == TextItemFieldStatus.READY
                    else ITEM_STAGE_PENDING,
                    message=None
                    if item.content_status == TextItemFieldStatus.READY
                    else item.processing_message,
                    error=None,
                )
            except Exception as exc:  # noqa: BLE001
                service._set_item_state(
                    item,
                    title_status=TextItemFieldStatus.FAILED,
                    stage=ITEM_STAGE_FAILED,
                    message="生成失败",
                    error=service._truncate_log_text(str(exc), 1000),
                )
            await db.commit()

    @classmethod
    def _launch_item_title_runner(
        cls,
        *,
        item_id: int,
        content: str,
        source_channel: TextSourceChannel,
        source_url: str | None,
        source_file_name: str | None,
    ) -> None:
        existing = cls._title_tasks.get(item_id)
        if existing and not existing.done():
            return
        task = asyncio.create_task(
            cls._run_item_title_background(
                item_id=item_id,
                content=content,
                source_channel=source_channel,
                source_url=source_url,
                source_file_name=source_file_name,
            )
        )
        cls._title_tasks[item_id] = task

        def _cleanup(done_task: asyncio.Task[None]) -> None:
            stored = cls._title_tasks.get(item_id)
            if stored is done_task:
                cls._title_tasks.pop(item_id, None)

        task.add_done_callback(_cleanup)

    async def list(
        self,
        *,
        q: str | None = None,
        enabled_only: bool = False,
        page: int | None = None,
        page_size: int | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        query = select(TextLibraryItem)
        count_query = select(func.count()).select_from(TextLibraryItem)

        keyword = self._normalize_text(q)
        if keyword:
            like_pattern = f"%{keyword}%"
            query = query.where(TextLibraryItem.name.ilike(like_pattern))
            count_query = count_query.where(TextLibraryItem.name.ilike(like_pattern))

        if enabled_only:
            query = query.where(TextLibraryItem.is_enabled.is_(True))
            count_query = count_query.where(TextLibraryItem.is_enabled.is_(True))

        query = query.order_by(TextLibraryItem.id.desc())
        total_result = await self.db.execute(count_query)
        total = int(total_result.scalar() or 0)

        if page is not None and page_size is not None:
            query = query.offset((page - 1) * page_size).limit(page_size)

        result = await self.db.execute(query)
        items = list(result.scalars().all())
        return [self._serialize_item(item) for item in items], total

    async def get(self, item_id: int) -> TextLibraryItem | None:
        result = await self.db.execute(select(TextLibraryItem).where(TextLibraryItem.id == item_id))
        return result.scalar_one_or_none()

    @staticmethod
    def _create_import_job_id() -> str:
        return f"job_{int(time.time() * 1000)}_{secrets.token_hex(4)}"

    async def _create_item(
        self,
        *,
        name: str,
        content: str,
        source_channel: TextSourceChannel,
        source_url: str | None = None,
        source_file_name: str | None = None,
        title_status: TextItemFieldStatus = TextItemFieldStatus.READY,
        content_status: TextItemFieldStatus = TextItemFieldStatus.READY,
        processing_stage: str | None = None,
        processing_message: str | None = None,
        error_message: str | None = None,
        source_post_id: str | None = None,
        source_post_updated_at: str | None = None,
        allow_empty_content: bool = False,
        auto_commit: bool = True,
    ) -> TextLibraryItem:
        normalized_content = self._normalize_text(content)
        if not allow_empty_content and not normalized_content:
            raise ServiceError(400, "文本内容不能为空")

        item = TextLibraryItem(
            name=self._normalize_name(name),
            content=normalized_content,
            source_channel=source_channel,
            title_status=title_status,
            content_status=content_status,
            processing_stage=processing_stage,
            processing_message=processing_message,
            error_message=error_message,
            source_url=self._normalize_text(source_url) or None,
            source_file_name=self._normalize_text(source_file_name) or None,
            source_post_id=self._normalize_text(source_post_id) or None,
            source_post_updated_at=self._normalize_post_timestamp(source_post_updated_at),
            is_enabled=True,
        )
        self.db.add(item)
        await self.db.flush()

        if auto_commit:
            await self.db.commit()
            await self.db.refresh(item)
        return item

    async def import_from_copy(self, content: str) -> dict[str, Any]:
        normalized_content = self._normalize_text(content)
        if not normalized_content:
            raise ServiceError(400, "文本内容不能为空")
        logger.info("[TextLibrary][ImportCopy] len=%s", len(normalized_content))
        item = await self._create_item(
            name="生成中",
            content=normalized_content,
            source_channel=TextSourceChannel.COPY,
            title_status=TextItemFieldStatus.PENDING,
            content_status=TextItemFieldStatus.READY,
            processing_stage=ITEM_STAGE_GENERATING,
            processing_message="生成中：正在生成标题",
        )
        self._launch_item_title_runner(
            item_id=item.id,
            content=normalized_content,
            source_channel=TextSourceChannel.COPY,
            source_url=None,
            source_file_name=None,
        )
        logger.info("[TextLibrary][ImportCopy] created item_id=%s", item.id)
        return self._serialize_item(item)

    async def import_from_files(self, files: list[UploadFile]) -> list[dict[str, Any]]:
        batch_limit = get_library_batch_max_items()
        if not files:
            raise ServiceError(400, "请至少上传一个文件")
        if len(files) > batch_limit:
            raise ServiceError(400, f"最多支持上传 {batch_limit} 个文件")

        created_models: list[TextLibraryItem] = []
        title_inputs: list[tuple[int, str, str]] = []
        total_upload_bytes = 0
        total_upload_limit = get_library_batch_max_total_upload_bytes()
        try:
            for file in files:
                filename = self._normalize_text(file.filename)
                suffix = Path(filename).suffix.lower()
                if suffix not in SUPPORTED_TEXT_EXTENSIONS:
                    raise ServiceError(400, "仅支持 txt 和 markdown 文件")

                raw_bytes = await file.read()
                total_upload_bytes += len(raw_bytes)
                if total_upload_bytes > total_upload_limit:
                    raise ServiceError(
                        400,
                        (
                            f"批量上传文本文件总大小不能超过 {get_library_batch_max_total_upload_mb()} MB，"
                            f"当前约 {total_upload_bytes / 1024 / 1024:.1f} MB"
                        ),
                    )
                content = self._decode_file_content(raw_bytes)
                if not content:
                    raise ServiceError(400, f"文件内容为空: {filename}")

                logger.info(
                    "[TextLibrary][ImportFile] filename=%s size=%s preview=%s",
                    filename,
                    len(raw_bytes),
                    self._truncate_log_text(content, 300),
                )
                item = await self._create_item(
                    name="生成中",
                    content=content,
                    source_channel=TextSourceChannel.FILE,
                    source_file_name=filename,
                    title_status=TextItemFieldStatus.PENDING,
                    content_status=TextItemFieldStatus.READY,
                    processing_stage=ITEM_STAGE_GENERATING,
                    processing_message="生成中：正在生成标题",
                    auto_commit=False,
                )
                created_models.append(item)
                title_inputs.append((item.id, content, filename))
                logger.info(
                    "[TextLibrary][ImportFile] created item_id=%s filename=%s", item.id, filename
                )
        finally:
            for file in files:
                await file.close()
        await self.db.commit()

        for item_id, content, filename in title_inputs:
            self._launch_item_title_runner(
                item_id=item_id,
                content=content,
                source_channel=TextSourceChannel.FILE,
                source_url=None,
                source_file_name=filename,
            )

        return [self._serialize_item(item) for item in created_models]

    @staticmethod
    def _resolve_web_url_parser_provider() -> str:
        provider = str(getattr(settings, "web_url_parser_provider", "") or "").strip().lower()
        if provider in {WEB_URL_PARSER_JINA_READER, WEB_URL_PARSER_CRAWL4AI}:
            return provider
        return WEB_URL_PARSER_JINA_READER

    async def _extract_text_from_jina_reader(self, source_url: str) -> str:
        reader_url = f"https://r.jina.ai/{source_url}"
        jina_reader_api_key = self._normalize_text(settings.jina_reader_api_key)
        jina_reader_ignore_images = bool(getattr(settings, "jina_reader_ignore_images", True))
        headers: dict[str, str] = {}
        if jina_reader_api_key:
            headers["Authorization"] = f"Bearer {jina_reader_api_key}"
            headers["X-API-Key"] = jina_reader_api_key
        headers["X-Remove-Selector"] = JINA_READER_REMOVE_SELECTOR
        headers["X-Retain-Images"] = "none" if jina_reader_ignore_images else "all"

        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            response = await client.get(reader_url, headers=headers or None)
            response.raise_for_status()
            text = self._normalize_text(response.text)
            if not text:
                raise ServiceError(400, "网页可见文本为空，可能是付费内容或反爬限制")
            return text

    async def _extract_text_from_crawl4ai(self, source_url: str) -> str:
        crawl4ai_ignore_images = bool(getattr(settings, "crawl4ai_ignore_images", True))
        crawl4ai_ignore_links = bool(getattr(settings, "crawl4ai_ignore_links", True))
        logger.info(
            "[TextLibrary][Crawl4AI] start url=%s ignore_images=%s ignore_links=%s",
            source_url,
            crawl4ai_ignore_images,
            crawl4ai_ignore_links,
        )
        try:
            text = await asyncio.wait_for(
                extract_text_with_crawl4ai(
                    source_url,
                    ignore_images=crawl4ai_ignore_images,
                    ignore_links=crawl4ai_ignore_links,
                ),
                timeout=240,
            )
        except TimeoutError as exc:
            raise ServiceError(500, "Crawl4AI 执行超时，请检查目标网页或运行环境") from exc
        except RuntimeError as exc:
            raise ServiceError(500, f"Crawl4AI 执行失败: {exc}") from exc

        text = self._normalize_text(text)
        if not text:
            raise ServiceError(400, "网页可见文本为空，可能是动态渲染失败或目标页面不可访问")
        return text

    async def _extract_text_from_web_url(self, source_url: str) -> str:
        provider = self._resolve_web_url_parser_provider()
        if provider == WEB_URL_PARSER_CRAWL4AI:
            text = await self._extract_text_from_crawl4ai(source_url)
        else:
            text = await self._extract_text_from_jina_reader(source_url)
        line_count = len(text.splitlines()) or 1
        logger.info(
            "[TextLibrary][Extract] provider=%s type=web channel=%s post_id=%s post_updated_at=%s url=%s chars=%s lines=%s",
            provider,
            TextSourceChannel.WEB.value,
            "-",
            "-",
            source_url,
            len(text),
            line_count,
        )
        return text

    async def _get_post_cache(
        self,
        *,
        source_channel: TextSourceChannel,
        post_id: str,
    ) -> TextLibraryPostCache | None:
        if not post_id:
            return None
        result = await self.db.execute(
            select(TextLibraryPostCache).where(
                TextLibraryPostCache.source_channel == source_channel,
                TextLibraryPostCache.post_id == post_id,
            )
        )
        return result.scalar_one_or_none()

    async def _upsert_post_cache(
        self,
        *,
        source_channel: TextSourceChannel,
        post_id: str,
        post_updated_at: str | None,
        source_url: str | None,
        media_kind: str | None,
        media_url: str | None,
        title_text: str | None,
        note_text: str | None,
        transcript_text: str | None,
        combined_content: str,
        generated_title: str | None = None,
    ) -> TextLibraryPostCache | None:
        if not post_id:
            return None
        normalized_title = self._normalize_text(title_text) or None
        normalized_note = self._normalize_text(note_text) or None
        normalized_transcript = self._normalize_text(transcript_text) or None
        normalized_content = self._normalize_text(combined_content)

        cache = await self._get_post_cache(source_channel=source_channel, post_id=post_id)
        if cache is None:
            cache = TextLibraryPostCache(
                source_channel=source_channel,
                post_id=post_id,
                post_updated_at=post_updated_at,
                source_url=source_url,
                media_kind=media_kind,
                media_url=media_url,
                title_text=normalized_title,
                note_text=normalized_note,
                transcript_text=normalized_transcript,
                combined_content=normalized_content,
                generated_title=generated_title,
            )
            self.db.add(cache)
            await self.db.flush()
            return cache

        cache.post_updated_at = post_updated_at
        cache.source_url = source_url
        cache.media_kind = media_kind
        cache.media_url = media_url
        cache.title_text = normalized_title
        cache.note_text = normalized_note
        cache.transcript_text = normalized_transcript
        cache.combined_content = normalized_content
        if generated_title is not None:
            cache.generated_title = generated_title
        await self.db.flush()
        return cache

    @staticmethod
    def _is_cache_fresh(
        *,
        cache: TextLibraryPostCache | None,
        latest_post_updated_at: str | None,
    ) -> bool:
        if cache is None:
            return False
        if not latest_post_updated_at:
            return False
        return str(cache.post_updated_at or "").strip() == str(latest_post_updated_at or "").strip()

    async def _prepare_link_task_payload(
        self,
        *,
        task: TextLibraryImportTask,
    ) -> dict[str, Any]:
        source_url = self._normalize_text(task.source_url)
        source_channel = task.source_channel

        if source_channel == TextSourceChannel.WEB:
            content = await run_card_stage(
                stage=CardStage.PARSE,
                label=f"text:parse:web:task:{task.id}",
                priority=120,
                coro_factory=lambda: self._extract_text_from_web_url(source_url),
            )
            return {
                "needs_transcribe": False,
                "content": content,
                "title_text": "",
                "note_text": "",
                "media_kind": "web",
                "media_url": "",
                "post_id": "",
                "post_updated_at": None,
                "cache_hit": False,
                "cache_id": None,
            }

        if source_channel not in MEDIA_CHANNELS:
            raise ServiceError(400, f"不支持的链接类型: {source_channel.value}")

        payload = await run_card_stage(
            stage=CardStage.PARSE,
            label=f"text:parse:post:task:{task.id}",
            priority=120,
            coro_factory=lambda: self._extract_media_url_by_downloader(
                source_url=source_url,
                source_channel=source_channel,
            ),
        )
        media_kind = self._normalize_text(payload.get("media_kind")) or "unknown"
        media_url = self._normalize_text(payload.get("media_url"))
        title_text = self._normalize_text(payload.get("title"))
        note_text = self._normalize_text(payload.get("content"))
        if source_channel in {TextSourceChannel.DOUYIN, TextSourceChannel.KUAISHOU}:
            title_text = ""
        post_id = self._normalize_text(payload.get("post_id"))
        post_updated_at = self._normalize_post_timestamp(payload.get("post_updated_at"))

        cache = await self._get_post_cache(source_channel=source_channel, post_id=post_id)
        post_cache_id = cache.id if cache else None

        combined_without_transcript = self._compose_media_content(
            title=title_text,
            note_text=note_text,
            transcript_text="",
        )
        logger.info(
            "[TextLibrary][Extract] type=post channel=%s post_id=%s post_updated_at=%s cache_hit=%s media_kind=%s preview=%s",
            source_channel.value,
            post_id or "-",
            post_updated_at or "-",
            False,
            media_kind,
            self._truncate_log_text(combined_without_transcript, 1000),
        )
        if media_kind != "video":
            return {
                "needs_transcribe": False,
                "content": combined_without_transcript,
                "title_text": title_text,
                "note_text": note_text,
                "media_kind": media_kind,
                "media_url": media_url,
                "post_id": post_id,
                "post_updated_at": post_updated_at,
                "cache_hit": False,
                "cache_id": post_cache_id,
            }

        if not media_url:
            raise ServiceError(500, "视频贴未返回可用视频地址，无法转写")
        return {
            "needs_transcribe": True,
            "content": combined_without_transcript,
            "title_text": title_text,
            "note_text": note_text,
            "media_kind": media_kind,
            "media_url": media_url,
            "post_id": post_id,
            "post_updated_at": post_updated_at,
            "cache_hit": False,
            "cache_id": post_cache_id,
        }

    async def _transcribe_video_task(
        self,
        *,
        task: TextLibraryImportTask,
        media_url: str,
        source_channel: TextSourceChannel,
        post_id: str | None,
        post_updated_at: str | None,
        on_progress: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> tuple[str, bool]:
        media_path, download_cache_hit = await run_card_stage(
            stage=CardStage.DOWNLOAD,
            label=f"text:download:task:{task.id}",
            priority=80,
            coro_factory=lambda: self._download_media_file(
                media_url=media_url,
                source_channel=source_channel,
                task_id=task.id,
                post_id=post_id,
                post_updated_at=post_updated_at,
            ),
        )
        logger.info("[TextLibrary][ASR] start task_id=%s media=%s", task.id, media_path)
        words = await run_card_stage(
            stage=CardStage.TRANSCRIBE,
            label=f"text:transcribe:task:{task.id}",
            priority=90,
            coro_factory=lambda: transcribe_audio_words(media_path, on_progress=on_progress),
        )
        transcript_text = self._join_whisper_words(words)
        if not transcript_text:
            raise ServiceError(500, "语音识别未识别出有效文本")
        logger.info(
            "[TextLibrary][ASR] done task_id=%s words=%s preview=%s",
            task.id,
            len(words),
            self._truncate_log_text(transcript_text, 300),
        )
        return transcript_text, download_cache_hit

    async def create_link_import_job(self, urls_text: str) -> dict[str, Any]:
        normalized_urls = self._split_urls(urls_text)
        batch_limit = get_library_batch_max_items()
        if not normalized_urls:
            raise ServiceError(400, "未识别到有效链接")
        if len(normalized_urls) > batch_limit:
            raise ServiceError(400, f"最多支持 {batch_limit} 个链接")

        job_ids: list[str] = []
        created_item_ids: list[int] = []
        for one_url in normalized_urls:
            source_channel = self._detect_channel_by_url(one_url)
            job_id = self._create_import_job_id()
            job_ids.append(job_id)
            self.db.add(
                TextLibraryImportJob(
                    id=job_id,
                    status=TextImportJobStatus.PENDING,
                    total_count=1,
                    completed_count=0,
                    success_count=0,
                    failed_count=0,
                    canceled_count=0,
                    cancel_requested=False,
                    cancel_requested_at=None,
                    cancel_requested_by=None,
                    terminal_at=None,
                    error_message=None,
                )
            )
            item = await self._create_item(
                name="解析中",
                content="",
                source_channel=source_channel,
                source_url=one_url,
                title_status=TextItemFieldStatus.PENDING,
                content_status=TextItemFieldStatus.PENDING,
                processing_stage=ITEM_STAGE_PENDING,
                processing_message="解析中：等待处理",
                allow_empty_content=True,
                auto_commit=False,
            )
            created_item_ids.append(int(item.id))
            self.db.add(
                TextLibraryImportTask(
                    job_id=job_id,
                    source_url=one_url,
                    source_channel=source_channel,
                    status=TextImportTaskStatus.PENDING,
                    stage=TASK_STAGE_PENDING,
                    stage_message="等待处理",
                    cache_hit=False,
                    error_message=None,
                    cancel_requested=False,
                    cancel_requested_at=None,
                    cancel_reason=None,
                    retry_of_task_id=None,
                    retry_no=0,
                    text_library_item_id=item.id,
                )
            )

        await self.db.commit()
        for job_id in job_ids:
            self._launch_job_runner(job_id)
        logger.info(
            "[TextLibrary][ImportLinks] jobs created job_ids=%s count=%s",
            job_ids,
            len(normalized_urls),
        )
        if not job_ids:
            raise ServiceError(500, "导入任务创建失败")
        return {"job_id": job_ids[0], "job_ids": job_ids, "item_ids": created_item_ids}

    async def retry_item(self, item_id: int) -> dict[str, Any]:
        item = await self.get(item_id)
        if not item:
            raise ServiceError(404, "文本卡片不存在")
        if self._is_item_processing(item):
            raise ServiceError(409, "文本仍在处理中，无需重试")

        source_channel = item.source_channel
        if source_channel in {TextSourceChannel.COPY, TextSourceChannel.FILE}:
            normalized_content = self._normalize_text(item.content)
            if not normalized_content:
                raise ServiceError(400, "文本内容为空，无法重试")
            self._set_item_state(
                item,
                title_status=TextItemFieldStatus.PENDING,
                content_status=TextItemFieldStatus.READY,
                stage=ITEM_STAGE_GENERATING,
                message="生成中：正在生成标题",
                error=None,
            )
            if not self._normalize_text(item.name):
                item.name = "生成中"
            await self.db.commit()
            await self.db.refresh(item)

            self._launch_item_title_runner(
                item_id=item.id,
                content=normalized_content,
                source_channel=source_channel,
                source_url=self._normalize_text(item.source_url) or None,
                source_file_name=self._normalize_text(item.source_file_name) or None,
            )
            logger.info(
                "[TextLibrary][Retry] restart title generation item_id=%s channel=%s",
                item.id,
                source_channel.value,
            )
            return self._serialize_item(item)

        if source_channel in {
            TextSourceChannel.WEB,
            TextSourceChannel.XIAOHONGSHU,
            TextSourceChannel.DOUYIN,
            TextSourceChannel.KUAISHOU,
        }:
            source_url = self._normalize_text(item.source_url)
            if not source_url:
                raise ServiceError(400, "当前卡片缺少源链接，无法重试")

            job_id = self._create_import_job_id()
            job = TextLibraryImportJob(
                id=job_id,
                status=TextImportJobStatus.PENDING,
                total_count=1,
                completed_count=0,
                success_count=0,
                failed_count=0,
                canceled_count=0,
                cancel_requested=False,
                cancel_requested_at=None,
                cancel_requested_by=None,
                terminal_at=None,
                error_message=None,
            )
            self.db.add(job)

            self._set_item_state(
                item,
                title_status=TextItemFieldStatus.PENDING,
                content_status=TextItemFieldStatus.PENDING,
                stage=ITEM_STAGE_PENDING,
                message="解析中：等待处理",
                error=None,
            )
            item.name = "解析中"

            self.db.add(
                TextLibraryImportTask(
                    job_id=job_id,
                    source_url=source_url,
                    source_channel=source_channel,
                    status=TextImportTaskStatus.PENDING,
                    stage=TASK_STAGE_PENDING,
                    stage_message="等待处理",
                    cache_hit=False,
                    error_message=None,
                    cancel_requested=False,
                    cancel_requested_at=None,
                    cancel_reason=None,
                    retry_of_task_id=None,
                    retry_no=0,
                    text_library_item_id=item.id,
                    source_post_id=item.source_post_id,
                    source_post_updated_at=item.source_post_updated_at,
                )
            )

            await self.db.commit()
            await self.db.refresh(item)
            self._launch_job_runner(job_id)
            logger.info(
                "[TextLibrary][Retry] restart import item_id=%s channel=%s source_url=%s job_id=%s",
                item.id,
                source_channel.value,
                source_url,
                job_id,
            )
            return self._serialize_item(item)

        raise ServiceError(400, f"不支持当前来源类型重试: {source_channel.value}")

    async def get_import_job(self, job_id: str) -> dict[str, Any]:
        job_result = await self.db.execute(
            select(TextLibraryImportJob).where(TextLibraryImportJob.id == job_id)
        )
        job = job_result.scalar_one_or_none()
        if not job:
            raise ServiceError(404, "导入任务不存在")

        task_result = await self.db.execute(
            select(TextLibraryImportTask)
            .where(TextLibraryImportTask.job_id == job_id)
            .order_by(TextLibraryImportTask.id.asc())
        )
        tasks = list(task_result.scalars().all())
        total_count = len(tasks)
        success_count = sum(1 for task in tasks if task.status == TextImportTaskStatus.COMPLETED)
        failed_count = sum(1 for task in tasks if task.status == TextImportTaskStatus.FAILED)
        canceled_count = sum(1 for task in tasks if task.status == TextImportTaskStatus.CANCELED)
        completed_count = success_count + failed_count + canceled_count
        return {
            "id": job.id,
            "status": job.status,
            "total_count": total_count,
            "completed_count": completed_count,
            "success_count": success_count,
            "failed_count": failed_count,
            "canceled_count": canceled_count,
            "cancel_requested": bool(job.cancel_requested),
            "cancel_requested_at": job.cancel_requested_at,
            "cancel_requested_by": job.cancel_requested_by,
            "terminal_at": job.terminal_at,
            "error_message": job.error_message,
            "tasks": [self._serialize_import_task(task) for task in tasks],
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        }

    async def _mark_import_job_failed(self, job_id: str, message: str) -> None:
        job_result = await self.db.execute(
            select(TextLibraryImportJob).where(TextLibraryImportJob.id == job_id)
        )
        job = job_result.scalar_one_or_none()
        if not job:
            return
        job.status = TextImportJobStatus.FAILED
        job.error_message = self._truncate_log_text(message, 1000)
        job.terminal_at = datetime.now()
        await self.db.commit()

    async def _generate_titles_parallel(
        self,
        inputs: list[_TitleGenerationInput],
    ) -> list[tuple[_TitleGenerationInput, str | None, str | None]]:
        if not inputs:
            return []

        async def _run_one(
            one: _TitleGenerationInput,
        ) -> tuple[_TitleGenerationInput, str | None, str | None]:
            try:
                title = await run_card_stage(
                    stage=CardStage.TEXT_NAME,
                    label=f"text:title:task:{one.task.id if one.task else one.item.id}",
                    priority=220,
                    coro_factory=lambda: self._auto_name_text(
                        content=one.content,
                        source_channel=one.source_channel,
                        source_url=one.source_url,
                        source_file_name=one.source_file_name,
                    ),
                )
                return one, self._normalize_name(title), None
            except Exception as exc:  # noqa: BLE001
                return one, None, self._truncate_log_text(str(exc), 1000)

        return list(await asyncio.gather(*[_run_one(one) for one in inputs]))

    async def _finalize_title_generation(
        self,
        *,
        job: TextLibraryImportJob,
        title_inputs: list[_TitleGenerationInput],
    ) -> None:
        if not title_inputs:
            return
        title_results = await self._generate_titles_parallel(title_inputs)
        for title_input, title, error in title_results:
            task = title_input.task
            item = title_input.item
            if task and (bool(task.cancel_requested) or bool(job.cancel_requested)):
                self._mark_task_and_item_canceled(
                    task=task,
                    item=item,
                    job=job,
                    reason=task.cancel_reason or "cancel_all",
                )
                continue
            if error or not title:
                fail_msg = error or "标题生成失败"
                if task:
                    self._set_task_state(
                        task,
                        status=TextImportTaskStatus.FAILED,
                        stage=TASK_STAGE_FAILED,
                        message="标题生成失败",
                        error=fail_msg,
                    )
                self._set_item_state(
                    item,
                    title_status=TextItemFieldStatus.FAILED,
                    stage=ITEM_STAGE_FAILED,
                    message="生成失败",
                    error=fail_msg,
                )
                job.failed_count = int(job.failed_count or 0) + 1
                job.completed_count = int(job.completed_count or 0) + 1
                continue

            item.name = self._normalize_name(title)
            self._set_item_state(
                item,
                title_status=TextItemFieldStatus.READY,
                stage=ITEM_STAGE_READY
                if item.content_status == TextItemFieldStatus.READY
                else ITEM_STAGE_PENDING,
                message=None
                if item.content_status == TextItemFieldStatus.READY
                else item.processing_message,
                error=None,
            )
            if task:
                self._set_task_state(
                    task,
                    status=TextImportTaskStatus.COMPLETED,
                    stage=TASK_STAGE_COMPLETED,
                    message="导入完成",
                    error=None,
                )
            job.success_count = int(job.success_count or 0) + 1
            job.completed_count = int(job.completed_count or 0) + 1

            if title_input.post_cache_id:
                cache = await self.db.get(TextLibraryPostCache, int(title_input.post_cache_id))
                if cache:
                    cache.generated_title = item.name

    def _mark_task_and_item_failed(
        self,
        *,
        task: TextLibraryImportTask,
        item: TextLibraryItem | None,
        job: TextLibraryImportJob,
        message: str,
        stage_message: str = "导入失败",
    ) -> None:
        error = self._truncate_log_text(message, 1000)
        self._set_task_state(
            task,
            status=TextImportTaskStatus.FAILED,
            stage=TASK_STAGE_FAILED,
            message=stage_message,
            error=error,
        )
        if item:
            self._set_item_state(
                item,
                title_status=TextItemFieldStatus.FAILED,
                content_status=TextItemFieldStatus.FAILED,
                stage=ITEM_STAGE_FAILED,
                message="导入失败",
                error=error,
            )
        job.failed_count = int(job.failed_count or 0) + 1
        job.completed_count = int(job.completed_count or 0) + 1

    def _mark_task_and_item_canceled(
        self,
        *,
        task: TextLibraryImportTask,
        item: TextLibraryItem | None,
        job: TextLibraryImportJob,
        reason: str = "user_cancel",
        stage_message: str = "导入已中断",
        reset_item_fields: bool = False,
    ) -> None:
        task.cancel_requested = True
        if task.cancel_requested_at is None:
            task.cancel_requested_at = datetime.now()
        task.cancel_reason = reason
        self._set_task_state(
            task,
            status=TextImportTaskStatus.CANCELED,
            stage=TASK_STAGE_CANCELED,
            message=stage_message,
            error=None,
        )
        if item and reset_item_fields:
            self._reset_item_on_hard_cancel(item=item)
        if item:
            self._set_item_state(
                item,
                title_status=TextItemFieldStatus.CANCELED,
                content_status=TextItemFieldStatus.CANCELED,
                stage=ITEM_STAGE_CANCELED,
                message="任务已中断",
                error=None,
            )
        job.canceled_count = int(job.canceled_count or 0) + 1
        job.completed_count = int(job.completed_count or 0) + 1

    def _reset_item_on_hard_cancel(self, *, item: TextLibraryItem) -> None:
        item.name = "解析中"
        item.content = ""

    async def _mark_import_job_canceled_after_abort(self, job_id: str, *, reason: str) -> None:
        job_result = await self.db.execute(
            select(TextLibraryImportJob).where(TextLibraryImportJob.id == str(job_id))
        )
        job = job_result.scalar_one_or_none()
        if not job:
            return

        task_result = await self.db.execute(
            select(TextLibraryImportTask).where(TextLibraryImportTask.job_id == str(job_id))
        )
        tasks = list(task_result.scalars().all())
        active_tasks = [
            one
            for one in tasks
            if one.status
            not in {
                TextImportTaskStatus.COMPLETED,
                TextImportTaskStatus.FAILED,
                TextImportTaskStatus.CANCELED,
            }
        ]
        item_ids = {
            int(one.text_library_item_id) for one in active_tasks if one.text_library_item_id
        }
        item_map: dict[int, TextLibraryItem] = {}
        if item_ids:
            item_result = await self.db.execute(
                select(TextLibraryItem).where(TextLibraryItem.id.in_(item_ids))
            )
            item_map = {int(one.id): one for one in item_result.scalars().all()}

        for task in active_tasks:
            self._mark_task_and_item_canceled(
                task=task,
                item=item_map.get(int(task.text_library_item_id or 0)),
                job=job,
                reason=task.cancel_reason or reason,
                stage_message="任务已强制中断",
                reset_item_fields=True,
            )

        if not job.cancel_requested:
            job.cancel_requested = True
            job.cancel_requested_at = datetime.now()
            job.cancel_requested_by = "user"
        if active_tasks or job.status in {TextImportJobStatus.PENDING, TextImportJobStatus.RUNNING}:
            job.status = TextImportJobStatus.CANCELED
            job.error_message = None
            job.terminal_at = datetime.now()
        await self.db.commit()

    async def _is_task_cancel_requested(self, *, job_id: str, task_id: int) -> tuple[bool, str]:
        task_result = await self.db.execute(
            select(
                TextLibraryImportTask.status,
                TextLibraryImportTask.cancel_requested,
                TextLibraryImportTask.cancel_reason,
            ).where(TextLibraryImportTask.id == int(task_id))
        )
        fresh_task = task_result.first()
        job_result = await self.db.execute(
            select(
                TextLibraryImportJob.status,
                TextLibraryImportJob.cancel_requested,
            ).where(TextLibraryImportJob.id == str(job_id))
        )
        fresh_job = job_result.first()
        if fresh_task:
            task_status, task_cancel_requested, task_cancel_reason = fresh_task
            if task_status == TextImportTaskStatus.CANCELED:
                return True, task_cancel_reason or "user_cancel"
            if bool(task_cancel_requested):
                return True, task_cancel_reason or "user_cancel"
        if fresh_job:
            job_status, job_cancel_requested = fresh_job
            if job_status == TextImportJobStatus.CANCELED or bool(job_cancel_requested):
                return True, "cancel_all"
        return False, ""

    async def cancel_all_import_jobs(self, *, canceled_by: str = "user") -> dict[str, int]:
        active_task_result = await self.db.execute(
            select(TextLibraryImportTask).where(
                TextLibraryImportTask.status.in_(
                    [TextImportTaskStatus.PENDING, TextImportTaskStatus.RUNNING]
                )
            )
        )
        tasks = list(active_task_result.scalars().all())
        task_job_ids = {str(one.job_id) for one in tasks}

        job_result = await self.db.execute(
            select(TextLibraryImportJob).where(
                or_(
                    TextLibraryImportJob.status.in_(
                        [TextImportJobStatus.PENDING, TextImportJobStatus.RUNNING]
                    ),
                    TextLibraryImportJob.id.in_(task_job_ids),
                )
            )
        )
        jobs = list(job_result.scalars().all())
        if not jobs and not tasks:
            return {"affected_jobs": 0, "affected_tasks": 0}

        item_ids = [int(one.text_library_item_id or 0) for one in tasks if one.text_library_item_id]
        item_map: dict[int, TextLibraryItem] = {}
        if item_ids:
            items_result = await self.db.execute(
                select(TextLibraryItem).where(TextLibraryItem.id.in_(item_ids))
            )
            item_map = {int(one.id): one for one in items_result.scalars().all()}

        job_map = {str(one.id): one for one in jobs}
        affected_jobs = 0
        for job in jobs:
            if not job.cancel_requested:
                job.cancel_requested = True
                if job.cancel_requested_at is None:
                    job.cancel_requested_at = datetime.now()
                job.cancel_requested_by = canceled_by
                affected_jobs += 1

        affected_tasks = 0
        for task in tasks:
            if task.status in {
                TextImportTaskStatus.COMPLETED,
                TextImportTaskStatus.FAILED,
                TextImportTaskStatus.CANCELED,
            }:
                continue
            if task.cancel_requested:
                continue
            task.cancel_requested = True
            if task.cancel_requested_at is None:
                task.cancel_requested_at = datetime.now()
            task.cancel_reason = "cancel_all"
            if task.status == TextImportTaskStatus.PENDING:
                job = job_map.get(str(task.job_id))
                if job:
                    self._mark_task_and_item_canceled(
                        task=task,
                        item=item_map.get(int(task.text_library_item_id or 0)),
                        job=job,
                        reason="cancel_all",
                    )
            affected_tasks += 1

        for job in jobs:
            if int(job.completed_count or 0) >= int(job.total_count or 0):
                job.status = TextImportJobStatus.CANCELED
                job.terminal_at = datetime.now()

        await self.db.commit()
        for job in jobs:
            self._request_hard_cancel_job_runner(job.id)
        return {"affected_jobs": affected_jobs, "affected_tasks": affected_tasks}

    async def cancel_import_job(self, job_id: str, *, canceled_by: str = "user") -> dict[str, int]:
        job = await self.db.get(TextLibraryImportJob, str(job_id))
        if not job:
            raise ServiceError(404, "导入任务不存在")

        task_result = await self.db.execute(
            select(TextLibraryImportTask).where(TextLibraryImportTask.job_id == job.id)
        )
        tasks = list(task_result.scalars().all())
        active_tasks = [
            one
            for one in tasks
            if one.status
            not in {
                TextImportTaskStatus.COMPLETED,
                TextImportTaskStatus.FAILED,
                TextImportTaskStatus.CANCELED,
            }
        ]
        if not active_tasks:
            return {"affected_jobs": 0, "affected_tasks": 0}
        item_ids = {int(one.text_library_item_id) for one in tasks if one.text_library_item_id}
        item_map: dict[int, TextLibraryItem] = {}
        if item_ids:
            item_result = await self.db.execute(
                select(TextLibraryItem).where(TextLibraryItem.id.in_(item_ids))
            )
            item_map = {int(one.id): one for one in item_result.scalars().all()}

        affected_jobs = 0
        if not job.cancel_requested:
            job.cancel_requested = True
            if job.cancel_requested_at is None:
                job.cancel_requested_at = datetime.now()
            job.cancel_requested_by = canceled_by
            affected_jobs = 1

        affected_tasks = 0
        for task in active_tasks:
            if task.status in {
                TextImportTaskStatus.COMPLETED,
                TextImportTaskStatus.FAILED,
                TextImportTaskStatus.CANCELED,
            }:
                continue
            if task.cancel_requested:
                continue
            task.cancel_requested = True
            if task.cancel_requested_at is None:
                task.cancel_requested_at = datetime.now()
            task.cancel_reason = "user_cancel_job"
            if task.status == TextImportTaskStatus.PENDING:
                self._mark_task_and_item_canceled(
                    task=task,
                    item=item_map.get(int(task.text_library_item_id or 0)),
                    job=job,
                    reason="user_cancel_job",
                )
            affected_tasks += 1

        if int(job.completed_count or 0) >= int(job.total_count or 0):
            job.status = TextImportJobStatus.CANCELED
            job.terminal_at = datetime.now()

        await self.db.commit()
        self._request_hard_cancel_job_runner(job.id)
        return {"affected_jobs": affected_jobs, "affected_tasks": affected_tasks}

    async def cancel_import_task(
        self, task_id: int, *, reason: str = "user_delete"
    ) -> dict[str, int]:
        task = await self.db.get(TextLibraryImportTask, int(task_id))
        if not task:
            raise ServiceError(404, "导入任务不存在")
        job = await self.db.get(TextLibraryImportJob, task.job_id)
        if not job:
            raise ServiceError(404, "导入任务不存在")
        item = (
            await self.db.get(TextLibraryItem, int(task.text_library_item_id))
            if task.text_library_item_id
            else None
        )
        if task.status in {
            TextImportTaskStatus.COMPLETED,
            TextImportTaskStatus.FAILED,
            TextImportTaskStatus.CANCELED,
        }:
            return {"affected_jobs": 0, "affected_tasks": 0}
        if task.cancel_requested:
            return {"affected_jobs": 0, "affected_tasks": 0}

        task.cancel_requested = True
        if task.cancel_requested_at is None:
            task.cancel_requested_at = datetime.now()
        task.cancel_reason = reason
        if task.status == TextImportTaskStatus.PENDING:
            self._mark_task_and_item_canceled(task=task, item=item, job=job, reason=reason)

        if int(job.completed_count or 0) >= int(job.total_count or 0):
            job.status = TextImportJobStatus.CANCELED
            job.terminal_at = datetime.now()

        await self.db.commit()
        return {"affected_jobs": 1 if job.cancel_requested else 0, "affected_tasks": 1}

    async def cancel_import_task_by_item(self, item_id: int) -> dict[str, int]:
        task_result = await self.db.execute(
            select(TextLibraryImportTask)
            .where(TextLibraryImportTask.text_library_item_id == int(item_id))
            .order_by(TextLibraryImportTask.id.desc())
        )
        task = next(
            (
                one
                for one in task_result.scalars().all()
                if one.status
                not in {
                    TextImportTaskStatus.COMPLETED,
                    TextImportTaskStatus.FAILED,
                    TextImportTaskStatus.CANCELED,
                }
            ),
            None,
        )
        if not task:
            return {"affected_jobs": 0, "affected_tasks": 0}
        return await self.cancel_import_task(int(task.id), reason="user_delete")

    async def retry_import_task(self, task_id: int) -> dict[str, Any]:
        task = await self.db.get(TextLibraryImportTask, int(task_id))
        if not task:
            raise ServiceError(404, "导入任务不存在")
        if task.status not in {TextImportTaskStatus.FAILED, TextImportTaskStatus.CANCELED}:
            raise ServiceError(409, "仅失败或中断的任务可重试")
        item = (
            await self.db.get(TextLibraryItem, int(task.text_library_item_id))
            if task.text_library_item_id
            else None
        )
        if not item:
            raise ServiceError(404, "关联文本卡片不存在")

        job_id = self._create_import_job_id()
        job = TextLibraryImportJob(
            id=job_id,
            status=TextImportJobStatus.PENDING,
            total_count=1,
            completed_count=0,
            success_count=0,
            failed_count=0,
            canceled_count=0,
            cancel_requested=False,
            cancel_requested_at=None,
            cancel_requested_by=None,
            terminal_at=None,
            error_message=None,
        )
        self.db.add(job)

        next_retry_no = int(task.retry_no or 0) + 1
        self.db.add(
            TextLibraryImportTask(
                job_id=job_id,
                source_url=task.source_url,
                source_channel=task.source_channel,
                status=TextImportTaskStatus.PENDING,
                stage=TASK_STAGE_PENDING,
                stage_message="等待处理",
                cache_hit=False,
                error_message=None,
                cancel_requested=False,
                cancel_requested_at=None,
                cancel_reason=None,
                retry_of_task_id=task.id,
                retry_no=next_retry_no,
                text_library_item_id=item.id,
                source_post_id=task.source_post_id,
                source_post_updated_at=task.source_post_updated_at,
            )
        )

        item.name = "解析中"
        item.content = ""
        item.title_status = TextItemFieldStatus.PENDING
        item.content_status = TextItemFieldStatus.PENDING
        item.processing_stage = ITEM_STAGE_PENDING
        item.processing_message = "解析中：等待处理"
        item.error_message = None

        await self.db.commit()
        self._launch_job_runner(job_id)
        return {"job_id": job_id, "job_ids": [job_id], "item_ids": [int(item.id)]}

    async def restart_interrupted_tasks(self) -> dict[str, int]:
        task_result = await self.db.execute(
            select(TextLibraryImportTask).order_by(TextLibraryImportTask.id.desc())
        )
        all_tasks = list(task_result.scalars().all())
        latest_by_item: dict[int, TextLibraryImportTask] = {}
        for task in all_tasks:
            item_id = int(task.text_library_item_id or 0)
            if item_id <= 0 or item_id in latest_by_item:
                continue
            latest_by_item[item_id] = task

        candidates = [
            one
            for one in latest_by_item.values()
            if one.status in {TextImportTaskStatus.CANCELED, TextImportTaskStatus.FAILED}
        ]
        if not candidates:
            return {"affected_jobs": 0, "affected_tasks": 0}

        item_ids = [
            int(one.text_library_item_id or 0) for one in candidates if one.text_library_item_id
        ]
        item_result = await self.db.execute(
            select(TextLibraryItem).where(TextLibraryItem.id.in_(item_ids))
        )
        item_map = {int(one.id): one for one in item_result.scalars().all()}

        retry_tasks = [one for one in candidates if int(one.text_library_item_id or 0) in item_map]
        if not retry_tasks:
            return {"affected_jobs": 0, "affected_tasks": 0}

        job_ids: list[str] = []
        for old_task in sorted(retry_tasks, key=lambda one: int(one.id)):
            item = item_map.get(int(old_task.text_library_item_id or 0))
            if not item:
                continue
            job_id = self._create_import_job_id()
            job_ids.append(job_id)
            self.db.add(
                TextLibraryImportJob(
                    id=job_id,
                    status=TextImportJobStatus.PENDING,
                    total_count=1,
                    completed_count=0,
                    success_count=0,
                    failed_count=0,
                    canceled_count=0,
                    cancel_requested=False,
                    cancel_requested_at=None,
                    cancel_requested_by=None,
                    terminal_at=None,
                    error_message=None,
                )
            )
            self.db.add(
                TextLibraryImportTask(
                    job_id=job_id,
                    source_url=old_task.source_url,
                    source_channel=old_task.source_channel,
                    status=TextImportTaskStatus.PENDING,
                    stage=TASK_STAGE_PENDING,
                    stage_message="等待继续",
                    cache_hit=False,
                    error_message=None,
                    cancel_requested=False,
                    cancel_requested_at=None,
                    cancel_reason=None,
                    retry_of_task_id=old_task.id,
                    retry_no=int(old_task.retry_no or 0) + 1,
                    text_library_item_id=item.id,
                    source_post_id=old_task.source_post_id,
                    source_post_updated_at=old_task.source_post_updated_at,
                )
            )
            item.name = "解析中"
            item.content = ""
            item.title_status = TextItemFieldStatus.PENDING
            item.content_status = TextItemFieldStatus.PENDING
            item.processing_stage = ITEM_STAGE_PENDING
            item.processing_message = "解析中：继续处理中"
            item.error_message = None

        await self.db.commit()
        for job_id in job_ids:
            self._launch_job_runner(job_id)
        return {"affected_jobs": len(job_ids), "affected_tasks": len(job_ids)}

    async def _execute_import_job(self, job_id: str) -> None:
        job_result = await self.db.execute(
            select(TextLibraryImportJob).where(TextLibraryImportJob.id == job_id)
        )
        job = job_result.scalar_one_or_none()
        if not job:
            return

        task_result = await self.db.execute(
            select(TextLibraryImportTask)
            .where(TextLibraryImportTask.job_id == job_id)
            .order_by(TextLibraryImportTask.id.asc())
        )
        tasks = list(task_result.scalars().all())
        if not tasks:
            job.status = TextImportJobStatus.FAILED
            job.error_message = "导入任务没有可执行项"
            await self.db.commit()
            return

        job.status = TextImportJobStatus.RUNNING
        job.total_count = len(tasks)
        job.completed_count = 0
        job.success_count = 0
        job.failed_count = 0
        job.canceled_count = 0
        job.error_message = None
        await self.db.commit()

        item_ids = [
            int(task.text_library_item_id or 0) for task in tasks if task.text_library_item_id
        ]
        item_map: dict[int, TextLibraryItem] = {}
        if item_ids:
            item_result = await self.db.execute(
                select(TextLibraryItem).where(TextLibraryItem.id.in_(item_ids))
            )
            item_map = {item.id: item for item in item_result.scalars().all()}

        pending_transcribe: list[tuple[TextLibraryImportTask, TextLibraryItem, dict[str, Any]]] = []

        for task in tasks:
            item = item_map.get(int(task.text_library_item_id or 0))
            task_id = int(task.id)
            should_cancel, cancel_reason = await self._is_task_cancel_requested(
                job_id=job_id,
                task_id=task_id,
            )
            if should_cancel:
                self._mark_task_and_item_canceled(
                    task=task,
                    item=item,
                    job=job,
                    reason=cancel_reason or "cancel_all",
                )
                await self.db.commit()
                continue
            if item is None:
                self._mark_task_and_item_failed(
                    task=task,
                    item=None,
                    job=job,
                    message="任务缺少对应文本卡片",
                )
                await self.db.commit()
                continue

            self._set_task_state(
                task,
                status=TextImportTaskStatus.RUNNING,
                stage=TASK_STAGE_EXTRACTING,
                message="解析中：正在获取内容",
                error=None,
            )
            self._set_item_state(
                item,
                content_status=TextItemFieldStatus.RUNNING,
                stage=ITEM_STAGE_EXTRACTING,
                message="解析中：正在获取内容",
                error=None,
            )
            await self.db.commit()

            try:
                logger.info(
                    "[TextLibrary][ImportTask] start job_id=%s task_id=%s channel=%s url=%s",
                    job_id,
                    task.id,
                    task.source_channel.value,
                    task.source_url,
                )
                payload = await self._prepare_link_task_payload(task=task)
                should_cancel, cancel_reason = await self._is_task_cancel_requested(
                    job_id=job_id,
                    task_id=task_id,
                )
                if should_cancel:
                    self._mark_task_and_item_canceled(
                        task=task,
                        item=item,
                        job=job,
                        reason=cancel_reason or "cancel_all",
                    )
                    await self.db.commit()
                    continue
                task.cache_hit = False
                task.source_post_id = self._normalize_text(payload.get("post_id")) or None
                task.source_post_updated_at = self._normalize_post_timestamp(
                    payload.get("post_updated_at")
                )
                item.source_post_id = task.source_post_id
                item.source_post_updated_at = task.source_post_updated_at

                preview_content = self._normalize_text(payload.get("content"))
                if preview_content:
                    item.content = preview_content

                if bool(payload.get("needs_transcribe")):
                    self._set_task_state(
                        task,
                        status=TextImportTaskStatus.RUNNING,
                        stage=TASK_STAGE_TRANSCRIBING,
                        message="解析完成：等待视频转写",
                        error=None,
                    )
                    self._set_item_state(
                        item,
                        content_status=TextItemFieldStatus.RUNNING,
                        stage=ITEM_STAGE_TRANSCRIBING,
                        message="解析中：视频转写中",
                        error=None,
                    )
                    pending_transcribe.append((task, item, payload))
                    await self.db.commit()
                    continue

                final_content = self._normalize_text(payload.get("content"))
                if not final_content:
                    raise ServiceError(500, "解析到的内容为空")
                item.content = final_content

                post_cache_id = payload.get("cache_id")
                if task.source_channel in MEDIA_CHANNELS and task.source_post_id:
                    cache = await self._upsert_post_cache(
                        source_channel=task.source_channel,
                        post_id=task.source_post_id,
                        post_updated_at=task.source_post_updated_at,
                        source_url=task.source_url,
                        media_kind=self._normalize_text(payload.get("media_kind")) or None,
                        media_url=self._normalize_text(payload.get("media_url")) or None,
                        title_text=self._normalize_text(payload.get("title_text")) or None,
                        note_text=self._normalize_text(payload.get("note_text")) or None,
                        transcript_text=None,
                        combined_content=final_content,
                    )
                    if cache is not None:
                        post_cache_id = cache.id

                self._set_item_state(
                    item,
                    title_status=TextItemFieldStatus.RUNNING,
                    content_status=TextItemFieldStatus.READY,
                    stage=ITEM_STAGE_GENERATING,
                    message="生成中：正在生成标题",
                    error=None,
                )
                self._set_task_state(
                    task,
                    status=TextImportTaskStatus.RUNNING,
                    stage=TASK_STAGE_GENERATING,
                    message="内容就绪：正在生成标题",
                    error=None,
                )
                await self._finalize_title_generation(
                    job=job,
                    title_inputs=[
                        _TitleGenerationInput(
                            task=task,
                            item=item,
                            content=final_content,
                            source_channel=task.source_channel,
                            source_url=task.source_url,
                            source_file_name=None,
                            post_cache_id=int(post_cache_id) if post_cache_id else None,
                        )
                    ],
                )
                await self.db.commit()
            except Exception as exc:  # noqa: BLE001
                if bool(task.cancel_requested) or bool(job.cancel_requested):
                    self._mark_task_and_item_canceled(
                        task=task,
                        item=item,
                        job=job,
                        reason=task.cancel_reason or "cancel_all",
                    )
                else:
                    self._mark_task_and_item_failed(task=task, item=item, job=job, message=str(exc))
                logger.warning(
                    "[TextLibrary][ImportTask] failed job_id=%s task_id=%s error=%s",
                    job_id,
                    task.id,
                    exc,
                )
                await self.db.commit()

        pending_total = len(pending_transcribe)
        for index, (task, item, payload) in enumerate(pending_transcribe, start=1):
            task_id = int(task.id)
            should_cancel, cancel_reason = await self._is_task_cancel_requested(
                job_id=job_id,
                task_id=task_id,
            )
            if should_cancel:
                self._mark_task_and_item_canceled(
                    task=task,
                    item=item,
                    job=job,
                    reason=cancel_reason or "cancel_all",
                )
                await self.db.commit()
                continue
            try:
                logger.info(
                    "[TextLibrary][ASR] queue task=%s/%s task_id=%s post_id=%s",
                    index,
                    pending_total,
                    task.id,
                    task.source_post_id or "-",
                )
                self._set_task_state(
                    task,
                    status=TextImportTaskStatus.RUNNING,
                    stage=TASK_STAGE_TRANSCRIBING,
                    message="解析中：正在视频转写",
                    error=None,
                )
                self._set_item_state(
                    item,
                    content_status=TextItemFieldStatus.RUNNING,
                    stage=ITEM_STAGE_TRANSCRIBING,
                    message="解析中：正在视频转写",
                    error=None,
                )
                await self.db.commit()

                last_transcribe_progress_at = 0.0
                last_transcribe_percent = -1

                async def _on_transcribe_progress(progress_payload: dict[str, Any]) -> None:
                    nonlocal last_transcribe_progress_at, last_transcribe_percent
                    total_seconds = max(0.0, float(progress_payload.get("total_seconds") or 0.0))
                    current_seconds = max(
                        0.0, float(progress_payload.get("current_seconds") or 0.0)
                    )
                    ratio = float(progress_payload.get("progress") or 0.0)
                    percent = int(max(0, min(100, round(ratio * 100))))
                    now = time.monotonic()

                    should_commit = False
                    if percent > last_transcribe_percent:
                        should_commit = True
                    if now - last_transcribe_progress_at >= 0.9:
                        should_commit = True
                    if percent >= 100:
                        should_commit = True
                    if not should_commit:
                        return

                    if total_seconds > 0:
                        message = (
                            f"解析中：正在视频转写 {percent}% "
                            f"({current_seconds:.1f}/{total_seconds:.1f}s)"
                        )
                    else:
                        message = f"解析中：正在视频转写 {percent}%"

                    self._set_task_state(
                        task,
                        status=TextImportTaskStatus.RUNNING,
                        stage=TASK_STAGE_TRANSCRIBING,
                        message=message,
                        error=None,
                    )
                    self._set_item_state(
                        item,
                        content_status=TextItemFieldStatus.RUNNING,
                        stage=ITEM_STAGE_TRANSCRIBING,
                        message=message,
                        error=None,
                    )
                    await self.db.commit()

                    last_transcribe_percent = percent
                    last_transcribe_progress_at = now

                transcript_text, download_cache_hit = await self._transcribe_video_task(
                    task=task,
                    media_url=self._normalize_text(payload.get("media_url")),
                    source_channel=task.source_channel,
                    post_id=self._normalize_text(payload.get("post_id")) or None,
                    post_updated_at=self._normalize_post_timestamp(payload.get("post_updated_at")),
                    on_progress=_on_transcribe_progress,
                )
                task.cache_hit = bool(download_cache_hit)
                logger.info(
                    "[TextLibrary][ASR] queue completed task=%s/%s task_id=%s transcript_len=%s download_cache_hit=%s",
                    index,
                    pending_total,
                    task.id,
                    len(transcript_text),
                    bool(download_cache_hit),
                )
                self._set_task_state(
                    task,
                    status=TextImportTaskStatus.RUNNING,
                    stage=TASK_STAGE_PROOFREADING,
                    message="转写完成：正在校对文本",
                    error=None,
                )
                self._set_item_state(
                    item,
                    content_status=TextItemFieldStatus.RUNNING,
                    stage=ITEM_STAGE_PROOFREADING,
                    message="解析中：正在校对文本",
                    error=None,
                )
                await self.db.commit()

                last_stream_commit_at = 0.0
                last_stream_len = 0

                async def _on_proofread_partial_update(partial_text: str) -> None:
                    nonlocal last_stream_commit_at, last_stream_len
                    normalized_partial = self._normalize_text(partial_text)
                    if not normalized_partial:
                        return
                    now = time.monotonic()
                    current_len = len(normalized_partial)
                    should_commit = False
                    if current_len >= last_stream_len + 24:
                        should_commit = True
                    if now - last_stream_commit_at >= 0.45:
                        should_commit = True
                    if not should_commit:
                        return
                    partial_content = self._compose_media_content(
                        title=self._normalize_text(payload.get("title_text")),
                        note_text=self._normalize_text(payload.get("note_text")),
                        transcript_text=normalized_partial,
                    )
                    if not partial_content or partial_content == item.content:
                        return
                    item.content = partial_content
                    await self.db.commit()
                    last_stream_len = current_len
                    last_stream_commit_at = now

                proofread_transcript = await run_card_stage(
                    stage=CardStage.PROOFREAD,
                    label=f"text:proofread:task:{task.id}",
                    priority=210,
                    coro_factory=lambda: self._proofread_transcript_text(
                        source_channel=task.source_channel,
                        source_url=task.source_url,
                        title_text=self._normalize_text(payload.get("title_text")),
                        note_text=self._normalize_text(payload.get("note_text")),
                        transcript_text=transcript_text,
                        on_partial_update=_on_proofread_partial_update,
                    ),
                )
                should_cancel, cancel_reason = await self._is_task_cancel_requested(
                    job_id=job_id,
                    task_id=task_id,
                )
                if should_cancel:
                    self._mark_task_and_item_canceled(
                        task=task,
                        item=item,
                        job=job,
                        reason=cancel_reason or "cancel_all",
                    )
                    await self.db.commit()
                    continue
                final_content = self._compose_media_content(
                    title=self._normalize_text(payload.get("title_text")),
                    note_text=self._normalize_text(payload.get("note_text")),
                    transcript_text=proofread_transcript,
                )
                if not final_content:
                    raise ServiceError(500, "转写后内容为空")
                item.content = final_content

                post_cache_id = payload.get("cache_id")
                if task.source_post_id:
                    cache = await self._upsert_post_cache(
                        source_channel=task.source_channel,
                        post_id=task.source_post_id,
                        post_updated_at=task.source_post_updated_at,
                        source_url=task.source_url,
                        media_kind=self._normalize_text(payload.get("media_kind")) or None,
                        media_url=self._normalize_text(payload.get("media_url")) or None,
                        title_text=self._normalize_text(payload.get("title_text")) or None,
                        note_text=self._normalize_text(payload.get("note_text")) or None,
                        transcript_text=proofread_transcript,
                        combined_content=final_content,
                    )
                    if cache is not None:
                        post_cache_id = cache.id

                self._set_item_state(
                    item,
                    title_status=TextItemFieldStatus.RUNNING,
                    content_status=TextItemFieldStatus.READY,
                    stage=ITEM_STAGE_GENERATING,
                    message="生成中：正在生成标题",
                    error=None,
                )
                self._set_task_state(
                    task,
                    status=TextImportTaskStatus.RUNNING,
                    stage=TASK_STAGE_GENERATING,
                    message="转写完成：正在生成标题",
                    error=None,
                )
                await self._finalize_title_generation(
                    job=job,
                    title_inputs=[
                        _TitleGenerationInput(
                            task=task,
                            item=item,
                            content=final_content,
                            source_channel=task.source_channel,
                            source_url=task.source_url,
                            source_file_name=None,
                            post_cache_id=int(post_cache_id) if post_cache_id else None,
                        )
                    ],
                )
                await self.db.commit()
            except Exception as exc:  # noqa: BLE001
                if bool(task.cancel_requested) or bool(job.cancel_requested):
                    self._mark_task_and_item_canceled(
                        task=task,
                        item=item,
                        job=job,
                        reason=task.cancel_reason or "cancel_all",
                    )
                else:
                    self._mark_task_and_item_failed(task=task, item=item, job=job, message=str(exc))
                logger.warning(
                    "[TextLibrary][ImportTask] transcribe failed job_id=%s task_id=%s error=%s",
                    job_id,
                    task.id,
                    exc,
                )
                await self.db.commit()

        if (
            int(job.success_count or 0) == 0
            and int(job.failed_count or 0) == 0
            and int(job.canceled_count or 0) > 0
        ):
            job.status = TextImportJobStatus.CANCELED
            job.error_message = None
        elif int(job.success_count or 0) == 0 and int(job.failed_count or 0) > 0:
            job.status = TextImportJobStatus.FAILED
            job.error_message = "所有链接导入均失败"
        else:
            job.status = TextImportJobStatus.COMPLETED
            job.error_message = None
        job.terminal_at = datetime.now()
        await self.db.commit()

    async def update(self, item_id: int, data: dict[str, Any]) -> dict[str, Any]:
        item = await self.get(item_id)
        if not item:
            raise ServiceError(404, "文本卡片不存在")
        if self._is_item_processing(item):
            raise ServiceError(409, "文本仍在处理中，请稍后再编辑")

        if data:
            self._clear_item_failed_state_on_manual_edit(item)
        if "name" in data:
            item.name = self._normalize_name(str(data.get("name") or ""))
        if "content" in data:
            content = self._normalize_text(str(data.get("content") or ""))
            if not content:
                raise ServiceError(400, "文本内容不能为空")
            item.content = content
        if "is_enabled" in data:
            item.is_enabled = bool(data.get("is_enabled"))

        await self.db.commit()
        await self.db.refresh(item)
        return self._serialize_item(item)

    async def delete(self, item_id: int) -> None:
        item = await self.get(item_id)
        if not item:
            raise ServiceError(404, "文本卡片不存在")
        await self.db.delete(item)
        await self.db.commit()
