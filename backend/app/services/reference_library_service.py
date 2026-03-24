from __future__ import annotations

import asyncio
import base64
import json
import logging
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import ServiceError
from app.core.media_file import (
    resolve_image_ext,
    safe_delete_file,
    save_upload_file,
    validate_image_upload,
)
from app.core.reference_voice import normalize_reference_voice_payload
from app.db.session import AsyncSessionLocal
from app.llm.runtime import ResolvedLLMRuntime, resolve_llm_runtime
from app.models.reference_library import (
    ReferenceImportJobStatus,
    ReferenceImportTaskStatus,
    ReferenceItemFieldStatus,
    ReferenceLibraryImportJob,
    ReferenceLibraryImportTask,
    ReferenceLibraryItem,
    ReferenceSourceChannel,
)
from app.schemas.reference_library import (
    ReferenceLibraryCreate,
    ReferenceLibraryImportImageRow,
    ReferenceLibraryUpdate,
)
from app.services.library_import_limits import (
    get_library_batch_max_items,
    get_library_batch_max_total_upload_bytes,
    get_library_batch_max_total_upload_mb,
    get_upload_file_size,
)
from app.services.library_task_scheduler import CardStage, run_card_stage
from app.stages.common.log_utils import log_stage_separator
from app.stages.vision import generate_description_from_image

logger = logging.getLogger(__name__)

ITEM_STAGE_PENDING = "pending"
ITEM_STAGE_GENERATING = "generating"
ITEM_STAGE_READY = "ready"
ITEM_STAGE_FAILED = "failed"
ITEM_STAGE_CANCELED = "canceled"

TASK_STAGE_PENDING = "pending"
TASK_STAGE_GENERATING = "generating"
TASK_STAGE_COMPLETED = "completed"
TASK_STAGE_FAILED = "failed"
TASK_STAGE_CANCELED = "canceled"

REFERENCE_NAME_SYSTEM_PROMPT = "你是视觉命名专家，请根据图像可见信息输出简短、自然的中文名称。"
REFERENCE_NAME_PROMPT_TEMPLATE = (
    "请基于输入图片为参考卡片命名。\n"
    "要求：\n"
    "1) 严格输出 JSON，不输出其他文本；\n"
    "2) 字段固定为 name；\n"
    "3) 名称长度 2-12 个中文字符；\n"
    "4) 不要使用标点符号。\n\n"
    "补充信息（可能为空）：\n"
    "原始文件名：{source_file_name}\n\n"
    "输出格式：\n"
    '{{"name":"短名称"}}'
)
REFERENCE_NAME_DESC_SYSTEM_PROMPT = "你是严谨的视觉抽取助手，只根据图片可见信息输出 JSON。"
REFERENCE_NAME_DESC_PROMPT_TEMPLATE = (
    "请基于输入图片同时完成参考卡片命名与外观描述。\n"
    "要求：\n"
    "1) 严格输出 JSON，不输出其他文本；\n"
    "2) 字段固定为 name、appearance_description；\n"
    "3) name：2-12 个中文字符，不带标点符号；\n"
    "4) appearance_description：50-150 字，只描述可见信息，不扩展背景设定。\n\n"
    "补充信息（可能为空）：\n"
    "原始文件名：{source_file_name}\n\n"
    "输出格式：\n"
    '{{"name":"短名称","appearance_description":"描述文本"}}'
)


class ReferenceLibraryService:
    _storage_bootstrapped: bool = False
    _paths_migrated: bool = False
    _job_tasks: dict[str, asyncio.Task[None]] = {}

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        return str(value or "").strip()

    @classmethod
    def _normalize_name(cls, value: str | None) -> str:
        normalized = cls._normalize_text(value)
        if not normalized:
            raise ServiceError(400, "参考名称不能为空")
        return normalized[:255]

    @staticmethod
    def _truncate_text(value: str, limit: int = 1200) -> str:
        text = str(value or "")
        if len(text) <= limit:
            return text
        half = max(200, limit // 2)
        return f"{text[:half]}\n...\n{text[-half:]}"

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
        logger.info("[ReferenceLibrary] LLM Generate - %s", action)
        logger.info(
            "[Input] llm_provider=%s(%s) llm_model=%s",
            llm_runtime.provider_name,
            llm_runtime.provider_type,
            llm_runtime.model,
        )
        for key, value in (extra_inputs or {}).items():
            logger.info("[Input] %s=%s", key, self._truncate_text(value, 400))
        logger.info("[Input] prompt: %s", self._truncate_text(prompt, 1000))
        logger.info("[Input] system_prompt: %s", self._truncate_text(system_prompt, 600))
        log_stage_separator(logger)

    @staticmethod
    def _encode_image_base64(image_bytes: bytes) -> str:
        return base64.b64encode(image_bytes).decode("utf-8")

    @classmethod
    def _storage_root(cls) -> Path:
        path = Path(settings.storage_path).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def _reference_library_storage_dir(cls) -> Path:
        path = cls._storage_root() / "reference-library"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def _reference_library_builtin_dir(cls) -> Path:
        path = cls._reference_library_storage_dir() / "builtin"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def _reference_library_upload_dir(cls) -> Path:
        path = cls._reference_library_storage_dir() / "uploads"
        path.mkdir(parents=True, exist_ok=True)
        return path

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
        return f"/storage/{relative_path.as_posix()}"

    @classmethod
    def bootstrap_builtin_assets(cls) -> None:
        cls._reference_library_storage_dir()
        cls._reference_library_builtin_dir()
        cls._reference_library_upload_dir()

    @classmethod
    def _resolve_storage_public_path(cls, normalized: str) -> Path | None:
        if normalized.startswith("/storage/"):
            relative = normalized[len("/storage/") :].strip("/")
            if not relative:
                return None
            return (cls._storage_root() / relative).resolve()
        return None

    @classmethod
    def _normalize_image_file_path(
        cls,
        value: str | None,
        *,
        allow_empty: bool = True,
    ) -> str | None:
        raw = cls._normalize_text(value).replace("\\", "/")
        if not raw:
            if allow_empty:
                return None
            raise ServiceError(400, "参考图片路径不能为空")

        if raw.startswith("http://") or raw.startswith("https://"):
            raise ServiceError(400, "参考图片路径仅支持本地存储路径")

        normalized = raw if raw.startswith("/") else f"/{raw}"
        if ".." in normalized:
            raise ServiceError(400, "参考图片路径不合法")

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
            elif raw.startswith("reference-library/"):
                resolved_path = (cls._storage_root() / raw).resolve()
            else:
                filename = Path(raw).name
                if filename:
                    builtin_candidate = (cls._reference_library_builtin_dir() / filename).resolve()
                    if builtin_candidate.is_file():
                        resolved_path = builtin_candidate
                    else:
                        upload_candidate = (
                            cls._reference_library_upload_dir() / filename
                        ).resolve()
                        if upload_candidate.is_file():
                            resolved_path = upload_candidate

        if resolved_path is None:
            raise ServiceError(400, "参考图片路径不合法")

        if not cls._is_within(resolved_path, cls._reference_library_storage_dir()):
            raise ServiceError(400, "参考图片路径必须位于 storage/reference-library 下")

        return str(resolved_path)

    @classmethod
    def _resolve_image_file_for_io(cls, image_file_path: str | None) -> Path | None:
        if not image_file_path:
            return None
        try:
            normalized = cls._normalize_image_file_path(image_file_path, allow_empty=False)
        except ServiceError:
            return None
        if not normalized:
            return None
        return Path(normalized)

    async def _migrate_existing_item_image_paths(self) -> None:
        result = await self.db.execute(
            select(ReferenceLibraryItem).where(ReferenceLibraryItem.image_file_path.is_not(None))
        )
        items = list(result.scalars().all())
        changed = False

        for item in items:
            original_path = self._normalize_text(item.image_file_path)
            if not original_path:
                continue
            try:
                normalized = self._normalize_image_file_path(original_path, allow_empty=False)
            except ServiceError:
                continue
            if not normalized:
                continue
            normalized_public = self._path_to_storage_public_url(Path(normalized))
            if normalized_public != original_path:
                item.image_file_path = normalized_public
                item.image_updated_at = int(time.time())
                changed = True

        name_result = await self.db.execute(select(ReferenceLibraryItem))
        name_items = list(name_result.scalars().all())
        for item in name_items:
            if self._normalize_text(item.name):
                continue
            item.name = "命名中"
            changed = True

        if changed:
            await self.db.commit()

    async def _ensure_storage_ready(self) -> None:
        cls = self.__class__
        if not cls._storage_bootstrapped:
            cls.bootstrap_builtin_assets()
            cls._storage_bootstrapped = True

        if not cls._paths_migrated:
            await self._migrate_existing_item_image_paths()
            cls._paths_migrated = True

    @classmethod
    def _normalize_voice_payload(
        cls,
        *,
        can_speak: bool,
        voice_audio_provider: str | None,
        voice_name: str | None,
        voice_speed: float | None,
        voice_wan2gp_preset: str | None,
        voice_wan2gp_alt_prompt: str | None,
        voice_wan2gp_audio_guide: str | None,
        voice_wan2gp_temperature: float | None,
        voice_wan2gp_top_k: int | None,
        voice_wan2gp_seed: int | None,
    ) -> dict[str, str | float | int | None]:
        payload = normalize_reference_voice_payload(
            can_speak=can_speak,
            voice_audio_provider=voice_audio_provider,
            voice_name=voice_name,
            voice_speed=voice_speed,
            voice_wan2gp_preset=voice_wan2gp_preset,
            voice_wan2gp_alt_prompt=voice_wan2gp_alt_prompt,
            voice_wan2gp_audio_guide=voice_wan2gp_audio_guide,
            voice_wan2gp_temperature=voice_wan2gp_temperature,
            voice_wan2gp_top_k=voice_wan2gp_top_k,
            voice_wan2gp_seed=voice_wan2gp_seed,
            default_wan2gp_preset=settings.audio_wan2gp_preset,
        )
        return payload

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

        fenced = text
        if fenced.startswith("```"):
            fenced = fenced.strip("`")
            fenced = fenced.replace("json", "", 1).strip()
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
    def _fallback_name_by_file(cls, source_file_name: str) -> str:
        stem = Path(cls._normalize_text(source_file_name)).stem.strip()
        if stem:
            return stem[:12]
        return f"参考{int(time.time()) % 10000}"

    async def _generate_name_from_image(self, *, image_path: str, source_file_name: str) -> str:
        normalized_image_path = self._normalize_image_file_path(image_path, allow_empty=False)
        file_path = Path(normalized_image_path)
        prompt = REFERENCE_NAME_PROMPT_TEMPLATE.format(source_file_name=source_file_name or "-")
        try:
            llm_runtime = resolve_llm_runtime(require_vision=True)
            image_bytes = file_path.read_bytes()
            self._log_llm_generate_input(
                action="Reference Name",
                llm_runtime=llm_runtime,
                prompt=prompt,
                system_prompt=REFERENCE_NAME_SYSTEM_PROMPT,
                extra_inputs={
                    "source_file_name": source_file_name or "-",
                    "image_path": normalized_image_path,
                    "image_size": str(len(image_bytes)),
                },
            )
            response = await llm_runtime.provider.generate(
                prompt=prompt,
                system_prompt=REFERENCE_NAME_SYSTEM_PROMPT,
                temperature=0.2,
                max_tokens=160,
                image_base64=self._encode_image_base64(image_bytes),
            )
            raw_text = str(getattr(response, "content", response) or "").strip()
            payload = self._extract_json_object_from_text(raw_text)
            candidate = self._normalize_text(str(payload.get("name") or ""))
            if not candidate and raw_text:
                candidate = self._normalize_text(raw_text.splitlines()[0])
            candidate = candidate.replace("\n", "").strip()[:24]
            if candidate:
                return candidate
        except Exception as exc:  # noqa: BLE001
            logger.warning("Reference name generation fallback: %s", exc)
        return self._fallback_name_by_file(source_file_name)

    async def _generate_description_from_image(
        self, *, image_path: str, source_file_name: str
    ) -> str:
        normalized_image_path = self._normalize_image_file_path(image_path, allow_empty=False)
        logger.info(
            "[ReferenceLibrary] generate appearance_description with vision prompt file=%s image_path=%s",
            source_file_name or "-",
            normalized_image_path,
        )
        description = await generate_description_from_image(
            normalized_image_path,
            target_language="zh",
            prompt_complexity="normal",
        )
        return self._normalize_text(description)

    async def _generate_name_and_description_from_image(
        self, *, image_path: str, source_file_name: str
    ) -> dict[str, str]:
        normalized_image_path = self._normalize_image_file_path(image_path, allow_empty=False)
        file_path = Path(normalized_image_path)
        prompt = REFERENCE_NAME_DESC_PROMPT_TEMPLATE.format(
            source_file_name=source_file_name or "-"
        )
        llm_runtime = resolve_llm_runtime(require_vision=True)
        image_bytes = file_path.read_bytes()
        self._log_llm_generate_input(
            action="Reference Name + Description",
            llm_runtime=llm_runtime,
            prompt=prompt,
            system_prompt=REFERENCE_NAME_DESC_SYSTEM_PROMPT,
            extra_inputs={
                "source_file_name": source_file_name or "-",
                "image_path": normalized_image_path,
                "image_size": str(len(image_bytes)),
            },
        )
        response = await llm_runtime.provider.generate(
            prompt=prompt,
            system_prompt=REFERENCE_NAME_DESC_SYSTEM_PROMPT,
            temperature=0.2,
            max_tokens=320,
            image_base64=self._encode_image_base64(image_bytes),
        )
        raw_text = str(getattr(response, "content", response) or "").strip()
        logger.info("[Output] response: %s", self._truncate_text(raw_text, 1200))
        payload = self._extract_json_object_from_text(raw_text)

        generated_name = self._normalize_text(str(payload.get("name") or ""))
        generated_description = self._normalize_text(
            str(payload.get("appearance_description") or "")
        )

        generated_name = generated_name.replace("\n", "").strip()[:24]
        if not generated_name:
            generated_name = self._fallback_name_by_file(source_file_name)
        if not generated_description:
            raise ServiceError(500, "LLM 未返回有效图片描述")

        return {
            "name": generated_name,
            "appearance_description": generated_description,
        }

    def _set_item_state(
        self,
        item: ReferenceLibraryItem,
        *,
        name_status: ReferenceItemFieldStatus | None = None,
        appearance_status: ReferenceItemFieldStatus | None = None,
        stage: str | None = None,
        message: str | None = None,
        error: str | None = None,
    ) -> None:
        if name_status is not None:
            item.name_status = name_status
        if appearance_status is not None:
            item.appearance_status = appearance_status
        item.processing_stage = stage
        item.processing_message = message
        item.error_message = error

    def _set_task_state(
        self,
        task: ReferenceLibraryImportTask,
        *,
        status: ReferenceImportTaskStatus,
        stage: str,
        message: str | None = None,
        error: str | None = None,
    ) -> None:
        task.status = status
        task.stage = stage
        task.stage_message = message
        task.error_message = error

    def _clear_item_failed_state_on_manual_edit(self, item: ReferenceLibraryItem) -> None:
        if item.name_status == ReferenceItemFieldStatus.FAILED:
            item.name_status = ReferenceItemFieldStatus.READY
        if item.appearance_status == ReferenceItemFieldStatus.FAILED:
            item.appearance_status = ReferenceItemFieldStatus.READY
        item.processing_stage = None
        item.processing_message = None
        item.error_message = None

    @staticmethod
    def _serialize_import_task(task: ReferenceLibraryImportTask) -> dict[str, Any]:
        return {
            "id": task.id,
            "source_file_name": task.source_file_name,
            "input_name": task.input_name,
            "generate_description": bool(task.generate_description),
            "status": task.status,
            "stage": task.stage,
            "stage_message": task.stage_message,
            "error_message": task.error_message,
            "cancel_requested": bool(task.cancel_requested),
            "cancel_requested_at": task.cancel_requested_at,
            "cancel_reason": task.cancel_reason,
            "retry_of_task_id": task.retry_of_task_id,
            "retry_no": int(task.retry_no or 0),
            "reference_library_item_id": task.reference_library_item_id,
        }

    @staticmethod
    def _create_import_job_id() -> str:
        return f"job_{int(time.time() * 1000)}_{secrets.token_hex(4)}"

    @staticmethod
    def _resolve_case(input_name: str, generate_description: bool) -> str:
        has_name = bool(input_name)
        if has_name and not generate_description:
            return "name_ready_desc_skip"
        if has_name and generate_description:
            return "name_ready_desc_generate"
        if (not has_name) and (not generate_description):
            return "name_generate_desc_skip"
        return "name_generate_desc_generate"

    @classmethod
    def _parse_import_rows(
        cls,
        *,
        rows_json: str,
        file_count: int,
    ) -> dict[int, ReferenceLibraryImportImageRow]:
        text = cls._normalize_text(rows_json)
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except Exception as exc:  # noqa: BLE001
            raise ServiceError(400, f"rows_json 不是合法 JSON: {exc}") from exc

        if not isinstance(payload, list):
            raise ServiceError(400, "rows_json 必须是数组")

        row_map: dict[int, ReferenceLibraryImportImageRow] = {}
        for one in payload:
            row = ReferenceLibraryImportImageRow.model_validate(one)
            if row.index < 0 or row.index >= file_count:
                raise ServiceError(400, f"rows_json index 越界: {row.index}")
            row_map[int(row.index)] = row
        return row_map

    async def list(
        self,
        q: str | None = None,
        *,
        enabled_only: bool = False,
        page: int | None = None,
        page_size: int | None = None,
    ) -> tuple[list[ReferenceLibraryItem], int]:
        await self._ensure_storage_ready()

        query = select(ReferenceLibraryItem)
        count_query = select(func.count()).select_from(ReferenceLibraryItem)

        keyword = self._normalize_text(q)
        if keyword:
            like_pattern = f"%{keyword}%"
            query = query.where(ReferenceLibraryItem.name.ilike(like_pattern))
            count_query = count_query.where(ReferenceLibraryItem.name.ilike(like_pattern))
        if enabled_only:
            query = query.where(ReferenceLibraryItem.is_enabled.is_(True))
            count_query = count_query.where(ReferenceLibraryItem.is_enabled.is_(True))

        query = query.order_by(ReferenceLibraryItem.id.desc())

        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        if page is not None and page_size is not None:
            query = query.offset((page - 1) * page_size).limit(page_size)

        result = await self.db.execute(query)
        items = list(result.scalars().all())
        if self._ensure_items_non_empty_name(items):
            await self.db.commit()
        return items, total

    async def get(self, item_id: int) -> ReferenceLibraryItem | None:
        await self._ensure_storage_ready()
        result = await self.db.execute(
            select(ReferenceLibraryItem).where(ReferenceLibraryItem.id == item_id)
        )
        item = result.scalar_one_or_none()
        if item and not self._normalize_text(item.name):
            item.name = "命名中"
            await self.db.commit()
        return item

    def _ensure_items_non_empty_name(self, items: list[ReferenceLibraryItem]) -> bool:
        changed = False
        for item in items:
            if self._normalize_text(item.name):
                continue
            item.name = "命名中"
            changed = True
        return changed

    async def create(
        self, data: ReferenceLibraryCreate, file: UploadFile | None = None
    ) -> ReferenceLibraryItem:
        await self._ensure_storage_ready()

        normalized_voice = self._normalize_voice_payload(
            can_speak=bool(data.can_speak),
            voice_audio_provider=data.voice_audio_provider,
            voice_name=data.voice_name,
            voice_speed=data.voice_speed,
            voice_wan2gp_preset=data.voice_wan2gp_preset,
            voice_wan2gp_alt_prompt=data.voice_wan2gp_alt_prompt,
            voice_wan2gp_audio_guide=data.voice_wan2gp_audio_guide,
            voice_wan2gp_temperature=data.voice_wan2gp_temperature,
            voice_wan2gp_top_k=data.voice_wan2gp_top_k,
            voice_wan2gp_seed=data.voice_wan2gp_seed,
        )

        item = ReferenceLibraryItem(
            name=self._normalize_name(data.name),
            is_enabled=bool(data.is_enabled),
            can_speak=bool(data.can_speak),
            setting=self._normalize_text(data.setting),
            appearance_description=self._normalize_text(data.appearance_description),
            source_channel=ReferenceSourceChannel.MANUAL,
            source_file_name=None,
            name_status=ReferenceItemFieldStatus.READY,
            appearance_status=ReferenceItemFieldStatus.READY,
            processing_stage=None,
            processing_message=None,
            error_message=None,
            **normalized_voice,
        )
        self.db.add(item)
        await self.db.flush()

        if file:
            await self._validate_image_file(file)
            await self._replace_item_image(item, file)

        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def update(self, item_id: int, data: ReferenceLibraryUpdate) -> ReferenceLibraryItem:
        item = await self.get(item_id)
        if not item:
            raise ServiceError(404, "Reference library item not found")

        payload = data.model_dump(exclude_unset=True)
        if payload:
            self._clear_item_failed_state_on_manual_edit(item)
        if "name" in payload:
            item.name = self._normalize_name(payload.get("name"))
            item.name_status = ReferenceItemFieldStatus.READY
        if "is_enabled" in payload:
            item.is_enabled = bool(payload.get("is_enabled"))
        if "can_speak" in payload:
            item.can_speak = bool(payload.get("can_speak"))
        if "setting" in payload:
            item.setting = self._normalize_text(payload.get("setting"))
        if "appearance_description" in payload:
            item.appearance_description = self._normalize_text(
                payload.get("appearance_description")
            )
            item.appearance_status = ReferenceItemFieldStatus.READY

        if (
            "can_speak" in payload
            or "voice_audio_provider" in payload
            or "voice_name" in payload
            or "voice_speed" in payload
            or "voice_wan2gp_preset" in payload
            or "voice_wan2gp_alt_prompt" in payload
            or "voice_wan2gp_audio_guide" in payload
            or "voice_wan2gp_temperature" in payload
            or "voice_wan2gp_top_k" in payload
            or "voice_wan2gp_seed" in payload
        ):
            normalized_voice = self._normalize_voice_payload(
                can_speak=bool(item.can_speak),
                voice_audio_provider=(
                    payload.get("voice_audio_provider")
                    if "voice_audio_provider" in payload
                    else item.voice_audio_provider
                ),
                voice_name=(
                    payload.get("voice_name") if "voice_name" in payload else item.voice_name
                ),
                voice_speed=(
                    payload.get("voice_speed") if "voice_speed" in payload else item.voice_speed
                ),
                voice_wan2gp_preset=(
                    payload.get("voice_wan2gp_preset")
                    if "voice_wan2gp_preset" in payload
                    else item.voice_wan2gp_preset
                ),
                voice_wan2gp_alt_prompt=(
                    payload.get("voice_wan2gp_alt_prompt")
                    if "voice_wan2gp_alt_prompt" in payload
                    else item.voice_wan2gp_alt_prompt
                ),
                voice_wan2gp_audio_guide=(
                    payload.get("voice_wan2gp_audio_guide")
                    if "voice_wan2gp_audio_guide" in payload
                    else item.voice_wan2gp_audio_guide
                ),
                voice_wan2gp_temperature=(
                    payload.get("voice_wan2gp_temperature")
                    if "voice_wan2gp_temperature" in payload
                    else item.voice_wan2gp_temperature
                ),
                voice_wan2gp_top_k=(
                    payload.get("voice_wan2gp_top_k")
                    if "voice_wan2gp_top_k" in payload
                    else item.voice_wan2gp_top_k
                ),
                voice_wan2gp_seed=(
                    payload.get("voice_wan2gp_seed")
                    if "voice_wan2gp_seed" in payload
                    else item.voice_wan2gp_seed
                ),
            )
            item.voice_audio_provider = normalized_voice["voice_audio_provider"]
            item.voice_name = normalized_voice["voice_name"]
            item.voice_speed = normalized_voice["voice_speed"]
            item.voice_wan2gp_preset = normalized_voice["voice_wan2gp_preset"]
            item.voice_wan2gp_alt_prompt = normalized_voice["voice_wan2gp_alt_prompt"]
            item.voice_wan2gp_audio_guide = normalized_voice["voice_wan2gp_audio_guide"]
            item.voice_wan2gp_temperature = normalized_voice["voice_wan2gp_temperature"]
            item.voice_wan2gp_top_k = normalized_voice["voice_wan2gp_top_k"]
            item.voice_wan2gp_seed = normalized_voice["voice_wan2gp_seed"]

        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def delete(self, item_id: int) -> None:
        item = await self.get(item_id)
        if not item:
            raise ServiceError(404, "Reference library item not found")

        safe_delete_file(item.image_file_path)
        await self.db.delete(item)
        await self.db.commit()

    async def upload_image(self, item_id: int, file: UploadFile) -> ReferenceLibraryItem:
        await self._validate_image_file(file)
        item = await self.get(item_id)
        if not item:
            raise ServiceError(404, "Reference library item not found")

        await self._replace_item_image(item, file)
        self._clear_item_failed_state_on_manual_edit(item)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def delete_image(self, item_id: int) -> ReferenceLibraryItem:
        item = await self.get(item_id)
        if not item:
            raise ServiceError(404, "Reference library item not found")

        safe_delete_file(item.image_file_path)
        item.image_file_path = None
        item.image_updated_at = int(time.time())
        self._clear_item_failed_state_on_manual_edit(item)

        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def describe_from_image(
        self,
        item_id: int,
        target_language: str | None = None,
        prompt_complexity: str | None = None,
        llm_provider: str | None = None,
        llm_model: str | None = None,
    ) -> dict:
        item = await self.get(item_id)
        if not item:
            raise ServiceError(404, "Reference library item not found")
        image_file_path = self._resolve_image_file_for_io(item.image_file_path)
        if not image_file_path:
            raise ServiceError(
                400, "Reference has no image. Upload an image first before generating description."
            )

        try:
            new_description = await generate_description_from_image(
                str(image_file_path),
                target_language=target_language,
                prompt_complexity=prompt_complexity,
                llm_provider=llm_provider,
                llm_model=llm_model,
            )
            item.appearance_description = self._normalize_text(new_description)
            item.appearance_status = ReferenceItemFieldStatus.READY
            self._clear_item_failed_state_on_manual_edit(item)
            await self.db.commit()
            await self.db.refresh(item)
            return {
                "success": True,
                "appearance_description": item.appearance_description,
                "data": {
                    "id": item.id,
                    "name": item.name,
                    "appearance_description": item.appearance_description,
                },
            }
        except FileNotFoundError:
            raise ServiceError(404, "Reference image file not found")
        except ValueError as e:
            raise ServiceError(400, str(e))
        except Exception as e:
            raise ServiceError(500, f"Failed to generate description: {str(e)}")

    async def describe_from_uploaded_image(
        self,
        file: UploadFile,
        target_language: str | None = None,
        prompt_complexity: str | None = None,
        llm_provider: str | None = None,
        llm_model: str | None = None,
    ) -> dict:
        await self._validate_image_file(file)
        temp_dir = self._reference_library_storage_dir() / "_tmp_describe"
        temp_dir.mkdir(parents=True, exist_ok=True)
        ext = resolve_image_ext(file.content_type)
        temp_path = temp_dir / f"describe_{int(time.time() * 1000)}_{uuid4().hex[:8]}.{ext}"

        try:
            await save_upload_file(file, temp_path)
            description = await generate_description_from_image(
                str(temp_path),
                target_language=target_language,
                prompt_complexity=prompt_complexity,
                llm_provider=llm_provider,
                llm_model=llm_model,
            )
            return {
                "success": True,
                "appearance_description": self._normalize_text(description),
                "data": {
                    "source": "uploaded_file",
                },
            }
        except FileNotFoundError:
            raise ServiceError(404, "Uploaded image file not found")
        except ValueError as e:
            raise ServiceError(400, str(e))
        except Exception as e:
            raise ServiceError(500, f"Failed to generate description: {str(e)}")
        finally:
            safe_delete_file(str(temp_path))

    async def create_image_import_job(
        self, *, files: list[UploadFile], rows_json: str
    ) -> dict[str, Any]:
        await self._ensure_storage_ready()

        batch_limit = get_library_batch_max_items()
        if not files:
            raise ServiceError(400, "请至少上传一张图片")
        if len(files) > batch_limit:
            raise ServiceError(400, f"最多支持上传 {batch_limit} 张图片")

        total_upload_bytes = sum(get_upload_file_size(file) for file in files)
        total_upload_limit = get_library_batch_max_total_upload_bytes()
        if total_upload_bytes > total_upload_limit:
            raise ServiceError(
                400,
                (
                    f"批量上传图片总大小不能超过 {get_library_batch_max_total_upload_mb()} MB，"
                    f"当前约 {total_upload_bytes / 1024 / 1024:.1f} MB"
                ),
            )

        for file in files:
            await self._validate_image_file(file)

        row_map = self._parse_import_rows(rows_json=rows_json, file_count=len(files))

        job_ids: list[str] = []
        item_ids: list[int] = []
        try:
            for index, file in enumerate(files):
                file_name = self._normalize_text(file.filename) or f"image_{index + 1}.png"
                row = row_map.get(index)
                input_name = self._normalize_text(row.name) if row else ""
                generate_description = bool(row.generate_description) if row else True

                case = self._resolve_case(
                    input_name=input_name, generate_description=generate_description
                )
                needs_name = not bool(input_name)
                needs_desc = bool(generate_description)

                if case == "name_ready_desc_skip":
                    processing_stage = ITEM_STAGE_READY
                    processing_message = None
                elif case == "name_ready_desc_generate":
                    processing_stage = ITEM_STAGE_GENERATING
                    processing_message = "生成中：正在生成图片描述"
                elif case == "name_generate_desc_skip":
                    processing_stage = ITEM_STAGE_GENERATING
                    processing_message = "生成中：正在生成名称"
                else:
                    processing_stage = ITEM_STAGE_GENERATING
                    processing_message = "生成中：正在生成名称与描述"

                item = ReferenceLibraryItem(
                    name=input_name or "命名中",
                    is_enabled=True,
                    can_speak=False,
                    setting="",
                    appearance_description="",
                    source_channel=ReferenceSourceChannel.IMAGE_BATCH,
                    source_file_name=file_name,
                    name_status=(
                        ReferenceItemFieldStatus.PENDING
                        if needs_name
                        else ReferenceItemFieldStatus.READY
                    ),
                    appearance_status=(
                        ReferenceItemFieldStatus.PENDING
                        if needs_desc
                        else ReferenceItemFieldStatus.READY
                    ),
                    processing_stage=processing_stage,
                    processing_message=processing_message,
                    error_message=None,
                )
                self.db.add(item)
                await self.db.flush()
                await self._replace_item_image(item, file)

                item_ids.append(int(item.id))
                job_id = self._create_import_job_id()
                job_ids.append(job_id)
                self.db.add(
                    ReferenceLibraryImportJob(
                        id=job_id,
                        status=ReferenceImportJobStatus.PENDING,
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
                    ReferenceLibraryImportTask(
                        job_id=job_id,
                        source_file_name=file_name,
                        input_name=input_name or None,
                        generate_description=generate_description,
                        status=ReferenceImportTaskStatus.PENDING,
                        stage=TASK_STAGE_PENDING,
                        stage_message="等待处理",
                        error_message=None,
                        cancel_requested=False,
                        cancel_requested_at=None,
                        cancel_reason=None,
                        retry_of_task_id=None,
                        retry_no=0,
                        reference_library_item_id=item.id,
                    )
                )
        finally:
            for file in files:
                await file.close()

        await self.db.commit()
        for job_id in job_ids:
            self._launch_job_runner(job_id)
        logger.info(
            "[ReferenceLibrary][ImportImages] created job_ids=%s count=%s item_ids=%s",
            job_ids,
            len(item_ids),
            item_ids,
        )
        if not job_ids:
            raise ServiceError(500, "导入任务创建失败")
        return {
            "job_id": job_ids[0],
            "job_ids": job_ids,
            "item_ids": item_ids,
        }

    async def get_import_job(self, job_id: str) -> dict[str, Any]:
        job_result = await self.db.execute(
            select(ReferenceLibraryImportJob).where(ReferenceLibraryImportJob.id == job_id)
        )
        job = job_result.scalar_one_or_none()
        if not job:
            raise ServiceError(404, "导入任务不存在")

        task_result = await self.db.execute(
            select(ReferenceLibraryImportTask)
            .where(ReferenceLibraryImportTask.job_id == job_id)
            .order_by(ReferenceLibraryImportTask.id.asc())
        )
        tasks = list(task_result.scalars().all())
        total_count = len(tasks)
        success_count = sum(
            1 for task in tasks if task.status == ReferenceImportTaskStatus.COMPLETED
        )
        failed_count = sum(1 for task in tasks if task.status == ReferenceImportTaskStatus.FAILED)
        canceled_count = sum(
            1 for task in tasks if task.status == ReferenceImportTaskStatus.CANCELED
        )
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
                logger.info("[ReferenceLibrary][ImportJob] runner start job_id=%s", job_id)
                await service._execute_import_job(job_id)
            except asyncio.CancelledError:
                logger.info("[ReferenceLibrary][ImportJob] runner canceled job_id=%s", job_id)
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
                        "[ReferenceLibrary][ImportJob] failed to mark canceled after abort job_id=%s",
                        job_id,
                    )
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("Reference library import job failed: %s", job_id)
                try:
                    await db.rollback()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    await service._mark_import_job_failed(job_id, str(exc))
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "[ReferenceLibrary][ImportJob] failed to mark job failed status job_id=%s",
                        job_id,
                    )

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
                select(ReferenceLibraryImportTask)
                .join(
                    ReferenceLibraryImportJob,
                    ReferenceLibraryImportTask.job_id == ReferenceLibraryImportJob.id,
                )
                .where(
                    ReferenceLibraryImportJob.status.in_(
                        [ReferenceImportJobStatus.PENDING, ReferenceImportJobStatus.RUNNING]
                    ),
                    ReferenceLibraryImportTask.status.in_(
                        [ReferenceImportTaskStatus.PENDING, ReferenceImportTaskStatus.RUNNING]
                    ),
                    ReferenceLibraryImportTask.updated_at < cutoff,
                )
            )
            stale_tasks = list(stale_task_result.scalars().all())

            stale_job_result = await db.execute(
                select(ReferenceLibraryImportJob).where(
                    ReferenceLibraryImportJob.status.in_(
                        [ReferenceImportJobStatus.PENDING, ReferenceImportJobStatus.RUNNING]
                    ),
                    ReferenceLibraryImportJob.updated_at < cutoff,
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
                select(ReferenceLibraryImportJob).where(ReferenceLibraryImportJob.id.in_(job_ids))
            )
            job_map = {str(one.id): one for one in jobs_result.scalars().all()}

            item_ids = {
                int(one.reference_library_item_id)
                for one in stale_tasks
                if one.reference_library_item_id
            }
            item_map: dict[int, ReferenceLibraryItem] = {}
            if item_ids:
                items_result = await db.execute(
                    select(ReferenceLibraryItem).where(ReferenceLibraryItem.id.in_(item_ids))
                )
                item_map = {int(one.id): one for one in items_result.scalars().all()}

            reconciled_tasks = 0
            for task in stale_tasks:
                job = job_map.get(str(task.job_id))
                if not job:
                    continue
                if task.status not in {
                    ReferenceImportTaskStatus.PENDING,
                    ReferenceImportTaskStatus.RUNNING,
                }:
                    continue
                service._mark_task_and_item_canceled(
                    task=task,
                    item=item_map.get(int(task.reference_library_item_id or 0)),
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
                    ReferenceImportJobStatus.PENDING,
                    ReferenceImportJobStatus.RUNNING,
                }:
                    continue

                active_result = await db.execute(
                    select(ReferenceLibraryImportTask.id).where(
                        ReferenceLibraryImportTask.job_id == job.id,
                        ReferenceLibraryImportTask.status.in_(
                            [ReferenceImportTaskStatus.PENDING, ReferenceImportTaskStatus.RUNNING]
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
                    job.status = ReferenceImportJobStatus.CANCELED
                    job.error_message = None
                elif int(job.success_count or 0) == 0 and int(job.failed_count or 0) > 0:
                    job.status = ReferenceImportJobStatus.FAILED
                    if not job.error_message:
                        job.error_message = "图片导入全部失败"
                else:
                    job.status = ReferenceImportJobStatus.COMPLETED
                    job.error_message = None
                job.terminal_at = now
                reconciled_jobs += 1

            if reconciled_tasks > 0 or reconciled_jobs > 0:
                await db.commit()
                logger.warning(
                    "[ReferenceLibrary][Reconciler] reconciled stale tasks=%s jobs=%s timeout=%ss",
                    reconciled_tasks,
                    reconciled_jobs,
                    timeout_seconds,
                )
            return {"reconciled_jobs": reconciled_jobs, "reconciled_tasks": reconciled_tasks}

    async def _mark_import_job_failed(self, job_id: str, message: str) -> None:
        job_result = await self.db.execute(
            select(ReferenceLibraryImportJob).where(ReferenceLibraryImportJob.id == job_id)
        )
        job = job_result.scalar_one_or_none()
        if not job:
            return

        job.status = ReferenceImportJobStatus.FAILED
        job.error_message = self._truncate_text(message, 1000)
        job.terminal_at = datetime.now()
        await self.db.commit()

    def _mark_task_and_item_failed(
        self,
        *,
        task: ReferenceLibraryImportTask,
        item: ReferenceLibraryItem | None,
        job: ReferenceLibraryImportJob,
        message: str,
        stage_message: str = "导入失败",
    ) -> None:
        error = self._truncate_text(message, 1000)
        self._set_task_state(
            task,
            status=ReferenceImportTaskStatus.FAILED,
            stage=TASK_STAGE_FAILED,
            message=stage_message,
            error=error,
        )
        if item:
            self._set_item_state(
                item,
                name_status=ReferenceItemFieldStatus.FAILED,
                appearance_status=ReferenceItemFieldStatus.FAILED,
                stage=ITEM_STAGE_FAILED,
                message="导入失败",
                error=error,
            )
        job.failed_count = int(job.failed_count or 0) + 1
        job.completed_count = int(job.completed_count or 0) + 1

    def _mark_task_and_item_canceled(
        self,
        *,
        task: ReferenceLibraryImportTask,
        item: ReferenceLibraryItem | None,
        job: ReferenceLibraryImportJob,
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
            status=ReferenceImportTaskStatus.CANCELED,
            stage=TASK_STAGE_CANCELED,
            message=stage_message,
            error=None,
        )
        if item and reset_item_fields:
            self._reset_item_on_hard_cancel(task=task, item=item)
        if item:
            self._set_item_state(
                item,
                name_status=ReferenceItemFieldStatus.CANCELED,
                appearance_status=ReferenceItemFieldStatus.CANCELED,
                stage=ITEM_STAGE_CANCELED,
                message="任务已中断",
                error=None,
            )
        job.canceled_count = int(job.canceled_count or 0) + 1
        job.completed_count = int(job.completed_count or 0) + 1

    def _reset_item_on_hard_cancel(
        self,
        *,
        task: ReferenceLibraryImportTask,
        item: ReferenceLibraryItem,
    ) -> None:
        input_name = self._normalize_text(task.input_name)
        item.name = self._normalize_name(input_name) if input_name else "命名中"
        if bool(task.generate_description):
            item.appearance_description = ""

    async def _mark_import_job_canceled_after_abort(self, job_id: str, *, reason: str) -> None:
        job_result = await self.db.execute(
            select(ReferenceLibraryImportJob).where(ReferenceLibraryImportJob.id == str(job_id))
        )
        job = job_result.scalar_one_or_none()
        if not job:
            return

        task_result = await self.db.execute(
            select(ReferenceLibraryImportTask).where(
                ReferenceLibraryImportTask.job_id == str(job_id)
            )
        )
        tasks = list(task_result.scalars().all())
        active_tasks = [
            one
            for one in tasks
            if one.status
            not in {
                ReferenceImportTaskStatus.COMPLETED,
                ReferenceImportTaskStatus.FAILED,
                ReferenceImportTaskStatus.CANCELED,
            }
        ]
        item_ids = {
            int(one.reference_library_item_id)
            for one in active_tasks
            if one.reference_library_item_id
        }
        item_map: dict[int, ReferenceLibraryItem] = {}
        if item_ids:
            item_result = await self.db.execute(
                select(ReferenceLibraryItem).where(ReferenceLibraryItem.id.in_(item_ids))
            )
            item_map = {int(one.id): one for one in item_result.scalars().all()}

        for task in active_tasks:
            self._mark_task_and_item_canceled(
                task=task,
                item=item_map.get(int(task.reference_library_item_id or 0)),
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
            ReferenceImportJobStatus.PENDING,
            ReferenceImportJobStatus.RUNNING,
        }:
            job.status = ReferenceImportJobStatus.CANCELED
            job.error_message = None
            job.terminal_at = datetime.now()
        await self.db.commit()

    async def _is_task_cancel_requested(
        self,
        *,
        job_id: str,
        task_id: int,
    ) -> tuple[bool, str]:
        task_result = await self.db.execute(
            select(
                ReferenceLibraryImportTask.status,
                ReferenceLibraryImportTask.cancel_requested,
                ReferenceLibraryImportTask.cancel_reason,
            ).where(ReferenceLibraryImportTask.id == int(task_id))
        )
        fresh_task = task_result.first()
        job_result = await self.db.execute(
            select(
                ReferenceLibraryImportJob.status,
                ReferenceLibraryImportJob.cancel_requested,
            ).where(ReferenceLibraryImportJob.id == str(job_id))
        )
        fresh_job = job_result.first()
        if fresh_task:
            task_status, task_cancel_requested, task_cancel_reason = fresh_task
            if task_status == ReferenceImportTaskStatus.CANCELED:
                return True, task_cancel_reason or "user_cancel"
            if bool(task_cancel_requested):
                return True, task_cancel_reason or "user_cancel"
        if fresh_job:
            job_status, job_cancel_requested = fresh_job
            if job_status == ReferenceImportJobStatus.CANCELED or bool(job_cancel_requested):
                return True, "cancel_all"
        return False, ""

    async def cancel_all_import_jobs(self, *, canceled_by: str = "user") -> dict[str, int]:
        active_task_result = await self.db.execute(
            select(ReferenceLibraryImportTask).where(
                ReferenceLibraryImportTask.status.in_(
                    [ReferenceImportTaskStatus.PENDING, ReferenceImportTaskStatus.RUNNING]
                )
            )
        )
        tasks = list(active_task_result.scalars().all())
        task_job_ids = {str(one.job_id) for one in tasks}

        job_result = await self.db.execute(
            select(ReferenceLibraryImportJob).where(
                or_(
                    ReferenceLibraryImportJob.status.in_(
                        [ReferenceImportJobStatus.PENDING, ReferenceImportJobStatus.RUNNING]
                    ),
                    ReferenceLibraryImportJob.id.in_(task_job_ids),
                )
            )
        )
        jobs = list(job_result.scalars().all())
        if not jobs and not tasks:
            return {"affected_jobs": 0, "affected_tasks": 0}

        item_ids = [
            int(one.reference_library_item_id or 0)
            for one in tasks
            if one.reference_library_item_id
        ]
        item_map: dict[int, ReferenceLibraryItem] = {}
        if item_ids:
            items_result = await self.db.execute(
                select(ReferenceLibraryItem).where(ReferenceLibraryItem.id.in_(item_ids))
            )
            item_map = {int(one.id): one for one in items_result.scalars().all()}

        job_map = {str(one.id): one for one in jobs}
        affected_jobs = 0
        affected_tasks = 0
        for job in jobs:
            if not job.cancel_requested:
                job.cancel_requested = True
                if job.cancel_requested_at is None:
                    job.cancel_requested_at = datetime.now()
                job.cancel_requested_by = canceled_by
                affected_jobs += 1

        for task in tasks:
            if task.status in {
                ReferenceImportTaskStatus.COMPLETED,
                ReferenceImportTaskStatus.FAILED,
                ReferenceImportTaskStatus.CANCELED,
            }:
                continue
            if task.cancel_requested:
                continue
            task.cancel_requested = True
            if task.cancel_requested_at is None:
                task.cancel_requested_at = datetime.now()
            task.cancel_reason = "cancel_all"
            if task.status == ReferenceImportTaskStatus.PENDING:
                job = job_map.get(str(task.job_id))
                if job:
                    self._mark_task_and_item_canceled(
                        task=task,
                        item=item_map.get(int(task.reference_library_item_id or 0)),
                        job=job,
                        reason="cancel_all",
                    )
            affected_tasks += 1

        for job in jobs:
            if int(job.completed_count or 0) >= int(job.total_count or 0):
                job.status = ReferenceImportJobStatus.CANCELED
                job.terminal_at = datetime.now()

        await self.db.commit()
        for job in jobs:
            self._request_hard_cancel_job_runner(job.id)
        return {"affected_jobs": affected_jobs, "affected_tasks": affected_tasks}

    async def cancel_import_job(self, job_id: str, *, canceled_by: str = "user") -> dict[str, int]:
        job = await self.db.get(ReferenceLibraryImportJob, str(job_id))
        if not job:
            raise ServiceError(404, "导入任务不存在")

        task_result = await self.db.execute(
            select(ReferenceLibraryImportTask).where(ReferenceLibraryImportTask.job_id == job.id)
        )
        tasks = list(task_result.scalars().all())
        active_tasks = [
            one
            for one in tasks
            if one.status
            not in {
                ReferenceImportTaskStatus.COMPLETED,
                ReferenceImportTaskStatus.FAILED,
                ReferenceImportTaskStatus.CANCELED,
            }
        ]
        if not active_tasks:
            return {"affected_jobs": 0, "affected_tasks": 0}
        item_ids = {
            int(one.reference_library_item_id) for one in tasks if one.reference_library_item_id
        }
        item_map: dict[int, ReferenceLibraryItem] = {}
        if item_ids:
            item_result = await self.db.execute(
                select(ReferenceLibraryItem).where(ReferenceLibraryItem.id.in_(item_ids))
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
                ReferenceImportTaskStatus.COMPLETED,
                ReferenceImportTaskStatus.FAILED,
                ReferenceImportTaskStatus.CANCELED,
            }:
                continue
            if task.cancel_requested:
                continue
            task.cancel_requested = True
            if task.cancel_requested_at is None:
                task.cancel_requested_at = datetime.now()
            task.cancel_reason = "user_cancel_job"
            if task.status == ReferenceImportTaskStatus.PENDING:
                self._mark_task_and_item_canceled(
                    task=task,
                    item=item_map.get(int(task.reference_library_item_id or 0)),
                    job=job,
                    reason="user_cancel_job",
                )
            affected_tasks += 1

        if int(job.completed_count or 0) >= int(job.total_count or 0):
            job.status = ReferenceImportJobStatus.CANCELED
            job.terminal_at = datetime.now()

        await self.db.commit()
        self._request_hard_cancel_job_runner(job.id)
        return {"affected_jobs": affected_jobs, "affected_tasks": affected_tasks}

    async def cancel_import_task(
        self, task_id: int, *, reason: str = "user_delete"
    ) -> dict[str, int]:
        task = await self.db.get(ReferenceLibraryImportTask, int(task_id))
        if not task:
            raise ServiceError(404, "导入任务不存在")
        job = await self.db.get(ReferenceLibraryImportJob, task.job_id)
        if not job:
            raise ServiceError(404, "导入任务不存在")
        item = (
            await self.db.get(ReferenceLibraryItem, int(task.reference_library_item_id))
            if task.reference_library_item_id
            else None
        )

        if task.status in {
            ReferenceImportTaskStatus.COMPLETED,
            ReferenceImportTaskStatus.FAILED,
            ReferenceImportTaskStatus.CANCELED,
        }:
            return {"affected_jobs": 0, "affected_tasks": 0}
        if task.cancel_requested:
            return {"affected_jobs": 0, "affected_tasks": 0}

        task.cancel_requested = True
        if task.cancel_requested_at is None:
            task.cancel_requested_at = datetime.now()
        task.cancel_reason = reason

        if task.status == ReferenceImportTaskStatus.PENDING:
            self._mark_task_and_item_canceled(
                task=task,
                item=item,
                job=job,
                reason=reason,
            )

        if int(job.completed_count or 0) >= int(job.total_count or 0):
            job.status = ReferenceImportJobStatus.CANCELED
            job.terminal_at = datetime.now()

        await self.db.commit()
        return {"affected_jobs": 1 if job.cancel_requested else 0, "affected_tasks": 1}

    async def cancel_import_task_by_item(self, item_id: int) -> dict[str, int]:
        task_result = await self.db.execute(
            select(ReferenceLibraryImportTask)
            .where(ReferenceLibraryImportTask.reference_library_item_id == int(item_id))
            .order_by(ReferenceLibraryImportTask.id.desc())
        )
        task = next(
            (
                one
                for one in task_result.scalars().all()
                if one.status
                not in {
                    ReferenceImportTaskStatus.COMPLETED,
                    ReferenceImportTaskStatus.FAILED,
                    ReferenceImportTaskStatus.CANCELED,
                }
            ),
            None,
        )
        if not task:
            return {"affected_jobs": 0, "affected_tasks": 0}
        return await self.cancel_import_task(int(task.id), reason="user_delete")

    async def retry_item(self, item_id: int) -> ReferenceLibraryItem:
        item = await self.get(item_id)
        if not item:
            raise ServiceError(404, "参考卡片不存在")
        if item.name_status in {
            ReferenceItemFieldStatus.PENDING,
            ReferenceItemFieldStatus.RUNNING,
        } or item.appearance_status in {
            ReferenceItemFieldStatus.PENDING,
            ReferenceItemFieldStatus.RUNNING,
        }:
            raise ServiceError(409, "当前卡片仍在处理中，无需重试")

        task_result = await self.db.execute(
            select(ReferenceLibraryImportTask)
            .where(ReferenceLibraryImportTask.reference_library_item_id == int(item_id))
            .order_by(ReferenceLibraryImportTask.id.desc())
        )
        retry_task = next(
            (
                one
                for one in task_result.scalars().all()
                if one.status
                in {
                    ReferenceImportTaskStatus.FAILED,
                    ReferenceImportTaskStatus.CANCELED,
                }
            ),
            None,
        )
        if not retry_task:
            raise ServiceError(409, "该参考没有可重试的任务")

        await self.retry_import_task(int(retry_task.id))
        refreshed = await self.get(item_id)
        if not refreshed:
            raise ServiceError(404, "关联参考卡片不存在")
        return refreshed

    async def retry_import_task(self, task_id: int) -> dict[str, Any]:
        task = await self.db.get(ReferenceLibraryImportTask, int(task_id))
        if not task:
            raise ServiceError(404, "导入任务不存在")
        if task.status not in {
            ReferenceImportTaskStatus.FAILED,
            ReferenceImportTaskStatus.CANCELED,
        }:
            raise ServiceError(409, "仅失败或中断的任务可重试")

        item = (
            await self.db.get(ReferenceLibraryItem, int(task.reference_library_item_id))
            if task.reference_library_item_id
            else None
        )
        if not item:
            raise ServiceError(404, "关联参考卡片不存在")

        job_id = self._create_import_job_id()
        job = ReferenceLibraryImportJob(
            id=job_id,
            status=ReferenceImportJobStatus.PENDING,
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
            ReferenceLibraryImportTask(
                job_id=job_id,
                source_file_name=task.source_file_name,
                input_name=task.input_name,
                generate_description=bool(task.generate_description),
                status=ReferenceImportTaskStatus.PENDING,
                stage=TASK_STAGE_PENDING,
                stage_message="等待处理",
                error_message=None,
                cancel_requested=False,
                cancel_requested_at=None,
                cancel_reason=None,
                retry_of_task_id=task.id,
                retry_no=next_retry_no,
                reference_library_item_id=item.id,
            )
        )

        item.name = self._normalize_text(task.input_name) or "命名中"
        item.name_status = (
            ReferenceItemFieldStatus.PENDING
            if not self._normalize_text(task.input_name)
            else ReferenceItemFieldStatus.READY
        )
        item.appearance_status = (
            ReferenceItemFieldStatus.PENDING
            if bool(task.generate_description)
            else ReferenceItemFieldStatus.READY
        )
        item.processing_stage = ITEM_STAGE_PENDING
        item.processing_message = "解析中：等待处理"
        item.error_message = None

        await self.db.commit()
        self._launch_job_runner(job_id)
        return {"job_id": job_id, "job_ids": [job_id], "item_ids": [int(item.id)]}

    async def restart_interrupted_tasks(self) -> dict[str, int]:
        task_result = await self.db.execute(
            select(ReferenceLibraryImportTask).order_by(ReferenceLibraryImportTask.id.desc())
        )
        all_tasks = list(task_result.scalars().all())
        latest_by_item: dict[int, ReferenceLibraryImportTask] = {}
        for task in all_tasks:
            item_id = int(task.reference_library_item_id or 0)
            if item_id <= 0 or item_id in latest_by_item:
                continue
            latest_by_item[item_id] = task

        candidates = [
            one
            for one in latest_by_item.values()
            if one.status in {ReferenceImportTaskStatus.CANCELED, ReferenceImportTaskStatus.FAILED}
        ]
        if not candidates:
            return {"affected_jobs": 0, "affected_tasks": 0}

        item_ids = [
            int(one.reference_library_item_id or 0)
            for one in candidates
            if one.reference_library_item_id
        ]
        item_result = await self.db.execute(
            select(ReferenceLibraryItem).where(ReferenceLibraryItem.id.in_(item_ids))
        )
        item_map = {int(one.id): one for one in item_result.scalars().all()}

        retry_tasks = [
            one for one in candidates if int(one.reference_library_item_id or 0) in item_map
        ]
        if not retry_tasks:
            return {"affected_jobs": 0, "affected_tasks": 0}

        job_ids: list[str] = []
        for old_task in sorted(retry_tasks, key=lambda one: int(one.id)):
            item = item_map.get(int(old_task.reference_library_item_id or 0))
            if not item:
                continue
            job_id = self._create_import_job_id()
            job_ids.append(job_id)
            self.db.add(
                ReferenceLibraryImportJob(
                    id=job_id,
                    status=ReferenceImportJobStatus.PENDING,
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
                ReferenceLibraryImportTask(
                    job_id=job_id,
                    source_file_name=old_task.source_file_name,
                    input_name=old_task.input_name,
                    generate_description=bool(old_task.generate_description),
                    status=ReferenceImportTaskStatus.PENDING,
                    stage=TASK_STAGE_PENDING,
                    stage_message="等待继续",
                    error_message=None,
                    cancel_requested=False,
                    cancel_requested_at=None,
                    cancel_reason=None,
                    retry_of_task_id=old_task.id,
                    retry_no=int(old_task.retry_no or 0) + 1,
                    reference_library_item_id=item.id,
                )
            )
            item.name = self._normalize_text(old_task.input_name) or "命名中"
            item.name_status = (
                ReferenceItemFieldStatus.PENDING
                if not self._normalize_text(old_task.input_name)
                else ReferenceItemFieldStatus.READY
            )
            item.appearance_status = (
                ReferenceItemFieldStatus.PENDING
                if bool(old_task.generate_description)
                else ReferenceItemFieldStatus.READY
            )
            item.processing_stage = ITEM_STAGE_PENDING
            item.processing_message = "解析中：继续处理中"
            item.error_message = None

        await self.db.commit()
        for job_id in job_ids:
            self._launch_job_runner(job_id)
        return {"affected_jobs": len(job_ids), "affected_tasks": len(job_ids)}

    async def _execute_import_job(self, job_id: str) -> None:
        job_result = await self.db.execute(
            select(ReferenceLibraryImportJob).where(ReferenceLibraryImportJob.id == job_id)
        )
        job = job_result.scalar_one_or_none()
        if not job:
            return

        task_result = await self.db.execute(
            select(ReferenceLibraryImportTask)
            .where(ReferenceLibraryImportTask.job_id == job_id)
            .order_by(ReferenceLibraryImportTask.id.asc())
        )
        tasks = list(task_result.scalars().all())
        if not tasks:
            job.status = ReferenceImportJobStatus.FAILED
            job.error_message = "导入任务没有可执行项"
            await self.db.commit()
            return

        job.status = ReferenceImportJobStatus.RUNNING
        job.total_count = len(tasks)
        job.completed_count = 0
        job.success_count = 0
        job.failed_count = 0
        job.canceled_count = 0
        job.error_message = None
        await self.db.commit()

        item_ids = [
            int(task.reference_library_item_id or 0)
            for task in tasks
            if task.reference_library_item_id
        ]
        item_map: dict[int, ReferenceLibraryItem] = {}
        if item_ids:
            item_result = await self.db.execute(
                select(ReferenceLibraryItem).where(ReferenceLibraryItem.id.in_(item_ids))
            )
            item_map = {item.id: item for item in item_result.scalars().all()}

        for task in tasks:
            item = item_map.get(int(task.reference_library_item_id or 0))
            task_id = int(task.id)
            item_id = int(task.reference_library_item_id or 0)

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
                    message="任务缺少对应参考卡片",
                )
                await self.db.commit()
                continue

            input_name = self._normalize_text(task.input_name)
            generate_description = bool(task.generate_description)
            case = self._resolve_case(
                input_name=input_name, generate_description=generate_description
            )
            source_file_name = self._normalize_text(task.source_file_name) or "-"

            try:
                logger.info(
                    "[ReferenceLibrary][ImportTask] start job_id=%s task_id=%s item_id=%s case=%s file=%s",
                    job_id,
                    task_id,
                    item_id,
                    case,
                    source_file_name,
                )

                if case == "name_ready_desc_skip":
                    if input_name:
                        item.name = self._normalize_name(input_name)
                    self._set_task_state(
                        task,
                        status=ReferenceImportTaskStatus.COMPLETED,
                        stage=TASK_STAGE_COMPLETED,
                        message="导入完成",
                        error=None,
                    )
                    self._set_item_state(
                        item,
                        name_status=ReferenceItemFieldStatus.READY,
                        appearance_status=ReferenceItemFieldStatus.READY,
                        stage=ITEM_STAGE_READY,
                        message=None,
                        error=None,
                    )
                    job.success_count = int(job.success_count or 0) + 1
                    job.completed_count = int(job.completed_count or 0) + 1
                    await self.db.commit()
                    continue

                if case == "name_ready_desc_generate":
                    self._set_task_state(
                        task,
                        status=ReferenceImportTaskStatus.RUNNING,
                        stage=TASK_STAGE_GENERATING,
                        message="生成中：正在生成图片描述",
                        error=None,
                    )
                    self._set_item_state(
                        item,
                        appearance_status=ReferenceItemFieldStatus.RUNNING,
                        stage=ITEM_STAGE_GENERATING,
                        message="生成中：正在生成图片描述",
                        error=None,
                    )
                    await self.db.commit()

                    generated_desc = await run_card_stage(
                        stage=CardStage.REFERENCE_DESCRIBE,
                        label=f"reference:describe:task:{task_id}",
                        priority=210,
                        coro_factory=lambda: self._generate_description_from_image(
                            image_path=self._normalize_text(item.image_file_path),
                            source_file_name=source_file_name,
                        ),
                    )
                    item.appearance_description = self._normalize_text(generated_desc)
                    item.name = self._normalize_name(input_name)

                elif case == "name_generate_desc_skip":
                    self._set_task_state(
                        task,
                        status=ReferenceImportTaskStatus.RUNNING,
                        stage=TASK_STAGE_GENERATING,
                        message="生成中：正在生成名称",
                        error=None,
                    )
                    self._set_item_state(
                        item,
                        name_status=ReferenceItemFieldStatus.RUNNING,
                        stage=ITEM_STAGE_GENERATING,
                        message="生成中：正在生成名称",
                        error=None,
                    )
                    await self.db.commit()

                    generated_name = await run_card_stage(
                        stage=CardStage.REFERENCE_NAME,
                        label=f"reference:name:task:{task_id}",
                        priority=220,
                        coro_factory=lambda: self._generate_name_from_image(
                            image_path=self._normalize_text(item.image_file_path),
                            source_file_name=source_file_name,
                        ),
                    )
                    item.name = self._normalize_name(generated_name)

                else:
                    self._set_task_state(
                        task,
                        status=ReferenceImportTaskStatus.RUNNING,
                        stage=TASK_STAGE_GENERATING,
                        message="生成中：正在生成名称与描述",
                        error=None,
                    )
                    self._set_item_state(
                        item,
                        name_status=ReferenceItemFieldStatus.RUNNING,
                        appearance_status=ReferenceItemFieldStatus.RUNNING,
                        stage=ITEM_STAGE_GENERATING,
                        message="生成中：正在生成名称与描述",
                        error=None,
                    )
                    await self.db.commit()

                    generated_meta = await run_card_stage(
                        stage=CardStage.REFERENCE_DESCRIBE,
                        label=f"reference:name_desc:task:{task_id}",
                        priority=205,
                        coro_factory=lambda: self._generate_name_and_description_from_image(
                            image_path=self._normalize_text(item.image_file_path),
                            source_file_name=source_file_name,
                        ),
                    )
                    item.appearance_description = self._normalize_text(
                        str(generated_meta.get("appearance_description") or "")
                    )
                    item.name = self._normalize_name(str(generated_meta.get("name") or ""))

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

                self._set_task_state(
                    task,
                    status=ReferenceImportTaskStatus.COMPLETED,
                    stage=TASK_STAGE_COMPLETED,
                    message="导入完成",
                    error=None,
                )
                self._set_item_state(
                    item,
                    name_status=ReferenceItemFieldStatus.READY,
                    appearance_status=ReferenceItemFieldStatus.READY,
                    stage=ITEM_STAGE_READY,
                    message=None,
                    error=None,
                )
                job.success_count = int(job.success_count or 0) + 1
                job.completed_count = int(job.completed_count or 0) + 1
                await self.db.commit()

                logger.info(
                    "[ReferenceLibrary][ImportTask] done job_id=%s task_id=%s item_id=%s name=%s desc_len=%s",
                    job_id,
                    task_id,
                    item_id,
                    item.name,
                    len(self._normalize_text(item.appearance_description)),
                )
            except Exception as exc:  # noqa: BLE001
                error_text = str(exc)
                try:
                    await self.db.rollback()
                except Exception:  # noqa: BLE001
                    pass
                logger.warning(
                    "[ReferenceLibrary][ImportTask] failed job_id=%s task_id=%s error=%s",
                    job_id,
                    task_id,
                    error_text,
                )
                try:
                    fresh_job = await self.db.get(ReferenceLibraryImportJob, job_id)
                    fresh_task = await self.db.get(ReferenceLibraryImportTask, task_id)
                    fresh_item = (
                        await self.db.get(ReferenceLibraryItem, item_id) if item_id > 0 else None
                    )
                    if fresh_job and fresh_task:
                        if bool(fresh_task.cancel_requested) or bool(fresh_job.cancel_requested):
                            self._mark_task_and_item_canceled(
                                task=fresh_task,
                                item=fresh_item,
                                job=fresh_job,
                                reason=fresh_task.cancel_reason or "cancel_all",
                            )
                        else:
                            self._mark_task_and_item_failed(
                                task=fresh_task,
                                item=fresh_item,
                                job=fresh_job,
                                message=error_text,
                            )
                        await self.db.commit()
                    elif fresh_job:
                        fresh_job.status = ReferenceImportJobStatus.FAILED
                        fresh_job.error_message = self._truncate_text(error_text, 1000)
                        await self.db.commit()
                except Exception:  # noqa: BLE001
                    try:
                        await self.db.rollback()
                    except Exception:  # noqa: BLE001
                        pass
                    logger.exception(
                        "[ReferenceLibrary][ImportTask] fail-safe mark failed error job_id=%s task_id=%s",
                        job_id,
                        task_id,
                    )

        if (
            int(job.success_count or 0) == 0
            and int(job.failed_count or 0) == 0
            and int(job.canceled_count or 0) > 0
        ):
            job.status = ReferenceImportJobStatus.CANCELED
            job.error_message = None
        elif int(job.success_count or 0) == 0 and int(job.failed_count or 0) > 0:
            job.status = ReferenceImportJobStatus.FAILED
            job.error_message = "图片导入全部失败"
        else:
            job.status = ReferenceImportJobStatus.COMPLETED
            job.error_message = None
        job.terminal_at = datetime.now()
        await self.db.commit()

        logger.info(
            "[ReferenceLibrary][ImportJob] finished job_id=%s status=%s success=%s failed=%s",
            job_id,
            job.status.value,
            int(job.success_count or 0),
            int(job.failed_count or 0),
        )

    async def _replace_item_image(self, item: ReferenceLibraryItem, file: UploadFile) -> None:
        upload_dir = self._reference_library_upload_dir()
        ext = resolve_image_ext(file.content_type)

        output_path = upload_dir / f"reference_{item.id}.{ext}"

        for old_ext in ("png", "jpg", "webp"):
            old_path = upload_dir / f"reference_{item.id}.{old_ext}"
            if old_path.exists() and old_path != output_path:
                old_path.unlink(missing_ok=True)

        await save_upload_file(file, output_path)

        item.image_file_path = self._path_to_storage_public_url(output_path)
        item.image_updated_at = int(time.time())

    async def _validate_image_file(self, file: UploadFile) -> None:
        validate_image_upload(file)
