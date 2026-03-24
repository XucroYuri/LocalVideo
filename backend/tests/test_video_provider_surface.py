import pytest

from app.api.v1.settings import general as general_module


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
    monkeypatch.setattr(general_module.settings, "video_vertex_ai_project", "legacy-project")

    response = await general_module.get_available_providers()

    assert response.video == ["volcengine_seedance", "wan2gp"]
