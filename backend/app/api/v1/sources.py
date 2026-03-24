from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.source import (
    SourceBatchUpdate,
    SourceCreate,
    SourceImportFromTextLibraryRequest,
    SourceImportFromTextLibraryResponse,
    SourceListResponse,
    SourceResponse,
    SourceUpdate,
)
from app.services.project_service import ProjectService
from app.services.source_service import SourceService

router = APIRouter(prefix="/projects/{project_id}/sources", tags=["sources"])


@router.post("", response_model=SourceResponse, status_code=201)
async def create_source(
    project_id: int,
    data: SourceCreate,
    db: AsyncSession = Depends(get_db),
):
    # 验证项目存在
    project_service = ProjectService(db)
    project = await project_service.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    service = SourceService(db)
    source = await service.create(project_id, data)
    return source


@router.get("", response_model=SourceListResponse)
async def list_sources(
    project_id: int,
    selected_only: bool = False,
    db: AsyncSession = Depends(get_db),
):
    service = SourceService(db)
    sources, total = await service.list_by_project(project_id, selected_only)
    return {"items": sources, "total": total}


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(
    project_id: int,
    source_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = SourceService(db)
    source = await service.get(source_id)
    if not source or source.project_id != project_id:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.patch("/{source_id}", response_model=SourceResponse)
async def update_source(
    project_id: int,
    source_id: int,
    data: SourceUpdate,
    db: AsyncSession = Depends(get_db),
):
    service = SourceService(db)
    source = await service.get(source_id)
    if not source or source.project_id != project_id:
        raise HTTPException(status_code=404, detail="Source not found")

    updated_source = await service.update(source_id, data)
    return updated_source


@router.delete("/{source_id}", status_code=204)
async def delete_source(
    project_id: int,
    source_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = SourceService(db)
    source = await service.get(source_id)
    # Idempotent delete: if source is already gone (or not under this project),
    # treat it as success to avoid frontend stale-id failures.
    if not source or source.project_id != project_id:
        return

    await service.delete(source_id)


@router.post("/batch-update", status_code=200)
async def batch_update_sources(
    project_id: int,
    data: SourceBatchUpdate,
    db: AsyncSession = Depends(get_db),
):
    service = SourceService(db)
    updated_count = await service.batch_update_selected(project_id, data.source_ids, data.selected)
    return {"updated_count": updated_count}


@router.post("/import-from-text-library", response_model=SourceImportFromTextLibraryResponse)
async def import_sources_from_text_library(
    project_id: int,
    data: SourceImportFromTextLibraryRequest,
    db: AsyncSession = Depends(get_db),
):
    project_service = ProjectService(db)
    project = await project_service.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    service = SourceService(db)
    return await service.import_from_text_library(project_id, data.text_library_ids)
