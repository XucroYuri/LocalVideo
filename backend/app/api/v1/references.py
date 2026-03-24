import asyncio
import json
import time

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.session import AsyncSessionLocal
from app.models.reference_library import ReferenceImportJobStatus, ReferenceLibraryImportJob
from app.schemas.reference_library import (
    ReferenceLibraryCancelResponse,
    ReferenceLibraryCreate,
    ReferenceLibraryImportImagesCreateResponse,
    ReferenceLibraryImportJobResponse,
    ReferenceLibraryListResponse,
    ReferenceLibraryResponse,
    ReferenceLibraryUpdate,
)
from app.schemas.stage import DescribeFromImageRequest
from app.services.reference_library_service import ReferenceLibraryService

router = APIRouter(prefix="/references", tags=["references"])
IMPORT_EVENTS_STREAM_MAX_LIFETIME_SECONDS = 25.0


@router.get("", response_model=ReferenceLibraryListResponse)
async def list_reference_library_items(
    q: str | None = Query(default=None),
    enabled_only: bool = Query(default=False),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    service = ReferenceLibraryService(db)
    items, total = await service.list(
        q=q,
        enabled_only=enabled_only,
        page=page,
        page_size=page_size,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("", response_model=ReferenceLibraryResponse, status_code=201)
async def create_reference_library_item(
    name: str = Form(...),
    is_enabled: bool = Form(default=True),
    can_speak: bool = Form(default=False),
    setting: str = Form(default=""),
    appearance_description: str = Form(default=""),
    voice_audio_provider: str = Form(default=""),
    voice_name: str = Form(default=""),
    voice_speed: float | None = Form(default=None),
    voice_wan2gp_preset: str = Form(default=""),
    voice_wan2gp_alt_prompt: str = Form(default=""),
    voice_wan2gp_audio_guide: str = Form(default=""),
    voice_wan2gp_temperature: float | None = Form(default=None),
    voice_wan2gp_top_k: int | None = Form(default=None),
    voice_wan2gp_seed: int | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    db: AsyncSession = Depends(get_db),
):
    service = ReferenceLibraryService(db)
    item = await service.create(
        ReferenceLibraryCreate(
            name=name,
            is_enabled=is_enabled,
            can_speak=can_speak,
            setting=setting,
            appearance_description=appearance_description,
            voice_audio_provider=voice_audio_provider,
            voice_name=voice_name,
            voice_speed=voice_speed,
            voice_wan2gp_preset=voice_wan2gp_preset,
            voice_wan2gp_alt_prompt=voice_wan2gp_alt_prompt,
            voice_wan2gp_audio_guide=voice_wan2gp_audio_guide,
            voice_wan2gp_temperature=voice_wan2gp_temperature,
            voice_wan2gp_top_k=voice_wan2gp_top_k,
            voice_wan2gp_seed=voice_wan2gp_seed,
        ),
        file=file,
    )
    return item


@router.post(
    "/import/images", response_model=ReferenceLibraryImportImagesCreateResponse, status_code=202
)
async def import_reference_library_by_images(
    files: list[UploadFile] = File(...),
    rows_json: str = Form(default="[]"),
    db: AsyncSession = Depends(get_db),
):
    service = ReferenceLibraryService(db)
    return await service.create_image_import_job(files=files, rows_json=rows_json)


@router.get("/import-jobs/{job_id}", response_model=ReferenceLibraryImportJobResponse)
async def get_reference_library_import_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    service = ReferenceLibraryService(db)
    return await service.get_import_job(job_id)


@router.post("/import-jobs/cancel-all", response_model=ReferenceLibraryCancelResponse)
async def cancel_all_reference_import_jobs(
    db: AsyncSession = Depends(get_db),
):
    service = ReferenceLibraryService(db)
    return await service.cancel_all_import_jobs(canceled_by="user")


@router.post("/import-jobs/{job_id}/cancel", response_model=ReferenceLibraryCancelResponse)
async def cancel_reference_import_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    service = ReferenceLibraryService(db)
    return await service.cancel_import_job(job_id, canceled_by="user")


@router.post("/import-tasks/{task_id}/cancel", response_model=ReferenceLibraryCancelResponse)
async def cancel_reference_import_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = ReferenceLibraryService(db)
    return await service.cancel_import_task(task_id, reason="user_delete")


@router.post(
    "/import-tasks/by-item/{item_id}/cancel", response_model=ReferenceLibraryCancelResponse
)
async def cancel_reference_import_task_by_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = ReferenceLibraryService(db)
    return await service.cancel_import_task_by_item(item_id)


@router.post(
    "/import-tasks/{task_id}/retry", response_model=ReferenceLibraryImportImagesCreateResponse
)
async def retry_reference_import_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = ReferenceLibraryService(db)
    return await service.retry_import_task(task_id)


@router.post("/import-jobs/restart-interrupted", response_model=ReferenceLibraryCancelResponse)
async def restart_interrupted_reference_import_tasks(
    db: AsyncSession = Depends(get_db),
):
    service = ReferenceLibraryService(db)
    return await service.restart_interrupted_tasks()


@router.get("/import-events/stream")
async def stream_reference_import_events(request: Request):
    async def _safe_stream():
        last_payload = ""
        deadline = time.monotonic() + IMPORT_EVENTS_STREAM_MAX_LIFETIME_SECONDS
        while True:
            if await request.is_disconnected():
                break
            if time.monotonic() >= deadline:
                break
            async with AsyncSessionLocal() as db:
                service = ReferenceLibraryService(db)
                jobs_result = await db.execute(
                    select(ReferenceLibraryImportJob).where(
                        ReferenceLibraryImportJob.status.in_(
                            [ReferenceImportJobStatus.PENDING, ReferenceImportJobStatus.RUNNING]
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
                            "library": "reference",
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


@router.post("/{item_id}/retry", response_model=ReferenceLibraryResponse)
async def retry_reference_library_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = ReferenceLibraryService(db)
    return await service.retry_item(item_id)


@router.post("/{item_id}/describe-from-image")
async def describe_reference_library_item_from_image(
    item_id: int,
    request: DescribeFromImageRequest = DescribeFromImageRequest(),
    db: AsyncSession = Depends(get_db),
):
    service = ReferenceLibraryService(db)
    return await service.describe_from_image(
        item_id=item_id,
        target_language=request.target_language,
        prompt_complexity=request.prompt_complexity,
        llm_provider=request.llm_provider,
        llm_model=request.llm_model,
    )


@router.post("/describe-from-upload")
async def describe_reference_library_item_from_upload(
    file: UploadFile = File(...),
    target_language: str | None = Form(default=None),
    prompt_complexity: str | None = Form(default=None),
    llm_provider: str | None = Form(default=None),
    llm_model: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    service = ReferenceLibraryService(db)
    return await service.describe_from_uploaded_image(
        file=file,
        target_language=target_language,
        prompt_complexity=prompt_complexity,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )


@router.patch("/{item_id}", response_model=ReferenceLibraryResponse)
async def update_reference_library_item(
    item_id: int,
    data: ReferenceLibraryUpdate,
    db: AsyncSession = Depends(get_db),
):
    service = ReferenceLibraryService(db)
    item = await service.update(item_id, data)
    return item


@router.delete("/{item_id}", status_code=204)
async def delete_reference_library_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = ReferenceLibraryService(db)
    await service.delete(item_id)


@router.post("/{item_id}/image/upload", response_model=ReferenceLibraryResponse)
async def upload_reference_library_image(
    item_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    service = ReferenceLibraryService(db)
    item = await service.upload_image(item_id, file)
    return item


@router.delete("/{item_id}/image", response_model=ReferenceLibraryResponse)
async def delete_reference_library_image(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = ReferenceLibraryService(db)
    item = await service.delete_image(item_id)
    return item
