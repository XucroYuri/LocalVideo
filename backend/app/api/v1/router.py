from fastapi import APIRouter

from app.core.stage_manifest import build_stage_manifest

from .capabilities import router as capabilities_router
from .projects import router as projects_router
from .references import router as references_router
from .settings import router as settings_router
from .sources import router as sources_router
from .stages import router as stages_router
from .text_library import router as text_library_router
from .voice_library import router as voice_library_router

router = APIRouter()

router.include_router(projects_router)
router.include_router(stages_router)
router.include_router(settings_router)
router.include_router(sources_router)
router.include_router(references_router)
router.include_router(voice_library_router)
router.include_router(text_library_router)
router.include_router(capabilities_router, prefix="/capabilities", tags=["capabilities"])


@router.get("/status")
async def api_status():
    return {"message": "API v1 is running"}


@router.get("/stages/manifest", tags=["stages"])
async def get_stage_manifest():
    """Return stage metadata for frontend consumption."""
    return {"stages": build_stage_manifest()}
