import pytest

from app.api.v1.settings import general as general_module
from app.schemas.settings import SettingsResponse, SettingsUpdate

LEGACY_VIDEO_PROVIDER_FIELDS = {
    "video_vertex_ai_project",
    "video_vertex_ai_location",
    "video_vertex_ai_model",
    "video_vertex_ai_aspect_ratio",
    "video_vertex_ai_resolution",
    "video_vertex_ai_negative_prompt",
    "video_vertex_ai_enabled_models",
    "video_kling_model",
    "video_kling_aspect_ratio",
    "video_kling_mode",
    "video_vidu_model",
    "video_vidu_aspect_ratio",
    "video_vidu_resolution",
    "video_vidu_enabled_models",
    "video_minimax_model",
    "video_minimax_aspect_ratio",
    "video_minimax_resolution",
    "video_minimax_enabled_models",
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
    monkeypatch.setattr(general_module, "_is_kling_configured", lambda *args, **kwargs: True)
    monkeypatch.setattr(general_module, "_is_vidu_configured", lambda *args, **kwargs: True)
    monkeypatch.setattr(general_module, "_is_minimax_configured", lambda *args, **kwargs: True)
    monkeypatch.setattr(general_module, "_is_xiaomi_mimo_configured", lambda *args, **kwargs: False)

    response = await general_module.get_available_providers()

    assert response.video == ["volcengine_seedance", "wan2gp"]


def test_settings_contract_excludes_legacy_video_provider_fields() -> None:
    assert LEGACY_VIDEO_PROVIDER_FIELDS.isdisjoint(SettingsResponse.model_fields)
    assert LEGACY_VIDEO_PROVIDER_FIELDS.isdisjoint(SettingsUpdate.model_fields)


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
    assert LEGACY_VIDEO_PROVIDER_FIELDS.isdisjoint(dumped)
