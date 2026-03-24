from fastapi import APIRouter

from .audio import router as audio_router
from .external import router as external_router
from .general import router as general_router
from .image import router as image_router
from .llm import router as llm_router
from .video import router as video_router

router = APIRouter(prefix="/settings", tags=["settings"])
router.include_router(general_router)
router.include_router(llm_router)
router.include_router(image_router)
router.include_router(video_router)
router.include_router(audio_router)
router.include_router(external_router)
