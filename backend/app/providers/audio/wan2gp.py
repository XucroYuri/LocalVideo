"""Wan2GP local audio provider (Qwen3 TTS 1.7B variants)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import shutil
import tempfile
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.storage_path import resolve_path_for_io
from app.providers.base.audio import AudioProvider, AudioResult
from app.providers.registry import audio_registry
from app.providers.wan2gp import (
    STATUS_GENERATING,
    Wan2GPBase,
    emit_bootstrap_status,
    register_wan2gp_pid,
    terminate_pid_tree,
    unregister_wan2gp_pid,
)

logger = logging.getLogger(__name__)

QWEN3_LANGUAGE_MODES: list[dict[str, str]] = [
    {"id": "auto", "label": "自动"},
    {"id": "chinese", "label": "中文"},
    {"id": "english", "label": "English"},
    {"id": "japanese", "label": "日本語"},
    {"id": "korean", "label": "한국어"},
    {"id": "german", "label": "Deutsch"},
    {"id": "french", "label": "Français"},
    {"id": "russian", "label": "Русский"},
    {"id": "portuguese", "label": "Português"},
    {"id": "spanish", "label": "Español"},
    {"id": "italian", "label": "Italiano"},
]

QWEN3_SPEAKER_MODES: list[dict[str, str]] = [
    {"id": "serena", "label": "Serena (Warm, gentle young female voice; Chinese)"},
    {"id": "aiden", "label": "Aiden (Sunny American male voice with a clear midrange; English)"},
    {
        "id": "dylan",
        "label": "Dylan (Youthful Beijing male voice with a clear, natural timbre; Chinese (Beijing Dialect))",
    },
    {
        "id": "eric",
        "label": "Eric (Lively Chengdu male voice with a slightly husky brightness; Chinese (Sichuan Dialect))",
    },
    {
        "id": "ono_anna",
        "label": "Ono Anna (Playful Japanese female voice with a light, nimble timbre; Japanese)",
    },
    {"id": "ryan", "label": "Ryan (Dynamic male voice with strong rhythmic drive; English)"},
    {"id": "v_serena", "label": "V Serena (Warm, gentle young female voice; Chinese)"},
    {"id": "sohee", "label": "Sohee (Warm Korean female voice with rich emotion; Korean)"},
    {
        "id": "uncle_fu",
        "label": "Uncle Fu (Seasoned male voice with a low, mellow timbre; Chinese)",
    },
    {"id": "vivian", "label": "Vivian (Bright, slightly edgy young female voice; Chinese)"},
]

WAN2GP_AUDIO_MODEL_PRESETS: dict[str, dict[str, Any]] = {
    "qwen3_tts_base": {
        "model_type": "qwen3_tts_base",
        "description": "Qwen3 Base (12Hz) 1.7B - 语音克隆（需要参考音频）",
        "supports_reference_audio": True,
        "audio_prompt_type": "A",
        "model_mode_label": "语言",
        "model_mode_choices": QWEN3_LANGUAGE_MODES,
        "default_model_mode": "auto",
        "default_alt_prompt": "",
        "default_duration_seconds": 600,
        "default_temperature": 0.9,
        "default_top_k": 50,
    },
    "qwen3_tts_customvoice": {
        "model_type": "qwen3_tts_customvoice",
        "description": "Qwen3 Custom Voice (12Hz) 1.7B - 预置音色",
        "supports_reference_audio": False,
        "audio_prompt_type": "",
        "model_mode_label": "音色",
        "model_mode_choices": QWEN3_SPEAKER_MODES,
        "default_model_mode": "serena",
        "default_alt_prompt": "calm, friendly, slightly husky",
        "default_duration_seconds": 600,
        "default_temperature": 0.9,
        "default_top_k": 50,
    },
    "qwen3_tts_voicedesign": {
        "model_type": "qwen3_tts_voicedesign",
        "description": "Qwen3 Voice Design (12Hz) 1.7B - 文本指定音色",
        "supports_reference_audio": False,
        "audio_prompt_type": "",
        "model_mode_label": "语言",
        "model_mode_choices": QWEN3_LANGUAGE_MODES,
        "default_model_mode": "auto",
        "default_alt_prompt": "young female, warm tone, clear articulation",
        "default_duration_seconds": 600,
        "default_temperature": 0.9,
        "default_top_k": 50,
    },
}

WAN2GP_AUDIO_PRESET_ORDER = [
    "qwen3_tts_base",
    "qwen3_tts_customvoice",
    "qwen3_tts_voicedesign",
]

WAN2GP_SPLIT_STRATEGY_SENTENCE_PUNCT = "sentence_punct"
WAN2GP_SPLIT_STRATEGY_ANCHOR_TAIL = "anchor_tail"
WAN2GP_SPLIT_STRATEGY_DEFAULT = WAN2GP_SPLIT_STRATEGY_SENTENCE_PUNCT
WAN2GP_SPLIT_STRATEGY_CHOICES = (
    WAN2GP_SPLIT_STRATEGY_SENTENCE_PUNCT,
    WAN2GP_SPLIT_STRATEGY_ANCHOR_TAIL,
)

AUDIO_OUTPUT_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg"}
BACKEND_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(__file__).resolve().parents[4]
WAN2GP_LOCAL_SPLIT_DEFAULT_SECONDS = 90.0
WAN2GP_LOCAL_SPLIT_MIN_SECONDS = 5.0
WAN2GP_LOCAL_SPLIT_MAX_SECONDS = 90.0
WAN2GP_LOCAL_SENTENCE_SPLIT_DEFAULT_SECONDS = WAN2GP_LOCAL_SPLIT_DEFAULT_SECONDS
WAN2GP_LOCAL_ANCHOR_SPLIT_DEFAULT_SECONDS = WAN2GP_LOCAL_SPLIT_DEFAULT_SECONDS
WAN2GP_QWEN3_AUTO_DURATION_BUFFER_DEFAULT_SECONDS = 60
WAN2GP_QWEN3_AUTO_DURATION_MAX_DEFAULT_SECONDS = 3600
WAN2GP_QWEN3_AUTO_DURATION_TRIGGER_RATIO = 1.15
WAN2GP_QWEN3_AUTO_DURATION_TRIGGER_MIN_DELTA_SECONDS = 30
WAN2GP_LOCAL_STITCH_DEFAULT_ENABLED = True
WAN2GP_LOCAL_STITCH_DEFAULT_PAUSE_MS = 20
WAN2GP_LOCAL_STITCH_DEFAULT_CROSSFADE_MS = 0
WAN2GP_LOCAL_STITCH_MAX_GAP_MS = 300
WAN2GP_LOCAL_CHUNK_LOG_PREVIEW_CHARS = 28
WAN2GP_SENTENCE_PUNCT_TARGET_WINDOW_CHARS = 50
WAN2GP_SENTENCE_PUNCT_EXTEND_WINDOW_CHARS = 30
WAN2GP_ANCHOR_TAIL_TARGET_WINDOW_CHARS = 200
WAN2GP_ANCHOR_TAIL_EXTEND_WINDOW_CHARS = 120
WAN2GP_SENTENCE_PUNCT_MIN_TAIL_CHARS = 12
WAN2GP_ANCHOR_TAIL_MIN_TAIL_CHARS = 24
WAN2GP_STRONG_SPLIT_MARKERS = frozenset(("。", "！", "？", ".", "!", "?"))
WAN2GP_WEAK_SPLIT_MARKERS = frozenset(("，", "、", "；", "：", ",", ";", ":"))
WAN2GP_SPACE_SPLIT_MARKERS = frozenset((" ", "\t", "\u3000"))
WAN2GP_TRAILING_CLOSERS = frozenset(
    (
        "”",
        "’",
        "」",
        "』",
        "】",
        "》",
        ")",
        "）",
        "]",
        "}",
        '"',
        "'",
    )
)
WAN2GP_SILENCEDETECT_NOISE_DB = -38.0
WAN2GP_SILENCEDETECT_MIN_SECONDS = 0.06
WAN2GP_SILENCEDETECT_EOF_TOLERANCE_SECONDS = 0.08
WAN2GP_TARGET_TAIL_SILENCE_MS = 90
WAN2GP_MAX_TAIL_SILENCE_MS = 220
WAN2GP_LOCAL_ANCHOR_TEXT = "这里是收尾锚点"
WAN2GP_LOCAL_ANCHOR_PREFIX = "。"
WAN2GP_LOCAL_ANCHOR_SUFFIX = "。"
WAN2GP_LOCAL_ANCHOR_EXTRA_MARGIN_MS = 80
WAN2GP_LOCAL_ANCHOR_MIN_REMOVE_MS = 400
WAN2GP_LOCAL_ANCHOR_MAX_REMOVE_MS = 4500
WAN2GP_LOCAL_CHUNK_KEEP_ARTIFACTS_DEFAULT = False
WAN2GP_LOCAL_ANCHOR_GAP_DETECT_MIN_SECONDS = 0.03
WAN2GP_LOCAL_ANCHOR_BOUNDARY_MIN_GAP_SECONDS = 0.10
WAN2GP_LOCAL_ANCHOR_BOUNDARY_SEARCH_EXPAND_RATIO = 0.15
WAN2GP_LOCAL_ANCHOR_RELATIVE_MEAN_OFFSET_DB = 24.0
WAN2GP_LOCAL_ANCHOR_RELATIVE_SWEEP_DB = (6.0, 3.0, 0.0, -3.0)
WAN2GP_LOCAL_ANCHOR_RELATIVE_NOISE_DB_MIN = -65.0
WAN2GP_LOCAL_ANCHOR_RELATIVE_NOISE_DB_MAX = -18.0


@dataclass
class Wan2GPAudioBatchTask:
    task_id: str
    text: str
    output_path: Path
    preset: str = ""
    model_mode: str = ""
    alt_prompt: str | None = None
    duration_seconds: int | None = None
    temperature: float | None = None
    top_k: int | None = None
    seed: int | None = None
    audio_guide: str | None = None
    speed: float | None = None
    split_strategy: str | None = None
    sentence_split_every_seconds: float | None = None
    anchor_split_every_seconds: float | None = None
    auto_duration_buffer_seconds: int | None = None
    auto_duration_max_seconds: int | None = None
    local_stitch: bool | None = None
    local_stitch_pause_ms: int | None = None
    local_stitch_crossfade_ms: int | None = None
    local_stitch_keep_artifacts: bool | None = None


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _normalize_speed(value: Any, default: float = 1.0) -> float:
    speed = _to_float(value, default)
    # Keep speed in a safe range for ffmpeg atempo and UI sliders.
    return max(0.5, min(2.0, speed))


def _normalize_split_strategy(value: Any, default: str = WAN2GP_SPLIT_STRATEGY_DEFAULT) -> str:
    normalized_default = (
        default if default in WAN2GP_SPLIT_STRATEGY_CHOICES else WAN2GP_SPLIT_STRATEGY_DEFAULT
    )
    if value is None:
        return normalized_default
    text = str(value or "").strip().lower()
    if not text:
        return normalized_default
    if text == WAN2GP_SPLIT_STRATEGY_SENTENCE_PUNCT:
        return WAN2GP_SPLIT_STRATEGY_SENTENCE_PUNCT
    if text == WAN2GP_SPLIT_STRATEGY_ANCHOR_TAIL:
        return WAN2GP_SPLIT_STRATEGY_ANCHOR_TAIL
    return normalized_default


def _normalize_positive_int(value: Any, default: int) -> int:
    parsed = _to_int(value, default)
    return parsed if parsed > 0 else default


def _normalize_non_negative_int(value: Any, default: int) -> int:
    parsed = _to_int(value, default)
    return parsed if parsed >= 0 else default


def _find_last_marker_index(text: str, markers: frozenset[str]) -> int:
    for idx in range(len(text) - 1, -1, -1):
        if text[idx] in markers:
            return idx
    return -1


def _find_first_marker_index(text: str, markers: frozenset[str]) -> int:
    for idx, ch in enumerate(text):
        if ch in markers:
            return idx
    return -1


def _consume_trailing_closers(text: str, index: int) -> int:
    cursor = max(0, int(index))
    while cursor < len(text) and text[cursor] in WAN2GP_TRAILING_CLOSERS:
        cursor += 1
    return cursor


def _split_text_with_progressive_fallback(
    text: str,
    *,
    target_window_chars: int,
    extend_window_chars: int,
    min_tail_chars: int,
) -> list[str]:
    chunks: list[str] = []
    remaining = str(text or "").strip()
    if not remaining:
        return chunks
    safe_target = max(1, int(target_window_chars))
    safe_extend = max(0, int(extend_window_chars))
    hard_limit = safe_target + safe_extend

    while remaining:
        if len(remaining) <= hard_limit:
            chunks.append(remaining.strip())
            break

        target_window = remaining[:safe_target]
        split_index = _find_last_marker_index(target_window, WAN2GP_STRONG_SPLIT_MARKERS)
        if split_index < 0:
            split_index = _find_last_marker_index(target_window, WAN2GP_WEAK_SPLIT_MARKERS)
        if split_index < 0:
            split_index = _find_last_marker_index(target_window, WAN2GP_SPACE_SPLIT_MARKERS)

        if split_index < 0 and safe_extend > 0:
            extended_window = remaining[safe_target:hard_limit]
            next_strong = _find_first_marker_index(extended_window, WAN2GP_STRONG_SPLIT_MARKERS)
            if next_strong >= 0:
                split_index = safe_target + next_strong
        if split_index < 0 and safe_extend > 0:
            extended_window = remaining[safe_target:hard_limit]
            next_weak = _find_first_marker_index(extended_window, WAN2GP_WEAK_SPLIT_MARKERS)
            if next_weak >= 0:
                split_index = safe_target + next_weak
        if split_index < 0 and safe_extend > 0:
            extended_window = remaining[safe_target:hard_limit]
            next_space = _find_first_marker_index(extended_window, WAN2GP_SPACE_SPLIT_MARKERS)
            if next_space >= 0:
                split_index = safe_target + next_space
        if split_index < 0:
            split_index = hard_limit - 1

        end = _consume_trailing_closers(remaining, split_index + 1)
        piece = remaining[:end].strip()
        if piece:
            chunks.append(piece)
        remaining = remaining[end:].lstrip()

    if len(chunks) >= 2 and len(chunks[-1]) < max(1, int(min_tail_chars)):
        chunks[-2] = f"{chunks[-2]}{chunks[-1]}"
        chunks.pop()

    return chunks


def _load_defaults_payloads(
    defaults_dir: Path | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    payload_by_stem: dict[str, dict[str, Any]] = {}
    payload_by_architecture: dict[str, dict[str, Any]] = {}
    if defaults_dir is None or not defaults_dir.exists() or not defaults_dir.is_dir():
        return payload_by_stem, payload_by_architecture

    for config_file in sorted(defaults_dir.glob("*.json")):
        try:
            payload = json.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        payload_by_stem[config_file.stem] = payload
        model_info = payload.get("model")
        if isinstance(model_info, dict):
            architecture = str(model_info.get("architecture") or "").strip()
            if architecture and architecture not in payload_by_architecture:
                payload_by_architecture[architecture] = payload
    return payload_by_stem, payload_by_architecture


def get_wan2gp_audio_preset(preset_name: str) -> dict[str, Any]:
    if preset_name not in WAN2GP_AUDIO_MODEL_PRESETS:
        available = ", ".join(sorted(WAN2GP_AUDIO_MODEL_PRESETS.keys()))
        raise ValueError(f"Unknown Wan2GP audio preset: {preset_name}. Available: {available}")
    return dict(WAN2GP_AUDIO_MODEL_PRESETS[preset_name])


def get_wan2gp_audio_presets(wan2gp_path: str | None = None) -> list[dict[str, Any]]:
    defaults_dir = Path(wan2gp_path).expanduser() / "defaults" if wan2gp_path else None
    payload_by_stem, payload_by_architecture = _load_defaults_payloads(defaults_dir)

    rows: list[dict[str, Any]] = []
    for preset_name in WAN2GP_AUDIO_PRESET_ORDER:
        if preset_name not in WAN2GP_AUDIO_MODEL_PRESETS:
            continue

        preset = get_wan2gp_audio_preset(preset_name)
        payload = payload_by_stem.get(preset_name)
        if payload is None:
            payload = payload_by_architecture.get(str(preset.get("model_type") or ""))
        if payload is None:
            payload = {}

        model_info = payload.get("model") if isinstance(payload.get("model"), dict) else {}
        display_name = str(model_info.get("name") or "").strip()
        description = str(model_info.get("description") or "").strip()
        if not display_name:
            display_name = str(preset["description"]).split(" - ", maxsplit=1)[0]
        if not description:
            description = str(preset["description"])

        payload_mode = payload.get("model_mode")
        default_model_mode = (
            str(payload_mode).strip()
            if isinstance(payload_mode, str)
            else str(preset["default_model_mode"])
        )
        if not default_model_mode:
            default_model_mode = str(preset["default_model_mode"])

        payload_alt_prompt = payload.get("alt_prompt")
        default_alt_prompt = (
            str(payload_alt_prompt)
            if isinstance(payload_alt_prompt, str)
            else str(preset["default_alt_prompt"])
        )
        default_duration_seconds = _to_int(
            payload.get("duration_seconds"),
            int(preset["default_duration_seconds"]),
        )
        if default_duration_seconds <= 0:
            default_duration_seconds = int(preset["default_duration_seconds"])

        rows.append(
            {
                "id": preset_name,
                "display_name": display_name,
                "description": description,
                "model_type": str(preset["model_type"]),
                "supports_reference_audio": bool(preset.get("supports_reference_audio", False)),
                "model_mode_label": str(preset["model_mode_label"]),
                "model_mode_choices": list(preset["model_mode_choices"]),
                "default_model_mode": default_model_mode,
                "default_alt_prompt": default_alt_prompt,
                "default_duration_seconds": default_duration_seconds,
                "default_temperature": float(preset["default_temperature"]),
                "default_top_k": int(preset["default_top_k"]),
            }
        )

    return rows


@audio_registry.register("wan2gp")
class Wan2GPAudioProvider(Wan2GPBase, AudioProvider):
    name = "wan2gp"

    def __init__(
        self,
        wan2gp_path: str | None = None,
        python_executable: str | None = None,
        preset: str = "qwen3_tts_base",
        model_mode: str = "",
        alt_prompt: str = "",
        duration_seconds: int | None = None,
        temperature: float = 0.9,
        top_k: int = 50,
        seed: int = -1,
        audio_guide: str | None = None,
        speed: float = 1.0,
        split_strategy: str = WAN2GP_SPLIT_STRATEGY_DEFAULT,
        local_sentence_split_every_seconds: float
        | None = WAN2GP_LOCAL_SENTENCE_SPLIT_DEFAULT_SECONDS,
        local_anchor_split_every_seconds: float | None = WAN2GP_LOCAL_ANCHOR_SPLIT_DEFAULT_SECONDS,
        auto_duration_buffer_seconds: int = WAN2GP_QWEN3_AUTO_DURATION_BUFFER_DEFAULT_SECONDS,
        auto_duration_max_seconds: int = WAN2GP_QWEN3_AUTO_DURATION_MAX_DEFAULT_SECONDS,
    ):
        self.wan2gp_path = Path(wan2gp_path or "../Wan2GP")
        self.python_executable = python_executable
        self.preset_name = preset
        self.model_mode_override = (model_mode or "").strip()
        self.alt_prompt_override = alt_prompt or ""
        self.duration_seconds_override: int | None = None
        if duration_seconds is not None:
            parsed_duration = _to_int(duration_seconds, -1)
            if parsed_duration > 0:
                self.duration_seconds_override = parsed_duration
        self.temperature_override = _to_float(temperature, 0.9)
        self.top_k_override = _to_int(top_k, 50)
        self.seed = _to_int(seed, -1)
        self.audio_guide_override = (audio_guide or "").strip()
        self.speed_override = _normalize_speed(speed, 1.0)
        self.split_strategy_override = _normalize_split_strategy(split_strategy)
        # Deprecated: local split threshold no longer drives split behavior.
        del local_sentence_split_every_seconds, local_anchor_split_every_seconds
        self.auto_duration_buffer_seconds_override = _normalize_positive_int(
            auto_duration_buffer_seconds,
            WAN2GP_QWEN3_AUTO_DURATION_BUFFER_DEFAULT_SECONDS,
        )
        self.auto_duration_max_seconds_override = _normalize_positive_int(
            auto_duration_max_seconds,
            WAN2GP_QWEN3_AUTO_DURATION_MAX_DEFAULT_SECONDS,
        )

    def _get_audio_config(
        self,
        *,
        text: str = "",
        preset_name: str = "",
        model_mode: str = "",
        alt_prompt: str | None = None,
        duration_seconds: int | None = None,
        temperature: float | None = None,
        top_k: int | None = None,
        seed: int | None = None,
        audio_guide: str | None = None,
        speed: float | None = None,
        split_strategy: str | None = None,
        local_sentence_split_every_seconds: float | None = None,
        local_anchor_split_every_seconds: float | None = None,
        auto_duration_buffer_seconds: int | None = None,
        auto_duration_max_seconds: int | None = None,
    ) -> dict[str, Any]:
        # Deprecated: local split threshold no longer drives split behavior.
        del local_sentence_split_every_seconds, local_anchor_split_every_seconds
        resolved_preset_name = (preset_name or self.preset_name).strip() or "qwen3_tts_base"
        preset = get_wan2gp_audio_preset(resolved_preset_name)

        resolved_mode = (model_mode or self.model_mode_override).strip() or str(
            preset["default_model_mode"]
        )

        if alt_prompt is None:
            resolved_alt_prompt = self.alt_prompt_override or str(preset["default_alt_prompt"])
        else:
            resolved_alt_prompt = alt_prompt

        raw_duration = (
            duration_seconds if duration_seconds is not None else self.duration_seconds_override
        )
        if raw_duration is None:
            resolved_duration = int(preset["default_duration_seconds"])
        else:
            resolved_duration = _to_int(raw_duration, int(preset["default_duration_seconds"]))
        if resolved_duration <= 0:
            resolved_duration = int(preset["default_duration_seconds"])
        requested_duration = int(resolved_duration)

        resolved_temperature = _to_float(
            temperature if temperature is not None else self.temperature_override,
            float(preset["default_temperature"]),
        )
        if resolved_temperature <= 0:
            resolved_temperature = float(preset["default_temperature"])

        resolved_top_k = _to_int(
            top_k if top_k is not None else self.top_k_override,
            int(preset["default_top_k"]),
        )
        if resolved_top_k <= 0:
            resolved_top_k = int(preset["default_top_k"])

        resolved_seed = _to_int(seed if seed is not None else self.seed, -1)
        resolved_audio_guide = (audio_guide or self.audio_guide_override).strip()
        if not resolved_audio_guide:
            resolved_audio_guide = ""
        resolved_speed = _normalize_speed(
            speed if speed is not None else self.speed_override,
            self.speed_override,
        )
        resolved_split_strategy = _normalize_split_strategy(
            split_strategy,
            default=self.split_strategy_override,
        )
        resolved_auto_duration_buffer_seconds = _normalize_positive_int(
            auto_duration_buffer_seconds
            if auto_duration_buffer_seconds is not None
            else self.auto_duration_buffer_seconds_override,
            WAN2GP_QWEN3_AUTO_DURATION_BUFFER_DEFAULT_SECONDS,
        )
        resolved_auto_duration_max_seconds = _normalize_positive_int(
            auto_duration_max_seconds
            if auto_duration_max_seconds is not None
            else self.auto_duration_max_seconds_override,
            WAN2GP_QWEN3_AUTO_DURATION_MAX_DEFAULT_SECONDS,
        )
        estimated_duration_seconds = self._estimate_total_seconds_from_text(text)
        auto_duration_applied = False
        if estimated_duration_seconds > resolved_duration and (
            estimated_duration_seconds
            >= int(round(float(resolved_duration) * WAN2GP_QWEN3_AUTO_DURATION_TRIGGER_RATIO))
            or (
                estimated_duration_seconds - resolved_duration
                >= WAN2GP_QWEN3_AUTO_DURATION_TRIGGER_MIN_DELTA_SECONDS
            )
        ):
            target_duration = estimated_duration_seconds + resolved_auto_duration_buffer_seconds
            target_duration = min(target_duration, resolved_auto_duration_max_seconds)
            if target_duration > resolved_duration:
                resolved_duration = target_duration
                auto_duration_applied = True

        return {
            "preset_name": resolved_preset_name,
            "model_type": str(preset["model_type"]),
            "supports_reference_audio": bool(preset.get("supports_reference_audio", False)),
            "audio_prompt_type": str(preset["audio_prompt_type"]),
            "model_mode": resolved_mode,
            "alt_prompt": resolved_alt_prompt,
            "duration_seconds": resolved_duration,
            "requested_duration_seconds": requested_duration,
            "estimated_duration_seconds": estimated_duration_seconds,
            "auto_duration_applied": auto_duration_applied,
            "auto_duration_buffer_seconds": resolved_auto_duration_buffer_seconds,
            "auto_duration_max_seconds": resolved_auto_duration_max_seconds,
            "temperature": resolved_temperature,
            "top_k": resolved_top_k,
            "seed": resolved_seed,
            "audio_guide": resolved_audio_guide,
            "speed": resolved_speed,
            "split_strategy": resolved_split_strategy,
        }

    @staticmethod
    def _build_settings_payload(
        *,
        text: str,
        audio_config: dict[str, Any],
        output_filename: str = "",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "settings_version": 2.49,
            "prompt": text,
            "multi_prompts_gen_type": 2,
            "model_type": audio_config["model_type"],
            "type": audio_config["model_type"],
            "image_mode": 0,
            "audio_prompt_type": audio_config["audio_prompt_type"],
            "model_mode": audio_config["model_mode"],
            "alt_prompt": audio_config["alt_prompt"],
            "duration_seconds": int(audio_config["duration_seconds"]),
            "temperature": float(audio_config["temperature"]),
            "top_k": int(audio_config["top_k"]),
            "seed": int(audio_config["seed"]),
            "batch_size": 1,
            "num_inference_steps": 0,
            "negative_prompt": "",
            "video_length": 0,
        }
        if audio_config["audio_guide"]:
            payload["audio_guide"] = str(audio_config["audio_guide"])
            payload["audio_prompt_type"] = "A"
        if output_filename:
            payload["output_filename"] = output_filename
        return payload

    @staticmethod
    def _estimate_total_seconds_from_text(text: str) -> int:
        text_compact = re.sub(r"\s+", "", text or "")
        return max(1, (len(text_compact) + 3) // 4)

    @staticmethod
    def _prepare_text_for_local_split(
        text: str,
        *,
        split_strategy: str,
    ) -> tuple[str, int]:
        resolved_split_strategy = _normalize_split_strategy(split_strategy)
        normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            return normalized, 0

        if resolved_split_strategy == WAN2GP_SPLIT_STRATEGY_ANCHOR_TAIL:
            target_chars = WAN2GP_ANCHOR_TAIL_TARGET_WINDOW_CHARS
            extend_chars = WAN2GP_ANCHOR_TAIL_EXTEND_WINDOW_CHARS
            min_tail_chars = WAN2GP_ANCHOR_TAIL_MIN_TAIL_CHARS
        else:
            target_chars = WAN2GP_SENTENCE_PUNCT_TARGET_WINDOW_CHARS
            extend_chars = WAN2GP_SENTENCE_PUNCT_EXTEND_WINDOW_CHARS
            min_tail_chars = WAN2GP_SENTENCE_PUNCT_MIN_TAIL_CHARS

        paragraphs = re.split(r"\n\s*\n+", normalized)
        prepared_chunks: list[str] = []

        for paragraph in paragraphs:
            paragraph_text = paragraph.strip()
            if not paragraph_text:
                continue
            prepared_chunks.extend(
                _split_text_with_progressive_fallback(
                    paragraph_text,
                    target_window_chars=target_chars,
                    extend_window_chars=extend_chars,
                    min_tail_chars=min_tail_chars,
                )
            )

        if not prepared_chunks:
            prepared_chunks = [normalized]
        final_chunks = [chunk for chunk in prepared_chunks if chunk]
        if not final_chunks:
            return normalized, 1
        return "\n\n".join(final_chunks), len(final_chunks)

    @staticmethod
    def _extract_manual_chunks(prepared_text: str) -> list[str]:
        return [
            chunk.strip()
            for chunk in re.split(r"\n\s*\n+", str(prepared_text or ""))
            if chunk and chunk.strip()
        ]

    @staticmethod
    def _resolve_output_and_raw_paths(
        *,
        output_path: Path,
        source_suffix: str,
        runtime_raw_output_path: Any,
    ) -> tuple[Path, Path]:
        normalized_suffix = str(source_suffix or output_path.suffix or ".wav").lower()
        final_output_path = (
            output_path
            if output_path.suffix.lower() == normalized_suffix
            else output_path.with_suffix(normalized_suffix)
        )
        if isinstance(runtime_raw_output_path, str | Path) and str(runtime_raw_output_path).strip():
            raw_output_path = Path(str(runtime_raw_output_path)).expanduser()
        else:
            raw_output_path = final_output_path.with_name(
                f"{final_output_path.stem}.raw{final_output_path.suffix}"
            )
        if raw_output_path.suffix.lower() != normalized_suffix:
            raw_output_path = raw_output_path.with_suffix(normalized_suffix)
        if raw_output_path.resolve() == final_output_path.resolve():
            raw_output_path = final_output_path.with_name(
                f"{final_output_path.stem}.raw{final_output_path.suffix}"
            )
        return final_output_path, raw_output_path

    @staticmethod
    def _chunk_preview(text: str, max_chars: int = WAN2GP_LOCAL_CHUNK_LOG_PREVIEW_CHARS) -> str:
        normalized = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(normalized) <= max_chars:
            return normalized
        return f"{normalized[:max_chars]}..."

    async def _stitch_local_chunks(
        self,
        *,
        chunk_paths: list[Path],
        output_path: Path,
        pause_ms: int,
        crossfade_ms: int,
        boundary_pause_ms_list: list[int] | None = None,
    ) -> None:
        if not chunk_paths:
            raise ValueError("No chunk audio files provided for stitching.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            output_path.unlink()
        if len(chunk_paths) == 1:
            shutil.copy2(str(chunk_paths[0]), str(output_path))
            return

        sample_rate = (await self._probe_audio_metadata(chunk_paths[0]))[1]
        if sample_rate <= 0:
            sample_rate = 24000

        cmd = ["ffmpeg", "-y"]
        for path in chunk_paths:
            cmd.extend(["-i", str(path)])

        filter_parts: list[str] = []
        normalized_labels: list[str] = []
        for idx in range(len(chunk_paths)):
            label = f"[src{idx}]"
            filter_parts.append(
                f"[{idx}:a]aresample={sample_rate},aformat=sample_fmts=fltp:channel_layouts=mono{label}"
            )
            normalized_labels.append(label)

        map_label = ""
        if crossfade_ms > 0:
            fade_seconds = max(0.0, float(crossfade_ms) / 1000.0)
            map_label = normalized_labels[0]
            for idx in range(1, len(normalized_labels)):
                out_label = f"[xf{idx}]"
                filter_parts.append(
                    f"{map_label}{normalized_labels[idx]}"
                    f"acrossfade=d={fade_seconds:.3f}:c1=tri:c2=tri{out_label}"
                )
                map_label = out_label
        else:
            concat_labels: list[str] = []
            default_pause_seconds = max(0.0, float(pause_ms) / 1000.0)
            for idx, label in enumerate(normalized_labels):
                concat_labels.append(label)
                if idx < len(normalized_labels) - 1:
                    pause_seconds = default_pause_seconds
                    if isinstance(boundary_pause_ms_list, list) and idx < len(
                        boundary_pause_ms_list
                    ):
                        pause_seconds = max(
                            0.0,
                            float(_normalize_non_negative_int(boundary_pause_ms_list[idx], 0))
                            / 1000.0,
                        )
                    if pause_seconds <= 0:
                        continue
                    silence_label = f"[sil{idx}]"
                    filter_parts.append(
                        f"anullsrc=r={sample_rate}:cl=mono,atrim=0:{pause_seconds:.3f}{silence_label}"
                    )
                    concat_labels.append(silence_label)
            map_label = "[out]"
            filter_parts.append(
                f"{''.join(concat_labels)}concat=n={len(concat_labels)}:v=0:a=1{map_label}"
            )

        filter_complex = ";".join(filter_parts)
        cmd.extend(
            [
                "-filter_complex",
                filter_complex,
                "-map",
                map_label,
                "-vn",
                str(output_path),
            ]
        )
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0 or not output_path.exists():
            error_text = stderr.decode(errors="ignore").strip()
            raise RuntimeError(
                "Wan2GP local chunk stitching failed "
                f"(pause_ms={pause_ms}, crossfade_ms={crossfade_ms}): {error_text}"
            )

    async def _detect_silence_intervals(
        self,
        file_path: Path,
        *,
        detection_min_seconds: float | None = None,
        noise_db: float | None = None,
    ) -> tuple[float, list[tuple[float, float]]]:
        duration, _ = await self._probe_audio_metadata(file_path)
        if duration <= 0:
            return 0.0, []
        resolved_min_seconds = (
            WAN2GP_SILENCEDETECT_MIN_SECONDS
            if detection_min_seconds is None
            else max(0.001, float(detection_min_seconds))
        )
        resolved_noise_db = WAN2GP_SILENCEDETECT_NOISE_DB if noise_db is None else float(noise_db)
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(file_path),
            "-af",
            (f"silencedetect=noise={resolved_noise_db:.1f}dB:d={resolved_min_seconds:.3f}"),
            "-f",
            "null",
            "-",
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode not in {0, 255}:
            return duration, []
        text = stderr.decode(errors="ignore")
        start_pattern = re.compile(r"silence_start:\s*([0-9]+(?:\.[0-9]+)?)")
        end_pattern = re.compile(
            r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)\s*\|\s*silence_duration:\s*([0-9]+(?:\.[0-9]+)?)"
        )
        intervals: list[tuple[float, float]] = []
        pending_start: float | None = None
        for line in text.splitlines():
            start_match = start_pattern.search(line)
            if start_match:
                pending_start = _to_float(start_match.group(1), 0.0)
                continue
            end_match = end_pattern.search(line)
            if end_match:
                end_value = _to_float(end_match.group(1), 0.0)
                if pending_start is not None and end_value > pending_start:
                    intervals.append((pending_start, end_value))
                pending_start = None
        if pending_start is not None and duration > pending_start:
            intervals.append((pending_start, duration))
        return duration, intervals

    async def _detect_trailing_silence(self, file_path: Path) -> tuple[float, float]:
        duration, intervals = await self._detect_silence_intervals(file_path)
        if not intervals:
            return duration, 0.0
        last_start, last_end = intervals[-1]
        if last_end < duration - WAN2GP_SILENCEDETECT_EOF_TOLERANCE_SECONDS:
            return duration, 0.0
        trailing = max(0.0, duration - max(0.0, last_start))
        if trailing < WAN2GP_SILENCEDETECT_MIN_SECONDS:
            return duration, 0.0
        return duration, trailing

    async def _trim_audio_to_duration(
        self,
        *,
        input_path: Path,
        output_path: Path,
        end_seconds: float,
    ) -> Path:
        safe_end = max(0.01, float(end_seconds or 0.0))
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-af",
            f"atrim=0:{safe_end:.6f},asetpts=N/SR/TB",
            "-vn",
            str(output_path),
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0 or not output_path.exists():
            error_text = stderr.decode(errors="ignore").strip()
            raise RuntimeError(
                f"Wan2GP tail trim failed (end={safe_end:.3f}s, input={input_path}): {error_text}"
            )
        return output_path

    @staticmethod
    def _build_anchor_appended_text(text: str) -> str:
        base = str(text or "").strip()
        if not base:
            return base
        return (
            f"{base}"
            f"{WAN2GP_LOCAL_ANCHOR_PREFIX}"
            f"{WAN2GP_LOCAL_ANCHOR_TEXT}"
            f"{WAN2GP_LOCAL_ANCHOR_SUFFIX}"
        )

    @staticmethod
    def _estimate_anchor_trim_seconds(
        *,
        anchor_duration_seconds: float,
        trailing_silence_seconds: float,
    ) -> float:
        remove_ms = int(
            round(anchor_duration_seconds * 1000.0)
            + round(max(0.0, trailing_silence_seconds) * 1000.0)
            + WAN2GP_LOCAL_ANCHOR_EXTRA_MARGIN_MS
        )
        remove_ms = max(WAN2GP_LOCAL_ANCHOR_MIN_REMOVE_MS, remove_ms)
        remove_ms = min(WAN2GP_LOCAL_ANCHOR_MAX_REMOVE_MS, remove_ms)
        return float(remove_ms) / 1000.0

    async def _find_anchor_boundary_by_silence(
        self,
        *,
        file_path: Path,
        anchor_duration_seconds: float,
    ) -> tuple[float, float, float, float, float]:
        duration, _ = await self._probe_audio_metadata(file_path)
        if duration <= 0:
            return 0.0, 0.0, 0.0, 0.0, WAN2GP_SILENCEDETECT_NOISE_DB
        if anchor_duration_seconds <= 0:
            return duration, 0.0, 0.0, 0.0, WAN2GP_SILENCEDETECT_NOISE_DB
        search_window_seconds = float(anchor_duration_seconds) * (
            1.0 + WAN2GP_LOCAL_ANCHOR_BOUNDARY_SEARCH_EXPAND_RATIO
        )
        search_window_seconds = max(
            WAN2GP_LOCAL_ANCHOR_GAP_DETECT_MIN_SECONDS, search_window_seconds
        )
        search_start = max(0.0, duration - search_window_seconds)

        mean_volume_db, _max_volume_db = await self._probe_volume_detect_db(file_path)
        base_noise_db = (
            WAN2GP_SILENCEDETECT_NOISE_DB
            if mean_volume_db is None
            else (float(mean_volume_db) - WAN2GP_LOCAL_ANCHOR_RELATIVE_MEAN_OFFSET_DB)
        )
        candidate_noise_values: list[float] = []
        for sweep in WAN2GP_LOCAL_ANCHOR_RELATIVE_SWEEP_DB:
            noise_db = base_noise_db - float(sweep)
            noise_db = max(WAN2GP_LOCAL_ANCHOR_RELATIVE_NOISE_DB_MIN, noise_db)
            noise_db = min(WAN2GP_LOCAL_ANCHOR_RELATIVE_NOISE_DB_MAX, noise_db)
            candidate_noise_values.append(round(noise_db, 1))
        candidate_noise_values = sorted(set(candidate_noise_values))

        # candidate tuple: (gap_seconds, noise_db, interval_start)
        strong_candidates: list[tuple[float, float, float]] = []
        weak_candidates: list[tuple[float, float, float]] = []
        for noise_db in candidate_noise_values:
            _, intervals = await self._detect_silence_intervals(
                file_path,
                detection_min_seconds=WAN2GP_LOCAL_ANCHOR_GAP_DETECT_MIN_SECONDS,
                noise_db=noise_db,
            )
            for interval_start, interval_end in intervals:
                if interval_end <= interval_start:
                    continue
                if interval_end >= duration - WAN2GP_SILENCEDETECT_EOF_TOLERANCE_SECONDS:
                    # trailing silence at EOF is not a reliable anchor boundary
                    continue
                if interval_start < search_start:
                    continue
                gap_seconds = interval_end - interval_start
                candidate = (gap_seconds, noise_db, interval_start)
                weak_candidates.append(candidate)
                if gap_seconds >= WAN2GP_LOCAL_ANCHOR_BOUNDARY_MIN_GAP_SECONDS:
                    strong_candidates.append(candidate)

        picked = strong_candidates or weak_candidates
        if not picked:
            # No silence interval detected in the relative window: cut at window start.
            trim_to_seconds = max(0.05, min(duration - 0.01, search_start))
            return duration, trim_to_seconds, search_start, 0.0, WAN2GP_SILENCEDETECT_NOISE_DB

        # Primary: larger gap; Secondary: lower relative dB (more negative); Tertiary: later boundary.
        best_gap, best_noise_db, best_start = sorted(
            picked,
            key=lambda item: (-item[0], item[1], -item[2]),
        )[0]
        trim_to_seconds = max(0.05, min(duration - 0.01, best_start))
        return duration, trim_to_seconds, search_start, best_gap, best_noise_db

    async def _probe_volume_detect_db(self, file_path: Path) -> tuple[float | None, float | None]:
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(file_path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode not in {0, 255}:
            return None, None
        text = stderr.decode(errors="ignore")
        mean_match = re.search(r"mean_volume:\s*(-?[0-9]+(?:\.[0-9]+)?)\s*dB", text)
        max_match = re.search(r"max_volume:\s*(-?[0-9]+(?:\.[0-9]+)?)\s*dB", text)
        mean_db = _to_float(mean_match.group(1), 0.0) if mean_match else None
        max_db = _to_float(max_match.group(1), 0.0) if max_match else None
        return mean_db, max_db

    async def _synthesize_with_local_chunks(
        self,
        *,
        chunk_texts: list[str],
        split_strategy: str,
        output_path: Path,
        runtime_raw_output_path: Any,
        audio_config: dict[str, Any],
        progress_callback: Callable[[int], Awaitable[None]] | None,
        status_callback: Callable[[str], Awaitable[None]] | None,
        pause_ms: int,
        crossfade_ms: int,
        keep_artifacts: bool,
    ) -> AudioResult:
        logger.info(
            "[Wan2GP Audio] Local chunked synthesis enabled: chunks=%s pause_ms=%s crossfade_ms=%s keep_artifacts=%s",
            len(chunk_texts),
            pause_ms,
            crossfade_ms,
            keep_artifacts,
        )
        logger.info("[Wan2GP Audio] Local chunk details begin")
        resolved_split_strategy = _normalize_split_strategy(split_strategy)
        anchor_enabled = (
            resolved_split_strategy == WAN2GP_SPLIT_STRATEGY_ANCHOR_TAIL and len(chunk_texts) > 1
        )
        tail_detect_enabled = resolved_split_strategy == WAN2GP_SPLIT_STRATEGY_ANCHOR_TAIL
        chunk_anchor_flags: list[bool] = []
        for idx, chunk_text in enumerate(chunk_texts):
            compact = re.sub(r"\s+", "", chunk_text or "")
            preview_head = self._chunk_preview(chunk_text)
            preview_tail = self._chunk_preview(
                (chunk_text or "")[-WAN2GP_LOCAL_CHUNK_LOG_PREVIEW_CHARS:]
            )
            use_anchor = anchor_enabled
            chunk_anchor_flags.append(use_anchor)
            logger.info(
                '[Wan2GP Audio][ShotPlan] idx=%s/%s chars=%s anchor=%s head="%s" tail="%s"',
                idx + 1,
                len(chunk_texts),
                len(compact),
                use_anchor,
                preview_head,
                preview_tail,
            )
        logger.info("[Wan2GP Audio] Local chunk details end")
        with tempfile.TemporaryDirectory(prefix="wan2gp_local_chunks_") as tmp_dir_text:
            tmp_dir = Path(tmp_dir_text)
            tasks: list[Wan2GPAudioBatchTask] = []
            task_order: dict[str, int] = {}
            for idx, chunk_text in enumerate(chunk_texts):
                task_id = str(idx)
                task_order[task_id] = idx
                synth_text = (
                    self._build_anchor_appended_text(chunk_text)
                    if chunk_anchor_flags[idx]
                    else chunk_text
                )
                tasks.append(
                    Wan2GPAudioBatchTask(
                        task_id=task_id,
                        text=synth_text,
                        output_path=tmp_dir / f"chunk_{idx:04d}.wav",
                        preset=str(audio_config["preset_name"]),
                        model_mode=str(audio_config["model_mode"]),
                        alt_prompt=str(audio_config["alt_prompt"]),
                        duration_seconds=int(audio_config["duration_seconds"]),
                        temperature=float(audio_config["temperature"]),
                        top_k=int(audio_config["top_k"]),
                        seed=int(audio_config["seed"]),
                        audio_guide=str(audio_config["audio_guide"]),
                        speed=1.0,
                        split_strategy=resolved_split_strategy,
                        sentence_split_every_seconds=0.0,
                        anchor_split_every_seconds=0.0,
                        auto_duration_buffer_seconds=int(
                            audio_config["auto_duration_buffer_seconds"]
                        ),
                        auto_duration_max_seconds=int(audio_config["auto_duration_max_seconds"]),
                    )
                )
            anchor_task_id = "__anchor_ref__"
            if anchor_enabled:
                task_order[anchor_task_id] = len(chunk_texts)
                tasks.append(
                    Wan2GPAudioBatchTask(
                        task_id=anchor_task_id,
                        text=(
                            f"{WAN2GP_LOCAL_ANCHOR_PREFIX}"
                            f"{WAN2GP_LOCAL_ANCHOR_TEXT}"
                            f"{WAN2GP_LOCAL_ANCHOR_SUFFIX}"
                        ),
                        output_path=tmp_dir / "chunk_anchor_ref.wav",
                        preset=str(audio_config["preset_name"]),
                        model_mode=str(audio_config["model_mode"]),
                        alt_prompt=str(audio_config["alt_prompt"]),
                        duration_seconds=int(audio_config["duration_seconds"]),
                        temperature=float(audio_config["temperature"]),
                        top_k=int(audio_config["top_k"]),
                        seed=int(audio_config["seed"]),
                        audio_guide=str(audio_config["audio_guide"]),
                        speed=1.0,
                        split_strategy=resolved_split_strategy,
                        sentence_split_every_seconds=0.0,
                        anchor_split_every_seconds=0.0,
                        auto_duration_buffer_seconds=int(
                            audio_config["auto_duration_buffer_seconds"]
                        ),
                        auto_duration_max_seconds=int(audio_config["auto_duration_max_seconds"]),
                    )
                )

            last_overall = 0

            async def on_batch_progress(
                task_id: str, progress: int, _file_path: str | None
            ) -> None:
                nonlocal last_overall
                if not progress_callback:
                    return
                idx = task_order.get(str(task_id), 0)
                fraction = (float(idx) + (max(0, min(100, int(progress))) / 100.0)) / max(
                    1, len(tasks)
                )
                overall = max(1, min(99, int(round(fraction * 99.0))))
                if overall <= last_overall:
                    return
                last_overall = overall
                try:
                    await progress_callback(overall)
                except Exception:
                    pass

            batch_results = await self.generate_batch(
                tasks,
                progress_callback=on_batch_progress if progress_callback else None,
                status_callback=status_callback,
            )
            if len(batch_results) != len(tasks):
                raise RuntimeError(
                    "Wan2GP local chunked synthesis failed: incomplete chunk outputs "
                    f"(got={len(batch_results)} expected={len(tasks)})"
                )

            stitched_inputs: list[Path] = []
            first_suffix = ".wav"
            for idx in range(len(chunk_texts)):
                task_result = batch_results.get(str(idx))
                if task_result is None:
                    raise RuntimeError(f"Wan2GP local chunked synthesis missing chunk {idx}.")
                picked = Path(task_result.source_file_path or task_result.file_path)
                if not picked.exists():
                    raise FileNotFoundError(
                        f"Wan2GP local chunked synthesis chunk not found: {picked}"
                    )
                stitched_inputs.append(picked)
                if idx == 0:
                    first_suffix = picked.suffix or ".wav"

            anchor_ref_duration_seconds = 0.0
            if anchor_enabled:
                anchor_ref_result = batch_results.get(anchor_task_id)
                if anchor_ref_result:
                    anchor_ref_file = Path(
                        anchor_ref_result.source_file_path or anchor_ref_result.file_path
                    )
                    anchor_ref_duration_seconds, _ = await self._probe_audio_metadata(
                        anchor_ref_file
                    )
                if anchor_ref_duration_seconds <= 0:
                    anchor_ref_duration_seconds = float(
                        self._estimate_total_seconds_from_text(
                            f"{WAN2GP_LOCAL_ANCHOR_PREFIX}"
                            f"{WAN2GP_LOCAL_ANCHOR_TEXT}"
                            f"{WAN2GP_LOCAL_ANCHOR_SUFFIX}"
                        )
                    )
                logger.info(
                    '[Wan2GP Audio][AnchorRef] mode=single_task duration=%.3fs text="%s%s%s"',
                    anchor_ref_duration_seconds,
                    WAN2GP_LOCAL_ANCHOR_PREFIX,
                    WAN2GP_LOCAL_ANCHOR_TEXT,
                    WAN2GP_LOCAL_ANCHOR_SUFFIX,
                )

            processed_inputs: list[Path] = []
            boundary_pause_ms_list: list[int] = []
            for idx, source_path in enumerate(stitched_inputs):
                effective_path = source_path
                trailing_ms = 0
                if anchor_enabled and chunk_anchor_flags[idx]:
                    (
                        pre_duration_seconds,
                        trim_to_seconds,
                        boundary_search_start_seconds,
                        boundary_gap_seconds,
                        boundary_noise_db,
                    ) = await self._find_anchor_boundary_by_silence(
                        file_path=effective_path,
                        anchor_duration_seconds=anchor_ref_duration_seconds,
                    )
                    trim_reason = (
                        "relative_gap" if boundary_gap_seconds > 0 else "relative_window_start"
                    )
                    if trim_to_seconds < pre_duration_seconds:
                        anchor_trimmed_path = (
                            tmp_dir / f"{effective_path.stem}.anchortrim{effective_path.suffix}"
                        )
                        effective_path = await self._trim_audio_to_duration(
                            input_path=effective_path,
                            output_path=anchor_trimmed_path,
                            end_seconds=trim_to_seconds,
                        )
                    logger.info(
                        (
                            "[Wan2GP Audio][AnchorTrim] idx=%s/%s "
                            "reason=%s duration=%.3fs gap=%.3fs noise=%.1fdB search_from=%.3fs keep_until=%.3fs"
                        ),
                        idx + 1,
                        len(stitched_inputs),
                        trim_reason,
                        pre_duration_seconds,
                        boundary_gap_seconds,
                        boundary_noise_db,
                        boundary_search_start_seconds,
                        trim_to_seconds,
                    )
                if tail_detect_enabled:
                    duration_seconds, trailing_seconds = await self._detect_trailing_silence(
                        effective_path
                    )
                    trailing_ms = int(round(trailing_seconds * 1000.0))
                    if duration_seconds > 0 and trailing_ms > WAN2GP_MAX_TAIL_SILENCE_MS:
                        keep_tail_ms = WAN2GP_TARGET_TAIL_SILENCE_MS
                        trim_seconds = max(
                            0.01,
                            duration_seconds - ((trailing_ms - keep_tail_ms) / 1000.0),
                        )
                        trimmed_path = (
                            tmp_dir / f"{effective_path.stem}.tailtrim{effective_path.suffix}"
                        )
                        effective_path = await self._trim_audio_to_duration(
                            input_path=effective_path,
                            output_path=trimmed_path,
                            end_seconds=trim_seconds,
                        )
                        trailing_ms = keep_tail_ms
                    logger.info(
                        "[Wan2GP Audio][TailDetect] idx=%s/%s file=%s trailing=%sms",
                        idx + 1,
                        len(stitched_inputs),
                        effective_path,
                        trailing_ms,
                    )
                processed_inputs.append(effective_path)
                if idx < len(stitched_inputs) - 1:
                    dynamic_pause_ms = int(
                        max(pause_ms, WAN2GP_TARGET_TAIL_SILENCE_MS - trailing_ms)
                    )
                    dynamic_pause_ms = min(WAN2GP_LOCAL_STITCH_MAX_GAP_MS, dynamic_pause_ms)
                    boundary_pause_ms_list.append(dynamic_pause_ms)

            if keep_artifacts:
                artifact_dir = output_path.parent / (
                    f"{output_path.stem}.local_chunks_{int(time.time() * 1000)}"
                )
                raw_dir = artifact_dir / "raw_chunks"
                stitched_dir = artifact_dir / "stitched_inputs"
                raw_dir.mkdir(parents=True, exist_ok=True)
                stitched_dir.mkdir(parents=True, exist_ok=True)
                for idx, raw_path in enumerate(stitched_inputs):
                    raw_copy = raw_dir / f"chunk_{idx + 1:03d}_raw{raw_path.suffix.lower()}"
                    shutil.copy2(str(raw_path), str(raw_copy))
                for idx, stitched_path in enumerate(processed_inputs):
                    stitched_copy = (
                        stitched_dir / f"chunk_{idx + 1:03d}_stitched{stitched_path.suffix.lower()}"
                    )
                    shutil.copy2(str(stitched_path), str(stitched_copy))
                manifest = {
                    "chunks": len(stitched_inputs),
                    "raw_chunks_dir": str(raw_dir),
                    "stitched_inputs_dir": str(stitched_dir),
                    "anchor_enabled": anchor_enabled,
                    "pause_ms": pause_ms,
                    "crossfade_ms": crossfade_ms,
                    "kept_at": int(time.time() * 1000),
                }
                (artifact_dir / "manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                logger.info(
                    "[Wan2GP Audio][LocalArtifacts] kept raw+stitched chunk files at: %s",
                    artifact_dir,
                )

            merged_raw_path = tmp_dir / f"merged_local_raw{first_suffix.lower()}"
            await self._stitch_local_chunks(
                chunk_paths=processed_inputs,
                output_path=merged_raw_path,
                pause_ms=pause_ms,
                crossfade_ms=crossfade_ms,
                boundary_pause_ms_list=boundary_pause_ms_list,
            )

            final_output_path, raw_output_path = self._resolve_output_and_raw_paths(
                output_path=output_path,
                source_suffix=first_suffix,
                runtime_raw_output_path=runtime_raw_output_path,
            )
            raw_output_path.parent.mkdir(parents=True, exist_ok=True)
            if raw_output_path.exists():
                raw_output_path.unlink()
            shutil.move(str(merged_raw_path), str(raw_output_path))

            rendered = await self.render_from_raw(
                source_file_path=raw_output_path,
                output_path=final_output_path,
                speed=float(audio_config["speed"]),
            )
            if progress_callback:
                try:
                    await progress_callback(100)
                except Exception:
                    pass
            return rendered

    async def _generate_batch_via_synthesize(
        self,
        tasks: list[Wan2GPAudioBatchTask],
        progress_callback: Callable[[str, int, str | None], Awaitable[None]] | None = None,
        status_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> dict[str, AudioResult]:
        results: dict[str, AudioResult] = {}
        for task in tasks:
            task_id = str(task.task_id)

            async def per_task_progress(progress: int, _task_id: str = task_id) -> None:
                if not progress_callback:
                    return
                try:
                    await progress_callback(_task_id, max(0, min(100, int(progress))), None)
                except Exception:
                    pass

            result = await self.synthesize(
                text=str(task.text or ""),
                output_path=Path(task.output_path),
                preset=str(task.preset or ""),
                model_mode=str(task.model_mode or ""),
                alt_prompt=task.alt_prompt,
                duration_seconds=task.duration_seconds,
                temperature=task.temperature,
                top_k=task.top_k,
                seed=task.seed,
                audio_guide=task.audio_guide,
                speed=task.speed,
                split_strategy=task.split_strategy,
                auto_duration_buffer_seconds=task.auto_duration_buffer_seconds,
                auto_duration_max_seconds=task.auto_duration_max_seconds,
                local_stitch=task.local_stitch,
                local_stitch_pause_ms=task.local_stitch_pause_ms,
                local_stitch_crossfade_ms=task.local_stitch_crossfade_ms,
                local_stitch_keep_artifacts=task.local_stitch_keep_artifacts,
                progress_callback=per_task_progress,
                status_callback=status_callback,
            )
            results[task_id] = result
            if progress_callback:
                try:
                    await progress_callback(task_id, 100, str(result.file_path))
                except Exception:
                    pass
        return results

    @staticmethod
    def _resolve_audio_guide_path(audio_guide: str) -> Path | None:
        normalized = str(audio_guide or "").strip()
        if not normalized:
            return None

        resolved_for_io = resolve_path_for_io(normalized)
        if resolved_for_io is not None:
            return resolved_for_io if resolved_for_io.is_file() else None

        candidate = Path(normalized).expanduser()
        if candidate.is_absolute():
            return candidate if candidate.is_file() else None

        search_roots = [Path.cwd(), REPO_ROOT, BACKEND_ROOT]
        for root in search_roots:
            resolved = (root / candidate).resolve()
            if resolved.is_file():
                return resolved
        return None

    async def _run_wgp(
        self,
        *,
        python_executable: str,
        settings_path: Path,
        output_dir: Path,
        estimated_total_seconds: int | None = None,
        progress_callback: Callable[[int], Awaitable[None]] | None = None,
        status_callback: Callable[[str], Awaitable[None]] | None = None,
        line_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> list[str]:
        cmd = [
            python_executable,
            "-u",
            str(self.wan2gp_path / "wgp.py"),
            "--process",
            str(settings_path),
            "--output-dir",
            str(output_dir),
            "--verbose",
            "1",
        ]
        cmd_text = " ".join(shlex.quote(part) for part in cmd)
        logger.info("[Wan2GP Audio] Start subprocess: %s", cmd_text)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self.wan2gp_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=(os.name != "nt"),
            env={
                **os.environ,
                "PYTHONUNBUFFERED": "1",
                # Force HF/tqdm progress output in subprocess logs when possible.
                "HF_HUB_DISABLE_PROGRESS_BARS": "0",
                "HF_HUB_ENABLE_HF_TRANSFER": "0",
                "HF_HUB_VERBOSITY": "info",
                "TQDM_DISABLE": "0",
                # huggingface_hub uses tqdm(disable=is_tqdm_disabled(...)); set this to force disable=False.
                "TQDM_POSITION": "-1",
            },
        )
        register_wan2gp_pid(process.pid)

        step_pattern = re.compile(r"(?:Step\s+)?(\d+)\s*/\s*(\d+)")
        second_pattern = re.compile(r"(\d+)\s*s\s*/\s*(\d+)\s*s")
        qwen_percent_pattern = re.compile(
            r"qwen3\s*tts\s*:\s*(\d{1,3})%\|.*\|\s*\d+\s*/\s*\d+\s*\[",
            re.IGNORECASE,
        )
        ansi_escape_pattern = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
        output_tail: deque[str] = deque(maxlen=60)
        last_progress = 0
        last_status_message: str | None = None
        pending = ""

        async def emit_status(message: str) -> None:
            nonlocal last_status_message
            if not status_callback or not message:
                return
            if message == last_status_message:
                return
            last_status_message = message
            try:
                await status_callback(message)
            except Exception:
                pass

        async def emit_progress(value: int) -> None:
            nonlocal last_progress
            if progress_callback is None:
                return
            value = max(1, min(99, int(value)))
            if value <= last_progress:
                return
            last_progress = value
            await emit_status(STATUS_GENERATING)
            try:
                await progress_callback(value)
            except Exception:
                pass

        try:
            stdout = process.stdout
            if stdout is not None:
                while True:
                    chunk = await stdout.read(4096)
                    if not chunk:
                        break
                    pending += chunk.decode(errors="ignore")
                    chunks = re.split(r"[\r\n]+", pending)
                    pending = chunks.pop() if chunks else ""

                    for chunk in chunks:
                        cleaned = ansi_escape_pattern.sub("", chunk).strip()
                        if not cleaned:
                            continue
                        output_tail.append(cleaned)
                        logger.info("[Wan2GP Audio] %s", cleaned)
                        if line_callback:
                            try:
                                await line_callback(cleaned)
                            except Exception:
                                pass

                        runtime_status = self._infer_runtime_status_message(cleaned)
                        if runtime_status:
                            await emit_status(runtime_status)

                        lowered = cleaned.lower()
                        generation_hints = (
                            "encoding prompt",
                            "generate()",
                            ".generate(",
                            "sampling",
                            "inference",
                            "infer ",
                        )
                        loading_hints = (
                            "downloading",
                            "download ",
                            "loading model",
                            "model loaded",
                            "moving file to",
                            "loading text encoder",
                            "loading vae",
                            "loading transformer",
                        )
                        if any(hint in lowered for hint in generation_hints) and not any(
                            hint in lowered for hint in loading_hints
                        ):
                            await emit_status(STATUS_GENERATING)

                        # Only treat "x / y" as inference progress under clear generation context.
                        # This avoids misclassifying download resume logs like "2537553920/3857413744"
                        # as generation progress.
                        has_inference_progress_context = (
                            "denoising" in lowered
                            or "qwen3 tts" in lowered
                            or "step " in lowered
                            or "sampling" in lowered
                            or "vae decoding" in lowered
                        )
                        for match in step_pattern.finditer(cleaned):
                            current_step = int(match.group(1))
                            total_steps = int(match.group(2))
                            if total_steps <= 0:
                                continue
                            # 跳过类似 “[Task 1/1] ready” 的任务计数日志，避免误判为推理进度 99%。
                            if total_steps <= 1:
                                continue
                            if "task " in lowered or lowered.startswith("[task"):
                                continue
                            if not has_inference_progress_context:
                                continue
                            denominator = total_steps
                            numerator = current_step
                            if (
                                estimated_total_seconds
                                and estimated_total_seconds > 0
                                and ("denoising" in lowered or "qwen3 tts" in lowered)
                            ):
                                denominator = estimated_total_seconds
                            numerator = max(0, min(numerator, denominator))
                            progress = int((numerator / denominator) * 99)
                            await emit_progress(progress)

                        for match in second_pattern.finditer(cleaned):
                            current_second = int(match.group(1))
                            total_second = int(match.group(2))
                            if total_second <= 0:
                                continue
                            denominator = (
                                estimated_total_seconds
                                if estimated_total_seconds and estimated_total_seconds > 0
                                else total_second
                            )
                            current_second = max(0, min(current_second, denominator))
                            progress = int((current_second / denominator) * 99)
                            await emit_progress(progress)

                        qwen_percent_match = qwen_percent_pattern.search(cleaned)
                        if qwen_percent_match and not (
                            estimated_total_seconds and estimated_total_seconds > 0
                        ):
                            progress = _to_int(qwen_percent_match.group(1), 0)
                            await emit_progress(progress)

                if pending.strip():
                    cleaned = ansi_escape_pattern.sub("", pending).strip()
                    output_tail.append(cleaned)
                    logger.info("[Wan2GP Audio] %s", cleaned)
                    if line_callback:
                        try:
                            await line_callback(cleaned)
                        except Exception:
                            pass
                    runtime_status = self._infer_runtime_status_message(cleaned)
                    if runtime_status:
                        await emit_status(runtime_status)

            return_code = await process.wait()
            if return_code != 0:
                tail_text = (
                    "\n".join(output_tail) if output_tail else "<no subprocess output captured>"
                )
                raise RuntimeError(
                    "Wan2GP audio generation failed with return code "
                    f"{return_code}\nCommand: {cmd_text}\nLast output lines:\n{tail_text}"
                )
            return list(output_tail)
        finally:
            if process.returncode is None:
                terminate_pid_tree(process.pid, grace_seconds=2.0)
                try:
                    await asyncio.wait_for(process.wait(), timeout=3.0)
                except Exception:
                    pass
            unregister_wan2gp_pid(process.pid)

    @staticmethod
    async def _probe_audio_metadata(file_path: Path) -> tuple[float, int]:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate,duration:format=duration",
            "-of",
            "json",
            str(file_path),
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            if process.returncode != 0:
                return 0.0, 24000
            payload = json.loads(stdout.decode(errors="ignore") or "{}")
            streams = payload.get("streams") or []
            stream0 = streams[0] if isinstance(streams, list) and streams else {}
            format_info = payload.get("format") if isinstance(payload.get("format"), dict) else {}

            duration = _to_float(stream0.get("duration"), 0.0)
            if duration <= 0:
                duration = _to_float(format_info.get("duration"), 0.0)
            sample_rate = _to_int(stream0.get("sample_rate"), 24000)
            if sample_rate <= 0:
                sample_rate = 24000
            return max(0.0, duration), sample_rate
        except Exception:
            return 0.0, 24000

    async def _apply_speed_adjustment(self, file_path: Path, speed: float) -> None:
        normalized_speed = _normalize_speed(speed, 1.0)
        if abs(normalized_speed - 1.0) < 1e-3:
            logger.info(
                "[Wan2GP Audio] Speed adjustment skipped: speed=%.2fx file=%s",
                normalized_speed,
                file_path,
            )
            return
        if not file_path.exists():
            raise FileNotFoundError(f"Audio file not found for speed adjustment: {file_path}")

        factors: list[float] = []
        remaining = normalized_speed
        while remaining > 2.0:
            factors.append(2.0)
            remaining /= 2.0
        while remaining < 0.5:
            factors.append(0.5)
            remaining /= 0.5
        factors.append(remaining)
        filter_expr = ",".join(f"atempo={factor:.6f}" for factor in factors)

        tmp_path = file_path.with_name(f"{file_path.stem}.speed_tmp{file_path.suffix}")
        logger.info(
            "[Wan2GP Audio] Speed adjustment start: speed=%.2fx filter=%s input=%s output=%s",
            normalized_speed,
            filter_expr,
            file_path,
            tmp_path,
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(file_path),
            "-filter:a",
            filter_expr,
            "-vn",
            str(tmp_path),
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await process.communicate()
            if process.returncode != 0 or not tmp_path.exists():
                error_text = stderr.decode(errors="ignore").strip()
                raise RuntimeError(
                    "Wan2GP speed adjustment failed "
                    f"(speed={normalized_speed:.3f}, filter={filter_expr}): {error_text}"
                )
            shutil.move(str(tmp_path), str(file_path))
            logger.info(
                "[Wan2GP Audio] Speed adjustment done: speed=%.2fx file=%s",
                normalized_speed,
                file_path,
            )
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    async def render_from_raw(
        self,
        *,
        source_file_path: Path,
        output_path: Path,
        speed: float,
    ) -> AudioResult:
        if not source_file_path.exists():
            raise FileNotFoundError(f"Wan2GP raw audio not found: {source_file_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            output_path.unlink()
        shutil.copy2(str(source_file_path), str(output_path))
        logger.info(
            "[Wan2GP Audio] Render from raw: raw=%s output=%s speed=%.2fx",
            source_file_path,
            output_path,
            _normalize_speed(speed, 1.0),
        )
        await self._apply_speed_adjustment(output_path, speed)
        duration, sample_rate = await self._probe_audio_metadata(output_path)
        logger.info(
            "[Wan2GP Audio] Render output metadata: output=%s duration=%.3fs sample_rate=%s",
            output_path,
            duration,
            sample_rate,
        )
        return AudioResult(
            file_path=output_path,
            duration=duration,
            sample_rate=sample_rate,
            source_file_path=source_file_path,
        )

    async def synthesize(
        self,
        text: str,
        output_path: Path,
        voice: str | None = None,
        rate: str | None = None,
        **kwargs: Any,
    ) -> AudioResult:
        del voice, rate
        self._validate_config()
        python_executable = self._resolve_python_executable()

        runtime_preset = str(kwargs.get("preset") or "")
        runtime_model_mode = str(kwargs.get("model_mode") or "")
        runtime_alt_prompt = kwargs.get("alt_prompt")
        runtime_duration_seconds = kwargs.get("duration_seconds")
        runtime_temperature = kwargs.get("temperature")
        runtime_top_k = kwargs.get("top_k")
        runtime_seed = kwargs.get("seed")
        runtime_audio_guide = kwargs.get("audio_guide")
        runtime_speed = kwargs.get("speed")
        runtime_split_strategy = kwargs.get("split_strategy")
        runtime_auto_duration_buffer_seconds = kwargs.get("auto_duration_buffer_seconds")
        runtime_auto_duration_max_seconds = kwargs.get("auto_duration_max_seconds")
        runtime_raw_output_path = kwargs.get("raw_output_path")
        runtime_local_stitch = kwargs.get("local_stitch")
        runtime_local_pause_ms = kwargs.get("local_stitch_pause_ms")
        runtime_local_crossfade_ms = kwargs.get("local_stitch_crossfade_ms")
        runtime_local_keep_artifacts = kwargs.get("local_stitch_keep_artifacts")

        progress_callback = kwargs.get("progress_callback")
        if not callable(progress_callback):
            progress_callback = None
        status_callback = kwargs.get("status_callback")
        if not callable(status_callback):
            status_callback = None

        audio_config = self._get_audio_config(
            text=text,
            preset_name=runtime_preset,
            model_mode=runtime_model_mode,
            alt_prompt=runtime_alt_prompt,
            duration_seconds=runtime_duration_seconds,
            temperature=runtime_temperature,
            top_k=runtime_top_k,
            seed=runtime_seed,
            audio_guide=runtime_audio_guide,
            speed=runtime_speed,
            split_strategy=runtime_split_strategy,
            auto_duration_buffer_seconds=runtime_auto_duration_buffer_seconds,
            auto_duration_max_seconds=runtime_auto_duration_max_seconds,
        )

        if audio_config["supports_reference_audio"]:
            audio_guide = str(audio_config["audio_guide"]).strip()
            if not audio_guide:
                raise ValueError("Wan2GP Qwen3 Base 需要参考音频（audio_wan2gp_audio_guide）。")
            resolved_audio_guide_path = self._resolve_audio_guide_path(audio_guide)
            if not resolved_audio_guide_path:
                raise ValueError(f"Wan2GP 参考音频不存在: {audio_guide}")
            audio_config["audio_guide"] = str(resolved_audio_guide_path)

        local_stitch_enabled = _to_bool(
            runtime_local_stitch,
            WAN2GP_LOCAL_STITCH_DEFAULT_ENABLED,
        )
        local_pause_ms = max(
            0,
            min(
                WAN2GP_LOCAL_STITCH_MAX_GAP_MS,
                _normalize_non_negative_int(
                    runtime_local_pause_ms,
                    WAN2GP_LOCAL_STITCH_DEFAULT_PAUSE_MS,
                ),
            ),
        )
        local_crossfade_ms = max(
            0,
            min(
                WAN2GP_LOCAL_STITCH_MAX_GAP_MS,
                _normalize_non_negative_int(
                    runtime_local_crossfade_ms,
                    WAN2GP_LOCAL_STITCH_DEFAULT_CROSSFADE_MS,
                ),
            ),
        )
        local_keep_artifacts = _to_bool(
            runtime_local_keep_artifacts,
            WAN2GP_LOCAL_CHUNK_KEEP_ARTIFACTS_DEFAULT,
        )
        split_strategy = _normalize_split_strategy(audio_config.get("split_strategy"))
        split_mode_label = (
            "anchor_long"
            if split_strategy == WAN2GP_SPLIT_STRATEGY_ANCHOR_TAIL
            else "sentence_forced"
        )
        prepared_text, manual_chunk_count = self._prepare_text_for_local_split(
            text,
            split_strategy=split_strategy,
        )
        prepared_chunks = self._extract_manual_chunks(prepared_text)
        if local_stitch_enabled and len(prepared_chunks) > 1:
            return await self._synthesize_with_local_chunks(
                chunk_texts=prepared_chunks,
                split_strategy=split_strategy,
                output_path=output_path,
                runtime_raw_output_path=runtime_raw_output_path,
                audio_config=audio_config,
                progress_callback=progress_callback,
                status_callback=status_callback,
                pause_ms=local_pause_ms,
                crossfade_ms=local_crossfade_ms,
                keep_artifacts=local_keep_artifacts,
            )

        settings_payload = self._build_settings_payload(
            text=prepared_text,
            audio_config=audio_config,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_dir = output_path.parent
        settings_path = self.wan2gp_path / (
            f"_settings_aud_{os.getpid()}_{int(time.time() * 1000)}_{output_path.stem}.json"
        )
        model_cached = self._is_model_cached(str(audio_config["model_type"]))
        await emit_bootstrap_status(status_callback, model_cached)

        text_compact = re.sub(r"\s+", "", prepared_text or "")
        estimated_total_seconds = self._estimate_total_seconds_from_text(prepared_text)

        try:
            settings_path.write_text(
                json.dumps(settings_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            split_target_window = (
                WAN2GP_ANCHOR_TAIL_TARGET_WINDOW_CHARS
                if split_strategy == WAN2GP_SPLIT_STRATEGY_ANCHOR_TAIL
                else WAN2GP_SENTENCE_PUNCT_TARGET_WINDOW_CHARS
            )
            split_extend_window = (
                WAN2GP_ANCHOR_TAIL_EXTEND_WINDOW_CHARS
                if split_strategy == WAN2GP_SPLIT_STRATEGY_ANCHOR_TAIL
                else WAN2GP_SENTENCE_PUNCT_EXTEND_WINDOW_CHARS
            )
            logger.info(
                "[Wan2GP Audio] preset=%s mode=%s duration=%ss requested=%ss estimated=%ss auto_raised=%s split_strategy=%s split_mode=%s split_window_target=%s split_window_extend=%s manual_chunks=%s top_k=%s temperature=%.2f speed=%.2fx",
                audio_config["preset_name"],
                audio_config["model_mode"],
                audio_config["duration_seconds"],
                audio_config["requested_duration_seconds"],
                audio_config["estimated_duration_seconds"],
                bool(audio_config["auto_duration_applied"]),
                split_strategy,
                split_mode_label,
                split_target_window,
                split_extend_window,
                manual_chunk_count,
                audio_config["top_k"],
                float(audio_config["temperature"]),
                float(audio_config["speed"]),
            )
            if manual_chunk_count > 1:
                logger.info(
                    "[Wan2GP Audio] Applied LocalVideo local pre-split before synthesis: chunks=%s",
                    manual_chunk_count,
                )
            logger.info(
                "[Wan2GP Audio] Progress denominator estimated from text length: %ss (chars=%s)",
                estimated_total_seconds,
                len(text_compact),
            )
            start_time = time.time()
            output_tail = await self._run_wgp(
                python_executable=python_executable,
                settings_path=settings_path,
                output_dir=output_dir,
                estimated_total_seconds=estimated_total_seconds,
                progress_callback=progress_callback,
                status_callback=status_callback,
            )

            generated = [
                path
                for path in output_dir.iterdir()
                if path.is_file()
                and path.suffix.lower() in AUDIO_OUTPUT_EXTENSIONS
                and path.stat().st_mtime >= start_time - 0.01
            ]
            if not generated:
                generated = [
                    path
                    for path in output_dir.iterdir()
                    if path.is_file() and path.suffix.lower() in AUDIO_OUTPUT_EXTENSIONS
                ]
            if not generated:
                tail_text = (
                    "\n".join(output_tail[-12:])
                    if output_tail
                    else "<no subprocess output captured>"
                )
                raise FileNotFoundError(
                    "Wan2GP did not output any audio file.\n"
                    f"Output dir: {output_dir}\n"
                    f"Last output lines:\n{tail_text}"
                )

            latest = max(generated, key=lambda p: p.stat().st_mtime)
            final_output_path, raw_output_path = self._resolve_output_and_raw_paths(
                output_path=output_path,
                source_suffix=latest.suffix,
                runtime_raw_output_path=runtime_raw_output_path,
            )
            raw_output_path.parent.mkdir(parents=True, exist_ok=True)
            if raw_output_path.exists():
                raw_output_path.unlink()
            if latest.resolve() != raw_output_path.resolve():
                shutil.move(str(latest), str(raw_output_path))

            rendered = await self.render_from_raw(
                source_file_path=raw_output_path,
                output_path=final_output_path,
                speed=float(audio_config["speed"]),
            )

            if progress_callback:
                try:
                    await progress_callback(100)
                except Exception:
                    pass

            return rendered
        finally:
            if settings_path.exists():
                settings_path.unlink()

    async def generate_batch(
        self,
        tasks: list[Wan2GPAudioBatchTask],
        progress_callback: Callable[[str, int, str | None], Awaitable[None]] | None = None,
        status_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> dict[str, AudioResult]:
        if not tasks:
            return {}

        self._validate_config()
        python_executable = self._resolve_python_executable()

        # If any task needs local chunked stitching, switch to per-task synthesize path.
        # This guarantees visible chunk-plan logs and keeps stitching fully local.
        for task in tasks:
            task_text = str(task.text or "")
            if not task_text.strip():
                continue
            audio_config_probe = self._get_audio_config(
                text=task_text,
                preset_name=str(task.preset or ""),
                model_mode=str(task.model_mode or ""),
                alt_prompt=task.alt_prompt,
                duration_seconds=task.duration_seconds,
                temperature=task.temperature,
                top_k=task.top_k,
                seed=task.seed,
                audio_guide=task.audio_guide,
                speed=task.speed,
                split_strategy=task.split_strategy,
                auto_duration_buffer_seconds=task.auto_duration_buffer_seconds,
                auto_duration_max_seconds=task.auto_duration_max_seconds,
            )
            local_stitch_enabled = _to_bool(
                task.local_stitch,
                WAN2GP_LOCAL_STITCH_DEFAULT_ENABLED,
            )
            split_strategy = _normalize_split_strategy(audio_config_probe.get("split_strategy"))
            prepared_text_probe, _ = self._prepare_text_for_local_split(
                task_text,
                split_strategy=split_strategy,
            )
            prepared_chunks_probe = self._extract_manual_chunks(prepared_text_probe)
            if local_stitch_enabled and len(prepared_chunks_probe) > 1:
                logger.info(
                    "[Wan2GP Audio][Batch] local chunked stitching detected; switching to per-task synthesize path"
                )
                return await self._generate_batch_via_synthesize(
                    tasks,
                    progress_callback=progress_callback,
                    status_callback=status_callback,
                )

        output_dir = Path(tempfile.mkdtemp(prefix="wan2gp_aud_batch_out_"))
        settings_path = self.wan2gp_path / (
            f"_settings_aud_batch_{os.getpid()}_{int(time.time() * 1000)}.json"
        )
        payloads: list[dict[str, Any]] = []
        task_info: dict[str, tuple[str, Path]] = {}
        task_estimated_seconds: dict[str, int] = {}
        current_task_idx = -1
        completed_task_ids: set[str] = set()
        assigned_source_paths: set[Path] = set()
        results: dict[str, AudioResult] = {}

        async def emit_progress(task_id: str, progress: int, file_path: str | None = None) -> None:
            if not progress_callback:
                return
            try:
                await progress_callback(task_id, max(0, min(100, int(progress))), file_path)
            except Exception:
                pass

        def collect_generated_paths() -> list[Path]:
            return [
                path
                for path in output_dir.rglob("*")
                if path.is_file() and path.suffix.lower() in AUDIO_OUTPUT_EXTENSIONS
            ]

        async def assign_result_for_task(
            task_id: str, candidates: list[Path]
        ) -> AudioResult | None:
            if task_id in results:
                return results[task_id]

            task_meta = task_info.get(task_id)
            if task_meta is None:
                return None
            output_key, output_path = task_meta
            matched = [
                path
                for path in candidates
                if path not in assigned_source_paths
                and (path.stem == output_key or path.stem.startswith(f"{output_key}_"))
            ]
            if not matched:
                return None

            picked = max(matched, key=lambda p: p.stat().st_mtime)
            assigned_source_paths.add(picked)
            target_path = output_path.with_suffix(picked.suffix.lower())
            raw_target_path = target_path.with_name(f"{target_path.stem}.raw{target_path.suffix}")
            if raw_target_path.exists():
                raw_target_path.unlink()
            if picked.resolve() != raw_target_path.resolve():
                shutil.move(str(picked), str(raw_target_path))
            task_speed = 1.0
            for task in tasks:
                if str(task.task_id) == task_id:
                    task_speed = _normalize_speed(task.speed, 1.0)
                    break
            result = await self.render_from_raw(
                source_file_path=raw_target_path,
                output_path=target_path,
                speed=task_speed,
            )
            results[task_id] = result
            return result

        task_start_pattern = re.compile(r"\[Task\s+(\d+)\s*/\s*(\d+)\]", re.IGNORECASE)
        task_done_pattern = re.compile(r"Task\s+(\d+)\s+completed", re.IGNORECASE)
        step_pattern = re.compile(r"(?:Step\s+)?(\d+)\s*/\s*(\d+)")
        second_pattern = re.compile(r"(\d+)\s*s\s*/\s*(\d+)\s*s")
        qwen_percent_pattern = re.compile(r"qwen3\s*tts.*?(\d{1,3})%", re.IGNORECASE)
        batch_model_cached: bool | None = None

        try:
            for i, task in enumerate(tasks):
                task_id = str(task.task_id)
                task_text = str(task.text or "")
                if not task_text:
                    raise ValueError(f"Wan2GP batch task text is empty (task_id={task_id})")

                audio_config = self._get_audio_config(
                    text=task_text,
                    preset_name=str(task.preset or ""),
                    model_mode=str(task.model_mode or ""),
                    alt_prompt=task.alt_prompt,
                    duration_seconds=task.duration_seconds,
                    temperature=task.temperature,
                    top_k=task.top_k,
                    seed=task.seed,
                    audio_guide=task.audio_guide,
                    speed=task.speed,
                    split_strategy=task.split_strategy,
                    auto_duration_buffer_seconds=task.auto_duration_buffer_seconds,
                    auto_duration_max_seconds=task.auto_duration_max_seconds,
                )
                split_strategy = _normalize_split_strategy(audio_config.get("split_strategy"))
                split_mode_label = (
                    "anchor_long"
                    if split_strategy == WAN2GP_SPLIT_STRATEGY_ANCHOR_TAIL
                    else "sentence_forced"
                )
                prepared_task_text, manual_chunk_count = self._prepare_text_for_local_split(
                    task_text,
                    split_strategy=split_strategy,
                )
                if batch_model_cached is None:
                    batch_model_cached = self._is_model_cached(str(audio_config["model_type"]))
                if audio_config["supports_reference_audio"]:
                    audio_guide = str(audio_config["audio_guide"]).strip()
                    if not audio_guide:
                        raise ValueError(
                            "Wan2GP Qwen3 Base 需要参考音频（audio_wan2gp_audio_guide）。"
                        )
                    resolved_audio_guide_path = self._resolve_audio_guide_path(audio_guide)
                    if not resolved_audio_guide_path:
                        raise ValueError(f"Wan2GP 参考音频不存在: {audio_guide}")
                    audio_config["audio_guide"] = str(resolved_audio_guide_path)

                output_key = f"yf_batch_aud_{i:04d}"
                output_path = Path(task.output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                task_info[task_id] = (output_key, output_path)
                task_estimated_seconds[task_id] = self._estimate_total_seconds_from_text(
                    prepared_task_text
                )
                payloads.append(
                    self._build_settings_payload(
                        text=prepared_task_text,
                        audio_config=audio_config,
                        output_filename=output_key,
                    )
                )
                split_target_window = (
                    WAN2GP_ANCHOR_TAIL_TARGET_WINDOW_CHARS
                    if split_strategy == WAN2GP_SPLIT_STRATEGY_ANCHOR_TAIL
                    else WAN2GP_SENTENCE_PUNCT_TARGET_WINDOW_CHARS
                )
                split_extend_window = (
                    WAN2GP_ANCHOR_TAIL_EXTEND_WINDOW_CHARS
                    if split_strategy == WAN2GP_SPLIT_STRATEGY_ANCHOR_TAIL
                    else WAN2GP_SENTENCE_PUNCT_EXTEND_WINDOW_CHARS
                )
                logger.info(
                    "[Wan2GP Audio][Batch] task=%s preset=%s mode=%s duration=%ss requested=%ss estimated=%ss auto_raised=%s split_strategy=%s split_mode=%s split_window_target=%s split_window_extend=%s manual_chunks=%s top_k=%s temperature=%.2f speed=%.2fx",
                    task_id,
                    audio_config["preset_name"],
                    audio_config["model_mode"],
                    audio_config["duration_seconds"],
                    audio_config["requested_duration_seconds"],
                    audio_config["estimated_duration_seconds"],
                    bool(audio_config["auto_duration_applied"]),
                    split_strategy,
                    split_mode_label,
                    split_target_window,
                    split_extend_window,
                    manual_chunk_count,
                    audio_config["top_k"],
                    float(audio_config["temperature"]),
                    float(audio_config["speed"]),
                )
                if manual_chunk_count > 1:
                    logger.info(
                        "[Wan2GP Audio][Batch] task=%s applied LocalVideo local pre-split: chunks=%s",
                        task_id,
                        manual_chunk_count,
                    )

            await emit_bootstrap_status(status_callback, batch_model_cached)

            settings_path.write_text(
                json.dumps(payloads, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            async def on_line(line: str) -> None:
                nonlocal current_task_idx
                start_match = task_start_pattern.search(line)
                if start_match:
                    task_no = int(start_match.group(1))
                    if 1 <= task_no <= len(tasks):
                        current_task_idx = task_no - 1
                    return

                done_match = task_done_pattern.search(line)
                if done_match:
                    task_no = int(done_match.group(1))
                    if 1 <= task_no <= len(tasks):
                        task_id = str(tasks[task_no - 1].task_id)
                        completed_task_ids.add(task_id)
                        result = await assign_result_for_task(task_id, collect_generated_paths())
                        await emit_progress(task_id, 100, str(result.file_path) if result else None)
                    return

                if not (0 <= current_task_idx < len(tasks)):
                    return
                task_id = str(tasks[current_task_idx].task_id)
                if task_id in completed_task_ids:
                    return

                lowered = line.lower()
                estimated_total_seconds = task_estimated_seconds.get(task_id)
                progress_values: list[int] = []
                for match in step_pattern.finditer(line):
                    current_step = int(match.group(1))
                    total_steps = int(match.group(2))
                    if total_steps <= 0:
                        continue
                    if total_steps <= 1:
                        continue
                    if "task " in lowered or lowered.startswith("[task"):
                        continue
                    denominator = total_steps
                    if estimated_total_seconds and (
                        "denoising" in lowered or "qwen3 tts" in lowered
                    ):
                        denominator = estimated_total_seconds
                    numerator = max(0, min(current_step, denominator))
                    progress_values.append(int((numerator / denominator) * 99))

                for match in second_pattern.finditer(line):
                    current_second = int(match.group(1))
                    total_second = int(match.group(2))
                    if total_second <= 0:
                        continue
                    denominator = (
                        estimated_total_seconds if estimated_total_seconds else total_second
                    )
                    current_second = max(0, min(current_second, denominator))
                    progress_values.append(int((current_second / denominator) * 99))

                if not progress_values and not estimated_total_seconds:
                    percent_match = qwen_percent_pattern.search(line)
                    if percent_match:
                        progress_values.append(_to_int(percent_match.group(1), 0))

                if progress_values:
                    await emit_progress(task_id, max(progress_values), None)
                    result = await assign_result_for_task(task_id, collect_generated_paths())
                    if result:
                        completed_task_ids.add(task_id)
                        await emit_progress(task_id, 100, str(result.file_path))

            output_tail = await self._run_wgp(
                python_executable=python_executable,
                settings_path=settings_path,
                output_dir=output_dir,
                progress_callback=None,
                status_callback=status_callback,
                line_callback=on_line,
            )

            all_generated = collect_generated_paths()
            if len(results) == len(tasks):
                return results
            if not all_generated and not results:
                tail_text = (
                    "\n".join(output_tail[-12:])
                    if output_tail
                    else "<no subprocess output captured>"
                )
                raise FileNotFoundError(
                    "Wan2GP batch audio run did not output any audio file.\n"
                    f"Output dir: {output_dir}\n"
                    f"Last output lines:\n{tail_text}"
                )

            for task in tasks:
                task_id = str(task.task_id)
                if task_id in results:
                    continue
                result = await assign_result_for_task(task_id, all_generated)
                if result:
                    completed_task_ids.add(task_id)
                    await emit_progress(task_id, 100, str(result.file_path))

            return results
        finally:
            if settings_path.exists():
                settings_path.unlink()
            if output_dir.exists():
                shutil.rmtree(output_dir, ignore_errors=True)

    def list_voices(self) -> list[str]:
        return [item["id"] for item in QWEN3_SPEAKER_MODES]
