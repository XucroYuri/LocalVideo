from pathlib import Path

import pytest

from app.stages import _audio_split as audio_split_module


class _FakeResult:
    def __init__(self) -> None:
        self.utterances = [
            {
                "text": "这是 第一段",
                "start": 0.0,
                "end": 1.2,
                "words": [
                    {"word": "这是", "start": 0.0, "end": 0.5, "utterance_index": 0},
                    {"word": "第一段", "start": 0.5, "end": 1.2, "utterance_index": 0},
                ],
            }
        ]
        self.words = [
            {"word": "这是", "start": 0.0, "end": 0.5, "utterance_index": 0},
            {"word": "第一段", "start": 0.5, "end": 1.2, "utterance_index": 0},
        ]


@pytest.mark.asyncio
async def test_transcribe_audio_words_faster_whisper_normalizes_words(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "demo.wav"
    audio_path.write_bytes(b"fake")

    async def _fake_probe_audio_duration(_audio_path: Path) -> float:
        return 1.2

    async def _fake_transcribe_with_faster_whisper(*args, **kwargs):
        del args, kwargs
        return _FakeResult()

    monkeypatch.setattr(audio_split_module, "probe_audio_duration", _fake_probe_audio_duration)
    monkeypatch.setattr(
        audio_split_module,
        "transcribe_with_faster_whisper",
        _fake_transcribe_with_faster_whisper,
    )

    words = await audio_split_module._transcribe_audio_words_faster_whisper(audio_path)

    assert len(words) == 2
    assert words[0]["word"] == "这是"
    assert words[0]["normalized"] == "这是"
    assert words[1]["word"] == "第一段"
    assert words[1]["normalized"] == "第0段"
