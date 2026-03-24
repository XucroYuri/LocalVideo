"""Storyboard generation stage handler."""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import cache
from typing import Any
from uuid import uuid4

from json_repair import loads as repair_json_loads
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.dialogue import (
    DEFAULT_SINGLE_ROLE_ID,
    DUO_ROLE_1_DEFAULT_DESCRIPTION,
    DUO_ROLE_1_DEFAULT_NAME,
    DUO_ROLE_1_ID,
    DUO_ROLE_2_DEFAULT_DESCRIPTION,
    DUO_ROLE_2_DEFAULT_NAME,
    DUO_ROLE_2_ID,
    resolve_script_mode,
)
from app.core.project_mode import resolve_script_mode_from_video_type
from app.core.reference_slots import build_reference_slots_from_ids, normalize_reference_slots
from app.core.stream_json import extract_json_array_items
from app.llm.runtime import resolve_llm_runtime
from app.models.project import Project
from app.models.stage import StageExecution, StageType
from app.providers.video_capabilities import (
    get_theoretical_single_generation_limit_seconds,
)
from app.stages.common.data_access import get_latest_stage_output
from app.stages.common.log_utils import log_stage_separator
from app.stages.common.paths import resolve_path_for_io
from app.stages.prompts import (
    build_storyboard_prompt,
    build_storyboard_regenerate_prompt,
    build_storyboard_smart_merge_prompt,
    build_storyboard_smart_merge_repair_prompt,
    resolve_storyboard_prompt_config,
)

from . import register_stage
from ._generation_log import format_generation_json, truncate_generation_text
from .base import StageHandler, StageResult

logger = logging.getLogger(__name__)

TEXT_NORMALIZE_PATTERN = re.compile(r"[^\u4e00-\u9fa5a-zA-Z0-9]+")
CONTENT_REQUIRED_ERROR = "文案内容为空或不可用，请先生成或保存文案"
STORYBOARD_REQUIRED_ERROR = "分镜生成失败，请调整文案或模型配置后重试"
SMART_MERGE_MAX_DURATION_CAP_SECONDS = 10.0
SMART_MERGE_THEORETICAL_WARNING_RATIO = 1.3


@dataclass
class SmartMergeValidationIssue:
    code: str
    message: str
    shot_index: int | None = None
    source_indices: list[int] | None = None


STORYBOARD_SHOT_DENSITY_CONFIG: dict[str, dict[str, float | str]] = {
    "low": {
        "label": "低密度",
        "avg_shot_seconds": 4.5,
        "min_shot_seconds": 4.0,
        "max_shot_seconds": 6.0,
    },
    "medium": {
        "label": "中密度",
        "avg_shot_seconds": 3.0,
        "min_shot_seconds": 2.5,
        "max_shot_seconds": 4.0,
    },
    "high": {
        "label": "高密度",
        "avg_shot_seconds": 2.0,
        "min_shot_seconds": 1.5,
        "max_shot_seconds": 3.0,
    },
}

STORYBOARD_SYSTEM_PROMPT = """你是专业的视频分镜规划师。

你的任务是把输入文案规划成可执行的分镜 JSON。
必须遵守：
1. voice_content 必须直接复制原文，不得改写、总结、润色、补词、漏词、重排。
2. 单个分镜内可见参考集合不能变化；如果角色/主体可见集合变化，必须拆成多个分镜。
3. video_prompt 必须是可直接喂给视频模型的描述，突出主体、构图、机位、动作、光线和氛围。
4. video_reference_slots 只能从给定参考信息里选；若当前分镜无需参考，返回空数组。
5. 返回 JSON 对象，顶层只允许有一个 shots 数组。"""

SMART_MERGE_SYSTEM_PROMPT = """你是专业的视频分镜优化师与合并规划师。

你的任务不是重写文案，而是在给定约束下把连续分镜重构为更少的分镜 JSON。
必须遵守：
1. 不能改写、润色、补词、删词、重排 voice_content；合并后的 voice_content 只能由连续原分镜文案直接拼接。
2. 不能跨 speaker_id 合并。
3. 不能超过当前视频模型单次推荐时长上限。
4. 不能使用参考信息之外的 video_reference_slots。
5. 若某些分镜保持独立或向后合并更利于一致性，就不要为了减少数量而强行向前合并。
6. 只输出 JSON 对象，顶层只允许有一个 shots 数组。"""


def _normalize_text(value: str) -> str:
    return TEXT_NORMALIZE_PATTERN.sub("", str(value or ""))


def _similarity_ratio(left: str, right: str) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return SequenceMatcher(a=left, b=right, autojunk=False).ratio()


def _build_normalized_index(raw_text: str) -> tuple[str, list[int]]:
    normalized_chars: list[str] = []
    raw_positions: list[int] = []
    for raw_index, char in enumerate(str(raw_text or "")):
        normalized = _normalize_text(char)
        if not normalized:
            continue
        for normalized_char in normalized:
            normalized_chars.append(normalized_char)
            raw_positions.append(raw_index)
    return "".join(normalized_chars), raw_positions


def _align_generated_segments_to_source(
    source_reference: str,
    generated_segments: list[str],
) -> list[str] | None:
    if not generated_segments:
        return None

    source_normalized, raw_positions = _build_normalized_index(source_reference)
    generated_normalized = [_normalize_text(item) for item in generated_segments]
    if not source_normalized or any(not item for item in generated_normalized):
        return None

    if len(source_normalized) < len(generated_normalized):
        return None

    global_ratio = _similarity_ratio("".join(generated_normalized), source_normalized)
    if global_ratio < 0.75:
        return None

    target_lengths = [len(item) for item in generated_normalized]
    suffix_lengths = [0] * (len(target_lengths) + 1)
    for index in range(len(target_lengths) - 1, -1, -1):
        suffix_lengths[index] = suffix_lengths[index + 1] + target_lengths[index]

    @cache
    def _search(segment_index: int, start_index: int) -> tuple[float, tuple[int, ...]] | None:
        remaining_segments = len(generated_normalized) - segment_index
        remaining_source_length = len(source_normalized) - start_index
        if remaining_source_length < remaining_segments:
            return None

        current_text = generated_normalized[segment_index]
        if segment_index == len(generated_normalized) - 1:
            candidate = source_normalized[start_index:]
            score = _similarity_ratio(current_text, candidate)
            return score, (len(source_normalized),)

        remaining_target_length = max(suffix_lengths[segment_index], 1)
        ideal_length = max(
            1,
            round(remaining_source_length * len(current_text) / remaining_target_length),
        )
        slack = max(4, int(max(len(current_text), ideal_length) * 0.55))
        min_length = max(1, ideal_length - slack)
        max_length = min(remaining_source_length - (remaining_segments - 1), ideal_length + slack)
        if min_length > max_length:
            return None

        candidate_end_indexes = list(range(start_index + min_length, start_index + max_length + 1))
        candidate_end_indexes.sort(
            key=lambda end_index: abs((end_index - start_index) - ideal_length)
        )

        best: tuple[float, tuple[int, ...]] | None = None
        for end_index in candidate_end_indexes:
            candidate = source_normalized[start_index:end_index]
            score = _similarity_ratio(current_text, candidate)
            tail = _search(segment_index + 1, end_index)
            if tail is None:
                continue
            total_score = score + tail[0]
            if best is None or total_score > best[0]:
                best = (total_score, (end_index, *tail[1]))
        return best

    best_match = _search(0, 0)
    if best_match is None:
        return None

    normalized_end_indexes = list(best_match[1])
    resolved_segments: list[str] = []
    raw_start_index = 0
    normalized_start_index = 0
    similarity_scores: list[float] = []

    for segment_index, normalized_end_index in enumerate(normalized_end_indexes):
        raw_end_index = (
            raw_positions[normalized_end_index]
            if normalized_end_index < len(raw_positions)
            else len(source_reference)
        )
        resolved_text = source_reference[raw_start_index:raw_end_index]
        resolved_normalized = source_normalized[normalized_start_index:normalized_end_index]
        if not resolved_normalized:
            return None
        similarity_scores.append(
            _similarity_ratio(generated_normalized[segment_index], resolved_normalized)
        )
        resolved_segments.append(resolved_text)
        raw_start_index = raw_end_index
        normalized_start_index = normalized_end_index

    if normalized_start_index != len(source_normalized):
        return None

    if min(similarity_scores, default=0.0) < 0.35:
        return None
    if sum(similarity_scores) / max(len(similarity_scores), 1) < 0.72:
        return None

    return resolved_segments


def _coerce_dialogue_lines(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    lines: list[dict[str, Any]] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        speaker_id = str(item.get("speaker_id") or "").strip() or DEFAULT_SINGLE_ROLE_ID
        speaker_name = str(item.get("speaker_name") or "").strip() or speaker_id
        lines.append(
            {
                "id": str(item.get("id") or f"line_{idx + 1}").strip() or f"line_{idx + 1}",
                "speaker_id": speaker_id,
                "speaker_name": speaker_name,
                "text": text,
                "order": idx,
            }
        )
    return lines


def _resolve_shot_speakers_from_dialogue_lines(
    shots: list[dict[str, Any]],
    dialogue_lines: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]] | None, str | None]:
    if not shots or not dialogue_lines:
        return shots, None

    line_cursor = 0
    line_offset = 0
    resolved: list[dict[str, Any]] = []

    for shot_index, shot in enumerate(shots):
        remaining = str(shot.get("voice_content") or "")
        if not remaining:
            resolved.append(dict(shot))
            continue

        assigned_speaker_id = ""
        assigned_speaker_name = ""
        consumed_any = False

        while remaining:
            if line_cursor >= len(dialogue_lines):
                return None, f"第 {shot_index + 1} 个分镜的 speaker 无法映射回原始台词"

            current_line = dialogue_lines[line_cursor]
            current_text = str(current_line.get("text") or "")
            available = current_text[line_offset:]
            if not available:
                line_cursor += 1
                line_offset = 0
                continue

            if not remaining.startswith(available) and not available.startswith(remaining):
                return None, f"第 {shot_index + 1} 个分镜的 voice_content 与原始对话边界不一致"

            current_speaker_id = (
                str(current_line.get("speaker_id") or "").strip() or DEFAULT_SINGLE_ROLE_ID
            )
            current_speaker_name = (
                str(current_line.get("speaker_name") or "").strip() or current_speaker_id
            )
            if not assigned_speaker_id:
                assigned_speaker_id = current_speaker_id
                assigned_speaker_name = current_speaker_name
            elif assigned_speaker_id != current_speaker_id:
                return None, f"第 {shot_index + 1} 个分镜跨越了不同 speaker_id 的原始台词"

            consumed_any = True

            if remaining.startswith(available):
                remaining = remaining[len(available) :]
                line_cursor += 1
                line_offset = 0
                continue

            line_offset += len(remaining)
            remaining = ""

        if not consumed_any or not assigned_speaker_id:
            return None, f"第 {shot_index + 1} 个分镜缺少可用的 speaker 映射"

        next_shot = dict(shot)
        next_shot["speaker_id"] = assigned_speaker_id
        next_shot["speaker_name"] = assigned_speaker_name
        resolved.append(next_shot)

    return resolved, None


def _estimate_source_char_count(source_reference: str) -> int:
    return len(_normalize_text(source_reference))


def _summarize_shots(shots: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "shot_count": len(shots),
        "voice_content_chars": sum(len(str(item.get("voice_content") or "")) for item in shots),
        "video_prompt_count": sum(
            1 for item in shots if str(item.get("video_prompt") or "").strip()
        ),
        "reference_slot_count": sum(
            len(item.get("video_reference_slots") or [])
            for item in shots
            if isinstance(item.get("video_reference_slots"), list)
        ),
    }


def _reference_slot_ids(raw: Any) -> list[str]:
    return [
        str(item.get("id") or "").strip()
        for item in normalize_reference_slots(raw)
        if str(item.get("id") or "").strip()
    ]


def _stringify_reference_ids(raw: list[str]) -> str:
    if not raw:
        return "[]"
    return "[" + ", ".join(raw) + "]"


def _build_smart_merge_shots_display(
    shots: list[dict[str, Any]],
    shot_durations: dict[int, float],
) -> str:
    lines: list[str] = []
    for idx, shot in enumerate(shots):
        reference_ids = _reference_slot_ids(shot.get("video_reference_slots"))
        lines.append(
            "\n".join(
                [
                    f"- shot_index={idx}",
                    f"  speaker_id={str(shot.get('speaker_id') or '').strip() or DEFAULT_SINGLE_ROLE_ID}",
                    f"  speaker_name={str(shot.get('speaker_name') or '').strip() or str(shot.get('speaker_id') or DEFAULT_SINGLE_ROLE_ID).strip() or DEFAULT_SINGLE_ROLE_ID}",
                    f"  duration_seconds={float(shot_durations.get(idx, 0.0) or 0.0):.3f}",
                    f"  voice_content={str(shot.get('voice_content') or '')}",
                    f"  video_prompt={str(shot.get('video_prompt') or '')}",
                    f"  video_reference_slot_ids={_stringify_reference_ids(reference_ids)}",
                ]
            )
        )
    return "\n".join(lines)


def _build_smart_merge_window_display(
    *,
    shots: list[dict[str, Any]],
    shot_durations: dict[int, float],
    original_indices: list[int],
    include_reference_slots: bool,
) -> str:
    lines: list[str] = []
    for local_idx, (original_index, shot) in enumerate(zip(original_indices, shots, strict=False)):
        source_indices = shot.get("source_shot_indices")
        source_indices_text = str(source_indices) if isinstance(source_indices, list) else "[]"
        reference_ids = (
            _reference_slot_ids(shot.get("video_reference_slots"))
            if include_reference_slots
            else []
        )
        entry = [
            f"- window_index={local_idx}",
            f"  original_index={original_index}",
            f"  speaker_id={str(shot.get('speaker_id') or '').strip() or DEFAULT_SINGLE_ROLE_ID}",
            f"  speaker_name={str(shot.get('speaker_name') or '').strip() or str(shot.get('speaker_id') or DEFAULT_SINGLE_ROLE_ID).strip() or DEFAULT_SINGLE_ROLE_ID}",
            f"  duration_seconds={float(shot_durations.get(original_index, 0.0) or 0.0):.3f}",
            f"  voice_content={str(shot.get('voice_content') or '')}",
        ]
        if "video_prompt" in shot:
            entry.append(f"  video_prompt={str(shot.get('video_prompt') or '')}")
        if include_reference_slots:
            entry.append(f"  video_reference_slot_ids={_stringify_reference_ids(reference_ids)}")
        if isinstance(source_indices, list):
            entry.append(f"  source_shot_indices={source_indices_text}")
        lines.append("\n".join(entry))
    return "\n".join(lines)


@register_stage(StageType.STORYBOARD)
class StoryboardHandler(StageHandler):
    async def execute(
        self,
        db: AsyncSession,
        project: Project,
        stage: StageExecution,
        input_data: dict[str, Any] | None = None,
    ) -> StageResult:
        stage_input = input_data or {}
        content_data = await self._get_content_data(db, project)
        if not content_data:
            return StageResult(success=False, error=CONTENT_REQUIRED_ERROR)

        script_mode = resolve_script_mode(
            content_data.get("script_mode")
            or resolve_script_mode_from_video_type(project.video_type)
        )
        dialogue_lines = _coerce_dialogue_lines(content_data.get("dialogue_lines"))
        source_text = str(content_data.get("content") or "").strip()

        if dialogue_lines:
            source_display = "\n".join(
                f"- {line['id']} | {line['speaker_name']}: {line['text']}"
                for line in dialogue_lines
            )
            source_reference = "".join(line["text"] for line in dialogue_lines)
        else:
            if not source_text:
                return StageResult(success=False, error=CONTENT_REQUIRED_ERROR)
            source_display = source_text
            source_reference = source_text

        existing_storyboard = await get_latest_stage_output(db, project.id, StageType.STORYBOARD)
        existing_shots = (
            [dict(item) for item in existing_storyboard.get("shots", [])]
            if isinstance(existing_storyboard, dict)
            else []
        )
        action = str(stage_input.get("action") or "").strip().lower()
        if action == "smart_merge":
            return await self._execute_smart_merge(
                db=db,
                project=project,
                stage=stage,
                stage_input=stage_input,
                script_mode=script_mode,
                existing_shots=existing_shots,
            )

        only_shot_index = (
            stage_input.get("only_shot_index")
            if stage_input.get("only_shot_index") is not None
            else None
        )

        reference_data = await self._get_reference_data(db, project)
        reference_info, allowed_reference_ids = self._build_reference_info(
            reference_data,
            script_mode=script_mode,
            content_data=content_data,
        )
        shot_plan_note = self._build_shot_plan_guidance(
            source_reference=source_reference,
            input_data=stage_input,
        )
        prompt_config = resolve_storyboard_prompt_config(stage_input)

        prompt = self._build_prompt(
            script_mode=script_mode,
            title=str(project.title or "").strip(),
            source_display=source_display,
            reference_info=reference_info,
            shot_plan_note=shot_plan_note,
            only_shot_index=only_shot_index,
            existing_shots=existing_shots,
            prompt_config=prompt_config,
        )

        llm_runtime = resolve_llm_runtime(stage_input)
        log_stage_separator(logger)
        logger.info(
            "[Storyboard] LLM Generate - %s",
            "Single Shot Regenerate" if only_shot_index is not None else "Shot Planning",
        )
        logger.info(
            "[Input] llm_provider=%s(%s) llm_model=%s",
            llm_runtime.provider_name,
            llm_runtime.provider_type,
            llm_runtime.model,
        )
        logger.info("[Input] script_mode=%s", script_mode)
        logger.info("[Input] only_shot_index=%s", only_shot_index)
        logger.info("[Input] existing_shot_count=%d", len(existing_shots))
        logger.info("[Input] allowed_reference_count=%d", len(allowed_reference_ids))
        logger.info(
            "[Input] target_language=%s(%s)",
            prompt_config["target_language"],
            prompt_config["target_language_label"],
        )
        logger.info(
            "[Input] prompt_complexity=%s(%s)",
            prompt_config["prompt_complexity"],
            prompt_config["prompt_complexity_label"],
        )
        logger.info(
            "[Input] storyboard_shot_density=%s",
            self._normalize_storyboard_shot_density(stage_input.get("storyboard_shot_density")),
        )
        logger.info(
            "[Input] system_prompt=%s",
            truncate_generation_text(STORYBOARD_SYSTEM_PROMPT),
        )
        log_stage_separator(logger)
        payload, error = await self._generate_with_retry(
            db=db,
            stage=stage,
            provider=llm_runtime.provider,
            provider_name=llm_runtime.provider_name,
            provider_type=llm_runtime.provider_type,
            model=llm_runtime.model,
            prompt=prompt,
            source_reference=source_reference,
            dialogue_lines=dialogue_lines,
            script_mode=script_mode,
            allowed_reference_ids=allowed_reference_ids,
            only_shot_index=only_shot_index,
            existing_shots=existing_shots,
        )
        if payload is None:
            return StageResult(success=False, error=error or STORYBOARD_REQUIRED_ERROR)

        if only_shot_index is not None:
            if (
                not isinstance(only_shot_index, int)
                or only_shot_index < 0
                or only_shot_index >= len(existing_shots)
            ):
                return StageResult(
                    success=False, error=f"Shot index {only_shot_index} out of range"
                )
            normalized_target = payload[0]
            current = dict(existing_shots[only_shot_index])
            current.update(normalized_target)
            current["shot_id"] = str(existing_shots[only_shot_index].get("shot_id") or uuid4().hex)
            current["shot_index"] = only_shot_index
            existing_shots[only_shot_index] = current
            shots = self._finalize_shots(existing_shots)
        else:
            shots = self._finalize_shots(payload)

        logger.info("[Output] shots_summary=%s", _summarize_shots(shots))
        log_stage_separator(logger)
        return StageResult(
            success=True,
            data={
                "script_mode": script_mode,
                "shots": shots,
                "shot_count": len(shots),
                "references": reference_data.get("references", [])
                if isinstance(reference_data, dict)
                else [],
            },
        )

    async def _execute_smart_merge(
        self,
        *,
        db: AsyncSession,
        project: Project,
        stage: StageExecution,
        stage_input: dict[str, Any],
        script_mode: str,
        existing_shots: list[dict[str, Any]],
    ) -> StageResult:
        if len(existing_shots) < 2:
            return StageResult(success=False, error="当前分镜不足 2 个，无法智能合并")

        reference_data = await self._get_reference_data(db, project)
        content_data = await self._get_content_data(db, project)
        reference_info, allowed_reference_ids = self._build_reference_info(
            reference_data,
            script_mode=script_mode,
            content_data=content_data,
        )
        audio_data = await get_latest_stage_output(db, project.id, StageType.AUDIO)
        shot_durations, duration_error = self._build_audio_duration_map(
            shots=existing_shots,
            audio_data=audio_data,
        )
        if duration_error:
            return StageResult(success=False, error=duration_error)

        (
            video_provider,
            video_model,
            video_mode,
            theoretical_max_duration_seconds,
        ) = self._resolve_smart_merge_video_context(stage_input)
        if theoretical_max_duration_seconds is None or theoretical_max_duration_seconds <= 0:
            return StageResult(success=False, error="无法解析当前视频模型的单次时长上限")

        use_first_frame_ref = bool(stage_input.get("use_first_frame_ref", False))
        use_reference_image_ref = bool(stage_input.get("use_reference_image_ref", False))
        title = str(project.title or "").strip()
        prompt_config = resolve_storyboard_prompt_config(stage_input)
        prompt_max_duration_seconds = self._resolve_smart_merge_prompt_duration_limit(
            theoretical_max_duration_seconds
        )
        prompt = self._build_smart_merge_prompt(
            title=title,
            script_mode=script_mode,
            shots=existing_shots,
            shot_durations=shot_durations,
            reference_info=reference_info,
            video_provider=video_provider,
            video_model=video_model,
            video_mode=video_mode,
            max_duration_seconds=prompt_max_duration_seconds,
            use_first_frame_ref=use_first_frame_ref,
            use_reference_image_ref=use_reference_image_ref,
            prompt_config=prompt_config,
        )

        llm_runtime = resolve_llm_runtime(stage_input)
        log_stage_separator(logger)
        logger.info("[Storyboard] LLM Generate - Smart Merge")
        logger.info(
            "[Input] llm_provider=%s(%s) llm_model=%s",
            llm_runtime.provider_name,
            llm_runtime.provider_type,
            llm_runtime.model,
        )
        logger.info("[Input] script_mode=%s", script_mode)
        logger.info("[Input] existing_shot_count=%d", len(existing_shots))
        logger.info("[Input] video_provider=%s", video_provider)
        logger.info("[Input] video_model=%s", video_model)
        logger.info("[Input] video_mode=%s", video_mode)
        logger.info("[Input] prompt_max_duration_seconds=%.3f", prompt_max_duration_seconds)
        logger.info(
            "[Input] theoretical_max_duration_seconds=%.3f", theoretical_max_duration_seconds
        )
        logger.info("[Input] use_first_frame_ref=%s", use_first_frame_ref)
        logger.info("[Input] use_reference_image_ref=%s", use_reference_image_ref)
        logger.info(
            "[Input] target_language=%s(%s)",
            prompt_config["target_language"],
            prompt_config["target_language_label"],
        )
        logger.info(
            "[Input] prompt_complexity=%s(%s)",
            prompt_config["prompt_complexity"],
            prompt_config["prompt_complexity_label"],
        )
        logger.info(
            "[Input] system_prompt=%s",
            truncate_generation_text(SMART_MERGE_SYSTEM_PROMPT),
        )
        log_stage_separator(logger)

        payload, error = await self._generate_smart_merge_with_retry(
            db=db,
            stage=stage,
            provider=llm_runtime.provider,
            provider_name=llm_runtime.provider_name,
            provider_type=llm_runtime.provider_type,
            model=llm_runtime.model,
            prompt=prompt,
            existing_shots=existing_shots,
            shot_durations=shot_durations,
            allowed_reference_ids=allowed_reference_ids,
            reference_info=reference_info,
            title=title,
            script_mode=script_mode,
            prompt_config=prompt_config,
            max_duration_seconds=prompt_max_duration_seconds,
            use_first_frame_ref=use_first_frame_ref,
            use_reference_image_ref=use_reference_image_ref,
        )
        if payload is None:
            return StageResult(success=False, error=error or STORYBOARD_REQUIRED_ERROR)

        shots = self._finalize_shots(payload)
        warnings = self._collect_smart_merge_duration_warnings(
            shots=shots,
            theoretical_max_duration_seconds=theoretical_max_duration_seconds,
        )
        result_data = {
            "script_mode": script_mode,
            "shots": shots,
            "shot_count": len(shots),
            "references": reference_data.get("references", [])
            if isinstance(reference_data, dict)
            else [],
        }
        if warnings:
            result_data["warnings"] = warnings
            for warning in warnings:
                logger.warning("[Storyboard][SmartMerge] %s", warning)
        await self._apply_smart_merge_result(
            db=db,
            project_id=project.id,
            storyboard_payload=result_data,
        )
        logger.info("[Output] shots_summary=%s", _summarize_shots(shots))
        log_stage_separator(logger)
        return StageResult(success=True, data=result_data)

    async def _generate_with_retry(
        self,
        *,
        db: AsyncSession,
        stage: StageExecution,
        provider: Any,
        provider_name: str,
        provider_type: str,
        model: str,
        prompt: str,
        source_reference: str,
        dialogue_lines: list[dict[str, Any]],
        script_mode: str,
        allowed_reference_ids: set[str],
        only_shot_index: Any,
        existing_shots: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]] | None, str | None]:
        feedback: str | None = None
        for attempt in range(2):
            effective_prompt = prompt
            if feedback:
                effective_prompt = f"{prompt}\n\n上一次输出不合格，原因：{feedback}\n请完整重生成。"
            log_stage_separator(logger)
            logger.info(
                "[Storyboard] LLM Attempt %d/2 provider=%s(%s) model=%s",
                attempt + 1,
                provider_name,
                provider_type,
                model,
            )
            if feedback:
                logger.info("[Input] retry_feedback=%s", truncate_generation_text(feedback))
            logger.info("[Input] effective_prompt=%s", truncate_generation_text(effective_prompt))
            try:
                response_text = await self._generate_response_text_with_stream_retry(
                    db=db,
                    stage=stage,
                    provider=provider,
                    prompt=effective_prompt,
                    system_prompt=STORYBOARD_SYSTEM_PROMPT,
                    temperature=0.2,
                    log_prefix="[Storyboard]",
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("[Storyboard] LLM generate failed")
                return None, str(exc)
            try:
                result = self._parse_json_response_text(response_text)
            except Exception as exc:  # noqa: BLE001
                logger.exception("[Storyboard] Failed to parse streamed JSON response")
                return None, str(exc)
            logger.info("[Output] raw_result=%s", format_generation_json(result))

            shots, feedback = self._validate_and_normalize(
                result=result,
                source_reference=source_reference,
                dialogue_lines=dialogue_lines,
                script_mode=script_mode,
                allowed_reference_ids=allowed_reference_ids,
                only_shot_index=only_shot_index,
                existing_shots=existing_shots,
            )
            if shots is not None:
                logger.info("[Storyboard] validation=passed")
                log_stage_separator(logger)
                return shots, None
            logger.warning(
                "[Storyboard] validation=failed reason=%s", feedback or STORYBOARD_REQUIRED_ERROR
            )
            log_stage_separator(logger)
        return None, feedback or STORYBOARD_REQUIRED_ERROR

    async def _generate_smart_merge_with_retry(
        self,
        *,
        db: AsyncSession,
        stage: StageExecution,
        provider: Any,
        provider_name: str,
        provider_type: str,
        model: str,
        prompt: str,
        existing_shots: list[dict[str, Any]],
        shot_durations: dict[int, float],
        allowed_reference_ids: set[str],
        reference_info: str,
        title: str,
        script_mode: str,
        prompt_config: dict[str, str],
        max_duration_seconds: float,
        use_first_frame_ref: bool,
        use_reference_image_ref: bool,
    ) -> tuple[list[dict[str, Any]] | None, str | None]:
        feedback: str | None = None
        for attempt in range(2):
            effective_prompt = prompt
            if feedback:
                effective_prompt = f"{prompt}\n\n上一次输出不合格，原因：{feedback}\n请完整重生成。"
            log_stage_separator(logger)
            logger.info(
                "[Storyboard][SmartMerge] LLM Attempt %d/2 provider=%s(%s) model=%s",
                attempt + 1,
                provider_name,
                provider_type,
                model,
            )
            if feedback:
                logger.info("[Input] retry_feedback=%s", truncate_generation_text(feedback))
            logger.info("[Input] effective_prompt=%s", truncate_generation_text(effective_prompt))
            try:
                response_text = await self._generate_response_text_with_stream_retry(
                    db=db,
                    stage=stage,
                    provider=provider,
                    prompt=effective_prompt,
                    system_prompt=SMART_MERGE_SYSTEM_PROMPT,
                    temperature=0.2,
                    log_prefix="[Storyboard][SmartMerge]",
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("[Storyboard][SmartMerge] LLM generate failed")
                return None, str(exc)
            try:
                result = self._parse_json_response_text(response_text)
            except Exception as exc:  # noqa: BLE001
                logger.exception("[Storyboard][SmartMerge] Failed to parse streamed JSON response")
                return None, str(exc)
            logger.info("[Output] raw_result=%s", format_generation_json(result))

            repaired_result = result
            feedback = None
            for repair_round in range(6):
                shots, issue = self._validate_smart_merge_and_normalize_detailed(
                    result=repaired_result,
                    existing_shots=existing_shots,
                    shot_durations=shot_durations,
                    allowed_reference_ids=allowed_reference_ids,
                    use_first_frame_ref=use_first_frame_ref,
                    use_reference_image_ref=use_reference_image_ref,
                )
                if shots is not None:
                    logger.info("[Storyboard][SmartMerge] validation=passed")
                    log_stage_separator(logger)
                    return shots, None
                if issue is None:
                    break
                feedback = issue.message
                next_result, repair_note = await self._attempt_llm_repair_smart_merge_result(
                    db=db,
                    stage=stage,
                    provider=provider,
                    issue=issue,
                    result=repaired_result,
                    existing_shots=existing_shots,
                    shot_durations=shot_durations,
                    reference_info=reference_info,
                    title=title,
                    script_mode=script_mode,
                    prompt_config=prompt_config,
                    max_duration_seconds=max_duration_seconds,
                )
                if next_result is not None:
                    llm_repaired_shots, llm_repair_issue = (
                        self._validate_smart_merge_and_normalize_detailed(
                            result=next_result,
                            existing_shots=existing_shots,
                            shot_durations=shot_durations,
                            allowed_reference_ids=allowed_reference_ids,
                            use_first_frame_ref=use_first_frame_ref,
                            use_reference_image_ref=use_reference_image_ref,
                        )
                    )
                    if llm_repaired_shots is not None:
                        logger.info(
                            "[Storyboard][SmartMerge][LLMRepair] round=%d issue=%s note=%s",
                            repair_round + 1,
                            issue.code,
                            repair_note or "",
                        )
                        logger.info(
                            "[Storyboard][SmartMerge][Repair] patched_result=%s",
                            format_generation_json(next_result),
                        )
                        logger.info("[Storyboard][SmartMerge] validation=passed")
                        log_stage_separator(logger)
                        return llm_repaired_shots, None
                    issue = llm_repair_issue or issue
                    feedback = issue.message
                if next_result is None or feedback:
                    next_result, repair_note = self._repair_smart_merge_result(
                        result=repaired_result,
                        issue=issue,
                        existing_shots=existing_shots,
                        shot_durations=shot_durations,
                        allowed_reference_ids=allowed_reference_ids,
                        use_first_frame_ref=use_first_frame_ref,
                        use_reference_image_ref=use_reference_image_ref,
                    )
                    if next_result is None:
                        logger.warning(
                            "[Storyboard][SmartMerge] validation=failed reason=%s",
                            feedback or STORYBOARD_REQUIRED_ERROR,
                        )
                        break
                    repaired_result = next_result
                    logger.info(
                        "[Storyboard][SmartMerge][AutoRepair] round=%d issue=%s note=%s",
                        repair_round + 1,
                        issue.code,
                        repair_note or "",
                    )
                    logger.info(
                        "[Storyboard][SmartMerge][Repair] patched_result=%s",
                        format_generation_json(repaired_result),
                    )
            logger.warning(
                "[Storyboard][SmartMerge] validation=failed reason=%s",
                feedback or STORYBOARD_REQUIRED_ERROR,
            )
            log_stage_separator(logger)
        return None, feedback or STORYBOARD_REQUIRED_ERROR

    async def _generate_response_text_with_stream_retry(
        self,
        *,
        db: AsyncSession,
        stage: StageExecution,
        provider: Any,
        prompt: str,
        system_prompt: str,
        temperature: float,
        log_prefix: str,
    ) -> str:
        for stream_attempt in range(2):
            logger.info("%s LLM streaming enabled (%d/2)", log_prefix, stream_attempt + 1)
            chunks: list[str] = []
            chars_since_flush = 0
            try:
                async for chunk in provider.generate_stream(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                ):
                    text = str(chunk or "")
                    if not text:
                        continue
                    chunks.append(text)
                    chars_since_flush += len(text)
                    if chars_since_flush < 500:
                        continue
                    await self._persist_storyboard_stream_progress(
                        db=db,
                        stage=stage,
                        raw_text="".join(chunks),
                    )
                    chars_since_flush = 0
                response_text = "".join(chunks).strip()
                if "{" not in response_text or "}" not in response_text:
                    raise ValueError("流式响应未返回 JSON 对象")
                return response_text
            except Exception as stream_err:  # noqa: BLE001
                if stream_attempt == 0:
                    logger.warning(
                        "%s LLM stream failed (%r), retry streaming",
                        log_prefix,
                        stream_err,
                    )
                    await self._persist_storyboard_stream_fallback_progress(
                        db=db,
                        stage=stage,
                        fallback_message="流式中断，正在重试流式生成...",
                    )
                    continue
                logger.warning(
                    "%s LLM stream failed again (%r), abort generation",
                    log_prefix,
                    stream_err,
                )
                await self._persist_storyboard_stream_fallback_progress(
                    db=db,
                    stage=stage,
                    fallback_message="流式再次中断，已停止生成，请重试。",
                )
                raise RuntimeError("流式生成连续中断 2 次，已停止本次任务") from stream_err

        raise RuntimeError("流式生成未返回结果")

    def _validate_and_normalize(
        self,
        *,
        result: dict[str, Any],
        source_reference: str,
        dialogue_lines: list[dict[str, Any]],
        script_mode: str,
        allowed_reference_ids: set[str],
        only_shot_index: Any,
        existing_shots: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]] | None, str | None]:
        raw_shots = result.get("shots")
        if not isinstance(raw_shots, list) or not raw_shots:
            return None, "shots 数组为空"

        normalized: list[dict[str, Any]] = []
        for idx, item in enumerate(raw_shots):
            if not isinstance(item, dict):
                return None, f"第 {idx + 1} 个分镜不是对象"
            voice_content = str(item.get("voice_content") or "").strip()
            video_prompt = str(item.get("video_prompt") or "").strip()
            if not voice_content:
                return None, f"第 {idx + 1} 个分镜缺少 voice_content"
            if not video_prompt:
                return None, f"第 {idx + 1} 个分镜缺少 video_prompt"
            normalized.append(
                {
                    "shot_id": str(item.get("shot_id") or "").strip() or uuid4().hex,
                    "shot_index": idx,
                    "voice_content": voice_content,
                    "speaker_id": str(item.get("speaker_id") or "").strip()
                    or DEFAULT_SINGLE_ROLE_ID,
                    "speaker_name": str(item.get("speaker_name") or "").strip()
                    or str(item.get("speaker_id") or DEFAULT_SINGLE_ROLE_ID).strip()
                    or DEFAULT_SINGLE_ROLE_ID,
                    "video_prompt": video_prompt,
                    "video_reference_slots": normalize_reference_slots(
                        item.get("video_reference_slots"),
                        allowed_reference_ids=allowed_reference_ids or None,
                    ),
                    "metadata": item.get("metadata")
                    if isinstance(item.get("metadata"), dict)
                    else {},
                }
            )

        if only_shot_index is not None:
            if len(normalized) != 1:
                return None, "单分镜重生成时 shots 只能返回 1 条"
            if (
                not isinstance(only_shot_index, int)
                or only_shot_index < 0
                or only_shot_index >= len(existing_shots)
            ):
                return None, "目标分镜索引无效"
            current_voice = _normalize_text(
                str(existing_shots[only_shot_index].get("voice_content") or "")
            )
            next_voice = _normalize_text(normalized[0]["voice_content"])
            if current_voice != next_voice:
                if _similarity_ratio(current_voice, next_voice) < 0.75:
                    return None, "单分镜重生成时 voice_content 必须保持不变"
                normalized[0]["voice_content"] = str(
                    existing_shots[only_shot_index].get("voice_content") or ""
                )
            return normalized, None

        source_compact = _normalize_text(source_reference)
        generated_compact = _normalize_text("".join(item["voice_content"] for item in normalized))
        if not source_compact:
            return None, CONTENT_REQUIRED_ERROR
        if generated_compact != source_compact:
            resolved_voice_segments = _align_generated_segments_to_source(
                source_reference,
                [str(item["voice_content"]) for item in normalized],
            )
            if resolved_voice_segments is None:
                return None, "voice_content 没有完整按顺序覆盖原文"
            for item, resolved_voice_content in zip(
                normalized, resolved_voice_segments, strict=False
            ):
                item["voice_content"] = resolved_voice_content

        if dialogue_lines:
            normalized, speaker_error = _resolve_shot_speakers_from_dialogue_lines(
                normalized,
                dialogue_lines,
            )
            if normalized is None:
                return None, speaker_error or "speaker_id 无法映射回原始台词"
        for idx, shot in enumerate(normalized):
            if not shot["speaker_id"]:
                return None, f"第 {idx + 1} 个分镜缺少 speaker_id"

        return normalized, None

    def _smart_merge_issue(
        self,
        *,
        code: str,
        message: str,
        shot_index: int | None = None,
        source_indices: list[int] | None = None,
    ) -> SmartMergeValidationIssue:
        return SmartMergeValidationIssue(
            code=code,
            message=message,
            shot_index=shot_index,
            source_indices=list(source_indices) if source_indices else None,
        )

    @staticmethod
    def _compose_repaired_smart_merge_video_prompt(segment_shots: list[dict[str, Any]]) -> str:
        prompts = [str(item.get("video_prompt") or "").strip() for item in segment_shots]
        prompts = [item for item in prompts if item]
        if not prompts:
            return ""
        if len(prompts) == 1:
            return prompts[0]
        merged_parts: list[str] = []
        for idx, prompt in enumerate(prompts, start=1):
            prefix = f"镜头{idx}："
            merged_parts.append(prompt if prompt.startswith(prefix) else f"{prefix}{prompt}")
        return " ".join(merged_parts)

    def _build_repaired_smart_merge_shot(
        self,
        *,
        source_indices: list[int],
        existing_shots: list[dict[str, Any]],
        shot_durations: dict[int, float],
        allowed_reference_ids: set[str],
        original_slots: Any = None,
    ) -> dict[str, Any]:
        segment_shots = [existing_shots[source_index] for source_index in source_indices]
        base_shot = segment_shots[0]
        original_slot_list = normalize_reference_slots(
            original_slots,
            allowed_reference_ids=allowed_reference_ids or None,
        )
        reference_ids = _reference_slot_ids(original_slot_list)
        if not reference_ids:
            reference_ids = _reference_slot_ids(base_shot.get("video_reference_slots"))
            reference_ids = [item for item in reference_ids if item in allowed_reference_ids]

        base_slots = normalize_reference_slots(
            base_shot.get("video_reference_slots"),
            allowed_reference_ids=allowed_reference_ids or None,
        )
        return {
            "shot_index": 0,
            "source_shot_indices": list(source_indices),
            "voice_content": "".join(
                str(item.get("voice_content") or "") for item in segment_shots
            ).strip(),
            "speaker_id": str(base_shot.get("speaker_id") or "").strip() or DEFAULT_SINGLE_ROLE_ID,
            "speaker_name": str(base_shot.get("speaker_name") or "").strip()
            or str(base_shot.get("speaker_id") or DEFAULT_SINGLE_ROLE_ID).strip()
            or DEFAULT_SINGLE_ROLE_ID,
            "video_prompt": self._compose_repaired_smart_merge_video_prompt(segment_shots),
            "video_reference_slots": build_reference_slots_from_ids(
                reference_ids,
                original_slot_list or base_slots,
            ),
            "metadata": self._build_smart_merge_metadata(
                source_indices=source_indices,
                segment_shots=segment_shots,
                shot_durations=shot_durations,
                merged_duration_seconds=sum(
                    max(float(shot_durations.get(source_index, 0.0) or 0.0), 0.0)
                    for source_index in source_indices
                ),
            ),
        }

    @staticmethod
    def _split_source_indices_by_speaker(
        source_indices: list[int],
        existing_shots: list[dict[str, Any]],
    ) -> list[list[int]]:
        groups: list[list[int]] = []
        current_group: list[int] = []
        current_speaker = ""
        for source_index in source_indices:
            speaker_id = (
                str(existing_shots[source_index].get("speaker_id") or "").strip()
                or DEFAULT_SINGLE_ROLE_ID
            )
            if current_group and speaker_id != current_speaker:
                groups.append(current_group)
                current_group = []
            current_group.append(source_index)
            current_speaker = speaker_id
        if current_group:
            groups.append(current_group)
        return groups

    def _split_source_indices_by_reference_growth(
        self,
        source_indices: list[int],
        existing_shots: list[dict[str, Any]],
    ) -> list[list[int]]:
        groups: list[list[int]] = []
        current_group: list[int] = []
        previous_refs: set[str] | None = None
        for source_index in source_indices:
            current_refs = set(
                _reference_slot_ids(existing_shots[source_index].get("video_reference_slots"))
            )
            if (
                current_group
                and previous_refs is not None
                and not current_refs.issubset(previous_refs)
            ):
                groups.append(current_group)
                current_group = []
            current_group.append(source_index)
            previous_refs = current_refs
        if current_group:
            groups.append(current_group)
        return groups

    @staticmethod
    def _extract_source_indices_from_raw_smart_merge_shot(raw_item: Any) -> list[int]:
        if not isinstance(raw_item, dict):
            return []
        raw_indices = raw_item.get("source_shot_indices")
        if not isinstance(raw_indices, list):
            return []
        return [int(item) for item in raw_indices if isinstance(item, int)]

    def _resolve_smart_merge_repair_window(
        self,
        *,
        result: dict[str, Any],
        issue: SmartMergeValidationIssue,
        existing_shots: list[dict[str, Any]],
    ) -> tuple[int, int, int, int] | None:
        raw_shots = result.get("shots")
        if not isinstance(raw_shots, list) or not raw_shots:
            return None

        if issue.shot_index is not None:
            merged_start = max(0, issue.shot_index - 1)
            merged_end = min(len(raw_shots) - 1, issue.shot_index + 1)
        else:
            merged_start = 0
            merged_end = len(raw_shots) - 1

        source_indices = list(issue.source_indices or [])
        if not source_indices:
            for item in raw_shots[merged_start : merged_end + 1]:
                source_indices.extend(self._extract_source_indices_from_raw_smart_merge_shot(item))
        if not source_indices:
            return 0, len(raw_shots) - 1, 0, len(existing_shots) - 1

        source_start = max(0, min(source_indices) - 1)
        source_end = min(len(existing_shots) - 1, max(source_indices) + 1)
        return merged_start, merged_end, source_start, source_end

    def _merge_smart_merge_repair_window(
        self,
        *,
        result: dict[str, Any],
        merged_start: int,
        merged_end: int,
        repaired_window_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        raw_shots = result.get("shots")
        repaired_shots = (
            repaired_window_result.get("shots")
            if isinstance(repaired_window_result, dict)
            else None
        )
        if not isinstance(raw_shots, list) or not isinstance(repaired_shots, list):
            return None
        next_raw_shots = list(raw_shots)
        next_raw_shots[merged_start : merged_end + 1] = repaired_shots
        return {"shots": next_raw_shots}

    async def _attempt_llm_repair_smart_merge_result(
        self,
        *,
        db: AsyncSession,
        stage: StageExecution,
        provider: Any,
        issue: SmartMergeValidationIssue,
        result: dict[str, Any],
        existing_shots: list[dict[str, Any]],
        shot_durations: dict[int, float],
        reference_info: str,
        title: str,
        script_mode: str,
        prompt_config: dict[str, str],
        max_duration_seconds: float,
    ) -> tuple[dict[str, Any] | None, str | None]:
        repair_window = self._resolve_smart_merge_repair_window(
            result=result,
            issue=issue,
            existing_shots=existing_shots,
        )
        if repair_window is None:
            return None, None
        merged_start, merged_end, source_start, source_end = repair_window

        raw_shots = result.get("shots")
        if not isinstance(raw_shots, list):
            return None, None

        merged_window_shots = [
            dict(item)
            for item in raw_shots[merged_start : merged_end + 1]
            if isinstance(item, dict)
        ]
        source_window_indices = list(range(source_start, source_end + 1))
        source_window_shots = [dict(existing_shots[index]) for index in source_window_indices]
        source_window_durations = {
            index: shot_durations.get(index, 0.0) for index in source_window_indices
        }
        current_window_durations: dict[int, float] = {}
        for offset, shot in enumerate(merged_window_shots):
            source_indices = self._extract_source_indices_from_raw_smart_merge_shot(shot)
            current_window_durations[merged_start + offset] = sum(
                max(float(shot_durations.get(source_index, 0.0) or 0.0), 0.0)
                for source_index in source_indices
            )

        repair_prompt = build_storyboard_smart_merge_repair_prompt(
            script_mode=script_mode,
            title=title,
            reference_info=reference_info,
            issue_message=issue.message,
            current_window_display=_build_smart_merge_window_display(
                shots=merged_window_shots,
                shot_durations=current_window_durations,
                original_indices=list(range(merged_start, merged_start + len(merged_window_shots))),
                include_reference_slots=True,
            ),
            source_window_display=_build_smart_merge_window_display(
                shots=source_window_shots,
                shot_durations=source_window_durations,
                original_indices=source_window_indices,
                include_reference_slots=True,
            ),
            max_duration_seconds=max_duration_seconds,
            target_language=prompt_config["target_language"],
            target_language_label=prompt_config["target_language_label"],
            prompt_complexity=prompt_config["prompt_complexity"],
            prompt_complexity_label=prompt_config["prompt_complexity_label"],
            video_prompt_length_requirement=prompt_config["video_prompt_length_requirement"],
        )

        logger.info(
            "[Storyboard][SmartMerge][LLMRepair] issue=%s merged_window=%s-%s source_window=%s-%s",
            issue.code,
            merged_start,
            merged_end,
            source_start,
            source_end,
        )
        logger.info(
            "[Storyboard][SmartMerge][LLMRepair] prompt=%s",
            truncate_generation_text(repair_prompt),
        )

        try:
            response_text = await self._generate_response_text_with_stream_retry(
                db=db,
                stage=stage,
                provider=provider,
                prompt=repair_prompt,
                system_prompt=SMART_MERGE_SYSTEM_PROMPT,
                temperature=0.2,
                log_prefix="[Storyboard][SmartMerge][LLMRepair]",
            )
            repaired_window_result = self._parse_json_response_text(response_text)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[Storyboard][SmartMerge][LLMRepair] failed issue=%s error=%r",
                issue.code,
                exc,
            )
            return None, None

        patched = self._merge_smart_merge_repair_window(
            result=result,
            merged_start=merged_start,
            merged_end=merged_end,
            repaired_window_result=repaired_window_result,
        )
        if patched is None:
            return None, None
        return patched, f"llm repaired {issue.code}"

    def _repair_smart_merge_result(
        self,
        *,
        result: dict[str, Any],
        issue: SmartMergeValidationIssue,
        existing_shots: list[dict[str, Any]],
        shot_durations: dict[int, float],
        allowed_reference_ids: set[str],
        use_first_frame_ref: bool,
        use_reference_image_ref: bool,
    ) -> tuple[dict[str, Any] | None, str | None]:
        raw_shots = result.get("shots")
        if not isinstance(raw_shots, list):
            return None, None

        if issue.code in {
            "missing_video_prompt",
            "missing_voice_content",
            "voice_mismatch",
            "invalid_reference_slot",
        }:
            if issue.shot_index is None or issue.source_indices is None:
                return None, None
            if issue.shot_index < 0 or issue.shot_index >= len(raw_shots):
                return None, None
            next_raw_shots = list(raw_shots)
            next_raw_shots[issue.shot_index] = self._build_repaired_smart_merge_shot(
                source_indices=issue.source_indices,
                existing_shots=existing_shots,
                shot_durations=shot_durations,
                allowed_reference_ids=allowed_reference_ids,
                original_slots=(
                    next_raw_shots[issue.shot_index].get("video_reference_slots")
                    if isinstance(next_raw_shots[issue.shot_index], dict)
                    else None
                ),
            )
            return {"shots": next_raw_shots}, f"repaired {issue.code}"

        if issue.code == "cross_speaker_merge":
            if issue.shot_index is None or issue.source_indices is None:
                return None, None
            split_groups = self._split_source_indices_by_speaker(
                issue.source_indices, existing_shots
            )
            next_raw_shots = list(raw_shots)
            original_item = (
                next_raw_shots[issue.shot_index] if issue.shot_index < len(next_raw_shots) else {}
            )
            replacement = [
                self._build_repaired_smart_merge_shot(
                    source_indices=group,
                    existing_shots=existing_shots,
                    shot_durations=shot_durations,
                    allowed_reference_ids=allowed_reference_ids,
                    original_slots=(
                        original_item.get("video_reference_slots")
                        if isinstance(original_item, dict)
                        else None
                    ),
                )
                for group in split_groups
            ]
            next_raw_shots[issue.shot_index : issue.shot_index + 1] = replacement
            return {"shots": next_raw_shots}, "split cross-speaker segment"

        if issue.code == "reference_growth" and use_first_frame_ref and not use_reference_image_ref:
            if issue.shot_index is None or issue.source_indices is None:
                return None, None
            split_groups = self._split_source_indices_by_reference_growth(
                issue.source_indices,
                existing_shots,
            )
            next_raw_shots = list(raw_shots)
            original_item = (
                next_raw_shots[issue.shot_index] if issue.shot_index < len(next_raw_shots) else {}
            )
            replacement = [
                self._build_repaired_smart_merge_shot(
                    source_indices=group,
                    existing_shots=existing_shots,
                    shot_durations=shot_durations,
                    allowed_reference_ids=allowed_reference_ids,
                    original_slots=(
                        original_item.get("video_reference_slots")
                        if isinstance(original_item, dict)
                        else None
                    ),
                )
                for group in split_groups
            ]
            next_raw_shots[issue.shot_index : issue.shot_index + 1] = replacement
            return {"shots": next_raw_shots}, "split reference-growth segment"

        if issue.code in {"coverage_mismatch", "global_voice_mismatch"}:
            rebuilt: list[dict[str, Any]] = []
            used_indices: set[int] = set()
            for raw_item in raw_shots:
                if not isinstance(raw_item, dict):
                    continue
                raw_indices = raw_item.get("source_shot_indices")
                if not isinstance(raw_indices, list) or not raw_indices:
                    continue
                if not all(isinstance(item, int) for item in raw_indices):
                    continue
                source_indices = [int(item) for item in raw_indices]
                if source_indices != list(range(source_indices[0], source_indices[-1] + 1)):
                    continue
                if source_indices[0] < 0 or source_indices[-1] >= len(existing_shots):
                    continue
                if any(item in used_indices for item in source_indices):
                    continue
                rebuilt.append(
                    self._build_repaired_smart_merge_shot(
                        source_indices=source_indices,
                        existing_shots=existing_shots,
                        shot_durations=shot_durations,
                        allowed_reference_ids=allowed_reference_ids,
                        original_slots=raw_item.get("video_reference_slots"),
                    )
                )
                used_indices.update(source_indices)
            for source_index in range(len(existing_shots)):
                if source_index in used_indices:
                    continue
                rebuilt.append(
                    self._build_repaired_smart_merge_shot(
                        source_indices=[source_index],
                        existing_shots=existing_shots,
                        shot_durations=shot_durations,
                        allowed_reference_ids=allowed_reference_ids,
                        original_slots=existing_shots[source_index].get("video_reference_slots"),
                    )
                )
            rebuilt.sort(
                key=lambda item: (
                    item.get("source_shot_indices", [10**9])[0]
                    if isinstance(item.get("source_shot_indices"), list)
                    and item.get("source_shot_indices")
                    else 10**9
                )
            )
            return {"shots": rebuilt}, f"rebuilt result for {issue.code}"

        return None, None

    def _validate_smart_merge_and_normalize_detailed(
        self,
        *,
        result: dict[str, Any],
        existing_shots: list[dict[str, Any]],
        shot_durations: dict[int, float],
        allowed_reference_ids: set[str],
        use_first_frame_ref: bool,
        use_reference_image_ref: bool,
    ) -> tuple[list[dict[str, Any]] | None, SmartMergeValidationIssue | None]:
        raw_shots = result.get("shots")
        if not isinstance(raw_shots, list) or not raw_shots:
            return None, self._smart_merge_issue(code="empty_shots", message="shots 数组为空")

        normalized: list[dict[str, Any]] = []
        consumed_indices: list[int] = []
        expected_source_count = len(existing_shots)

        for idx, item in enumerate(raw_shots):
            if not isinstance(item, dict):
                return None, self._smart_merge_issue(
                    code="shot_not_object",
                    message=f"第 {idx + 1} 个合并分镜不是对象",
                    shot_index=idx,
                )
            video_prompt = str(item.get("video_prompt") or "").strip()
            voice_content = str(item.get("voice_content") or "").strip()
            if not video_prompt:
                return None, self._smart_merge_issue(
                    code="missing_video_prompt",
                    message=f"第 {idx + 1} 个合并分镜缺少 video_prompt",
                    shot_index=idx,
                )
            if not voice_content:
                return None, self._smart_merge_issue(
                    code="missing_voice_content",
                    message=f"第 {idx + 1} 个合并分镜缺少 voice_content",
                    shot_index=idx,
                )

            raw_source_indices = item.get("source_shot_indices")
            if not isinstance(raw_source_indices, list) or not raw_source_indices:
                return None, self._smart_merge_issue(
                    code="missing_source_indices",
                    message=f"第 {idx + 1} 个合并分镜缺少 source_shot_indices",
                    shot_index=idx,
                )

            source_indices: list[int] = []
            for raw_value in raw_source_indices:
                if not isinstance(raw_value, int):
                    return None, self._smart_merge_issue(
                        code="invalid_source_indices_type",
                        message=f"第 {idx + 1} 个合并分镜的 source_shot_indices 必须是整数",
                        shot_index=idx,
                    )
                source_indices.append(raw_value)
            if sorted(source_indices) != list(range(min(source_indices), max(source_indices) + 1)):
                return None, self._smart_merge_issue(
                    code="non_contiguous_source_indices",
                    message=f"第 {idx + 1} 个合并分镜只能引用连续原分镜",
                    shot_index=idx,
                    source_indices=source_indices,
                )
            if source_indices[0] < 0 or source_indices[-1] >= expected_source_count:
                return None, self._smart_merge_issue(
                    code="source_indices_out_of_range",
                    message=f"第 {idx + 1} 个合并分镜引用了越界分镜",
                    shot_index=idx,
                    source_indices=source_indices,
                )

            segment_shots = [existing_shots[source_index] for source_index in source_indices]
            segment_voice = "".join(
                str(shot.get("voice_content") or "") for shot in segment_shots
            ).strip()
            if _normalize_text(segment_voice) != _normalize_text(voice_content):
                return None, self._smart_merge_issue(
                    code="voice_mismatch",
                    message=f"第 {idx + 1} 个合并分镜的 voice_content 必须与原连续分镜拼接一致",
                    shot_index=idx,
                    source_indices=source_indices,
                )

            speaker_ids = {
                str(shot.get("speaker_id") or "").strip() or DEFAULT_SINGLE_ROLE_ID
                for shot in segment_shots
            }
            if len(speaker_ids) != 1:
                return None, self._smart_merge_issue(
                    code="cross_speaker_merge",
                    message=f"第 {idx + 1} 个合并分镜跨 speaker_id 合并",
                    shot_index=idx,
                    source_indices=source_indices,
                )

            merged_duration_seconds = sum(
                max(float(shot_durations.get(source_index, 0.0) or 0.0), 0.0)
                for source_index in source_indices
            )
            if merged_duration_seconds <= 0:
                return None, self._smart_merge_issue(
                    code="missing_duration",
                    message=f"第 {idx + 1} 个合并分镜缺少有效音频时长",
                    shot_index=idx,
                    source_indices=source_indices,
                )

            if use_first_frame_ref and not use_reference_image_ref:
                if not self._segment_respects_first_frame_reference_constraint(
                    existing_shots=existing_shots,
                    source_indices=source_indices,
                ):
                    return None, self._smart_merge_issue(
                        code="reference_growth",
                        message=f"第 {idx + 1} 个合并分镜违反首帧参考递减约束",
                        shot_index=idx,
                        source_indices=source_indices,
                    )

            base_shot = segment_shots[0]
            normalized.append(
                {
                    "shot_id": uuid4().hex,
                    "shot_index": idx,
                    "voice_content": segment_voice,
                    "speaker_id": str(base_shot.get("speaker_id") or "").strip()
                    or DEFAULT_SINGLE_ROLE_ID,
                    "speaker_name": str(base_shot.get("speaker_name") or "").strip()
                    or str(base_shot.get("speaker_id") or DEFAULT_SINGLE_ROLE_ID).strip()
                    or DEFAULT_SINGLE_ROLE_ID,
                    "video_prompt": video_prompt,
                    "video_reference_slots": normalize_reference_slots(
                        item.get("video_reference_slots"),
                        allowed_reference_ids=allowed_reference_ids or None,
                    ),
                    "metadata": self._build_smart_merge_metadata(
                        source_indices=source_indices,
                        segment_shots=segment_shots,
                        shot_durations=shot_durations,
                        merged_duration_seconds=merged_duration_seconds,
                    ),
                }
            )
            consumed_indices.extend(source_indices)

        if consumed_indices != list(range(expected_source_count)):
            return None, self._smart_merge_issue(
                code="coverage_mismatch",
                message="合并结果必须完整覆盖全部原分镜且顺序不能变化",
            )

        generated_compact = _normalize_text("".join(item["voice_content"] for item in normalized))
        original_compact = _normalize_text(
            "".join(str(item.get("voice_content") or "") for item in existing_shots)
        )
        if generated_compact != original_compact:
            return None, self._smart_merge_issue(
                code="global_voice_mismatch",
                message="合并后的 voice_content 没有完整按顺序覆盖原分镜",
            )

        for idx, shot in enumerate(normalized):
            reference_ids = set(_reference_slot_ids(shot.get("video_reference_slots")))
            if not reference_ids.issubset(allowed_reference_ids):
                return None, self._smart_merge_issue(
                    code="invalid_reference_slot",
                    message=f"第 {idx + 1} 个合并分镜使用了不可用参考",
                    shot_index=idx,
                    source_indices=(
                        shot.get("metadata", {}).get("smart_merge", {}).get("source_shot_indices")
                        if isinstance(shot.get("metadata"), dict)
                        else None
                    ),
                )

        return normalized, None

    def _validate_smart_merge_and_normalize(
        self,
        *,
        result: dict[str, Any],
        existing_shots: list[dict[str, Any]],
        shot_durations: dict[int, float],
        allowed_reference_ids: set[str],
        use_first_frame_ref: bool,
        use_reference_image_ref: bool,
    ) -> tuple[list[dict[str, Any]] | None, str | None]:
        normalized, issue = self._validate_smart_merge_and_normalize_detailed(
            result=result,
            existing_shots=existing_shots,
            shot_durations=shot_durations,
            allowed_reference_ids=allowed_reference_ids,
            use_first_frame_ref=use_first_frame_ref,
            use_reference_image_ref=use_reference_image_ref,
        )
        return normalized, issue.message if issue else None

    @staticmethod
    def _collect_smart_merge_duration_warnings(
        *,
        shots: list[dict[str, Any]],
        theoretical_max_duration_seconds: float,
    ) -> list[str]:
        limit = max(0.0, float(theoretical_max_duration_seconds or 0.0))
        if limit <= 0:
            return []
        warning_threshold = limit * SMART_MERGE_THEORETICAL_WARNING_RATIO
        warnings: list[str] = []
        for idx, shot in enumerate(shots):
            metadata = shot.get("metadata")
            smart_merge_meta = metadata.get("smart_merge") if isinstance(metadata, dict) else None
            merged_duration_seconds = (
                float(smart_merge_meta.get("merged_duration_seconds") or 0.0)
                if isinstance(smart_merge_meta, dict)
                else 0.0
            )
            if merged_duration_seconds <= warning_threshold + 1e-6:
                continue
            warnings.append(
                f"第 {idx + 1} 个合并分镜时长 {merged_duration_seconds:.3f}s，"
                f"超过了理论单次运行上限较多（理论上限 {limit:.3f}s）"
            )
        return warnings

    @staticmethod
    def _finalize_shots(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
        finalized: list[dict[str, Any]] = []
        for idx, shot in enumerate(shots):
            item = dict(shot)
            item["shot_id"] = str(item.get("shot_id") or "").strip() or uuid4().hex
            item["shot_index"] = idx
            item["video_reference_slots"] = normalize_reference_slots(
                item.get("video_reference_slots")
            )
            finalized.append(item)
        return finalized

    @staticmethod
    def _build_audio_duration_map(
        *,
        shots: list[dict[str, Any]],
        audio_data: dict[str, Any] | None,
    ) -> tuple[dict[int, float], str | None]:
        if not isinstance(audio_data, dict):
            return {}, "当前分镜缺少音频结果，无法智能合并"
        raw_assets = audio_data.get("audio_assets")
        if not isinstance(raw_assets, list) or len(raw_assets) < len(shots):
            return {}, "当前分镜音频不完整，无法智能合并"

        by_index: dict[int, float] = {}
        for item in raw_assets:
            if not isinstance(item, dict):
                continue
            shot_index = item.get("shot_index")
            if not isinstance(shot_index, int) or shot_index < 0:
                continue
            try:
                duration = float(item.get("duration") or 0.0)
            except (TypeError, ValueError):
                duration = 0.0
            if duration > 0:
                by_index[shot_index] = duration

        missing = [idx for idx in range(len(shots)) if by_index.get(idx, 0.0) <= 0]
        if missing:
            return (
                {},
                f"分镜音频时长不完整，缺少分镜: {', '.join(str(idx + 1) for idx in missing[:5])}",
            )
        return by_index, None

    @staticmethod
    def _resolve_smart_merge_video_context(
        stage_input: dict[str, Any],
    ) -> tuple[str, str, str, float | None]:
        provider = str(stage_input.get("video_provider") or "").strip().lower()
        use_first_frame_ref = bool(stage_input.get("use_first_frame_ref", False))
        mode = "i2v" if use_first_frame_ref else "t2v"
        if provider == "wan2gp":
            model = str(
                stage_input.get(
                    "video_wan2gp_i2v_preset" if mode == "i2v" else "video_wan2gp_t2v_preset"
                )
                or ""
            ).strip()
            limit = get_theoretical_single_generation_limit_seconds(provider, model, mode)
            return provider, model, mode, limit

        model = str(stage_input.get("video_model") or "").strip()
        limit = get_theoretical_single_generation_limit_seconds(provider, model, mode)
        return provider, model, mode, limit

    @staticmethod
    def _resolve_smart_merge_prompt_duration_limit(max_duration_seconds: float) -> float:
        safe_limit = max(0.0, float(max_duration_seconds or 0.0))
        if safe_limit <= 0:
            return safe_limit
        return min(SMART_MERGE_MAX_DURATION_CAP_SECONDS, safe_limit)

    def _build_smart_merge_prompt(
        self,
        *,
        title: str,
        script_mode: str,
        shots: list[dict[str, Any]],
        shot_durations: dict[int, float],
        reference_info: str,
        video_provider: str,
        video_model: str,
        video_mode: str,
        max_duration_seconds: float,
        use_first_frame_ref: bool,
        use_reference_image_ref: bool,
        prompt_config: dict[str, str],
    ) -> str:
        shot_count = max(1, len(shots))
        total_duration_seconds = sum(
            max(0.0, float(shot_durations.get(index, 0.0) or 0.0)) for index in range(len(shots))
        )
        average_duration_seconds = total_duration_seconds / shot_count
        minimum_shot_count = max(
            1,
            math.ceil(total_duration_seconds / max_duration_seconds)
            if max_duration_seconds > 0
            else shot_count,
        )
        recommended_min_shot_count = max(
            minimum_shot_count,
            math.ceil(total_duration_seconds / max(max_duration_seconds * 0.85, 0.001)),
        )
        recommended_max_shot_count = max(
            recommended_min_shot_count,
            min(
                shot_count,
                math.ceil(total_duration_seconds / max(max_duration_seconds * 0.65, 0.001)),
            ),
        )
        return build_storyboard_smart_merge_prompt(
            script_mode=script_mode,
            title=title,
            reference_info=reference_info,
            shots_display=_build_smart_merge_shots_display(shots, shot_durations),
            total_duration_seconds=total_duration_seconds,
            shot_count=shot_count,
            average_duration_seconds=average_duration_seconds,
            minimum_shot_count=minimum_shot_count,
            recommended_min_shot_count=recommended_min_shot_count,
            recommended_max_shot_count=recommended_max_shot_count,
            video_provider=video_provider,
            video_model=video_model,
            video_mode=video_mode,
            max_duration_seconds=max_duration_seconds,
            use_first_frame_ref=use_first_frame_ref,
            use_reference_image_ref=use_reference_image_ref,
            target_language=prompt_config["target_language"],
            target_language_label=prompt_config["target_language_label"],
            prompt_complexity=prompt_config["prompt_complexity"],
            prompt_complexity_label=prompt_config["prompt_complexity_label"],
            video_prompt_length_requirement=prompt_config["video_prompt_length_requirement"],
        )

    @staticmethod
    def _segment_respects_first_frame_reference_constraint(
        *,
        existing_shots: list[dict[str, Any]],
        source_indices: list[int],
    ) -> bool:
        if len(source_indices) <= 1:
            return True
        previous: set[str] | None = None
        for source_index in source_indices:
            current = set(
                _reference_slot_ids(existing_shots[source_index].get("video_reference_slots"))
            )
            if previous is not None and not current.issubset(previous):
                return False
            previous = current
        return True

    @staticmethod
    def _build_smart_merge_metadata(
        *,
        source_indices: list[int],
        segment_shots: list[dict[str, Any]],
        shot_durations: dict[int, float],
        merged_duration_seconds: float,
    ) -> dict[str, Any]:
        return {
            "smart_merge": {
                "source_shot_indices": source_indices,
                "source_shot_ids": [
                    str(shot.get("shot_id") or "").strip() or f"shot_{source_indices[idx] + 1}"
                    for idx, shot in enumerate(segment_shots)
                ],
                "source_duration_seconds": [
                    float(shot_durations.get(source_index, 0.0) or 0.0)
                    for source_index in source_indices
                ],
                "merged_duration_seconds": float(merged_duration_seconds),
            }
        }

    @staticmethod
    async def _apply_smart_merge_result(
        *,
        db: AsyncSession,
        project_id: int,
        storyboard_payload: dict[str, Any],
    ) -> None:
        from app.services.stage_service import StageService

        service = StageService(db)
        await service.replace_storyboard_and_clear_downstream(
            project_id,
            storyboard_payload=storyboard_payload,
        )

    def _build_prompt(
        self,
        *,
        script_mode: str,
        title: str,
        source_display: str,
        reference_info: str,
        shot_plan_note: str,
        only_shot_index: Any,
        existing_shots: list[dict[str, Any]],
        prompt_config: dict[str, str],
    ) -> str:
        if (
            only_shot_index is not None
            and isinstance(only_shot_index, int)
            and 0 <= only_shot_index < len(existing_shots)
        ):
            shot = existing_shots[only_shot_index]
            return build_storyboard_regenerate_prompt(
                script_mode=script_mode,
                title=title,
                reference_info=reference_info,
                shot=shot,
                only_shot_index=only_shot_index,
                target_language=prompt_config["target_language"],
                target_language_label=prompt_config["target_language_label"],
                prompt_complexity=prompt_config["prompt_complexity"],
                prompt_complexity_label=prompt_config["prompt_complexity_label"],
                video_prompt_length_requirement=prompt_config["video_prompt_length_requirement"],
            )

        return build_storyboard_prompt(
            script_mode=script_mode,
            title=title,
            source_display=source_display,
            reference_info=reference_info,
            shot_plan_note=shot_plan_note,
            target_language=prompt_config["target_language"],
            target_language_label=prompt_config["target_language_label"],
            prompt_complexity=prompt_config["prompt_complexity"],
            prompt_complexity_label=prompt_config["prompt_complexity_label"],
            video_prompt_length_requirement=prompt_config["video_prompt_length_requirement"],
        )

    @staticmethod
    def _normalize_storyboard_shot_density(value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in STORYBOARD_SHOT_DENSITY_CONFIG:
            return normalized
        return "medium"

    def _build_shot_plan_guidance(
        self, *, source_reference: str, input_data: dict[str, Any]
    ) -> str:
        density_key = self._normalize_storyboard_shot_density(
            input_data.get("storyboard_shot_density")
        )
        density_cfg = STORYBOARD_SHOT_DENSITY_CONFIG[density_key]
        char_count = _estimate_source_char_count(source_reference)
        estimated_total_seconds = max(3, math.ceil(char_count / 5.0)) if char_count > 0 else 3
        avg_shot_seconds = float(density_cfg["avg_shot_seconds"])
        min_shot_seconds = float(density_cfg["min_shot_seconds"])
        max_shot_seconds = float(density_cfg["max_shot_seconds"])
        target_shot_count = max(1, round(estimated_total_seconds / avg_shot_seconds))
        min_shot_count = max(1, math.ceil(estimated_total_seconds / max_shot_seconds))
        max_shot_count = max(min_shot_count, math.ceil(estimated_total_seconds / min_shot_seconds))
        density_label = str(density_cfg["label"])
        return (
            f"原始文案净字数约 {char_count} 字；按中文短视频口播约 5.0 字/秒估算，"
            f"整条视频时长约 {estimated_total_seconds} 秒。\n"
            f"用户要求的镜头密度为 {density_label}；建议单镜头时长约 "
            f"{min_shot_seconds:.1f}-{max_shot_seconds:.1f} 秒。\n"
            f"据此，建议本次规划控制在约 {target_shot_count} 个分镜，"
            f"合理浮动范围约 {min_shot_count}-{max_shot_count} 个。\n"
            "请尽量贴近该镜头数量进行规划；如果因为主体/可见参考集合变化必须拆分，"
            "可以在该范围内微调，但不要明显偏离。"
        )

    async def _get_content_data(self, db: AsyncSession, project: Project) -> dict[str, Any] | None:
        return await get_latest_stage_output(db, project.id, StageType.CONTENT)

    async def _get_reference_data(
        self, db: AsyncSession, project: Project
    ) -> dict[str, Any] | None:
        result = await db.execute(
            select(StageExecution)
            .where(
                StageExecution.project_id == project.id,
                StageExecution.stage_type == StageType.REFERENCE,
            )
            .order_by(StageExecution.updated_at.desc(), StageExecution.id.desc())
        )
        for reference_stage in result.scalars():
            if isinstance(reference_stage.output_data, dict):
                return reference_stage.output_data
        return None

    @staticmethod
    def _has_usable_reference_image(item: dict[str, Any]) -> bool:
        file_path = str(item.get("file_path") or "").strip()
        if not file_path:
            return False
        resolved = resolve_path_for_io(file_path)
        if resolved is None:
            return False
        return resolved.is_file()

    @staticmethod
    def _format_duo_seat_side(value: Any, default: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"left", "左", "左侧"}:
            return "左"
        if normalized in {"right", "右", "右侧"}:
            return "右"
        return default

    @classmethod
    def _build_reference_info(
        cls,
        reference_data: dict[str, Any] | None,
        *,
        script_mode: str,
        content_data: dict[str, Any] | None = None,
    ) -> tuple[str, set[str]]:
        if not isinstance(reference_data, dict):
            return "无可用参考；若不需要参考，video_reference_slots 返回 []。", set()

        references = reference_data.get("references")
        reference_images = reference_data.get("reference_images")
        image_ids = {
            str(item.get("id") or "").strip()
            for item in reference_images or []
            if (
                isinstance(item, dict)
                and str(item.get("id") or "").strip()
                and StoryboardHandler._has_usable_reference_image(item)
            )
        }
        lines: list[str] = []
        allowed_ids: set[str] = set()
        for item in references or []:
            if not isinstance(item, dict):
                continue
            ref_id = str(item.get("id") or "").strip()
            if not ref_id or ref_id not in image_ids:
                continue
            allowed_ids.add(ref_id)
            name = str(item.get("name") or "").strip() or ref_id
            setting = str(item.get("setting") or "").strip()
            summary = setting or "无设定"
            lines.append(f"- {ref_id}: {name} | {summary}")

        if str(script_mode or "").strip().lower() == "duo_podcast":
            reference_by_id = {
                str(item.get("id") or "").strip(): item
                for item in references or []
                if isinstance(item, dict) and str(item.get("id") or "").strip()
            }
            content_roles = (
                content_data.get("roles")
                if isinstance(content_data, dict) and isinstance(content_data.get("roles"), list)
                else []
            )
            role_1 = next(
                (
                    role
                    for role in content_roles
                    if str(role.get("id") or "").strip() == DUO_ROLE_1_ID
                ),
                {},
            )
            role_2 = next(
                (
                    role
                    for role in content_roles
                    if str(role.get("id") or "").strip() == DUO_ROLE_2_ID
                ),
                {},
            )

            def _build_duo_role_line(
                *,
                role: dict[str, Any],
                default_name: str,
                default_description: str,
                default_seat: str,
            ) -> str | None:
                role_name = str(role.get("name") or "").strip() or default_name
                role_description = str(role.get("description") or "").strip() or default_description
                seat_label = cls._format_duo_seat_side(role.get("seat_side"), default_seat)
                reference_id = str(role.get("id") or "").strip()
                if not reference_id or reference_id not in image_ids:
                    return None
                reference_item = reference_by_id.get(reference_id, {})
                reference_summary = (
                    str(reference_item.get("setting") or "").strip()
                    or str(reference_item.get("appearance_description") or "").strip()
                    or role_description
                )
                return f"- {reference_id}: {role_name} | {seat_label}侧座位 | {reference_summary}"

            duo_lines = [
                _build_duo_role_line(
                    role=role_1,
                    default_name=DUO_ROLE_1_DEFAULT_NAME,
                    default_description=DUO_ROLE_1_DEFAULT_DESCRIPTION,
                    default_seat="左",
                ),
                _build_duo_role_line(
                    role=role_2,
                    default_name=DUO_ROLE_2_DEFAULT_NAME,
                    default_description=DUO_ROLE_2_DEFAULT_DESCRIPTION,
                    default_seat="右",
                ),
            ]
            duo_lines = [line for line in duo_lines if line]
            if lines:
                if not duo_lines:
                    duo_lines = lines
            if not duo_lines:
                return "无可用参考；若不需要参考，video_reference_slots 返回 []。", set()
            return "\n".join(duo_lines), allowed_ids

        if not lines:
            return "无可用参考；若不需要参考，video_reference_slots 返回 []。", set()
        return "\n".join(lines), allowed_ids

    @staticmethod
    def _parse_json_response_text(response_text: str) -> dict[str, Any]:
        json_start = response_text.find("{")
        json_end = response_text.rfind("}") + 1
        if json_start == -1 or json_end <= json_start:
            raise ValueError("No JSON object found in response")
        json_fragment = response_text[json_start:json_end]
        try:
            parsed = json.loads(json_fragment)
        except json.JSONDecodeError as original_error:
            logger.warning(
                "[Storyboard] Invalid JSON detected, attempting json_repair fallback: %s",
                original_error,
            )
            try:
                parsed = repair_json_loads(json_fragment, skip_json_loads=True)
            except Exception as repair_error:  # noqa: BLE001
                raise ValueError(
                    f"JSON repair failed after parse error: {original_error}"
                ) from repair_error
            if not isinstance(parsed, dict):
                raise ValueError("JSON repair did not return an object")
            logger.info("[Storyboard] JSON repaired successfully via json_repair")
            return parsed

        if not isinstance(parsed, dict):
            raise ValueError("JSON response is not an object")
        return parsed

    async def _persist_storyboard_stream_progress(
        self,
        *,
        db: AsyncSession,
        stage: StageExecution,
        raw_text: str,
    ) -> None:
        stage.progress = min(94, max(int(stage.progress or 0), 62 + min(len(raw_text) // 260, 28)))
        output_data = dict(stage.output_data or {})
        output_data["partial_storyboard_raw"] = raw_text[-12000:]
        output_data["progress_message"] = "正在接收分镜流式输出..."

        items = extract_json_array_items(raw_text, "shots")
        partial_shots: list[dict[str, Any]] = []
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            shot_index_raw = item.get("shot_index")
            shot_index = (
                shot_index_raw if isinstance(shot_index_raw, int) and shot_index_raw >= 0 else idx
            )
            partial_shot: dict[str, Any] = {"shot_index": shot_index}
            voice_content = str(item.get("voice_content") or "").strip()
            if voice_content:
                partial_shot["voice_content"] = voice_content
            speaker_id = str(item.get("speaker_id") or "").strip()
            if speaker_id:
                partial_shot["speaker_id"] = speaker_id
            speaker_name = str(item.get("speaker_name") or "").strip()
            if speaker_name:
                partial_shot["speaker_name"] = speaker_name
            video_prompt = str(item.get("video_prompt") or "").strip()
            if video_prompt:
                partial_shot["video_prompt"] = video_prompt
            reference_slots = item.get("video_reference_slots")
            if isinstance(reference_slots, list):
                partial_shot["video_reference_slots"] = reference_slots
            if len(partial_shot) > 1:
                partial_shots.append(partial_shot)

        if partial_shots:
            output_data["partial_storyboard_shots"] = partial_shots

        stage.output_data = output_data
        flag_modified(stage, "output_data")
        await db.commit()

    async def _persist_storyboard_stream_fallback_progress(
        self,
        *,
        db: AsyncSession,
        stage: StageExecution,
        fallback_message: str,
    ) -> None:
        stage.progress = min(94, max(int(stage.progress or 0), 66))
        output_data = dict(stage.output_data or {})
        output_data.pop("partial_storyboard_raw", None)
        output_data.pop("partial_storyboard_shots", None)
        output_data["progress_message"] = (
            str(fallback_message or "").strip() or "正在改用普通生成..."
        )
        stage.output_data = output_data
        flag_modified(stage, "output_data")
        await db.commit()
