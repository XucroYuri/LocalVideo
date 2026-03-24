from fastapi import APIRouter

from .projects import router as projects_router
from .stages import router as stages_router

api_router = APIRouter()
api_router.include_router(projects_router)
api_router.include_router(stages_router)
