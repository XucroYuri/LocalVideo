from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.media_file import ImageScene
from app.models.stage import StageType
from app.schemas.stage import (
    AudioRegenerateRequest,
    ContentUpdateRequest,
    CreateReferenceForm,
    DescribeFromImageRequest,
    FrameShotUpdateRequest,
    ImageRegenerateRequest,
    ImportReferencesFromLibraryRequest,
    PipelineRunRequest,
    ReferenceUpdateRequest,
    ShotAssetBulkDeleteRequest,
    ShotInsertRequest,
    ShotMoveRequest,
    ShotReorderRequest,
    ShotUpdateRequest,
    StageListResponse,
    StageResponse,
    StageRunRequest,
    VideoDescUpdateRequest,
    VideoRegenerateRequest,
)
from app.services.stage_service import StageService

router = APIRouter(prefix="/projects/{project_id}/stages", tags=["stages"])


@router.get("", response_model=StageListResponse)
async def list_stages(
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.list_stages(project_id)


@router.get("/{stage_type}", response_model=StageResponse)
async def get_stage(
    project_id: int,
    stage_type: StageType,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.get_stage(project_id, stage_type)


@router.post("/{stage_type}", response_model=StageResponse)
async def run_stage(
    project_id: int,
    stage_type: StageType,
    request: StageRunRequest = StageRunRequest(),
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.run_stage(project_id, stage_type, request)


@router.get("/{stage_type}/stream")
async def stream_stage(
    project_id: int,
    stage_type: StageType,
    force: bool = Query(False),
    input_data: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.stream_stage(project_id, stage_type, force, input_data)


@router.post("/pipeline/run")
async def run_pipeline(
    project_id: int,
    request: PipelineRunRequest = PipelineRunRequest(),
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.run_pipeline(project_id, request)


@router.post("/tasks/cancel")
async def cancel_tasks(
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.cancel_project_tasks(project_id)


@router.patch("/content/data")
async def update_content_data(
    project_id: int,
    request: ContentUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.update_content_data(
        project_id=project_id,
        title=request.title,
        content=request.content,
        script_mode=request.script_mode,
        roles=request.roles,
        dialogue_lines=request.dialogue_lines,
    )


@router.post("/content/dialogue/import")
async def import_content_dialogue_data(
    project_id: int,
    file: UploadFile = File(...),
    script_mode: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.import_content_dialogue_data(
        project_id=project_id,
        file=file,
        script_mode=script_mode,
    )


@router.patch("/reference/items/{reference_id}")
async def update_reference(
    project_id: int,
    reference_id: str,
    request: ReferenceUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.update_reference(project_id, reference_id, request)


@router.delete("/reference/items/{reference_id}")
async def delete_reference(
    project_id: int,
    reference_id: str,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.delete_reference(project_id, reference_id)


@router.post("/reference/items")
async def create_reference(
    project_id: int,
    form: CreateReferenceForm = Depends(),
    file: UploadFile | None = File(default=None),
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.create_reference(project_id, form, file)


@router.post("/reference/items/{reference_id}/describe-from-image")
async def describe_reference_from_image_api(
    project_id: int,
    reference_id: str,
    request: DescribeFromImageRequest = DescribeFromImageRequest(),
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.describe_reference_from_image(
        project_id,
        reference_id,
        target_language=request.target_language,
        prompt_complexity=request.prompt_complexity,
        llm_provider=request.llm_provider,
        llm_model=request.llm_model,
    )


@router.post("/reference/import-from-library")
async def import_references_from_library(
    project_id: int,
    request: ImportReferencesFromLibraryRequest,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.import_references_from_library(
        project_id=project_id,
        library_reference_ids=request.library_reference_ids,
        start_reference_index=request.start_reference_index,
        import_setting=request.import_setting,
        import_appearance_description=request.import_appearance_description,
        import_image=request.import_image,
        import_voice=request.import_voice,
    )


@router.post("/frame/frames/reuse-first")
async def reuse_first_frame_to_other_shots(
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.reuse_first_frame_to_other_shots(project_id)


@router.patch("/frame/shots/{shot_index}")
async def update_frame_description(
    project_id: int,
    shot_index: int,
    request: FrameShotUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.update_frame_description(
        project_id,
        shot_index,
        request.description,
        request.first_frame_reference_slots,
    )


@router.post("/image/{scene}/items/{item_id}/regenerate")
async def regenerate_image_item(
    project_id: int,
    scene: ImageScene,
    item_id: str,
    request: ImageRegenerateRequest = ImageRegenerateRequest(),
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.regenerate_image_asset(project_id, scene, item_id, request)


@router.post("/image/{scene}/items/{item_id}/upload")
async def upload_image_item(
    project_id: int,
    scene: ImageScene,
    item_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.upload_image_asset(project_id, scene, item_id, file)


@router.delete("/image/{scene}/items/{item_id}/asset")
async def delete_image_item(
    project_id: int,
    scene: ImageScene,
    item_id: str,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.delete_image_asset(project_id, scene, item_id)


@router.post("/image/frame/assets/bulk-delete")
async def bulk_delete_frame_images(
    project_id: int,
    request: ShotAssetBulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.delete_frame_images(project_id, request.shot_indices)


@router.delete("/video/shots/{shot_index}")
async def delete_video(
    project_id: int,
    shot_index: int,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.delete_video(project_id, shot_index)


@router.post("/video/shots/bulk-delete")
async def bulk_delete_videos(
    project_id: int,
    request: ShotAssetBulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.delete_videos(project_id, request.shot_indices)


@router.delete("/audio/shots/{shot_index}")
async def delete_audio(
    project_id: int,
    shot_index: int,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.delete_audio(project_id, shot_index)


@router.post("/audio/shots/bulk-delete")
async def bulk_delete_audios(
    project_id: int,
    request: ShotAssetBulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.delete_audios(project_id, request.shot_indices)


@router.delete("/compose/video")
async def delete_compose_video(
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.delete_compose_video(project_id)


@router.post("/shots/clear-all")
async def clear_all_shot_content(
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.clear_all_shot_content(project_id)


@router.get("/shots")
async def list_shots(
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.list_shots(project_id)


@router.post("/shots/insert")
async def insert_shots(
    project_id: int,
    request: ShotInsertRequest,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.insert_shots(
        project_id,
        anchor_index=request.anchor_index,
        direction=request.direction,
        count=request.count,
    )


@router.delete("/shots/{shot_id}")
async def delete_shot(
    project_id: int,
    shot_id: str,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.delete_shot(project_id, shot_id)


@router.patch("/shots/{shot_id}")
async def update_shot(
    project_id: int,
    shot_id: str,
    request: ShotUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.update_shot(
        project_id,
        shot_id,
        voice_content=request.voice_content,
        speaker_id=request.speaker_id,
        speaker_name=request.speaker_name,
    )


@router.post("/shots/reorder")
async def reorder_shots(
    project_id: int,
    request: ShotReorderRequest,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.reorder_shots(
        project_id,
        ordered_shot_ids=request.ordered_shot_ids,
    )


@router.post("/shots/move")
async def move_shots(
    project_id: int,
    request: ShotMoveRequest,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.move_shot(
        project_id,
        shot_id=request.shot_id,
        direction=request.direction,
        step=request.step,
    )


@router.post("/shots/unlock-content")
async def clear_shots_unlock_content(
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.clear_shots_and_unlock_content(project_id)


@router.post("/video/shots/{shot_index}/regenerate")
async def regenerate_video(
    project_id: int,
    shot_index: int,
    request: VideoRegenerateRequest = VideoRegenerateRequest(),
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.regenerate_video(project_id, shot_index, request)


@router.patch("/video/shots/{shot_index}")
async def update_video_description(
    project_id: int,
    shot_index: int,
    request: VideoDescUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.update_video_description(
        project_id,
        shot_index,
        request.description,
        request.video_reference_slots,
    )


@router.post("/audio/shots/{shot_index}/regenerate")
async def regenerate_audio(
    project_id: int,
    shot_index: int,
    request: AudioRegenerateRequest = AudioRegenerateRequest(),
    db: AsyncSession = Depends(get_db),
):
    service = StageService(db)
    return await service.regenerate_audio(project_id, shot_index, request)
