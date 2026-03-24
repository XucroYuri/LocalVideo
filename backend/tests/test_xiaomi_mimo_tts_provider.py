import base64
from pathlib import Path

import httpx
import pytest

from app.providers.audio.xiaomi_mimo_tts import XiaomiMiMoTTSProvider


class _FakeAsyncClient:
    def __init__(self, *, timeout, trust_env):  # noqa: ANN001
        self.timeout = timeout
        self.trust_env = trust_env

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
        return None

    async def post(self, url: str, *, headers: dict[str, str], json: dict):  # noqa: A002
        assert url == "https://api.xiaomimimo.com/v1/chat/completions"
        assert headers["api-key"] == "test-key"
        assert json["model"] == "mimo-v2-tts"
        assert json["audio"]["voice"] == "default_en"
        assert json["audio"]["format"] == "wav"
        assert json["messages"][1]["role"] == "assistant"
        assert json["messages"][1]["content"] == "<style>孙悟空</style>你好，世界"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "audio": {
                                "id": "audio_123",
                                "data": base64.b64encode(b"fake-wav-bytes").decode("utf-8"),
                                "transcript": "hello",
                            },
                        }
                    }
                ]
            },
        )


@pytest.mark.asyncio
async def test_xiaomi_mimo_tts_provider_decodes_audio_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    provider = XiaomiMiMoTTSProvider(
        api_key="test-key",
        base_url="https://api.xiaomimimo.com",
    )

    result = await provider.synthesize(
        text="你好，世界",
        output_path=tmp_path / "sample.wav",
        voice="default_en",
        audio_xiaomi_mimo_style_preset="sun_wukong",
        audio_format="wav",
    )

    assert result.file_path == tmp_path / "sample.wav"
    assert result.file_path.read_bytes() == b"fake-wav-bytes"
