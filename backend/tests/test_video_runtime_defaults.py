from app.config import Settings
from app.stages._video_config import VideoConfigResolver


def test_localvideo_settings_default_to_seedance_primary_and_wan2gp_fallback_ready() -> None:
    settings = Settings(_env_file=None)

    assert settings.project_name == "LocalVideo Backend"
    assert settings.video_seedance_base_url == "https://kwjm.com"
    assert settings.video_seedance_model == "seedance-2-0"
    assert settings.default_video_provider == "volcengine_seedance"
    assert settings.video_wan2gp_t2v_preset == "t2v_1.3B"
    assert settings.video_wan2gp_i2v_preset == "i2v_720p"


def test_video_config_resolver_maps_legacy_video_provider_back_to_seedance() -> None:
    resolved = VideoConfigResolver.resolve(
        {"video_provider": "vertex_ai"},
        {},
    )

    assert resolved.video_provider_name == "volcengine_seedance"
