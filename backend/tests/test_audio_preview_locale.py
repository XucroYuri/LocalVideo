from app.api.v1.settings._common import (
    normalize_audio_preview_locale,
    resolve_audio_preview_text_for_locale,
)
from app.api.v1.settings.audio import _resolve_audio_preview_text


def test_normalize_audio_preview_locale_supports_current_catalog_languages() -> None:
    assert normalize_audio_preview_locale("zh-CN-liaoning") == "zh-CN"
    assert normalize_audio_preview_locale("zh-TW") == "zh-TW"
    assert normalize_audio_preview_locale("zh-HK") == "zh-HK"
    assert normalize_audio_preview_locale("en-GB") == "en-GB"
    assert normalize_audio_preview_locale("en-US") == "en-US"
    assert normalize_audio_preview_locale("ja-JP") == "ja-JP"
    assert normalize_audio_preview_locale("es-ES") == "es-ES"
    assert normalize_audio_preview_locale("es-MX") == "es-MX"
    assert normalize_audio_preview_locale("id-ID") == "id-ID"
    assert normalize_audio_preview_locale("zh-CN/en-US/es-ES/ja-JP") == "zh-CN"


def test_resolve_audio_preview_text_uses_provider_locale_for_minimax_and_xiaomi() -> None:
    hong_kong_preview = resolve_audio_preview_text_for_locale("zh-HK")
    english_preview = resolve_audio_preview_text_for_locale("en-US")

    assert (
        _resolve_audio_preview_text(
            "minimax_tts",
            {"audio_minimax_voice_id": "Cantonese_GentleLady"},
        )
        == hong_kong_preview
    )
    assert (
        _resolve_audio_preview_text(
            "xiaomi_mimo_tts",
            {"audio_xiaomi_mimo_voice": "default_en"},
        )
        == english_preview
    )
    assert (
        _resolve_audio_preview_text(
            "xiaomi_mimo_tts",
            {"audio_xiaomi_mimo_style_preset": "yue_yu_zhu_bo"},
        )
        == hong_kong_preview
    )
