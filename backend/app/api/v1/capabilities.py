"""Capabilities API — exposes provider model catalogs to the frontend.

This is the single source of truth for model catalogs that were
previously hardcoded in the frontend.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.providers.video.kling import list_kling_video_presets
from app.providers.video.minimax import list_minimax_video_presets
from app.providers.video.vidu import list_vidu_video_presets
from app.providers.video_capabilities import get_supported_durations_seconds

router = APIRouter()


# ---------------------------------------------------------------------------
# Vertex AI video model catalog
# ---------------------------------------------------------------------------


class VertexVideoModel(BaseModel):
    id: str
    label: str
    supported_durations_seconds: list[int] = []
    supports_reference_image: bool = False
    supports_combined_reference: bool = False
    supports_last_frame: bool = True
    reference_restrictions: list[str] = []


VERTEX_VIDEO_MODELS: list[VertexVideoModel] = [
    VertexVideoModel(
        id="veo-3.1",
        label="veo-3.1",
        supported_durations_seconds=get_supported_durations_seconds("vertex_ai", "veo-3.1", "t2v"),
    ),
    VertexVideoModel(
        id="veo-3.1-fast",
        label="veo-3.1-fast",
        supported_durations_seconds=get_supported_durations_seconds(
            "vertex_ai", "veo-3.1-fast", "t2v"
        ),
    ),
    VertexVideoModel(
        id="veo-3.1-preview",
        label="veo-3.1-preview",
        supported_durations_seconds=get_supported_durations_seconds(
            "vertex_ai", "veo-3.1-preview", "t2v"
        ),
        supports_reference_image=True,
        reference_restrictions=["最多 3 张参考图", "每张图需为单一主体"],
    ),
    VertexVideoModel(
        id="veo-3.1-fast-preview",
        label="veo-3.1-fast-preview",
        supported_durations_seconds=get_supported_durations_seconds(
            "vertex_ai", "veo-3.1-fast-preview", "t2v"
        ),
        supports_reference_image=True,
        reference_restrictions=["最多 3 张参考图", "每张图需为单一主体"],
    ),
]


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


class ProviderVideoModelPreset(BaseModel):
    id: str
    label: str
    description: str = ""
    supported_durations_seconds: list[int] = []
    supported_aspect_ratios: list[str] = []
    supported_resolutions: list[str] = []
    default_aspect_ratio: str = ""
    default_resolution: str = ""
    supports_t2v: bool = True
    supports_i2v: bool = True
    supports_last_frame: bool = True
    supports_reference_image: bool = False
    supports_combined_reference: bool = False
    max_reference_images: int = 0
    reference_restrictions: list[str] = []


KLING_MODEL_PRESETS: list[ProviderVideoModelPreset] = [
    ProviderVideoModelPreset(**item) for item in list_kling_video_presets()
]

VIDU_MODEL_PRESETS: list[ProviderVideoModelPreset] = [
    ProviderVideoModelPreset(**item) for item in list_vidu_video_presets()
]

MINIMAX_MODEL_PRESETS: list[ProviderVideoModelPreset] = [
    ProviderVideoModelPreset(**item) for item in list_minimax_video_presets()
]


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


class CapabilitiesResponse(BaseModel):
    vertex_video_models: list[VertexVideoModel]
    seedance_model_presets: list[SeedanceModelPreset]
    kling_model_presets: list[ProviderVideoModelPreset]
    vidu_model_presets: list[ProviderVideoModelPreset]
    minimax_model_presets: list[ProviderVideoModelPreset]
    seedance_aspect_ratios: list[str]
    seedance_resolutions: list[str]


@router.get("", response_model=CapabilitiesResponse)
async def get_capabilities():
    return CapabilitiesResponse(
        vertex_video_models=VERTEX_VIDEO_MODELS,
        seedance_model_presets=SEEDANCE_MODEL_PRESETS,
        kling_model_presets=KLING_MODEL_PRESETS,
        vidu_model_presets=VIDU_MODEL_PRESETS,
        minimax_model_presets=MINIMAX_MODEL_PRESETS,
        seedance_aspect_ratios=SEEDANCE_ASPECT_RATIOS,
        seedance_resolutions=SEEDANCE_RESOLUTIONS,
    )
