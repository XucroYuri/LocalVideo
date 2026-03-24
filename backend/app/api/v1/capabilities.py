"""Capabilities API for active frontend-facing provider catalogs."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.providers.video_capabilities import get_supported_durations_seconds

router = APIRouter()


# ---------------------------------------------------------------------------
# Seedance model catalog
# ---------------------------------------------------------------------------


class SeedanceModelPreset(BaseModel):
    id: str
    label: str
    description: str
    supported_durations_seconds: list[int]
    supports_t2v: bool
    supports_i2v: bool
    supports_last_frame: bool
    supports_reference_image: bool
    reference_restrictions: list[str] = []


SEEDANCE_MODEL_PRESETS: list[SeedanceModelPreset] = [
    SeedanceModelPreset(
        id="seedance-2-0",
        label="Seedance 2.0",
        description="支持文生视频、图生视频与多模态参考视频",
        supported_durations_seconds=get_supported_durations_seconds(
            "volcengine_seedance", "seedance-2-0", "t2v"
        ),
        supports_t2v=True,
        supports_i2v=True,
        supports_last_frame=True,
        supports_reference_image=True,
        reference_restrictions=["参考图模式支持 1~9 张图片"],
    ),
    SeedanceModelPreset(
        id="seedance-2-0-fast",
        label="Seedance 2.0 fast",
        description="更快的 Seedance 2.0，支持文生视频、图生视频与多模态参考视频",
        supported_durations_seconds=get_supported_durations_seconds(
            "volcengine_seedance", "seedance-2-0-fast", "t2v"
        ),
        supports_t2v=True,
        supports_i2v=True,
        supports_last_frame=True,
        supports_reference_image=True,
        reference_restrictions=["参考图模式支持 1~9 张图片"],
    ),
]

SEEDANCE_ASPECT_RATIOS: list[str] = ["adaptive", "16:9", "4:3", "1:1", "3:4", "9:16", "21:9"]
SEEDANCE_RESOLUTIONS: list[str] = ["480p", "720p"]


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


class CapabilitiesResponse(BaseModel):
    seedance_model_presets: list[SeedanceModelPreset]
    seedance_aspect_ratios: list[str]
    seedance_resolutions: list[str]


@router.get("", response_model=CapabilitiesResponse)
async def get_capabilities():
    return CapabilitiesResponse(
        seedance_model_presets=SEEDANCE_MODEL_PRESETS,
        seedance_aspect_ratios=SEEDANCE_ASPECT_RATIOS,
        seedance_resolutions=SEEDANCE_RESOLUTIONS,
    )
