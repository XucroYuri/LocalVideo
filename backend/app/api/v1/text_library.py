import asyncio
import json
import time

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.session import AsyncSessionLocal
from app.models.text_library import TextImportJobStatus, TextLibraryImportJob
from app.schemas.text_library import (
    TextLibraryCancelResponse,
    TextLibraryImportCopyRequest,
    TextLibraryImportJobResponse,
    TextLibraryImportLinksCreateResponse,
    TextLibraryImportLinksRequest,
    TextLibraryItemResponse,
    TextLibraryListResponse,
    TextLibraryUpdateRequest,
)
from app.services.text_library_service import TextLibraryService

router = APIRouter(prefix="/text-library", tags=["text-library"])
IMPORT_EVENTS_STREAM_MAX_LIFETIME_SECONDS = 25.0


@router.get("", response_model=TextLibraryListResponse)
async def list_text_library_items(
    q: str | None = Query(default=None),
    enabled_only: bool = Query(default=False),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    service = TextLibraryService(db)
    items, total = await service.list(
        q=q,
        enabled_only=enabled_only,
        page=page,
        page_size=page_size,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/import/copy", response_model=TextLibraryItemResponse, status_code=201)
async def import_text_library_by_copy(
    request: TextLibraryImportCopyRequest,
    db: AsyncSession = Depends(get_db),
):
    service = TextLibraryService(db)
    return await service.import_from_copy(request.content)


@router.post("/import/files", response_model=list[TextLibraryItemResponse], status_code=201)
async def import_text_library_by_files(
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    service = TextLibraryService(db)
    return await service.import_from_files(files)


@router.post("/import/links", response_model=TextLibraryImportLinksCreateResponse, status_code=202)
async def import_text_library_by_links(
    request: TextLibraryImportLinksRequest,
    db: AsyncSession = Depends(get_db),
):
    service = TextLibraryService(db)
    result = await service.create_link_import_job(request.urls_text)
    return result


@router.get("/import-jobs/{job_id}", response_model=TextLibraryImportJobResponse)
async def get_text_library_import_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    service = TextLibraryService(db)
    return await service.get_import_job(job_id)


@router.post("/import-jobs/cancel-all", response_model=TextLibraryCancelResponse)
async def cancel_all_text_import_jobs(
    db: AsyncSession = Depends(get_db),
):
    service = TextLibraryService(db)
    return await service.cancel_all_import_jobs(canceled_by="user")


@router.post("/import-jobs/{job_id}/cancel", response_model=TextLibraryCancelResponse)
async def cancel_text_import_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    service = TextLibraryService(db)
    return await service.cancel_import_job(job_id, canceled_by="user")


@router.post("/import-tasks/{task_id}/cancel", response_model=TextLibraryCancelResponse)
async def cancel_text_import_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = TextLibraryService(db)
    return await service.cancel_import_task(task_id, reason="user_delete")


@router.post("/import-tasks/by-item/{item_id}/cancel", response_model=TextLibraryCancelResponse)
async def cancel_text_import_task_by_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = TextLibraryService(db)
    return await service.cancel_import_task_by_item(item_id)


@router.post("/import-tasks/{task_id}/retry", response_model=TextLibraryImportLinksCreateResponse)
async def retry_text_import_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = TextLibraryService(db)
    return await service.retry_import_task(task_id)


@router.post("/import-jobs/restart-interrupted", response_model=TextLibraryCancelResponse)
async def restart_interrupted_text_import_tasks(
    db: AsyncSession = Depends(get_db),
):
    service = TextLibraryService(db)
    return await service.restart_interrupted_tasks()


@router.get("/import-events/stream")
async def stream_text_import_events(request: Request):
    async def _safe_stream():
        last_payload = ""
        deadline = time.monotonic() + IMPORT_EVENTS_STREAM_MAX_LIFETIME_SECONDS
        while True:
            if await request.is_disconnected():
                break
            if time.monotonic() >= deadline:
                break
            async with AsyncSessionLocal() as db:
                service = TextLibraryService(db)
                jobs_result = await db.execute(
                    select(TextLibraryImportJob).where(
                        TextLibraryImportJob.status.in_(
                            [TextImportJobStatus.PENDING, TextImportJobStatus.RUNNING]
                        )
                    )
                )
                active_ids = [one.id for one in jobs_result.scalars().all()]
                jobs: list[dict] = []
                for job_id in active_ids[:50]:
                    try:
                        jobs.append(await service.get_import_job(job_id))
                    except Exception:
                        continue

                try:
                    payload = json.dumps(
                        {
                            "library": "text",
                            "active_job_ids": active_ids,
                            "jobs": jobs,
                        },
                        ensure_ascii=False,
                        default=str,
                    )
                except Exception:
                    await asyncio.sleep(1.5)
                    continue

                if payload != last_payload:
                    yield f"event: import.update\ndata: {payload}\n\n"
                    last_payload = payload
            await asyncio.sleep(1.5)

    return StreamingResponse(_safe_stream(), media_type="text/event-stream")


@router.post("/{item_id}/retry", response_model=TextLibraryItemResponse)
async def retry_text_library_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = TextLibraryService(db)
    return await service.retry_item(item_id)


@router.patch("/{item_id}", response_model=TextLibraryItemResponse)
async def update_text_library_item(
    item_id: int,
    request: TextLibraryUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = TextLibraryService(db)
    return await service.update(item_id, request.model_dump(exclude_unset=True))


@router.delete("/{item_id}", status_code=204)
async def delete_text_library_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = TextLibraryService(db)
    await service.delete(item_id)
