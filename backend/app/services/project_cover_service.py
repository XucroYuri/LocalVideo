from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ServiceError
from app.db.session import AsyncSessionLocal
from app.llm.runtime import ResolvedLLMRuntime, resolve_llm_runtime
from app.models.project import Project
from app.stages.common.data_access import get_content_data

logger = logging.getLogger(__name__)
PUNCTUATION_PATTERN = re.compile(r'[，。！？；：,.!?;:、\'"()（）【】\[\]《》<>～~…—\-\s]')

DEFAULT_PROJECT_COVER_EMOJI = "🎬"
PROJECT_COVER_SYSTEM_PROMPT = (
    "你是中文内容主题识别助手。"
    "你要根据项目标题与文案内容，挑选一个最贴切的单个 emoji 作为项目封面。"
    "输出必须是 JSON，字段名固定为 emoji。"
)


class ProjectCoverService:
    _tasks: dict[int, asyncio.Task[None]] = {}
    _tasks_lock = asyncio.Lock()

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        return str(value or "").strip()

    @classmethod
    def has_usable_content_payload(cls, payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        content = cls._normalize_text(str(payload.get("content") or ""))
        if content:
            return True
        dialogue_lines = payload.get("dialogue_lines")
        if not isinstance(dialogue_lines, list):
            return False
        return any(
            isinstance(item, dict) and cls._normalize_text(str(item.get("text") or ""))
            for item in dialogue_lines
        )

    @classmethod
    def _truncate_text(cls, value: str, limit: int = 1200) -> str:
        text = cls._normalize_text(value)
        if len(text) <= limit:
            return text
        return text[:limit].rstrip()

    @staticmethod
    def _count_chars(text: str) -> int:
        return len(PUNCTUATION_PATTERN.sub("", text))

    @classmethod
    def _normalize_generated_emoji(cls, value: str | None) -> str:
        text = cls._normalize_text(value)
        if not text:
            return ""

        compact = text.splitlines()[0].strip().split()[0].strip()
        compact = compact.strip("\"'`")
        if not compact:
            return ""

        # 允许常见复合 emoji（带 VS16 / ZWJ），但拒绝明显的解释文本。
        if len(compact) > 8:
            return ""
        if any(ch.isalnum() for ch in compact):
            return ""
        return compact

    @classmethod
    def _truncate_log_text(cls, value: str | None, limit: int = 1000) -> str:
        text = cls._normalize_text(value)
        if len(text) <= limit:
            return text
        return f"{text[:limit]}..."

    @staticmethod
    def _extract_json_object_from_text(output_text: str) -> dict:
        import json
        import re

        text = str(output_text or "").strip()
        if not text:
            return {}

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
            except Exception:
                pass

            decoder = json.JSONDecoder()
            for idx, ch in enumerate(candidate):
                if ch != "{":
                    continue
                try:
                    parsed, end = decoder.raw_decode(candidate[idx:])
                except Exception:
                    continue
                if end > 0 and isinstance(parsed, dict):
                    return parsed

        return {}

    @classmethod
    def _build_prompt(cls, *, project: Project, content_data: dict) -> str:
        title = cls._normalize_text(project.title)
        content = cls._truncate_text(str(content_data.get("content") or ""), 900)
        dialogue_lines = content_data.get("dialogue_lines")
        line_texts: list[str] = []
        if isinstance(dialogue_lines, list):
            for item in dialogue_lines[:6]:
                if not isinstance(item, dict):
                    continue
                speaker = cls._normalize_text(
                    str(item.get("speaker_name") or item.get("speaker_id") or "")
                )
                text = cls._normalize_text(str(item.get("text") or ""))
                if not text:
                    continue
                line_texts.append(f"{speaker}: {text}" if speaker else text)
        dialogue_block = "\n".join(f"- {one}" for one in line_texts) or "（空）"
        return (
            "请直接选择 1 个最适合当前项目主题的单个 emoji 作为封面。\n"
            "判断标准：优先看文案主题，其次看标题。\n"
            "不要输出文字解释，不要输出多个 emoji，不要输出 JSON 以外的内容。\n"
            "不要解释，不要输出额外文本。\n"
            f"项目标题：{title or '（空）'}\n"
            f"文案字数：{cls._count_chars(content)}\n"
            f"文案摘要：{content or '（空）'}\n"
            f"示例台词：\n{dialogue_block}\n\n"
            '只输出 JSON，例如：{"emoji":"🤖"}'
        )

    @staticmethod
    def _log_llm_input(
        *,
        project_id: int,
        llm_runtime: ResolvedLLMRuntime,
        prompt: str,
    ) -> None:
        logger.info("=" * 80)
        logger.info("[ProjectCover] Generate project_id=%s", project_id)
        logger.info(
            "[Input] llm_provider=%s(%s) llm_model=%s",
            llm_runtime.provider_name,
            llm_runtime.provider_type,
            llm_runtime.model,
        )
        logger.info("[Input] prompt=%s", prompt[:1500])
        logger.info("=" * 80)

    @classmethod
    def _log_llm_output(
        cls,
        *,
        project_id: int,
        raw_text: str,
        parsed_payload: dict,
        resolved_emoji: str,
    ) -> None:
        logger.info("=" * 80)
        logger.info("[ProjectCover] Generate Output project_id=%s", project_id)
        logger.info("[Output] raw=%s", cls._truncate_log_text(raw_text, 1500))
        logger.info("[Output] parsed=%s", cls._truncate_log_text(str(parsed_payload), 500))
        logger.info("[Output] emoji=%s", resolved_emoji or "（空）")
        logger.info("=" * 80)

    @classmethod
    async def _ensure_no_running_task(cls, project_id: int) -> None:
        async with cls._tasks_lock:
            task = cls._tasks.get(project_id)
            if task and not task.done():
                raise ServiceError(409, "封面生成进行中，请稍后重试")

    @classmethod
    async def schedule_initial_generation(cls, project_id: int) -> bool:
        async with cls._tasks_lock:
            task = cls._tasks.get(project_id)
            if task and not task.done():
                return False

            async def runner() -> None:
                try:
                    async with AsyncSessionLocal() as db:
                        service = cls(db)
                        await service.generate_cover(project_id, force=False, fail_if_missing=False)
                except Exception as exc:
                    logger.warning(
                        "[ProjectCover] auto generation failed project_id=%s error=%s",
                        project_id,
                        exc,
                    )
                finally:
                    async with cls._tasks_lock:
                        current = cls._tasks.get(project_id)
                        if current is task:
                            cls._tasks.pop(project_id, None)

            task = asyncio.create_task(runner())
            cls._tasks[project_id] = task
            return True

    async def generate_cover(
        self,
        project_id: int,
        *,
        force: bool,
        fail_if_missing: bool,
    ) -> Project | None:
        if force:
            await self._ensure_no_running_task(project_id)

        project = await self.db.get(Project, project_id)
        if project is None:
            raise ServiceError(404, "项目不存在")

        if not force and project.cover_emoji and project.cover_generated_at is not None:
            return project

        content_data = await get_content_data(self.db, project_id)
        if not self.has_usable_content_payload(content_data):
            if fail_if_missing:
                raise ServiceError(400, "请先生成文案后再重新生成 emoji")
            return project

        try:
            llm_runtime = resolve_llm_runtime(default_mode="fast_first")
        except Exception as exc:
            raise ServiceError(503, f"emoji 生成不可用：{exc}") from exc

        prompt = self._build_prompt(project=project, content_data=content_data or {})
        self._log_llm_input(project_id=project_id, llm_runtime=llm_runtime, prompt=prompt)
        try:
            payload = await llm_runtime.provider.generate_json(
                prompt=prompt,
                system_prompt=PROJECT_COVER_SYSTEM_PROMPT,
                temperature=0.1,
            )
        except Exception as exc:
            raise ServiceError(502, f"emoji 生成失败：{exc}") from exc
        if not isinstance(payload, dict):
            raise ServiceError(502, "emoji 生成返回格式无效")

        raw_text = str(payload)
        emoji = self._normalize_generated_emoji(str(payload.get("emoji") or ""))
        if not emoji:
            raw_payload = self._extract_json_object_from_text(str(payload))
            emoji = self._normalize_generated_emoji(str(raw_payload.get("emoji") or ""))
            if raw_payload:
                payload = raw_payload
        self._log_llm_output(
            project_id=project_id,
            raw_text=raw_text,
            parsed_payload=payload,
            resolved_emoji=emoji,
        )
        if not emoji:
            raise ServiceError(502, "emoji 生成结果无效")

        project.cover_emoji = emoji
        project.cover_generated_at = datetime.now()
        project.cover_generation_attempted = True
        await self.db.commit()
        await self.db.refresh(project)
        return project
