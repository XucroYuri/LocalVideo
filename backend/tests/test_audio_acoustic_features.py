import math
import wave
from pathlib import Path

from app.core.audio_acoustic_features import (
    extract_wav_acoustic_features,
    format_acoustic_features_for_prompt,
)


def _write_test_wav(path: Path, *, duration_seconds: float = 1.0, sample_rate: int = 16000) -> None:
    frame_count = int(duration_seconds * sample_rate)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for index in range(frame_count):
            sample = int(12000 * math.sin(2 * math.pi * 440 * index / sample_rate))
            frames.extend(sample.to_bytes(2, "little", signed=True))
        wav_file.writeframes(bytes(frames))


def test_extract_wav_acoustic_features_returns_expected_shape(tmp_path: Path) -> None:
    audio_path = tmp_path / "demo.wav"
    _write_test_wav(audio_path, duration_seconds=1.2)

    features = extract_wav_acoustic_features(
        audio_path, transcript_text="这是一个用于测试的口播文本"
    )

    assert features["channels"] == 1
    assert features["sample_rate_hz"] == 16000
    assert features["duration_seconds"] > 1.0
    assert features["rms_norm"] > 0
    assert features["peak_norm"] > 0
    assert features["transcript_chars"] > 0
    assert features["speaking_rate_label"] in {"偏慢", "自然", "偏快", "很快"}
    assert features["loudness_label"] in {"很轻", "偏轻", "适中", "偏强", "较强"}
    assert features["clarity_label"] in {"低频偏厚", "均衡自然", "高频偏亮"}

    prompt_text = format_acoustic_features_for_prompt(features)
    assert "时长:" in prompt_text
    assert "文本字速估计:" in prompt_text
