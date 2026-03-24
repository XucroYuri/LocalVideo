import shutil
import time
from typing import Any

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import ServiceError
from app.core.media_file import (
    ImageScene,
    resolve_image_ext,
    safe_delete_file,
    save_upload_file,
    validate_image_upload,
)
from app.core.reference_slots import extract_reference_slot_ids, normalize_reference_slots
from app.models.stage import StageExecution, StageStatus, StageType
from app.stages.common.paths import resolve_existing_path_for_io


class StageAssetMixin:
    @staticmethod
    def _normalize_bulk_shot_indices(shot_indices: list[int] | None) -> list[int]:
        normalized: list[int] = []
        seen: set[int] = set()
        for raw in shot_indices or []:
            if not isinstance(raw, int) or raw < 0 or raw in seen:
                continue
            seen.add(raw)
            normalized.append(raw)
        return normalized

    @staticmethod
    def _reset_stage_runtime_fields(
        stage: StageExecution,
        *,
        status: StageStatus = StageStatus.PENDING,
        progress: int = 0,
    ) -> None:
        stage.status = status
        stage.progress = progress
        stage.error_message = None
        stage.total_items = None
        stage.completed_items = None
        stage.skipped_items = None
        stage.last_item_complete = -1

    async def regenerate_image_asset(
        self,
        project_id: int,
        scene: ImageScene,
        item_id: str | int,
        request: Any,
    ) -> dict[str, Any]:
        normalized_scene = self._normalize_image_scene(scene)
        project = await self.get_project_or_404(project_id)
        input_data = self._build_common_image_generation_input(request)

        if normalized_scene == "reference":
            reference_id = str(item_id)
            stage = await self._get_stage_or_404(
                project_id, StageType.REFERENCE, "Reference stage not found"
            )
            output_data = dict(stage.output_data or {})
            references = list(output_data.get("references", []))

            reference = None
            for reference_item in references:
                if str(reference_item.get("id")) == reference_id:
                    reference = reference_item
                    break
            if not reference:
                raise ServiceError(404, f"Reference {reference_id} not found")

            input_data["action"] = "generate_images"
            input_data["only_reference_id"] = reference_id
            stage_type = StageType.REFERENCE
            output_items_key = "reference_images"

            def matcher(item: dict[str, Any]) -> bool:
                return str(item.get("id")) == reference_id

            not_found_detail = f"Reference {reference_id} not found"
        else:
            shot_index = self._coerce_shot_index(item_id)
            storyboard_stage = await self._get_stage_or_404(
                project_id, StageType.STORYBOARD, "Storyboard stage not found"
            )
            storyboard_data = storyboard_stage.output_data or {}
            shots = storyboard_data.get("shots") or []
            if shot_index < 0 or shot_index >= len(shots):
                raise ServiceError(404, f"Shot index {shot_index} out of range")

            shot = shots[shot_index]
            prompt = shot.get("first_frame_description") or shot.get("video_prompt", "")
            if not prompt:
                raise ServiceError(400, "No description available for this frame")

            input_data["only_shot_index"] = shot_index
            input_data["use_reference_consistency"] = bool(
                getattr(request, "use_reference_consistency", False)
            )
            stage_type = StageType.FRAME
            output_items_key = "frame_images"

            def matcher(item: dict[str, Any]) -> bool:
                return int(item.get("shot_index", -1)) == shot_index

            not_found_detail = f"Shot index {shot_index} not found"

        pipeline = await self._run_stage_transient(project, stage_type, input_data)
        stage = await pipeline.get_or_create_stage(stage_type)
        if stage.status == StageStatus.FAILED:
            raise ServiceError(400, stage.error_message or "Stage failed")

        output_data = stage.output_data or {}
        output_items = output_data.get(output_items_key, [])
        for item in output_items:
            if isinstance(item, dict) and matcher(item):
                return {"success": True, "data": item}

        raise ServiceError(404, not_found_detail)

    async def upload_image_asset(
        self,
        project_id: int,
        scene: ImageScene,
        item_id: str | int,
        file: UploadFile,
    ) -> dict[str, Any]:
        validate_image_upload(file)
        normalized_scene = self._normalize_image_scene(scene)
        project = await self.get_project_or_404(project_id)
        ext = resolve_image_ext(file.content_type)

        if normalized_scene == "reference":
            reference_id = str(item_id)
            stage = await self._get_stage_or_404(
                project_id, StageType.REFERENCE, "Reference stage not found"
            )
            output_data = dict(stage.output_data or {})
            references, reference_images = self._normalize_reference_records(
                output_data.get("references"),
                output_data.get("reference_images"),
            )

            reference = None
            for reference_item in references:
                if str(reference_item.get("id")) == reference_id:
                    reference = reference_item
                    break
            if not reference:
                raise ServiceError(404, f"Reference {reference_id} not found")

            for img in reference_images:
                if str(img.get("id")) == reference_id:
                    safe_delete_file(img.get("file_path"))
                    break

            output_dir = self._get_output_dir(project)
            item_dir = output_dir / "references"
            item_dir.mkdir(parents=True, exist_ok=True)
            output_path = item_dir / f"{reference_id}.{ext}"

            await save_upload_file(file, output_path)

            new_item_data = {
                "id": reference_id,
                "name": reference.get("name", ""),
                "setting": reference.get("setting", ""),
                "appearance_description": reference.get("appearance_description", ""),
                "can_speak": bool(reference.get("can_speak", True)),
                "library_reference_id": reference.get("library_reference_id"),
                "file_path": str(output_path),
                "generated": False,
                "uploaded": True,
                "updated_at": int(time.time()),
            }

            replaced = False
            for idx, img in enumerate(reference_images):
                if str(img.get("id")) == reference_id:
                    reference_images[idx] = new_item_data
                    replaced = True
                    break
            if not replaced:
                reference_images.append(new_item_data)

            output_data["references"] = references
            output_data["reference_images"] = reference_images
            stage.output_data = output_data
            flag_modified(stage, "output_data")
            await self.db.commit()
            await self.db.refresh(stage)
            return {"success": True, "data": new_item_data}

        shot_index = self._coerce_shot_index(item_id)
        storyboard_stage = await self._get_stage_or_404(
            project_id, StageType.STORYBOARD, "Storyboard stage not found"
        )
        storyboard_data = storyboard_stage.output_data or {}
        shots = storyboard_data.get("shots") or []
        if shot_index < 0 or shot_index >= len(shots):
            raise ServiceError(404, f"Shot index {shot_index} out of range")
        shot = shots[shot_index]

        frame_stage = await self._get_or_create_stage(
            project,
            StageType.FRAME,
            {"frame_images": [], "frame_count": 0, "success_count": 0},
        )
        output_data = dict(frame_stage.output_data or {})
        frame_images = [dict(f) for f in output_data.get("frame_images", [])]

        output_dir = self._get_output_dir(project)
        frame_dir = output_dir / "frames"
        frame_dir.mkdir(parents=True, exist_ok=True)
        output_path = frame_dir / f"frame_{shot_index:03d}.{ext}"

        for old_ext in ("png", "jpg", "jpeg", "webp"):
            old_path = frame_dir / f"frame_{shot_index:03d}.{old_ext}"
            if old_path.exists() and old_path != output_path:
                old_path.unlink()

        await save_upload_file(file, output_path)

        new_item_data = {
            "shot_index": shot_index,
            "prompt": shot.get("first_frame_description", ""),
            "file_path": str(output_path),
            "first_frame_description": shot.get("first_frame_description"),
            "generated": False,
            "uploaded": True,
        }

        replaced = False
        for idx, frame in enumerate(frame_images):
            if frame.get("shot_index") == shot_index:
                frame_images[idx] = new_item_data
                replaced = True
                break
        if not replaced:
            frame_images.append(new_item_data)
        frame_images.sort(key=lambda x: x.get("shot_index", 0))

        output_data["frame_images"] = frame_images
        output_data["frame_count"] = len(frame_images)
        output_data["success_count"] = sum(
            1 for frame in frame_images if frame.get("generated") or frame.get("uploaded")
        )
        frame_stage.output_data = output_data
        flag_modified(frame_stage, "output_data")
        await self.db.commit()
        await self.db.refresh(frame_stage)
        return {"success": True, "data": new_item_data}

    async def delete_image_asset(
        self,
        project_id: int,
        scene: ImageScene,
        item_id: str | int,
    ) -> dict[str, Any]:
        await self.get_project_or_404(project_id)
        normalized_scene = self._normalize_image_scene(scene)

        if normalized_scene == "reference":
            reference_id = str(item_id)
            stage = await self._get_stage_or_404(
                project_id, StageType.REFERENCE, "Reference stage not found"
            )
            output_data = dict(stage.output_data or {})
            reference_images = [dict(i) for i in output_data.get("reference_images", [])]

            found = False
            for image in reference_images:
                if str(image.get("id")) == reference_id:
                    safe_delete_file(image.get("file_path"))
                    image["file_path"] = None
                    image["generated"] = False
                    image["uploaded"] = False
                    found = True
                    break
            if not found:
                raise ServiceError(404, f"Reference {reference_id} not found")

            output_data["reference_images"] = reference_images
            stage.output_data = output_data
            flag_modified(stage, "output_data")
            await self.db.commit()
            await self.db.refresh(stage)
            return {"success": True}

        shot_index = self._coerce_shot_index(item_id)
        frame_stage = await self._get_stage_or_404(
            project_id, StageType.FRAME, "Frame stage not found"
        )
        output_data = dict(frame_stage.output_data or {})
        frame_images = [dict(frame) for frame in output_data.get("frame_images", [])]

        deleted_file_path = None
        new_frame_images: list[dict[str, Any]] = []
        found = False
        for frame in frame_images:
            if frame.get("shot_index") == shot_index:
                deleted_file_path = frame.get("file_path")
                found = True
            else:
                new_frame_images.append(frame)
        if not found:
            raise ServiceError(404, f"Shot index {shot_index} not found")

        safe_delete_file(deleted_file_path)
        output_data["frame_images"] = new_frame_images
        output_data["frame_count"] = len(new_frame_images)
        output_data["success_count"] = sum(
            1 for frame in new_frame_images if frame.get("generated") or frame.get("uploaded")
        )
        frame_stage.output_data = output_data
        flag_modified(frame_stage, "output_data")

        await self.db.commit()
        await self.db.refresh(frame_stage)
        return {"success": True}

    async def delete_frame_images(
        self, project_id: int, shot_indices: list[int] | None
    ) -> dict[str, Any]:
        await self.get_project_or_404(project_id)
        normalized_indices = self._normalize_bulk_shot_indices(shot_indices)
        if not normalized_indices:
            return {"success": True, "deleted_count": 0, "missing_shot_indices": []}

        frame_stage = await self._get_stage_or_404(
            project_id, StageType.FRAME, "Frame stage not found"
        )
        output_data = dict(frame_stage.output_data or {})
        frame_images = [dict(frame) for frame in output_data.get("frame_images", [])]

        target_set = set(normalized_indices)
        remaining_frame_images: list[dict[str, Any]] = []
        deleted_indices: set[int] = set()
        for frame in frame_images:
            shot_index = frame.get("shot_index")
            if isinstance(shot_index, int) and shot_index in target_set:
                safe_delete_file(frame.get("file_path"))
                deleted_indices.add(shot_index)
                continue
            remaining_frame_images.append(frame)

        output_data["frame_images"] = remaining_frame_images
        output_data["frame_count"] = len(remaining_frame_images)
        output_data["success_count"] = sum(
            1 for frame in remaining_frame_images if frame.get("generated") or frame.get("uploaded")
        )
        frame_stage.output_data = output_data
        flag_modified(frame_stage, "output_data")
        await self.db.commit()
        await self.db.refresh(frame_stage)

        return {
            "success": True,
            "deleted_count": len(deleted_indices),
            "missing_shot_indices": [
                idx for idx in normalized_indices if idx not in deleted_indices
            ],
        }

    async def update_frame_description(
        self,
        project_id: int,
        shot_index: int,
        description: str | None = None,
        first_frame_reference_slots: list[dict[str, Any]] | None = None,
    ):
        await self.get_project_or_404(project_id)

        result = await self.db.execute(
            select(StageExecution).where(
                StageExecution.project_id == project_id,
                StageExecution.stage_type == StageType.STORYBOARD,
            )
        )
        storyboard_stage = result.scalar_one_or_none()
        if not storyboard_stage:
            raise ServiceError(404, "Storyboard stage not found")

        output_data = dict(storyboard_stage.output_data or {})
        shots = [dict(t) for t in output_data.get("shots") or []]

        if shot_index < 0 or shot_index >= len(shots):
            raise ServiceError(404, f"Shot index {shot_index} out of range")

        if description is None and first_frame_reference_slots is None:
            raise ServiceError(400, "No fields provided to update")

        if description is not None:
            shots[shot_index]["first_frame_description"] = description
        if first_frame_reference_slots is not None:
            normalized_slots = normalize_reference_slots(first_frame_reference_slots)
            normalized_ids = extract_reference_slot_ids(normalized_slots)
            shots[shot_index]["first_frame_reference_slots"] = normalized_slots
            identity = self._build_frame_reference_identity(normalized_ids)
            if identity:
                shots[shot_index]["first_frame_prompt_reference_identity"] = identity
            else:
                shots[shot_index].pop("first_frame_prompt_reference_identity", None)

        output_data["shots"] = shots
        storyboard_stage.output_data = output_data
        flag_modified(storyboard_stage, "output_data")

        # Keep FRAME stage metadata in sync so UI paths reading frame.output_data
        # can immediately see updated first-frame description.
        if description is not None:
            frame_result = await self.db.execute(
                select(StageExecution).where(
                    StageExecution.project_id == project_id,
                    StageExecution.stage_type == StageType.FRAME,
                )
            )
            frame_stage = frame_result.scalar_one_or_none()
            if frame_stage and isinstance(frame_stage.output_data, dict):
                frame_output = dict(frame_stage.output_data)
                frame_images = frame_output.get("frame_images")
                if isinstance(frame_images, list):
                    updated = False
                    new_frame_images = []
                    for item in frame_images:
                        if isinstance(item, dict):
                            frame_item = dict(item)
                            if frame_item.get("shot_index") == shot_index:
                                frame_item["first_frame_description"] = shots[shot_index].get(
                                    "first_frame_description"
                                )
                                updated = True
                            new_frame_images.append(frame_item)
                        else:
                            new_frame_images.append(item)
                    if updated:
                        frame_output["frame_images"] = new_frame_images
                        frame_stage.output_data = frame_output
                        flag_modified(frame_stage, "output_data")

        await self.db.commit()
        await self.db.refresh(storyboard_stage)

        return {
            "success": True,
            "data": {
                "shot_index": shot_index,
                "description": shots[shot_index].get("first_frame_description"),
                "first_frame_reference_slots": shots[shot_index].get(
                    "first_frame_reference_slots",
                    [],
                ),
            },
        }

    async def reuse_first_frame_to_other_shots(self, project_id: int) -> dict[str, Any]:
        project = await self.get_project_or_404(project_id)
        storyboard_stage = await self._get_stage_or_404(
            project_id,
            StageType.STORYBOARD,
            "Storyboard stage not found",
        )
        storyboard_output = dict(storyboard_stage.output_data or {})
        shots = [
            dict(shot) for shot in storyboard_output.get("shots") or [] if isinstance(shot, dict)
        ]
        if not shots:
            raise ServiceError(400, "分镜为空，无法复用首帧图")

        frame_stage = await self._get_or_create_stage(
            project,
            StageType.FRAME,
            {"frame_images": [], "frame_count": 0, "success_count": 0},
        )
        frame_output = dict(frame_stage.output_data or {})
        frame_images = [
            dict(item) for item in frame_output.get("frame_images", []) if isinstance(item, dict)
        ]
        frame_by_index = {
            int(item.get("shot_index")): item
            for item in frame_images
            if item.get("shot_index") is not None
        }
        first_frame = frame_by_index.get(0)
        first_frame_path = (
            resolve_existing_path_for_io(
                first_frame.get("file_path"),
                allowed_suffixes={".png", ".jpg", ".jpeg", ".webp"},
            )
            if first_frame
            else None
        )
        if not first_frame_path or not first_frame_path.exists():
            raise ServiceError(400, "第一个分镜位缺少首帧图，请先生成或上传第一个分镜位首帧图")

        output_dir = self._get_output_dir(project)
        frame_dir = output_dir / "frames"
        frame_dir.mkdir(parents=True, exist_ok=True)
        target_suffix = first_frame_path.suffix or ".png"
        updated_at = int(time.time())
        merged_items: list[dict[str, Any]] = []
        for idx, shot in enumerate(shots):
            if idx == 0:
                target_path = first_frame_path
            else:
                target_path = frame_dir / f"frame_{idx:03d}{target_suffix}"
                shutil.copy2(first_frame_path, target_path)
            current_item = dict(frame_by_index.get(idx) or {})
            current_item.update(
                {
                    "shot_index": idx,
                    "prompt": str(
                        shot.get("first_frame_description") or shot.get("video_prompt") or ""
                    ),
                    "file_path": str(target_path),
                    "first_frame_description": shot.get("first_frame_description"),
                    "generated": True,
                    "uploaded": bool(current_item.get("uploaded")) if idx == 0 else False,
                    "updated_at": updated_at,
                }
            )
            current_item.pop("error", None)
            merged_items.append(current_item)

        frame_output["frame_images"] = merged_items
        frame_output["frame_count"] = len(merged_items)
        frame_output["success_count"] = len(merged_items)
        frame_stage.output_data = frame_output
        flag_modified(frame_stage, "output_data")
        await self.db.commit()
        await self.db.refresh(frame_stage)
        return {
            "success": True,
            "data": {
                "source_shot_index": 0,
                "shot_count": len(merged_items),
            },
        }

    async def delete_video(self, project_id: int, shot_index: int):
        await self.get_project_or_404(project_id)

        result = await self.db.execute(
            select(StageExecution).where(
                StageExecution.project_id == project_id,
                StageExecution.stage_type == StageType.VIDEO,
            )
        )
        video_stage = result.scalar_one_or_none()
        if not video_stage:
            raise ServiceError(404, "Video stage not found")

        output_data = dict(video_stage.output_data or {})
        video_assets = [dict(v) for v in output_data.get("video_assets", [])]

        deleted_file_path = None
        new_video_assets = []
        for v in video_assets:
            if v.get("shot_index") == shot_index:
                deleted_file_path = v.get("file_path")
            else:
                new_video_assets.append(v)

        if deleted_file_path:
            safe_delete_file(deleted_file_path)

        output_data["video_assets"] = new_video_assets
        output_data["video_count"] = len(new_video_assets)

        video_stage.output_data = output_data
        flag_modified(video_stage, "output_data")
        await self.db.commit()
        await self.db.refresh(video_stage)

        return {"success": True}

    async def delete_videos(
        self, project_id: int, shot_indices: list[int] | None
    ) -> dict[str, Any]:
        await self.get_project_or_404(project_id)
        normalized_indices = self._normalize_bulk_shot_indices(shot_indices)
        if not normalized_indices:
            return {"success": True, "deleted_count": 0, "missing_shot_indices": []}

        result = await self.db.execute(
            select(StageExecution).where(
                StageExecution.project_id == project_id,
                StageExecution.stage_type == StageType.VIDEO,
            )
        )
        video_stage = result.scalar_one_or_none()
        if not video_stage:
            return {
                "success": True,
                "deleted_count": 0,
                "missing_shot_indices": normalized_indices,
            }

        output_data = dict(video_stage.output_data or {})
        video_assets = [dict(v) for v in output_data.get("video_assets", [])]

        target_set = set(normalized_indices)
        new_video_assets: list[dict[str, Any]] = []
        deleted_indices: set[int] = set()
        for video_asset in video_assets:
            shot_index = video_asset.get("shot_index")
            if isinstance(shot_index, int) and shot_index in target_set:
                safe_delete_file(video_asset.get("file_path"))
                deleted_indices.add(shot_index)
                continue
            new_video_assets.append(video_asset)

        output_data["video_assets"] = new_video_assets
        output_data["video_count"] = len(new_video_assets)
        video_stage.output_data = output_data
        flag_modified(video_stage, "output_data")
        await self.db.commit()
        await self.db.refresh(video_stage)

        return {
            "success": True,
            "deleted_count": len(deleted_indices),
            "missing_shot_indices": [
                idx for idx in normalized_indices if idx not in deleted_indices
            ],
        }

    async def delete_compose_video(self, project_id: int):
        await self.get_project_or_404(project_id)

        result = await self.db.execute(
            select(StageExecution).where(StageExecution.project_id == project_id)
        )
        stages = {stage.stage_type: stage for stage in result.scalars()}
        compose_stage = stages.get(StageType.COMPOSE)
        if not compose_stage:
            raise ServiceError(404, "Compose stage not found")

        compose_output = dict(compose_stage.output_data or {})
        safe_delete_file(compose_output.get("master_video_path"))
        safe_delete_file(
            str(self._get_output_dir(await self.get_project_or_404(project_id)) / "final_video.mp4")
        )
        merged_files = compose_output.get("merged_files")
        if isinstance(merged_files, list):
            for item in merged_files:
                if isinstance(item, dict):
                    safe_delete_file(item.get("file_path"))

        self._reset_stage_runtime_fields(compose_stage)
        compose_stage.output_data = {}
        flag_modified(compose_stage, "output_data")

        subtitle_stage = stages.get(StageType.SUBTITLE)
        if subtitle_stage:
            subtitle_output = dict(subtitle_stage.output_data or {})
            safe_delete_file(subtitle_output.get("subtitle_file_path"))
            self._reset_stage_runtime_fields(subtitle_stage)
            subtitle_stage.output_data = {}
            flag_modified(subtitle_stage, "output_data")

        burn_stage = stages.get(StageType.BURN_SUBTITLE)
        if burn_stage:
            burn_output = dict(burn_stage.output_data or {})
            safe_delete_file(burn_output.get("burned_video_path"))
            self._reset_stage_runtime_fields(burn_stage)
            burn_stage.output_data = {}
            flag_modified(burn_stage, "output_data")

        finalize_stage = stages.get(StageType.FINALIZE)
        if finalize_stage:
            safe_delete_file(
                str(
                    self._get_output_dir(await self.get_project_or_404(project_id))
                    / "final_video.mp4"
                )
            )
            self._reset_stage_runtime_fields(finalize_stage)
            finalize_stage.output_data = {}
            flag_modified(finalize_stage, "output_data")

        await self.db.commit()

        return {"success": True}

    async def delete_audio(self, project_id: int, shot_index: int):
        await self.get_project_or_404(project_id)

        result = await self.db.execute(
            select(StageExecution).where(
                StageExecution.project_id == project_id,
                StageExecution.stage_type == StageType.AUDIO,
            )
        )
        audio_stage = result.scalar_one_or_none()
        if not audio_stage:
            raise ServiceError(404, "Audio stage not found")

        output_data = dict(audio_stage.output_data or {})
        audio_assets = [dict(a) for a in output_data.get("audio_assets", [])]

        deleted_file_path = None
        new_audio_assets = []
        for a in audio_assets:
            if a.get("shot_index") == shot_index:
                deleted_file_path = a.get("file_path")
                safe_delete_file(a.get("source_file_path"))
            else:
                new_audio_assets.append(a)

        if deleted_file_path:
            safe_delete_file(deleted_file_path)

        output_data["audio_assets"] = new_audio_assets
        output_data["shot_count"] = len(new_audio_assets)
        output_data["total_duration"] = sum(a.get("duration", 0.0) for a in new_audio_assets if a)
        if not new_audio_assets:
            output_data.pop("audio_wan2gp_effective_seed", None)
            output_data.pop("audio_wan2gp_seed_anchor_shot_index", None)

        audio_stage.output_data = output_data
        flag_modified(audio_stage, "output_data")
        await self.db.commit()
        await self.db.refresh(audio_stage)

        return {"success": True}

    async def delete_audios(
        self, project_id: int, shot_indices: list[int] | None
    ) -> dict[str, Any]:
        await self.get_project_or_404(project_id)
        normalized_indices = self._normalize_bulk_shot_indices(shot_indices)
        if not normalized_indices:
            return {"success": True, "deleted_count": 0, "missing_shot_indices": []}

        result = await self.db.execute(
            select(StageExecution).where(
                StageExecution.project_id == project_id,
                StageExecution.stage_type == StageType.AUDIO,
            )
        )
        audio_stage = result.scalar_one_or_none()
        if not audio_stage:
            return {
                "success": True,
                "deleted_count": 0,
                "missing_shot_indices": normalized_indices,
            }

        output_data = dict(audio_stage.output_data or {})
        audio_assets = [dict(a) for a in output_data.get("audio_assets", [])]

        target_set = set(normalized_indices)
        new_audio_assets: list[dict[str, Any]] = []
        deleted_indices: set[int] = set()
        for audio_asset in audio_assets:
            shot_index = audio_asset.get("shot_index")
            if isinstance(shot_index, int) and shot_index in target_set:
                safe_delete_file(audio_asset.get("source_file_path"))
                safe_delete_file(audio_asset.get("file_path"))
                deleted_indices.add(shot_index)
                continue
            new_audio_assets.append(audio_asset)

        output_data["audio_assets"] = new_audio_assets
        output_data["shot_count"] = len(new_audio_assets)
        output_data["total_duration"] = sum(a.get("duration", 0.0) for a in new_audio_assets if a)
        if not new_audio_assets:
            output_data.pop("audio_wan2gp_effective_seed", None)
            output_data.pop("audio_wan2gp_seed_anchor_shot_index", None)

        audio_stage.output_data = output_data
        flag_modified(audio_stage, "output_data")
        await self.db.commit()
        await self.db.refresh(audio_stage)

        return {
            "success": True,
            "deleted_count": len(deleted_indices),
            "missing_shot_indices": [
                idx for idx in normalized_indices if idx not in deleted_indices
            ],
        }

    async def clear_all_shot_content(self, project_id: int) -> dict[str, Any]:
        project = await self.get_project_or_404(project_id)
        output_dir = self._get_output_dir(project)

        result = await self.db.execute(
            select(StageExecution).where(StageExecution.project_id == project_id)
        )
        stages = {stage.stage_type: stage for stage in result.scalars()}
        content_stage = stages.get(StageType.CONTENT)
        if content_stage and isinstance(content_stage.output_data, dict):
            content_output = dict(content_stage.output_data)
            content_output["shots_locked"] = False
            content_stage.output_data = content_output
            flag_modified(content_stage, "output_data")

        storyboard_stage = stages.get(StageType.STORYBOARD)
        if storyboard_stage:
            storyboard_output = dict(storyboard_stage.output_data or {})
            next_storyboard_output: dict[str, Any] = {
                "shots": [],
                "shot_count": 0,
            }
            if isinstance(storyboard_output.get("title"), str):
                next_storyboard_output["title"] = storyboard_output["title"]
            if isinstance(storyboard_output.get("script_mode"), str):
                next_storyboard_output["script_mode"] = storyboard_output["script_mode"]
            if isinstance(storyboard_output.get("roles"), list):
                next_storyboard_output["roles"] = storyboard_output["roles"]
            if isinstance(storyboard_output.get("dialogue_lines"), list):
                next_storyboard_output["dialogue_lines"] = storyboard_output["dialogue_lines"]
            if isinstance(storyboard_output.get("references"), list):
                next_storyboard_output["references"] = storyboard_output["references"]

            self._reset_stage_runtime_fields(storyboard_stage)
            storyboard_stage.output_data = next_storyboard_output
            flag_modified(storyboard_stage, "output_data")

        first_frame_desc_stage = stages.get(StageType.FIRST_FRAME_DESC)
        if first_frame_desc_stage:
            self._reset_stage_runtime_fields(first_frame_desc_stage)
            first_frame_desc_stage.output_data = {}
            flag_modified(first_frame_desc_stage, "output_data")

        frame_stage = stages.get(StageType.FRAME)
        if frame_stage:
            frame_output = dict(frame_stage.output_data or {})
            frame_images = frame_output.get("frame_images")
            if isinstance(frame_images, list):
                for image in frame_images:
                    if isinstance(image, dict):
                        safe_delete_file(image.get("file_path"))

            self._reset_stage_runtime_fields(frame_stage)
            frame_stage.output_data = {
                "frame_images": [],
                "frame_count": 0,
                "success_count": 0,
            }
            flag_modified(frame_stage, "output_data")

        frame_dir = output_dir / "frames"
        if frame_dir.exists():
            for pattern in ("frame_*.png", "frame_*.jpg", "frame_*.jpeg", "frame_*.webp"):
                for file_path in frame_dir.glob(pattern):
                    if file_path.is_file():
                        safe_delete_file(str(file_path))

        video_stage = stages.get(StageType.VIDEO)
        if video_stage:
            video_output = dict(video_stage.output_data or {})
            video_assets = video_output.get("video_assets")
            if isinstance(video_assets, list):
                for asset in video_assets:
                    if isinstance(asset, dict):
                        safe_delete_file(asset.get("file_path"))

            self._reset_stage_runtime_fields(video_stage)
            video_stage.output_data = {
                "video_assets": [],
                "video_count": 0,
            }
            flag_modified(video_stage, "output_data")

        video_dir = output_dir / "videos"
        if video_dir.exists():
            for file_path in video_dir.glob("shot_*.*"):
                if file_path.is_file():
                    safe_delete_file(str(file_path))

        audio_stage = stages.get(StageType.AUDIO)
        if audio_stage:
            audio_output = dict(audio_stage.output_data or {})
            audio_assets = audio_output.get("audio_assets")
            if isinstance(audio_assets, list):
                for asset in audio_assets:
                    if isinstance(asset, dict):
                        safe_delete_file(asset.get("file_path"))
                        safe_delete_file(asset.get("source_file_path"))

            next_audio_output: dict[str, Any] = {
                "audio_assets": [],
                "shot_count": 0,
                "total_duration": 0.0,
                "generating_shots": {},
            }
            self._reset_stage_runtime_fields(audio_stage)
            audio_stage.output_data = next_audio_output
            flag_modified(audio_stage, "output_data")

        audio_dir = output_dir / "audio"
        if audio_dir.exists():
            for file_path in audio_dir.glob("shot_*.*"):
                if file_path.is_file():
                    safe_delete_file(str(file_path))

        subtitle_stage = stages.get(StageType.SUBTITLE)
        if subtitle_stage:
            subtitle_output = dict(subtitle_stage.output_data or {})
            safe_delete_file(subtitle_output.get("subtitle_file_path"))

            self._reset_stage_runtime_fields(subtitle_stage)
            subtitle_stage.output_data = {}
            flag_modified(subtitle_stage, "output_data")

        subtitle_dir = output_dir / "subtitles"
        if subtitle_dir.exists():
            for subtitle_file in subtitle_dir.glob("*"):
                if subtitle_file.is_file():
                    safe_delete_file(str(subtitle_file))

        burn_stage = stages.get(StageType.BURN_SUBTITLE)
        if burn_stage:
            burn_output = dict(burn_stage.output_data or {})
            safe_delete_file(burn_output.get("burned_video_path"))
            self._reset_stage_runtime_fields(burn_stage)
            burn_stage.output_data = {}
            flag_modified(burn_stage, "output_data")

        finalize_stage = stages.get(StageType.FINALIZE)
        if finalize_stage:
            safe_delete_file(str(output_dir / "final_video.mp4"))
            self._reset_stage_runtime_fields(finalize_stage)
            finalize_stage.output_data = {}
            flag_modified(finalize_stage, "output_data")

        compose_stage = stages.get(StageType.COMPOSE)
        if compose_stage:
            compose_output = dict(compose_stage.output_data or {})
            safe_delete_file(compose_output.get("master_video_path"))
            safe_delete_file(str(output_dir / "final_video.mp4"))
            merged_files = compose_output.get("merged_files")
            if isinstance(merged_files, list):
                for item in merged_files:
                    if isinstance(item, dict):
                        safe_delete_file(item.get("file_path"))

            self._reset_stage_runtime_fields(compose_stage)
            compose_stage.output_data = {}
            flag_modified(compose_stage, "output_data")

        await self.db.commit()
        return {"success": True}

    async def regenerate_video(self, project_id: int, shot_index: int, request):
        project = await self.get_project_or_404(project_id)

        result = await self.db.execute(
            select(StageExecution).where(
                StageExecution.project_id == project_id,
                StageExecution.stage_type == StageType.STORYBOARD,
            )
        )
        storyboard_stage = result.scalar_one_or_none()
        if not storyboard_stage:
            raise ServiceError(404, "Storyboard stage not found")

        storyboard_data = storyboard_stage.output_data or {}
        shots = storyboard_data.get("shots") or []

        if shot_index < 0 or shot_index >= len(shots):
            raise ServiceError(404, f"Shot index {shot_index} out of range")

        shot = shots[shot_index]
        video_prompt = shot.get("video_prompt", "")
        if not video_prompt:
            raise ServiceError(400, "No video prompt available for this shot")

        result = await self.db.execute(
            select(StageExecution).where(
                StageExecution.project_id == project_id,
                StageExecution.stage_type == StageType.AUDIO,
            )
        )
        audio_stage = result.scalar_one_or_none()
        if not audio_stage:
            raise ServiceError(404, "Audio stage not found")

        input_data = {
            "video_provider": request.video_provider,
            "video_model": request.video_model,
            "video_aspect_ratio": request.aspect_ratio,
            "resolution": request.resolution,
            "use_first_frame_ref": request.use_first_frame_ref,
            "use_reference_image_ref": request.use_reference_image_ref,
            "video_wan2gp_t2v_preset": request.video_wan2gp_t2v_preset,
            "video_wan2gp_i2v_preset": request.video_wan2gp_i2v_preset,
            "video_wan2gp_resolution": request.video_wan2gp_resolution,
            "video_wan2gp_inference_steps": request.video_wan2gp_inference_steps,
            "video_wan2gp_sliding_window_size": request.video_wan2gp_sliding_window_size,
            "only_shot_index": shot_index,
            "force_regenerate": True,
        }

        pipeline = await self._run_stage_transient(project, StageType.VIDEO, input_data)

        stage = await pipeline.get_or_create_stage(StageType.VIDEO)
        if stage.status == StageStatus.FAILED:
            raise ServiceError(400, stage.error_message or "Stage failed")

        output_data = stage.output_data or {}
        video_assets = output_data.get("video_assets", [])
        for video in video_assets:
            if video.get("shot_index") == shot_index:
                return {"success": True, "data": video}

        raise ServiceError(404, f"Shot index {shot_index} not found")

    async def update_video_description(
        self,
        project_id: int,
        shot_index: int,
        description: str | None = None,
        video_reference_slots: list[dict[str, Any]] | None = None,
    ):
        await self.get_project_or_404(project_id)

        result = await self.db.execute(
            select(StageExecution).where(
                StageExecution.project_id == project_id,
                StageExecution.stage_type == StageType.STORYBOARD,
            )
        )
        storyboard_stage = result.scalar_one_or_none()
        if not storyboard_stage:
            raise ServiceError(404, "Storyboard stage not found")

        output_data = dict(storyboard_stage.output_data or {})
        shots = [dict(t) for t in output_data.get("shots") or []]

        if shot_index < 0 or shot_index >= len(shots):
            raise ServiceError(404, f"Shot index {shot_index} out of range")

        if description is None and video_reference_slots is None:
            raise ServiceError(400, "No fields provided to update")

        if description is not None:
            shots[shot_index]["video_prompt"] = description
        if video_reference_slots is not None:
            normalized_slots = normalize_reference_slots(video_reference_slots)
            shots[shot_index]["video_reference_slots"] = normalized_slots
            shots[shot_index].pop("video_reference_ids", None)

        for item in shots:
            if isinstance(item, dict):
                item.pop("video_reference_ids", None)

        output_data["shots"] = shots
        storyboard_stage.output_data = output_data
        flag_modified(storyboard_stage, "output_data")
        await self.db.commit()
        await self.db.refresh(storyboard_stage)

        return {
            "success": True,
            "data": {
                "shot_index": shot_index,
                "description": shots[shot_index].get("video_prompt"),
                "video_reference_slots": shots[shot_index].get(
                    "video_reference_slots",
                    [],
                ),
            },
        }

    async def regenerate_audio(self, project_id: int, shot_index: int, request):
        project = await self.get_project_or_404(project_id)

        result = await self.db.execute(
            select(StageExecution).where(
                StageExecution.project_id == project_id,
                StageExecution.stage_type == StageType.STORYBOARD,
            )
        )
        storyboard_stage = result.scalar_one_or_none()
        if not storyboard_stage:
            raise ServiceError(404, "Storyboard stage not found")

        storyboard_data = storyboard_stage.output_data or {}
        shots = storyboard_data.get("shots") or []
        if shot_index < 0 or shot_index >= len(shots):
            raise ServiceError(404, f"Shot index {shot_index} out of range")

        shot = shots[shot_index]
        voice_content = shot.get("voice_content", "")
        if not voice_content:
            raise ServiceError(400, "No voice_content available for this shot")

        input_data = {
            "audio_provider": request.audio_provider,
            "voice": request.voice,
            "speed": request.speed,
            "audio_wan2gp_preset": request.audio_wan2gp_preset,
            "audio_wan2gp_model_mode": request.audio_wan2gp_model_mode,
            "audio_wan2gp_alt_prompt": request.audio_wan2gp_alt_prompt,
            "audio_wan2gp_duration_seconds": request.audio_wan2gp_duration_seconds,
            "audio_wan2gp_temperature": request.audio_wan2gp_temperature,
            "audio_wan2gp_top_k": request.audio_wan2gp_top_k,
            "audio_wan2gp_seed": request.audio_wan2gp_seed,
            "audio_wan2gp_audio_guide": request.audio_wan2gp_audio_guide,
            "audio_wan2gp_split_strategy": request.audio_wan2gp_split_strategy,
            "only_shot_index": shot_index,
            "force_regenerate": True,
        }

        pipeline = await self._run_stage_transient(project, StageType.AUDIO, input_data)

        stage = await pipeline.get_or_create_stage(StageType.AUDIO)
        if stage.status == StageStatus.FAILED:
            raise ServiceError(400, stage.error_message or "Stage failed")

        output_data = stage.output_data or {}
        audio_assets = output_data.get("audio_assets", [])
        for audio in audio_assets:
            if audio.get("shot_index") == shot_index:
                return {"success": True, "data": audio}

        raise ServiceError(404, f"Shot index {shot_index} not found")
