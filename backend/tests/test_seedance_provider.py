import httpx
import pytest

from app.api.v1.capabilities import (
    SEEDANCE_MODEL_PRESETS as API_SEEDANCE_MODEL_PRESETS,
)
from app.api.v1.capabilities import get_capabilities
from app.config import Settings
from app.providers.video.volcengine_seedance import (
    VolcengineSeedanceVideoProvider,
    get_seedance_duration_control_mode,
    get_seedance_video_presets,
    resolve_seedance_model_id,
)


def test_resolve_seedance_2_0_model_id() -> None:
    resolved_model = resolve_seedance_model_id("seedance-2-0")

    assert resolved_model == "doubao-seedance-2-0"


def test_seedance_2_0_keeps_kwjm_base_url_without_legacy_api_suffix() -> None:
    provider = VolcengineSeedanceVideoProvider(
        api_key="test",
        base_url="https://kwjm.com",
        model="seedance-2-0",
    )

    assert provider.base_url == "https://kwjm.com"


def test_build_payload_uses_duration_for_seedance_2_0() -> None:
    provider = VolcengineSeedanceVideoProvider(
        api_key="test",
        base_url="https://kwjm.com",
        model="seedance-2-0",
    )

    payload = provider._build_payload(prompt="test", duration=8.0)  # noqa: SLF001

    assert get_seedance_duration_control_mode("seedance-2-0") == "duration"
    assert payload["model"] == "doubao-seedance-2-0"
    assert payload.get("duration") == 8
    assert "frames" not in payload
    assert payload.get("ratio") == "adaptive"
    assert payload.get("resolution") == "720p"


def test_seedance_2_0_supports_nine_reference_images_and_last_frame() -> None:
    provider = VolcengineSeedanceVideoProvider(
        api_key="test",
        base_url="https://kwjm.com",
        model="seedance-2-0",
    )

    assert provider._supports_last_frame() is True  # noqa: SLF001
    assert provider._supports_reference_images() is True  # noqa: SLF001
    assert provider._max_reference_images() == 9  # noqa: SLF001


def test_localvideo_defaults_seedance_primary_and_kwjm_base_url() -> None:
    settings = Settings(_env_file=None)

    assert settings.project_name == "LocalVideo Backend"
    assert settings.video_seedance_base_url == "https://kwjm.com"
    assert settings.video_seedance_model == "seedance-2-0"
    assert settings.default_video_provider == "volcengine_seedance"


def test_seedance_2_0_catalog_exposes_adaptive_ratio_and_720p_default() -> None:
    presets = {item["id"]: item for item in get_seedance_video_presets()}

    assert "seedance-2-0" in presets
    assert presets["seedance-2-0"]["default_aspect_ratio"] == "adaptive"
    assert presets["seedance-2-0"]["default_resolution"] == "720p"
    assert "adaptive" in presets["seedance-2-0"]["aspect_ratios"]


def test_capabilities_catalog_exposes_seedance_2_0_family_first() -> None:
    ids = [item.id for item in API_SEEDANCE_MODEL_PRESETS]

    assert ids[:2] == ["seedance-2-0", "seedance-2-0-fast"]


@pytest.mark.asyncio
async def test_capabilities_response_only_exposes_active_video_surface() -> None:
    response = await get_capabilities()
    payload = response.model_dump()

    assert set(payload.keys()) == {
        "seedance_model_presets",
        "seedance_aspect_ratios",
        "seedance_resolutions",
    }


@pytest.mark.asyncio
async def test_seedance_2_0_uses_kwjm_video_generation_endpoints() -> None:
    provider = VolcengineSeedanceVideoProvider(
        api_key="test",
        base_url="https://kwjm.com",
        model="seedance-2-0",
    )
    requests: list[tuple[str, str]] = []

    async def fake_request_with_retry(*, client, method, url, headers=None, json_payload=None):
        del client, headers, json_payload
        requests.append((method, url))
        if method == "POST":
            return {"id": "task_123"}
        return {"status": "succeeded", "data": {"content": {"video_url": "https://example.com/out.mp4"}}}

    provider._request_with_retry = fake_request_with_retry  # type: ignore[method-assign]  # noqa: SLF001

    async with httpx.AsyncClient(trust_env=False) as client:
        task_id = await provider._create_task(client=client, payload={"model": "doubao-seedance-2-0"})  # noqa: SLF001
        await provider._query_task(client=client, task_id=task_id)  # noqa: SLF001

    assert requests == [
        ("POST", "https://kwjm.com/v1/videos/generations"),
        ("GET", "https://kwjm.com/v1/videos/generations/task_123"),
    ]
