import asyncio
import json
import time

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.session import AsyncSessionLocal
from app.models.voice_library import VoiceImportJobStatus, VoiceLibraryImportJob
from app.schemas.voice_library import (
    VoiceLibraryCancelResponse,
    VoiceLibraryImportAudioFilesResponse,
    VoiceLibraryImportJobResponse,
    VoiceLibraryImportVideoLinkCreateResponse,
    VoiceLibraryImportVideoLinkRequest,
    VoiceLibraryItemCreate,
    VoiceLibraryItemResponse,
    VoiceLibraryItemUpdate,
    VoiceLibraryListResponse,
)
from app.services.voice_library_service import VoiceLibraryService

router = APIRouter(prefix="/voice-library", tags=["voice-library"])
IMPORT_EVENTS_STREAM_MAX_LIFETIME_SECONDS = 25.0


@router.get("", response_model=VoiceLibraryListResponse)
async def list_voice_library_items(
    q: str | None = Query(default=None),
    enabled_only: bool = Query(default=False),
    with_audio_only: bool = Query(default=False),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    service = VoiceLibraryService(db)
    items, total = await service.list(
        q=q,
        enabled_only=enabled_only,
        with_audio_only=with_audio_only,
        page=page,
        page_size=page_size,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/import/audio-with-text", response_model=VoiceLibraryItemResponse, status_code=201)
async def import_voice_library_audio_with_text(
    file: UploadFile = File(...),
    reference_text: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    service = VoiceLibraryService(db)
    return await service.import_audio_with_text(file=file, reference_text=reference_text)


@router.post(
    "/import/audio-files", response_model=VoiceLibraryImportAudioFilesResponse, status_code=201
)
async def import_voice_library_audio_files(
    files: list[UploadFile] = File(...),
    rows_json: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    service = VoiceLibraryService(db)
    return await service.import_audio_files(files=files, rows_json=rows_json)


@router.post(
    "/import/video-link", response_model=VoiceLibraryImportVideoLinkCreateResponse, status_code=202
)
async def import_voice_library_video_link(
    request: VoiceLibraryImportVideoLinkRequest,
    db: AsyncSession = Depends(get_db),
):
    service = VoiceLibraryService(db)
    return await service.create_video_link_import_job(
        source_url=request.url,
        start_time=request.start_time,
        end_time=request.end_time,
    )


@router.get("/import-jobs/{job_id}", response_model=VoiceLibraryImportJobResponse)
async def get_voice_library_import_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    service = VoiceLibraryService(db)
    return await service.get_import_job(job_id)


@router.post("/import-jobs/cancel-all", response_model=VoiceLibraryCancelResponse)
async def cancel_all_voice_import_jobs(
    db: AsyncSession = Depends(get_db),
):
    service = VoiceLibraryService(db)
    return await service.cancel_all_import_jobs(canceled_by="user")


@router.post("/import-jobs/{job_id}/cancel", response_model=VoiceLibraryCancelResponse)
async def cancel_voice_import_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    service = VoiceLibraryService(db)
    return await service.cancel_import_job(job_id, canceled_by="user")


@router.post("/import-tasks/{task_id}/cancel", response_model=VoiceLibraryCancelResponse)
async def cancel_voice_import_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = VoiceLibraryService(db)
    return await service.cancel_import_task(task_id, reason="user_delete")


@router.post("/import-tasks/by-item/{item_id}/cancel", response_model=VoiceLibraryCancelResponse)
async def cancel_voice_import_task_by_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = VoiceLibraryService(db)
    return await service.cancel_import_task_by_item(item_id)


@router.post(
    "/import-tasks/{task_id}/retry", response_model=VoiceLibraryImportVideoLinkCreateResponse
)
async def retry_voice_import_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = VoiceLibraryService(db)
    return await service.retry_import_task(task_id)


@router.post("/import-jobs/restart-interrupted", response_model=VoiceLibraryCancelResponse)
async def restart_interrupted_voice_import_tasks(
    db: AsyncSession = Depends(get_db),
):
    service = VoiceLibraryService(db)
    return await service.restart_interrupted_tasks()


@router.get("/import-events/stream")
async def stream_voice_import_events(request: Request):
    async def _safe_stream():
        last_payload = ""
        deadline = time.monotonic() + IMPORT_EVENTS_STREAM_MAX_LIFETIME_SECONDS
        while True:
            if await request.is_disconnected():
                break
            if time.monotonic() >= deadline:
                break
            async with AsyncSessionLocal() as db:
                service = VoiceLibraryService(db)
                jobs_result = await db.execute(
                    select(VoiceLibraryImportJob).where(
                        VoiceLibraryImportJob.status.in_(
                            [VoiceImportJobStatus.PENDING, VoiceImportJobStatus.RUNNING]
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
                            "library": "voice",
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


@router.post("/{item_id}/retry", response_model=VoiceLibraryItemResponse)
async def retry_voice_library_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = VoiceLibraryService(db)
    return await service.retry_item(item_id)


@router.post("", response_model=VoiceLibraryItemResponse, status_code=201)
async def create_voice_library_item(
    data: VoiceLibraryItemCreate,
    db: AsyncSession = Depends(get_db),
):
    service = VoiceLibraryService(db)
    return await service.create(data.model_dump())


@router.patch("/{item_id}", response_model=VoiceLibraryItemResponse)
async def update_voice_library_item(
    item_id: int,
    data: VoiceLibraryItemUpdate,
    db: AsyncSession = Depends(get_db),
):
    service = VoiceLibraryService(db)
    return await service.update(item_id, data.model_dump(exclude_unset=True))


@router.delete("/{item_id}", status_code=204)
async def delete_voice_library_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = VoiceLibraryService(db)
    await service.delete(item_id)


@router.post("/{item_id}/audio/upload", response_model=VoiceLibraryItemResponse)
async def upload_voice_library_audio(
    item_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    service = VoiceLibraryService(db)
    return await service.upload_audio(item_id, file)


@router.delete("/{item_id}/audio", response_model=VoiceLibraryItemResponse)
async def delete_voice_library_audio(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = VoiceLibraryService(db)
    return await service.delete_audio(item_id)
