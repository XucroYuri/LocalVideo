import pytest

from app.api.v1.settings import general as general_module
from app.providers import video_registry
from app.schemas.settings import SettingsResponse, SettingsUpdate

ACTIVE_VIDEO_RESPONSE_FIELDS = {
    "video_seedance_api_key_set",
    "video_seedance_api_key",
    "video_seedance_base_url",
    "video_seedance_model",
    "video_seedance_aspect_ratio",
    "video_seedance_resolution",
    "video_seedance_watermark",
    "video_seedance_enabled_models",
    "video_wan2gp_t2v_preset",
    "video_wan2gp_i2v_preset",
    "video_wan2gp_resolution",
    "video_wan2gp_negative_prompt",
    "video_wan2gp_enabled_models",
}

ACTIVE_VIDEO_UPDATE_FIELDS = {
    "video_seedance_api_key",
    "video_seedance_base_url",
    "video_seedance_model",
    "video_seedance_aspect_ratio",
    "video_seedance_resolution",
    "video_seedance_watermark",
    "video_seedance_enabled_models",
    "video_wan2gp_t2v_preset",
    "video_wan2gp_i2v_preset",
    "video_wan2gp_resolution",
    "video_wan2gp_negative_prompt",
    "video_wan2gp_enabled_models",
}


@pytest.mark.asyncio
async def test_settings_video_provider_surface_only_exposes_seedance_and_wan2gp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        general_module,
        "_resolve_shared_volcengine_ark_credentials",
        lambda image_providers, llm_providers: ("seedance-key", [], []),
    )
    monkeypatch.setattr(
        general_module,
        "_resolve_shared_xiaomi_mimo_api_key",
        lambda llm_providers: ("", llm_providers),
    )
    monkeypatch.setattr(
        general_module,
        "_resolve_shared_minimax_api_key",
        lambda llm_providers: ("", llm_providers),
    )
    monkeypatch.setattr(general_module, "_is_wan2gp_available", lambda: True)
    monkeypatch.setattr(general_module, "_is_volcengine_tts_configured", lambda: False)
    monkeypatch.setattr(general_module, "_is_xiaomi_mimo_configured", lambda *args, **kwargs: False)

    response = await general_module.get_available_providers()

    assert response.video == ["volcengine_seedance", "wan2gp"]


def test_settings_contract_exposes_only_active_video_provider_fields() -> None:
    response_fields = {name for name in SettingsResponse.model_fields if name.startswith("video_")}
    update_fields = {name for name in SettingsUpdate.model_fields if name.startswith("video_")}

    assert response_fields == ACTIVE_VIDEO_RESPONSE_FIELDS
    assert update_fields == ACTIVE_VIDEO_UPDATE_FIELDS


def test_video_registry_surface_only_keeps_seedance_and_wan2gp() -> None:
    assert set(video_registry.list_providers()) == {"volcengine_seedance", "wan2gp"}


def test_settings_general_output_keeps_only_seedance_and_wan2gp_video_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        general_module,
        "_resolve_shared_volcengine_ark_credentials",
        lambda image_providers, llm_providers: ("seedance-key", [], []),
    )
    monkeypatch.setattr(
        general_module,
        "_resolve_shared_xiaomi_mimo_api_key",
        lambda llm_providers: ("", llm_providers),
    )
    monkeypatch.setattr(
        general_module,
        "_resolve_shared_minimax_api_key",
        lambda llm_providers: ("", llm_providers),
    )
    monkeypatch.setattr(general_module, "_is_wan2gp_available", lambda: True)
    monkeypatch.setattr(general_module, "_is_volcengine_tts_configured", lambda: False)
    monkeypatch.setattr(general_module.settings, "default_video_provider", "kling")

    response = general_module._build_settings_response()
    dumped = response.model_dump()

    assert response.default_video_provider == "volcengine_seedance"
    assert response.video_seedance_api_key_set is True
    assert response.video_seedance_api_key == "seedance-key"
    assert response.video_seedance_base_url == "https://kwjm.com/api/v3"
    assert response.video_wan2gp_t2v_preset == "t2v_1.3B"
    assert response.video_wan2gp_i2v_preset == "i2v_720p"
    assert {name for name in dumped if name.startswith("video_")} == ACTIVE_VIDEO_RESPONSE_FIELDS
