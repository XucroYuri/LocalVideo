from __future__ import annotations

import asyncio
import base64
import difflib
import json
import logging
import re
import secrets
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import UploadFile
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.audio_acoustic_features import (
    extract_wav_acoustic_features,
    format_acoustic_features_for_prompt,
)
from app.core.errors import ServiceError
from app.db.session import AsyncSessionLocal
from app.llm.runtime import ResolvedLLMRuntime, resolve_llm_runtime
from app.models.text_library import TextSourceChannel
from app.models.voice_library import (
    VoiceImportJobStatus,
    VoiceImportTaskStatus,
    VoiceItemFieldStatus,
    VoiceLibraryImportJob,
    VoiceLibraryImportTask,
    VoiceLibraryItem,
    VoiceSourceChannel,
)
from app.schemas.voice_library import VoiceLibraryImportAudioRow
from app.services.library_import_limits import (
    get_library_batch_max_items,
    get_library_batch_max_total_upload_bytes,
    get_library_batch_max_total_upload_mb,
    get_upload_file_size,
)
from app.services.library_task_scheduler import CardStage, run_card_stage

logger = logging.getLogger(__name__)

SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg", ".mp4", ".webm"}
STORAGE_PUBLIC_PREFIX = "/storage/"
LOG_STAGE_SEPARATOR = "=" * 80

ITEM_STAGE_PENDING = "pending"
ITEM_STAGE_EXTRACTING = "extracting"
ITEM_STAGE_CLIPPING = "clipping"
ITEM_STAGE_TRANSCRIBING = "transcribing"
ITEM_STAGE_PROOFREADING = "proofreading"
ITEM_STAGE_GENERATING = "generating"
ITEM_STAGE_READY = "ready"
ITEM_STAGE_FAILED = "failed"

TASK_STAGE_PENDING = "pending"
TASK_STAGE_EXTRACTING = "extracting"
TASK_STAGE_CLIPPING = "clipping"
TASK_STAGE_TRANSCRIBING = "transcribing"
TASK_STAGE_PROOFREADING = "proofreading"
TASK_STAGE_GENERATING = "generating"
TASK_STAGE_COMPLETED = "completed"
TASK_STAGE_FAILED = "failed"
TASK_STAGE_CANCELED = "canceled"

ITEM_STAGE_CANCELED = "canceled"

NAME_SYSTEM_PROMPT = (
    "你是中文配音策划与音色命名助手。"
    "你会根据现有口播文本与本地提取的音频声学特征，给出简短、自然、可读的中文音色名称。"
)
NAME_PROMPT_TEMPLATE = (
    "请基于下面信息，为声音样本命名。\n"
    "目标：突出音色与说话风格，风格可参考：元气少女、清冷阿姨、解说小帅。\n"
    "要求：\n"
    "1) 只输出 JSON，不要输出额外文本；\n"
    "2) 字段名固定为 name；\n"
    "3) 名称长度 2-8 个汉字；\n"
    "4) 不要使用标点符号；\n"
    "5) 重点依据声学特征和说话风格命名，不要根据文本话题直接命名；\n"
    "6) 如果文本内容和声学特征冲突，以声学特征体现出的风格为主；\n"
    "7) 不要复用原始文件名或来源名称。\n\n"
    "补充信息（可能为空）：\n"
    "来源文件名：{source_file_name}\n"
    "参考文本：{reference_text}\n\n"
    "本地提取的音频声学特征：\n"
    "{acoustic_features}\n\n"
    "输出格式：\n"
    '{{"name":"元气少女"}}'
)
TRANSCRIPT_PROOFREAD_SYSTEM_PROMPT = "你是严谨的中文语音转写校对编辑。"
TRANSCRIPT_PROOFREAD_PROMPT_TEMPLATE = (
    "请你对下面的语音转写内容做“严格对齐原文”的中文校对。\n"
    "输入信息：\n"
    "来源渠道：{source_channel}\n"
    "来源链接：{source_url}\n"
    "来源文件名：{source_file_name}\n"
    "待校对转写文本：\n{transcript}\n\n"
    "要求：\n"
    "1) 仅允许做两类修改：a) 明显错别字纠正；b) 补充标点；\n"
    "2) 不得新增原文里没有的新事实、新判断、新措辞；\n"
    "3) 不得做总结、改写、润色扩写，不得省略关键信息；\n"
    "4) 数字可做紧凑化规范（如“20 26”->“2026”），但不得改动数值本身；\n"
    "5) 输出必须是单段整段文本，不要分段；\n"
    "6) 严格输出 JSON，不要输出任何额外文本。\n\n"
    "输出格式：\n"
    '{{"proofread_text":"这里是校对后的单段文本"}}'
)


def log_stage_separator(logger: logging.Logger) -> None:
    logger.info(LOG_STAGE_SEPARATOR)


class VoiceLibraryService:
    _job_tasks: dict[str, asyncio.Task[None]] = {}
    _item_tasks: dict[int, asyncio.Task[None]] = {}

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        return str(value or "").strip()

    @classmethod
    def _normalize_name(cls, value: str | None) -> str:
        normalized = cls._normalize_text(value)
        if not normalized:
            raise ServiceError(400, "语音名称不能为空")
        return normalized[:255]

    @staticmethod
    def _truncate_text(value: str, limit: int = 1800) -> str:
        text = str(value or "")
        if len(text) <= limit:
            return text
        half = max(200, limit // 2)
        return f"{text[:half]}\n...\n{text[-half:]}"

    @classmethod
    def _parse_audio_import_rows(
        cls,
        *,
        rows_json: str,
        file_count: int,
    ) -> dict[int, VoiceLibraryImportAudioRow]:
        text = cls._normalize_text(rows_json)
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except Exception as exc:  # noqa: BLE001
            raise ServiceError(400, f"rows_json 不是合法 JSON: {exc}") from exc

        if not isinstance(payload, list):
            raise ServiceError(400, "rows_json 必须是数组")

        row_map: dict[int, VoiceLibraryImportAudioRow] = {}
        for one in payload:
            row = VoiceLibraryImportAudioRow.model_validate(one)
            if row.index < 0 or row.index >= file_count:
                raise ServiceError(400, f"rows_json index 越界: {row.index}")
            row_map[int(row.index)] = row
        return row_map

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
        logger.info("[VoiceLibrary] LLM Generate - %s", action)
        logger.info(
            "[Input] llm_provider=%s(%s) llm_model=%s",
            llm_runtime.provider_name,
            llm_runtime.provider_type,
            llm_runtime.model,
        )
        for key, value in (extra_inputs or {}).items():
            logger.info("[Input] %s=%s", key, self._truncate_text(value, 500))
        logger.info("[Input] prompt: %s", self._truncate_text(prompt, 1000))
        logger.info("[Input] system_prompt: %s", self._truncate_text(system_prompt, 1000))
        log_stage_separator(logger)

    @classmethod
    def _storage_root(cls) -> Path:
        path = Path(settings.storage_path).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def _voice_library_storage_dir(cls) -> Path:
        path = cls._storage_root() / "voice-library"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def _voice_library_builtin_dir(cls) -> Path:
        path = cls._voice_library_storage_dir() / "builtin"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def _voice_library_upload_dir(cls) -> Path:
        path = cls._voice_library_storage_dir() / "uploads"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def _voice_library_tmp_dir(cls) -> Path:
        path = cls._voice_library_storage_dir() / "_tmp"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def _voice_library_builtin_manifest(cls) -> Path:
        return cls._voice_library_builtin_dir() / "builtin_voices.json"

    @staticmethod
    def _is_within(path: Path, parent: Path) -> bool:
        try:
            path.resolve().relative_to(parent.resolve())
            return True
        except ValueError:
            return False

    @classmethod
    def _path_to_storage_public_url(cls, path: Path) -> str:
        relative_path = path.resolve().relative_to(cls._storage_root())
        return f"{STORAGE_PUBLIC_PREFIX}{relative_path.as_posix()}"

    @classmethod
    def normalize_audio_guide_value(cls, value: str | None, *, allow_empty: bool = True) -> str:
        text = cls._normalize_text(value)
        if not text:
            if allow_empty:
                return ""
            raise ServiceError(400, "语音文件路径不能为空")
        normalized = cls._normalize_audio_file_path(text, allow_empty=False)
        if not normalized:
            if allow_empty:
                return ""
            raise ServiceError(400, "语音文件路径不合法")
        return cls._path_to_storage_public_url(Path(normalized))

    @classmethod
    def _resolve_storage_public_path(cls, normalized: str) -> Path | None:
        if normalized.startswith(STORAGE_PUBLIC_PREFIX):
            relative = normalized[len(STORAGE_PUBLIC_PREFIX) :].strip("/")
            if not relative:
                return None
            return (cls._storage_root() / relative).resolve()
        return None

    @classmethod
    def _normalize_audio_file_path(
        cls,
        value: str | None,
        *,
        allow_empty: bool = True,
    ) -> str | None:
        raw = cls._normalize_text(value).replace("\\", "/")
        if not raw:
            if allow_empty:
                return None
            raise ServiceError(400, "语音文件路径不能为空")

        if raw.startswith("http://") or raw.startswith("https://"):
            raise ServiceError(400, "语音文件路径仅支持本地存储路径")

        normalized = raw if raw.startswith("/") else f"/{raw}"
        if ".." in normalized:
            raise ServiceError(400, "语音文件路径不合法")

        resolved_path: Path | None = None

        storage_public = cls._resolve_storage_public_path(normalized)
        if storage_public is not None:
            resolved_path = storage_public
        else:
            candidate = Path(raw).expanduser()
            if candidate.is_absolute():
                resolved_path = candidate.resolve()
            elif raw.startswith("storage/"):
                resolved_path = (cls._storage_root() / raw[len("storage/") :]).resolve()
            elif raw.startswith("voice-library/"):
                resolved_path = (cls._storage_root() / raw).resolve()
            else:
                builtin_candidate = (cls._voice_library_builtin_dir() / Path(raw).name).resolve()
                if builtin_candidate.is_file():
                    resolved_path = builtin_candidate

        if resolved_path is None:
            raise ServiceError(400, "语音文件路径不合法")

        if not cls._is_within(resolved_path, cls._voice_library_storage_dir()):
            raise ServiceError(400, "语音文件路径必须位于 storage/voice-library 下")

        return str(resolved_path)

    @classmethod
    def _audio_file_exists(cls, audio_file_path: str | None) -> bool:
        if not audio_file_path:
            return False
        try:
            normalized = cls._normalize_audio_file_path(audio_file_path, allow_empty=False)
        except ServiceError:
            return False
        if not normalized:
            return False
        file_path = Path(normalized)
        return file_path.is_file() and file_path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS

    @classmethod
    def _resolve_audio_file_for_io(cls, audio_file_path: str | None) -> Path | None:
        if not audio_file_path:
            return None
        try:
            normalized = cls._normalize_audio_file_path(audio_file_path, allow_empty=False)
        except ServiceError:
            return None
        if not normalized:
            return None
        return Path(normalized)

    @classmethod
    def _serialize_item(cls, item: VoiceLibraryItem) -> dict[str, Any]:
        has_audio = cls._audio_file_exists(item.audio_file_path)
        audio_url = None
        if has_audio and item.audio_file_path:
            normalized_audio_path: str | None = None
            try:
                normalized_audio_path = cls._normalize_audio_file_path(
                    item.audio_file_path, allow_empty=False
                )
            except ServiceError:
                normalized_audio_path = None
            if normalized_audio_path:
                audio_url = cls._path_to_storage_public_url(Path(normalized_audio_path))
        return {
            "id": item.id,
            "name": item.name,
            "reference_text": item.reference_text,
            "audio_file_path": item.audio_file_path,
            "audio_url": audio_url,
            "has_audio": has_audio,
            "is_enabled": bool(item.is_enabled),
            "is_builtin": bool(item.is_builtin),
            "source_channel": item.source_channel,
            "auto_parse_text": bool(item.auto_parse_text),
            "source_url": item.source_url,
            "source_file_name": item.source_file_name,
            "source_post_id": item.source_post_id,
            "source_post_updated_at": item.source_post_updated_at,
            "clip_start_requested_sec": item.clip_start_requested_sec,
            "clip_end_requested_sec": item.clip_end_requested_sec,
            "clip_start_actual_sec": item.clip_start_actual_sec,
            "clip_end_actual_sec": item.clip_end_actual_sec,
            "name_status": item.name_status,
            "reference_text_status": item.reference_text_status,
            "processing_stage": item.processing_stage,
            "processing_message": item.processing_message,
            "error_message": item.error_message,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }

    @staticmethod
    def _serialize_import_task(task: VoiceLibraryImportTask) -> dict[str, Any]:
        return {
            "id": task.id,
            "source_channel": task.source_channel,
            "source_url": task.source_url,
            "source_file_name": task.source_file_name,
            "auto_parse_text": bool(task.auto_parse_text),
            "clip_start_requested_sec": task.clip_start_requested_sec,
            "clip_end_requested_sec": task.clip_end_requested_sec,
            "clip_start_actual_sec": task.clip_start_actual_sec,
            "clip_end_actual_sec": task.clip_end_actual_sec,
            "status": task.status,
            "stage": task.stage,
            "stage_message": task.stage_message,
            "error_message": task.error_message,
            "cancel_requested": bool(task.cancel_requested),
            "cancel_requested_at": task.cancel_requested_at,
            "cancel_reason": task.cancel_reason,
            "retry_of_task_id": task.retry_of_task_id,
            "retry_no": int(task.retry_no or 0),
            "voice_library_item_id": task.voice_library_item_id,
            "source_post_id": task.source_post_id,
            "source_post_updated_at": task.source_post_updated_at,
        }

    @staticmethod
    def _extract_json_object_from_text(output_text: str) -> dict[str, Any]:
        text = str(output_text or "").strip()
        if not text:
            return {}

        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        fenced = re.sub(r"^\s*```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        fenced = re.sub(r"\s*```\s*$", "", fenced, flags=re.IGNORECASE).strip()
        if fenced and fenced != text:
            try:
                parsed = json.loads(fenced)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass

        decoder = json.JSONDecoder()
        for idx, one in enumerate(text):
            if one != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(text[idx:])
            except Exception:
                continue
            if isinstance(parsed, dict):
                return parsed
        return {}

    @classmethod
    def _normalize_generated_name(cls, raw_text: str) -> str:
        candidate = cls._normalize_text(raw_text)
        if not candidate:
            return ""
        candidate = re.sub(r"^[\s\"'“”‘’]+", "", candidate)
        candidate = re.sub(r"[\s\"'“”‘’]+$", "", candidate)
        candidate = re.sub(r"[：:、,，。.!！?？;；()（）\[\]{}<>《》]", "", candidate).strip()
        return candidate[:32]

    @classmethod
    def _fallback_name(
        cls,
        *,
        source_channel: VoiceSourceChannel | None,
        source_url: str | None,
        source_file_name: str | None,
        reference_text: str | None,
    ) -> str:
        if source_file_name:
            stem = Path(source_file_name).stem.strip()
            if stem:
                return stem[:24]

        if source_url:
            host = (urlparse(source_url).netloc or "").strip()
            if host:
                return host[:24]

        compact = re.sub(r"\s+", "", cls._normalize_text(reference_text))
        if compact:
            return compact[:8]

        prefix_map = {
            VoiceSourceChannel.AUDIO_WITH_TEXT: "参考音色",
            VoiceSourceChannel.AUDIO_FILE: "音频音色",
            VoiceSourceChannel.VIDEO_LINK: "视频音色",
            VoiceSourceChannel.BUILTIN: "内置音色",
        }
        return prefix_map.get(source_channel, "音色参考")

    @staticmethod
    def _is_item_ready(item: VoiceLibraryItem) -> bool:
        return (
            item.name_status == VoiceItemFieldStatus.READY
            and item.reference_text_status == VoiceItemFieldStatus.READY
            and not item.error_message
        )

    @staticmethod
    def _is_item_processing(item: VoiceLibraryItem) -> bool:
        return item.name_status in {
            VoiceItemFieldStatus.PENDING,
            VoiceItemFieldStatus.RUNNING,
        } or item.reference_text_status in {
            VoiceItemFieldStatus.PENDING,
            VoiceItemFieldStatus.RUNNING,
        }

    @staticmethod
    def _is_builtin_item(item: VoiceLibraryItem) -> bool:
        return bool(item.is_builtin) or item.source_channel == VoiceSourceChannel.BUILTIN

    @classmethod
    def _ensure_item_mutable(cls, item: VoiceLibraryItem) -> None:
        if cls._is_builtin_item(item):
            raise ServiceError(403, "内置语音卡片不支持修改或删除")

    @classmethod
    def _ensure_item_editable(cls, item: VoiceLibraryItem, data: dict[str, Any]) -> None:
        if not cls._is_builtin_item(item):
            return
        editable_keys = {"name", "reference_text", "audio_file_path"}
        if any(key in data for key in editable_keys):
            raise ServiceError(403, "内置语音卡片不支持编辑")

    def _set_item_state(
        self,
        item: VoiceLibraryItem,
        *,
        name_status: VoiceItemFieldStatus | None = None,
        reference_text_status: VoiceItemFieldStatus | None = None,
        stage: str | None = None,
        message: str | None = None,
        error: str | None = None,
    ) -> None:
        if name_status is not None:
            item.name_status = name_status
        if reference_text_status is not None:
            item.reference_text_status = reference_text_status
        item.processing_stage = stage
        item.processing_message = message
        item.error_message = error

    def _set_task_state(
        self,
        task: VoiceLibraryImportTask,
        *,
        status: VoiceImportTaskStatus,
        stage: str,
        message: str | None = None,
        error: str | None = None,
    ) -> None:
        task.status = status
        task.stage = stage
        task.stage_message = message
        task.error_message = error

    def _clear_item_failed_state_on_manual_edit(self, item: VoiceLibraryItem) -> None:
        if item.name_status == VoiceItemFieldStatus.FAILED:
            item.name_status = VoiceItemFieldStatus.READY
        if item.reference_text_status == VoiceItemFieldStatus.FAILED:
            item.reference_text_status = VoiceItemFieldStatus.READY
        item.processing_stage = None
        item.processing_message = None
        item.error_message = None

    @classmethod
    def _resolve_builtin_audio_from_manifest_row(
        cls, raw: dict[str, Any], index: int
    ) -> str | None:
        raw_audio_path = cls._normalize_text(str(raw.get("audio_file_path") or ""))
        if raw_audio_path:
            try:
                normalized = cls._normalize_audio_file_path(raw_audio_path, allow_empty=False)
                if normalized and Path(normalized).is_file():
                    return cls._path_to_storage_public_url(Path(normalized))
            except ServiceError:
                pass

        filename = Path(raw_audio_path).name if raw_audio_path else ""
        fallback_names = [filename]
        for one_name in fallback_names:
            if not one_name:
                continue
            candidate = cls._voice_library_builtin_dir() / one_name
            if candidate.is_file():
                return cls._path_to_storage_public_url(candidate)
        return None

    @classmethod
    def _build_builtin_item_payload(
        cls,
        *,
        raw: dict[str, Any],
        index: int,
    ) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None

        name = cls._normalize_text(str(raw.get("name") or ""))
        if not name:
            return None

        audio_file_path = cls._resolve_builtin_audio_from_manifest_row(raw, index)
        if not audio_file_path:
            return None

        builtin_key = cls._normalize_text(str(raw.get("builtin_key") or ""))
        if not builtin_key:
            builtin_key = f"builtin:{index + 1}"

        return {
            "name": name,
            "reference_text": cls._normalize_text(str(raw.get("reference_text") or "")),
            "audio_file_path": audio_file_path,
            "builtin_key": builtin_key,
        }

    @classmethod
    def _load_builtin_manifest_rows(cls) -> list[dict[str, Any]]:
        builtin_manifest = cls._voice_library_builtin_manifest()
        if not builtin_manifest.is_file():
            return []

        try:
            rows = json.loads(builtin_manifest.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(rows, list):
            return []

        normalized_rows: list[dict[str, Any]] = []
        for index, raw in enumerate(rows):
            item_payload = cls._build_builtin_item_payload(raw=raw, index=index)
            if item_payload is not None:
                normalized_rows.append(item_payload)
        return normalized_rows

    @staticmethod
    def _serialize_builtin_item_snapshot(item: VoiceLibraryItem) -> dict[str, str]:
        return {
            "name": str(item.name or ""),
            "reference_text": str(item.reference_text or ""),
            "audio_file_path": str(item.audio_file_path or ""),
            "builtin_key": str(item.builtin_key or ""),
        }

    @classmethod
    def _ensure_builtin_manifest_exists(cls) -> None:
        builtin_manifest = cls._voice_library_builtin_manifest()
        if builtin_manifest.is_file():
            return

    @classmethod
    def _try_rebase_storage_audio_path(cls, value: str | None) -> str | None:
        raw = cls._normalize_text(value).replace("\\", "/")
        if not raw:
            return None
        lowered = raw.lower()
        marker = "/voice-library/"
        pos = lowered.find(marker)
        if pos < 0:
            return None
        relative = raw[pos + 1 :].strip("/")
        if not relative:
            return None
        candidate = (cls._storage_root() / relative).resolve()
        if not cls._is_within(candidate, cls._voice_library_storage_dir()):
            return None
        if not candidate.is_file():
            return None
        return str(candidate)

    async def _migrate_existing_item_audio_paths(self) -> None:
        result = await self.db.execute(
            select(VoiceLibraryItem).where(VoiceLibraryItem.audio_file_path.is_not(None))
        )
        items = list(result.scalars().all())
        changed = False

        for item in items:
            original_path = self._normalize_text(item.audio_file_path)
            if not original_path:
                continue
            try:
                normalized = self._normalize_audio_file_path(original_path, allow_empty=False)
            except ServiceError:
                normalized = self._try_rebase_storage_audio_path(original_path)
                if not normalized:
                    continue
            if not normalized or not Path(normalized).is_file():
                continue
            normalized_public = self._path_to_storage_public_url(Path(normalized))
            if normalized_public != original_path:
                item.audio_file_path = normalized_public
                changed = True

        if changed:
            await self.db.commit()

    async def _ensure_builtin_seeded(self) -> None:
        self._voice_library_storage_dir()
        self._voice_library_builtin_dir()
        self._voice_library_upload_dir()
        self._voice_library_tmp_dir()
        self._ensure_builtin_manifest_exists()
        await self._migrate_existing_item_audio_paths()
        desired_rows = self._load_builtin_manifest_rows()

        existing_result = await self.db.execute(
            select(VoiceLibraryItem)
            .where(
                or_(
                    VoiceLibraryItem.is_builtin.is_(True),
                    VoiceLibraryItem.source_channel == VoiceSourceChannel.BUILTIN,
                )
            )
            .order_by(VoiceLibraryItem.id.asc())
        )
        existing_items = list(existing_result.scalars().all())

        existing_snapshot = [self._serialize_builtin_item_snapshot(item) for item in existing_items]
        if existing_snapshot == desired_rows:
            return

        existing_item_ids = [int(item.id) for item in existing_items]
        if existing_item_ids:
            task_result = await self.db.execute(
                select(VoiceLibraryImportTask).where(
                    VoiceLibraryImportTask.voice_library_item_id.in_(existing_item_ids)
                )
            )
            for task in task_result.scalars().all():
                task.voice_library_item_id = None

            for item in existing_items:
                await self.db.delete(item)

            await self.db.flush()

        for row in desired_rows:
            item = VoiceLibraryItem(
                name=str(row["name"]),
                reference_text=str(row["reference_text"]),
                audio_file_path=str(row["audio_file_path"]),
                is_enabled=True,
                is_builtin=True,
                builtin_key=str(row["builtin_key"]),
                source_channel=VoiceSourceChannel.BUILTIN,
                auto_parse_text=False,
                name_status=VoiceItemFieldStatus.READY,
                reference_text_status=VoiceItemFieldStatus.READY,
                processing_stage=None,
                processing_message=None,
                error_message=None,
            )
            self.db.add(item)

        await self.db.commit()

    async def list(
        self,
        *,
        q: str | None = None,
        enabled_only: bool = False,
        with_audio_only: bool = False,
        page: int | None = None,
        page_size: int | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        await self._ensure_builtin_seeded()

        query = select(VoiceLibraryItem)
        count_query = select(func.count()).select_from(VoiceLibraryItem)

        keyword = self._normalize_text(q)
        if keyword:
            like_pattern = f"%{keyword}%"
            query = query.where(VoiceLibraryItem.name.ilike(like_pattern))
            count_query = count_query.where(VoiceLibraryItem.name.ilike(like_pattern))
        if enabled_only:
            query = query.where(VoiceLibraryItem.is_enabled.is_(True))
            count_query = count_query.where(VoiceLibraryItem.is_enabled.is_(True))

        query = query.order_by(*self._default_order_clauses())

        if with_audio_only:
            result = await self.db.execute(query)
            items = list(result.scalars().all())
            serialized = [self._serialize_item(item) for item in items]
            filtered = [item for item in serialized if item["has_audio"]]
            total = len(filtered)
            if page is not None and page_size is not None:
                start = (page - 1) * page_size
                end = start + page_size
                return filtered[start:end], total
            return filtered, total

        total_result = await self.db.execute(count_query)
        total = int(total_result.scalar() or 0)
        if page is not None and page_size is not None:
            query = query.offset((page - 1) * page_size).limit(page_size)

        result = await self.db.execute(query)
        items = list(result.scalars().all())
        serialized = [self._serialize_item(item) for item in items]
        return serialized, total

    async def get(self, item_id: int) -> VoiceLibraryItem | None:
        await self._ensure_builtin_seeded()
        result = await self.db.execute(
            select(VoiceLibraryItem).where(VoiceLibraryItem.id == item_id)
        )
        return result.scalar_one_or_none()

    async def get_serialized(self, item_id: int) -> dict[str, Any]:
        item = await self.get(item_id)
        if not item:
            raise ServiceError(404, "语音预设不存在")
        return self._serialize_item(item)

    async def _create_item(
        self,
        *,
        name: str,
        reference_text: str,
        source_channel: VoiceSourceChannel,
        auto_parse_text: bool,
        source_url: str | None = None,
        source_file_name: str | None = None,
        source_post_id: str | None = None,
        source_post_updated_at: str | None = None,
        clip_start_requested_sec: float | None = None,
        clip_end_requested_sec: float | None = None,
        clip_start_actual_sec: float | None = None,
        clip_end_actual_sec: float | None = None,
        name_status: VoiceItemFieldStatus = VoiceItemFieldStatus.READY,
        reference_text_status: VoiceItemFieldStatus = VoiceItemFieldStatus.READY,
        processing_stage: str | None = None,
        processing_message: str | None = None,
        error_message: str | None = None,
        is_enabled: bool = True,
        auto_commit: bool = True,
    ) -> VoiceLibraryItem:
        item = VoiceLibraryItem(
            name=self._normalize_name(name),
            reference_text=self._normalize_text(reference_text),
            audio_file_path=None,
            is_enabled=bool(is_enabled),
            is_builtin=False,
            builtin_key=None,
            source_channel=source_channel,
            auto_parse_text=bool(auto_parse_text),
            source_url=self._normalize_text(source_url) or None,
            source_file_name=self._normalize_text(source_file_name) or None,
            source_post_id=self._normalize_text(source_post_id) or None,
            source_post_updated_at=self._normalize_text(source_post_updated_at) or None,
            clip_start_requested_sec=clip_start_requested_sec,
            clip_end_requested_sec=clip_end_requested_sec,
            clip_start_actual_sec=clip_start_actual_sec,
            clip_end_actual_sec=clip_end_actual_sec,
            name_status=name_status,
            reference_text_status=reference_text_status,
            processing_stage=processing_stage,
            processing_message=processing_message,
            error_message=error_message,
        )
        self.db.add(item)
        await self.db.flush()
        if auto_commit:
            await self.db.commit()
            await self.db.refresh(item)
        return item

    @classmethod
    def _is_uploaded_audio_path(cls, audio_file_path: str | None) -> bool:
        if not audio_file_path:
            return False
        try:
            normalized = cls._normalize_audio_file_path(audio_file_path, allow_empty=False)
        except ServiceError:
            return False
        if not normalized:
            return False
        return cls._is_within(Path(normalized), cls._voice_library_upload_dir())

    @classmethod
    def _delete_if_uploaded_audio(cls, audio_file_path: str | None) -> None:
        if not audio_file_path:
            return
        try:
            if not cls._is_uploaded_audio_path(audio_file_path):
                return
            target = Path(cls._normalize_audio_file_path(audio_file_path, allow_empty=False) or "")
            if target:
                target.unlink(missing_ok=True)
        except Exception:
            return

    async def _save_upload_audio_for_item(self, item: VoiceLibraryItem, file: UploadFile) -> str:
        filename = self._normalize_text(file.filename)
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_AUDIO_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_AUDIO_EXTENSIONS))
            raise ServiceError(400, f"音频格式不支持，仅支持: {supported}")

        upload_dir = self._voice_library_upload_dir()
        safe_token = secrets.token_hex(8)
        output_filename = f"voice_{item.id}_{int(time.time() * 1000)}_{safe_token}{suffix}"
        output_path = upload_dir / output_filename

        try:
            with output_path.open("wb") as fp:
                shutil.copyfileobj(file.file, fp)
        except Exception as exc:
            raise ServiceError(500, f"音频上传失败: {exc}") from exc
        finally:
            await file.close()

        self._delete_if_uploaded_audio(item.audio_file_path)
        item.audio_file_path = self._path_to_storage_public_url(output_path)
        logger.info(
            "[VoiceLibrary][UploadAudio] item_id=%s filename=%s path=%s size=%s",
            item.id,
            filename or "-",
            item.audio_file_path,
            int(output_path.stat().st_size or 0),
        )
        return item.audio_file_path

    async def _replace_item_audio_by_path(self, item: VoiceLibraryItem, source_path: Path) -> str:
        if not source_path.is_file():
            raise ServiceError(500, "音频文件不存在，无法写入卡片")

        suffix = source_path.suffix.lower() or ".wav"
        upload_dir = self._voice_library_upload_dir()
        safe_token = secrets.token_hex(8)
        output_filename = f"voice_{item.id}_{int(time.time() * 1000)}_{safe_token}{suffix}"
        output_path = upload_dir / output_filename

        self._delete_if_uploaded_audio(item.audio_file_path)
        shutil.move(str(source_path), str(output_path))
        item.audio_file_path = self._path_to_storage_public_url(output_path)
        logger.info(
            "[VoiceLibrary][ReplaceAudio] item_id=%s source=%s target=%s size=%s",
            item.id,
            source_path,
            item.audio_file_path,
            int(output_path.stat().st_size or 0),
        )
        return item.audio_file_path

    @staticmethod
    def _create_import_job_id() -> str:
        return f"job_{int(time.time() * 1000)}_{secrets.token_hex(4)}"

    @staticmethod
    def _extract_response_text_from_openai_responses(payload: dict[str, Any]) -> str:
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()
        if isinstance(output_text, list):
            chunks = [str(one) for one in output_text if str(one or "").strip()]
            if chunks:
                return "".join(chunks).strip()

        output = payload.get("output")
        if isinstance(output, list):
            parts: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    text = block.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text)
            if parts:
                return "".join(parts).strip()
        return ""

    async def _openai_responses_audio_completion(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str,
        system_prompt: str,
        prompt: str,
        audio_path: Path,
        temperature: float = 0.2,
    ) -> str:
        if not audio_path.is_file():
            return ""

        raw_bytes = audio_path.read_bytes()
        if not raw_bytes:
            return ""

        audio_format = audio_path.suffix.lower().lstrip(".") or "wav"
        if audio_format not in {"wav", "mp3", "m4a", "ogg", "flac"}:
            audio_format = "wav"
        audio_b64 = base64.b64encode(raw_bytes).decode("ascii")

        normalized_base_url = str(base_url or "").strip().rstrip("/")
        if not normalized_base_url:
            normalized_base_url = "https://api.openai.com/v1"

        payload = {
            "model": model,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": audio_b64,
                                "format": audio_format,
                            },
                        },
                    ],
                },
            ],
            "temperature": float(temperature),
        }

        async with httpx.AsyncClient(
            base_url=normalized_base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(300.0, connect=30.0),
            trust_env=True,
        ) as client:
            response = await client.post("/responses", json=payload)
            response.raise_for_status()
            data = response.json()

        text = self._extract_response_text_from_openai_responses(data)
        return self._normalize_text(text)

    async def _auto_name_by_openai_responses_audio(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str,
        prompt: str,
        audio_path: Path,
    ) -> str:
        text = await self._openai_responses_audio_completion(
            model=model,
            base_url=base_url,
            api_key=api_key,
            system_prompt=NAME_SYSTEM_PROMPT,
            prompt=prompt,
            audio_path=audio_path,
            temperature=0.2,
        )
        if not text:
            return ""
        parsed = self._extract_json_object_from_text(text)
        if parsed:
            return self._normalize_generated_name(str(parsed.get("name") or ""))
        return self._normalize_generated_name(text.splitlines()[0] if text else "")

    async def _auto_name_voice(
        self,
        *,
        item: VoiceLibraryItem,
    ) -> str:
        fallback = self._fallback_name(
            source_channel=item.source_channel,
            source_url=item.source_url,
            source_file_name=item.source_file_name,
            reference_text=item.reference_text,
        )

        reference_text = self._normalize_text(item.reference_text)
        source_file_name = self._normalize_text(item.source_file_name)
        normalized_audio_path = self._resolve_audio_file_for_io(item.audio_file_path)
        acoustic_features_text = "（无可用音频特征）"
        if normalized_audio_path and normalized_audio_path.is_file():
            try:
                acoustic_features = extract_wav_acoustic_features(
                    normalized_audio_path,
                    transcript_text=reference_text,
                )
                acoustic_features_text = format_acoustic_features_for_prompt(acoustic_features)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[VoiceLibrary][Naming] acoustic feature fallback item_id=%s error=%s",
                    item.id,
                    exc,
                )
        prompt = NAME_PROMPT_TEMPLATE.format(
            source_file_name=self._truncate_text(source_file_name or "（空）", 255),
            reference_text=self._truncate_text(reference_text or "（空）", 1500),
            acoustic_features=acoustic_features_text,
        )
        try:
            llm_runtime = resolve_llm_runtime(require_vision=False)
            self._log_llm_generate_input(
                action="Voice Naming",
                llm_runtime=llm_runtime,
                prompt=prompt,
                system_prompt=NAME_SYSTEM_PROMPT,
                extra_inputs={
                    "item_id": str(item.id),
                    "channel": item.source_channel.value if item.source_channel else "-",
                    "source_url": item.source_url or "-",
                    "source_file": item.source_file_name or "-",
                    "text_len": str(len(reference_text)),
                    "has_audio": str(
                        bool(normalized_audio_path and normalized_audio_path.is_file())
                    ),
                },
            )
            candidate = ""

            if not candidate:
                generated = await llm_runtime.provider.generate(
                    prompt=prompt,
                    system_prompt=NAME_SYSTEM_PROMPT,
                    temperature=0.2,
                )
                raw_text = str(getattr(generated, "content", "") or "").strip()
                parsed = self._extract_json_object_from_text(raw_text)
                candidate = self._normalize_generated_name(str(parsed.get("name") or ""))
                if not candidate and raw_text:
                    candidate = self._normalize_generated_name(raw_text.splitlines()[0])

            if candidate:
                logger.info(
                    "[VoiceLibrary][Naming] response item_id=%s name=%s",
                    item.id,
                    self._truncate_text(candidate, 80),
                )
                return candidate[:32]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Voice library auto name fallback: %s", exc)

        logger.info(
            "[VoiceLibrary][Naming] fallback item_id=%s name=%s",
            item.id,
            self._truncate_text(fallback, 80),
        )
        return fallback[:32]

    async def _transcribe_audio_with_progress(
        self,
        *,
        item: VoiceLibraryItem,
        task: VoiceLibraryImportTask | None = None,
    ) -> str:
        file_path = self._resolve_audio_file_for_io(item.audio_file_path)
        if not file_path:
            raise ServiceError(500, "缺少音频文件，无法转写")
        if not file_path.is_file():
            raise ServiceError(500, "音频文件不存在，无法转写")
        logger.info(
            "[VoiceLibrary][ASR] start item_id=%s task_id=%s audio=%s",
            item.id,
            task.id if task else "-",
            file_path,
        )

        last_commit_at = 0.0
        last_percent = -1

        async def _on_progress(progress_payload: dict[str, Any]) -> None:
            nonlocal last_commit_at, last_percent
            total_seconds = max(0.0, float(progress_payload.get("total_seconds") or 0.0))
            current_seconds = max(0.0, float(progress_payload.get("current_seconds") or 0.0))
            ratio = float(progress_payload.get("progress") or 0.0)
            percent = int(max(0, min(100, round(ratio * 100))))
            now = time.monotonic()

            should_commit = percent > last_percent or now - last_commit_at >= 0.9 or percent >= 100
            if not should_commit:
                return

            if total_seconds > 0:
                message = (
                    f"解析中：正在音频转写 {percent}% ({current_seconds:.1f}/{total_seconds:.1f}s)"
                )
            else:
                message = f"解析中：正在音频转写 {percent}%"

            self._set_item_state(
                item,
                reference_text_status=VoiceItemFieldStatus.RUNNING,
                stage=ITEM_STAGE_TRANSCRIBING,
                message=message,
                error=None,
            )
            if task is not None:
                self._set_task_state(
                    task,
                    status=VoiceImportTaskStatus.RUNNING,
                    stage=TASK_STAGE_TRANSCRIBING,
                    message=message,
                    error=None,
                )
            await self.db.commit()
            last_percent = percent
            last_commit_at = now

        from app.stages._audio_split import transcribe_audio_words

        words = await transcribe_audio_words(file_path, on_progress=_on_progress)
        from app.services.text_library_service import TextLibraryService

        transcript = TextLibraryService._join_whisper_words(words)
        transcript = self._normalize_text(transcript)
        if not transcript:
            raise ServiceError(500, "未识别出有效文本")
        logger.info(
            "[VoiceLibrary][ASR] done item_id=%s task_id=%s words=%s text_len=%s preview=%s",
            item.id,
            task.id if task else "-",
            len(words),
            len(transcript),
            self._truncate_text(transcript, 180),
        )
        return transcript

    async def _proofread_transcript_text(
        self,
        *,
        item: VoiceLibraryItem,
        transcript_text: str,
    ) -> str:
        raw_transcript = self._normalize_text(transcript_text)
        if not raw_transcript:
            return ""

        source_channel = item.source_channel.value if item.source_channel else "-"
        source_url = self._normalize_text(item.source_url) or "-"
        source_file_name = self._normalize_text(item.source_file_name) or "-"
        prompt = TRANSCRIPT_PROOFREAD_PROMPT_TEMPLATE.format(
            source_channel=source_channel,
            source_url=self._truncate_text(source_url, 500),
            source_file_name=self._truncate_text(source_file_name, 255),
            transcript=self._truncate_text(raw_transcript, 2600),
        )
        try:
            llm_runtime = resolve_llm_runtime()
            self._log_llm_generate_input(
                action="Transcript Proofread",
                llm_runtime=llm_runtime,
                prompt=prompt,
                system_prompt=TRANSCRIPT_PROOFREAD_SYSTEM_PROMPT,
                extra_inputs={
                    "item_id": str(item.id),
                    "channel": source_channel,
                    "source_url": source_url,
                    "source_file": source_file_name,
                    "raw_text_len": str(len(raw_transcript)),
                },
            )
            generated = await llm_runtime.provider.generate(
                prompt=prompt,
                system_prompt=TRANSCRIPT_PROOFREAD_SYSTEM_PROMPT,
                temperature=0.0,
            )
            raw_text = str(getattr(generated, "content", generated) or "").strip()
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
            candidate = re.sub(r"\n+", " ", candidate)
            candidate = re.sub(r"\s{2,}", " ", candidate).strip()
            if not self._is_strict_proofread_candidate(raw_transcript, candidate):
                logger.warning(
                    "[VoiceLibrary][Proofread] reject_over_generated item_id=%s raw_len=%s candidate_len=%s",
                    item.id,
                    len(raw_transcript),
                    len(candidate),
                )
                return raw_transcript
            if candidate:
                logger.info(
                    "[VoiceLibrary][Proofread] response item_id=%s text_len=%s",
                    item.id,
                    len(candidate),
                )
                return candidate
        except Exception as exc:  # noqa: BLE001
            logger.warning("Voice library transcript proofread fallback: %s", exc)

        logger.info(
            "[VoiceLibrary][Proofread] fallback item_id=%s text_len=%s",
            item.id,
            len(raw_transcript),
        )
        return raw_transcript

    @staticmethod
    def _normalize_for_strict_compare(text: str) -> str:
        normalized = str(text or "").strip()
        normalized = re.sub(r"\s+", "", normalized)
        normalized = re.sub(
            r"[，。！？；：、“”‘’\"'（）()《》【】\[\]<>…—\-_,.!?;:]", "", normalized
        )
        return normalized

    @classmethod
    def _is_strict_proofread_candidate(cls, raw_text: str, candidate_text: str) -> bool:
        raw = cls._normalize_for_strict_compare(raw_text)
        candidate = cls._normalize_for_strict_compare(candidate_text)
        if not raw or not candidate:
            return False

        matcher = difflib.SequenceMatcher(a=raw, b=candidate)
        similarity = float(matcher.ratio() or 0.0)
        inserted_chars = sum(
            max(0, j2 - j1) for tag, _, _, j1, j2 in matcher.get_opcodes() if tag == "insert"
        )
        max_inserted = max(2, int(len(raw) * 0.02))
        min_similarity = 0.92
        return inserted_chars <= max_inserted and similarity >= min_similarity

    @classmethod
    def _detect_video_channel(cls, source_url: str) -> VoiceSourceChannel:
        host = (urlparse(source_url).netloc or "").lower()
        if "xiaohongshu.com" in host or "xhslink.com" in host:
            return VoiceSourceChannel.VIDEO_LINK
        if "douyin.com" in host or "iesdouyin.com" in host:
            return VoiceSourceChannel.VIDEO_LINK
        if (
            "kuaishou.com" in host
            or "kuaishouapp.com" in host
            or "chenzhongtech.com" in host
            or "gifshow.com" in host
        ):
            return VoiceSourceChannel.VIDEO_LINK
        raise ServiceError(400, "仅支持小红书、抖音、快手链接")

    @classmethod
    def _map_video_url_to_text_source_channel(cls, source_url: str) -> TextSourceChannel:
        host = (urlparse(source_url).netloc or "").lower()
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
        raise ServiceError(400, "仅支持小红书、抖音、快手链接")

    @classmethod
    def _parse_timecode_to_seconds(cls, value: str | None) -> float | None:
        text = cls._normalize_text(value)
        if not text:
            return None

        if re.fullmatch(r"\d+(?:\.\d+)?", text):
            seconds = float(text)
            if seconds < 0:
                raise ServiceError(400, "时间不能为负数")
            return seconds

        parts = text.split(":")
        if len(parts) not in {2, 3}:
            raise ServiceError(400, "时间格式不正确，请使用 HH:MM:SS 或 MM:SS")

        try:
            if len(parts) == 2:
                minutes = int(parts[0])
                seconds = float(parts[1])
                total = minutes * 60 + seconds
            else:
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds = float(parts[2])
                total = hours * 3600 + minutes * 60 + seconds
        except ValueError as exc:
            raise ServiceError(400, "时间格式不正确，请使用 HH:MM:SS 或 MM:SS") from exc

        if total < 0:
            raise ServiceError(400, "时间不能为负数")
        return total

    @classmethod
    def _resolve_requested_clip_range(
        cls,
        *,
        start_seconds: float | None,
        end_seconds: float | None,
    ) -> tuple[float, float]:
        start = start_seconds
        end = end_seconds

        if start is None and end is None:
            return 0.0, 60.0
        if start is not None and end is None:
            if start < 0:
                raise ServiceError(400, "开始时间不能为负数")
            return start, start + 60.0
        if start is None and end is not None:
            if end < 0:
                raise ServiceError(400, "结束时间不能为负数")
            return max(end - 60.0, 0.0), end

        if start is None or end is None:
            raise ServiceError(400, "时间参数不合法")
        if start < 0 or end < 0:
            raise ServiceError(400, "时间不能为负数")
        if end <= start:
            raise ServiceError(400, "结束时间必须大于开始时间")
        if (end - start) > 60.0:
            raise ServiceError(400, "截取时间区间不能超过1分钟")
        return start, end

    @classmethod
    def _resolve_actual_clip_range(
        cls,
        *,
        requested_start: float,
        requested_end: float,
        total_duration: float,
    ) -> tuple[float, float]:
        duration = max(0.0, float(total_duration or 0.0))
        if duration <= 0.0:
            raise ServiceError(500, "媒体时长无效，无法截取音频")

        actual_start = min(max(float(requested_start), 0.0), duration)
        actual_end = min(max(float(requested_end), 0.0), duration)
        if actual_end - actual_start <= 0.01:
            raise ServiceError(400, "无法截取有效音频段：起止时间超出视频时长")
        return actual_start, actual_end

    async def _extract_audio_clip(
        self, *, media_path: Path, start_sec: float, end_sec: float, task_id: int
    ) -> Path:
        if end_sec - start_sec <= 0.01:
            raise ServiceError(400, "无法截取有效音频段")

        output_path = (
            self._voice_library_tmp_dir() / f"clip_{task_id}_{int(time.time() * 1000)}.wav"
        )
        duration = end_sec - start_sec
        logger.info(
            "[VoiceLibrary][Clip] start task_id=%s media=%s start=%.2f end=%.2f duration=%.2f",
            task_id,
            media_path,
            start_sec,
            end_sec,
            duration,
        )
        command = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{start_sec:.6f}",
            "-i",
            str(media_path),
            "-t",
            f"{duration:.6f}",
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(output_path),
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise ServiceError(500, "未找到 ffmpeg，请先安装并配置到 PATH") from exc

        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            detail = self._truncate_text(
                f"{stdout.decode(errors='ignore')}\n{stderr.decode(errors='ignore')}",
                1200,
            )
            raise ServiceError(500, f"音频截取失败: {detail}")

        if not output_path.is_file() or int(output_path.stat().st_size or 0) <= 0:
            raise ServiceError(500, "音频截取结果为空")
        logger.info(
            "[VoiceLibrary][Clip] done task_id=%s output=%s size=%s",
            task_id,
            output_path,
            int(output_path.stat().st_size or 0),
        )
        return output_path

    @classmethod
    async def _run_item_pipeline_background(cls, *, item_id: int) -> None:
        async with AsyncSessionLocal() as db:
            service = cls(db)
            try:
                item_result = await db.execute(
                    select(VoiceLibraryItem).where(VoiceLibraryItem.id == item_id)
                )
                item = item_result.scalar_one_or_none()
                if not item:
                    return

                item_audio_path = service._resolve_audio_file_for_io(item.audio_file_path)
                if not item_audio_path or not item_audio_path.is_file():
                    raise ServiceError(500, "音频文件不存在，无法处理")
                logger.info(
                    "[VoiceLibrary][ItemPipeline] start item_id=%s channel=%s auto_parse=%s audio=%s",
                    item.id,
                    item.source_channel.value if item.source_channel else "-",
                    bool(item.auto_parse_text),
                    item.audio_file_path,
                )

                auto_parse_text = bool(item.auto_parse_text)
                initial_name = service._normalize_text(item.name)
                has_fixed_name = (
                    item.name_status == VoiceItemFieldStatus.READY
                    and bool(initial_name)
                    and initial_name not in {"解析中", "命名中", "生成中"}
                )
                if auto_parse_text:
                    service._set_item_state(
                        item,
                        name_status=(
                            VoiceItemFieldStatus.READY
                            if has_fixed_name
                            else VoiceItemFieldStatus.PENDING
                        ),
                        reference_text_status=VoiceItemFieldStatus.RUNNING,
                        stage=ITEM_STAGE_TRANSCRIBING,
                        message="解析中：正在音频转写",
                        error=None,
                    )
                    await db.commit()

                    transcript = await run_card_stage(
                        stage=CardStage.TRANSCRIBE,
                        label=f"voice:item:transcribe:{item.id}",
                        priority=90,
                        coro_factory=lambda: service._transcribe_audio_with_progress(item=item),
                    )
                    logger.info(
                        "[VoiceLibrary][ItemPipeline] transcribed item_id=%s text_len=%s",
                        item.id,
                        len(service._normalize_text(transcript)),
                    )
                    service._set_item_state(
                        item,
                        reference_text_status=VoiceItemFieldStatus.RUNNING,
                        stage=ITEM_STAGE_PROOFREADING,
                        message="解析中：正在校对文本",
                        error=None,
                    )
                    await db.commit()

                    proofread_text = await run_card_stage(
                        stage=CardStage.AUDIO_PROOFREAD,
                        label=f"voice:item:proofread:{item.id}",
                        priority=210,
                        coro_factory=lambda: service._proofread_transcript_text(
                            item=item,
                            transcript_text=transcript,
                        ),
                    )
                    item.reference_text = proofread_text
                    logger.info(
                        "[VoiceLibrary][ItemPipeline] proofread item_id=%s text_len=%s",
                        item.id,
                        len(service._normalize_text(proofread_text)),
                    )
                    service._set_item_state(
                        item,
                        reference_text_status=VoiceItemFieldStatus.READY,
                        stage=ITEM_STAGE_GENERATING,
                        message="生成中：正在命名",
                        error=None,
                    )
                    await db.commit()
                else:
                    service._set_item_state(
                        item,
                        reference_text_status=VoiceItemFieldStatus.READY,
                        stage=ITEM_STAGE_GENERATING,
                        message="生成中：等待命名",
                        error=None,
                    )
                    await db.commit()

                normalized_name = service._normalize_text(item.name)
                should_generate_name = (
                    item.name_status != VoiceItemFieldStatus.READY
                    or (not normalized_name)
                    or normalized_name in {"解析中", "命名中", "生成中"}
                )
                if should_generate_name:
                    service._set_item_state(
                        item,
                        name_status=VoiceItemFieldStatus.RUNNING,
                        stage=ITEM_STAGE_GENERATING,
                        message="生成中：正在命名",
                        error=None,
                    )
                    await db.commit()

                    generated_name = await run_card_stage(
                        stage=CardStage.AUDIO_NAME,
                        label=f"voice:item:name:{item.id}",
                        priority=220,
                        coro_factory=lambda: service._auto_name_voice(item=item),
                    )
                    item.name = service._normalize_name(generated_name)
                    logger.info(
                        "[VoiceLibrary][ItemPipeline] named item_id=%s name=%s",
                        item.id,
                        item.name,
                    )
                else:
                    logger.info(
                        "[VoiceLibrary][ItemPipeline] skip naming item_id=%s name=%s",
                        item.id,
                        item.name,
                    )
                service._set_item_state(
                    item,
                    name_status=VoiceItemFieldStatus.READY,
                    reference_text_status=VoiceItemFieldStatus.READY,
                    stage=ITEM_STAGE_READY,
                    message=None,
                    error=None,
                )
                await db.commit()
                logger.info("[VoiceLibrary][ItemPipeline] done item_id=%s", item.id)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Voice library item pipeline failed item_id=%s", item_id)
                item_result = await db.execute(
                    select(VoiceLibraryItem).where(VoiceLibraryItem.id == item_id)
                )
                item = item_result.scalar_one_or_none()
                if item:
                    service._set_item_state(
                        item,
                        name_status=VoiceItemFieldStatus.FAILED,
                        reference_text_status=(
                            VoiceItemFieldStatus.FAILED
                            if item.reference_text_status
                            in {
                                VoiceItemFieldStatus.PENDING,
                                VoiceItemFieldStatus.RUNNING,
                            }
                            else item.reference_text_status
                        ),
                        stage=ITEM_STAGE_FAILED,
                        message="处理失败",
                        error=service._truncate_text(str(exc), 1000),
                    )
                    await db.commit()

    @classmethod
    def _launch_item_runner(cls, item_id: int) -> None:
        existing = cls._item_tasks.get(item_id)
        if existing and not existing.done():
            return
        task = asyncio.create_task(cls._run_item_pipeline_background(item_id=item_id))
        cls._item_tasks[item_id] = task
        logger.info("[VoiceLibrary][ItemPipeline] launched item_id=%s", item_id)

        def _cleanup(done_task: asyncio.Task[None]) -> None:
            stored = cls._item_tasks.get(item_id)
            if stored is done_task:
                cls._item_tasks.pop(item_id, None)

        task.add_done_callback(_cleanup)

    @classmethod
    def _cancel_item_runner(cls, item_id: int) -> bool:
        task = cls._item_tasks.get(int(item_id))
        if not task:
            return False
        if task.done():
            cls._item_tasks.pop(int(item_id), None)
            return False
        task.cancel()
        cls._item_tasks.pop(int(item_id), None)
        return True

    def _mark_item_pipeline_canceled(
        self,
        *,
        item: VoiceLibraryItem,
        reason: str,
        message: str = "任务已中断",
    ) -> None:
        next_name_status = (
            VoiceItemFieldStatus.CANCELED
            if item.name_status in {VoiceItemFieldStatus.PENDING, VoiceItemFieldStatus.RUNNING}
            else item.name_status
        )
        next_reference_status = (
            VoiceItemFieldStatus.CANCELED
            if item.reference_text_status
            in {VoiceItemFieldStatus.PENDING, VoiceItemFieldStatus.RUNNING}
            else item.reference_text_status
        )
        self._set_item_state(
            item,
            name_status=next_name_status,
            reference_text_status=next_reference_status,
            stage=ITEM_STAGE_CANCELED,
            message=message,
            error=None,
        )
        logger.info(
            "[VoiceLibrary][ItemPipeline] canceled item_id=%s reason=%s",
            item.id,
            reason,
        )

    async def _cancel_running_item_pipeline_tasks(
        self,
        *,
        item_ids: list[int] | None = None,
        reason: str,
    ) -> int:
        if item_ids is None:
            candidate_item_ids = [
                int(item_id)
                for item_id, task in list(type(self)._item_tasks.items())
                if task and not task.done()
            ]
        else:
            candidate_item_ids = [int(one) for one in item_ids]

        if not candidate_item_ids:
            return 0

        unique_item_ids = sorted(set(candidate_item_ids))
        items_result = await self.db.execute(
            select(VoiceLibraryItem).where(VoiceLibraryItem.id.in_(unique_item_ids))
        )
        item_map = {int(one.id): one for one in items_result.scalars().all()}

        canceled_count = 0
        for item_id in unique_item_ids:
            canceled = type(self)._cancel_item_runner(item_id)
            if not canceled:
                continue
            item = item_map.get(item_id)
            if item:
                self._mark_item_pipeline_canceled(item=item, reason=reason)
            canceled_count += 1
        return canceled_count

    async def import_audio_with_text(
        self, *, file: UploadFile, reference_text: str
    ) -> dict[str, Any]:
        await self._ensure_builtin_seeded()

        normalized_text = self._normalize_text(reference_text)
        if not normalized_text:
            raise ServiceError(400, "参考文本不能为空")
        logger.info(
            "[VoiceLibrary][ImportAudioWithText] start filename=%s text_len=%s",
            self._normalize_text(file.filename) or "-",
            len(normalized_text),
        )

        item = await self._create_item(
            name="命名中",
            reference_text=normalized_text,
            source_channel=VoiceSourceChannel.AUDIO_WITH_TEXT,
            auto_parse_text=False,
            source_file_name=self._normalize_text(file.filename) or None,
            name_status=VoiceItemFieldStatus.PENDING,
            reference_text_status=VoiceItemFieldStatus.READY,
            processing_stage=ITEM_STAGE_GENERATING,
            processing_message="生成中：正在命名",
            error_message=None,
            auto_commit=False,
        )
        await self._save_upload_audio_for_item(item, file)
        await self.db.commit()
        await self.db.refresh(item)

        self._launch_item_runner(item.id)
        logger.info(
            "[VoiceLibrary][ImportAudioWithText] created item_id=%s",
            item.id,
        )
        return self._serialize_item(item)

    async def import_audio_files(
        self, *, files: list[UploadFile], rows_json: str = ""
    ) -> dict[str, Any]:
        await self._ensure_builtin_seeded()

        batch_limit = get_library_batch_max_items()
        if not files:
            raise ServiceError(400, "请至少上传一个音频文件")
        if len(files) > batch_limit:
            raise ServiceError(400, f"最多支持上传 {batch_limit} 个音频文件")
        total_upload_bytes = sum(get_upload_file_size(file) for file in files)
        total_upload_limit = get_library_batch_max_total_upload_bytes()
        if total_upload_bytes > total_upload_limit:
            raise ServiceError(
                400,
                (
                    f"批量上传音频总大小不能超过 {get_library_batch_max_total_upload_mb()} MB，"
                    f"当前约 {total_upload_bytes / 1024 / 1024:.1f} MB"
                ),
            )
        row_map = self._parse_audio_import_rows(rows_json=rows_json, file_count=len(files))
        logger.info("[VoiceLibrary][ImportAudioFiles] start count=%s", len(files))

        created_ids: list[int] = []
        queued_ids: list[int] = []
        for index, file in enumerate(files):
            file_name = self._normalize_text(file.filename)
            suffix = Path(file_name).suffix.lower()
            if suffix not in SUPPORTED_AUDIO_EXTENSIONS:
                supported = ", ".join(sorted(SUPPORTED_AUDIO_EXTENSIONS))
                raise ServiceError(400, f"音频格式不支持，仅支持: {supported}")

            row = row_map.get(index)
            input_name = self._normalize_text(row.name) if row else ""
            auto_parse_text = bool(row.auto_parse_text) if row else True
            has_name = bool(input_name)
            should_queue = bool(auto_parse_text) or not has_name

            if not auto_parse_text and has_name:
                processing_stage = ITEM_STAGE_READY
                processing_message = None
            elif auto_parse_text:
                processing_stage = ITEM_STAGE_PENDING
                processing_message = "解析中：等待处理"
            else:
                processing_stage = ITEM_STAGE_PENDING
                processing_message = "生成中：等待命名"

            item = await self._create_item(
                name=input_name or ("解析中" if auto_parse_text else "命名中"),
                reference_text="",
                source_channel=VoiceSourceChannel.AUDIO_FILE,
                auto_parse_text=bool(auto_parse_text),
                source_file_name=file_name or None,
                name_status=(
                    VoiceItemFieldStatus.READY if has_name else VoiceItemFieldStatus.PENDING
                ),
                reference_text_status=(
                    VoiceItemFieldStatus.PENDING if auto_parse_text else VoiceItemFieldStatus.READY
                ),
                processing_stage=processing_stage,
                processing_message=processing_message,
                error_message=None,
                auto_commit=False,
            )
            await self._save_upload_audio_for_item(item, file)
            created_ids.append(item.id)
            if should_queue:
                queued_ids.append(item.id)
            logger.info(
                "[VoiceLibrary][ImportAudioFiles] prepared item_id=%s filename=%s parse=%s has_name=%s queued=%s",
                item.id,
                file_name or "-",
                bool(auto_parse_text),
                has_name,
                should_queue,
            )

        await self.db.commit()

        for item_id in queued_ids:
            self._launch_item_runner(item_id)
        logger.info(
            "[VoiceLibrary][ImportAudioFiles] queued item_ids=%s (created=%s)",
            queued_ids,
            created_ids,
        )
        return {"item_ids": created_ids}

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        await self._ensure_builtin_seeded()

        name = self._normalize_name(str(data.get("name") or ""))
        reference_text = self._normalize_text(str(data.get("reference_text") or ""))
        is_enabled = bool(data.get("is_enabled", True))
        audio_file_path: str | None = None
        if data.get("audio_file_path") is not None:
            audio_file_path = self._normalize_audio_file_path(
                str(data.get("audio_file_path") or ""),
                allow_empty=True,
            )
            if audio_file_path and not self._audio_file_exists(audio_file_path):
                raise ServiceError(400, "音频文件不存在，请先上传可访问的音频")
            if audio_file_path:
                audio_file_path = self._path_to_storage_public_url(Path(audio_file_path))

        item = VoiceLibraryItem(
            name=name,
            reference_text=reference_text,
            audio_file_path=audio_file_path,
            is_enabled=is_enabled,
            is_builtin=False,
            builtin_key=None,
            source_channel=VoiceSourceChannel.AUDIO_WITH_TEXT,
            auto_parse_text=False,
            name_status=VoiceItemFieldStatus.READY,
            reference_text_status=VoiceItemFieldStatus.READY,
            processing_stage=None,
            processing_message=None,
            error_message=None,
        )
        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)
        return self._serialize_item(item)

    async def update(self, item_id: int, data: dict[str, Any]) -> dict[str, Any]:
        item = await self.get(item_id)
        if not item:
            raise ServiceError(404, "语音预设不存在")
        self._ensure_item_editable(item, data)
        if self._is_item_processing(item):
            raise ServiceError(409, "当前卡片仍在处理中，请稍后再编辑")

        if data:
            self._clear_item_failed_state_on_manual_edit(item)
        if "name" in data:
            item.name = self._normalize_name(str(data.get("name") or ""))
        if "reference_text" in data:
            item.reference_text = self._normalize_text(str(data.get("reference_text") or ""))
        if "is_enabled" in data:
            item.is_enabled = bool(data.get("is_enabled"))
        if "audio_file_path" in data:
            next_audio_file_path = self._normalize_audio_file_path(
                str(data.get("audio_file_path") or ""),
                allow_empty=True,
            )
            if next_audio_file_path and not self._audio_file_exists(next_audio_file_path):
                raise ServiceError(400, "音频文件不存在，请先上传可访问的音频")
            if next_audio_file_path:
                next_audio_file_path = self._path_to_storage_public_url(Path(next_audio_file_path))
            item.audio_file_path = next_audio_file_path

        await self.db.commit()
        await self.db.refresh(item)
        return self._serialize_item(item)

    async def delete(self, item_id: int) -> None:
        item = await self.get(item_id)
        if not item:
            raise ServiceError(404, "语音预设不存在")
        self._ensure_item_mutable(item)

        self._delete_if_uploaded_audio(item.audio_file_path)
        await self.db.delete(item)
        await self.db.commit()

    async def upload_audio(self, item_id: int, file: UploadFile) -> dict[str, Any]:
        item = await self.get(item_id)
        if not item:
            raise ServiceError(404, "语音预设不存在")
        self._ensure_item_mutable(item)
        if self._is_item_processing(item):
            raise ServiceError(409, "当前卡片仍在处理中，请稍后再操作")

        await self._save_upload_audio_for_item(item, file)
        self._clear_item_failed_state_on_manual_edit(item)
        await self.db.commit()
        await self.db.refresh(item)
        return self._serialize_item(item)

    async def delete_audio(self, item_id: int) -> dict[str, Any]:
        item = await self.get(item_id)
        if not item:
            raise ServiceError(404, "语音预设不存在")
        self._ensure_item_mutable(item)
        if self._is_item_processing(item):
            raise ServiceError(409, "当前卡片仍在处理中，请稍后再操作")

        self._delete_if_uploaded_audio(item.audio_file_path)
        item.audio_file_path = None
        self._clear_item_failed_state_on_manual_edit(item)
        await self.db.commit()
        await self.db.refresh(item)
        return self._serialize_item(item)

    async def _create_video_import_task_with_item(
        self,
        *,
        job_id: str,
        source_url: str,
        requested_start: float,
        requested_end: float,
    ) -> int:
        item = await self._create_item(
            name="解析中",
            reference_text="",
            source_channel=VoiceSourceChannel.VIDEO_LINK,
            auto_parse_text=True,
            source_url=source_url,
            source_file_name=None,
            clip_start_requested_sec=requested_start,
            clip_end_requested_sec=requested_end,
            name_status=VoiceItemFieldStatus.PENDING,
            reference_text_status=VoiceItemFieldStatus.PENDING,
            processing_stage=ITEM_STAGE_PENDING,
            processing_message="解析中：等待处理",
            error_message=None,
            auto_commit=False,
        )
        self.db.add(
            VoiceLibraryImportTask(
                job_id=job_id,
                source_channel=VoiceSourceChannel.VIDEO_LINK,
                source_url=source_url,
                source_file_name=None,
                auto_parse_text=True,
                clip_start_requested_sec=requested_start,
                clip_end_requested_sec=requested_end,
                clip_start_actual_sec=None,
                clip_end_actual_sec=None,
                status=VoiceImportTaskStatus.PENDING,
                stage=TASK_STAGE_PENDING,
                stage_message="等待处理",
                error_message=None,
                cancel_requested=False,
                cancel_requested_at=None,
                cancel_reason=None,
                retry_of_task_id=None,
                retry_no=0,
                voice_library_item_id=item.id,
                source_post_id=None,
                source_post_updated_at=None,
            )
        )
        return int(item.id)

    async def create_video_link_import_job(
        self,
        *,
        source_url: str,
        start_time: str | None,
        end_time: str | None,
    ) -> dict[str, Any]:
        await self._ensure_builtin_seeded()

        normalized_url = self._normalize_text(source_url)
        if not normalized_url:
            raise ServiceError(400, "链接不能为空")
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://", normalized_url):
            normalized_url = f"https://{normalized_url}"
        parsed = urlparse(normalized_url)
        if not parsed.scheme or not parsed.netloc:
            raise ServiceError(400, "链接格式不合法")

        self._detect_video_channel(normalized_url)

        start_seconds = self._parse_timecode_to_seconds(start_time)
        end_seconds = self._parse_timecode_to_seconds(end_time)
        requested_start, requested_end = self._resolve_requested_clip_range(
            start_seconds=start_seconds,
            end_seconds=end_seconds,
        )
        logger.info(
            "[VoiceLibrary][ImportVideoLink] start url=%s start_time=%s end_time=%s clip=[%.2f, %.2f]",
            normalized_url,
            start_time or "-",
            end_time or "-",
            requested_start,
            requested_end,
        )

        job_id = self._create_import_job_id()
        job = VoiceLibraryImportJob(
            id=job_id,
            status=VoiceImportJobStatus.PENDING,
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
        item_id = await self._create_video_import_task_with_item(
            job_id=job_id,
            source_url=normalized_url,
            requested_start=requested_start,
            requested_end=requested_end,
        )
        await self.db.commit()

        self._launch_job_runner(job_id)
        logger.info(
            "[VoiceLibrary][ImportVideoLink] created job_id=%s item_id=%s",
            job_id,
            item_id,
        )
        return {"job_id": job_id, "job_ids": [job_id], "item_ids": [item_id]}

    async def get_import_job(self, job_id: str) -> dict[str, Any]:
        job_result = await self.db.execute(
            select(VoiceLibraryImportJob).where(VoiceLibraryImportJob.id == job_id)
        )
        job = job_result.scalar_one_or_none()
        if not job:
            raise ServiceError(404, "导入任务不存在")

        task_result = await self.db.execute(
            select(VoiceLibraryImportTask)
            .where(VoiceLibraryImportTask.job_id == job_id)
            .order_by(VoiceLibraryImportTask.id.asc())
        )
        tasks = list(task_result.scalars().all())
        total_count = len(tasks)
        success_count = sum(1 for task in tasks if task.status == VoiceImportTaskStatus.COMPLETED)
        failed_count = sum(1 for task in tasks if task.status == VoiceImportTaskStatus.FAILED)
        canceled_count = sum(1 for task in tasks if task.status == VoiceImportTaskStatus.CANCELED)
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

    @classmethod
    async def _run_import_job_background(cls, job_id: str) -> None:
        async with AsyncSessionLocal() as db:
            service = cls(db)
            try:
                logger.info("[VoiceLibrary][ImportJob] runner start job_id=%s", job_id)
                await service._execute_import_job(job_id)
            except asyncio.CancelledError:
                logger.info("[VoiceLibrary][ImportJob] runner canceled job_id=%s", job_id)
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
                        "[VoiceLibrary][ImportJob] failed to mark canceled after abort job_id=%s",
                        job_id,
                    )
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("Voice library import job failed: %s", job_id)
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
        logger.info("[VoiceLibrary][ImportJob] launched job_id=%s", job_id)

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
                select(VoiceLibraryImportTask)
                .join(
                    VoiceLibraryImportJob,
                    VoiceLibraryImportTask.job_id == VoiceLibraryImportJob.id,
                )
                .where(
                    VoiceLibraryImportJob.status.in_(
                        [VoiceImportJobStatus.PENDING, VoiceImportJobStatus.RUNNING]
                    ),
                    VoiceLibraryImportTask.status.in_(
                        [VoiceImportTaskStatus.PENDING, VoiceImportTaskStatus.RUNNING]
                    ),
                    VoiceLibraryImportTask.updated_at < cutoff,
                )
            )
            stale_tasks = list(stale_task_result.scalars().all())

            stale_job_result = await db.execute(
                select(VoiceLibraryImportJob).where(
                    VoiceLibraryImportJob.status.in_(
                        [VoiceImportJobStatus.PENDING, VoiceImportJobStatus.RUNNING]
                    ),
                    VoiceLibraryImportJob.updated_at < cutoff,
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
                select(VoiceLibraryImportJob).where(VoiceLibraryImportJob.id.in_(job_ids))
            )
            job_map = {str(one.id): one for one in jobs_result.scalars().all()}

            item_ids = {
                int(one.voice_library_item_id) for one in stale_tasks if one.voice_library_item_id
            }
            item_map: dict[int, VoiceLibraryItem] = {}
            if item_ids:
                item_result = await db.execute(
                    select(VoiceLibraryItem).where(VoiceLibraryItem.id.in_(item_ids))
                )
                item_map = {int(one.id): one for one in item_result.scalars().all()}

            reconciled_tasks = 0
            for task in stale_tasks:
                job = job_map.get(str(task.job_id))
                if not job:
                    continue
                if task.status not in {
                    VoiceImportTaskStatus.PENDING,
                    VoiceImportTaskStatus.RUNNING,
                }:
                    continue
                service._mark_task_and_item_canceled(
                    task=task,
                    item=item_map.get(int(task.voice_library_item_id or 0)),
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
                    VoiceImportJobStatus.PENDING,
                    VoiceImportJobStatus.RUNNING,
                }:
                    continue

                active_result = await db.execute(
                    select(VoiceLibraryImportTask.id).where(
                        VoiceLibraryImportTask.job_id == job.id,
                        VoiceLibraryImportTask.status.in_(
                            [VoiceImportTaskStatus.PENDING, VoiceImportTaskStatus.RUNNING]
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
                    job.status = VoiceImportJobStatus.CANCELED
                    job.error_message = None
                elif int(job.success_count or 0) == 0 and int(job.failed_count or 0) > 0:
                    job.status = VoiceImportJobStatus.FAILED
                    if not job.error_message:
                        job.error_message = "视频链接导入失败"
                else:
                    job.status = VoiceImportJobStatus.COMPLETED
                    job.error_message = None
                job.terminal_at = now
                reconciled_jobs += 1

            if reconciled_tasks > 0 or reconciled_jobs > 0:
                await db.commit()
                logger.warning(
                    "[VoiceLibrary][Reconciler] reconciled stale tasks=%s jobs=%s timeout=%ss",
                    reconciled_tasks,
                    reconciled_jobs,
                    timeout_seconds,
                )
            return {"reconciled_jobs": reconciled_jobs, "reconciled_tasks": reconciled_tasks}

    async def _mark_import_job_failed(self, job_id: str, message: str) -> None:
        job_result = await self.db.execute(
            select(VoiceLibraryImportJob).where(VoiceLibraryImportJob.id == job_id)
        )
        job = job_result.scalar_one_or_none()
        if not job:
            return
        job.status = VoiceImportJobStatus.FAILED
        job.error_message = self._truncate_text(message, 1000)
        job.terminal_at = datetime.now()
        logger.warning(
            "[VoiceLibrary][ImportJob] mark failed job_id=%s error=%s",
            job_id,
            self._truncate_text(message, 300),
        )
        await self.db.commit()

    def _mark_task_and_item_failed(
        self,
        *,
        task: VoiceLibraryImportTask,
        item: VoiceLibraryItem | None,
        job: VoiceLibraryImportJob,
        message: str,
        stage_message: str = "导入失败",
    ) -> None:
        error = self._truncate_text(message, 1000)
        self._set_task_state(
            task,
            status=VoiceImportTaskStatus.FAILED,
            stage=TASK_STAGE_FAILED,
            message=stage_message,
            error=error,
        )
        if item:
            self._set_item_state(
                item,
                name_status=VoiceItemFieldStatus.FAILED,
                reference_text_status=VoiceItemFieldStatus.FAILED,
                stage=ITEM_STAGE_FAILED,
                message="导入失败",
                error=error,
            )
        job.failed_count = int(job.failed_count or 0) + 1
        job.completed_count = int(job.completed_count or 0) + 1
        logger.warning(
            "[VoiceLibrary][ImportTask] failed job_id=%s task_id=%s item_id=%s stage=%s error=%s",
            job.id,
            task.id,
            item.id if item else "-",
            task.stage or "-",
            self._truncate_text(error, 300),
        )

    def _mark_task_and_item_canceled(
        self,
        *,
        task: VoiceLibraryImportTask,
        item: VoiceLibraryItem | None,
        job: VoiceLibraryImportJob,
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
            status=VoiceImportTaskStatus.CANCELED,
            stage=TASK_STAGE_CANCELED,
            message=stage_message,
            error=None,
        )
        if item and reset_item_fields:
            self._reset_item_on_hard_cancel(item=item)
        if item:
            self._set_item_state(
                item,
                name_status=VoiceItemFieldStatus.CANCELED,
                reference_text_status=VoiceItemFieldStatus.CANCELED,
                stage=ITEM_STAGE_CANCELED,
                message="任务已中断",
                error=None,
            )
        job.canceled_count = int(job.canceled_count or 0) + 1
        job.completed_count = int(job.completed_count or 0) + 1

    def _reset_item_on_hard_cancel(self, *, item: VoiceLibraryItem) -> None:
        item.name = "解析中"
        item.reference_text = ""
        item.clip_start_actual_sec = None
        item.clip_end_actual_sec = None

    async def _mark_import_job_canceled_after_abort(self, job_id: str, *, reason: str) -> None:
        job_result = await self.db.execute(
            select(VoiceLibraryImportJob).where(VoiceLibraryImportJob.id == str(job_id))
        )
        job = job_result.scalar_one_or_none()
        if not job:
            return

        task_result = await self.db.execute(
            select(VoiceLibraryImportTask).where(VoiceLibraryImportTask.job_id == str(job_id))
        )
        tasks = list(task_result.scalars().all())
        active_tasks = [
            one
            for one in tasks
            if one.status
            not in {
                VoiceImportTaskStatus.COMPLETED,
                VoiceImportTaskStatus.FAILED,
                VoiceImportTaskStatus.CANCELED,
            }
        ]
        item_ids = {
            int(one.voice_library_item_id) for one in active_tasks if one.voice_library_item_id
        }
        item_map: dict[int, VoiceLibraryItem] = {}
        if item_ids:
            item_result = await self.db.execute(
                select(VoiceLibraryItem).where(VoiceLibraryItem.id.in_(item_ids))
            )
            item_map = {int(one.id): one for one in item_result.scalars().all()}

        for task in active_tasks:
            self._mark_task_and_item_canceled(
                task=task,
                item=item_map.get(int(task.voice_library_item_id or 0)),
                job=job,
                reason=task.cancel_reason or reason,
                stage_message="任务已强制中断",
                reset_item_fields=True,
            )

        if not job.cancel_requested:
            job.cancel_requested = True
            job.cancel_requested_at = datetime.now()
            job.cancel_requested_by = "user"
        if active_tasks or job.status in {
            VoiceImportJobStatus.PENDING,
            VoiceImportJobStatus.RUNNING,
        }:
            job.status = VoiceImportJobStatus.CANCELED
            job.error_message = None
            job.terminal_at = datetime.now()
        await self.db.commit()

    async def _is_task_cancel_requested(self, *, job_id: str, task_id: int) -> tuple[bool, str]:
        task_result = await self.db.execute(
            select(
                VoiceLibraryImportTask.status,
                VoiceLibraryImportTask.cancel_requested,
                VoiceLibraryImportTask.cancel_reason,
            ).where(VoiceLibraryImportTask.id == int(task_id))
        )
        fresh_task = task_result.first()
        job_result = await self.db.execute(
            select(
                VoiceLibraryImportJob.status,
                VoiceLibraryImportJob.cancel_requested,
            ).where(VoiceLibraryImportJob.id == str(job_id))
        )
        fresh_job = job_result.first()
        if fresh_task:
            task_status, task_cancel_requested, task_cancel_reason = fresh_task
            if task_status == VoiceImportTaskStatus.CANCELED:
                return True, task_cancel_reason or "user_cancel"
            if bool(task_cancel_requested):
                return True, task_cancel_reason or "user_cancel"
        if fresh_job:
            job_status, job_cancel_requested = fresh_job
            if job_status == VoiceImportJobStatus.CANCELED or bool(job_cancel_requested):
                return True, "cancel_all"
        return False, ""

    async def cancel_all_import_jobs(self, *, canceled_by: str = "user") -> dict[str, int]:
        active_item_task_ids = [
            int(item_id)
            for item_id, task in list(type(self)._item_tasks.items())
            if task and not task.done()
        ]
        active_task_result = await self.db.execute(
            select(VoiceLibraryImportTask).where(
                VoiceLibraryImportTask.status.in_(
                    [VoiceImportTaskStatus.PENDING, VoiceImportTaskStatus.RUNNING]
                )
            )
        )
        tasks = list(active_task_result.scalars().all())
        task_job_ids = {str(one.job_id) for one in tasks}

        job_result = await self.db.execute(
            select(VoiceLibraryImportJob).where(
                or_(
                    VoiceLibraryImportJob.status.in_(
                        [VoiceImportJobStatus.PENDING, VoiceImportJobStatus.RUNNING]
                    ),
                    VoiceLibraryImportJob.id.in_(task_job_ids),
                )
            )
        )
        jobs = list(job_result.scalars().all())
        if not jobs and not tasks and not active_item_task_ids:
            return {"affected_jobs": 0, "affected_tasks": 0}

        item_ids = [
            int(one.voice_library_item_id or 0) for one in tasks if one.voice_library_item_id
        ]
        item_map: dict[int, VoiceLibraryItem] = {}
        if item_ids:
            items_result = await self.db.execute(
                select(VoiceLibraryItem).where(VoiceLibraryItem.id.in_(item_ids))
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
                VoiceImportTaskStatus.COMPLETED,
                VoiceImportTaskStatus.FAILED,
                VoiceImportTaskStatus.CANCELED,
            }:
                continue
            if task.cancel_requested:
                continue
            task.cancel_requested = True
            if task.cancel_requested_at is None:
                task.cancel_requested_at = datetime.now()
            task.cancel_reason = "cancel_all"
            if task.status == VoiceImportTaskStatus.PENDING:
                job = job_map.get(str(task.job_id))
                if job:
                    self._mark_task_and_item_canceled(
                        task=task,
                        item=item_map.get(int(task.voice_library_item_id or 0)),
                        job=job,
                        reason="cancel_all",
                    )
            affected_tasks += 1

        for job in jobs:
            if int(job.completed_count or 0) >= int(job.total_count or 0):
                job.status = VoiceImportJobStatus.CANCELED
                job.terminal_at = datetime.now()

        affected_tasks += await self._cancel_running_item_pipeline_tasks(
            item_ids=active_item_task_ids,
            reason="cancel_all",
        )

        await self.db.commit()
        for job in jobs:
            self._request_hard_cancel_job_runner(job.id)
        return {"affected_jobs": affected_jobs, "affected_tasks": affected_tasks}

    async def cancel_import_job(self, job_id: str, *, canceled_by: str = "user") -> dict[str, int]:
        job = await self.db.get(VoiceLibraryImportJob, str(job_id))
        if not job:
            raise ServiceError(404, "导入任务不存在")

        task_result = await self.db.execute(
            select(VoiceLibraryImportTask).where(VoiceLibraryImportTask.job_id == job.id)
        )
        tasks = list(task_result.scalars().all())
        active_tasks = [
            one
            for one in tasks
            if one.status
            not in {
                VoiceImportTaskStatus.COMPLETED,
                VoiceImportTaskStatus.FAILED,
                VoiceImportTaskStatus.CANCELED,
            }
        ]
        if not active_tasks:
            return {"affected_jobs": 0, "affected_tasks": 0}
        item_ids = {int(one.voice_library_item_id) for one in tasks if one.voice_library_item_id}
        item_map: dict[int, VoiceLibraryItem] = {}
        if item_ids:
            item_result = await self.db.execute(
                select(VoiceLibraryItem).where(VoiceLibraryItem.id.in_(item_ids))
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
                VoiceImportTaskStatus.COMPLETED,
                VoiceImportTaskStatus.FAILED,
                VoiceImportTaskStatus.CANCELED,
            }:
                continue
            if task.cancel_requested:
                continue
            task.cancel_requested = True
            if task.cancel_requested_at is None:
                task.cancel_requested_at = datetime.now()
            task.cancel_reason = "user_cancel_job"
            if task.status == VoiceImportTaskStatus.PENDING:
                self._mark_task_and_item_canceled(
                    task=task,
                    item=item_map.get(int(task.voice_library_item_id or 0)),
                    job=job,
                    reason="user_cancel_job",
                )
            affected_tasks += 1

        if int(job.completed_count or 0) >= int(job.total_count or 0):
            job.status = VoiceImportJobStatus.CANCELED
            job.terminal_at = datetime.now()

        await self.db.commit()
        self._request_hard_cancel_job_runner(job.id)
        return {"affected_jobs": affected_jobs, "affected_tasks": affected_tasks}

    async def cancel_import_task(
        self, task_id: int, *, reason: str = "user_delete"
    ) -> dict[str, int]:
        task = await self.db.get(VoiceLibraryImportTask, int(task_id))
        if not task:
            raise ServiceError(404, "导入任务不存在")
        job = await self.db.get(VoiceLibraryImportJob, task.job_id)
        if not job:
            raise ServiceError(404, "导入任务不存在")
        item = (
            await self.db.get(VoiceLibraryItem, int(task.voice_library_item_id))
            if task.voice_library_item_id
            else None
        )
        if task.status in {
            VoiceImportTaskStatus.COMPLETED,
            VoiceImportTaskStatus.FAILED,
            VoiceImportTaskStatus.CANCELED,
        }:
            return {"affected_jobs": 0, "affected_tasks": 0}
        if task.cancel_requested:
            return {"affected_jobs": 0, "affected_tasks": 0}

        task.cancel_requested = True
        if task.cancel_requested_at is None:
            task.cancel_requested_at = datetime.now()
        task.cancel_reason = reason
        if task.status == VoiceImportTaskStatus.PENDING:
            self._mark_task_and_item_canceled(task=task, item=item, job=job, reason=reason)

        if int(job.completed_count or 0) >= int(job.total_count or 0):
            job.status = VoiceImportJobStatus.CANCELED
            job.terminal_at = datetime.now()

        await self.db.commit()
        return {"affected_jobs": 1 if job.cancel_requested else 0, "affected_tasks": 1}

    async def cancel_import_task_by_item(self, item_id: int) -> dict[str, int]:
        task_result = await self.db.execute(
            select(VoiceLibraryImportTask)
            .where(VoiceLibraryImportTask.voice_library_item_id == int(item_id))
            .order_by(VoiceLibraryImportTask.id.desc())
        )
        task = next(
            (
                one
                for one in task_result.scalars().all()
                if one.status
                not in {
                    VoiceImportTaskStatus.COMPLETED,
                    VoiceImportTaskStatus.FAILED,
                    VoiceImportTaskStatus.CANCELED,
                }
            ),
            None,
        )
        if not task:
            affected_item_tasks = await self._cancel_running_item_pipeline_tasks(
                item_ids=[int(item_id)],
                reason="user_cancel_item",
            )
            if affected_item_tasks <= 0:
                return {"affected_jobs": 0, "affected_tasks": 0}
            await self.db.commit()
            return {"affected_jobs": 0, "affected_tasks": affected_item_tasks}
        return await self.cancel_import_task(int(task.id), reason="user_delete")

    async def retry_import_task(self, task_id: int) -> dict[str, Any]:
        task = await self.db.get(VoiceLibraryImportTask, int(task_id))
        if not task:
            raise ServiceError(404, "导入任务不存在")
        if task.status not in {VoiceImportTaskStatus.FAILED, VoiceImportTaskStatus.CANCELED}:
            raise ServiceError(409, "仅失败或中断的任务可重试")
        item = (
            await self.db.get(VoiceLibraryItem, int(task.voice_library_item_id))
            if task.voice_library_item_id
            else None
        )
        if not item:
            raise ServiceError(404, "关联语音卡片不存在")

        job_id = self._create_import_job_id()
        job = VoiceLibraryImportJob(
            id=job_id,
            status=VoiceImportJobStatus.PENDING,
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
            VoiceLibraryImportTask(
                job_id=job_id,
                source_channel=task.source_channel,
                source_url=task.source_url,
                source_file_name=task.source_file_name,
                auto_parse_text=bool(task.auto_parse_text),
                clip_start_requested_sec=task.clip_start_requested_sec,
                clip_end_requested_sec=task.clip_end_requested_sec,
                clip_start_actual_sec=None,
                clip_end_actual_sec=None,
                status=VoiceImportTaskStatus.PENDING,
                stage=TASK_STAGE_PENDING,
                stage_message="等待处理",
                error_message=None,
                cancel_requested=False,
                cancel_requested_at=None,
                cancel_reason=None,
                retry_of_task_id=task.id,
                retry_no=next_retry_no,
                voice_library_item_id=item.id,
                source_post_id=task.source_post_id,
                source_post_updated_at=task.source_post_updated_at,
            )
        )

        item.name = "解析中"
        item.reference_text = ""
        item.name_status = VoiceItemFieldStatus.PENDING
        item.reference_text_status = VoiceItemFieldStatus.PENDING
        item.processing_stage = ITEM_STAGE_PENDING
        item.processing_message = "解析中：等待处理"
        item.error_message = None
        item.clip_start_actual_sec = None
        item.clip_end_actual_sec = None

        await self.db.commit()
        self._launch_job_runner(job_id)
        return {"job_id": job_id, "job_ids": [job_id], "item_ids": [int(item.id)]}

    async def restart_interrupted_tasks(self) -> dict[str, int]:
        task_result = await self.db.execute(
            select(VoiceLibraryImportTask).order_by(VoiceLibraryImportTask.id.desc())
        )
        all_tasks = list(task_result.scalars().all())
        latest_by_item: dict[int, VoiceLibraryImportTask] = {}
        for task in all_tasks:
            item_id = int(task.voice_library_item_id or 0)
            if item_id <= 0 or item_id in latest_by_item:
                continue
            latest_by_item[item_id] = task

        candidates = [
            one
            for one in latest_by_item.values()
            if one.status in {VoiceImportTaskStatus.CANCELED, VoiceImportTaskStatus.FAILED}
        ]
        if not candidates:
            return {"affected_jobs": 0, "affected_tasks": 0}

        item_ids = [
            int(one.voice_library_item_id or 0) for one in candidates if one.voice_library_item_id
        ]
        item_result = await self.db.execute(
            select(VoiceLibraryItem).where(VoiceLibraryItem.id.in_(item_ids))
        )
        item_map = {int(one.id): one for one in item_result.scalars().all()}

        retry_tasks = [one for one in candidates if int(one.voice_library_item_id or 0) in item_map]
        if not retry_tasks:
            return {"affected_jobs": 0, "affected_tasks": 0}

        job_ids: list[str] = []
        for old_task in sorted(retry_tasks, key=lambda one: int(one.id)):
            item = item_map.get(int(old_task.voice_library_item_id or 0))
            if not item:
                continue
            job_id = self._create_import_job_id()
            job_ids.append(job_id)
            self.db.add(
                VoiceLibraryImportJob(
                    id=job_id,
                    status=VoiceImportJobStatus.PENDING,
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
                VoiceLibraryImportTask(
                    job_id=job_id,
                    source_channel=old_task.source_channel,
                    source_url=old_task.source_url,
                    source_file_name=old_task.source_file_name,
                    auto_parse_text=bool(old_task.auto_parse_text),
                    clip_start_requested_sec=old_task.clip_start_requested_sec,
                    clip_end_requested_sec=old_task.clip_end_requested_sec,
                    clip_start_actual_sec=None,
                    clip_end_actual_sec=None,
                    status=VoiceImportTaskStatus.PENDING,
                    stage=TASK_STAGE_PENDING,
                    stage_message="等待继续",
                    error_message=None,
                    cancel_requested=False,
                    cancel_requested_at=None,
                    cancel_reason=None,
                    retry_of_task_id=old_task.id,
                    retry_no=int(old_task.retry_no or 0) + 1,
                    voice_library_item_id=item.id,
                    source_post_id=old_task.source_post_id,
                    source_post_updated_at=old_task.source_post_updated_at,
                )
            )
            item.name = "解析中"
            item.reference_text = ""
            item.name_status = VoiceItemFieldStatus.PENDING
            item.reference_text_status = VoiceItemFieldStatus.PENDING
            item.processing_stage = ITEM_STAGE_PENDING
            item.processing_message = "解析中：继续处理中"
            item.error_message = None
            item.clip_start_actual_sec = None
            item.clip_end_actual_sec = None

        await self.db.commit()
        for job_id in job_ids:
            self._launch_job_runner(job_id)
        return {"affected_jobs": len(job_ids), "affected_tasks": len(job_ids)}

    async def _execute_import_job(self, job_id: str) -> None:
        job_result = await self.db.execute(
            select(VoiceLibraryImportJob).where(VoiceLibraryImportJob.id == job_id)
        )
        job = job_result.scalar_one_or_none()
        if not job:
            return

        task_result = await self.db.execute(
            select(VoiceLibraryImportTask)
            .where(VoiceLibraryImportTask.job_id == job_id)
            .order_by(VoiceLibraryImportTask.id.asc())
        )
        tasks = list(task_result.scalars().all())
        if not tasks:
            job.status = VoiceImportJobStatus.FAILED
            job.error_message = "导入任务没有可执行项"
            await self.db.commit()
            return

        job.status = VoiceImportJobStatus.RUNNING
        job.total_count = len(tasks)
        job.completed_count = 0
        job.success_count = 0
        job.failed_count = 0
        job.canceled_count = 0
        job.error_message = None
        await self.db.commit()
        logger.info(
            "[VoiceLibrary][ImportJob] start job_id=%s total=%s",
            job_id,
            len(tasks),
        )

        item_ids = [
            int(task.voice_library_item_id or 0) for task in tasks if task.voice_library_item_id
        ]
        item_map: dict[int, VoiceLibraryItem] = {}
        if item_ids:
            item_result = await self.db.execute(
                select(VoiceLibraryItem).where(VoiceLibraryItem.id.in_(item_ids))
            )
            item_map = {item.id: item for item in item_result.scalars().all()}

        from app.services.text_library_service import TextLibraryService

        text_helper = TextLibraryService(self.db)

        for task in tasks:
            item = item_map.get(int(task.voice_library_item_id or 0))
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
                    message="任务缺少对应语音卡片",
                )
                await self.db.commit()
                continue

            try:
                logger.info(
                    "[VoiceLibrary][ImportTask] start job_id=%s task_id=%s source_url=%s clip_req=[%s,%s]",
                    job_id,
                    task.id,
                    task.source_url or "-",
                    task.clip_start_requested_sec,
                    task.clip_end_requested_sec,
                )
                self._set_task_state(
                    task,
                    status=VoiceImportTaskStatus.RUNNING,
                    stage=TASK_STAGE_EXTRACTING,
                    message="解析中：正在获取视频",
                    error=None,
                )
                self._set_item_state(
                    item,
                    name_status=VoiceItemFieldStatus.PENDING,
                    reference_text_status=VoiceItemFieldStatus.RUNNING,
                    stage=ITEM_STAGE_EXTRACTING,
                    message="解析中：正在获取视频",
                    error=None,
                )
                await self.db.commit()

                source_url = self._normalize_text(task.source_url)
                if not source_url:
                    raise ServiceError(400, "缺少视频链接")

                source_channel = self._map_video_url_to_text_source_channel(source_url)
                payload = await run_card_stage(
                    stage=CardStage.PARSE,
                    label=f"voice:parse:task:{task.id}",
                    priority=120,
                    coro_factory=lambda: text_helper._extract_media_url_by_downloader(
                        source_url=source_url,
                        source_channel=source_channel,
                    ),
                )
                media_url = self._normalize_text(payload.get("media_url"))
                media_kind = self._normalize_text(payload.get("media_kind"))
                if media_kind and media_kind != "video":
                    raise ServiceError(400, "该链接不是视频内容，无法提取音频")
                if not media_url:
                    raise ServiceError(500, "未解析到可用视频地址")
                logger.info(
                    "[VoiceLibrary][ImportTask] parsed job_id=%s task_id=%s media_url=%s media_kind=%s post_id=%s",
                    job_id,
                    task.id,
                    media_url,
                    media_kind or "-",
                    payload.get("post_id") or "-",
                )

                task.source_post_id = self._normalize_text(payload.get("post_id")) or None
                task.source_post_updated_at = (
                    self._normalize_text(payload.get("post_updated_at")) or None
                )
                item.source_post_id = task.source_post_id
                item.source_post_updated_at = task.source_post_updated_at
                await self.db.commit()

                media_path, _ = await run_card_stage(
                    stage=CardStage.DOWNLOAD,
                    label=f"voice:download:task:{task.id}",
                    priority=80,
                    coro_factory=lambda: text_helper._download_media_file(
                        media_url=media_url,
                        source_channel=source_channel,
                        task_id=task.id,
                        post_id=task.source_post_id,
                        post_updated_at=task.source_post_updated_at,
                    ),
                )
                from app.stages._audio_split import probe_audio_duration

                total_duration = await run_card_stage(
                    stage=CardStage.AUDIO_PREPARE,
                    label=f"voice:probe:task:{task.id}",
                    priority=95,
                    coro_factory=lambda: probe_audio_duration(media_path),
                )
                requested_start = float(task.clip_start_requested_sec or 0.0)
                requested_end = float(task.clip_end_requested_sec or (requested_start + 60.0))
                actual_start, actual_end = self._resolve_actual_clip_range(
                    requested_start=requested_start,
                    requested_end=requested_end,
                    total_duration=total_duration,
                )
                task.clip_start_actual_sec = actual_start
                task.clip_end_actual_sec = actual_end
                item.clip_start_actual_sec = actual_start
                item.clip_end_actual_sec = actual_end
                logger.info(
                    "[VoiceLibrary][ImportTask] downloaded job_id=%s task_id=%s media=%s total_duration=%.2f clip_actual=[%.2f,%.2f]",
                    job_id,
                    task.id,
                    media_path,
                    total_duration,
                    actual_start,
                    actual_end,
                )

                self._set_task_state(
                    task,
                    status=VoiceImportTaskStatus.RUNNING,
                    stage=TASK_STAGE_CLIPPING,
                    message="解析中：正在截取音频",
                    error=None,
                )
                self._set_item_state(
                    item,
                    reference_text_status=VoiceItemFieldStatus.RUNNING,
                    stage=ITEM_STAGE_CLIPPING,
                    message="解析中：正在截取音频",
                    error=None,
                )
                await self.db.commit()

                clip_path = await run_card_stage(
                    stage=CardStage.AUDIO_PREPARE,
                    label=f"voice:clip:task:{task.id}",
                    priority=95,
                    coro_factory=lambda: self._extract_audio_clip(
                        media_path=media_path,
                        start_sec=actual_start,
                        end_sec=actual_end,
                        task_id=task.id,
                    ),
                )
                await self._replace_item_audio_by_path(item, clip_path)
                logger.info(
                    "[VoiceLibrary][ImportTask] clip_ready job_id=%s task_id=%s clip=%s item_audio=%s",
                    job_id,
                    task.id,
                    clip_path,
                    item.audio_file_path,
                )

                self._set_task_state(
                    task,
                    status=VoiceImportTaskStatus.RUNNING,
                    stage=TASK_STAGE_TRANSCRIBING,
                    message="解析中：正在音频转写",
                    error=None,
                )
                self._set_item_state(
                    item,
                    reference_text_status=VoiceItemFieldStatus.RUNNING,
                    stage=ITEM_STAGE_TRANSCRIBING,
                    message="解析中：正在音频转写",
                    error=None,
                )
                await self.db.commit()

                transcript = await run_card_stage(
                    stage=CardStage.TRANSCRIBE,
                    label=f"voice:transcribe:task:{task.id}",
                    priority=90,
                    coro_factory=lambda: self._transcribe_audio_with_progress(item=item, task=task),
                )
                logger.info(
                    "[VoiceLibrary][ImportTask] transcribed job_id=%s task_id=%s text_len=%s",
                    job_id,
                    task.id,
                    len(self._normalize_text(transcript)),
                )

                self._set_task_state(
                    task,
                    status=VoiceImportTaskStatus.RUNNING,
                    stage=TASK_STAGE_PROOFREADING,
                    message="转写完成：正在校对文本",
                    error=None,
                )
                self._set_item_state(
                    item,
                    reference_text_status=VoiceItemFieldStatus.RUNNING,
                    stage=ITEM_STAGE_PROOFREADING,
                    message="解析中：正在校对文本",
                    error=None,
                )
                await self.db.commit()

                proofread_text = await run_card_stage(
                    stage=CardStage.AUDIO_PROOFREAD,
                    label=f"voice:proofread:task:{task.id}",
                    priority=210,
                    coro_factory=lambda: self._proofread_transcript_text(
                        item=item,
                        transcript_text=transcript,
                    ),
                )
                item.reference_text = proofread_text
                logger.info(
                    "[VoiceLibrary][ImportTask] proofread job_id=%s task_id=%s text_len=%s",
                    job_id,
                    task.id,
                    len(self._normalize_text(proofread_text)),
                )

                self._set_task_state(
                    task,
                    status=VoiceImportTaskStatus.RUNNING,
                    stage=TASK_STAGE_GENERATING,
                    message="生成中：正在命名",
                    error=None,
                )
                self._set_item_state(
                    item,
                    name_status=VoiceItemFieldStatus.RUNNING,
                    reference_text_status=VoiceItemFieldStatus.READY,
                    stage=ITEM_STAGE_GENERATING,
                    message="生成中：正在命名",
                    error=None,
                )
                await self.db.commit()

                generated_name = await run_card_stage(
                    stage=CardStage.AUDIO_NAME,
                    label=f"voice:name:task:{task.id}",
                    priority=220,
                    coro_factory=lambda: self._auto_name_voice(item=item),
                )
                item.name = self._normalize_name(generated_name)
                should_cancel, cancel_reason = await self._is_task_cancel_requested(
                    job_id=job_id,
                    task_id=task_id,
                )
                if should_cancel:
                    self._mark_task_and_item_canceled(
                        task=task,
                        item=item,
                        job=job,
                        reason=cancel_reason or "user_cancel",
                    )
                    await self.db.commit()
                    continue
                logger.info(
                    "[VoiceLibrary][ImportTask] named job_id=%s task_id=%s name=%s",
                    job_id,
                    task.id,
                    item.name,
                )
                self._set_task_state(
                    task,
                    status=VoiceImportTaskStatus.COMPLETED,
                    stage=TASK_STAGE_COMPLETED,
                    message="导入完成",
                    error=None,
                )
                self._set_item_state(
                    item,
                    name_status=VoiceItemFieldStatus.READY,
                    reference_text_status=VoiceItemFieldStatus.READY,
                    stage=ITEM_STAGE_READY,
                    message=None,
                    error=None,
                )
                job.success_count = int(job.success_count or 0) + 1
                job.completed_count = int(job.completed_count or 0) + 1
                await self.db.commit()
                logger.info(
                    "[VoiceLibrary][ImportTask] done job_id=%s task_id=%s item_id=%s",
                    job_id,
                    task.id,
                    item.id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Voice library import task failed task_id=%s: %s", task.id, exc)
                if bool(task.cancel_requested) or bool(job.cancel_requested):
                    self._mark_task_and_item_canceled(
                        task=task,
                        item=item,
                        job=job,
                        reason=task.cancel_reason or "cancel_all",
                    )
                else:
                    self._mark_task_and_item_failed(task=task, item=item, job=job, message=str(exc))
                await self.db.commit()

        if (
            int(job.success_count or 0) == 0
            and int(job.failed_count or 0) == 0
            and int(job.canceled_count or 0) > 0
        ):
            job.status = VoiceImportJobStatus.CANCELED
            job.error_message = None
        elif int(job.success_count or 0) == 0 and int(job.failed_count or 0) > 0:
            job.status = VoiceImportJobStatus.FAILED
            job.error_message = "视频链接导入失败"
        else:
            job.status = VoiceImportJobStatus.COMPLETED
            job.error_message = None
        job.terminal_at = datetime.now()
        await self.db.commit()
        logger.info(
            "[VoiceLibrary][ImportJob] finished job_id=%s status=%s success=%s failed=%s",
            job_id,
            job.status.value,
            int(job.success_count or 0),
            int(job.failed_count or 0),
        )

    async def retry_item(self, item_id: int) -> dict[str, Any]:
        item = await self.get(item_id)
        if not item:
            raise ServiceError(404, "语音预设不存在")
        self._ensure_item_mutable(item)
        if self._is_item_processing(item):
            raise ServiceError(409, "当前卡片仍在处理中，无需重试")
        logger.info(
            "[VoiceLibrary][Retry] start item_id=%s channel=%s",
            item.id,
            item.source_channel.value if item.source_channel else "-",
        )

        if item.source_channel == VoiceSourceChannel.VIDEO_LINK:
            source_url = self._normalize_text(item.source_url)
            if not source_url:
                raise ServiceError(400, "缺少原始链接，无法重试")

            requested_start = float(item.clip_start_requested_sec or 0.0)
            requested_end = float(item.clip_end_requested_sec or (requested_start + 60.0))

            job_id = self._create_import_job_id()
            self.db.add(
                VoiceLibraryImportJob(
                    id=job_id,
                    status=VoiceImportJobStatus.PENDING,
                    total_count=1,
                    completed_count=0,
                    success_count=0,
                    failed_count=0,
                    error_message=None,
                )
            )

            self._set_item_state(
                item,
                name_status=VoiceItemFieldStatus.PENDING,
                reference_text_status=VoiceItemFieldStatus.PENDING,
                stage=ITEM_STAGE_PENDING,
                message="解析中：等待处理",
                error=None,
            )
            item.name = "解析中"
            item.reference_text = ""
            item.auto_parse_text = True
            item.clip_start_actual_sec = None
            item.clip_end_actual_sec = None

            self.db.add(
                VoiceLibraryImportTask(
                    job_id=job_id,
                    source_channel=VoiceSourceChannel.VIDEO_LINK,
                    source_url=source_url,
                    source_file_name=None,
                    auto_parse_text=True,
                    clip_start_requested_sec=requested_start,
                    clip_end_requested_sec=requested_end,
                    clip_start_actual_sec=None,
                    clip_end_actual_sec=None,
                    status=VoiceImportTaskStatus.PENDING,
                    stage=TASK_STAGE_PENDING,
                    stage_message="等待处理",
                    error_message=None,
                    voice_library_item_id=item.id,
                    source_post_id=item.source_post_id,
                    source_post_updated_at=item.source_post_updated_at,
                )
            )
            await self.db.commit()
            await self.db.refresh(item)
            self._launch_job_runner(job_id)
            logger.info(
                "[VoiceLibrary][Retry] restart import item_id=%s job_id=%s source_url=%s",
                item.id,
                job_id,
                source_url,
            )
            return self._serialize_item(item)

        if item.source_channel in {
            VoiceSourceChannel.AUDIO_FILE,
            VoiceSourceChannel.AUDIO_WITH_TEXT,
        }:
            item_audio_path = self._resolve_audio_file_for_io(item.audio_file_path)
            if not item_audio_path or not item_audio_path.is_file():
                raise ServiceError(400, "音频文件不存在，无法重试")

            if bool(item.auto_parse_text):
                item.reference_text = ""
                reference_status = VoiceItemFieldStatus.PENDING
                message = "解析中：等待处理"
                name = "解析中"
            else:
                reference_status = VoiceItemFieldStatus.READY
                message = "生成中：等待命名"
                name = "命名中"

            self._set_item_state(
                item,
                name_status=VoiceItemFieldStatus.PENDING,
                reference_text_status=reference_status,
                stage=ITEM_STAGE_PENDING,
                message=message,
                error=None,
            )
            item.name = name
            await self.db.commit()
            await self.db.refresh(item)
            self._launch_item_runner(item.id)
            logger.info(
                "[VoiceLibrary][Retry] restart item pipeline item_id=%s auto_parse=%s",
                item.id,
                bool(item.auto_parse_text),
            )
            return self._serialize_item(item)

        raise ServiceError(400, "当前卡片不支持重试")

    async def resolve_active_voice_by_audio_path(
        self, audio_file_path: str | None
    ) -> VoiceLibraryItem | None:
        await self._ensure_builtin_seeded()
        normalized_path = self._normalize_text(audio_file_path)
        if not normalized_path:
            return None
        candidate_paths: set[str] = {normalized_path.replace("\\", "/")}
        try:
            normalized_audio_path = self._normalize_audio_file_path(
                normalized_path, allow_empty=False
            )
        except ServiceError:
            return None
        if not normalized_audio_path:
            return None
        candidate_paths.add(normalized_audio_path)
        try:
            candidate_paths.add(self._path_to_storage_public_url(Path(normalized_audio_path)))
        except Exception:
            pass

        result = await self.db.execute(
            select(VoiceLibraryItem).where(
                VoiceLibraryItem.audio_file_path.in_(candidate_paths),
                VoiceLibraryItem.is_enabled.is_(True),
            )
        )
        item = result.scalar_one_or_none()
        if not item:
            return None
        if not self._audio_file_exists(item.audio_file_path):
            return None
        return item

    @staticmethod
    def _default_order_clauses() -> tuple[Any, Any, Any]:
        custom_first = case((VoiceLibraryItem.is_builtin.is_(False), 0), else_=1)
        custom_id_desc = case(
            (VoiceLibraryItem.is_builtin.is_(False), VoiceLibraryItem.id), else_=None
        ).desc()
        builtin_id_asc = case(
            (VoiceLibraryItem.is_builtin.is_(True), VoiceLibraryItem.id), else_=None
        ).asc()
        return custom_first, custom_id_desc, builtin_id_asc
