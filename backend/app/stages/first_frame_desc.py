"""First frame description generation stage handler."""

import json
import logging
from typing import Any

from json_repair import loads as repair_json_loads
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.core.dialogue import (
    DUO_ROLE_1_DEFAULT_NAME,
    DUO_ROLE_1_ID,
    DUO_ROLE_2_DEFAULT_NAME,
    DUO_ROLE_2_ID,
    DUO_SCENE_ROLE_ID,
    DUO_SCENE_ROLE_NAME,
    SCRIPT_MODE_DIALOGUE_SCRIPT,
    SCRIPT_MODE_DUO_PODCAST,
    SCRIPT_MODE_SINGLE,
    normalize_dialogue_max_roles,
    normalize_roles,
    resolve_script_mode,
)
from app.core.errors import StageValidationError
from app.core.project_mode import (
    VIDEO_TYPE_CUSTOM,
    resolve_script_mode_from_video_type,
    resolve_video_type,
)
from app.core.reference_slots import (
    build_reference_slots_from_ids,
    extract_reference_slot_ids,
    normalize_reference_slots,
)
from app.core.stream_json import extract_json_array_items
from app.llm.runtime import resolve_llm_runtime
from app.models.project import Project
from app.models.stage import StageExecution, StageType
from app.stages.common.log_utils import log_stage_separator
from app.stages.common.validators import is_shot_data_usable

from . import register_stage
from ._generation_log import format_generation_json, truncate_generation_text
from .base import StageHandler, StageResult
from .prompts import (
    FIRST_FRAME_BATCH_COMMON_USER,
    FIRST_FRAME_BATCH_DIALOGUE_SCRIPT_USER,
    FIRST_FRAME_BATCH_SYSTEM,
    format_prompt_complexity_for_log,
    format_target_language_for_log,
    get_first_frame_prompt_example,
    get_first_frame_prompt_length_requirement,
    get_target_language_label,
    resolve_prompt_complexity,
    resolve_target_language,
)

logger = logging.getLogger(__name__)
STORYBOARD_SHOTS_REQUIRED_ERROR = "分镜为空或不可用，请先生成分镜"
VIDEO_PROMPTS_REQUIRED_ERROR = "视频描述为空或不可用，请先生成视频描述"


@register_stage(StageType.FIRST_FRAME_DESC)
class FirstFrameDescHandler(StageHandler):
    """Generate first frame descriptions for all shots in batch using LLM."""

    async def execute(
        self,
        db: AsyncSession,
        project: Project,
        stage: StageExecution,
        input_data: dict[str, Any] | None = None,
    ) -> StageResult:
        # Get storyboard data (shots)
        storyboard_data = await self._get_storyboard_data(db, project)
        if not storyboard_data:
            return StageResult(success=False, error=STORYBOARD_SHOTS_REQUIRED_ERROR)

        shots = storyboard_data.get("shots") or []
        if not shots:
            return StageResult(success=False, error=STORYBOARD_SHOTS_REQUIRED_ERROR)

        script_mode_hint = resolve_script_mode(
            storyboard_data.get("script_mode")
            or resolve_script_mode_from_video_type(project.video_type)
        )
        only_shot_index = (
            (input_data or {}).get("only_shot_index")
            if (input_data or {}).get("only_shot_index") is not None
            else None
        )
        effective_only_shot_index = only_shot_index
        target_indices = list(range(len(shots)))
        if only_shot_index is not None:
            if (
                not isinstance(only_shot_index, int)
                or only_shot_index < 0
                or only_shot_index >= len(shots)
            ):
                return StageResult(
                    success=False, error=f"Shot index {only_shot_index} out of range"
                )
            target_indices = [only_shot_index]
        elif script_mode_hint == SCRIPT_MODE_DUO_PODCAST:
            # 双人播客下，批量入口仅生成第一个分镜的首帧描述，避免批量首帧描述提示词。
            effective_only_shot_index = 0
            target_indices = [0]

        invalid_shot_indices = [
            idx for idx in target_indices if not self._is_shot_voice_content_valid(shots[idx])
        ]
        if invalid_shot_indices:
            return StageResult(success=False, error=STORYBOARD_SHOTS_REQUIRED_ERROR)

        invalid_video_prompt_indices = [
            idx for idx in target_indices if not self._is_shot_video_prompt_valid(shots[idx])
        ]
        if invalid_video_prompt_indices:
            return StageResult(
                success=False,
                error=VIDEO_PROMPTS_REQUIRED_ERROR,
            )

        max_roles = normalize_dialogue_max_roles(settings.dialogue_script_max_roles)
        script_mode = resolve_script_mode(
            storyboard_data.get("script_mode")
            or resolve_script_mode_from_video_type(project.video_type)
        )
        roles = normalize_roles(
            storyboard_data.get("roles"),
            script_mode=script_mode,
            max_roles=max_roles,
        )
        prompt_script_mode = self._resolve_prompt_script_mode(
            project_video_type=project.video_type,
            script_mode=script_mode,
            roles=roles,
            shots=shots,
        )
        single_take = bool(
            (input_data or {}).get("single_take", False)
            or prompt_script_mode == SCRIPT_MODE_DUO_PODCAST
        )

        # Check if we should use reference consistency
        use_reference_consistency = (input_data or {}).get("use_reference_consistency", False)
        logger.info(f"[FirstFrameDesc] use_reference_consistency: {use_reference_consistency}")

        # Collect available references with images.
        # Even when reference consistency is off, we still ask LLM to output
        # first_frame_reference_slots (usually [] if no reference is needed).
        references = []
        reference_by_id: dict[str, dict[str, str]] = {}
        raw_reference_by_id: dict[str, dict[str, str]] = {}
        reference_data = await self._get_reference_data(db, project)
        if reference_data:
            raw_references = reference_data.get("references", [])
            reference_ids_with_image = self._collect_reference_ids_with_image(reference_data)
            if isinstance(raw_references, list):
                references = list(raw_references)
                references = [
                    item
                    for item in raw_references
                    if isinstance(item, dict)
                    and str(item.get("id") or "").strip() in reference_ids_with_image
                ]
                for item in raw_references:
                    if not isinstance(item, dict):
                        continue
                    reference_id = str(item.get("id") or "").strip()
                    if not reference_id:
                        continue
                    setting = str(item.get("setting") or "").strip()
                    appearance = self._resolve_reference_appearance_text(item)
                    raw_reference_by_id[reference_id] = {
                        "id": reference_id,
                        "name": str(item.get("name") or "").strip(),
                        "setting": setting,
                        "appearance_description": appearance,
                        "description": self._build_reference_prompt_description(
                            setting=setting,
                            appearance=appearance,
                        ),
                    }
                for item in references:
                    if not isinstance(item, dict):
                        continue
                    reference_id = str(item.get("id") or "").strip()
                    if not reference_id:
                        continue
                    setting = str(item.get("setting") or "").strip()
                    appearance = self._resolve_reference_appearance_text(item)
                    reference_by_id[reference_id] = {
                        "id": reference_id,
                        "name": str(item.get("name") or "").strip(),
                        "setting": setting,
                        "appearance_description": appearance,
                        "description": self._build_reference_prompt_description(
                            setting=setting,
                            appearance=appearance,
                        ),
                    }
        logger.info("[FirstFrameDesc] Found %d references with image", len(references))
        allowed_reference_ids = {
            str(item.get("id") or "").strip()
            for item in references
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        }

        try:
            target_language = resolve_target_language((input_data or {}).get("target_language"))
            target_language_label = get_target_language_label(target_language)
            target_language_log = format_target_language_for_log(target_language)
            prompt_complexity = resolve_prompt_complexity(
                (input_data or {}).get("prompt_complexity")
            )
            prompt_complexity_log = format_prompt_complexity_for_log(prompt_complexity)
            first_frame_prompt_example = get_first_frame_prompt_example(target_language)

            # Build all shots text for batch/single processing.
            # 单条模式也提供全量分镜上下文，保证模型理解全局叙事。
            all_shots = []
            for i in range(len(shots)):
                shot = shots[i]
                voice_content = shot.get("voice_content", "")
                video_prompt = shot.get("video_prompt", "")
                speaker_id = str(shot.get("speaker_id") or "").strip()
                speaker_name = str(shot.get("speaker_name") or "").strip()
                speaker_label = speaker_name or speaker_id or "未标注"
                shot_text = (
                    f"【分镜 {i + 1}】(shot_index={i}, 说话人={speaker_label})\n"
                    f"口播内容：{voice_content}"
                )
                if video_prompt:
                    shot_text += f"\n视频描述：{video_prompt}"
                all_shots.append(shot_text)

            all_shots_str = "\n\n".join(all_shots)
            if effective_only_shot_index is not None:
                generation_scope = (
                    f"仅生成一个分镜：分镜 {effective_only_shot_index + 1}（shot_index={effective_only_shot_index}）。"
                    " 严禁生成其他分镜。JSON 中 frames 数组只允许 1 条记录，shot_index 必须与目标一致。"
                )
            else:
                generation_scope = "生成所有分镜。JSON 中 frames 数组应覆盖所有分镜。"

            base_prompt_kwargs = {
                "generation_scope": generation_scope,
                "all_shots": all_shots_str,
                "target_language_name": target_language_label,
                "first_frame_prompt_length_requirement": get_first_frame_prompt_length_requirement(
                    target_language,
                    prompt_complexity,
                ),
                "first_frame_prompt_example": first_frame_prompt_example,
            }
            duo_role_1: dict[str, Any] = {}
            duo_role_2: dict[str, Any] = {}
            duo_scene_role: dict[str, Any] = {}

            if prompt_script_mode == SCRIPT_MODE_DUO_PODCAST:
                duo_role_1 = next(
                    (role for role in roles if str(role.get("id") or "").strip() == DUO_ROLE_1_ID),
                    {},
                )
                duo_role_2 = next(
                    (role for role in roles if str(role.get("id") or "").strip() == DUO_ROLE_2_ID),
                    {},
                )
                duo_scene_role = next(
                    (
                        role
                        for role in roles
                        if str(role.get("id") or "").strip() == DUO_SCENE_ROLE_ID
                    ),
                    {},
                )
                if use_reference_consistency and reference_by_id:
                    duo_role_1 = self._apply_reference_profile_to_role(duo_role_1, reference_by_id)
                    duo_role_2 = self._apply_reference_profile_to_role(duo_role_2, reference_by_id)
                    duo_scene_role = self._apply_reference_profile_to_role(
                        duo_scene_role,
                        reference_by_id,
                    )
                direct_result = await self._execute_duo_podcast_template_generation(
                    db=db,
                    project=project,
                    stage=stage,
                    shots=shots,
                    target_indices=target_indices,
                    use_reference_consistency=bool(use_reference_consistency),
                    allowed_reference_ids=allowed_reference_ids,
                    raw_reference_by_id=raw_reference_by_id,
                    role_1=duo_role_1,
                    role_2=duo_role_2,
                    scene_role=duo_scene_role,
                    target_language=target_language,
                )
                return direct_result

            llm_runtime = resolve_llm_runtime(input_data)
            llm_provider = llm_runtime.provider

            role_names_by_reference_id = self._build_reference_role_name_map(
                roles,
                reference_by_id,
            )
            references_str = self._format_references_for_prompt(
                references,
                role_names_by_reference_id,
            )
            if not references_str.strip():
                references_str = (
                    "无可用参考信息（可用ID为空）。"
                    "请为每个分镜输出 first_frame_reference_slots: []，且不要在 first_frame_prompt 中使用 @图片N。"
                )
            extra_requirement_blocks: list[str] = []
            if use_reference_consistency and bool(references):
                extra_requirement_blocks.append(
                    "附加硬性要求（参考图引用语法）：\n"
                    "1. 若某分镜 first_frame_reference_slots 非空，first_frame_prompt 必须直接使用“@图片1、@图片2 …”引用参考图。\n"
                    "2. @图片N 对应该分镜 first_frame_reference_slots 按 order 升序排列后的第 N 个 ID；顺序必须一致。\n"
                    "3. 若 first_frame_reference_slots 为空，则该分镜 first_frame_prompt 中不得出现“@图片N”。"
                )
            else:
                extra_requirement_blocks.append(
                    "附加硬性要求（参考图引用语法）：\n"
                    "1. 当前未开启“保持参考一致性”或无可用参考图，first_frame_prompt 不要求使用“@图片N”。\n"
                    "2. 请仍输出 first_frame_reference_slots（若分镜不需要参考图则输出 []）。"
                )
            if prompt_script_mode == SCRIPT_MODE_DIALOGUE_SCRIPT:
                prompt = FIRST_FRAME_BATCH_DIALOGUE_SCRIPT_USER.format(
                    **base_prompt_kwargs,
                    references=references_str,
                )
            else:
                prompt = FIRST_FRAME_BATCH_COMMON_USER.format(
                    **base_prompt_kwargs,
                    references=references_str,
                )
            if extra_requirement_blocks:
                extra_requirements = "\n\n".join(extra_requirement_blocks)
                json_output_anchor = "请以JSON格式输出："
                anchor_index = prompt.rfind(json_output_anchor)
                if anchor_index >= 0:
                    prompt = (
                        f"{prompt[:anchor_index].rstrip()}\n\n"
                        f"{extra_requirements}\n\n"
                        f"{prompt[anchor_index:]}"
                    )
                else:
                    prompt = f"{prompt}\n\n{extra_requirements}"

            system_prompt = FIRST_FRAME_BATCH_SYSTEM

            log_stage_separator(logger)
            logger.info(
                "[FirstFrameDesc] LLM Generate - %s mode for %d shots",
                "single" if effective_only_shot_index is not None else "batch",
                len(target_indices),
            )
            logger.info(
                "[Input] llm_provider=%s(%s) llm_model=%s",
                llm_runtime.provider_name,
                llm_runtime.provider_type,
                llm_runtime.model,
            )
            logger.info("[Input] target_language=%s", target_language_log)
            logger.info("[Input] prompt_complexity=%s", prompt_complexity_log)
            logger.info("[Input] context shots count: %d", len(shots))
            logger.info("[Input] only_shot_index: %s", effective_only_shot_index)
            logger.info("[Input] script_mode: %s", script_mode)
            logger.info("[Input] prompt_script_mode: %s", prompt_script_mode)
            logger.info("[Input] single_take: %s", single_take)
            logger.info("[Input] prompt: %s", truncate_generation_text(prompt))
            logger.info(
                "[Input] system_prompt: %s",
                truncate_generation_text(system_prompt),
            )
            log_stage_separator(logger)

            use_stream = str((input_data or {}).get("llm_stream", "1")).strip().lower() not in {
                "0",
                "false",
                "off",
                "no",
            }
            response_text = ""
            if use_stream:
                logger.info("[FirstFrameDesc] LLM streaming enabled")
                chunks: list[str] = []
                chars_since_flush = 0
                try:
                    async for chunk in llm_provider.generate_stream(
                        prompt=prompt,
                        system_prompt=system_prompt,
                        temperature=0.5,
                    ):
                        text = str(chunk or "")
                        if not text:
                            continue
                        chunks.append(text)
                        chars_since_flush += len(text)
                        if chars_since_flush < 500:
                            continue
                        await self._persist_first_frame_stream_progress(
                            db=db,
                            stage=stage,
                            target_indices=target_indices,
                            shots=shots,
                            raw_text="".join(chunks),
                        )
                        chars_since_flush = 0
                    response_text = "".join(chunks).strip()
                except Exception as stream_err:
                    logger.warning(
                        "[FirstFrameDesc] LLM stream failed (%r), fallback to non-stream generate",
                        stream_err,
                    )

            if not response_text:
                response = await llm_provider.generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=0.5,
                )
                response_text = response.content.strip()

            # Parse JSON response
            try:
                result_data = self._parse_json_response_text(response_text)
            except Exception as e:
                logger.error(f"[FirstFrameDesc] Failed to parse JSON: {e}")
                return StageResult(
                    success=False, error=f"Failed to parse LLM response as JSON: {e}"
                )

            frames = result_data.get("frames", [])
            if not frames:
                return StageResult(success=False, error="No frames found in LLM response")

            # Update shots with first frame descriptions
            updated_shots = [dict(shot) for shot in shots]
            frame_by_index = {}
            for frame in frames:
                if isinstance(frame, dict) and isinstance(frame.get("shot_index"), int):
                    frame_by_index[int(frame["shot_index"])] = frame

            if (
                effective_only_shot_index is not None
                and effective_only_shot_index not in frame_by_index
                and frames
            ):
                first_frame = frames[0]
                if isinstance(first_frame, dict):
                    frame_by_index[effective_only_shot_index] = first_frame

            for i in target_indices:
                frame_data = frame_by_index.get(i)
                if not frame_data:
                    continue

                updated_shot = updated_shots[i]
                action_prompt = str(frame_data.get("first_frame_prompt") or "").strip()
                if prompt_script_mode == SCRIPT_MODE_DUO_PODCAST:
                    updated_shot["first_frame_description"] = (
                        self._compose_duo_podcast_first_frame_prompt(
                            action_prompt=action_prompt,
                            role_1=duo_role_1,
                            role_2=duo_role_2,
                            scene_role=duo_scene_role,
                            references_by_id=reference_by_id,
                            allowed_reference_ids=allowed_reference_ids,
                            include_reference_identity=bool(use_reference_consistency),
                            target_language=target_language,
                        )
                    )
                else:
                    updated_shot["first_frame_description"] = action_prompt

                reference_slots = normalize_reference_slots(
                    frame_data.get("first_frame_reference_slots"),
                    allowed_reference_ids=allowed_reference_ids,
                )
                reference_slot_ids = extract_reference_slot_ids(reference_slots)
                if prompt_script_mode == SCRIPT_MODE_DUO_PODCAST:
                    reference_slot_ids = self._normalize_duo_first_frame_slot_ids(
                        reference_slot_ids,
                        duo_scene_role,
                        allowed_reference_ids,
                    )
                    reference_slots = build_reference_slots_from_ids(
                        reference_slot_ids,
                        original_slots=reference_slots,
                    )
                updated_shot["first_frame_reference_slots"] = reference_slots
                if reference_slot_ids:
                    if prompt_script_mode == SCRIPT_MODE_DUO_PODCAST:
                        updated_shot["first_frame_prompt_reference_identity"] = (
                            self._build_duo_first_frame_reference_identity(
                                reference_ids=reference_slot_ids,
                                scene_role=duo_scene_role,
                                role_1=duo_role_1,
                                role_2=duo_role_2,
                                allowed_reference_ids=allowed_reference_ids,
                            )
                        )
                    else:
                        updated_shot["first_frame_prompt_reference_identity"] = (
                            self._build_reference_slot_identity(reference_slot_ids)
                        )
                else:
                    updated_shot.pop("first_frame_prompt_reference_identity", None)

            generated_frames_log = [
                {
                    "shot_index": idx,
                    "first_frame_description": str(
                        updated_shots[idx].get("first_frame_description") or ""
                    ),
                    "first_frame_reference_slots": updated_shots[idx].get(
                        "first_frame_reference_slots", []
                    ),
                }
                for idx in target_indices
            ]
            logger.info(
                "[Output] generated_frames: %s",
                format_generation_json(generated_frames_log),
            )

            # Update the script stage with the new first frame descriptions
            await self._update_storyboard_shots(db, project, updated_shots)

            # Update progress: complete
            stage.progress = 100
            await db.commit()

            return StageResult(
                success=True,
                data={
                    "shots": updated_shots,
                    "shot_count": len(updated_shots),
                    "use_reference_consistency": use_reference_consistency,
                },
            )

        except Exception as e:
            logger.error(f"[FirstFrameDesc] Stage failed: {e}")
            return StageResult(success=False, error=str(e))

    async def _persist_first_frame_stream_progress(
        self,
        db: AsyncSession,
        stage: StageExecution,
        target_indices: list[int],
        shots: list[dict[str, Any]],
        raw_text: str,
    ) -> None:
        stage.progress = min(94, max(int(stage.progress or 0), 66 + min(len(raw_text) // 260, 22)))
        output_data = dict(stage.output_data or {})
        output_data["partial_first_frame_raw"] = raw_text[-12000:]
        output_data["progress_message"] = "正在接收首帧描述流式输出..."

        items = extract_json_array_items(raw_text, "frames")
        partial_shots: list[dict[str, Any]] = []
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            shot_index_raw = item.get("shot_index")
            shot_index: int
            if isinstance(shot_index_raw, int):
                shot_index = shot_index_raw
            elif idx < len(target_indices):
                shot_index = target_indices[idx]
            else:
                shot_index = idx
            if shot_index < 0 or shot_index >= len(shots):
                continue
            description = str(item.get("first_frame_prompt") or "").strip()
            if not description:
                continue
            partial_shots.append(
                {
                    "shot_index": shot_index,
                    "first_frame_description": description,
                    "first_frame_reference_slots": (
                        item.get("first_frame_reference_slots")
                        if isinstance(item.get("first_frame_reference_slots"), list)
                        else []
                    ),
                }
            )
        if partial_shots:
            output_data["partial_first_frame_shots"] = partial_shots

        stage.output_data = output_data
        flag_modified(stage, "output_data")
        await db.commit()

    async def _get_storyboard_data(self, db: AsyncSession, project: Project) -> dict | None:
        result = await db.execute(
            select(StageExecution)
            .where(
                StageExecution.project_id == project.id,
                StageExecution.stage_type == StageType.STORYBOARD,
            )
            .order_by(StageExecution.updated_at.desc(), StageExecution.id.desc())
        )
        storyboard_data, _ = self._pick_latest_usable_shot_data(list(result.scalars()))
        return storyboard_data

    async def _get_reference_data(self, db: AsyncSession, project: Project) -> dict | None:
        result = await db.execute(
            select(StageExecution)
            .where(
                StageExecution.project_id == project.id,
                StageExecution.stage_type == StageType.REFERENCE,
            )
            .order_by(StageExecution.updated_at.desc(), StageExecution.id.desc())
        )
        for stage in result.scalars():
            output_data = stage.output_data
            if not isinstance(output_data, dict):
                continue
            references = output_data.get("references")
            if isinstance(references, list) and references:
                return output_data
        return None

    async def _update_storyboard_shots(
        self, db: AsyncSession, project: Project, updated_shots: list
    ) -> None:
        """Update storyboard shots and keep frame stage metadata in sync."""
        changed = False

        result = await db.execute(
            select(StageExecution)
            .where(
                StageExecution.project_id == project.id,
                StageExecution.stage_type == StageType.STORYBOARD,
            )
            .order_by(StageExecution.updated_at.desc(), StageExecution.id.desc())
        )
        storyboard_stage = result.scalars().first()

        if storyboard_stage:
            output_data = dict(storyboard_stage.output_data or {})
            output_data["shots"] = updated_shots
            storyboard_stage.output_data = output_data
            flag_modified(storyboard_stage, "output_data")
            changed = True

        # Keep FRAME stage descriptions in sync to avoid stale UI fallback values.
        frame_result = await db.execute(
            select(StageExecution).where(
                StageExecution.project_id == project.id,
                StageExecution.stage_type == StageType.FRAME,
            )
        )
        frame_stage = frame_result.scalar_one_or_none()
        if frame_stage and isinstance(frame_stage.output_data, dict):
            frame_output = dict(frame_stage.output_data)
            frame_images = frame_output.get("frame_images")
            if isinstance(frame_images, list):
                frame_changed = False
                synced_frame_images = []
                for item in frame_images:
                    if not isinstance(item, dict):
                        synced_frame_images.append(item)
                        continue
                    frame_item = dict(item)
                    shot_index = frame_item.get("shot_index")
                    if isinstance(shot_index, int) and 0 <= shot_index < len(updated_shots):
                        new_description = updated_shots[shot_index].get("first_frame_description")
                        if (
                            isinstance(new_description, str)
                            and new_description.strip()
                            and frame_item.get("first_frame_description") != new_description
                        ):
                            frame_item["first_frame_description"] = new_description
                            frame_changed = True
                    synced_frame_images.append(frame_item)
                if frame_changed:
                    frame_output["frame_images"] = synced_frame_images
                    frame_stage.output_data = frame_output
                    flag_modified(frame_stage, "output_data")
                    changed = True

        if changed:
            await db.commit()

    async def validate_prerequisites(self, db: AsyncSession, project: Project) -> str | None:
        storyboard_data = await self._get_storyboard_data(db, project)
        if not storyboard_data:
            return STORYBOARD_SHOTS_REQUIRED_ERROR
        shots = storyboard_data.get("shots") or []
        if not isinstance(shots, list) or not shots:
            return STORYBOARD_SHOTS_REQUIRED_ERROR
        if any(
            not isinstance(shot, dict) or not self._is_shot_video_prompt_valid(shot)
            for shot in shots
        ):
            return VIDEO_PROMPTS_REQUIRED_ERROR
        return None

    @staticmethod
    def _is_shot_voice_content_valid(shot: dict[str, Any]) -> bool:
        voice_content = shot.get("voice_content")
        return isinstance(voice_content, str) and voice_content.strip() != ""

    @staticmethod
    def _is_shot_video_prompt_valid(shot: dict[str, Any]) -> bool:
        video_prompt = shot.get("video_prompt")
        return isinstance(video_prompt, str) and video_prompt.strip() != ""

    @staticmethod
    def _format_duo_seat_side(value: Any, default: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in {"right", "右"}:
            return "右"
        if normalized in {"left", "左"}:
            return "左"
        return default

    @staticmethod
    def _resolve_role_reference_id(role: dict[str, Any]) -> str:
        return str((role or {}).get("id") or "").strip()

    def _apply_reference_profile_to_role(
        self,
        role: dict[str, Any],
        references_by_id: dict[str, dict[str, str]],
    ) -> dict[str, Any]:
        resolved_role = dict(role or {})
        reference_id = self._resolve_role_reference_id(resolved_role)
        if not reference_id:
            return resolved_role
        reference = references_by_id.get(reference_id) or {}
        reference_name = str(reference.get("name") or "").strip()
        reference_description = self._resolve_duo_role_description_for_prompt(
            resolved_role,
            references_by_id,
        )
        if reference_name:
            resolved_role["name"] = reference_name
        resolved_role["description"] = reference_description
        return resolved_role

    def _build_reference_role_name_map(
        self,
        roles: list[dict[str, Any]],
        references_by_id: dict[str, dict[str, str]] | None = None,
    ) -> dict[str, list[str]]:
        mapping: dict[str, list[str]] = {}
        reference_lookup = references_by_id or {}
        for role in roles:
            reference_id = self._resolve_role_reference_id(role)
            if not reference_id:
                continue
            role_name = str((reference_lookup.get(reference_id) or {}).get("name") or "").strip()
            if not role_name:
                role_name = (
                    str(role.get("name") or "").strip()
                    or str(role.get("id") or "").strip()
                    or "未命名角色"
                )
            role_names = mapping.setdefault(reference_id, [])
            if role_name not in role_names:
                role_names.append(role_name)
        return mapping

    @staticmethod
    def _collect_non_narrator_speakers(shots: list[dict[str, Any]]) -> set[str]:
        speaker_ids: set[str] = set()
        for shot in shots:
            speaker_id = str(shot.get("speaker_id") or "").strip().lower()
            speaker_name = str(shot.get("speaker_name") or "").strip().lower()
            if not speaker_id or speaker_name in {"画外音", "旁白"} or speaker_id == "narrator":
                continue
            speaker_ids.add(speaker_id)
        return speaker_ids

    @staticmethod
    def _collect_speaking_roles(roles: list[dict[str, Any]]) -> set[str]:
        role_ids: set[str] = set()
        for role in roles:
            role_id = str(role.get("id") or "").strip().lower()
            if not role_id or role_id == DUO_SCENE_ROLE_ID:
                continue
            role_ids.add(role_id)
        return role_ids

    def _resolve_prompt_script_mode(
        self,
        *,
        project_video_type: Any,
        script_mode: str,
        roles: list[dict[str, Any]],
        shots: list[dict[str, Any]],
    ) -> str:
        resolved_video_type = resolve_video_type(project_video_type)
        if resolved_video_type != VIDEO_TYPE_CUSTOM:
            return script_mode
        if script_mode == SCRIPT_MODE_DUO_PODCAST:
            return script_mode

        speakers = self._collect_non_narrator_speakers(shots)
        if not speakers:
            speakers = self._collect_speaking_roles(roles)
        if len(speakers) <= 1:
            return SCRIPT_MODE_SINGLE
        return SCRIPT_MODE_DIALOGUE_SCRIPT

    @staticmethod
    def _resolve_usable_reference_id(
        role: dict[str, Any],
        allowed_reference_ids: set[str] | None = None,
    ) -> str:
        reference_id = FirstFrameDescHandler._resolve_role_reference_id(role)
        if not reference_id:
            return ""
        if allowed_reference_ids is not None and reference_id not in allowed_reference_ids:
            return ""
        return reference_id

    @staticmethod
    def _build_reference_slot_identity(reference_ids: list[str]) -> str:
        if not reference_ids:
            return ""
        lines = ["参考图顺序映射："]
        for idx, reference_id in enumerate(reference_ids):
            lines.append(f"@图片{idx + 1} = {reference_id}")
        lines.append("请在描述中使用“@图片N”引用对应参考图。")
        return "\n".join(lines)

    @staticmethod
    def _normalize_duo_first_frame_slot_ids(
        reference_slot_ids: list[str],
        scene_role: dict[str, Any],
        allowed_reference_ids: set[str] | None = None,
    ) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in reference_slot_ids:
            value = str(item or "").strip()
            if not value or value in seen:
                continue
            normalized.append(value)
            seen.add(value)

        scene_reference_id = FirstFrameDescHandler._resolve_usable_reference_id(
            scene_role,
            allowed_reference_ids,
        )
        if not scene_reference_id:
            return normalized

        if scene_reference_id in seen:
            return [scene_reference_id] + [rid for rid in normalized if rid != scene_reference_id]
        return [scene_reference_id, *normalized]

    def _build_duo_first_frame_reference_identity(
        self,
        *,
        reference_ids: list[str],
        scene_role: dict[str, Any],
        role_1: dict[str, Any],
        role_2: dict[str, Any],
        allowed_reference_ids: set[str] | None = None,
    ) -> str:
        if not reference_ids:
            return ""
        lines = self._build_reference_slot_identity(reference_ids).splitlines()
        scene_ref = self._resolve_usable_reference_id(scene_role, allowed_reference_ids)
        role_1_ref = self._resolve_usable_reference_id(role_1, allowed_reference_ids)
        role_2_ref = self._resolve_usable_reference_id(role_2, allowed_reference_ids)
        role_1_seat = self._format_duo_seat_side(role_1.get("seat_side"), "左")
        role_2_seat = self._format_duo_seat_side(role_2.get("seat_side"), "右")
        if scene_ref:
            lines.append(f"场景参考ID：{scene_ref}")
        if role_1_ref:
            lines.append(f"{role_1_seat}侧角色参考ID：{role_1_ref}")
        if role_2_ref:
            lines.append(f"{role_2_seat}侧角色参考ID：{role_2_ref}")
        return "\n".join(lines)

    @staticmethod
    def _format_references_for_prompt(
        references: list[dict[str, Any]],
        role_names_by_reference_id: dict[str, list[str]],
    ) -> str:
        lines: list[str] = []
        for reference in references:
            reference_id = str(reference.get("id") or "").strip() or "unknown"
            reference_name = str(reference.get("name") or "").strip() or "Unknown"
            setting = str(reference.get("setting") or "").strip()
            appearance = FirstFrameDescHandler._resolve_reference_appearance_text(reference)
            reference_description = FirstFrameDescHandler._build_reference_prompt_description(
                setting=setting,
                appearance=appearance,
            )
            role_names = role_names_by_reference_id.get(reference_id) or []
            if role_names:
                lines.append(
                    f"- {reference_id}: {reference_name} - {reference_description}（绑定角色：{'、'.join(role_names)}）"
                )
            else:
                lines.append(f"- {reference_id}: {reference_name} - {reference_description}")
        return "\n".join(lines)

    def _build_duo_podcast_template_reference_slot_ids(
        self,
        *,
        use_reference_consistency: bool,
        allowed_reference_ids: set[str],
        scene_role: dict[str, Any],
        role_1: dict[str, Any],
        role_2: dict[str, Any],
    ) -> list[str]:
        if not use_reference_consistency:
            return []
        ordered_ids = [
            self._resolve_usable_reference_id(scene_role, allowed_reference_ids),
            self._resolve_usable_reference_id(role_1, allowed_reference_ids),
            self._resolve_usable_reference_id(role_2, allowed_reference_ids),
        ]
        return [reference_id for reference_id in ordered_ids if reference_id]

    @staticmethod
    def _get_duo_reference_marker(
        reference_slot_ids: list[str],
        reference_id: str,
        *,
        target_language: str = "zh",
    ) -> str:
        normalized_reference_id = str(reference_id or "").strip()
        if not normalized_reference_id:
            return ""
        for index, current_reference_id in enumerate(reference_slot_ids, start=1):
            if str(current_reference_id or "").strip() == normalized_reference_id:
                return f"@image{index}" if target_language == "en" else f"@图片{index}"
        return ""

    @staticmethod
    def _resolve_duo_reference_appearance_text(reference: dict[str, Any] | None) -> str:
        if not isinstance(reference, dict):
            return ""
        appearance = str(reference.get("appearance_description") or "").strip()
        if appearance:
            return appearance
        return str(reference.get("setting") or "").strip()

    @staticmethod
    def _strip_terminal_punctuation(text: str) -> str:
        return str(text or "").strip().rstrip("。．.!！？?;；，,、")

    def _build_duo_podcast_template_first_frame_description(
        self,
        *,
        reference_slot_ids: list[str],
        raw_reference_by_id: dict[str, dict[str, str]],
        scene_role: dict[str, Any],
        role_1: dict[str, Any],
        role_2: dict[str, Any],
        allowed_reference_ids: set[str],
        target_language: str = "zh",
    ) -> str:
        scene_reference_id = self._resolve_usable_reference_id(scene_role, allowed_reference_ids)
        role_1_reference_id = self._resolve_usable_reference_id(role_1, allowed_reference_ids)
        role_2_reference_id = self._resolve_usable_reference_id(role_2, allowed_reference_ids)

        scene_marker = self._get_duo_reference_marker(
            reference_slot_ids,
            scene_reference_id,
            target_language=target_language,
        )
        role_1_marker = self._get_duo_reference_marker(
            reference_slot_ids,
            role_1_reference_id,
            target_language=target_language,
        )
        role_2_marker = self._get_duo_reference_marker(
            reference_slot_ids,
            role_2_reference_id,
            target_language=target_language,
        )

        scene_reference = raw_reference_by_id.get(self._resolve_role_reference_id(scene_role)) or {}
        role_1_reference = raw_reference_by_id.get(self._resolve_role_reference_id(role_1)) or {}
        role_2_reference = raw_reference_by_id.get(self._resolve_role_reference_id(role_2)) or {}

        scene_text = self._strip_terminal_punctuation(
            self._resolve_duo_reference_appearance_text(scene_reference)
        )
        role_1_text = self._strip_terminal_punctuation(
            str(role_1_reference.get("appearance_description") or "").strip()
        )
        role_2_text = self._strip_terminal_punctuation(
            str(role_2_reference.get("appearance_description") or "").strip()
        )

        if target_language == "en":
            if scene_marker:
                first_sentence = (
                    f"Fixed front-facing two-host podcast frame: scene references {scene_marker}."
                )
            elif scene_text:
                first_sentence = (
                    f"Fixed front-facing two-host podcast frame: scene appearance: {scene_text}."
                )
            else:
                first_sentence = "Fixed front-facing two-host podcast frame: no predefined scene."

            parts = [
                first_sentence,
                "Both hosts sit naturally facing the microphones.",
            ]
            if role_1_marker:
                parts.append(f"The left-side host references {role_1_marker}.")
            elif role_1_text:
                parts.append(f"The left-side host appearance: {role_1_text}.")
            if role_2_marker:
                parts.append(f"The right-side host references {role_2_marker}.")
            elif role_2_text:
                parts.append(f"The right-side host appearance: {role_2_text}.")
            parts.append(
                "Keep only subtle expression differences and minimal posture variation; "
                "avoid obvious gestures or large movements."
            )
            return " ".join(parts)

        if scene_marker:
            first_sentence = f"固定双人播客同框正面画面：场景参考{scene_marker}。"
        elif scene_text:
            first_sentence = f"固定双人播客同框正面画面：场景外观描述：{scene_text}。"
        else:
            first_sentence = "固定双人播客同框正面画面：无设定。"

        parts = [
            first_sentence,
            "两侧角色普通静坐并面向麦克风。",
        ]
        if role_1_marker:
            parts.append(f"画面左侧角色参考{role_1_marker}。")
        elif role_1_text:
            parts.append(f"画面左侧角色外观描述：{role_1_text}。")
        if role_2_marker:
            parts.append(f"画面右侧角色参考{role_2_marker}。")
        elif role_2_text:
            parts.append(f"画面右侧角色外观描述：{role_2_text}。")
        parts.append("仅保留轻微表情差异与极小幅度姿态变化，禁止明显手势或大幅动作。")
        return "".join(parts)

    async def _execute_duo_podcast_template_generation(
        self,
        *,
        db: AsyncSession,
        project: Project,
        stage: StageExecution,
        shots: list[dict[str, Any]],
        target_indices: list[int],
        use_reference_consistency: bool,
        allowed_reference_ids: set[str],
        raw_reference_by_id: dict[str, dict[str, str]],
        role_1: dict[str, Any],
        role_2: dict[str, Any],
        scene_role: dict[str, Any],
        target_language: str,
    ) -> StageResult:
        logger.info("[FirstFrameDesc] Duo podcast template generation enabled")
        logger.info("[Input] target_indices: %s", target_indices)
        logger.info("[Input] use_reference_consistency: %s", use_reference_consistency)

        updated_shots = [dict(shot) for shot in shots]
        generated_frames_log: list[dict[str, Any]] = []

        for shot_index in target_indices:
            reference_slot_ids = self._build_duo_podcast_template_reference_slot_ids(
                use_reference_consistency=use_reference_consistency,
                allowed_reference_ids=allowed_reference_ids,
                scene_role=scene_role,
                role_1=role_1,
                role_2=role_2,
            )
            reference_slots = build_reference_slots_from_ids(reference_slot_ids)
            description = self._build_duo_podcast_template_first_frame_description(
                reference_slot_ids=reference_slot_ids,
                raw_reference_by_id=raw_reference_by_id,
                scene_role=scene_role,
                role_1=role_1,
                role_2=role_2,
                allowed_reference_ids=allowed_reference_ids,
                target_language=target_language,
            )

            updated_shot = updated_shots[shot_index]
            updated_shot["first_frame_description"] = description
            updated_shot["first_frame_reference_slots"] = reference_slots
            if reference_slot_ids:
                updated_shot["first_frame_prompt_reference_identity"] = (
                    self._build_duo_first_frame_reference_identity(
                        reference_ids=reference_slot_ids,
                        scene_role=scene_role,
                        role_1=role_1,
                        role_2=role_2,
                        allowed_reference_ids=allowed_reference_ids,
                    )
                )
            else:
                updated_shot.pop("first_frame_prompt_reference_identity", None)

            generated_frames_log.append(
                {
                    "shot_index": shot_index,
                    "first_frame_description": description,
                    "first_frame_reference_slots": reference_slots,
                }
            )

        logger.info("[Output] generated_frames: %s", format_generation_json(generated_frames_log))
        await self._update_storyboard_shots(db, project, updated_shots)
        stage.progress = 100
        await db.commit()
        return StageResult(
            success=True,
            data={
                "shots": updated_shots,
                "shot_count": len(updated_shots),
                "use_reference_consistency": use_reference_consistency,
            },
        )

    @staticmethod
    def _build_duo_first_frame_action_fallback(target_language: str) -> str:
        if target_language == "en":
            return (
                "Both side roles remain in a normal seated posture, with only subtle facial-expression "
                "differences and natural eye focus."
            )
        return "左右两侧角色保持普通静坐，仅保留轻微表情差异与自然目光交流。"

    @staticmethod
    def _build_duo_role_identity(
        role: dict[str, Any],
        side_label: str,
        references_by_id: dict[str, dict[str, str]],
        include_reference_identity: bool,
    ) -> str:
        if not include_reference_identity:
            return side_label
        reference_id = FirstFrameDescHandler._resolve_role_reference_id(role)
        if reference_id:
            return f"{side_label}（使用参考图{reference_id}）"
        reference_name = str((references_by_id.get(reference_id) or {}).get("name") or "").strip()
        if reference_name:
            return f"{side_label}（参考图名称：{reference_name}）"
        return f"{side_label}（未绑定参考图）"

    @staticmethod
    def _build_duo_scene_identity(
        scene_role: dict[str, Any],
        references_by_id: dict[str, dict[str, str]],
        include_reference_identity: bool,
    ) -> str:
        if not include_reference_identity:
            return "场景"
        reference_id = FirstFrameDescHandler._resolve_role_reference_id(scene_role)
        if reference_id:
            return f"场景（使用参考图{reference_id}）"
        reference_name = str((references_by_id.get(reference_id) or {}).get("name") or "").strip()
        if reference_name:
            return f"场景（参考图名称：{reference_name}）"
        return "场景（未绑定参考图）"

    @staticmethod
    def _resolve_reference_appearance_text(reference: dict[str, Any]) -> str:
        return str(reference.get("appearance_description") or "").strip()

    @staticmethod
    def _build_reference_prompt_description(*, setting: str, appearance: str) -> str:
        if not appearance:
            return "设定：无设定"
        if setting:
            return f"设定：{setting}；描述：{appearance}"
        return f"描述：{appearance}"

    @staticmethod
    def _collect_reference_ids_with_image(reference_data: dict[str, Any]) -> set[str]:
        image_ids: set[str] = set()
        raw_reference_images = reference_data.get("reference_images")
        if not isinstance(raw_reference_images, list):
            return image_ids
        for item in raw_reference_images:
            if not isinstance(item, dict):
                continue
            reference_id = str(item.get("id") or "").strip()
            file_path = str(item.get("file_path") or "").strip()
            if reference_id and file_path:
                image_ids.add(reference_id)
        return image_ids

    @staticmethod
    def _resolve_duo_role_description_for_prompt(
        role: dict[str, Any],
        reference_by_id: dict[str, dict[str, str]],
    ) -> str:
        role_description = str(role.get("description") or "").strip()
        reference_id = FirstFrameDescHandler._resolve_role_reference_id(role)
        if not reference_id:
            return role_description or "无设定"
        reference = reference_by_id.get(reference_id) or {}
        reference_appearance = str(reference.get("appearance_description") or "").strip()
        if not reference_appearance:
            return "无设定"
        reference_setting = str(reference.get("setting") or "").strip()
        if role_description and role_description != reference_setting:
            return role_description
        return reference_setting or role_description or "无设定"

    @staticmethod
    def _normalize_duo_action_prompt_entities(
        action_prompt: str,
        role_1: dict[str, Any],
        role_2: dict[str, Any],
        scene_role: dict[str, Any],
        include_reference_identity: bool,
    ) -> str:
        text = str(action_prompt or "").strip()
        if not text:
            return ""

        role_1_ref = FirstFrameDescHandler._resolve_role_reference_id(role_1)
        role_2_ref = FirstFrameDescHandler._resolve_role_reference_id(role_2)
        scene_ref = FirstFrameDescHandler._resolve_role_reference_id(scene_role)

        role_1_target = (
            f"左侧角色（参考图{role_1_ref}）"
            if (include_reference_identity and role_1_ref)
            else "左侧角色"
        )
        role_2_target = (
            f"右侧角色（参考图{role_2_ref}）"
            if (include_reference_identity and role_2_ref)
            else "右侧角色"
        )
        scene_target = (
            f"参考图{scene_ref}" if (include_reference_identity and scene_ref) else "场景"
        )

        role_1_aliases = {
            str(role_1.get("name") or "").strip(),
            DUO_ROLE_1_DEFAULT_NAME,
        }
        role_2_aliases = {
            str(role_2.get("name") or "").strip(),
            DUO_ROLE_2_DEFAULT_NAME,
        }
        scene_alias = str(scene_role.get("name") or "").strip()

        for alias in role_1_aliases:
            if alias and alias != role_1_target:
                text = text.replace(alias, role_1_target)
        for alias in role_2_aliases:
            if alias and alias != role_2_target:
                text = text.replace(alias, role_2_target)
        if scene_alias and scene_alias not in {DUO_SCENE_ROLE_NAME, scene_target}:
            text = text.replace(scene_alias, scene_target)
        return text

    @staticmethod
    def _normalize_duo_first_frame_motion_level(action_text: str, target_language: str) -> str:
        text = str(action_text or "").strip()
        if not text:
            return text

        large_motion_keywords_zh = [
            "抬手",
            "举手",
            "挥手",
            "翻书",
            "掀页",
            "点数",
            "摊手",
            "耸肩",
            "前倾",
            "后仰",
            "侧身",
            "摆动",
            "挥舞",
            "快速",
            "抛出悬念",
            "做翻页动作",
            "做手势",
        ]
        lowered = text.lower()
        large_motion_keywords_en = [
            "wave",
            "raise hand",
            "flip",
            "count on fingers",
            "shrug",
            "lean forward",
            "lean back",
            "swing",
            "dramatic",
            "quickly",
        ]

        has_large_motion = any(keyword in text for keyword in large_motion_keywords_zh) or any(
            keyword in lowered for keyword in large_motion_keywords_en
        )
        if not has_large_motion:
            return text

        if target_language == "en":
            return (
                "Both side roles keep a normal seated pose, with only subtle expression differences "
                "and minimal head/eye movement."
            )
        return "左右两侧角色保持普通静坐，双手自然放松，仅保留轻微表情差异与极小幅度头部/目光变化。"

    def _compose_duo_podcast_first_frame_prompt(
        self,
        *,
        action_prompt: str,
        role_1: dict[str, Any],
        role_2: dict[str, Any],
        scene_role: dict[str, Any],
        references_by_id: dict[str, dict[str, str]],
        allowed_reference_ids: set[str] | None,
        include_reference_identity: bool,
        target_language: str,
    ) -> str:
        role_1_seat = self._format_duo_seat_side(role_1.get("seat_side"), "左")
        role_2_seat = self._format_duo_seat_side(role_2.get("seat_side"), "右")
        scene_name = (
            str(scene_role.get("name") or DUO_SCENE_ROLE_NAME).strip() or DUO_SCENE_ROLE_NAME
        )
        scene_description = str(scene_role.get("description") or "").strip()
        scene_description_text = (scene_description or scene_name).strip().rstrip("。.!！？!?")
        if not scene_description_text:
            scene_description_text = scene_name

        if target_language == "en":
            role_1_ref = self._resolve_usable_reference_id(role_1, allowed_reference_ids)
            role_2_ref = self._resolve_usable_reference_id(role_2, allowed_reference_ids)
            scene_ref = self._resolve_usable_reference_id(scene_role, allowed_reference_ids)
            reference_parts: list[str] = []
            if include_reference_identity and scene_ref:
                reference_parts.append(f"scene uses reference image {scene_ref}")
            if include_reference_identity and role_1_ref:
                reference_parts.append(f"{role_1_seat}-side role uses reference image {role_1_ref}")
            if include_reference_identity and role_2_ref:
                reference_parts.append(f"{role_2_seat}-side role uses reference image {role_2_ref}")
            reference_clause = f" {'; '.join(reference_parts)}." if reference_parts else ""
            return (
                f"Fixed front-facing two-host podcast frame: {scene_description_text}.{reference_clause} "
                "Both side roles are naturally seated facing microphones. "
                "Keep only subtle expression differences and minimal posture variation; avoid obvious gestures."
            )

        role_1_ref = self._resolve_usable_reference_id(role_1, allowed_reference_ids)
        role_2_ref = self._resolve_usable_reference_id(role_2, allowed_reference_ids)
        scene_ref = self._resolve_usable_reference_id(scene_role, allowed_reference_ids)
        scene_reference_clause = (
            f"，场景使用参考图{scene_ref}" if include_reference_identity and scene_ref else ""
        )
        role_reference_parts: list[str] = []
        if include_reference_identity and role_1_ref:
            role_reference_parts.append(f"画面{role_1_seat}侧角色使用参考图{role_1_ref}")
        if include_reference_identity and role_2_ref:
            role_reference_parts.append(f"画面{role_2_seat}侧角色使用参考图{role_2_ref}")
        role_reference_sentence = (
            f"{'，'.join(role_reference_parts)}。" if role_reference_parts else ""
        )
        return (
            f"固定双人播客同框正面画面：{scene_description_text}{scene_reference_clause}。"
            "两侧角色普通静坐并面向麦克风。"
            f"{role_reference_sentence}"
            "仅保留轻微表情差异与极小幅度姿态变化，禁止明显手势或大幅动作。"
        )

    def _is_shot_data_usable(self, output_data: Any) -> bool:
        return is_shot_data_usable(output_data)

    @staticmethod
    def _parse_json_response_text(response_text: str) -> dict[str, Any]:
        json_start = response_text.find("{")
        json_end = response_text.rfind("}") + 1
        if json_start == -1 or json_end <= json_start:
            raise StageValidationError("No JSON object found in response")

        json_fragment = response_text[json_start:json_end]
        try:
            parsed = json.loads(json_fragment)
        except json.JSONDecodeError as original_error:
            logger.warning(
                "[FirstFrameDesc] Invalid JSON detected, attempting json_repair fallback: %s",
                original_error,
            )
            try:
                parsed = repair_json_loads(json_fragment, skip_json_loads=True)
            except Exception as repair_error:  # noqa: BLE001
                raise StageValidationError(
                    f"JSON repair failed after parse error: {original_error}"
                ) from repair_error
            if not isinstance(parsed, dict):
                raise StageValidationError("JSON repair did not return an object")
            logger.info("[FirstFrameDesc] JSON repaired successfully via json_repair")
            return parsed

        if not isinstance(parsed, dict):
            raise StageValidationError("JSON response is not an object")
        return parsed

    def _pick_latest_usable_shot_data(
        self, stages: list[StageExecution]
    ) -> tuple[dict[str, Any] | None, Any]:
        for stage in stages:
            output_data = stage.output_data
            if self._is_shot_data_usable(output_data):
                return output_data, stage.updated_at
        return None, None
