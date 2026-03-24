from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import Source, SourceType
from app.models.text_library import TextLibraryItem
from app.schemas.source import SourceCreate, SourceUpdate


class SourceService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, project_id: int, data: SourceCreate) -> Source:
        source = Source(
            project_id=project_id,
            type=data.type,
            title=data.title,
            content=data.content,
            selected=data.selected,
        )
        self.db.add(source)
        await self.db.commit()
        await self.db.refresh(source)
        return source

    async def get(self, source_id: int) -> Source | None:
        result = await self.db.execute(select(Source).where(Source.id == source_id))
        return result.scalar_one_or_none()

    async def list_by_project(
        self, project_id: int, selected_only: bool = False
    ) -> tuple[list[Source], int]:
        query = select(Source).where(Source.project_id == project_id)

        if selected_only:
            query = query.where(Source.selected == True)  # noqa: E712

        query = query.order_by(Source.created_at.desc())

        count_query = (
            select(func.count()).select_from(Source).where(Source.project_id == project_id)
        )
        if selected_only:
            count_query = count_query.where(Source.selected == True)  # noqa: E712

        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        result = await self.db.execute(query)
        sources = list(result.scalars().all())

        return sources, total

    async def update(self, source_id: int, data: SourceUpdate) -> Source | None:
        source = await self.get(source_id)
        if not source:
            return None

        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(source, key, value)

        await self.db.commit()
        await self.db.refresh(source)
        return source

    async def delete(self, source_id: int) -> bool:
        source = await self.get(source_id)
        if not source:
            return False

        await self.db.delete(source)
        await self.db.commit()
        return True

    async def batch_update_selected(
        self, project_id: int, source_ids: list[int], selected: bool
    ) -> int:
        """批量更新来源的 selected 状态"""
        stmt = (
            update(Source)
            .where(Source.project_id == project_id, Source.id.in_(source_ids))
            .values(selected=selected)
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount

    async def get_selected_content(self, project_id: int) -> str:
        """获取所有选中来源的内容，合并为一个字符串"""
        sources, _ = await self.list_by_project(project_id, selected_only=True)
        if not sources:
            return ""

        # 按创建时间排序（最早创建的在前）
        sources.sort(key=lambda s: s.created_at)

        contents = []
        for source in sources:
            contents.append(f"【{source.title}】\n{source.content}")

        return "\n\n---\n\n".join(contents)

    async def import_from_text_library(
        self,
        project_id: int,
        text_library_ids: list[int],
    ) -> dict:
        unique_ids: list[int] = []
        for item in text_library_ids:
            try:
                normalized = int(item)
            except (TypeError, ValueError):
                continue
            if normalized <= 0:
                continue
            if normalized not in unique_ids:
                unique_ids.append(normalized)
        if not unique_ids:
            return {
                "success": True,
                "summary": {
                    "requested_count": 0,
                    "created_count": 0,
                    "skipped_count": 0,
                    "failed_count": 0,
                },
                "results": [],
            }

        result = await self.db.execute(
            select(TextLibraryItem).where(TextLibraryItem.id.in_(unique_ids))
        )
        item_map = {item.id: item for item in result.scalars().all()}

        created_count = 0
        skipped_count = 0
        failed_count = 0
        results: list[dict] = []

        for library_id in unique_ids:
            item = item_map.get(library_id)
            if not item:
                failed_count += 1
                results.append(
                    {
                        "text_library_id": library_id,
                        "status": "failed",
                        "source_id": None,
                        "message": "文本库卡片不存在",
                    }
                )
                continue

            if not bool(item.is_enabled):
                skipped_count += 1
                results.append(
                    {
                        "text_library_id": library_id,
                        "status": "skipped",
                        "source_id": None,
                        "message": "文本库卡片已禁用，已跳过",
                    }
                )
                continue

            source = Source(
                project_id=project_id,
                type=SourceType.TEXT,
                title=str(item.name or "").strip() or "文本来源",
                content=str(item.content or "").strip(),
                selected=True,
            )
            if not source.content:
                skipped_count += 1
                results.append(
                    {
                        "text_library_id": library_id,
                        "status": "skipped",
                        "source_id": None,
                        "message": "文本内容为空，已跳过",
                    }
                )
                continue
            self.db.add(source)
            await self.db.flush()
            created_count += 1
            results.append(
                {
                    "text_library_id": library_id,
                    "status": "created",
                    "source_id": source.id,
                    "message": "导入成功",
                }
            )

        await self.db.commit()
        return {
            "success": True,
            "summary": {
                "requested_count": len(unique_ids),
                "created_count": created_count,
                "skipped_count": skipped_count,
                "failed_count": failed_count,
            },
            "results": results,
        }
