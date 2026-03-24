import asyncio
import re
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.errors import ServiceError
from app.core.media_file import safe_delete_file
from app.models.project import Project
from app.models.stage import StageExecution, StageStatus, StageType
from app.stages._audio_split import probe_audio_duration

CHAR_COUNT_PATTERN = re.compile(r"[^\u4e00-\u9fa5a-zA-Z0-9]")
DEFAULT_SPEAKER_ID = "ref_01"
DEFAULT_SPEAKER_NAME = "讲述者"


class StageShotMixin:
    @staticmethod
    def _new_shot_id() -> str:
        return uuid4().hex

    @staticmethod
    def _count_script_chars(text: str) -> int:
        return len(CHAR_COUNT_PATTERN.sub("", text))

    @staticmethod
    def _coerce_shot_items(raw_shots: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_shots, list):
            return []

        normalized: list[dict[str, Any]] = []
        for idx, item in enumerate(raw_shots):
            shot = item if isinstance(item, dict) else {}
            shot_id = str(shot.get("shot_id") or "").strip() or f"shot_{idx + 1}"
            speaker_id = str(shot.get("speaker_id") or "").strip() or DEFAULT_SPEAKER_ID
            speaker_name = str(shot.get("speaker_name") or "").strip() or speaker_id
            line_id = str(shot.get("line_id") or "").strip() or f"line_{idx + 1}"
            normalized.append(
                {
                    "shot_id": shot_id,
                    "order": idx,
                    "voice_content": str(shot.get("voice_content") or ""),
                    "speaker_id": speaker_id,
                    "speaker_name": speaker_name,
                    "speaker_type": str(shot.get("speaker_type") or "role"),
                    "line_id": line_id,
                    "video_prompt": str(shot.get("video_prompt") or ""),
                    "first_frame_description": str(shot.get("first_frame_description") or ""),
                    "video_reference_slots": shot.get("video_reference_slots") or [],
                    "first_frame_reference_slots": shot.get("first_frame_reference_slots") or [],
                }
            )
        return normalized

    def _build_storyboard_shots(
        self,
        *,
        shots: list[dict[str, Any]],
        old_storyboard_by_shot: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        storyboard_shots: list[dict[str, Any]] = []
        for idx, shot in enumerate(shots):
            shot_id = str(shot.get("shot_id") or "").strip()
            old_shot = old_storyboard_by_shot.get(shot_id, {})
            merged = dict(old_shot)
            merged.update(
                {
                    "shot_id": shot_id,
                    "shot_index": idx,
                    "order": idx,
                    "voice_content": str(shot.get("voice_content") or ""),
                    "speaker_id": str(shot.get("speaker_id") or DEFAULT_SPEAKER_ID),
                    "speaker_name": str(shot.get("speaker_name") or DEFAULT_SPEAKER_NAME),
                    "speaker_type": str(shot.get("speaker_type") or "role"),
                    "line_id": str(shot.get("line_id") or f"line_{idx + 1}"),
                }
            )
            if "video_reference_slots" in shot:
                merged["video_reference_slots"] = shot.get("video_reference_slots") or []
                merged.pop("video_reference_ids", None)
            if "first_frame_reference_slots" in shot:
                merged["first_frame_reference_slots"] = (
                    shot.get("first_frame_reference_slots") or []
                )
            if "video_prompt" in shot:
                merged["video_prompt"] = str(shot.get("video_prompt") or "")
            if "first_frame_description" in shot:
                merged["first_frame_description"] = str(shot.get("first_frame_description") or "")
            storyboard_shots.append(merged)
        return storyboard_shots

    @staticmethod
    def _build_split_shots(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
        split_shots: list[dict[str, Any]] = []
        for idx, shot in enumerate(shots):
            split_shots.append(
                {
                    "shot_id": str(shot.get("shot_id") or "").strip(),
                    "order": idx,
                    "voice_content": str(shot.get("voice_content") or ""),
                    "speaker_id": str(shot.get("speaker_id") or DEFAULT_SPEAKER_ID),
                    "speaker_name": str(shot.get("speaker_name") or DEFAULT_SPEAKER_NAME),
                    "speaker_type": str(shot.get("speaker_type") or "role"),
                    "line_id": str(shot.get("line_id") or f"line_{idx + 1}"),
                }
            )
        return split_shots

    @staticmethod
    async def _concat_audio_inputs_to_wav(
        *,
        input_paths: list[Path],
        output_path: Path,
    ) -> None:
        if not input_paths:
            raise ServiceError(400, "没有可拼接的音频输入")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["ffmpeg", "-y"]
        for path in input_paths:
            cmd.extend(["-i", str(path)])
        if len(input_paths) == 1:
            cmd.extend(["-vn", "-acodec", "pcm_s16le", str(output_path)])
        else:
            cmd.extend(
                [
                    "-filter_complex",
                    f"concat=n={len(input_paths)}:v=0:a=1",
                    "-vn",
                    "-acodec",
                    "pcm_s16le",
                    str(output_path),
                ]
            )
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise ServiceError(500, "未找到 ffmpeg，无法拼接智能合并音频") from exc
        _, stderr = await process.communicate()
        if process.returncode != 0 or not output_path.exists():
            message = stderr.decode(errors="ignore").strip()
            raise ServiceError(500, f"智能合并音频拼接失败: {message}")

    async def _build_smart_merged_audio_assets(
        self,
        *,
        storyboard_payload: dict[str, Any],
        existing_audio_output: dict[str, Any],
        output_dir: Path,
    ) -> list[dict[str, Any]] | None:
        raw_shots = storyboard_payload.get("shots")
        raw_audio_assets = existing_audio_output.get("audio_assets")
        if not isinstance(raw_shots, list) or not isinstance(raw_audio_assets, list):
            return None

        audio_assets_by_index: dict[int, dict[str, Any]] = {}
        for asset in raw_audio_assets:
            if not isinstance(asset, dict):
                continue
            try:
                shot_index = int(asset.get("shot_index"))
            except (TypeError, ValueError):
                continue
            audio_assets_by_index[shot_index] = asset

        merged_assets: list[dict[str, Any]] = []
        audio_dir = output_dir / "audio"
        for merged_index, raw_shot in enumerate(raw_shots):
            if not isinstance(raw_shot, dict):
                return None
            metadata = raw_shot.get("metadata")
            smart_merge = metadata.get("smart_merge") if isinstance(metadata, dict) else None
            source_indices = (
                smart_merge.get("source_shot_indices") if isinstance(smart_merge, dict) else None
            )
            if not isinstance(source_indices, list) or not source_indices:
                return None
            if not all(isinstance(item, int) for item in source_indices):
                return None

            source_assets: list[dict[str, Any]] = []
            input_paths: list[Path] = []
            for source_index in source_indices:
                asset = audio_assets_by_index.get(int(source_index))
                if not isinstance(asset, dict):
                    return None
                asset_path = Path(str(asset.get("file_path") or "").strip())
                if not asset_path.exists():
                    return None
                source_assets.append(asset)
                input_paths.append(asset_path)

            output_path = audio_dir / f"shot_{merged_index:03d}.wav"
            await self._concat_audio_inputs_to_wav(
                input_paths=input_paths,
                output_path=output_path,
            )
            duration = await probe_audio_duration(output_path)
            provider_names = {
                str(asset.get("audio_provider") or "").strip()
                for asset in source_assets
                if str(asset.get("audio_provider") or "").strip()
            }
            merged_assets.append(
                {
                    "shot_index": merged_index,
                    "voice_content": str(raw_shot.get("voice_content") or ""),
                    "file_path": str(output_path),
                    "source_file_path": str(output_path),
                    "duration": float(duration),
                    "updated_at": int(time.time()),
                    "audio_provider": provider_names.pop()
                    if len(provider_names) == 1
                    else "merged",
                }
            )
        return merged_assets

    def _sync_asset_stage_by_shots(
        self,
        *,
        stage: StageExecution | None,
        assets_key: str,
        old_index_to_shot_id: dict[int, str],
        new_shot_id_to_index: dict[str, int],
        deleted_shot_ids: set[str],
        path_fields: list[str],
        count_field: str,
    ) -> None:
        if stage is None:
            return
        output_data = dict(stage.output_data or {})
        raw_assets = output_data.get(assets_key)
        assets = [dict(item) for item in raw_assets] if isinstance(raw_assets, list) else []

        mapped_assets: list[dict[str, Any]] = []
        for asset in assets:
            shot_id = str(asset.get("shot_id") or "").strip()
            if not shot_id:
                shot_index = asset.get("shot_index")
                try:
                    shot_id = old_index_to_shot_id.get(int(shot_index), "")
                except (TypeError, ValueError):
                    shot_id = ""

            if not shot_id or shot_id in deleted_shot_ids:
                for field in path_fields:
                    safe_delete_file(asset.get(field))
                continue

            new_index = new_shot_id_to_index.get(shot_id)
            if new_index is None:
                for field in path_fields:
                    safe_delete_file(asset.get(field))
                continue

            next_asset = dict(asset)
            next_asset["shot_id"] = shot_id
            next_asset["shot_index"] = new_index
            mapped_assets.append(next_asset)

        mapped_assets.sort(key=lambda item: int(item.get("shot_index") or 0))
        output_data[assets_key] = mapped_assets
        output_data[count_field] = len(mapped_assets)

        if assets_key == "audio_assets":
            output_data["shot_count"] = len(mapped_assets)
            output_data["total_duration"] = sum(
                float(asset.get("duration", 0.0) or 0.0) for asset in mapped_assets
            )
        if assets_key == "frame_images":
            output_data["success_count"] = sum(
                1 for item in mapped_assets if item.get("generated") or item.get("uploaded")
            )

        has_assets = len(mapped_assets) > 0
        stage.status = StageStatus.COMPLETED if has_assets else StageStatus.PENDING
        stage.progress = 100 if has_assets else 0
        stage.error_message = None
        stage.last_item_complete = len(mapped_assets) - 1 if has_assets else -1
        stage.total_items = len(mapped_assets) if has_assets else 0
        stage.completed_items = len(mapped_assets) if has_assets else 0
        stage.skipped_items = 0
        stage.output_data = output_data
        flag_modified(stage, "output_data")

    @staticmethod
    def _rebuild_content_dialogue_lines(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
        lines: list[dict[str, Any]] = []
        for idx, shot in enumerate(shots):
            line_id = str(shot.get("line_id") or "").strip() or f"line_{idx + 1}"
            speaker_id = str(shot.get("speaker_id") or "").strip() or DEFAULT_SPEAKER_ID
            speaker_name = str(shot.get("speaker_name") or "").strip() or speaker_id
            lines.append(
                {
                    "id": line_id,
                    "speaker_id": speaker_id,
                    "speaker_name": speaker_name,
                    "text": str(shot.get("voice_content") or ""),
                    "order": idx,
                    "shot_id": str(shot.get("shot_id") or "").strip(),
                }
            )
        return lines

    def _sync_content_stage_from_shots(
        self,
        *,
        content_stage: StageExecution | None,
        shots: list[dict[str, Any]],
        shots_locked: bool,
    ) -> None:
        if content_stage is None:
            return

        output_data = dict(content_stage.output_data or {})
        existing_dialogue_lines = output_data.get("dialogue_lines")
        preserved_dialogue_lines = (
            existing_dialogue_lines
            if isinstance(existing_dialogue_lines, list)
            and any(
                isinstance(item, dict) and str(item.get("text") or "").strip()
                for item in existing_dialogue_lines
            )
            else None
        )
        preserved_content = str(output_data.get("content") or "").strip()

        if preserved_dialogue_lines is not None and not preserved_content:
            preserved_content = "".join(
                str(item.get("text") or "")
                for item in preserved_dialogue_lines
                if isinstance(item, dict)
            )

        if preserved_dialogue_lines is None and not preserved_content:
            dialogue_lines = self._rebuild_content_dialogue_lines(shots)
            merged_content = "".join(str(shot.get("voice_content") or "") for shot in shots)
        else:
            dialogue_lines = preserved_dialogue_lines or []
            merged_content = preserved_content

        output_data["dialogue_lines"] = dialogue_lines
        output_data["content"] = merged_content
        output_data["char_count"] = self._count_script_chars(merged_content)
        output_data["shots_locked"] = bool(shots_locked and len(shots) > 0)

        content_stage.output_data = output_data
        has_content = bool(str(merged_content).strip())
        content_stage.status = StageStatus.COMPLETED if has_content else StageStatus.PENDING
        content_stage.progress = 100 if has_content else 0
        content_stage.error_message = None
        content_stage.last_item_complete = len(dialogue_lines) - 1 if dialogue_lines else -1
        content_stage.total_items = len(dialogue_lines)
        content_stage.completed_items = len(dialogue_lines)
        content_stage.skipped_items = 0
        flag_modified(content_stage, "output_data")

    def _reset_compose_stage(self, compose_stage: StageExecution | None) -> None:
        if compose_stage is None:
            return
        output_data = dict(compose_stage.output_data or {})
        safe_delete_file(output_data.get("master_video_path"))
        project_output_dir = compose_stage.project.output_dir if compose_stage.project else None
        if isinstance(project_output_dir, str) and project_output_dir.strip():
            safe_delete_file(project_output_dir.rstrip("/") + "/final_video.mp4")
        merged_files = output_data.get("merged_files")
        if isinstance(merged_files, list):
            for item in merged_files:
                if isinstance(item, dict):
                    safe_delete_file(item.get("file_path"))

        compose_stage.status = StageStatus.PENDING
        compose_stage.progress = 0
        compose_stage.error_message = None
        compose_stage.total_items = None
        compose_stage.completed_items = None
        compose_stage.skipped_items = None
        compose_stage.last_item_complete = -1
        compose_stage.output_data = {}
        flag_modified(compose_stage, "output_data")

    def _reset_simple_stage_with_paths(
        self,
        stage: StageExecution | None,
        *,
        path_fields: list[str],
    ) -> None:
        if stage is None:
            return
        output_data = dict(stage.output_data or {})
        for field in path_fields:
            safe_delete_file(output_data.get(field))
        stage.status = StageStatus.PENDING
        stage.progress = 0
        stage.error_message = None
        stage.total_items = None
        stage.completed_items = None
        stage.skipped_items = None
        stage.last_item_complete = -1
        stage.output_data = {}
        flag_modified(stage, "output_data")

    async def _load_shot_stages(self, project_id: int) -> dict[StageType, StageExecution]:
        result = await self.db.execute(
            select(StageExecution).where(StageExecution.project_id == project_id)
        )
        return {stage.stage_type: stage for stage in result.scalars()}

    async def _collect_shot_items(
        self,
        *,
        stages: dict[StageType, StageExecution],
        allow_empty: bool = False,
    ) -> list[dict[str, Any]]:
        storyboard_stage = stages.get(StageType.STORYBOARD)

        storyboard_shots = []
        if storyboard_stage and isinstance(storyboard_stage.output_data, dict):
            storyboard_shots = self._coerce_shot_items(storyboard_stage.output_data.get("shots"))
        if storyboard_shots:
            return storyboard_shots

        if allow_empty:
            return []

        raise ServiceError(400, "当前没有可编辑的分镜，请先生成分镜")

    async def _persist_shots(
        self,
        *,
        project: Project,
        stages: dict[StageType, StageExecution],
        shots: list[dict[str, Any]],
        shots_locked: bool,
        sync_content_stage: bool = True,
        reset_first_frame_desc_stage: bool = True,
    ) -> None:
        storyboard_stage = stages.get(StageType.STORYBOARD)
        content_stage = stages.get(StageType.CONTENT)
        audio_stage = stages.get(StageType.AUDIO)
        frame_stage = stages.get(StageType.FRAME)
        video_stage = stages.get(StageType.VIDEO)
        subtitle_stage = stages.get(StageType.SUBTITLE)
        burn_subtitle_stage = stages.get(StageType.BURN_SUBTITLE)
        finalize_stage = stages.get(StageType.FINALIZE)
        compose_stage = stages.get(StageType.COMPOSE)
        first_frame_desc_stage = stages.get(StageType.FIRST_FRAME_DESC)

        if storyboard_stage is None:
            raise ServiceError(400, "当前没有可编辑的分镜，请先生成分镜")

        old_storyboard_shots = []
        if storyboard_stage and isinstance(storyboard_stage.output_data, dict):
            old_storyboard_shots = self._coerce_shot_items(
                storyboard_stage.output_data.get("shots")
            )

        old_index_to_shot_id = {
            idx: str(shot.get("shot_id") or "").strip()
            for idx, shot in enumerate(old_storyboard_shots)
            if str(shot.get("shot_id") or "").strip()
        }
        old_storyboard_by_shot = {
            str(shot.get("shot_id") or "").strip(): dict(shot)
            for shot in old_storyboard_shots
            if str(shot.get("shot_id") or "").strip()
        }

        for idx, shot in enumerate(shots):
            shot["order"] = idx
            shot["shot_id"] = str(shot.get("shot_id") or "").strip() or self._new_shot_id()
            shot["line_id"] = str(shot.get("line_id") or "").strip() or f"line_{idx + 1}"
            shot["speaker_id"] = str(shot.get("speaker_id") or "").strip() or DEFAULT_SPEAKER_ID
            shot["speaker_name"] = str(shot.get("speaker_name") or "").strip() or str(
                shot.get("speaker_id") or DEFAULT_SPEAKER_NAME
            )
            shot["voice_content"] = str(shot.get("voice_content") or "")

        new_shot_ids = {
            str(shot.get("shot_id") or "").strip()
            for shot in shots
            if str(shot.get("shot_id") or "").strip()
        }
        old_shot_ids = set(old_storyboard_by_shot.keys())
        deleted_shot_ids = old_shot_ids - new_shot_ids
        new_shot_id_to_index = {
            str(shot.get("shot_id") or "").strip(): idx
            for idx, shot in enumerate(shots)
            if str(shot.get("shot_id") or "").strip()
        }

        if storyboard_stage is not None:
            storyboard_output = dict(storyboard_stage.output_data or {})
            storyboard_output["shots"] = self._build_storyboard_shots(
                shots=shots,
                old_storyboard_by_shot=old_storyboard_by_shot,
            )
            storyboard_output["shot_count"] = len(shots)
            storyboard_stage.output_data = storyboard_output
            storyboard_stage.status = StageStatus.COMPLETED if shots else StageStatus.PENDING
            storyboard_stage.progress = 100 if shots else 0
            storyboard_stage.error_message = None
            storyboard_stage.last_item_complete = len(shots) - 1 if shots else -1
            storyboard_stage.total_items = len(shots)
            storyboard_stage.completed_items = len(shots)
            storyboard_stage.skipped_items = 0
            flag_modified(storyboard_stage, "output_data")

        self._sync_asset_stage_by_shots(
            stage=audio_stage,
            assets_key="audio_assets",
            old_index_to_shot_id=old_index_to_shot_id,
            new_shot_id_to_index=new_shot_id_to_index,
            deleted_shot_ids=deleted_shot_ids,
            path_fields=["file_path", "source_file_path"],
            count_field="shot_count",
        )
        self._sync_asset_stage_by_shots(
            stage=frame_stage,
            assets_key="frame_images",
            old_index_to_shot_id=old_index_to_shot_id,
            new_shot_id_to_index=new_shot_id_to_index,
            deleted_shot_ids=deleted_shot_ids,
            path_fields=["file_path"],
            count_field="frame_count",
        )
        self._sync_asset_stage_by_shots(
            stage=video_stage,
            assets_key="video_assets",
            old_index_to_shot_id=old_index_to_shot_id,
            new_shot_id_to_index=new_shot_id_to_index,
            deleted_shot_ids=deleted_shot_ids,
            path_fields=["file_path"],
            count_field="video_count",
        )
        if sync_content_stage:
            self._sync_content_stage_from_shots(
                content_stage=content_stage,
                shots=shots,
                shots_locked=shots_locked,
            )
        elif content_stage is not None:
            output_data = dict(content_stage.output_data or {})
            output_data["shots_locked"] = False
            content_stage.output_data = output_data
            flag_modified(content_stage, "output_data")
        self._reset_compose_stage(compose_stage)
        self._reset_simple_stage_with_paths(
            subtitle_stage,
            path_fields=["subtitle_file_path"],
        )
        self._reset_simple_stage_with_paths(
            burn_subtitle_stage,
            path_fields=["burned_video_path"],
        )
        self._reset_simple_stage_with_paths(
            finalize_stage,
            path_fields=[],
        )

        if reset_first_frame_desc_stage and first_frame_desc_stage is not None:
            first_frame_desc_stage.status = StageStatus.PENDING
            first_frame_desc_stage.progress = 0
            first_frame_desc_stage.error_message = None
            first_frame_desc_stage.total_items = None
            first_frame_desc_stage.completed_items = None
            first_frame_desc_stage.skipped_items = None
            first_frame_desc_stage.last_item_complete = -1
            first_frame_desc_stage.output_data = {}
            flag_modified(first_frame_desc_stage, "output_data")

        await self.db.commit()

    async def replace_storyboard_and_clear_downstream(
        self,
        project_id: int,
        *,
        storyboard_payload: dict[str, Any],
    ) -> dict[str, Any]:
        project = await self.get_project_or_404(project_id)
        output_dir = self._get_output_dir(project)
        stages = await self._load_shot_stages(project_id)

        storyboard_stage = stages.get(StageType.STORYBOARD)
        if storyboard_stage is None:
            raise ServiceError(400, "当前没有可编辑的分镜，请先生成分镜")

        content_stage = stages.get(StageType.CONTENT)
        if content_stage is not None and isinstance(content_stage.output_data, dict):
            content_output = dict(content_stage.output_data)
            content_output["shots_locked"] = True
            content_stage.output_data = content_output
            flag_modified(content_stage, "output_data")

        storyboard_stage.output_data = dict(storyboard_payload)
        storyboard_stage.status = StageStatus.COMPLETED
        storyboard_stage.progress = 100
        storyboard_stage.error_message = None
        shot_count = len(list((storyboard_payload or {}).get("shots") or []))
        storyboard_stage.total_items = shot_count
        storyboard_stage.completed_items = shot_count
        storyboard_stage.skipped_items = 0
        storyboard_stage.last_item_complete = shot_count - 1 if shot_count > 0 else -1
        flag_modified(storyboard_stage, "output_data")

        first_frame_desc_stage = stages.get(StageType.FIRST_FRAME_DESC)
        if first_frame_desc_stage is not None:
            self._reset_stage_runtime_fields(first_frame_desc_stage)
            first_frame_desc_stage.output_data = {}
            flag_modified(first_frame_desc_stage, "output_data")

        frame_stage = stages.get(StageType.FRAME)
        if frame_stage is not None:
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
        if video_stage is not None:
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
        if audio_stage is not None:
            audio_output = dict(audio_stage.output_data or {})
            merged_audio_assets = await self._build_smart_merged_audio_assets(
                storyboard_payload=storyboard_payload,
                existing_audio_output=audio_output,
                output_dir=output_dir,
            )
            audio_assets = audio_output.get("audio_assets")
            if isinstance(audio_assets, list):
                for asset in audio_assets:
                    if isinstance(asset, dict):
                        safe_delete_file(asset.get("file_path"))
                        safe_delete_file(asset.get("source_file_path"))
            self._reset_stage_runtime_fields(audio_stage)
            if merged_audio_assets is not None:
                preserved_audio_output = {
                    key: value
                    for key, value in audio_output.items()
                    if key
                    not in {
                        "audio_assets",
                        "shot_count",
                        "total_duration",
                        "generating_shots",
                        "progress_message",
                        "warnings",
                        "failed_items",
                    }
                }
                audio_stage.output_data = {
                    **preserved_audio_output,
                    "audio_assets": merged_audio_assets,
                    "shot_count": len(merged_audio_assets),
                    "total_duration": sum(
                        float(item.get("duration") or 0.0) for item in merged_audio_assets
                    ),
                    "generating_shots": {},
                }
                audio_stage.status = StageStatus.COMPLETED
                audio_stage.progress = 100
                audio_stage.error_message = None
                audio_stage.total_items = len(merged_audio_assets)
                audio_stage.completed_items = len(merged_audio_assets)
                audio_stage.skipped_items = 0
                audio_stage.last_item_complete = (
                    len(merged_audio_assets) - 1 if merged_audio_assets else -1
                )
            else:
                audio_stage.output_data = {
                    "audio_assets": [],
                    "shot_count": 0,
                    "total_duration": 0.0,
                    "generating_shots": {},
                }
            flag_modified(audio_stage, "output_data")

        audio_dir = output_dir / "audio"
        if audio_dir.exists():
            keep_paths: set[Path] = set()
            if audio_stage is not None and isinstance(audio_stage.output_data, dict):
                for asset in audio_stage.output_data.get("audio_assets", []):
                    if not isinstance(asset, dict):
                        continue
                    for field in ("file_path", "source_file_path"):
                        value = str(asset.get(field) or "").strip()
                        if value:
                            keep_paths.add(Path(value))
            for file_path in audio_dir.glob("shot_*.*"):
                if file_path.is_file() and file_path not in keep_paths:
                    safe_delete_file(str(file_path))

        self._reset_compose_stage(stages.get(StageType.COMPOSE))
        self._reset_simple_stage_with_paths(
            stages.get(StageType.SUBTITLE),
            path_fields=["subtitle_file_path"],
        )
        self._reset_simple_stage_with_paths(
            stages.get(StageType.BURN_SUBTITLE),
            path_fields=["burned_video_path"],
        )
        self._reset_simple_stage_with_paths(
            stages.get(StageType.FINALIZE),
            path_fields=[],
        )

        subtitle_dir = output_dir / "subtitles"
        if subtitle_dir.exists():
            for subtitle_file in subtitle_dir.glob("*"):
                if subtitle_file.is_file():
                    safe_delete_file(str(subtitle_file))

        safe_delete_file(str(output_dir / "final_video.mp4"))
        await self.db.commit()
        return {"success": True}

    async def list_shots(self, project_id: int) -> dict[str, Any]:
        await self.get_project_or_404(project_id)
        stages = await self._load_shot_stages(project_id)
        shots = await self._collect_shot_items(stages=stages, allow_empty=True)
        content_stage = stages.get(StageType.CONTENT)
        content_output = dict(content_stage.output_data or {}) if content_stage else {}

        return {
            "success": True,
            "data": {
                "shots": shots,
                "shot_count": len(shots),
                "shots_locked": bool(content_output.get("shots_locked")),
            },
        }

    async def insert_shots(
        self,
        project_id: int,
        *,
        anchor_index: int,
        direction: str,
        count: int,
    ) -> dict[str, Any]:
        project = await self.get_project_or_404(project_id)
        stages = await self._load_shot_stages(project_id)
        shots = await self._collect_shot_items(stages=stages)

        if count <= 0:
            raise ServiceError(400, "插入数量必须大于 0")
        if count > 20:
            raise ServiceError(400, "单次最多插入 20 个分镜位")
        if anchor_index < -1 or (len(shots) > 0 and anchor_index >= len(shots)):
            raise ServiceError(400, "anchor_index 超出范围")
        normalized_direction = str(direction or "after").strip().lower()
        if normalized_direction not in {"before", "after"}:
            raise ServiceError(400, "direction 必须是 before 或 after")

        if normalized_direction == "before":
            insert_at = max(0, anchor_index)
        else:
            insert_at = anchor_index + 1
        insert_at = max(0, min(insert_at, len(shots)))

        new_items = []
        for idx in range(count):
            new_items.append(
                {
                    "shot_id": self._new_shot_id(),
                    "voice_content": "",
                    "speaker_id": DEFAULT_SPEAKER_ID,
                    "speaker_name": DEFAULT_SPEAKER_NAME,
                    "speaker_type": "role",
                    "line_id": f"line_insert_{insert_at}_{idx + 1}",
                    "video_prompt": "",
                    "first_frame_description": "",
                    "video_reference_slots": [],
                    "first_frame_reference_slots": [],
                }
            )

        next_shots = [*shots[:insert_at], *new_items, *shots[insert_at:]]
        await self._persist_shots(
            project=project,
            stages=stages,
            shots=next_shots,
            shots_locked=True,
        )
        return await self.list_shots(project_id)

    async def delete_shot(self, project_id: int, shot_id: str) -> dict[str, Any]:
        project = await self.get_project_or_404(project_id)
        stages = await self._load_shot_stages(project_id)
        shots = await self._collect_shot_items(stages=stages)

        normalized_id = str(shot_id or "").strip()
        if not normalized_id:
            raise ServiceError(400, "shot_id 不能为空")

        next_shots = [
            shot for shot in shots if str(shot.get("shot_id") or "").strip() != normalized_id
        ]
        if len(next_shots) == len(shots):
            raise ServiceError(404, "分镜位不存在")

        await self._persist_shots(
            project=project,
            stages=stages,
            shots=next_shots,
            shots_locked=True,
        )
        return await self.list_shots(project_id)

    async def update_shot(
        self,
        project_id: int,
        shot_id: str,
        *,
        voice_content: str | None = None,
        speaker_id: str | None = None,
        speaker_name: str | None = None,
    ) -> dict[str, Any]:
        project = await self.get_project_or_404(project_id)
        stages = await self._load_shot_stages(project_id)
        shots = await self._collect_shot_items(stages=stages)

        normalized_id = str(shot_id or "").strip()
        if not normalized_id:
            raise ServiceError(400, "shot_id 不能为空")

        target = None
        for shot in shots:
            if str(shot.get("shot_id") or "").strip() == normalized_id:
                target = shot
                break
        if target is None:
            raise ServiceError(404, "分镜位不存在")

        if voice_content is None and speaker_id is None and speaker_name is None:
            return await self.list_shots(project_id)

        if voice_content is not None:
            target["voice_content"] = str(voice_content)
        if speaker_id is not None:
            normalized_speaker_id = str(speaker_id).strip() or DEFAULT_SPEAKER_ID
            target["speaker_id"] = normalized_speaker_id
            if speaker_name is None and not str(target.get("speaker_name") or "").strip():
                target["speaker_name"] = normalized_speaker_id
        if speaker_name is not None:
            target["speaker_name"] = str(speaker_name).strip() or str(
                target.get("speaker_id") or DEFAULT_SPEAKER_NAME
            )

        await self._persist_shots(
            project=project,
            stages=stages,
            shots=shots,
            shots_locked=True,
            reset_first_frame_desc_stage=False,
        )
        return await self.list_shots(project_id)

    async def reorder_shots(
        self,
        project_id: int,
        *,
        ordered_shot_ids: list[str],
    ) -> dict[str, Any]:
        project = await self.get_project_or_404(project_id)
        stages = await self._load_shot_stages(project_id)
        shots = await self._collect_shot_items(stages=stages)

        if not isinstance(ordered_shot_ids, list) or not ordered_shot_ids:
            raise ServiceError(400, "ordered_shot_ids 不能为空")

        normalized_ids = [str(item or "").strip() for item in ordered_shot_ids]
        if any(not item for item in normalized_ids):
            raise ServiceError(400, "ordered_shot_ids 包含空值")

        existing_ids = [str(shot.get("shot_id") or "").strip() for shot in shots]
        if sorted(existing_ids) != sorted(normalized_ids):
            raise ServiceError(400, "ordered_shot_ids 与当前分镜位集合不一致")

        shot_by_id = {str(shot.get("shot_id") or "").strip(): dict(shot) for shot in shots}
        next_shots = [shot_by_id[item] for item in normalized_ids]
        await self._persist_shots(
            project=project,
            stages=stages,
            shots=next_shots,
            shots_locked=True,
            reset_first_frame_desc_stage=False,
        )
        return await self.list_shots(project_id)

    async def move_shot(
        self,
        project_id: int,
        *,
        shot_id: str,
        direction: str,
        step: int,
    ) -> dict[str, Any]:
        project = await self.get_project_or_404(project_id)
        stages = await self._load_shot_stages(project_id)
        shots = await self._collect_shot_items(stages=stages)

        normalized_id = str(shot_id or "").strip()
        if not normalized_id:
            raise ServiceError(400, "shot_id 不能为空")
        if step <= 0:
            raise ServiceError(400, "step 必须大于 0")

        current_index = -1
        for idx, shot in enumerate(shots):
            if str(shot.get("shot_id") or "").strip() == normalized_id:
                current_index = idx
                break
        if current_index < 0:
            raise ServiceError(404, "分镜位不存在")

        normalized_direction = str(direction or "").strip().lower()
        if normalized_direction == "up":
            target_index = max(0, current_index - step)
        elif normalized_direction == "down":
            target_index = min(len(shots) - 1, current_index + step)
        else:
            raise ServiceError(400, "direction 必须是 up 或 down")

        if target_index == current_index:
            return await self.list_shots(project_id)

        item = shots.pop(current_index)
        shots.insert(target_index, item)

        await self._persist_shots(
            project=project,
            stages=stages,
            shots=shots,
            shots_locked=True,
            reset_first_frame_desc_stage=False,
        )
        return await self.list_shots(project_id)

    async def clear_shots_and_unlock_content(self, project_id: int) -> dict[str, Any]:
        project = await self.get_project_or_404(project_id)
        stages = await self._load_shot_stages(project_id)
        await self._persist_shots(
            project=project,
            stages=stages,
            shots=[],
            shots_locked=False,
            sync_content_stage=False,
        )
        return {"success": True}
