from __future__ import annotations

import contextlib
import math
import re
import subprocess
import tempfile
import unicodedata
import wave
from pathlib import Path
from typing import Any


def visible_char_count(text: str) -> int:
    compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or ""))
    return len(compact)


@contextlib.contextmanager
def open_wave_compatible(path: Path):
    try:
        with contextlib.closing(wave.open(str(path), "rb")) as wav_file:
            yield wav_file
            return
    except wave.Error:
        pass

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
        temp_path = Path(temp_file.name)
    try:
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-acodec",
            "pcm_s16le",
            str(temp_path),
        ]
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
        if process.returncode != 0:
            raise RuntimeError(f"ffmpeg convert failed for {path}: {process.stderr.strip()}")
        with contextlib.closing(wave.open(str(temp_path), "rb")) as wav_file:
            yield wav_file
    finally:
        temp_path.unlink(missing_ok=True)


def extract_wav_acoustic_features(path: Path, transcript_text: str = "") -> dict[str, Any]:
    with open_wave_compatible(path) as wav_file:
        channels = int(wav_file.getnchannels())
        sample_width = int(wav_file.getsampwidth())
        sample_rate = int(wav_file.getframerate())
        total_frames = int(wav_file.getnframes())
        duration_seconds = total_frames / float(sample_rate) if sample_rate > 0 else 0.0

        window_seconds = 10.0
        max_windows = 3
        window_frames = max(1, int(sample_rate * window_seconds))
        positions = _build_frame_positions(
            total_frames=total_frames,
            window_frames=window_frames,
            max_windows=max_windows,
        )

        sampled_bytes = b""
        for pos in positions:
            wav_file.setpos(pos)
            sampled_bytes += wav_file.readframes(min(window_frames, total_frames - pos))

    if not sampled_bytes:
        raise ValueError(f"empty wav audio: {path}")

    if channels >= 2:
        mono_samples = _mix_to_mono(_pcm_to_ints(sampled_bytes, sample_width), channels)
    else:
        mono_samples = _pcm_to_ints(sampled_bytes, sample_width)

    max_possible_value = float((1 << (sample_width * 8 - 1)) - 1) if sample_width > 0 else 1.0
    sample_count = max(1, len(mono_samples))
    rms = math.sqrt(sum(value * value for value in mono_samples) / sample_count)
    peak = max((abs(value) for value in mono_samples), default=0.0)
    rms_norm = max(0.0, min(1.0, rms / max_possible_value))
    peak_norm = max(0.0, min(1.0, peak / max_possible_value))
    zero_crossing_rate = _estimate_zero_crossing_rate(mono_samples, sample_rate)
    silence_ratio, energy_variation = _estimate_silence_and_variation(
        mono_samples, sample_rate=sample_rate
    )

    transcript_chars = visible_char_count(transcript_text)
    chars_per_second = transcript_chars / duration_seconds if duration_seconds > 0 else 0.0

    return {
        "channels": channels,
        "sample_width_bytes": sample_width,
        "sample_rate_hz": sample_rate,
        "duration_seconds": round(duration_seconds, 3),
        "sampled_seconds": round(sample_count / float(sample_rate), 3) if sample_rate > 0 else 0.0,
        "rms_norm": round(rms_norm, 4),
        "peak_norm": round(peak_norm, 4),
        "zero_crossing_rate": round(zero_crossing_rate, 4),
        "silence_ratio": round(silence_ratio, 4),
        "energy_variation": round(energy_variation, 4),
        "transcript_chars": transcript_chars,
        "chars_per_second": round(chars_per_second, 3),
        "speaking_rate_label": _classify_speaking_rate(chars_per_second),
        "loudness_label": _classify_loudness(rms_norm),
        "energy_label": _classify_energy_variation(energy_variation),
        "clarity_label": _classify_clarity(zero_crossing_rate),
    }


def format_acoustic_features_for_prompt(features: dict[str, Any]) -> str:
    lines = [
        f"- 时长: {features.get('duration_seconds', 0)} 秒",
        f"- 声道数: {features.get('channels', 1)}",
        f"- 采样率: {features.get('sample_rate_hz', 0)} Hz",
        f"- 平均响度(RMS归一化): {features.get('rms_norm', 0)}",
        f"- 峰值电平(归一化): {features.get('peak_norm', 0)}",
        f"- 静音占比: {features.get('silence_ratio', 0)}",
        f"- 零交叉率: {features.get('zero_crossing_rate', 0)}",
        f"- 能量波动: {features.get('energy_variation', 0)} ({features.get('energy_label', '未知')})",
        f"- 文本字速估计: {features.get('chars_per_second', 0)} 字/秒 ({features.get('speaking_rate_label', '未知')})",
        f"- 响度感知: {features.get('loudness_label', '未知')}",
        f"- 清晰度倾向: {features.get('clarity_label', '未知')}",
    ]
    return "\n".join(lines)


def _build_frame_positions(total_frames: int, window_frames: int, max_windows: int) -> list[int]:
    if total_frames <= window_frames:
        return [0]
    if total_frames <= int(window_frames * 1.8):
        return [0]
    if total_frames <= int(window_frames * 2.6) or max_windows <= 2:
        return [0, max(0, total_frames - window_frames)]
    positions = [0]
    if max_windows >= 2:
        positions.append(max(0, (total_frames - window_frames) // 2))
    if max_windows >= 3:
        positions.append(max(0, total_frames - window_frames))
    return sorted({pos for pos in positions})


def _pcm_to_ints(data: bytes, sample_width: int) -> list[int]:
    if sample_width == 1:
        return [value - 128 for value in data]
    if sample_width == 2:
        return [
            int.from_bytes(data[index : index + 2], "little", signed=True)
            for index in range(0, len(data) - 1, 2)
        ]
    if sample_width == 4:
        return [
            int.from_bytes(data[index : index + 4], "little", signed=True)
            for index in range(0, len(data) - 3, 4)
        ]
    raise ValueError(f"unsupported sample width: {sample_width}")


def _mix_to_mono(samples: list[int], channels: int) -> list[int]:
    if channels <= 1:
        return samples
    mono: list[int] = []
    for index in range(0, len(samples), channels):
        frame = samples[index : index + channels]
        if not frame:
            continue
        mono.append(int(sum(frame) / len(frame)))
    return mono


def _estimate_zero_crossing_rate(samples: list[int], sample_rate: int) -> float:
    if sample_rate <= 0 or len(samples) < 2:
        return 0.0
    threshold = max(1, int(max(abs(value) for value in samples[: min(len(samples), 4096)]) * 0.02))
    crossings = 0
    previous = samples[0]
    for current in samples[1:]:
        if abs(previous) < threshold and abs(current) < threshold:
            previous = current
            continue
        if (previous < 0 <= current) or (previous > 0 >= current):
            crossings += 1
        previous = current
    duration = len(samples) / float(sample_rate)
    return crossings / duration if duration > 0 else 0.0


def _estimate_silence_and_variation(samples: list[int], *, sample_rate: int) -> tuple[float, float]:
    if sample_rate <= 0 or not samples:
        return 0.0, 0.0
    chunk_frames = max(1, int(sample_rate * 0.05))
    rms_values: list[float] = []
    for index in range(0, len(samples), chunk_frames):
        chunk = samples[index : index + chunk_frames]
        if not chunk:
            continue
        chunk_rms = math.sqrt(sum(value * value for value in chunk) / float(len(chunk)))
        rms_values.append(chunk_rms)
    if not rms_values:
        return 0.0, 0.0
    max_rms = max(rms_values) or 1.0
    silence_threshold = max(120.0, max_rms * 0.12)
    silence_ratio = sum(1 for value in rms_values if value <= silence_threshold) / float(
        len(rms_values)
    )
    mean_rms = sum(rms_values) / float(len(rms_values))
    variance = sum((value - mean_rms) ** 2 for value in rms_values) / float(len(rms_values))
    variation = math.sqrt(variance) / max(mean_rms, 1.0)
    return silence_ratio, variation


def _classify_speaking_rate(chars_per_second: float) -> str:
    if chars_per_second <= 0:
        return "未知"
    if chars_per_second < 3.2:
        return "偏慢"
    if chars_per_second < 5.0:
        return "自然"
    if chars_per_second < 6.6:
        return "偏快"
    return "很快"


def _classify_loudness(rms_norm: float) -> str:
    if rms_norm < 0.05:
        return "很轻"
    if rms_norm < 0.1:
        return "偏轻"
    if rms_norm < 0.18:
        return "适中"
    if rms_norm < 0.28:
        return "偏强"
    return "较强"


def _classify_energy_variation(variation: float) -> str:
    if variation < 0.22:
        return "平稳"
    if variation < 0.45:
        return "中等"
    return "起伏明显"


def _classify_clarity(zero_crossing_rate: float) -> str:
    if zero_crossing_rate < 900:
        return "低频偏厚"
    if zero_crossing_rate < 1800:
        return "均衡自然"
    return "高频偏亮"
