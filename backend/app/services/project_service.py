import json
import re
import shutil
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.core.errors import ServiceError
from app.core.project_mode import (
    VIDEO_MODE_AUDIO_VISUAL_DRIVEN,
    VIDEO_MODE_ORAL_SCRIPT_DRIVEN,
    VIDEO_TYPE_CUSTOM,
    resolve_script_mode_from_video_type,
    resolve_video_mode,
    resolve_video_type,
)
from app.models.asset import Asset
from app.models.project import Project, ProjectStatus
from app.models.source import Source
from app.models.stage import StageExecution, StageType
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.services.stage_service import StageService
from app.stages.common.paths import resolve_output_dir_value, to_storage_public_path


class ProjectService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _sanitize_filename(self, name: str) -> str:
        """清理文件名中的非法字符"""
        # 替换 Windows/Unix 非法字符
        return re.sub(r'[<>:"/\\|?*]', "-", name)

    def _build_output_dir(self, title: str) -> Path:
        now = datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        safe_title = self._sanitize_filename(title)
        base_name = f"{timestamp}_{safe_title}"
        base_dir = Path(settings.storage_path)
        candidate = base_dir / base_name
        suffix = 1
        while candidate.exists():
            candidate = base_dir / f"{base_name}_{suffix}"
            suffix += 1
        return candidate

    async def _build_duplicate_title(self, source_title: str) -> str:
        base = f"{source_title}_副本"
        like_pattern = f"{base}%"
        result = await self.db.execute(
            select(Project.title).where(Project.title.like(like_pattern))
        )
        existing_titles = {
            str(item or "").strip() for item in result.scalars().all() if str(item or "").strip()
        }
        if base not in existing_titles:
            return base

        idx = 1
        while True:
            candidate = f"{base}（{idx}）"
            if candidate not in existing_titles:
                return candidate
            idx += 1

    @staticmethod
    def _replace_path_prefix(value, old_prefix: str | None, new_prefix: str) -> object:
        if isinstance(value, dict):
            return {
                key: ProjectService._replace_path_prefix(item, old_prefix, new_prefix)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                ProjectService._replace_path_prefix(item, old_prefix, new_prefix) for item in value
            ]
        if isinstance(value, str):
            if old_prefix and old_prefix in value:
                return value.replace(old_prefix, new_prefix)
            return value
        return value

    @staticmethod
    def _validate_video_mode(video_mode: str) -> None:
        if video_mode == VIDEO_MODE_AUDIO_VISUAL_DRIVEN:
            raise ServiceError(400, "声画驱动暂未支持")

    async def _initialize_project_video_preset(self, project: Project) -> None:
        if project.video_mode != VIDEO_MODE_ORAL_SCRIPT_DRIVEN:
            return
        if project.video_type == VIDEO_TYPE_CUSTOM:
            return

        script_mode = resolve_script_mode_from_video_type(project.video_type)
        stage_service = StageService(self.db)
        await stage_service._reset_reference_stage_for_mode(project, script_mode)
        await stage_service.update_content_data(
            project_id=project.id,
            title=None,
            content="",
            script_mode=script_mode,
            roles=[],
            dialogue_lines=[],
            create_missing_references=False,
        )

    async def create(self, data: ProjectCreate) -> Project:
        output_dir = self._build_output_dir(data.title)
        resolved_video_mode = resolve_video_mode(data.video_mode)
        resolved_video_type = resolve_video_type(
            data.video_type,
            video_mode=resolved_video_mode,
        )
        self._validate_video_mode(resolved_video_mode)
        config_data = dict(data.config or {})
        config_data.setdefault(
            "script_mode",
            resolve_script_mode_from_video_type(resolved_video_type),
        )

        # 创建存储目录
        output_dir.mkdir(parents=True, exist_ok=True)

        project = Project(
            title=data.title,
            keywords=data.keywords,
            input_text=data.input_text,
            style=data.style if data.style is not None else "",
            target_duration=data.target_duration or 60,
            video_mode=resolved_video_mode,
            video_type=resolved_video_type,
            config=config_data,
            status=ProjectStatus.DRAFT,
            output_dir=to_storage_public_path(output_dir),
        )
        self.db.add(project)
        await self.db.commit()
        await self.db.refresh(project)
        await self._initialize_project_video_preset(project)
        await self.db.refresh(project)
        return project

    async def duplicate(self, project_id: int) -> Project | None:
        source_project = await self.get(project_id)
        if not source_project:
            return None

        duplicate_title = await self._build_duplicate_title(source_project.title)
        duplicate_output_dir = self._build_output_dir(duplicate_title)
        source_output_dir = resolve_output_dir_value(source_project.output_dir)
        old_prefix = str(source_output_dir) if source_output_dir else None
        new_prefix = str(duplicate_output_dir)
        old_public_prefix = to_storage_public_path(source_output_dir) if source_output_dir else None
        new_public_prefix = to_storage_public_path(duplicate_output_dir)

        def remap_storage_paths(value):
            mapped = self._replace_path_prefix(value, old_prefix, new_prefix)
            return self._replace_path_prefix(mapped, old_public_prefix, new_public_prefix)

        copied_storage = False
        try:
            duplicate_output_dir.parent.mkdir(parents=True, exist_ok=True)
            if source_output_dir and source_output_dir.exists() and source_output_dir.is_dir():
                shutil.copytree(source_output_dir, duplicate_output_dir)
            else:
                duplicate_output_dir.mkdir(parents=True, exist_ok=True)
            copied_storage = True

            duplicate_project = Project(
                title=duplicate_title,
                keywords=source_project.keywords,
                input_text=source_project.input_text,
                style=source_project.style,
                target_duration=source_project.target_duration,
                video_mode=source_project.video_mode,
                video_type=source_project.video_type,
                config=deepcopy(source_project.config)
                if source_project.config is not None
                else None,
                status=source_project.status,
                current_stage=source_project.current_stage,
                error_message=source_project.error_message,
                cover_emoji=source_project.cover_emoji,
                cover_generation_attempted=source_project.cover_generation_attempted,
                cover_generated_at=source_project.cover_generated_at,
                output_dir=to_storage_public_path(duplicate_output_dir),
            )
            self.db.add(duplicate_project)
            await self.db.flush()

            source_result = await self.db.execute(
                select(Source).where(Source.project_id == source_project.id)
            )
            for source in source_result.scalars().all():
                self.db.add(
                    Source(
                        project_id=duplicate_project.id,
                        type=source.type,
                        title=source.title,
                        content=source.content,
                        selected=source.selected,
                    )
                )

            asset_result = await self.db.execute(
                select(Asset).where(Asset.project_id == source_project.id)
            )
            for asset in asset_result.scalars().all():
                self.db.add(
                    Asset(
                        project_id=duplicate_project.id,
                        asset_type=asset.asset_type,
                        shot_index=asset.shot_index,
                        file_path=remap_storage_paths(asset.file_path),
                        json_content=remap_storage_paths(
                            deepcopy(asset.json_content) if asset.json_content is not None else None
                        ),
                        asset_metadata=remap_storage_paths(
                            deepcopy(asset.asset_metadata)
                            if asset.asset_metadata is not None
                            else None
                        ),
                    )
                )

            stage_result = await self.db.execute(
                select(StageExecution)
                .where(StageExecution.project_id == source_project.id)
                .order_by(StageExecution.stage_number, StageExecution.id)
            )
            for stage in stage_result.scalars().all():
                self.db.add(
                    StageExecution(
                        project_id=duplicate_project.id,
                        stage_type=stage.stage_type,
                        stage_number=stage.stage_number,
                        status=stage.status,
                        progress=stage.progress,
                        input_data=remap_storage_paths(
                            deepcopy(stage.input_data) if stage.input_data is not None else None
                        ),
                        output_data=remap_storage_paths(
                            deepcopy(stage.output_data) if stage.output_data is not None else None
                        ),
                        error_message=stage.error_message,
                        last_item_complete=stage.last_item_complete,
                        total_items=stage.total_items,
                        completed_items=stage.completed_items,
                        skipped_items=stage.skipped_items,
                    )
                )

            await self.db.commit()
            await self.db.refresh(duplicate_project)
            return duplicate_project
        except Exception:
            await self.db.rollback()
            if copied_storage and duplicate_output_dir.exists():
                shutil.rmtree(duplicate_output_dir, ignore_errors=True)
            raise

    async def get(self, project_id: int) -> Project | None:
        result = await self.db.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one_or_none()

    @staticmethod
    def _compact_preview_text(value: object) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    @classmethod
    def _build_dialogue_preview(cls, stage_output: object) -> str | None:
        if not isinstance(stage_output, dict):
            return None

        dialogue_lines = stage_output.get("dialogue_lines")
        if not isinstance(dialogue_lines, list):
            return None
        valid_lines: list[tuple[str, str]] = []
        for item in dialogue_lines:
            if not isinstance(item, dict):
                continue
            text = cls._compact_preview_text(item.get("text"))
            if not text:
                continue
            speaker_name = cls._compact_preview_text(
                item.get("speaker_name") or item.get("speaker_id")
            )
            valid_lines.append((speaker_name, text))

        if not valid_lines:
            return None

        distinct_speakers = {speaker_name for speaker_name, _ in valid_lines if speaker_name}
        compact_content = cls._compact_preview_text(stage_output.get("content"))
        if len(distinct_speakers) <= 1:
            speaker_name = valid_lines[0][0]
            merged_text = compact_content or "".join(text for _, text in valid_lines)
            if speaker_name:
                return f"{speaker_name}: {merged_text}"
            return merged_text

        return " ".join(
            f"{speaker_name}: {text}" if speaker_name else text
            for speaker_name, text in valid_lines
        )

    @staticmethod
    def _build_first_video_url(stage_output: object) -> str | None:
        if not isinstance(stage_output, dict):
            return None

        video_assets = stage_output.get("video_assets")
        if not isinstance(video_assets, list):
            return None

        target_item = None
        for item in video_assets:
            if not isinstance(item, dict):
                continue
            if int(item.get("shot_index") or -1) == 0:
                target_item = item
                break

        if target_item is None:
            for item in video_assets:
                if isinstance(item, dict):
                    target_item = item
                    break

        if not isinstance(target_item, dict):
            return None

        file_path = str(target_item.get("file_path") or "").strip()
        if not file_path:
            return None
        updated_at = target_item.get("updated_at")
        if isinstance(updated_at, int):
            return f"{file_path}?t={updated_at}"
        return file_path

    async def list(
        self,
        page: int = 1,
        page_size: int = 20,
        status: ProjectStatus | None = None,
        q: str | None = None,
    ) -> tuple[list[Project], int]:
        query = select(Project).order_by(Project.created_at.desc())

        if status:
            query = query.where(Project.status == status)

        count_query = select(func.count()).select_from(Project)
        if status:
            count_query = count_query.where(Project.status == status)

        keyword = str(q or "").strip()
        if keyword:
            like_pattern = f"%{keyword}%"
            text_filter = or_(
                Project.title.ilike(like_pattern),
                Project.keywords.ilike(like_pattern),
                Project.input_text.ilike(like_pattern),
            )
            query = query.where(text_filter)
            count_query = count_query.where(text_filter)

        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(query)
        projects = list(result.scalars().all())

        if projects:
            project_ids = [project.id for project in projects]
            stage_result = await self.db.execute(
                select(StageExecution)
                .where(
                    StageExecution.project_id.in_(project_ids),
                    StageExecution.stage_type.in_([StageType.CONTENT, StageType.VIDEO]),
                )
                .order_by(
                    StageExecution.project_id,
                    StageExecution.stage_type,
                    StageExecution.updated_at.desc(),
                    StageExecution.id.desc(),
                )
            )
            dialogue_preview_map: dict[int, str] = {}
            first_video_url_map: dict[int, str] = {}
            for stage in stage_result.scalars().all():
                if stage.stage_type == StageType.CONTENT:
                    if stage.project_id in dialogue_preview_map:
                        continue
                    preview = self._build_dialogue_preview(stage.output_data)
                    if preview:
                        dialogue_preview_map[stage.project_id] = preview
                    continue

                if stage.stage_type == StageType.VIDEO:
                    if stage.project_id in first_video_url_map:
                        continue
                    first_video_url = self._build_first_video_url(stage.output_data)
                    if first_video_url:
                        first_video_url_map[stage.project_id] = first_video_url

            for project in projects:
                setattr(project, "dialogue_preview", dialogue_preview_map.get(project.id))
                setattr(project, "first_video_url", first_video_url_map.get(project.id))

        return projects, total

    async def update(self, project_id: int, data: ProjectUpdate) -> Project | None:
        project = await self.get(project_id)
        if not project:
            return None

        update_data = data.model_dump(exclude_unset=True)

        requested_video_mode = (
            update_data.get("video_mode") if "video_mode" in update_data else project.video_mode
        )
        resolved_video_mode = resolve_video_mode(requested_video_mode)
        resolved_video_type = resolve_video_type(
            update_data.get("video_type", project.video_type),
            video_mode=resolved_video_mode,
        )
        self._validate_video_mode(resolved_video_mode)
        if "video_mode" in update_data:
            update_data["video_mode"] = resolved_video_mode
        if "video_type" in update_data:
            update_data["video_type"] = resolved_video_type

        # 如果 title 变化，需要重命名存储目录
        if "title" in update_data and update_data["title"] != project.title:
            new_title = update_data["title"]
            old_dir = resolve_output_dir_value(project.output_dir)
            if old_dir and old_dir.exists():
                # 从现有路径提取时间戳前缀
                dir_name = old_dir.name
                # 解析出时间戳部分 (前15个字符: YYYYMMDD_HHMMSS)
                if len(dir_name) > 16 and dir_name[8] == "_":
                    timestamp_prefix = dir_name[:15]  # YYYYMMDD_HHMMSS
                    safe_title = self._sanitize_filename(new_title)
                    new_dir_name = f"{timestamp_prefix}_{safe_title}"
                    new_dir = old_dir.parent / new_dir_name

                    # 重命名目录
                    if old_dir != new_dir:
                        old_dir.rename(new_dir)
                        update_data["output_dir"] = to_storage_public_path(new_dir)
                        await self._replace_stage_paths(
                            project_id=project.id,
                            old_prefix=str(old_dir),
                            new_prefix=str(new_dir),
                            old_public_prefix=to_storage_public_path(old_dir),
                            new_public_prefix=to_storage_public_path(new_dir),
                        )

        for key, value in update_data.items():
            setattr(project, key, value)

        if "video_mode" in update_data or "video_type" in update_data:
            project_config = dict(project.config or {})
            project_config["script_mode"] = resolve_script_mode_from_video_type(project.video_type)
            project.config = project_config
            flag_modified(project, "config")

        await self.db.commit()
        await self.db.refresh(project)
        return project

    async def _replace_stage_paths(
        self,
        project_id: int,
        old_prefix: str,
        new_prefix: str,
        old_public_prefix: str | None = None,
        new_public_prefix: str | None = None,
    ) -> None:
        """同步更新阶段输出中引用的存储路径。"""
        result = await self.db.execute(
            select(StageExecution).where(StageExecution.project_id == project_id)
        )
        stages = list(result.scalars().all())
        changed_any = False

        for stage in stages:
            output_data = stage.output_data
            if not output_data:
                continue

            changed = False
            raw = output_data
            if isinstance(raw, str):
                if old_prefix in raw:
                    raw = raw.replace(old_prefix, new_prefix)
                    changed = True
                if old_public_prefix and new_public_prefix and old_public_prefix in raw:
                    raw = raw.replace(old_public_prefix, new_public_prefix)
                    changed = True
                try:
                    obj = json.loads(raw)
                except Exception:
                    obj = None
            else:
                obj = raw

            if isinstance(obj, dict):

                def walk(value):
                    nonlocal changed
                    if isinstance(value, dict):
                        return {k: walk(v) for k, v in value.items()}
                    if isinstance(value, list):
                        return [walk(v) for v in value]
                    if isinstance(value, str):
                        next_value = value
                        if old_prefix in next_value:
                            next_value = next_value.replace(old_prefix, new_prefix)
                        if (
                            old_public_prefix
                            and new_public_prefix
                            and old_public_prefix in next_value
                        ):
                            next_value = next_value.replace(old_public_prefix, new_public_prefix)
                        if next_value != value:
                            changed = True
                            return next_value
                    return value

                new_obj = walk(obj)
                if new_obj != obj:
                    changed = True
                if changed:
                    stage.output_data = new_obj
                    flag_modified(stage, "output_data")
            elif changed:
                stage.output_data = raw
                flag_modified(stage, "output_data")

            if changed:
                changed_any = True

        if changed_any:
            await self.db.commit()

    async def delete(self, project_id: int) -> bool:
        project = await self.get(project_id)
        if not project:
            return False

        # 删除存储目录
        output_dir = resolve_output_dir_value(project.output_dir)
        if output_dir and output_dir.exists():
            shutil.rmtree(output_dir, ignore_errors=True)

        await self.db.delete(project)
        await self.db.commit()
        return True
