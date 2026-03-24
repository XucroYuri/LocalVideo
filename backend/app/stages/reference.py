import logging
import re
import time as time_module
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.core.reference_voice import normalize_reference_voice_payload
from app.core.stream_json import extract_json_array_items
from app.llm.runtime import resolve_llm_runtime
from app.models.project import Project
from app.models.stage import StageExecution, StageType
from app.providers import get_image_provider
from app.stages.common.data_access import get_content_data
from app.stages.common.json_response import parse_json_response
from app.stages.common.log_utils import log_stage_separator
from app.stages.common.paths import (
    get_output_dir,
    resolve_path_for_io,
    resolve_stage_payload_for_io,
)

from . import register_stage
from ._generation_log import truncate_generation_text
from .base import StageHandler, StageResult
from .image_provider_utils import (
    get_provider_image_defaults,
    get_provider_kwargs,
    resolve_provider_runtime_name,
)
from .image_task_engine import (
    ImageTaskAdapter,
    ImageTaskRunSettings,
    ImageTaskSpec,
    run_image_tasks,
)
from .prompts import (
    REFERENCE_ANALYSIS_SYSTEM,
    REFERENCE_ANALYSIS_USER,
    format_prompt_complexity_for_log,
    format_target_language_for_log,
    get_reference_description_example,
    get_reference_description_length_requirement,
    get_reference_description_requirement,
    resolve_prompt_complexity,
    resolve_target_language,
)
from .vision import generate_description_from_image

logger = logging.getLogger(__name__)
CONTENT_REQUIRED_ERROR = "文案内容为空或不可用，请先生成或保存文案"
REFERENCE_INFO_REQUIRED_ERROR = "参考信息为空或不可用，请先生成或完善参考信息"
NO_IMAGE_STYLE_VALUES = {"", "__none__", "__empty__", "none", "null", "无"}

IMAGE_STYLE_TEMPLATES = {
    "semi_realistic_anime": """Generate a reference image based on this description:

{description}

Style requirements:
- Semi-realistic anime style (半写实动漫风格)
- High quality, detailed reference subject with smooth anime-like features
- Clean, simple gradient background suitable for video composition
- Soft, professional studio lighting
- Consistent art style: blend of realistic proportions with anime aesthetics
- All references should look like they belong in the same anime/game production
""",
    "anime": """Generate a reference image based on this description:

{description}

Style requirements:
- Japanese anime style (日系动漫风格)
- Bold outlines, vibrant colors, expressive eyes
- Clean, simple gradient background suitable for video composition
- Anime-style lighting with soft shadows
- Consistent anime art style throughout
- All references should look like they belong in the same anime series
""",
    "realistic": """Generate a reference image based on this description:

{description}

Style requirements:
- Photorealistic style (写实风格)
- High quality, detailed reference subject with realistic features
- Professional studio background, neutral tones
- Natural, professional lighting like a photography studio
- Realistic skin textures, natural proportions
- All references should have consistent realistic rendering
""",
    "cartoon": """Generate a reference image based on this description:

{description}

Style requirements:
- Western cartoon style (卡通风格)
- Stylized features, exaggerated expressions, bold colors
- Clean, colorful background suitable for video
- Bright, even lighting
- Consistent cartoon art style throughout
- All references should look like they belong in the same cartoon show
""",
    "watercolor": """Generate a reference image based on this description:

{description}

Style requirements:
- Watercolor painting style (水彩风格)
- Soft, flowing colors with visible brushstrokes
- Light, ethereal background with watercolor wash
- Soft, diffused lighting
- Artistic, painterly quality
- All references should have consistent watercolor aesthetics
""",
    "oil_painting": """Generate a reference image based on this description:

{description}

Style requirements:
- Oil painting style (油画风格)
- Rich, deep colors with visible brushwork and texture
- Classic art-studio background
- Dramatic lighting like Renaissance paintings
- Artistic, textured quality
- All references should have consistent oil painting aesthetics
""",
    "pixel_art": """Generate a reference image based on this description:

{description}

Style requirements:
- Pixel art style (像素风格)
- Retro video game aesthetic with visible pixels
- Simple, blocky background suitable for games
- Flat, even lighting
- 16-bit or 32-bit game art style
- All references should have consistent pixel art rendering
""",
    "cyberpunk": """Generate a reference image based on this description:

{description}

Style requirements:
- Cyberpunk style (赛博朋克)
- Neon colors, high contrast, futuristic aesthetic
- Dark urban background with neon accents
- Dramatic neon lighting, purple and cyan tones
- High-tech, dystopian atmosphere
- All references should fit the cyberpunk aesthetic
""",
}


def normalize_image_style(style: Any) -> str | None:
    if style is None:
        return None
    normalized = str(style).strip()
    if not normalized:
        return None
    if normalized.lower() in NO_IMAGE_STYLE_VALUES:
        return None
    return normalized


def get_image_prompt_template(style: str | None) -> str | None:
    normalized = normalize_image_style(style)
    if not normalized:
        return None
    return IMAGE_STYLE_TEMPLATES.get(normalized)


def _normalize_reference_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_reference_identity_key(value: Any) -> str:
    normalized = _normalize_reference_text(value).lower()
    if not normalized:
        return ""
    # Keep alphanumerics and CJK letters, remove separators/punctuation for stable dedupe.
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)


def _generate_next_reference_id(existing_ids: set[str]) -> str:
    index = 1
    while True:
        candidate = f"ref_{index:02d}"
        if candidate not in existing_ids:
            return candidate
        index += 1


def _format_existing_references_for_prompt(references: list[dict[str, Any]]) -> str:
    if not references:
        return "（当前无已存在参考）"

    lines: list[str] = []
    for item in references:
        reference_id = _normalize_reference_text(item.get("id"))
        name = _normalize_reference_text(item.get("name"))
        setting = _normalize_reference_text(item.get("setting"))
        appearance = _normalize_reference_text(item.get("appearance_description"))
        if len(appearance) > 120:
            appearance = f"{appearance[:120]}..."
        detail_parts = []
        if appearance:
            if setting:
                detail_parts.append(f"设定：{setting}")
            detail_parts.append(f"描述：{appearance}")
        else:
            detail_parts.append("设定：无设定")
            detail_parts.append("外观描述：无描述")
        detail_text = "；".join(detail_parts) if detail_parts else "无额外描述"
        lines.append(f"- {reference_id or '未知ID'} | {name or '未命名'} | {detail_text}")
    return "\n".join(lines)


def _normalize_reference_can_speak(
    value: Any, *, reference_name: str = "", reference_id: str = ""
) -> bool:
    if isinstance(value, bool):
        return value
    normalized_name = str(reference_name or "").strip().lower()
    if "场景" in normalized_name:
        return False
    return True


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


def normalize_reference_records(
    references_raw: Any,
    reference_images_raw: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized_references: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    raw_references = references_raw if isinstance(references_raw, list) else []
    for index, item in enumerate(raw_references):
        if not isinstance(item, dict):
            continue
        reference_id = _normalize_reference_text(item.get("id")) or f"ref_{index + 1:02d}"
        if reference_id in seen_ids:
            continue
        seen_ids.add(reference_id)
        setting = _normalize_reference_text(item.get("setting"))
        appearance_description = _normalize_reference_text(item.get("appearance_description"))
        normalized_name = (
            _normalize_reference_text(item.get("name")) or f"参考{len(normalized_references) + 1}"
        )
        can_speak = _normalize_reference_can_speak(
            item.get("can_speak"),
            reference_name=normalized_name,
            reference_id=reference_id,
        )
        library_reference_id = _normalize_library_reference_id(item.get("library_reference_id"))
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
        reference_id = _normalize_reference_text(item.get("id"))
        if not reference_id:
            continue
        image_by_id[reference_id] = dict(item)

    normalized_images: list[dict[str, Any]] = []
    for reference in normalized_references:
        reference_id = str(reference.get("id") or "")
        existing = image_by_id.get(reference_id, {})
        setting = _normalize_reference_text(existing.get("setting")) or _normalize_reference_text(
            reference.get("setting")
        )
        appearance_description = _normalize_reference_text(
            existing.get("appearance_description")
        ) or _normalize_reference_text(reference.get("appearance_description"))
        can_speak = _normalize_reference_can_speak(
            existing.get("can_speak", reference.get("can_speak")),
            reference_name=str(reference.get("name") or ""),
            reference_id=reference_id,
        )
        library_reference_id = _normalize_library_reference_id(
            existing.get("library_reference_id", reference.get("library_reference_id"))
        )
        voice_payload = normalize_reference_voice_payload(
            can_speak=can_speak,
            voice_audio_provider=existing.get(
                "voice_audio_provider",
                reference.get("voice_audio_provider"),
            ),
            voice_name=existing.get("voice_name", reference.get("voice_name")),
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


class ReferenceImageTaskAdapter(ImageTaskAdapter):
    def __init__(
        self,
        references: list[dict[str, Any]],
        provider_name: str,
        *,
        target_count: int = 0,
        image_exists_skipped_count: int = 0,
        missing_description_skipped_count: int = 0,
    ):
        self.references = references
        self.provider_name = provider_name
        self.target_count = max(0, int(target_count))
        self.image_exists_skipped_count = max(0, int(image_exists_skipped_count))
        self.missing_description_skipped_count = max(0, int(missing_description_skipped_count))

    def set_summary_counts(
        self,
        *,
        target_count: int,
        image_exists_skipped_count: int,
        missing_description_skipped_count: int,
    ) -> None:
        self.target_count = max(0, int(target_count))
        self.image_exists_skipped_count = max(0, int(image_exists_skipped_count))
        self.missing_description_skipped_count = max(0, int(missing_description_skipped_count))

    def build_missing_prompt_result(self, spec: ImageTaskSpec) -> dict[str, Any]:
        appearance_description = spec.payload["appearance_description"]
        return {
            "id": spec.payload["id"],
            "name": spec.payload["name"],
            "setting": spec.payload["setting"],
            "appearance_description": appearance_description,
            "can_speak": bool(spec.payload.get("can_speak", True)),
            "library_reference_id": spec.payload.get("library_reference_id"),
            "voice_audio_provider": spec.payload.get("voice_audio_provider"),
            "voice_name": spec.payload.get("voice_name"),
            "voice_speed": spec.payload.get("voice_speed"),
            "voice_wan2gp_preset": spec.payload.get("voice_wan2gp_preset"),
            "voice_wan2gp_alt_prompt": spec.payload.get("voice_wan2gp_alt_prompt"),
            "voice_wan2gp_audio_guide": spec.payload.get("voice_wan2gp_audio_guide"),
            "voice_wan2gp_temperature": spec.payload.get("voice_wan2gp_temperature"),
            "voice_wan2gp_top_k": spec.payload.get("voice_wan2gp_top_k"),
            "voice_wan2gp_seed": spec.payload.get("voice_wan2gp_seed"),
            "file_path": None,
            "generated": False,
            "skip_reason": "missing_description",
            "error": "No description available",
        }

    def build_success_result(self, spec: ImageTaskSpec, file_path: str) -> dict[str, Any]:
        appearance_description = spec.payload["appearance_description"]
        return {
            "id": spec.payload["id"],
            "name": spec.payload["name"],
            "setting": spec.payload["setting"],
            "appearance_description": appearance_description,
            "can_speak": bool(spec.payload.get("can_speak", True)),
            "library_reference_id": spec.payload.get("library_reference_id"),
            "voice_audio_provider": spec.payload.get("voice_audio_provider"),
            "voice_name": spec.payload.get("voice_name"),
            "voice_speed": spec.payload.get("voice_speed"),
            "voice_wan2gp_preset": spec.payload.get("voice_wan2gp_preset"),
            "voice_wan2gp_alt_prompt": spec.payload.get("voice_wan2gp_alt_prompt"),
            "voice_wan2gp_audio_guide": spec.payload.get("voice_wan2gp_audio_guide"),
            "voice_wan2gp_temperature": spec.payload.get("voice_wan2gp_temperature"),
            "voice_wan2gp_top_k": spec.payload.get("voice_wan2gp_top_k"),
            "voice_wan2gp_seed": spec.payload.get("voice_wan2gp_seed"),
            "file_path": file_path,
            "generated": True,
            "updated_at": int(time_module.time()),
        }

    def build_error_result(self, spec: ImageTaskSpec, error: str) -> dict[str, Any]:
        appearance_description = spec.payload["appearance_description"]
        return {
            "id": spec.payload["id"],
            "name": spec.payload["name"],
            "setting": spec.payload["setting"],
            "appearance_description": appearance_description,
            "can_speak": bool(spec.payload.get("can_speak", True)),
            "library_reference_id": spec.payload.get("library_reference_id"),
            "voice_audio_provider": spec.payload.get("voice_audio_provider"),
            "voice_name": spec.payload.get("voice_name"),
            "voice_speed": spec.payload.get("voice_speed"),
            "voice_wan2gp_preset": spec.payload.get("voice_wan2gp_preset"),
            "voice_wan2gp_alt_prompt": spec.payload.get("voice_wan2gp_alt_prompt"),
            "voice_wan2gp_audio_guide": spec.payload.get("voice_wan2gp_audio_guide"),
            "voice_wan2gp_temperature": spec.payload.get("voice_wan2gp_temperature"),
            "voice_wan2gp_top_k": spec.payload.get("voice_wan2gp_top_k"),
            "voice_wan2gp_seed": spec.payload.get("voice_wan2gp_seed"),
            "file_path": None,
            "generated": False,
            "error": error,
        }

    def build_stage_output(
        self,
        current_items: list[dict[str, Any]],
        generating_shots: dict[str, dict[str, Any]],
        provider_name: str,
        progress_message: str | None,
    ) -> dict[str, Any]:
        generated_count = sum(1 for item in current_items if item.get("generated"))
        output = {
            "references": self.references,
            "reference_images": current_items,
            "reference_count": len(self.references),
            "generated_count": generated_count,
            "target_count": self.target_count,
            "image_exists_skipped_count": self.image_exists_skipped_count,
            "missing_description_skipped_count": self.missing_description_skipped_count,
            "skipped_count": (
                self.image_exists_skipped_count + self.missing_description_skipped_count
            ),
            "generating_shots": generating_shots,
            "runtime_provider": provider_name,
            "image_provider": provider_name,
        }
        if progress_message and generating_shots:
            output["progress_message"] = progress_message
        return output

    def build_final_data(
        self,
        final_items: list[dict[str, Any]],
        failed_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        data = {
            "references": self.references,
            "reference_images": final_items,
            "reference_count": len(self.references),
            "generated_count": sum(1 for item in final_items if item.get("generated")),
            "target_count": self.target_count,
            "image_exists_skipped_count": self.image_exists_skipped_count,
            "missing_description_skipped_count": self.missing_description_skipped_count,
            "skipped_count": (
                self.image_exists_skipped_count + self.missing_description_skipped_count
            ),
            "runtime_provider": self.provider_name,
            "image_provider": self.provider_name,
        }
        if failed_items:
            data["failed_items"] = failed_items
        return data

    def build_partial_failure_error(self, failed_items: list[dict[str, Any]]) -> str:
        summary = "; ".join(
            f"Reference {item.get('item_key', item.get('item_index'))}: {item.get('error', 'Unknown error')}"
            for item in failed_items
        )
        return f"参考图生成失败: {summary}"


@register_stage(StageType.REFERENCE)
class ReferenceHandler(StageHandler):
    async def execute(
        self,
        db: AsyncSession,
        project: Project,
        stage: StageExecution,
        input_data: dict[str, Any] | None = None,
    ) -> StageResult:
        action = (input_data or {}).get("action", "generate_info")

        if action == "generate_info":
            return await self._generate_reference_info(db, project, stage, input_data)
        if action == "describe_from_image":
            return await self._describe_reference_from_image(db, project, stage, input_data)
        if action == "generate_images":
            return await self._generate_reference_images(db, project, stage, input_data)
        return StageResult(success=False, error=f"Unknown action: {action}")

    async def _generate_reference_info(
        self,
        db: AsyncSession,
        project: Project,
        stage: StageExecution,
        input_data: dict[str, Any] | None = None,
    ) -> StageResult:
        content_data = await self._get_content_data(db, project)
        if not content_data:
            return StageResult(success=False, error=CONTENT_REQUIRED_ERROR)

        try:
            llm_runtime = resolve_llm_runtime(input_data)
            llm_provider = llm_runtime.provider

            content = content_data.get("content", "")
            if not isinstance(content, str) or not content.strip():
                return StageResult(success=False, error=CONTENT_REQUIRED_ERROR)

            existing_output = stage.output_data or {}
            existing_refs, _ = normalize_reference_records(
                existing_output.get("references"),
                existing_output.get("reference_images"),
            )
            if not existing_refs:
                storyboard_data = await self._get_storyboard_data(db, project)
                if storyboard_data:
                    existing_refs, _ = normalize_reference_records(
                        storyboard_data.get("references"),
                        existing_output.get("reference_images"),
                    )

            target_language = resolve_target_language((input_data or {}).get("target_language"))
            target_language_log = format_target_language_for_log(target_language)
            prompt_complexity = resolve_prompt_complexity(
                (input_data or {}).get("prompt_complexity")
            )
            prompt_complexity_log = format_prompt_complexity_for_log(prompt_complexity)
            reference_prompt = REFERENCE_ANALYSIS_USER.format(
                content=content,
                existing_references=_format_existing_references_for_prompt(existing_refs),
                reference_description_requirement=get_reference_description_requirement(
                    target_language
                ),
                reference_description_length_requirement=get_reference_description_length_requirement(
                    target_language,
                    prompt_complexity,
                ),
                reference_description_example=get_reference_description_example(target_language),
            )
            log_stage_separator(logger)
            logger.info("[Reference] LLM Generate - Reference Info")
            logger.info(
                "[Input] llm_provider=%s(%s) llm_model=%s",
                llm_runtime.provider_name,
                llm_runtime.provider_type,
                llm_runtime.model,
            )
            logger.info("[Input] target_language=%s", target_language_log)
            logger.info("[Input] prompt_complexity=%s", prompt_complexity_log)
            logger.info("[Input] prompt: %s", truncate_generation_text(reference_prompt))
            logger.info(
                "[Input] system_prompt: %s",
                truncate_generation_text(REFERENCE_ANALYSIS_SYSTEM),
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
                logger.info("[Reference] LLM streaming enabled")
                chunks: list[str] = []
                chars_since_flush = 0
                try:
                    async for chunk in llm_provider.generate_stream(
                        prompt=reference_prompt,
                        system_prompt=REFERENCE_ANALYSIS_SYSTEM,
                        temperature=0.5,
                    ):
                        text = str(chunk or "")
                        if not text:
                            continue
                        chunks.append(text)
                        chars_since_flush += len(text)
                        if chars_since_flush < 500:
                            continue
                        await self._persist_reference_info_stream_progress(
                            db=db,
                            stage=stage,
                            existing_refs=existing_refs,
                            raw_text="".join(chunks),
                        )
                        chars_since_flush = 0
                    response_text = "".join(chunks).strip()
                except Exception as stream_err:  # noqa: BLE001
                    logger.warning(
                        "[Reference] LLM stream failed (%r), fallback to non-stream generate",
                        stream_err,
                    )

            if not response_text:
                reference_response = await llm_provider.generate(
                    prompt=reference_prompt,
                    system_prompt=REFERENCE_ANALYSIS_SYSTEM,
                    temperature=0.5,
                )
                response_text = reference_response.content

            logger.info(
                "[Output] response: %s",
                truncate_generation_text(response_text),
            )
            log_stage_separator(logger)

            reference_data = self._parse_json_response(response_text)
            raw_references = reference_data.get("references", [])
            mapped_new_references = self._map_new_references_from_raw(raw_references, existing_refs)
            combined_references = [*existing_refs, *mapped_new_references]
            references, reference_images = normalize_reference_records(
                combined_references,
                existing_output.get("reference_images"),
            )

            return StageResult(
                success=True,
                data={
                    "references": references,
                    "reference_images": reference_images,
                    "reference_count": len(references),
                    "new_reference_count": len(mapped_new_references),
                    "new_reference_ids": [
                        str(item.get("id") or "").strip()
                        for item in mapped_new_references
                        if str(item.get("id") or "").strip()
                    ],
                    "new_reference_names": [
                        str(item.get("name") or "").strip()
                        for item in mapped_new_references
                        if str(item.get("name") or "").strip()
                    ],
                },
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("[Reference] generate_info failed")
            return StageResult(success=False, error=str(e))

    @staticmethod
    def _map_new_references_from_raw(
        raw_references: Any,
        existing_refs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        mapped_new_references: list[dict[str, Any]] = []
        existing_reference_ids = {
            _normalize_reference_text(item.get("id"))
            for item in existing_refs
            if _normalize_reference_text(item.get("id"))
        }
        existing_name_keys = {
            _normalize_reference_identity_key(item.get("name"))
            for item in existing_refs
            if _normalize_reference_identity_key(item.get("name"))
        }
        existing_description_keys = {
            _normalize_reference_identity_key(item.get("appearance_description"))
            for item in existing_refs
            if _normalize_reference_identity_key(item.get("appearance_description"))
        }
        pending_name_keys: set[str] = set()
        pending_description_keys: set[str] = set()
        if not isinstance(raw_references, list):
            return mapped_new_references

        for item in raw_references:
            if not isinstance(item, dict):
                continue
            name = _normalize_reference_text(item.get("name")) or (
                f"参考{len(existing_refs) + len(mapped_new_references) + 1}"
            )
            name_key = _normalize_reference_identity_key(name)
            appearance_description = _normalize_reference_text(item.get("appearance_description"))
            description_key = _normalize_reference_identity_key(appearance_description)

            if (
                (name_key and name_key in existing_name_keys)
                or (description_key and description_key in existing_description_keys)
                or (name_key and name_key in pending_name_keys)
                or (description_key and description_key in pending_description_keys)
            ):
                continue

            reference_id = _generate_next_reference_id(existing_reference_ids)
            existing_reference_ids.add(reference_id)
            mapped_new_references.append(
                {
                    "id": reference_id,
                    "name": name,
                    "setting": _normalize_reference_text(item.get("setting")),
                    "appearance_description": appearance_description,
                    # Newly inferred references default to non-speaking.
                    "can_speak": False,
                }
            )
            if name_key:
                pending_name_keys.add(name_key)
            if description_key:
                pending_description_keys.add(description_key)
        return mapped_new_references

    async def _persist_reference_info_stream_progress(
        self,
        db: AsyncSession,
        stage: StageExecution,
        existing_refs: list[dict[str, Any]],
        raw_text: str,
    ) -> None:
        stage.progress = min(94, max(int(stage.progress or 0), 66 + min(len(raw_text) // 260, 22)))
        output_data = dict(resolve_stage_payload_for_io(stage.output_data) or {})
        output_data["partial_reference_raw"] = raw_text[-12000:]
        output_data["progress_message"] = "正在接收参考信息流式输出..."

        partial_items = extract_json_array_items(raw_text, "references")
        mapped_new_references = self._map_new_references_from_raw(partial_items, existing_refs)
        if mapped_new_references:
            output_data["partial_references"] = [*existing_refs, *mapped_new_references]

        stage.output_data = output_data
        flag_modified(stage, "output_data")
        await db.commit()

    async def _describe_reference_from_image(
        self,
        db: AsyncSession,
        project: Project,
        stage: StageExecution,
        input_data: dict[str, Any] | None = None,
    ) -> StageResult:
        output_data = dict(stage.output_data or {})
        references, reference_images = normalize_reference_records(
            output_data.get("references"),
            output_data.get("reference_images"),
        )
        if not references:
            return StageResult(success=False, error=REFERENCE_INFO_REQUIRED_ERROR)

        reference_id = str((input_data or {}).get("only_reference_id") or "").strip()
        if not reference_id:
            return StageResult(success=False, error="缺少 only_reference_id，无法从图生成描述")

        reference_index = -1
        for idx, reference in enumerate(references):
            if str(reference.get("id") or "").strip() == reference_id:
                reference_index = idx
                break
        if reference_index < 0:
            return StageResult(success=False, error=f"Reference {reference_id} not found")

        image_info = None
        image_index = -1
        for idx, item in enumerate(reference_images):
            if str(item.get("id") or "").strip() != reference_id:
                continue
            image_info = item
            image_index = idx
            break
        file_path = str((image_info or {}).get("file_path") or "").strip()
        if not file_path:
            return StageResult(
                success=False,
                error="Reference has no image. Upload an image first before generating description.",
            )
        resolved_image_path = resolve_path_for_io(file_path)
        if resolved_image_path is None or not resolved_image_path.exists():
            return StageResult(success=False, error="Reference image file not found")

        target_language = (input_data or {}).get("target_language")
        prompt_complexity = (input_data or {}).get("prompt_complexity")
        llm_provider = (input_data or {}).get("llm_provider")
        llm_model = (input_data or {}).get("llm_model")
        use_stream = str((input_data or {}).get("llm_stream", "1")).strip().lower() not in {
            "0",
            "false",
            "off",
            "no",
        }

        async def _on_stream_update(partial_description: str) -> None:
            await self._persist_reference_description_stream_progress(
                db=db,
                stage=stage,
                references=references,
                reference_id=reference_id,
                partial_description=partial_description,
            )

        try:
            description = await generate_description_from_image(
                file_path=str(resolved_image_path),
                target_language=target_language,
                prompt_complexity=prompt_complexity,
                llm_provider=str(llm_provider or "").strip() or None,
                llm_model=str(llm_model or "").strip() or None,
                use_stream=use_stream,
                on_stream_update=_on_stream_update if use_stream else None,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception(
                "[Reference] describe_from_image failed: reference_id=%s", reference_id
            )
            return StageResult(success=False, error=str(e))

        normalized_description = str(description or "").strip()
        references[reference_index]["appearance_description"] = normalized_description
        if image_index >= 0:
            reference_images[image_index]["appearance_description"] = normalized_description

        return StageResult(
            success=True,
            data={
                "references": references,
                "reference_images": reference_images,
                "reference_count": len(references),
                "described_reference_id": reference_id,
            },
        )

    async def _persist_reference_description_stream_progress(
        self,
        db: AsyncSession,
        stage: StageExecution,
        references: list[dict[str, Any]],
        reference_id: str,
        partial_description: str,
    ) -> None:
        normalized_partial = str(partial_description or "").strip()
        if not normalized_partial:
            return
        stage.progress = min(
            94, max(int(stage.progress or 0), 72 + min(len(normalized_partial) // 120, 18))
        )
        output_data = dict(stage.output_data or {})
        output_data["progress_message"] = "正在接收从图生成描述流式输出..."
        output_data["partial_reference_id"] = reference_id
        output_data["partial_reference_description"] = normalized_partial[-8000:]

        partial_references: list[dict[str, Any]] = []
        for item in references:
            if not isinstance(item, dict):
                continue
            next_item = dict(item)
            if str(next_item.get("id") or "").strip() == reference_id:
                next_item["appearance_description"] = normalized_partial
            partial_references.append(next_item)
        output_data["partial_references"] = partial_references

        stage.output_data = output_data
        flag_modified(stage, "output_data")
        await db.commit()

    async def _generate_reference_images(
        self,
        db: AsyncSession,
        project: Project,
        stage: StageExecution,
        input_data: dict[str, Any] | None = None,
    ) -> StageResult:
        existing_output = resolve_stage_payload_for_io(stage.output_data) or {}
        references, existing_images = normalize_reference_records(
            existing_output.get("references"),
            existing_output.get("reference_images"),
        )

        if not references:
            storyboard_data = await self._get_storyboard_data(db, project)
            if storyboard_data:
                references, existing_images = normalize_reference_records(
                    storyboard_data.get("references"),
                    existing_images,
                )

        if not references:
            return StageResult(success=False, error=REFERENCE_INFO_REQUIRED_ERROR)

        only_reference_id = (input_data or {}).get("only_reference_id")
        force_regenerate = bool((input_data or {}).get("force_regenerate", False))

        target_indices = list(range(len(references)))
        if only_reference_id is not None:
            matched_index = None
            for i, reference in enumerate(references):
                if str(reference.get("id")) == str(only_reference_id):
                    matched_index = i
                    break
            if matched_index is None:
                return StageResult(success=False, error=f"Reference {only_reference_id} not found")
            target_indices = [matched_index]

        provider_name = (input_data or {}).get("image_provider", settings.default_image_provider)
        image_aspect_ratio = (input_data or {}).get("image_aspect_ratio")
        image_size = (input_data or {}).get("image_size")
        image_resolution = (input_data or {}).get("image_resolution")

        default_aspect_ratio, default_size = get_provider_image_defaults(provider_name, "reference")
        if not image_aspect_ratio:
            image_aspect_ratio = default_aspect_ratio
        if not image_size:
            image_size = default_size
        if not image_resolution:
            image_resolution = settings.image_wan2gp_reference_resolution or "1024x1024"

        image_style = normalize_image_style((input_data or {}).get("image_style"))
        max_concurrency = int((input_data or {}).get("max_concurrency", 4))
        if provider_name == "wan2gp":
            max_concurrency = 1

        logger.info(
            "[Reference][Image] provider=%s model=%s style=%s target=%d only_reference_id=%s force=%s max_concurrency=%d",
            provider_name,
            (input_data or {}).get("image_model"),
            image_style,
            len(target_indices),
            only_reference_id,
            force_regenerate,
            max_concurrency,
        )

        provider_kwargs = get_provider_kwargs(provider_name, "reference", input_data=input_data)
        if provider_kwargs is None:
            return StageResult(
                success=False,
                error=f"Image provider '{provider_name}' is not configured.",
            )

        try:
            runtime_provider_name = resolve_provider_runtime_name(provider_name)
            image_provider = get_image_provider(runtime_provider_name, **provider_kwargs)
        except Exception as e:  # noqa: BLE001
            return StageResult(success=False, error=str(e))

        output_dir = self._get_output_dir(project)
        reference_dir = output_dir / "references"
        reference_dir.mkdir(parents=True, exist_ok=True)

        existing_images_by_id = {
            str(img.get("id")): img for img in existing_images if isinstance(img, dict)
        }

        all_results: list[dict[str, Any] | None] = [None] * len(references)
        for i, reference in enumerate(references):
            reference_id = str(reference.get("id", f"ref_{i + 1:02d}"))
            existing = existing_images_by_id.get(reference_id)
            if existing:
                all_results[i] = existing

        adapter = ReferenceImageTaskAdapter(references=references, provider_name=provider_name)
        task_specs: list[ImageTaskSpec] = []
        prompt_template = get_image_prompt_template(image_style)
        target_count = len(target_indices)
        image_exists_skipped_count = 0
        missing_description_skipped_count = 0
        for i in target_indices:
            reference = references[i]
            reference_id = str(reference.get("id", f"ref_{i + 1:02d}"))
            reference_name = reference.get("name", f"Reference {i + 1}")
            reference_setting = str(reference.get("setting", "") or "")
            reference_appearance_desc = str(reference.get("appearance_description") or "")

            existing = existing_images_by_id.get(reference_id)
            existing_file_path = (
                str(existing.get("file_path") or "").strip() if isinstance(existing, dict) else ""
            )
            existing_file = resolve_path_for_io(existing_file_path)
            has_existing_image = (
                not force_regenerate
                and existing is not None
                and bool(existing_file_path)
                and existing_file is not None
                and existing_file.exists()
            )
            missing_description = (not has_existing_image) and (
                not reference_appearance_desc.strip()
            )
            if has_existing_image:
                image_exists_skipped_count += 1
            elif missing_description:
                missing_description_skipped_count += 1

            spec = ImageTaskSpec(
                index=i,
                key=reference_id,
                prompt=(
                    (
                        prompt_template.format(description=reference_appearance_desc)
                        if prompt_template
                        else reference_appearance_desc
                    )
                    if reference_appearance_desc.strip()
                    else ""
                ),
                output_path=reference_dir / f"{reference_id}.png",
                skip=(has_existing_image or missing_description),
                payload={
                    "id": reference_id,
                    "name": reference_name,
                    "setting": reference_setting,
                    "appearance_description": reference_appearance_desc,
                    "can_speak": bool(reference.get("can_speak", True)),
                    "library_reference_id": reference.get("library_reference_id"),
                    "voice_audio_provider": reference.get("voice_audio_provider"),
                    "voice_name": reference.get("voice_name"),
                    "voice_speed": reference.get("voice_speed"),
                    "voice_wan2gp_preset": reference.get("voice_wan2gp_preset"),
                    "voice_wan2gp_alt_prompt": reference.get("voice_wan2gp_alt_prompt"),
                    "voice_wan2gp_audio_guide": reference.get("voice_wan2gp_audio_guide"),
                    "voice_wan2gp_temperature": reference.get("voice_wan2gp_temperature"),
                    "voice_wan2gp_top_k": reference.get("voice_wan2gp_top_k"),
                    "voice_wan2gp_seed": reference.get("voice_wan2gp_seed"),
                },
            )
            task_specs.append(spec)
            if missing_description:
                all_results[i] = adapter.build_missing_prompt_result(spec)

        adapter.set_summary_counts(
            target_count=target_count,
            image_exists_skipped_count=image_exists_skipped_count,
            missing_description_skipped_count=missing_description_skipped_count,
        )
        to_generate_count = max(
            0,
            target_count - image_exists_skipped_count - missing_description_skipped_count,
        )
        logger.info(
            "[Reference][Image] Summary target=%d to_generate=%d skip_image_exists=%d skip_missing_description=%d",
            target_count,
            to_generate_count,
            image_exists_skipped_count,
            missing_description_skipped_count,
        )
        run_settings = ImageTaskRunSettings(
            provider_name=provider_name,
            image_provider=image_provider,
            max_concurrency=max_concurrency,
            image_aspect_ratio=image_aspect_ratio,
            image_size=image_size,
            image_resolution=image_resolution,
            force_regenerate=force_regenerate,
            allow_wan2gp_batch=True,
            fail_on_partial=True,
        )

        result = await run_image_tasks(
            db=db,
            stage=stage,
            task_specs=task_specs,
            all_results=all_results,
            adapter=adapter,
            settings=run_settings,
        )
        failed_count = 0
        if isinstance(result.data, dict):
            failed_items = result.data.get("failed_items")
            if isinstance(failed_items, list):
                failed_count = len(failed_items)
        logger.info(
            "[Reference][Image] Result completed=%d failed=%d skip_image_exists=%d skip_missing_description=%d status=%s",
            int(stage.completed_items or 0),
            failed_count,
            image_exists_skipped_count,
            missing_description_skipped_count,
            "success" if result.success else "failed",
        )
        return result

    def _parse_json_response(self, content: str) -> dict[str, Any]:
        return parse_json_response(content)

    def _get_output_dir(self, project: Project) -> Path:
        return get_output_dir(project)

    async def _get_content_data(self, db: AsyncSession, project: Project) -> dict[str, Any] | None:
        return await get_content_data(db, project.id)

    async def _get_storyboard_data(
        self, db: AsyncSession, project: Project
    ) -> dict[str, Any] | None:
        result = await db.execute(
            select(StageExecution)
            .where(
                StageExecution.project_id == project.id,
                StageExecution.stage_type == StageType.STORYBOARD,
            )
            .order_by(StageExecution.updated_at.desc(), StageExecution.id.desc())
        )
        for storyboard_stage in result.scalars():
            output_data = resolve_stage_payload_for_io(storyboard_stage.output_data) or {}
            references = output_data.get("references")
            if isinstance(references, list) and references:
                return output_data
        return None

    async def validate_prerequisites(
        self,
        db: AsyncSession,
        project: Project,
    ) -> str | None:
        content_data = await self._get_content_data(db, project)
        if not content_data:
            return CONTENT_REQUIRED_ERROR
        return None
