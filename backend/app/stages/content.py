import json
import logging
import re
from json import JSONDecodeError
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.core.dialogue import (
    DEFAULT_SINGLE_ROLE_NAME,
    DUO_ROLE_1_DEFAULT_DESCRIPTION,
    DUO_ROLE_1_DEFAULT_NAME,
    DUO_ROLE_1_ID,
    DUO_ROLE_2_DEFAULT_DESCRIPTION,
    DUO_ROLE_2_DEFAULT_NAME,
    DUO_ROLE_2_ID,
    DUO_SCENE_DEFAULT_DESCRIPTION,
    DUO_SCENE_ROLE_ID,
    DUO_SCENE_ROLE_NAME,
    SCRIPT_MODE_CUSTOM,
    SCRIPT_MODE_DUO_PODCAST,
    SCRIPT_MODE_SINGLE,
    flatten_dialogue_text,
    normalize_dialogue_lines,
    normalize_dialogue_max_roles,
    normalize_roles,
    resolve_script_mode,
)
from app.core.errors import StageValidationError
from app.core.project_mode import resolve_script_mode_from_video_type
from app.core.stream_json import extract_json_array_items, extract_json_string_value
from app.llm.runtime import resolve_llm_runtime
from app.models.project import Project
from app.models.stage import StageExecution, StageStatus, StageType
from app.services.source_service import SourceService
from app.stages.common.log_utils import log_stage_separator

from . import register_stage
from ._generation_log import truncate_generation_text
from .base import StageHandler, StageResult
from .prompts import (
    CONTENT_CUSTOM_DIALOGUE_SCRIPT_USER,
    CONTENT_CUSTOM_DUO_USER,
    CONTENT_CUSTOM_SINGLE_USER,
    CONTENT_CUSTOM_USER,
    CONTENT_DIALOGUE_DUO_USER,
    CONTENT_DIALOGUE_SCRIPT_USER,
    CONTENT_SYSTEM,
    CONTENT_USER,
    DUO_PODCAST_STYLE_DESCRIPTIONS,
    STYLE_DESCRIPTIONS,
    TITLE_USER,
    get_unrestricted_language_log_label,
)

logger = logging.getLogger(__name__)

PUNCTUATION_PATTERN = re.compile(r'[，。！？；：,.!?;:、\'"()（）【】\[\]《》<>～~…—\-\s]')
SENTENCE_PUNCTUATION_PATTERN = re.compile(r"[。！？!?]")
COMMON_PUNCTUATION_PATTERN = re.compile(r"[，。！？；：、,.!?;:]")
CJK_INLINE_SPACE_PATTERN = re.compile(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])")
CHARS_PER_SECOND = 5
CONTENT_INPUT_REQUIRED_ERROR = "输入素材为空或不可用，请先选择来源或填写输入文本"
CONTENT_CUSTOM_MESSAGE_REQUIRED_ERROR = "请输入你希望生成或调整的台词需求"
CHAT_HISTORY_MAX_MESSAGES = 12
CHAT_SUMMARY_MAX_CHARS = 1800


def count_chars(text: str) -> int:
    return len(PUNCTUATION_PATTERN.sub("", text))


@register_stage(StageType.CONTENT)
class ContentHandler(StageHandler):
    async def execute(
        self,
        db: AsyncSession,
        project: Project,
        stage: StageExecution,
        input_data: dict[str, Any] | None = None,
    ) -> StageResult:
        try:
            input_data = input_data or {}
            script_mode = resolve_script_mode(
                input_data.get("script_mode")
                or resolve_script_mode_from_video_type(project.video_type)
            )
            reset_chat = bool(input_data.get("reset_chat"))
            user_message = str(input_data.get("user_message") or "").strip()
            has_user_message = bool(user_message)
            previous_output = stage.output_data if isinstance(stage.output_data, dict) else {}

            if reset_chat:
                should_reset_reference_stage = script_mode not in {
                    SCRIPT_MODE_SINGLE,
                    SCRIPT_MODE_DUO_PODCAST,
                }
                if should_reset_reference_stage:
                    await self._clear_reference_stage_for_content_reset(db=db, project=project)
                return StageResult(
                    success=True,
                    data=self._build_reset_payload(script_mode),
                )

            input_text = await self._get_input_text(db, project)
            if script_mode != SCRIPT_MODE_CUSTOM and not input_text and not has_user_message:
                return StageResult(
                    success=False,
                    error=CONTENT_INPUT_REQUIRED_ERROR,
                )

            llm_runtime = resolve_llm_runtime(input_data)
            llm_provider = llm_runtime.provider

            target_duration = project.target_duration or 60
            total_chars = target_duration * CHARS_PER_SECOND
            max_roles = normalize_dialogue_max_roles(settings.dialogue_script_max_roles)
            seed_roles = (
                input_data.get("roles")
                if isinstance(input_data.get("roles"), list)
                else previous_output.get("roles")
            )
            normalized_seed_roles = normalize_roles(
                seed_roles,
                script_mode=script_mode,
                max_roles=max_roles,
            )

            chat_history = self._normalize_chat_history(previous_output.get("chat_history"))
            chat_summary = str(previous_output.get("chat_summary") or "").strip()
            current_draft = self._format_current_draft(previous_output)
            existing_roles = self._format_existing_roles(normalized_seed_roles)
            user_history = self._format_user_history(chat_history)

            if script_mode == SCRIPT_MODE_CUSTOM:
                if not user_message:
                    return StageResult(
                        success=False,
                        error=CONTENT_CUSTOM_MESSAGE_REQUIRED_ERROR,
                    )
                prompt = CONTENT_CUSTOM_USER.format(
                    user_message=user_message,
                    input_text=(input_text or "无"),
                    current_draft=current_draft,
                    user_history=user_history,
                    chat_summary=(chat_summary or "无"),
                    total_chars=total_chars,
                )
            elif has_user_message:
                if script_mode == "single":
                    single_role = normalized_seed_roles[0] if normalized_seed_roles else {}
                    prompt = CONTENT_CUSTOM_SINGLE_USER.format(
                        user_message=user_message,
                        input_text=(input_text or "无"),
                        current_draft=current_draft,
                        user_history=user_history,
                        chat_summary=(chat_summary or "无"),
                        total_chars=total_chars,
                        role_name=str(single_role.get("name") or DEFAULT_SINGLE_ROLE_NAME),
                        role_description=str(single_role.get("description") or "").strip()
                        or "无设定",
                    )
                elif script_mode == "duo_podcast":
                    duo_context = self._build_duo_prompt_context(normalized_seed_roles)
                    prompt = CONTENT_CUSTOM_DUO_USER.format(
                        user_message=user_message,
                        input_text=(input_text or "无"),
                        current_draft=current_draft,
                        user_history=user_history,
                        chat_summary=(chat_summary or "无"),
                        total_chars=total_chars,
                        role_1_id=duo_context["role_1_id"],
                        role_1_name=duo_context["role_1_name"],
                        role_1_description=duo_context["role_1_description"],
                        role_2_id=duo_context["role_2_id"],
                        role_2_name=duo_context["role_2_name"],
                        role_2_description=duo_context["role_2_description"],
                        scene_name=duo_context["scene_name"],
                        scene_description=duo_context["scene_description"],
                    )
                elif script_mode == "dialogue_script":
                    prompt = CONTENT_CUSTOM_DIALOGUE_SCRIPT_USER.format(
                        user_message=user_message,
                        input_text=(input_text or "无"),
                        current_draft=current_draft,
                        existing_roles=existing_roles,
                        user_history=user_history,
                        chat_summary=(chat_summary or "无"),
                        total_chars=total_chars,
                    )
                else:
                    prompt = CONTENT_CUSTOM_USER.format(
                        user_message=user_message,
                        input_text=(input_text or "无"),
                        current_draft=current_draft,
                        user_history=user_history,
                        chat_summary=(chat_summary or "无"),
                        total_chars=total_chars,
                    )
            elif script_mode == "duo_podcast":
                style = str(project.style or "").strip()
                default_duo_style_desc = (
                    DUO_PODCAST_STYLE_DESCRIPTIONS.get("无预设")
                    or DUO_PODCAST_STYLE_DESCRIPTIONS.get("默认")
                    or ""
                )
                style_desc = DUO_PODCAST_STYLE_DESCRIPTIONS.get(style, default_duo_style_desc)
                duo_context = self._build_duo_prompt_context(normalized_seed_roles)
                prompt = CONTENT_DIALOGUE_DUO_USER.format(
                    input_text=input_text,
                    total_chars=total_chars,
                    style_desc=style_desc,
                    role_1_name=duo_context["role_1_name"],
                    role_1_description=duo_context["role_1_description"],
                    role_2_name=duo_context["role_2_name"],
                    role_2_description=duo_context["role_2_description"],
                    scene_name=duo_context["scene_name"],
                    scene_description=duo_context["scene_description"],
                )
            elif script_mode == "dialogue_script":
                prompt = CONTENT_DIALOGUE_SCRIPT_USER.format(
                    input_text=input_text,
                    existing_roles=existing_roles,
                    total_chars=total_chars,
                )
            else:
                style = str(project.style or "").strip()
                default_single_style_desc = (
                    STYLE_DESCRIPTIONS.get("无预设") or STYLE_DESCRIPTIONS.get("默认") or ""
                )
                style_desc = STYLE_DESCRIPTIONS.get(style, default_single_style_desc)
                single_role = normalized_seed_roles[0] if normalized_seed_roles else {}
                prompt = CONTENT_USER.format(
                    input_text=input_text,
                    style_desc=style_desc,
                    total_chars=total_chars,
                    role_name=str(single_role.get("name") or DEFAULT_SINGLE_ROLE_NAME),
                    role_description=str(single_role.get("description") or "").strip() or "无设定",
                )

            log_stage_separator(logger)
            logger.info("[Content] LLM Generate - Content")
            logger.info(
                "[Input] llm_provider=%s(%s) llm_model=%s",
                llm_runtime.provider_name,
                llm_runtime.provider_type,
                llm_runtime.model,
            )
            logger.info("[Input] target_language=%s", get_unrestricted_language_log_label())
            logger.info("[Input] prompt: %s", truncate_generation_text(prompt))
            logger.info("[Input] system_prompt: %s", truncate_generation_text(CONTENT_SYSTEM))
            log_stage_separator(logger)

            use_stream = str((input_data or {}).get("llm_stream", "1")).strip().lower() not in {
                "0",
                "false",
                "off",
                "no",
            }
            raw_content = ""
            if use_stream:
                logger.info("[Content] LLM streaming enabled")
                chunks: list[str] = []
                chars_since_flush = 0
                try:
                    async for chunk in llm_provider.generate_stream(
                        prompt=prompt,
                        system_prompt=CONTENT_SYSTEM,
                        temperature=0.7,
                    ):
                        text = str(chunk or "")
                        if not text:
                            continue
                        chunks.append(text)
                        chars_since_flush += len(text)
                        if chars_since_flush < 500:
                            continue
                        partial_raw = "".join(chunks)
                        await self._persist_content_stream_progress(
                            db=db,
                            stage=stage,
                            script_mode=script_mode,
                            roles=normalized_seed_roles,
                            raw_text=partial_raw,
                        )
                        chars_since_flush = 0
                    raw_content = "".join(chunks).strip()
                except Exception as stream_err:
                    logger.warning(
                        "[Content] LLM stream failed (%r), fallback to non-stream generate",
                        stream_err,
                    )

            if not raw_content:
                response = await llm_provider.generate(
                    prompt=prompt,
                    system_prompt=CONTENT_SYSTEM,
                    temperature=0.7,
                )
                raw_content = response.content.strip()

            logger.info("[Output] content: %s", truncate_generation_text(raw_content))
            log_stage_separator(logger)
            if script_mode == "single":
                parsed_single = self._parse_single_payload(raw_content)
                content = self._ensure_spoken_punctuation(
                    str(parsed_single.get("content") or "").strip() or raw_content
                )
                normalized_roles = normalize_roles(
                    normalized_seed_roles,
                    script_mode=script_mode,
                    max_roles=max_roles,
                )
                normalized_roles, normalized_lines = normalize_dialogue_lines(
                    [],
                    roles=normalized_roles,
                    script_mode=script_mode,
                    max_roles=max_roles,
                    allow_role_autofill=True,
                    fallback_text=content,
                )
                if not normalized_lines:
                    return StageResult(success=False, error="单人文案为空，无法生成文案")
                normalized_roles = await self._sync_content_roles_to_reference_stage(
                    db=db,
                    project=project,
                    script_mode=script_mode,
                    roles=normalized_roles,
                    dialogue_lines=normalized_lines,
                )
                content = flatten_dialogue_text(normalized_lines)
                content = self._ensure_spoken_punctuation(content)
                title = str(parsed_single.get("title") or "").strip() or self._fallback_title(
                    content
                )
                char_count = count_chars(content)
                payload: dict[str, Any] = {
                    "content": content,
                    "title": title,
                    "char_count": char_count,
                    "script_mode": script_mode,
                    "roles": normalized_roles,
                    "dialogue_lines": normalized_lines,
                }
                if has_user_message:
                    next_history, next_summary = self._build_next_chat_memory(
                        chat_history=chat_history,
                        chat_summary=chat_summary,
                        user_message=user_message,
                        assistant_content=content,
                    )
                    payload.update(
                        {
                            "chat_history": next_history,
                            "chat_summary": next_summary,
                            "last_user_message": user_message,
                        }
                    )
                return StageResult(
                    success=True,
                    data=payload,
                )

            parsed_dialogue = self._parse_dialogue_payload(raw_content)
            if script_mode == "duo_podcast":
                # 双人播客角色与场景由已有配置固定，不允许模型改写。
                raw_roles = normalized_seed_roles
            else:
                raw_roles = parsed_dialogue.get("roles")
            raw_lines = parsed_dialogue.get("dialogue_lines")
            normalized_roles = normalize_roles(
                raw_roles,
                script_mode=script_mode,
                max_roles=max_roles,
            )
            normalized_roles, normalized_lines = normalize_dialogue_lines(
                raw_lines,
                roles=normalized_roles,
                script_mode=script_mode,
                max_roles=max_roles,
                allow_role_autofill=True,
                fallback_text=raw_content,
            )
            if not normalized_lines:
                return StageResult(success=False, error="对话内容为空，无法生成文案")
            normalized_lines = self._ensure_dialogue_line_punctuation(normalized_lines)
            normalized_roles = await self._sync_content_roles_to_reference_stage(
                db=db,
                project=project,
                script_mode=script_mode,
                roles=normalized_roles,
                dialogue_lines=normalized_lines,
            )
            content = flatten_dialogue_text(normalized_lines)
            content = self._ensure_spoken_punctuation(content)
            parsed_title = str(parsed_dialogue.get("title") or "").strip()
            title = parsed_title or await self._generate_title(llm_provider, llm_runtime, content)
            char_count = count_chars(content)
            payload: dict[str, Any] = {
                "content": content,
                "title": title,
                "char_count": char_count,
                "script_mode": script_mode,
                "roles": normalized_roles,
                "dialogue_lines": normalized_lines,
            }
            if has_user_message:
                next_history, next_summary = self._build_next_chat_memory(
                    chat_history=chat_history,
                    chat_summary=chat_summary,
                    user_message=user_message,
                    assistant_content=content,
                )
                payload.update(
                    {
                        "chat_history": next_history,
                        "chat_summary": next_summary,
                        "last_user_message": user_message,
                    }
                )

            return StageResult(
                success=True,
                data=payload,
            )

        except Exception as e:
            return StageResult(success=False, error=str(e))

    async def _sync_content_roles_to_reference_stage(
        self,
        *,
        db: AsyncSession,
        project: Project,
        script_mode: str,
        roles: list[dict[str, Any]],
        dialogue_lines: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        from app.services.stage_service import StageService

        service = StageService(db)
        synced_roles, _ = await service._sync_content_roles_with_references(
            project,
            script_mode,
            roles,
            create_missing=True,
            prune_unmatched=True,
            dialogue_lines=dialogue_lines,
        )
        reference_stage = await service._get_or_create_reference_stage_for_sync(project)
        reference_stage.status = StageStatus.COMPLETED
        reference_stage.progress = 100
        reference_stage.error_message = None
        return synced_roles

    async def _clear_reference_stage_for_content_reset(
        self,
        *,
        db: AsyncSession,
        project: Project,
    ) -> None:
        from app.services.stage_service import StageService

        service = StageService(db)
        # Reset to "custom" reference baseline => empty reference list.
        await service._reset_reference_stage_for_mode(project, SCRIPT_MODE_CUSTOM)

    async def _persist_content_stream_progress(
        self,
        db: AsyncSession,
        stage: StageExecution,
        script_mode: str,
        roles: list[dict[str, Any]],
        raw_text: str,
    ) -> None:
        stage.progress = min(94, max(int(stage.progress or 0), 65 + min(len(raw_text) // 220, 24)))
        output_data = dict(stage.output_data or {})
        output_data["script_mode"] = script_mode
        output_data["roles"] = roles
        output_data["partial_content_raw"] = raw_text[-12000:]
        output_data["progress_message"] = "正在接收文案流式输出..."

        if script_mode == "single":
            title = extract_json_string_value(raw_text, "title")
            content = extract_json_string_value(raw_text, "content")
            if isinstance(title, str) and title.strip():
                output_data["partial_title"] = title.strip()
            if isinstance(content, str) and content.strip():
                output_data["content"] = content.strip()
        else:
            title = extract_json_string_value(raw_text, "title")
            if isinstance(title, str) and title.strip():
                output_data["partial_title"] = title.strip()
            items = extract_json_array_items(raw_text, "dialogue_lines")
            partial_lines: list[dict[str, Any]] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                speaker_id = str(item.get("speaker_id") or item.get("speaker_name") or "").strip()
                speaker_name = str(item.get("speaker_name") or item.get("speaker_id") or "").strip()
                text = str(item.get("text") or "").strip()
                if not speaker_id or not text:
                    continue
                partial_lines.append(
                    {
                        "speaker_id": speaker_id,
                        "speaker_name": speaker_name,
                        "text": text,
                    }
                )
            if partial_lines:
                output_data["partial_dialogue_lines"] = partial_lines
                output_data["content"] = flatten_dialogue_text(partial_lines)

        stage.output_data = output_data
        flag_modified(stage, "output_data")
        await db.commit()

    @staticmethod
    def _build_reset_payload(script_mode: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "title": "",
            "content": "",
            "char_count": 0,
            "script_mode": script_mode,
            "roles": [],
            "dialogue_lines": [],
        }
        if script_mode == SCRIPT_MODE_CUSTOM:
            payload.update(
                {
                    "chat_history": [],
                    "chat_summary": "",
                    "last_user_message": "",
                }
            )
        return payload

    @staticmethod
    def _normalize_chat_history(raw_history: Any) -> list[dict[str, str]]:
        if not isinstance(raw_history, list):
            return []
        normalized: list[dict[str, str]] = []
        for item in raw_history:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            if role not in {"user", "assistant"}:
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            normalized.append(
                {
                    "role": role,
                    "text": text[:2000],
                }
            )
        if len(normalized) > CHAT_HISTORY_MAX_MESSAGES:
            return normalized[-CHAT_HISTORY_MAX_MESSAGES:]
        return normalized

    @staticmethod
    def _format_chat_history(chat_history: list[dict[str, str]]) -> str:
        if not chat_history:
            return "无"
        lines: list[str] = []
        for item in chat_history:
            role = str(item.get("role") or "").strip().lower()
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            role_label = "用户" if role == "user" else "助手"
            lines.append(f"{role_label}: {text}")
        return "\n".join(lines) if lines else "无"

    @staticmethod
    def _format_user_history(chat_history: list[dict[str, str]]) -> str:
        user_lines = [
            f"用户: {str(item.get('text') or '').strip()}"
            for item in chat_history
            if str(item.get("role") or "").strip().lower() == "user"
            and str(item.get("text") or "").strip()
        ]
        return "\n".join(user_lines) if user_lines else "无"

    @staticmethod
    def _format_current_draft(previous_output: dict[str, Any]) -> str:
        roles = previous_output.get("roles")
        dialogue_lines = previous_output.get("dialogue_lines")
        plain_content = str(previous_output.get("content") or "").strip()

        role_lines: list[str] = []
        if isinstance(roles, list):
            for item in roles:
                if not isinstance(item, dict):
                    continue
                role_name = str(item.get("name") or item.get("id") or "").strip()
                role_desc = str(item.get("description") or "").strip()
                if not role_name:
                    continue
                if role_desc:
                    role_lines.append(f"- {role_name}：{role_desc}")
                else:
                    role_lines.append(f"- {role_name}")

        script_lines: list[str] = []
        if isinstance(dialogue_lines, list):
            for item in dialogue_lines:
                if not isinstance(item, dict):
                    continue
                speaker_name = str(item.get("speaker_name") or item.get("speaker_id") or "").strip()
                text = str(item.get("text") or "").strip()
                if not text:
                    continue
                if speaker_name:
                    script_lines.append(f"- {speaker_name}: {text}")
                else:
                    script_lines.append(f"- {text}")

        if not script_lines and plain_content:
            script_lines = [f"- {plain_content}"]

        sections: list[str] = [
            "角色设定：",
            "\n".join(role_lines) if role_lines else "无",
            "",
            "台词草稿：",
            "\n".join(script_lines) if script_lines else "无",
        ]
        return "\n".join(sections)

    @staticmethod
    def _format_existing_roles(roles: list[dict[str, Any]]) -> str:
        if not isinstance(roles, list) or not roles:
            return "无"
        role_lines: list[str] = []
        for item in roles:
            if not isinstance(item, dict):
                continue
            role_id = str(item.get("id") or "").strip()
            role_name = str(item.get("name") or "").strip() or role_id
            role_desc = str(item.get("description") or "").strip()
            if not role_name:
                continue
            meta_parts: list[str] = []
            if role_id:
                meta_parts.append(f"id={role_id}")
            meta_suffix = f" ({', '.join(meta_parts)})" if meta_parts else ""
            role_lines.append(f"- {role_name}{meta_suffix}：{role_desc or '（未提供设定）'}")
        return "\n".join(role_lines) if role_lines else "无"

    @staticmethod
    def _build_duo_prompt_context(normalized_seed_roles: list[dict[str, Any]]) -> dict[str, str]:
        role_1 = next(
            (role for role in normalized_seed_roles if str(role.get("id") or "") == DUO_ROLE_1_ID),
            normalized_seed_roles[0] if normalized_seed_roles else {},
        )
        role_2 = next(
            (role for role in normalized_seed_roles if str(role.get("id") or "") == DUO_ROLE_2_ID),
            normalized_seed_roles[1] if len(normalized_seed_roles) > 1 else {},
        )
        scene_role = next(
            (
                role
                for role in normalized_seed_roles
                if str(role.get("id") or "") == DUO_SCENE_ROLE_ID
            ),
            normalized_seed_roles[2] if len(normalized_seed_roles) > 2 else {},
        )
        return {
            "role_1_id": DUO_ROLE_1_ID,
            "role_1_name": str(role_1.get("name") or DUO_ROLE_1_DEFAULT_NAME).strip()
            or DUO_ROLE_1_DEFAULT_NAME,
            "role_1_description": str(role_1.get("description") or "").strip()
            or DUO_ROLE_1_DEFAULT_DESCRIPTION,
            "role_2_id": DUO_ROLE_2_ID,
            "role_2_name": str(role_2.get("name") or DUO_ROLE_2_DEFAULT_NAME).strip()
            or DUO_ROLE_2_DEFAULT_NAME,
            "role_2_description": str(role_2.get("description") or "").strip()
            or DUO_ROLE_2_DEFAULT_DESCRIPTION,
            "scene_name": str(scene_role.get("name") or DUO_SCENE_ROLE_NAME).strip()
            or DUO_SCENE_ROLE_NAME,
            "scene_description": str(scene_role.get("description") or "").strip()
            or DUO_SCENE_DEFAULT_DESCRIPTION,
        }

    def _build_next_chat_memory(
        self,
        *,
        chat_history: list[dict[str, str]],
        chat_summary: str,
        user_message: str,
        assistant_content: str,
    ) -> tuple[list[dict[str, str]], str]:
        next_history = list(chat_history)
        if user_message:
            next_history.append({"role": "user", "text": user_message[:2000]})
        if assistant_content:
            next_history.append({"role": "assistant", "text": assistant_content[:3000]})

        clean_summary = str(chat_summary or "").strip()
        if len(next_history) <= CHAT_HISTORY_MAX_MESSAGES:
            return next_history, clean_summary

        overflow = next_history[:-CHAT_HISTORY_MAX_MESSAGES]
        kept_history = next_history[-CHAT_HISTORY_MAX_MESSAGES:]
        overflow_text = self._format_chat_history(overflow)
        merged_summary = "\n".join(
            part for part in [clean_summary, overflow_text] if part and part != "无"
        ).strip()
        if len(merged_summary) > CHAT_SUMMARY_MAX_CHARS:
            merged_summary = merged_summary[-CHAT_SUMMARY_MAX_CHARS:]

        return kept_history, merged_summary

    def _parse_single_payload(self, raw_text: str) -> dict[str, Any]:
        try:
            payload = self._parse_dialogue_payload(raw_text)
        except StageValidationError:
            return {}
        if not isinstance(payload, dict):
            return {}
        return payload

    @staticmethod
    def _fallback_title(content: str) -> str:
        sentence = str(content or "").strip().split("。", 1)[0].strip()
        sentence = re.sub(r"[，。！？；：、,.!?;:]+", "", sentence)
        if not sentence:
            return "未命名文案"
        return sentence[:24]

    async def _generate_title(self, llm_provider, llm_runtime, content: str) -> str:
        title_prompt = TITLE_USER.format(content=content[:500])

        log_stage_separator(logger)
        logger.info("[Content] LLM Generate - Title")
        logger.info(
            "[Input] llm_provider=%s(%s) llm_model=%s",
            llm_runtime.provider_name,
            llm_runtime.provider_type,
            llm_runtime.model,
        )
        logger.info("[Input] target_language=%s", get_unrestricted_language_log_label())
        logger.info("[Input] prompt: %s", truncate_generation_text(title_prompt))
        logger.info("[Input] system_prompt: %s", truncate_generation_text(CONTENT_SYSTEM))
        log_stage_separator(logger)

        title_response = await llm_provider.generate(
            prompt=title_prompt,
            system_prompt=CONTENT_SYSTEM,
            temperature=0.7,
        )

        logger.info("[Output] title: %s", title_response.content.strip())
        log_stage_separator(logger)
        return title_response.content.strip()

    def _ensure_dialogue_line_punctuation(
        self,
        lines: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        normalized_lines: list[dict[str, Any]] = []
        updated = 0
        for line in lines:
            item = dict(line)
            text = str(item.get("text") or "").strip()
            if text:
                repaired = self._ensure_spoken_punctuation(text)
                if repaired != text:
                    item["text"] = repaired
                    updated += 1
            normalized_lines.append(item)
        if updated > 0:
            logger.warning("[Content] punctuation repair applied to %d dialogue lines", updated)
        return normalized_lines

    def _ensure_spoken_punctuation(self, text: str) -> str:
        normalized = self._normalize_spoken_text_whitespace(text)
        if not normalized:
            return ""
        if self._has_sufficient_spoken_punctuation(normalized):
            return normalized

        repaired = self._inject_basic_spoken_punctuation(normalized)
        logger.warning(
            "[Content] punctuation repair applied (chars=%d -> %d)",
            len(normalized),
            len(repaired),
        )
        return repaired

    @staticmethod
    def _normalize_spoken_text_whitespace(text: str) -> str:
        normalized = str(text or "").replace("\r\n", "\n").replace("\n", " ").strip()
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = re.sub(r"\s*([，。！？；：、,.!?;:])\s*", r"\1", normalized)
        normalized = CJK_INLINE_SPACE_PATTERN.sub("", normalized)
        return normalized.strip()

    @staticmethod
    def _has_sufficient_spoken_punctuation(text: str) -> bool:
        return bool(SENTENCE_PUNCTUATION_PATTERN.search(text)) and bool(
            COMMON_PUNCTUATION_PATTERN.search(text)
        )

    @staticmethod
    def _inject_basic_spoken_punctuation(text: str) -> str:
        if not text:
            return ""
        dense = "".join(text.split())
        if not dense:
            return ""

        pieces: list[str] = []
        buffer: list[str] = []
        clause_chars = 16
        clause_index = 0
        for ch in dense:
            buffer.append(ch)
            if len(buffer) < clause_chars:
                continue
            punct = "，" if clause_index % 2 == 0 else "。"
            pieces.append("".join(buffer) + punct)
            buffer = []
            clause_index += 1

        if buffer:
            tail = "".join(buffer)
            if not SENTENCE_PUNCTUATION_PATTERN.search(tail[-1:]):
                tail = f"{tail}。"
            pieces.append(tail)

        repaired = "".join(pieces).strip()
        if not SENTENCE_PUNCTUATION_PATTERN.search(repaired):
            repaired = f"{repaired}。"
        return repaired

    def _parse_dialogue_payload(self, raw_text: str) -> dict[str, Any]:
        text = raw_text.strip()
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if json_match:
            text = json_match.group(1).strip()
        start_idx = text.find("{")
        end_idx = text.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            text = text[start_idx : end_idx + 1]
        try:
            payload = json.loads(text)
        except JSONDecodeError as exc:
            repaired_text = self._repair_unescaped_json_quotes(text)
            if repaired_text == text:
                raise StageValidationError(f"对话生成结果不是合法 JSON：{exc}") from exc
            try:
                payload = json.loads(repaired_text)
                logger.warning(
                    "[Content] invalid JSON repaired automatically (reason=%s line=%s col=%s)",
                    exc.msg,
                    exc.lineno,
                    exc.colno,
                )
            except JSONDecodeError as repaired_exc:
                raise StageValidationError(
                    f"对话生成结果不是合法 JSON（自动修复失败）：{repaired_exc}"
                ) from repaired_exc
        if not isinstance(payload, dict):
            raise StageValidationError("对话生成结果格式错误：未返回 JSON 对象")
        return payload

    @staticmethod
    def _repair_unescaped_json_quotes(text: str) -> str:
        # Repair common model output issue: unescaped double quotes inside JSON string values.
        chars = list(text)
        result: list[str] = []
        in_string = False
        escaped = False
        length = len(chars)

        def next_non_space(index: int) -> str:
            cursor = index
            while cursor < length and chars[cursor].isspace():
                cursor += 1
            return chars[cursor] if cursor < length else ""

        for idx, ch in enumerate(chars):
            if not in_string:
                if ch == '"':
                    in_string = True
                result.append(ch)
                escaped = False
                continue

            if escaped:
                result.append(ch)
                escaped = False
                continue

            if ch == "\\":
                result.append(ch)
                escaped = True
                continue

            if ch == '"':
                follower = next_non_space(idx + 1)
                if follower in {",", "}", "]", ":"}:
                    in_string = False
                    result.append(ch)
                else:
                    result.append('\\"')
                continue

            result.append(ch)

        return "".join(result)

    async def _get_input_text(self, db: AsyncSession, project: Project) -> str | None:
        # 优先从 sources 表获取所有选中的来源
        source_service = SourceService(db)
        combined_content = await source_service.get_selected_content(project.id)
        if combined_content:
            return combined_content

        # 若未配置 sources，使用项目输入文本
        if project.input_text:
            return project.input_text

        # 再尝试从 research stage 获取
        result = await db.execute(
            select(StageExecution)
            .where(
                StageExecution.project_id == project.id,
                StageExecution.stage_type == StageType.RESEARCH,
            )
            .order_by(StageExecution.updated_at.desc(), StageExecution.id.desc())
        )
        for research_stage in result.scalars():
            output_data = research_stage.output_data or {}
            report = output_data.get("report")
            if isinstance(report, str) and report.strip():
                return report

        return None

    async def validate_prerequisites(
        self,
        db: AsyncSession,
        project: Project,
    ) -> str | None:
        # Content stage supports mode-specific validation in execute();
        # custom mode can be generated from user_message only.
        _ = (db, project)
        return None
