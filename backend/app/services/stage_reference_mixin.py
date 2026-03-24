import logging
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import ServiceError
from app.core.media_file import ALLOWED_IMAGE_TYPES, safe_delete_file
from app.core.pipeline import PipelineEngine
from app.core.project_mode import resolve_script_mode_from_video_type
from app.core.reference_voice import normalize_reference_voice_payload
from app.models.reference_library import ReferenceLibraryItem
from app.models.stage import StageExecution, StageStatus, StageType
from app.stages.common.paths import resolve_path_for_io
from app.stages.vision import generate_description_from_image

logger = logging.getLogger(__name__)


class StageReferenceMixin:
    def _generate_reference_id(self, existing_references: list) -> str:
        existing_ids = set()
        for reference in existing_references:
            reference_id = str(reference.get("id", ""))
            if reference_id.startswith("ref_"):
                try:
                    num = int(reference_id.split("_")[1])
                    existing_ids.add(num)
                except (ValueError, IndexError):
                    pass

        next_num = 1
        while next_num in existing_ids:
            next_num += 1
        return f"ref_{next_num:02d}"

    def _build_unique_reference_name(
        self, base_name: str, existing_names: set[str]
    ) -> tuple[str, bool]:
        normalized_base = self._normalize_reference_text(base_name) or "未命名参考"
        candidate = normalized_base
        if candidate.lower() not in existing_names:
            return candidate, False

        suffix = "（导入）"
        candidate = f"{normalized_base}{suffix}"
        if candidate.lower() not in existing_names:
            return candidate, True

        idx = 2
        while True:
            candidate = f"{normalized_base}{suffix}{idx}"
            if candidate.lower() not in existing_names:
                return candidate, True
            idx += 1

    async def update_reference(
        self,
        project_id: int,
        reference_id: str,
        request: Any,
    ):
        project = await self.get_project_or_404(project_id)
        normalized_name = self._normalize_reference_text(request.name)
        if not normalized_name:
            raise ServiceError(400, "Reference name cannot be empty")
        normalized_setting = self._normalize_reference_text(request.setting)
        normalized_appearance = self._normalize_reference_text(request.appearance_description)

        result = await self.db.execute(
            select(StageExecution).where(
                StageExecution.project_id == project_id,
                StageExecution.stage_type == StageType.REFERENCE,
            )
        )
        stage = result.scalar_one_or_none()
        if not stage:
            raise ServiceError(404, "Reference stage not found")

        output_data = dict(stage.output_data or {})
        references, reference_images = self._normalize_reference_records(
            output_data.get("references"),
            output_data.get("reference_images"),
        )

        reference_found = False
        resolved_voice_payload: dict[str, Any] = {}
        for reference in references:
            if str(reference.get("id")) == str(reference_id):
                normalized_voice_payload = normalize_reference_voice_payload(
                    can_speak=bool(request.can_speak),
                    voice_audio_provider=(
                        request.voice_audio_provider
                        if request.voice_audio_provider is not None
                        else reference.get("voice_audio_provider")
                    ),
                    voice_name=(
                        request.voice_name
                        if request.voice_name is not None
                        else reference.get("voice_name")
                    ),
                    voice_speed=(
                        request.voice_speed
                        if request.voice_speed is not None
                        else reference.get("voice_speed")
                    ),
                    voice_wan2gp_preset=(
                        request.voice_wan2gp_preset
                        if request.voice_wan2gp_preset is not None
                        else reference.get("voice_wan2gp_preset")
                    ),
                    voice_wan2gp_alt_prompt=(
                        request.voice_wan2gp_alt_prompt
                        if request.voice_wan2gp_alt_prompt is not None
                        else reference.get("voice_wan2gp_alt_prompt")
                    ),
                    voice_wan2gp_audio_guide=(
                        request.voice_wan2gp_audio_guide
                        if request.voice_wan2gp_audio_guide is not None
                        else reference.get("voice_wan2gp_audio_guide")
                    ),
                    voice_wan2gp_temperature=(
                        request.voice_wan2gp_temperature
                        if request.voice_wan2gp_temperature is not None
                        else reference.get("voice_wan2gp_temperature")
                    ),
                    voice_wan2gp_top_k=(
                        request.voice_wan2gp_top_k
                        if request.voice_wan2gp_top_k is not None
                        else reference.get("voice_wan2gp_top_k")
                    ),
                    voice_wan2gp_seed=(
                        request.voice_wan2gp_seed
                        if request.voice_wan2gp_seed is not None
                        else reference.get("voice_wan2gp_seed")
                    ),
                )
                reference["name"] = normalized_name
                reference["setting"] = normalized_setting
                reference["appearance_description"] = normalized_appearance
                reference["can_speak"] = bool(request.can_speak)
                reference.update(normalized_voice_payload)
                resolved_voice_payload = normalized_voice_payload
                reference_found = True
                break

        for img in reference_images:
            if str(img.get("id")) == str(reference_id):
                img["name"] = normalized_name
                img["setting"] = normalized_setting
                img["appearance_description"] = normalized_appearance
                img["can_speak"] = bool(request.can_speak)
                img.update(resolved_voice_payload)
                break

        if not reference_found:
            raise ServiceError(404, f"Reference {reference_id} not found")

        output_data["references"] = references
        output_data["reference_images"] = reference_images
        output_data["reference_count"] = len(references)
        stage.output_data = output_data
        flag_modified(stage, "output_data")

        await self._sync_content_stage_after_reference_change(project, create_missing=False)
        await self.db.commit()
        await self.db.refresh(stage)

        return {"success": True, "data": stage.output_data}

    async def delete_reference(self, project_id: int, reference_id: str):
        project = await self.get_project_or_404(project_id)
        normalized_reference_id = str(reference_id or "").strip()

        result = await self.db.execute(
            select(StageExecution).where(
                StageExecution.project_id == project_id,
                StageExecution.stage_type == StageType.REFERENCE,
            )
        )
        stage = result.scalar_one_or_none()
        if not stage:
            raise ServiceError(404, "Reference stage not found")

        output_data = dict(stage.output_data or {})
        references, reference_images = self._normalize_reference_records(
            output_data.get("references"),
            output_data.get("reference_images"),
        )

        script_mode = resolve_script_mode_from_video_type(project.video_type)
        locked_reference_ids: set[str] = set()

        if script_mode == "single":
            for reference in references[:1]:
                reference_id_text = str(reference.get("id") or "").strip()
                if reference_id_text:
                    locked_reference_ids.add(reference_id_text)
        elif script_mode == "duo_podcast":
            for reference in references[:3]:
                reference_id_text = str(reference.get("id") or "").strip()
                if reference_id_text:
                    locked_reference_ids.add(reference_id_text)

        if normalized_reference_id in locked_reference_ids:
            if script_mode == "single":
                raise ServiceError(400, "单人叙述模式下，首个参考固定为讲述者，不能删除")
            if script_mode == "duo_podcast":
                if (
                    references[:3]
                    and normalized_reference_id == str(references[2].get("id") or "").strip()
                ):
                    raise ServiceError(400, "双人播客模式下，播客场景参考固定，不能删除")
                raise ServiceError(
                    400, "双人播客模式下，前3个参考固定为左角色、右角色和播客场景，不能删除"
                )

        deleted_file_path = None
        for img in reference_images:
            if str(img.get("id") or "").strip() == normalized_reference_id:
                deleted_file_path = img.get("file_path")
                break

        original_len = len(references)
        references = [
            reference
            for reference in references
            if str(reference.get("id") or "").strip() != normalized_reference_id
        ]
        reference_images = [
            image
            for image in reference_images
            if str(image.get("id") or "").strip() != normalized_reference_id
        ]

        if len(references) == original_len:
            raise ServiceError(404, f"Reference {reference_id} not found")

        safe_delete_file(deleted_file_path)

        output_data["references"] = references
        output_data["reference_images"] = reference_images
        output_data["reference_count"] = len(references)

        stage.output_data = output_data
        flag_modified(stage, "output_data")

        await self._sync_content_stage_after_reference_change(project, create_missing=False)
        await self.db.commit()
        await self.db.refresh(stage)

        return {"success": True, "data": stage.output_data}

    async def import_references_from_library(
        self,
        project_id: int,
        library_reference_ids: list[int],
        start_reference_index: int = 0,
        import_setting: bool = True,
        import_appearance_description: bool = True,
        import_image: bool = True,
        import_voice: bool = True,
    ) -> dict[str, Any]:
        if not library_reference_ids:
            raise ServiceError(400, "No library references selected")

        project = await self.get_project_or_404(project_id)
        reference_stage = await self._get_or_create_reference_stage_for_sync(project)
        output_data = dict(reference_stage.output_data or {})
        references, reference_images = self._normalize_reference_records(
            output_data.get("references"),
            output_data.get("reference_images"),
        )

        try:
            normalized_start_index = int(start_reference_index)
        except (TypeError, ValueError):
            normalized_start_index = 0
        if normalized_start_index < 0:
            normalized_start_index = 0
        script_mode = resolve_script_mode_from_video_type(project.video_type)
        locked_narrator_slots = (
            2 if script_mode == "duo_podcast" else (1 if script_mode == "single" else 0)
        )

        unique_ids = list(dict.fromkeys(int(item) for item in library_reference_ids))
        item_result = await self.db.execute(
            select(ReferenceLibraryItem).where(ReferenceLibraryItem.id.in_(unique_ids))
        )
        library_item_map = {item.id: item for item in item_result.scalars().all()}

        existing_reference_ids_by_library_id = {
            int(normalized_library_id): str(ref.get("id"))
            for ref in references
            for normalized_library_id in [
                self._normalize_library_reference_id(ref.get("library_reference_id"))
            ]
            if normalized_library_id is not None
        }
        existing_names = {
            self._normalize_reference_text(ref.get("name")).lower()
            for ref in references
            if self._normalize_reference_text(ref.get("name"))
        }
        reference_images_by_id = {str(item.get("id")): dict(item) for item in reference_images}

        output_dir = self._get_output_dir(project)
        reference_dir = output_dir / "references"
        if import_image:
            reference_dir.mkdir(parents=True, exist_ok=True)

        results: list[dict[str, Any]] = []
        created_count = 0
        skipped_count = 0
        failed_count = 0
        processed_request_ids: set[int] = set()
        overwrite_count = 0

        overwrite_slots = references[
            normalized_start_index : normalized_start_index + len(library_reference_ids)
        ]
        overwrite_reference_ids = {
            str(item.get("id")) for item in overwrite_slots if item.get("id")
        }

        for request_offset, raw_library_id in enumerate(library_reference_ids):
            library_id = int(raw_library_id)
            target_index = normalized_start_index + request_offset
            target_reference = (
                references[target_index] if 0 <= target_index < len(references) else None
            )
            target_reference_id = str(target_reference.get("id") or "") if target_reference else ""

            if library_id in processed_request_ids:
                skipped_count += 1
                results.append(
                    {
                        "library_reference_id": library_id,
                        "library_name": None,
                        "status": "skipped",
                        "project_reference_id": None,
                        "code": "DUPLICATE_IN_REQUEST",
                        "message": "同一导入请求中重复选择，已跳过重复项",
                        "warnings": [],
                    }
                )
                continue
            processed_request_ids.add(library_id)

            library_item = library_item_map.get(library_id)
            if not library_item:
                failed_count += 1
                results.append(
                    {
                        "library_reference_id": library_id,
                        "library_name": None,
                        "status": "failed",
                        "project_reference_id": None,
                        "code": "LIBRARY_REFERENCE_NOT_FOUND",
                        "message": "参考库条目不存在",
                        "warnings": [],
                    }
                )
                continue
            if not bool(getattr(library_item, "is_enabled", True)):
                skipped_count += 1
                results.append(
                    {
                        "library_reference_id": library_id,
                        "library_name": library_item.name,
                        "status": "skipped",
                        "project_reference_id": None,
                        "code": "LIBRARY_REFERENCE_DISABLED",
                        "message": "参考库条目已禁用，已跳过",
                        "warnings": [],
                    }
                )
                continue

            existing_reference_id = existing_reference_ids_by_library_id.get(library_id)
            # Append mode keeps global de-duplication, but overwrite mode must respect
            # the user's explicit position replacement request.
            if (
                existing_reference_id
                and target_reference is None
                and existing_reference_id not in overwrite_reference_ids
            ):
                skipped_count += 1
                results.append(
                    {
                        "library_reference_id": library_id,
                        "library_name": library_item.name,
                        "status": "skipped",
                        "project_reference_id": existing_reference_id,
                        "code": "ALREADY_IMPORTED",
                        "message": "该参考已导入到当前项目，已跳过",
                        "warnings": [],
                    }
                )
                continue

            warnings: list[str] = []
            target_existing_name = (
                self._normalize_reference_text(target_reference.get("name"))
                if target_reference
                else ""
            )
            existing_names_for_slot = set(existing_names)
            if target_existing_name:
                existing_names_for_slot.discard(target_existing_name.lower())

            final_name, renamed = self._build_unique_reference_name(
                library_item.name, existing_names_for_slot
            )
            if renamed:
                warnings.append("NAME_CONFLICT_RENAMED")
            if target_existing_name:
                existing_names.discard(target_existing_name.lower())
            existing_names.add(final_name.lower())

            if target_reference:
                reference_id = target_reference_id
            else:
                reference_id = self._generate_reference_id(references)

            library_setting = self._normalize_reference_text(library_item.setting)
            library_appearance = self._normalize_reference_text(library_item.appearance_description)
            if target_reference:
                final_setting = (
                    library_setting
                    if import_setting
                    else self._normalize_reference_text(target_reference.get("setting"))
                )
                final_appearance = (
                    library_appearance
                    if import_appearance_description
                    else self._normalize_reference_text(
                        target_reference.get("appearance_description")
                    )
                )
            else:
                final_setting = library_setting if import_setting else ""
                final_appearance = library_appearance if import_appearance_description else ""
            final_can_speak = bool(library_item.can_speak)
            if target_index < locked_narrator_slots and not final_can_speak:
                failed_count += 1
                results.append(
                    {
                        "library_reference_id": library_id,
                        "library_name": library_item.name,
                        "status": "failed",
                        "project_reference_id": target_reference_id or None,
                        "code": "NARRATOR_SLOT_REQUIRES_SPEAKABLE",
                        "message": (
                            f"第 {target_index + 1} 个位置为讲述者固定槽位，仅允许导入可说台词的参考"
                        ),
                        "warnings": [],
                    }
                )
                continue
            existing_voice_reference = target_reference or {}
            final_voice_payload = normalize_reference_voice_payload(
                can_speak=final_can_speak,
                voice_audio_provider=(
                    library_item.voice_audio_provider
                    if import_voice
                    else existing_voice_reference.get("voice_audio_provider")
                ),
                voice_name=(
                    library_item.voice_name
                    if import_voice
                    else existing_voice_reference.get("voice_name")
                ),
                voice_speed=(
                    library_item.voice_speed
                    if import_voice
                    else existing_voice_reference.get("voice_speed")
                ),
                voice_wan2gp_preset=(
                    library_item.voice_wan2gp_preset
                    if import_voice
                    else existing_voice_reference.get("voice_wan2gp_preset")
                ),
                voice_wan2gp_alt_prompt=(
                    library_item.voice_wan2gp_alt_prompt
                    if import_voice
                    else existing_voice_reference.get("voice_wan2gp_alt_prompt")
                ),
                voice_wan2gp_audio_guide=(
                    library_item.voice_wan2gp_audio_guide
                    if import_voice
                    else existing_voice_reference.get("voice_wan2gp_audio_guide")
                ),
                voice_wan2gp_temperature=(
                    library_item.voice_wan2gp_temperature
                    if import_voice
                    else existing_voice_reference.get("voice_wan2gp_temperature")
                ),
                voice_wan2gp_top_k=(
                    library_item.voice_wan2gp_top_k
                    if import_voice
                    else existing_voice_reference.get("voice_wan2gp_top_k")
                ),
                voice_wan2gp_seed=(
                    library_item.voice_wan2gp_seed
                    if import_voice
                    else existing_voice_reference.get("voice_wan2gp_seed")
                ),
            )
            if (
                import_voice
                and final_can_speak
                and (
                    not final_voice_payload.get("voice_audio_provider")
                    or not final_voice_payload.get("voice_name")
                )
            ):
                warnings.append("VOICE_MISSING")

            reference_payload = {
                "id": reference_id,
                "name": final_name,
                "setting": final_setting,
                "appearance_description": final_appearance,
                "can_speak": final_can_speak,
                "library_reference_id": library_id,
                **final_voice_payload,
            }
            if target_reference:
                references[target_index] = reference_payload
            else:
                references.append(reference_payload)

            target_file_path: str | None = None
            existing_image_payload = reference_images_by_id.get(reference_id) or {}
            existing_image_path = self._normalize_reference_text(
                existing_image_payload.get("file_path")
            )
            target_file_path = existing_image_path if target_reference else None
            if import_image:
                source_path_text = self._normalize_reference_text(library_item.image_file_path)
                if not source_path_text:
                    warnings.append("IMAGE_MISSING")
                else:
                    source_path = resolve_path_for_io(source_path_text) or Path(source_path_text)
                    if not source_path.exists():
                        warnings.append("IMAGE_FILE_NOT_FOUND")
                    else:
                        ext = source_path.suffix.lower().lstrip(".")
                        if ext == "jpeg":
                            ext = "jpg"
                        if ext not in {"png", "jpg", "webp"}:
                            ext = "png"
                        target_path = reference_dir / f"{reference_id}.{ext}"
                        try:
                            shutil.copy2(source_path, target_path)
                            target_file_path = str(target_path)
                        except Exception as e:  # noqa: BLE001
                            logger.exception(
                                "Failed to copy library reference image: library_id=%s target_ref=%s",
                                library_id,
                                reference_id,
                            )
                            warnings.append(f"IMAGE_COPY_FAILED:{e}")

            image_payload = reference_images_by_id.get(reference_id) or {
                "id": reference_id,
            }
            image_payload.update(
                {
                    "id": reference_id,
                    "name": final_name,
                    "setting": final_setting,
                    "appearance_description": final_appearance,
                    "can_speak": final_can_speak,
                    "library_reference_id": library_id,
                    **final_voice_payload,
                    "file_path": target_file_path,
                    "generated": False,
                    "uploaded": bool(target_file_path)
                    or bool(image_payload.get("uploaded", False)),
                    "updated_at": int(time.time())
                    if target_file_path
                    else image_payload.get("updated_at"),
                    "error": None,
                }
            )
            reference_images_by_id[reference_id] = image_payload

            if target_reference:
                overwrite_count += 1
                old_library_reference_id = self._normalize_library_reference_id(
                    target_reference.get("library_reference_id")
                )
                if (
                    old_library_reference_id is not None
                    and existing_reference_ids_by_library_id.get(old_library_reference_id)
                    == reference_id
                    and old_library_reference_id != library_id
                ):
                    existing_reference_ids_by_library_id.pop(old_library_reference_id, None)
                existing_reference_ids_by_library_id[library_id] = reference_id
            else:
                existing_reference_ids_by_library_id[library_id] = reference_id

            created_count += 1
            results.append(
                {
                    "library_reference_id": library_id,
                    "library_name": library_item.name,
                    "status": "created",
                    "project_reference_id": reference_id,
                    "code": "IMPORTED_OVERWRITE" if target_reference else "IMPORTED",
                    "message": ("覆盖成功" if target_reference else "导入成功")
                    if not warnings
                    else ("覆盖成功（含警告）" if target_reference else "导入成功（含警告）"),
                    "warnings": warnings,
                }
            )

        reference_images = list(reference_images_by_id.values())
        references, reference_images = self._normalize_reference_records(
            references, reference_images
        )

        output_data["references"] = references
        output_data["reference_images"] = reference_images
        output_data["reference_count"] = len(references)
        reference_stage.output_data = output_data
        flag_modified(reference_stage, "output_data")

        await self._sync_content_stage_after_reference_change(project, create_missing=False)
        await self.db.commit()
        await self.db.refresh(reference_stage)

        return {
            "success": True,
            "summary": {
                "requested_count": len(library_reference_ids),
                "created_count": created_count,
                "overwritten_count": overwrite_count,
                "skipped_count": skipped_count,
                "failed_count": failed_count,
            },
            "results": results,
            "data": reference_stage.output_data,
        }

    async def create_reference(
        self,
        project_id: int,
        form: Any,
        file: UploadFile | None,
    ):
        if file and file.content_type not in ALLOWED_IMAGE_TYPES:
            raise ServiceError(
                400,
                f"File type '{file.content_type}' not allowed. Allowed types: PNG, JPEG, WebP",
            )

        project = await self.get_project_or_404(project_id)
        normalized_name = self._normalize_reference_text(form.name)
        if not normalized_name:
            raise ServiceError(400, "Reference name cannot be empty")
        normalized_setting = self._normalize_reference_text(form.setting)
        normalized_appearance = self._normalize_reference_text(form.appearance_description)
        normalized_voice_payload = normalize_reference_voice_payload(
            can_speak=bool(form.can_speak),
            voice_audio_provider=form.voice_audio_provider,
            voice_name=form.voice_name,
            voice_speed=form.voice_speed,
            voice_wan2gp_preset=form.voice_wan2gp_preset,
            voice_wan2gp_alt_prompt=form.voice_wan2gp_alt_prompt,
            voice_wan2gp_audio_guide=form.voice_wan2gp_audio_guide,
            voice_wan2gp_temperature=form.voice_wan2gp_temperature,
            voice_wan2gp_top_k=form.voice_wan2gp_top_k,
            voice_wan2gp_seed=form.voice_wan2gp_seed,
        )

        result = await self.db.execute(
            select(StageExecution).where(
                StageExecution.project_id == project_id,
                StageExecution.stage_type == StageType.REFERENCE,
            )
        )
        stage = result.scalar_one_or_none()

        if not stage:
            pipeline = PipelineEngine(self.db, project)
            stage = StageExecution(
                project_id=project_id,
                stage_type=StageType.REFERENCE,
                stage_number=pipeline.get_stage_number(StageType.REFERENCE),
                status=StageStatus.COMPLETED,
                progress=100,
                output_data={"references": [], "reference_images": [], "reference_count": 0},
            )
            self.db.add(stage)
            await self.db.commit()
            await self.db.refresh(stage)

        output_data = dict(stage.output_data or {})
        references, reference_images = self._normalize_reference_records(
            output_data.get("references"),
            output_data.get("reference_images"),
        )

        reference_id = self._generate_reference_id(references)

        new_reference = {
            "id": reference_id,
            "name": normalized_name,
            "setting": normalized_setting,
            "appearance_description": normalized_appearance,
            "can_speak": bool(form.can_speak),
            "library_reference_id": None,
            **normalized_voice_payload,
        }
        references.append(new_reference)

        file_path = None
        if file:
            ext_map = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
            ext = ext_map.get(file.content_type, "png")

            output_dir = self._get_output_dir(project)
            reference_dir = output_dir / "references"
            reference_dir.mkdir(parents=True, exist_ok=True)

            output_path = reference_dir / f"{reference_id}.{ext}"

            try:
                content = await file.read()
                with open(output_path, "wb") as f:
                    f.write(content)
                file_path = str(output_path)
            except Exception as e:
                raise ServiceError(500, f"Failed to save file: {str(e)}")

        new_image_data = {
            "id": reference_id,
            "name": normalized_name,
            "setting": normalized_setting,
            "appearance_description": normalized_appearance,
            "can_speak": bool(form.can_speak),
            "library_reference_id": None,
            **normalized_voice_payload,
            "file_path": file_path,
            "generated": False,
            "uploaded": bool(file_path),
        }
        reference_images.append(new_image_data)

        output_data["references"] = references
        output_data["reference_images"] = reference_images
        output_data["reference_count"] = len(references)

        stage.output_data = output_data
        flag_modified(stage, "output_data")

        await self._sync_content_stage_after_reference_change(project, create_missing=False)
        await self.db.commit()
        await self.db.refresh(stage)

        return {"success": True, "data": new_image_data, "reference_id": reference_id}

    async def describe_reference_from_image(
        self,
        project_id: int,
        reference_id: str,
        target_language: str | None = None,
        prompt_complexity: str | None = None,
        llm_provider: str | None = None,
        llm_model: str | None = None,
    ):
        project = await self.get_project_or_404(project_id)

        result = await self.db.execute(
            select(StageExecution).where(
                StageExecution.project_id == project_id,
                StageExecution.stage_type == StageType.REFERENCE,
            )
        )
        stage = result.scalar_one_or_none()
        if not stage:
            raise ServiceError(404, "Reference stage not found")

        output_data = dict(stage.output_data or {})
        references, reference_images = self._normalize_reference_records(
            output_data.get("references"),
            output_data.get("reference_images"),
        )

        reference = None
        reference_idx = -1
        for idx, reference_item in enumerate(references):
            if str(reference_item.get("id")) == str(reference_id):
                reference = reference_item
                reference_idx = idx
                break

        if not reference:
            raise ServiceError(404, f"Reference {reference_id} not found")

        image_info = None
        image_idx = -1
        for idx, img in enumerate(reference_images):
            if str(img.get("id")) == str(reference_id):
                image_info = img
                image_idx = idx
                break

        if not image_info or not image_info.get("file_path"):
            raise ServiceError(
                400, "Reference has no image. Upload an image first before generating description."
            )

        file_path = str(image_info["file_path"])
        resolved_file_path = resolve_path_for_io(file_path)
        if resolved_file_path is None or not resolved_file_path.exists():
            raise ServiceError(400, "Reference image file not found")

        try:
            new_description = await generate_description_from_image(
                str(resolved_file_path),
                target_language=target_language,
                prompt_complexity=prompt_complexity,
                llm_provider=llm_provider,
                llm_model=llm_model,
            )

            references[reference_idx]["appearance_description"] = new_description
            if image_idx >= 0:
                reference_images[image_idx]["appearance_description"] = new_description

            output_data["references"] = references
            output_data["reference_images"] = reference_images
            output_data["reference_count"] = len(references)
            stage.output_data = output_data
            flag_modified(stage, "output_data")

            await self._sync_content_stage_after_reference_change(project, create_missing=False)
            await self.db.commit()
            await self.db.refresh(stage)

            return {
                "success": True,
                "appearance_description": new_description,
                "data": {
                    "id": reference_id,
                    "name": reference["name"],
                    "appearance_description": new_description,
                },
            }

        except FileNotFoundError:
            raise ServiceError(404, "Reference image file not found")
        except ValueError as e:
            raise ServiceError(400, str(e))
        except Exception as e:
            raise ServiceError(500, f"Failed to generate description: {str(e)}")
