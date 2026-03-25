from pathlib import Path

import httpx
import pytest

from app.providers.audio.minimax_tts import MiniMaxTTSProvider
from app.providers.image.minimax import MiniMaxImageProvider


class _FakeMiniMaxClient:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.calls: list[tuple[str, str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return None

    async def post(self, url: str, *, headers: dict[str, str], json: dict):  # noqa: A002
        self.calls.append(("POST", url, {"headers": headers, "json": json}))
        request = httpx.Request("POST", url, headers=headers, json=json)
        if url.endswith("/image_generation"):
            assert json["model"] == "image-01"
            assert json["prompt"] == "一只小猫"
            return httpx.Response(
                200,
                request=request,
                json={
                    "base_resp": {"status_code": 0, "status_msg": "success"},
                    "data": {"image_urls": ["https://example.com/image.png"]},
                },
            )
        if url.endswith("/t2a_v2"):
            assert json["model"] == "speech-2.8-turbo"
            assert json["stream"] is False
            assert json["voice_setting"]["voice_id"] == "Chinese (Mandarin)_Reliable_Executive"
            assert json["voice_setting"]["vol"] == 1
            assert json["voice_setting"]["pitch"] == 0
            assert json["audio_setting"]["sample_rate"] == 32000
            assert json["audio_setting"]["channel"] == 1
            assert json["output_format"] == "hex"
            return httpx.Response(
                200,
                request=request,
                json={
                    "base_resp": {"status_code": 0, "status_msg": "success"},
                    "data": {"audio": b"fake-audio-bytes".hex(), "status": 2},
                },
            )
        if url.endswith("/get_voice"):
            return httpx.Response(200, request=request, json={"system_voice": []})
        raise AssertionError(f"Unexpected POST {url}")

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        follow_redirects: bool = False,
    ):
        self.calls.append(
            (
                "GET",
                url,
                {
                    "headers": headers or {},
                    "params": params or {},
                    "follow_redirects": follow_redirects,
                },
            )
        )
        request = httpx.Request("GET", url, headers=headers, params=params)
        if url == "https://example.com/image.png":
            return httpx.Response(200, request=request, content=b"fake-image-bytes")
        raise AssertionError(f"Unexpected GET {url}")


class _RetryMiniMaxClient:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.trust_env = kwargs.get("trust_env", True)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return None

    async def post(self, url: str, *, headers: dict[str, str], json: dict):  # noqa: A002
        if self.trust_env:
            raise httpx.ConnectTimeout("proxy connect timeout")
        request = httpx.Request("POST", url, headers=headers, json=json)
        return httpx.Response(
            200,
            request=request,
            json={
                "base_resp": {"status_code": 0, "status_msg": "success"},
                "data": {"audio": b"retry-audio-bytes".hex(), "status": 2},
            },
        )

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        follow_redirects: bool = False,
    ):
        raise AssertionError(f"Unexpected GET {url}")


@pytest.mark.asyncio
async def test_minimax_image_provider_downloads_first_image(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", _FakeMiniMaxClient)
    monkeypatch.setattr(
        MiniMaxImageProvider,
        "_resolve_dimensions",
        staticmethod(lambda _path: (1024, 1024)),
    )
    provider = MiniMaxImageProvider(
        api_key="test-key",
        base_url="https://api.minimaxi.com",
        model="image-01",
    )

    result = await provider.generate(
        prompt="一只小猫",
        output_path=tmp_path / "sample.png",
    )

    assert result.file_path == tmp_path / "sample.png"
    assert result.file_path.read_bytes() == b"fake-image-bytes"
    assert result.width == 1024
    assert result.height == 1024


@pytest.mark.asyncio
async def test_minimax_tts_provider_generates_audio_via_sync_http(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", _FakeMiniMaxClient)
    monkeypatch.setattr(
        "app.providers.audio.minimax_tts._resolve_duration",
        lambda _path: 3.5,
    )
    provider = MiniMaxTTSProvider(
        api_key="test-key",
        base_url="https://api.minimaxi.com",
        model="speech-2.8-turbo",
    )

    result = await provider.synthesize(
        text="你好，欢迎使用影流。",
        output_path=tmp_path / "sample.mp3",
        voice="Chinese (Mandarin)_Reliable_Executive",
    )

    assert result.file_path == tmp_path / "sample.mp3"
    assert result.file_path.read_bytes() == b"fake-audio-bytes"
    assert result.duration == 3.5


@pytest.mark.asyncio
async def test_minimax_tts_provider_retries_without_env_proxy_on_connect_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", _RetryMiniMaxClient)
    monkeypatch.setattr(
        "app.providers.audio.minimax_tts._resolve_duration",
        lambda _path: 1.2,
    )
    provider = MiniMaxTTSProvider(
        api_key="test-key",
        base_url="https://api.minimaxi.com",
        model="speech-2.8-turbo",
    )

    result = await provider.synthesize(
        text="你好，欢迎使用影流。",
        output_path=tmp_path / "retry.mp3",
        voice="Chinese (Mandarin)_Reliable_Executive",
    )

    assert result.file_path == tmp_path / "retry.mp3"
    assert result.file_path.read_bytes() == b"retry-audio-bytes"
    assert result.duration == 1.2
