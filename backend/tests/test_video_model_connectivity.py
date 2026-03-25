import pytest

from app.api.v1.settings import video as settings_video_module
from app.api.v1.settings.video import (
    SeedanceConnectivityTestResponse,
    VideoModelConnectivityTestRequest,
)


@pytest.mark.asyncio
async def test_video_model_connectivity_accepts_seedance_and_wan2gp_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_model = "seedance-2-0"
    async def _fake_seedance_connectivity_test(
        *,
        api_key: str,
        base_url: str,
        model: str,
    ) -> SeedanceConnectivityTestResponse:
        del api_key, base_url

        return SeedanceConnectivityTestResponse(
            success=True,
            model=model,
            latency_ms=15,
            message="seedance ok",
        )

    monkeypatch.setattr(
        settings_video_module,
        "_run_seedance_connectivity_test",
        _fake_seedance_connectivity_test,
    )
    monkeypatch.setattr(
        settings_video_module, "resolve_seedance_model_id", lambda model: f"resolved-{model}"
    )

    result = await settings_video_module.test_video_model_connectivity(
        VideoModelConnectivityTestRequest(
            provider_id="volcengine_seedance",
            model=input_model,
            api_key="seedance-token",
            base_url="https://kwjm.com",
        )
    )

    assert result.success
    assert result.model == f"resolved-{input_model}"


@pytest.mark.asyncio
async def test_video_model_connectivity_checks_wan2gp_runtime_model_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    wan2gp_root = tmp_path / "Wan2GP"
    wan2gp_root.mkdir()
    (wan2gp_root / "wgp.py").write_text("")
    monkeypatch.setattr(
        settings_video_module,
        "get_wan2gp_video_presets",
        lambda _path: {
            "t2v_presets": [{"id": "t2v_test", "model_type": "t2v_1"}],
            "i2v_presets": [],
        },
    )
    monkeypatch.setattr(
        settings_video_module,
        "get_wan2gp_t2v_preset",
        lambda model: {"model_type": "t2v_1"} if model == "t2v_test" else {},
    )
    monkeypatch.setattr(settings_video_module, "is_model_cached", lambda *_args: True)

    result = await settings_video_module.test_video_model_connectivity(
        VideoModelConnectivityTestRequest(
            provider_id="wan2gp",
            model="t2v_test",
            wan2gp_path=str(wan2gp_root),
        )
    )

    assert result.success
    assert result.model == "t2v_test"
    assert "Wan2GP 运行时可用（t2v）。" in (result.message or "")


@pytest.mark.asyncio
async def test_video_model_connectivity_rejects_unsupported_provider() -> None:
    result = await settings_video_module.test_video_model_connectivity(
        VideoModelConnectivityTestRequest(
            provider_id="unsupported_provider",
            model="test-model",
        )
    )

    assert result.success is False
    assert result.error == "Unsupported video provider: unsupported_provider"
