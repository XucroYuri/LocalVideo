from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.project import ProjectStatus
from app.schemas.project import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)
from app.services.project_cover_service import ProjectCoverService
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    data: ProjectCreate,
    db: AsyncSession = Depends(get_db),
):
    service = ProjectService(db)
    project = await service.create(data)
    return project


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: ProjectStatus | None = None,
    q: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    service = ProjectService(db)
    projects, total = await service.list(page, page_size, status, q=q)
    return {
        "items": projects,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = ProjectService(db)
    project = await service.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: int,
    data: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
):
    service = ProjectService(db)
    project = await service.update(project_id, data)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("/{project_id}/duplicate", response_model=ProjectResponse, status_code=201)
async def duplicate_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = ProjectService(db)
    project = await service.duplicate(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("/{project_id}/cover/regenerate", response_model=ProjectResponse)
async def regenerate_project_cover(
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = ProjectCoverService(db)
    project = await service.generate_cover(project_id, force=True, fail_if_missing=True)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = ProjectService(db)
    deleted = await service.delete(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
