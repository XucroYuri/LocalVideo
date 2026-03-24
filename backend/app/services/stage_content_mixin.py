import json
import logging
import re
from typing import Any

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.core.dialogue import (
    DEFAULT_NARRATOR_NAME,
    DEFAULT_SINGLE_ROLE_NAME,
    DUO_ROLE_1_DEFAULT_DESCRIPTION,
    DUO_ROLE_1_DEFAULT_NAME,
    DUO_ROLE_1_ID,
    DUO_ROLE_2_DEFAULT_DESCRIPTION,
    DUO_ROLE_2_DEFAULT_NAME,
    DUO_ROLE_2_ID,
    DUO_SCENE_DEFAULT_DESCRIPTION,
    DUO_SCENE_ROLE_ID,
    NARRATOR_ALIASES,
    SCRIPT_MODE_CUSTOM,
    SCRIPT_MODE_DIALOGUE_SCRIPT,
    SCRIPT_MODE_DUO_PODCAST,
    SCRIPT_MODE_SINGLE,
    flatten_dialogue_text,
    generate_next_reference_id,
    is_reference_id,
    normalize_dialogue_lines,
    normalize_dialogue_max_roles,
    normalize_roles,
    resolve_script_mode,
)
from app.core.errors import ServiceError
from app.core.media_file import safe_delete_file
from app.core.pipeline import PipelineEngine
from app.core.project_mode import (
    VIDEO_MODE_ORAL_SCRIPT_DRIVEN,
    resolve_script_mode_from_video_type,
    resolve_video_type_from_script_mode,
)
from app.core.reference_voice import normalize_reference_voice_payload
from app.models.project import Project
from app.models.stage import StageExecution, StageStatus, StageType

logger = logging.getLogger(__name__)

EDGE_TTS_VOICE_YUNJIAN = "zh-CN-YunjianNeural"
EDGE_TTS_VOICE_XIAOYI = "zh-CN-XiaoyiNeural"


class StageContentMixin:
    """Content domain methods + content↔reference bridge helpers."""

    @staticmethod
    def _normalize_reference_text(value: Any) -> str:
        return str(value or "").strip()

    @classmethod
    def _normalize_reference_identity_key(cls, value: Any) -> str:
        text = cls._normalize_reference_text(value)
        if not text:
            return ""
        text = re.sub(r"[（(][^（）()]*[）)]", "", text)
        text = re.sub(r"\s+", "", text)
        return text.lower()

    @classmethod
    def _resolve_reference_appearance_text(cls, reference: dict[str, Any]) -> str:
        return cls._normalize_reference_text(reference.get("appearance_description"))

    @classmethod
    def _resolve_role_description_from_reference(cls, reference: dict[str, Any]) -> str:
        setting = cls._normalize_reference_text(reference.get("setting"))
        appearance = cls._resolve_reference_appearance_text(reference)
        if not appearance:
            return ""
        return setting or appearance

    @staticmethod
    def _normalize_reference_can_speak(
        value: Any, *, reference_name: str = "", reference_id: str = ""
    ) -> bool:
        if isinstance(value, bool):
            return value
        normalized_name = str(reference_name or "").strip().lower()
        if "场景" in normalized_name:
            return False
        return True

    @staticmethod
    def _normalize_library_reference_id(value: Any) -> int | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = int(text)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _role_can_speak(role: dict[str, Any]) -> bool:
        if isinstance(role.get("can_speak"), bool):
            return bool(role.get("can_speak"))
        role_name = str(role.get("name") or "").strip().lower()
        return "场景" not in role_name

    @classmethod
    def _build_default_references_for_mode(cls, script_mode: str) -> list[dict[str, Any]]:
        mode = resolve_script_mode(script_mode)
        if mode == SCRIPT_MODE_SINGLE:
            return [
                {
                    "id": "ref_01",
                    "name": DEFAULT_SINGLE_ROLE_NAME,
                    "setting": "",
                    "appearance_description": "",
                    "can_speak": True,
                    "voice_audio_provider": "edge_tts",
                    "voice_name": EDGE_TTS_VOICE_YUNJIAN,
                }
            ]
        if mode == SCRIPT_MODE_DUO_PODCAST:
            return [
                {
                    "id": "ref_01",
                    "name": DUO_ROLE_1_DEFAULT_NAME,
                    "setting": DUO_ROLE_1_DEFAULT_DESCRIPTION,
                    "appearance_description": "",
                    "can_speak": True,
                    "voice_audio_provider": "edge_tts",
                    "voice_name": EDGE_TTS_VOICE_YUNJIAN,
                },
                {
                    "id": "ref_02",
                    "name": DUO_ROLE_2_DEFAULT_NAME,
                    "setting": DUO_ROLE_2_DEFAULT_DESCRIPTION,
                    "appearance_description": "",
                    "can_speak": True,
                    "voice_audio_provider": "edge_tts",
                    "voice_name": EDGE_TTS_VOICE_XIAOYI,
                },
                {
                    "id": "ref_03",
                    "name": "播客场景",
                    "setting": DUO_SCENE_DEFAULT_DESCRIPTION,
                    "appearance_description": "",
                    "can_speak": False,
                },
            ]
        if mode == SCRIPT_MODE_DIALOGUE_SCRIPT:
            return []
        return []

    async def _reset_reference_stage_for_mode(self, project: Project, script_mode: str) -> None:
        reference_stage = await self._get_or_create_reference_stage_for_sync(project)
        current_output_data = dict(reference_stage.output_data or {})
        _, current_images = self._normalize_reference_records(
            current_output_data.get("references"),
            current_output_data.get("reference_images"),
        )

        deleted_paths: set[str] = set()
        for image in current_images:
            file_path = self._normalize_reference_text(image.get("file_path"))
            if not file_path or file_path in deleted_paths:
                continue
            safe_delete_file(file_path)
            deleted_paths.add(file_path)

        default_references = self._build_default_references_for_mode(script_mode)
        references, reference_images = self._normalize_reference_records(default_references, [])
        reference_stage.output_data = {
            "references": references,
            "reference_images": reference_images,
            "reference_count": len(references),
        }
        reference_stage.status = StageStatus.COMPLETED
        reference_stage.progress = 100
        reference_stage.error_message = None
        flag_modified(reference_stage, "output_data")

    @staticmethod
    def _select_roles_for_reference_sync(
        script_mode: str,
        roles: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        mode = resolve_script_mode(script_mode)
        if mode == SCRIPT_MODE_DUO_PODCAST:
            selected: list[dict[str, Any]] = []
            for role_id in (DUO_ROLE_1_ID, DUO_ROLE_2_ID, DUO_SCENE_ROLE_ID):
                matched = next(
                    (
                        role
                        for role in roles
                        if str(role.get("id") or "").strip()
                        in ({role_id} if role_id != DUO_SCENE_ROLE_ID else {DUO_SCENE_ROLE_ID})
                    ),
                    None,
                )
                if matched:
                    selected.append(matched)
            return selected
        if mode == "single":
            return [roles[0]] if roles else []
        return [role for role in roles]

    @classmethod
    def _build_dialogue_script_roles_from_references(
        cls,
        references: list[dict[str, Any]],
        *,
        max_roles: int,
    ) -> list[dict[str, Any]]:
        roles: list[dict[str, Any]] = []
        for reference in references:
            reference_id = cls._normalize_reference_text(reference.get("id"))
            reference_name = cls._normalize_reference_text(reference.get("name"))
            if not reference_id:
                continue
            can_speak = cls._normalize_reference_can_speak(
                reference.get("can_speak"),
                reference_name=reference_name,
                reference_id=reference_id,
            )
            if not can_speak:
                continue
            roles.append(
                {
                    "id": reference_id,
                    "name": reference_name or "角色",
                    "description": cls._resolve_role_description_from_reference(reference),
                    "seat_side": None,
                    "locked": False,
                }
            )
            if len(roles) >= max_roles:
                break
        return roles

    @classmethod
    def _filter_dialogue_script_lines_for_roles(
        cls,
        raw_lines: Any,
        roles: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not isinstance(raw_lines, list):
            return []

        valid_role_ids = {
            str(role.get("id") or "").strip() for role in roles if str(role.get("id") or "").strip()
        }
        role_name_to_id = {
            str(role.get("name") or "").strip().lower(): str(role.get("id") or "").strip()
            for role in roles
            if str(role.get("name") or "").strip() and str(role.get("id") or "").strip()
        }
        narrator_role_id = next(
            (
                str(role.get("id") or "").strip()
                for role in roles
                if str(role.get("name") or "").strip().lower()
                in {str(item).strip().lower() for item in NARRATOR_ALIASES}
                or str(role.get("name") or "").strip() == DEFAULT_NARRATOR_NAME
            ),
            "",
        )
        narrator_aliases = {str(item).strip().lower() for item in NARRATOR_ALIASES} | {
            DEFAULT_NARRATOR_NAME.lower()
        }

        normalized: list[dict[str, Any]] = []
        for item in raw_lines:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            speaker_id = str(item.get("speaker_id") or "").strip()
            speaker_name = str(item.get("speaker_name") or "").strip()
            speaker_id_lower = speaker_id.lower()
            speaker_name_lower = speaker_name.lower()

            resolved_speaker_id = ""
            if speaker_id and speaker_id in valid_role_ids:
                resolved_speaker_id = speaker_id
            elif speaker_name_lower and speaker_name_lower in role_name_to_id:
                resolved_speaker_id = role_name_to_id[speaker_name_lower]
            elif narrator_role_id and (
                speaker_id_lower == "narrator"
                or speaker_id_lower in narrator_aliases
                or speaker_name_lower in narrator_aliases
            ):
                resolved_speaker_id = narrator_role_id

            if not resolved_speaker_id:
                continue

            resolved_role_name = next(
                (
                    str(role.get("name") or "").strip()
                    for role in roles
                    if str(role.get("id") or "").strip() == resolved_speaker_id
                ),
                speaker_name or resolved_speaker_id,
            )
            normalized.append(
                {
                    **item,
                    "speaker_id": resolved_speaker_id,
                    "speaker_name": resolved_role_name,
                    "text": text,
                }
            )

        return normalized

    @staticmethod
    def _resolve_import_role_limit(script_mode: str, dialogue_max_roles: int) -> int:
        mode = resolve_script_mode(script_mode)
        if mode == SCRIPT_MODE_SINGLE:
            return 1
        if mode == SCRIPT_MODE_DUO_PODCAST:
            return 2
        return normalize_dialogue_max_roles(dialogue_max_roles)

    @classmethod
    def _parse_content_import_payload(
        cls,
        raw_text: str,
        *,
        script_mode: str,
        dialogue_max_roles: int,
    ) -> tuple[str | None, list[dict[str, Any]], list[dict[str, Any]]]:
        mode = resolve_script_mode(script_mode)
        role_limit = cls._resolve_import_role_limit(mode, dialogue_max_roles)
        narrator_aliases = {str(item).strip().lower() for item in NARRATOR_ALIASES} | {
            DEFAULT_NARRATOR_NAME.lower()
        }

        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"解析失败：{exc}") from exc

        if isinstance(payload, list):
            payload = {"dialogue_lines": payload}
        if not isinstance(payload, dict):
            raise ValueError("解析失败：JSON 顶层必须是对象或数组")

        title_value = payload.get("title")
        title: str | None = None
        if title_value is not None:
            title = str(title_value).strip() or None

        raw_roles = payload.get("roles")
        declared_role_names: list[str] = []
        role_description_by_name: dict[str, str] = {}
        if raw_roles is not None:
            if not isinstance(raw_roles, list):
                raise ValueError("解析失败：roles 必须是数组")
            for idx, item in enumerate(raw_roles, start=1):
                if not isinstance(item, dict):
                    raise ValueError(f"解析失败：roles 第{idx}项必须是对象")
                role_name = str(
                    item.get("name")
                    or item.get("speaker_name")
                    or item.get("speaker")
                    or item.get("role")
                    or ""
                ).strip()
                role_description = str(item.get("description") or item.get("setting") or "").strip()
                if not role_name:
                    continue
                normalized_role_name = (
                    DEFAULT_NARRATOR_NAME if role_name.lower() in narrator_aliases else role_name
                )
                if normalized_role_name not in declared_role_names:
                    declared_role_names.append(normalized_role_name)
                if role_description and normalized_role_name not in role_description_by_name:
                    role_description_by_name[normalized_role_name] = role_description

        raw_lines = payload.get("dialogue_lines")
        if raw_lines is None:
            raw_lines = payload.get("dialogue") or payload.get("lines") or payload.get("items")
        if not isinstance(raw_lines, list) or len(raw_lines) == 0:
            raise ValueError("解析失败：dialogue_lines 为空或格式错误")

        speaker_names_in_order: list[str] = []
        raw_line_pairs: list[tuple[str, str]] = []
        for idx, item in enumerate(raw_lines, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"解析失败：dialogue_lines 第{idx}项必须是对象")
            speaker_name = str(
                item.get("speaker_name")
                or item.get("name")
                or item.get("speaker")
                or item.get("role")
                or item.get("speaker_id")
                or ""
            ).strip()
            text = str(item.get("text") or item.get("content") or "").strip()
            if not text:
                continue
            if not speaker_name:
                raise ValueError(f"解析失败：dialogue_lines 第{idx}项缺少 speaker_name")
            speaker_token = (
                DEFAULT_NARRATOR_NAME if speaker_name.lower() in narrator_aliases else speaker_name
            )
            raw_line_pairs.append((speaker_token, text))
            if speaker_token not in speaker_names_in_order:
                speaker_names_in_order.append(speaker_token)

        if not raw_line_pairs:
            raise ValueError("解析失败：dialogue_lines 没有可用台词")

        merged_role_names = speaker_names_in_order + [
            name for name in declared_role_names if name not in speaker_names_in_order
        ]
        effective_role_count = len(merged_role_names)
        if effective_role_count > role_limit:
            dialogue_like_limit = normalize_dialogue_max_roles(dialogue_max_roles)
            if mode == SCRIPT_MODE_CUSTOM:
                limit_hint = (
                    "当前上传的json解析出来的说话角色超过了当前模式的上限"
                    f"（自定义模式目前是{dialogue_like_limit}）"
                )
            elif mode == SCRIPT_MODE_DIALOGUE_SCRIPT:
                limit_hint = (
                    "当前上传的json解析出来的说话角色超过了当前模式的上限"
                    f"（台词剧本目前是{dialogue_like_limit}）"
                )
            else:
                limit_hint = (
                    "当前上传的json解析出来的说话角色超过了当前模式的上限"
                    f"（单人1，双人2，台词剧本目前是{dialogue_like_limit}）"
                )
            raise ValueError(limit_hint)

        speaking_name_set = set(speaker_names_in_order)
        roles: list[dict[str, Any]] = []
        role_id_by_name: dict[str, str] = {}

        if mode == SCRIPT_MODE_SINGLE:
            role_name = merged_role_names[0] if merged_role_names else DEFAULT_SINGLE_ROLE_NAME
            role_id_by_name[role_name] = "ref_01"
            roles = [
                {
                    "id": "ref_01",
                    "name": role_name,
                    "description": role_description_by_name.get(role_name, ""),
                    "seat_side": None,
                    "locked": True,
                    "can_speak": True,
                }
            ]
        elif mode == SCRIPT_MODE_DUO_PODCAST:
            role_1_name = (
                merged_role_names[0] if len(merged_role_names) >= 1 else DUO_ROLE_1_DEFAULT_NAME
            )
            role_2_name = (
                merged_role_names[1] if len(merged_role_names) >= 2 else DUO_ROLE_2_DEFAULT_NAME
            )
            role_id_by_name[role_1_name] = DUO_ROLE_1_ID
            role_id_by_name[role_2_name] = DUO_ROLE_2_ID
            roles = [
                {
                    "id": DUO_ROLE_1_ID,
                    "name": role_1_name,
                    "description": role_description_by_name.get(
                        role_1_name, DUO_ROLE_1_DEFAULT_DESCRIPTION
                    ),
                    "seat_side": "left",
                    "locked": True,
                    "can_speak": role_1_name in speaking_name_set,
                },
                {
                    "id": DUO_ROLE_2_ID,
                    "name": role_2_name,
                    "description": role_description_by_name.get(
                        role_2_name, DUO_ROLE_2_DEFAULT_DESCRIPTION
                    ),
                    "seat_side": "right",
                    "locked": True,
                    "can_speak": role_2_name in speaking_name_set,
                },
                {
                    "id": DUO_SCENE_ROLE_ID,
                    "name": "播客场景",
                    "description": DUO_SCENE_DEFAULT_DESCRIPTION,
                    "seat_side": None,
                    "locked": True,
                    "can_speak": False,
                },
            ]
        else:
            existing_role_ids: set[str] = set()
            for role_name in merged_role_names:
                role_id = generate_next_reference_id(existing_role_ids)
                existing_role_ids.add(role_id)
                display_name = (
                    DEFAULT_NARRATOR_NAME if role_name == DEFAULT_NARRATOR_NAME else role_name
                )
                role_id_by_name[role_name] = role_id
                roles.append(
                    {
                        "id": role_id,
                        "name": display_name,
                        "description": role_description_by_name.get(role_name, ""),
                        "seat_side": None,
                        "locked": False,
                        "can_speak": role_name in speaking_name_set,
                    }
                )

        dialogue_lines: list[dict[str, Any]] = []
        for idx, (speaker_token, text) in enumerate(raw_line_pairs, start=1):
            if speaker_token == DEFAULT_NARRATOR_NAME:
                speaker_id = role_id_by_name.get(DEFAULT_NARRATOR_NAME) or ""
                speaker_name = DEFAULT_NARRATOR_NAME
            else:
                resolved_name = speaker_token
                if mode == SCRIPT_MODE_SINGLE:
                    resolved_name = roles[0]["name"] if roles else DEFAULT_SINGLE_ROLE_NAME
                speaker_id = (
                    role_id_by_name.get(resolved_name) or role_id_by_name.get(speaker_token) or ""
                )
                speaker_name = resolved_name
            dialogue_lines.append(
                {
                    "id": f"line_{idx:03d}",
                    "speaker_id": speaker_id,
                    "speaker_name": speaker_name,
                    "text": text,
                    "order": idx - 1,
                }
            )

        return title, roles, dialogue_lines

    @classmethod
    def _normalize_reference_records(
        cls,
        references_raw: Any,
        reference_images_raw: Any,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        normalized_references: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        raw_references = references_raw if isinstance(references_raw, list) else []
        for index, item in enumerate(raw_references):
            if not isinstance(item, dict):
                continue
            reference_id = cls._normalize_reference_text(item.get("id")) or f"ref_{index + 1:02d}"
            if reference_id in seen_ids:
                continue
            seen_ids.add(reference_id)
            setting = cls._normalize_reference_text(item.get("setting"))
            appearance_description = cls._normalize_reference_text(
                item.get("appearance_description")
            )
            normalized_name = (
                cls._normalize_reference_text(item.get("name"))
                or f"参考{len(normalized_references) + 1}"
            )
            can_speak = cls._normalize_reference_can_speak(
                item.get("can_speak"),
                reference_name=normalized_name,
                reference_id=reference_id,
            )
            library_reference_id = cls._normalize_library_reference_id(
                item.get("library_reference_id")
            )
            voice_payload = normalize_reference_voice_payload(
                can_speak=can_speak,
                voice_audio_provider=item.get("voice_audio_provider"),
                voice_name=item.get("voice_name"),
                voice_speed=item.get("voice_speed"),
                voice_wan2gp_preset=item.get("voice_wan2gp_preset"),
                voice_wan2gp_alt_prompt=item.get("voice_wan2gp_alt_prompt"),
                voice_wan2gp_audio_guide=item.get("voice_wan2gp_audio_guide"),
                voice_wan2gp_temperature=item.get("voice_wan2gp_temperature"),
                voice_wan2gp_top_k=item.get("voice_wan2gp_top_k"),
                voice_wan2gp_seed=item.get("voice_wan2gp_seed"),
            )
            normalized_references.append(
                {
                    "id": reference_id,
                    "name": normalized_name,
                    "setting": setting,
                    "appearance_description": appearance_description,
                    "can_speak": can_speak,
                    "library_reference_id": library_reference_id,
                    **voice_payload,
                }
            )

        raw_images = reference_images_raw if isinstance(reference_images_raw, list) else []
        image_by_id: dict[str, dict[str, Any]] = {}
        for item in raw_images:
            if not isinstance(item, dict):
                continue
            reference_id = cls._normalize_reference_text(item.get("id"))
            if not reference_id:
                continue
            image_by_id[reference_id] = dict(item)

        normalized_images: list[dict[str, Any]] = []
        for reference in normalized_references:
            reference_id = str(reference["id"])
            existing = image_by_id.get(reference_id, {})
            setting = cls._normalize_reference_text(
                existing.get("setting")
            ) or cls._normalize_reference_text(reference.get("setting"))
            appearance_description = cls._normalize_reference_text(
                existing.get("appearance_description")
            ) or reference.get("appearance_description", "")
            can_speak = cls._normalize_reference_can_speak(
                existing.get("can_speak", reference.get("can_speak")),
                reference_name=str(reference.get("name") or ""),
                reference_id=reference_id,
            )
            library_reference_id = cls._normalize_library_reference_id(
                existing.get("library_reference_id", reference.get("library_reference_id"))
            )
            voice_payload = normalize_reference_voice_payload(
                can_speak=can_speak,
                voice_audio_provider=existing.get(
                    "voice_audio_provider",
                    reference.get("voice_audio_provider"),
                ),
                voice_name=existing.get(
                    "voice_name",
                    reference.get("voice_name"),
                ),
                voice_speed=existing.get(
                    "voice_speed",
                    reference.get("voice_speed"),
                ),
                voice_wan2gp_preset=existing.get(
                    "voice_wan2gp_preset",
                    reference.get("voice_wan2gp_preset"),
                ),
                voice_wan2gp_alt_prompt=existing.get(
                    "voice_wan2gp_alt_prompt",
                    reference.get("voice_wan2gp_alt_prompt"),
                ),
                voice_wan2gp_audio_guide=existing.get(
                    "voice_wan2gp_audio_guide",
                    reference.get("voice_wan2gp_audio_guide"),
                ),
                voice_wan2gp_temperature=existing.get(
                    "voice_wan2gp_temperature",
                    reference.get("voice_wan2gp_temperature"),
                ),
                voice_wan2gp_top_k=existing.get(
                    "voice_wan2gp_top_k",
                    reference.get("voice_wan2gp_top_k"),
                ),
                voice_wan2gp_seed=existing.get(
                    "voice_wan2gp_seed",
                    reference.get("voice_wan2gp_seed"),
                ),
            )
            normalized_images.append(
                {
                    "id": reference_id,
                    "name": reference.get("name", ""),
                    "setting": setting,
                    "appearance_description": appearance_description,
                    "can_speak": can_speak,
                    "library_reference_id": library_reference_id,
                    **voice_payload,
                    "file_path": existing.get("file_path"),
                    "generated": bool(existing.get("generated", False)),
                    "uploaded": bool(existing.get("uploaded", False)),
                    "updated_at": existing.get("updated_at"),
                    "error": existing.get("error"),
                }
            )

        return normalized_references, normalized_images

    async def _get_or_create_reference_stage_for_sync(self, project: Project) -> StageExecution:
        result = await self.db.execute(
            select(StageExecution).where(
                StageExecution.project_id == project.id,
                StageExecution.stage_type == StageType.REFERENCE,
            )
        )
        stage = result.scalar_one_or_none()
        if stage:
            return stage

        pipeline = PipelineEngine(self.db, project)
        stage = StageExecution(
            project_id=project.id,
            stage_type=StageType.REFERENCE,
            stage_number=pipeline.get_stage_number(StageType.REFERENCE),
            status=StageStatus.COMPLETED,
            progress=100,
            output_data={"references": [], "reference_images": [], "reference_count": 0},
        )
        self.db.add(stage)
        await self.db.flush()
        return stage

    @classmethod
    def _stabilize_role_reference_mapping(
        cls,
        roles: list[dict[str, Any]],
        references: list[dict[str, Any]],
    ) -> None:
        """Reconcile freshly generated role lists against existing references.

        LLM-generated roles may be reindexed purely by output order. When a new role is inserted
        at the front, those synthetic ids can accidentally bind to the wrong existing reference
        and inherit its image / appearance payload. We first preserve exact name matches, then only
        keep id-based matches when they do not conflict with another retained reference.
        """
        if not roles or not references:
            return

        references_by_id: dict[str, dict[str, Any]] = {}
        references_by_name: dict[str, dict[str, Any]] = {}
        references_by_identity: dict[str, dict[str, Any]] = {}
        duplicate_name_keys: set[str] = set()
        duplicate_identity_keys: set[str] = set()
        role_name_counts: dict[str, int] = {}
        role_identity_counts: dict[str, int] = {}

        for reference in references:
            reference_id = cls._normalize_reference_text(reference.get("id"))
            reference_name_key = cls._normalize_reference_text(reference.get("name")).lower()
            reference_identity_key = cls._normalize_reference_identity_key(reference.get("name"))
            if reference_id:
                references_by_id[reference_id] = reference
            if reference_name_key:
                if reference_name_key in references_by_name:
                    duplicate_name_keys.add(reference_name_key)
                else:
                    references_by_name[reference_name_key] = reference
            if reference_identity_key:
                if reference_identity_key in references_by_identity:
                    duplicate_identity_keys.add(reference_identity_key)
                else:
                    references_by_identity[reference_identity_key] = reference

        for duplicate_name_key in duplicate_name_keys:
            references_by_name.pop(duplicate_name_key, None)
        for duplicate_identity_key in duplicate_identity_keys:
            references_by_identity.pop(duplicate_identity_key, None)

        for role in roles:
            role_name_key = cls._normalize_reference_text(role.get("name")).lower()
            role_identity_key = cls._normalize_reference_identity_key(role.get("name"))
            if role_name_key:
                role_name_counts[role_name_key] = role_name_counts.get(role_name_key, 0) + 1
            if role_identity_key:
                role_identity_counts[role_identity_key] = (
                    role_identity_counts.get(role_identity_key, 0) + 1
                )

        claimed_reference_ids: set[str] = set()
        name_matched_indexes: set[int] = set()

        for idx, role in enumerate(roles):
            role_name_key = cls._normalize_reference_text(role.get("name")).lower()
            if not role_name_key:
                continue
            matched_reference = references_by_name.get(role_name_key)
            if not matched_reference:
                continue
            matched_reference_id = cls._normalize_reference_text(matched_reference.get("id"))
            if not matched_reference_id or matched_reference_id in claimed_reference_ids:
                continue
            role["id"] = matched_reference_id
            claimed_reference_ids.add(matched_reference_id)
            name_matched_indexes.add(idx)

        for idx, role in enumerate(roles):
            if idx in name_matched_indexes:
                continue

            role_identity_key = cls._normalize_reference_identity_key(role.get("name"))
            if not role_identity_key:
                continue
            if role_identity_counts.get(role_identity_key, 0) != 1:
                continue
            matched_reference = references_by_identity.get(role_identity_key)
            if not matched_reference:
                continue
            matched_reference_id = cls._normalize_reference_text(matched_reference.get("id"))
            if not matched_reference_id or matched_reference_id in claimed_reference_ids:
                continue
            role["id"] = matched_reference_id
            claimed_reference_ids.add(matched_reference_id)
            name_matched_indexes.add(idx)

        for idx, role in enumerate(roles):
            if idx in name_matched_indexes:
                continue

            role_id = cls._normalize_reference_text(role.get("id"))
            if not role_id:
                continue
            if role_id in claimed_reference_ids:
                role["id"] = ""
                continue

            matched_reference = references_by_id.get(role_id)
            if not matched_reference:
                continue

            role_name_key = cls._normalize_reference_text(role.get("name")).lower()
            role_identity_key = cls._normalize_reference_identity_key(role.get("name"))
            matched_reference_name_key = cls._normalize_reference_text(
                matched_reference.get("name")
            ).lower()
            matched_reference_identity_key = cls._normalize_reference_identity_key(
                matched_reference.get("name")
            )
            if matched_reference_identity_key in duplicate_identity_keys:
                role["id"] = ""
                continue
            if (
                role_name_key
                and matched_reference_name_key
                and role_name_key != matched_reference_name_key
                and role_name_counts.get(matched_reference_name_key, 0) > 0
            ):
                role["id"] = ""
                continue
            if (
                role_identity_key
                and matched_reference_identity_key
                and role_identity_key != matched_reference_identity_key
                and role_identity_counts.get(matched_reference_identity_key, 0) > 0
            ):
                role["id"] = ""
                continue

            claimed_reference_ids.add(role_id)

    @classmethod
    def _reorder_reference_payloads_by_role_order(
        cls,
        references: list[dict[str, Any]],
        reference_images: list[dict[str, Any]],
        roles: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        ordered_ids: list[str] = []
        seen_ids: set[str] = set()

        for role in roles:
            role_id = cls._normalize_reference_text(role.get("id"))
            if not role_id or role_id in seen_ids:
                continue
            ordered_ids.append(role_id)
            seen_ids.add(role_id)

        if not ordered_ids:
            return references, reference_images

        references_by_id = {
            cls._normalize_reference_text(reference.get("id")): reference
            for reference in references
        }
        reference_images_by_id = {
            cls._normalize_reference_text(image.get("id")): image for image in reference_images
        }

        ordered_references = [
            references_by_id[reference_id]
            for reference_id in ordered_ids
            if reference_id in references_by_id
        ]
        ordered_references.extend(
            reference
            for reference in references
            if cls._normalize_reference_text(reference.get("id")) not in seen_ids
        )

        ordered_reference_images = [
            reference_images_by_id[reference_id]
            for reference_id in ordered_ids
            if reference_id in reference_images_by_id
        ]
        ordered_reference_images.extend(
            image
            for image in reference_images
            if cls._normalize_reference_text(image.get("id")) not in seen_ids
        )

        return ordered_references, ordered_reference_images

    @classmethod
    def _realign_dialogue_lines_with_roles(
        cls,
        dialogue_lines: list[dict[str, Any]] | None,
        roles: list[dict[str, Any]],
    ) -> None:
        if not isinstance(dialogue_lines, list) or not dialogue_lines or not roles:
            return

        role_by_id: dict[str, dict[str, Any]] = {}
        role_by_name: dict[str, dict[str, Any]] = {}
        duplicate_name_keys: set[str] = set()
        narrator_role: dict[str, Any] | None = None

        for role in roles:
            role_id = cls._normalize_reference_text(role.get("id"))
            role_name = cls._normalize_reference_text(role.get("name"))
            role_name_key = role_name.lower()
            if role_id:
                role_by_id[role_id] = role
            if role_name_key:
                if role_name_key in role_by_name:
                    duplicate_name_keys.add(role_name_key)
                else:
                    role_by_name[role_name_key] = role
            if role_name in NARRATOR_ALIASES or role_name == DEFAULT_NARRATOR_NAME:
                narrator_role = role

        for duplicate_name_key in duplicate_name_keys:
            role_by_name.pop(duplicate_name_key, None)

        for line in dialogue_lines:
            if not isinstance(line, dict):
                continue

            speaker_name = cls._normalize_reference_text(line.get("speaker_name"))
            speaker_id = cls._normalize_reference_text(line.get("speaker_id"))
            matched_role: dict[str, Any] | None = None

            if speaker_name:
                matched_role = role_by_name.get(speaker_name.lower())
                if (
                    matched_role is None
                    and narrator_role is not None
                    and speaker_name.lower()
                    in {str(alias).strip().lower() for alias in NARRATOR_ALIASES}
                ):
                    matched_role = narrator_role

            if matched_role is None and speaker_id:
                matched_role = role_by_id.get(speaker_id)

            if matched_role is None:
                continue

            matched_role_id = cls._normalize_reference_text(matched_role.get("id"))
            matched_role_name = cls._normalize_reference_text(matched_role.get("name"))
            if matched_role_id:
                line["speaker_id"] = matched_role_id
            if matched_role_name:
                line["speaker_name"] = matched_role_name

    async def _sync_content_roles_with_references(
        self,
        project: Project,
        script_mode: str,
        roles: list[dict[str, Any]],
        *,
        create_missing: bool,
        prune_unmatched: bool = False,
        dialogue_lines: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        reference_stage = await self._get_or_create_reference_stage_for_sync(project)
        output_data = dict(reference_stage.output_data or {})
        references, reference_images = self._normalize_reference_records(
            output_data.get("references"),
            output_data.get("reference_images"),
        )

        created_reference_names: list[str] = []
        matched_reference_ids: set[str] = set()
        role_targets = self._select_roles_for_reference_sync(script_mode, roles)
        self._stabilize_role_reference_mapping(role_targets, references)
        references_by_id = {str(item.get("id")): item for item in references}
        references_by_name = {
            self._normalize_reference_text(item.get("name")).lower(): item
            for item in references
            if self._normalize_reference_text(item.get("name"))
        }
        default_edge_voice = (
            str(getattr(settings, "edge_tts_voice", "") or "").strip() or EDGE_TTS_VOICE_YUNJIAN
        )

        for role in role_targets:
            role_name = self._normalize_reference_text(role.get("name"))
            role_setting = self._normalize_reference_text(role.get("description"))
            role_id = self._normalize_reference_text(role.get("id"))
            role_can_speak = self._role_can_speak(role)
            matched_reference = references_by_id.get(role_id) if role_id else None

            if (
                create_missing
                and matched_reference
                and role_name
                and role_name != str(matched_reference.get("name") or "").strip()
            ):
                # 已绑定同一参考时，允许通过角色名重命名该参考，保证名称统一。
                matched_reference["name"] = role_name
                references_by_name = {
                    self._normalize_reference_text(item.get("name")).lower(): item
                    for item in references
                    if self._normalize_reference_text(item.get("name"))
                }

            if not matched_reference and role_name:
                matched_reference = references_by_name.get(role_name.lower())

            if not matched_reference and create_missing and role_name:
                new_reference_id = (
                    role_id
                    if role_id and is_reference_id(role_id) and role_id not in references_by_id
                    else self._generate_reference_id(references)
                )
                matched_reference = {
                    "id": new_reference_id,
                    "name": role_name,
                    "setting": role_setting,
                    "appearance_description": "",
                    "can_speak": role_can_speak,
                    "voice_audio_provider": "edge_tts" if role_can_speak else None,
                    "voice_name": default_edge_voice if role_can_speak else None,
                }
                references.append(matched_reference)
                created_reference_names.append(role_name)
                references_by_id[new_reference_id] = matched_reference
                references_by_name[role_name.lower()] = matched_reference

            if matched_reference:
                if (
                    create_missing
                    and role_setting
                    and not self._normalize_reference_text(matched_reference.get("setting"))
                ):
                    matched_reference["setting"] = role_setting
                matched_reference["can_speak"] = role_can_speak
                if role_can_speak and not self._normalize_reference_text(
                    matched_reference.get("voice_name")
                ):
                    matched_reference["voice_audio_provider"] = "edge_tts"
                    matched_reference["voice_name"] = default_edge_voice
                matched_reference_id = self._normalize_reference_text(matched_reference.get("id"))
                role["id"] = matched_reference_id or matched_reference.get("id")
                role["name"] = matched_reference.get("name")
                role["description"] = self._resolve_role_description_from_reference(
                    matched_reference
                )
                if matched_reference_id:
                    matched_reference_ids.add(matched_reference_id)
            elif not create_missing and role_id:
                role["id"] = ""

        if prune_unmatched:
            # 覆盖式同步：仅保留当前角色实际命中的参考，避免旧角色残留。
            kept_ids = matched_reference_ids
            removed_images = [
                image
                for image in reference_images
                if self._normalize_reference_text(image.get("id")) not in kept_ids
            ]
            for image in removed_images:
                file_path = self._normalize_reference_text(image.get("file_path"))
                if file_path:
                    safe_delete_file(file_path)
            references = [
                reference
                for reference in references
                if self._normalize_reference_text(reference.get("id")) in kept_ids
            ]
            reference_images = [
                image
                for image in reference_images
                if self._normalize_reference_text(image.get("id")) in kept_ids
            ]

        references, reference_images = self._reorder_reference_payloads_by_role_order(
            references,
            reference_images,
            role_targets,
        )

        references, reference_images = self._normalize_reference_records(
            references, reference_images
        )
        references_by_id = {str(item.get("id")): item for item in references}
        for role in roles:
            role_id = self._normalize_reference_text(role.get("id"))
            matched_reference = references_by_id.get(role_id) if role_id else None
            if matched_reference:
                role["name"] = matched_reference.get("name")
                role["description"] = self._resolve_role_description_from_reference(
                    matched_reference
                )
            elif role_id:
                role["id"] = ""

        self._realign_dialogue_lines_with_roles(dialogue_lines, roles)

        output_data["references"] = references
        output_data["reference_images"] = reference_images
        output_data["reference_count"] = len(references)
        reference_stage.output_data = output_data
        flag_modified(reference_stage, "output_data")
        return roles, created_reference_names

    async def _sync_content_stage_after_reference_change(
        self,
        project: Project,
        *,
        create_missing: bool,
    ) -> None:
        result = await self.db.execute(
            select(StageExecution).where(
                StageExecution.project_id == project.id,
                StageExecution.stage_type == StageType.CONTENT,
            )
        )
        content_stage = result.scalar_one_or_none()
        if not content_stage:
            return

        output_data = dict(content_stage.output_data or {})
        max_roles = normalize_dialogue_max_roles(settings.dialogue_script_max_roles)
        resolved_mode = resolve_script_mode(
            output_data.get("script_mode")
            or resolve_script_mode_from_video_type(project.video_type)
        )
        reference_stage_result = await self.db.execute(
            select(StageExecution).where(
                StageExecution.project_id == project.id,
                StageExecution.stage_type == StageType.REFERENCE,
            )
        )
        reference_stage = reference_stage_result.scalar_one_or_none()
        reference_output_data = dict(reference_stage.output_data or {}) if reference_stage else {}
        references, _ = self._normalize_reference_records(
            reference_output_data.get("references"),
            reference_output_data.get("reference_images"),
        )

        if resolved_mode == SCRIPT_MODE_DIALOGUE_SCRIPT:
            normalized_roles = self._build_dialogue_script_roles_from_references(
                references,
                max_roles=max_roles,
            )
            existing_lines = self._filter_dialogue_script_lines_for_roles(
                output_data.get("dialogue_lines"),
                normalized_roles,
            )
            self._realign_dialogue_lines_with_roles(existing_lines, normalized_roles)
            fallback_text = ""
        else:
            normalized_roles = normalize_roles(
                output_data.get("roles"),
                script_mode=resolved_mode,
                max_roles=max_roles,
            )
            existing_lines = output_data.get("dialogue_lines")
            if isinstance(existing_lines, list):
                self._realign_dialogue_lines_with_roles(existing_lines, normalized_roles)
            fallback_text = str(output_data.get("content") or "")
        allow_role_autofill_first_pass = (
            create_missing or resolved_mode != SCRIPT_MODE_DIALOGUE_SCRIPT
        )
        try:
            normalized_roles, normalized_lines = normalize_dialogue_lines(
                existing_lines,
                roles=normalized_roles,
                script_mode=resolved_mode,
                max_roles=max_roles,
                allow_role_autofill=allow_role_autofill_first_pass,
                fallback_text=fallback_text,
            )
        except ValueError:
            return
        normalized_roles, _ = await self._sync_content_roles_with_references(
            project,
            resolved_mode,
            normalized_roles,
            create_missing=create_missing,
            dialogue_lines=normalized_lines if isinstance(normalized_lines, list) else None,
        )
        try:
            normalized_roles, normalized_lines = normalize_dialogue_lines(
                normalized_lines,
                roles=normalized_roles,
                script_mode=resolved_mode,
                max_roles=max_roles,
                allow_role_autofill=(resolved_mode != "dialogue_script"),
                fallback_text=fallback_text,
            )
        except ValueError:
            return
        output_data["roles"] = normalized_roles
        output_data["dialogue_lines"] = normalized_lines
        output_data["content"] = flatten_dialogue_text(normalized_lines)

        output_data["char_count"] = len(
            re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", str(output_data.get("content") or ""))
        )
        content_stage.output_data = output_data
        flag_modified(content_stage, "output_data")

    async def update_content_data(
        self,
        project_id: int,
        title: str | None,
        content: str | None,
        script_mode: str | None = None,
        roles: list[dict[str, Any]] | None = None,
        dialogue_lines: list[dict[str, Any]] | None = None,
        *,
        create_missing_references: bool = False,
    ):
        project = await self.get_project_or_404(project_id)

        result = await self.db.execute(
            select(StageExecution).where(
                StageExecution.project_id == project_id,
                StageExecution.stage_type == StageType.CONTENT,
            )
        )
        stage = result.scalar_one_or_none()
        if not stage:
            stage = StageExecution(
                project_id=project_id,
                stage_type=StageType.CONTENT,
                stage_number=2,
                status=StageStatus.COMPLETED,
                output_data={},
            )
            self.db.add(stage)

        output_data = dict(stage.output_data or {})
        shots_locked = bool(output_data.get("shots_locked"))
        if not shots_locked:
            shot_stage_result = await self.db.execute(
                select(StageExecution.output_data).where(
                    StageExecution.project_id == project_id,
                    StageExecution.stage_type == StageType.STORYBOARD,
                )
            )
            for shot_stage_output in shot_stage_result.scalars():
                if not isinstance(shot_stage_output, dict):
                    continue
                shot_items = shot_stage_output.get("shots")
                if isinstance(shot_items, list) and len(shot_items) > 0:
                    shots_locked = True
                    break

        if shots_locked:
            raise ServiceError(
                409,
                "文案已与分镜绑定，请在分镜区编辑，或先清空分镜内容后再编辑文案",
            )
        max_roles = normalize_dialogue_max_roles(settings.dialogue_script_max_roles)
        previous_mode = resolve_script_mode(
            output_data.get("script_mode")
            or resolve_script_mode_from_video_type(project.video_type)
        )
        resolved_mode = resolve_script_mode(
            script_mode
            or output_data.get("script_mode")
            or resolve_script_mode_from_video_type(project.video_type)
        )
        mode_switched = script_mode is not None and resolved_mode != previous_mode

        if mode_switched:
            await self._reset_reference_stage_for_mode(project, resolved_mode)

        if script_mode is not None:
            output_data["script_mode"] = resolved_mode
        if title is not None:
            output_data["title"] = title

        existing_roles = roles if roles is not None else output_data.get("roles")
        normalized_roles = normalize_roles(
            existing_roles,
            script_mode=resolved_mode,
            max_roles=max_roles,
        )
        existing_lines = (
            dialogue_lines if dialogue_lines is not None else output_data.get("dialogue_lines")
        )
        if dialogue_lines is None and content is not None:
            fallback_speaker_id = str(
                (normalized_roles[0] if normalized_roles else {}).get("id") or "ref_01"
            )
            existing_lines = [
                {
                    "speaker_id": fallback_speaker_id,
                    "text": str(content),
                }
            ]
        explicit_dialogue_clear = (
            dialogue_lines is not None
            and isinstance(dialogue_lines, list)
            and len(dialogue_lines) == 0
            and content is None
        )
        fallback_text = (
            ""
            if explicit_dialogue_clear
            else (str(content) if content is not None else str(output_data.get("content") or ""))
        )
        allow_role_autofill_first_pass = (
            create_missing_references or resolved_mode != SCRIPT_MODE_DIALOGUE_SCRIPT
        )
        try:
            normalized_roles, normalized_lines = normalize_dialogue_lines(
                existing_lines,
                roles=normalized_roles,
                script_mode=resolved_mode,
                max_roles=max_roles,
                allow_role_autofill=allow_role_autofill_first_pass,
                fallback_text=fallback_text,
            )
        except ValueError as exc:
            raise ServiceError(400, str(exc)) from exc

        normalized_roles, created_reference_names = await self._sync_content_roles_with_references(
            project,
            resolved_mode,
            normalized_roles,
            create_missing=create_missing_references,
            dialogue_lines=normalized_lines if isinstance(normalized_lines, list) else None,
        )
        try:
            normalized_roles, normalized_lines = normalize_dialogue_lines(
                normalized_lines,
                roles=normalized_roles,
                script_mode=resolved_mode,
                max_roles=max_roles,
                allow_role_autofill=(resolved_mode != "dialogue_script"),
                fallback_text=fallback_text,
            )
        except ValueError as exc:
            raise ServiceError(400, str(exc)) from exc

        output_data["roles"] = normalized_roles
        output_data["dialogue_lines"] = normalized_lines
        output_data["content"] = flatten_dialogue_text(normalized_lines)
        output_data["shots_locked"] = False
        if script_mode is not None:
            output_data["script_mode"] = resolved_mode

        normalized_content_for_count = str(output_data.get("content") or "")
        char_count = len(re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", normalized_content_for_count))
        output_data["char_count"] = char_count

        # Manual content save should update stage completion state as well,
        # otherwise downstream stages (e.g. reference) may reject non-completed content stage.
        normalized_content = output_data.get("content")
        has_valid_content = isinstance(normalized_content, str) and normalized_content.strip() != ""
        stage.status = StageStatus.COMPLETED if has_valid_content else StageStatus.PENDING
        stage.error_message = None
        stage.progress = 100 if has_valid_content else 0
        stage.last_item_complete = -1
        stage.total_items = None
        stage.completed_items = None
        stage.skipped_items = None

        stage.output_data = output_data
        flag_modified(stage, "output_data")

        if script_mode is not None:
            project.video_mode = VIDEO_MODE_ORAL_SCRIPT_DRIVEN
            project.video_type = resolve_video_type_from_script_mode(resolved_mode)

        await self.db.commit()
        await self.db.refresh(stage)

        response: dict[str, Any] = {"success": True, "data": stage.output_data}
        if created_reference_names:
            response["auto_created_references"] = created_reference_names
        return response

    async def import_content_dialogue_data(
        self,
        project_id: int,
        file: UploadFile,
        script_mode: str | None = None,
    ):
        project = await self.get_project_or_404(project_id)
        raw_bytes = await file.read()
        if not raw_bytes:
            raise ServiceError(400, "上传内容为空")
        try:
            raw_text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raw_text = raw_bytes.decode("utf-8-sig", errors="ignore")

        max_roles = normalize_dialogue_max_roles(settings.dialogue_script_max_roles)

        result = await self.db.execute(
            select(StageExecution).where(
                StageExecution.project_id == project_id,
                StageExecution.stage_type == StageType.CONTENT,
            )
        )
        content_stage = result.scalar_one_or_none()
        existing_output = dict(content_stage.output_data or {}) if content_stage else {}
        resolved_mode = resolve_script_mode(
            script_mode
            or existing_output.get("script_mode")
            or resolve_script_mode_from_video_type(project.video_type),
            default="single",
        )
        existing_roles = existing_output.get("roles")
        existing_lines = existing_output.get("dialogue_lines")
        logger.info(
            "[Content][Import] start project_id=%s filename=%s bytes=%d requested_mode=%s resolved_mode=%s "
            "existing_roles=%d existing_lines=%d has_title=%s",
            project_id,
            getattr(file, "filename", None),
            len(raw_bytes),
            script_mode,
            resolved_mode,
            len(existing_roles) if isinstance(existing_roles, list) else 0,
            len(existing_lines) if isinstance(existing_lines, list) else 0,
            bool(str(existing_output.get("title") or "").strip()),
        )

        # 导入是覆盖语义：先清空当前模式下已有参考/角色绑定，再根据上传内容重建。
        await self._reset_reference_stage_for_mode(project, resolved_mode)
        logger.info(
            "[Content][Import] reference reset completed project_id=%s mode=%s",
            project_id,
            resolved_mode,
        )

        try:
            parsed_title, parsed_roles, parsed_lines = self._parse_content_import_payload(
                raw_text,
                script_mode=resolved_mode,
                dialogue_max_roles=max_roles,
            )
        except ValueError as exc:
            logger.warning(
                "[Content][Import] parse failed project_id=%s mode=%s error=%s",
                project_id,
                resolved_mode,
                str(exc),
            )
            raise ServiceError(400, str(exc)) from exc
        logger.info(
            "[Content][Import] parsed project_id=%s mode=%s title_present=%s parsed_roles=%d parsed_lines=%d",
            project_id,
            resolved_mode,
            bool(parsed_title),
            len(parsed_roles),
            len(parsed_lines),
        )

        result_payload = await self.update_content_data(
            project_id=project_id,
            title=parsed_title,
            content=None,
            script_mode=resolved_mode,
            roles=parsed_roles,
            dialogue_lines=parsed_lines,
            create_missing_references=True,
        )
        created_refs = result_payload.get("auto_created_references")
        logger.info(
            "[Content][Import] content updated project_id=%s mode=%s auto_created_references=%d",
            project_id,
            resolved_mode,
            len(created_refs) if isinstance(created_refs, list) else 0,
        )

        if resolved_mode == SCRIPT_MODE_DIALOGUE_SCRIPT:
            await self._sync_content_stage_after_reference_change(project, create_missing=False)
            await self.db.commit()
            refreshed = await self.db.execute(
                select(StageExecution).where(
                    StageExecution.project_id == project_id,
                    StageExecution.stage_type == StageType.CONTENT,
                )
            )
            refreshed_stage = refreshed.scalar_one_or_none()
            if refreshed_stage is not None:
                result_payload["data"] = dict(refreshed_stage.output_data or {})
            logger.info(
                "[Content][Import] dialogue_script post-sync completed project_id=%s",
                project_id,
            )

        output_data = dict(result_payload.get("data") or {})
        final_lines = output_data.get("dialogue_lines")
        final_roles = output_data.get("roles")
        final_content = str(output_data.get("content") or "")
        char_count = len(re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", final_content))
        logger.info(
            "[Content][Import] completed project_id=%s mode=%s final_roles=%d final_lines=%d char_count=%d",
            project_id,
            resolved_mode,
            len(final_roles) if isinstance(final_roles, list) else 0,
            len(final_lines) if isinstance(final_lines, list) else 0,
            char_count,
        )
        return result_payload | {
            "imported": True,
            "line_count": len(final_lines) if isinstance(final_lines, list) else 0,
            "role_count": len(final_roles) if isinstance(final_roles, list) else 0,
            "char_count": char_count,
        }
