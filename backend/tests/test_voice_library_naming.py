import json
import math
import wave
from pathlib import Path

import pytest

from app.config import settings
from app.models.voice_library import VoiceItemFieldStatus, VoiceLibraryItem, VoiceSourceChannel
from app.services.voice_library_service import VoiceLibraryService


def _write_test_wav(path: Path, *, duration_seconds: float = 1.0, sample_rate: int = 16000) -> None:
    frame_count = int(duration_seconds * sample_rate)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for index in range(frame_count):
            sample = int(9000 * math.sin(2 * math.pi * 330 * index / sample_rate))
            frames.extend(sample.to_bytes(2, "little", signed=True))
        wav_file.writeframes(bytes(frames))


@pytest.mark.asyncio
async def test_auto_name_voice_uses_local_acoustic_features_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage"
    audio_path = storage_root / "voice-library" / "uploads" / "demo.wav"
    _write_test_wav(audio_path, duration_seconds=1.0)

    monkeypatch.setattr(settings, "storage_path", str(storage_root), raising=False)

    captured: dict[str, str] = {}

    class FakeProvider:
        async def generate(self, *, prompt: str, system_prompt: str, temperature: float):
            captured["prompt"] = prompt
            captured["system_prompt"] = system_prompt
            captured["temperature"] = str(temperature)
            return type(
                "Result", (), {"content": json.dumps({"name": "清亮学姐"}, ensure_ascii=False)}
            )()

    fake_runtime = type(
        "Runtime",
        (),
        {
            "provider_name": "fake",
            "provider_type": "openai_chat",
            "model": "fake-model",
            "provider": FakeProvider(),
        },
    )()

    monkeypatch.setattr(
        "app.services.voice_library_service.resolve_llm_runtime",
        lambda require_vision=False: fake_runtime,
    )

    item = VoiceLibraryItem(
        id=1,
        name="命名中",
        reference_text="今天给自己一点从容，把任务拆小一点，生活会顺很多。",
        audio_file_path="/storage/voice-library/uploads/demo.wav",
        is_enabled=True,
        is_builtin=False,
        builtin_key=None,
        source_channel=VoiceSourceChannel.AUDIO_FILE,
        auto_parse_text=True,
        source_file_name="demo.wav",
        name_status=VoiceItemFieldStatus.PENDING,
        reference_text_status=VoiceItemFieldStatus.READY,
    )

    service = VoiceLibraryService(None)  # type: ignore[arg-type]
    name = await service._auto_name_voice(item=item)

    assert name == "清亮学姐"
    assert "本地提取的音频声学特征" in captured["prompt"]
    assert "时长:" in captured["prompt"]
    assert "文本字速估计:" in captured["prompt"]
    assert "参考文本：" in captured["prompt"]
