"""Wan2GP local video provider."""

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

from app.providers.base.video import VideoProvider, VideoResult
from app.providers.wan2gp import (
    COMMON_RESOLUTIONS,
    STATUS_GENERATING,
    STATUS_MODEL_DOWNLOADING,
    STATUS_MODEL_LOADING,
    Wan2GPBase,
    detect_external_wan2gp_ui_processes,
    emit_bootstrap_status,
    register_wan2gp_pid,
    terminate_pid_tree,
    unregister_wan2gp_pid,
)

logger = logging.getLogger(__name__)

WAN2GP_VIDEO_SETTINGS_VERSION = 2.55
WAN2GP_RUNTIME_CONFIG_DEFAULTS: dict[str, Any] = {
    "attention_mode": "auto",
    "transformer_types": [],
    "transformer_quantization": "int8",
    "text_encoder_quantization": "int8",
    "save_path": "outputs",
    "image_save_path": "outputs",
    "compile": "",
    "metadata_type": "metadata",
    "boost": 1,
    "clear_file_list": 5,
    "enable_4k_resolutions": 0,
    "max_reserved_loras": -1,
    "vae_config": 0,
    "video_profile": 4,
    "image_profile": 4,
    "audio_profile": 3.5,
    "checkpoints_paths": ["ckpts", "."],
    "video_output_codec": "libx264_8",
    "video_container": "mp4",
    "image_output_codec": "jpeg_95",
    "embed_source_images": False,
    "audio_save_path": "outputs",
    "audio_output_codec": "aac_128",
    "audio_stand_alone_output_codec": "wav",
    "rife_version": "v4",
    "loras_root": "loras",
    "prompt_enhancer_temperature": 0.6,
    "prompt_enhancer_top_p": 0.9,
    "prompt_enhancer_randomize_seed": True,
    "save_queue_if_crash": 1,
    "enable_int8_kernels": 1,
    "prompt_enhancer_quantization": "quanto_int8",
    "last_model_per_family": {},
    "last_model_per_type": {},
    "last_model_type": "t2v_1.3B",
    "last_resolution_choice": "720x1280",
    "last_resolution_per_group": {
        "720p": "1280x720",
        "480p": "832x480",
        "1080p": "1088x1920",
        "540p": "960x544",
    },
    "last_advanced_choice": False,
    "notification_sound_enabled": False,
}

WAN2GP_T2V_MODEL_PRESETS: dict[str, dict[str, Any]] = {
    "t2v_1.3B": {
        "description": "Wan 2.1 T2V 1.3B - 速度快，适合低显存",
        "model_type": "t2v_1.3B",
        "supports_chinese": True,
        "prompt_language_preference": "balanced",
        "default_resolution": "480x832",
        "frames_per_second": 16,
        "inference_steps": 30,
        "guidance_scale": 5.0,
        "flow_shift": 5.0,
        "max_frames": 337,
        "vram_min": 6,
    },
    "t2v_14B": {
        "description": "Wan 2.1 T2V 14B - 高质量",
        "model_type": "t2v",
        "supports_chinese": True,
        "prompt_language_preference": "balanced",
        "default_resolution": "720x1280",
        "frames_per_second": 16,
        "inference_steps": 30,
        "guidance_scale": 5.0,
        "flow_shift": 5.0,
        "max_frames": 737,
        "vram_min": 12,
        "sliding_window_size": 81,
        "sliding_window_overlap": 5,
        "sliding_window_size_min": 5,
        "sliding_window_size_max": 257,
        "sliding_window_size_step": 4,
    },
    "t2v_2.2_14B": {
        "description": "Wan 2.2 T2V 14B - 双模型架构，更高质量",
        "model_type": "t2v_2_2",
        "supports_chinese": True,
        "prompt_language_preference": "balanced",
        "default_resolution": "720x1280",
        "frames_per_second": 16,
        "inference_steps": 30,
        "guidance_scale": 4.0,
        "guidance2_scale": 3.0,
        "guidance_phases": 2,
        "switch_threshold": 875,
        "flow_shift": 12.0,
        "max_frames": 737,
        "vram_min": 12,
        "sliding_window_size": 81,
        "sliding_window_overlap": 5,
        "sliding_window_size_min": 5,
        "sliding_window_size_max": 257,
        "sliding_window_size_step": 4,
    },
    "hunyuan_1.5_t2v": {
        "description": "Hunyuan 1.5 T2V 8B 720p - 最高质量",
        "model_type": "hunyuan_1_5_t2v",
        "metadata_key": "hunyuan_1_5_t2v",
        "supports_chinese": True,
        "prompt_language_preference": "balanced",
        "default_resolution": "720x1280",
        "frames_per_second": 24,
        "inference_steps": 30,
        "guidance_scale": 6.0,
        "flow_shift": 9.0,
        "max_frames": 337,
        "vram_min": 12,
    },
    "hunyuan_1_5_t2v_480p": {
        "description": "Hunyuan 1.5 T2V 8B 480p - 更省显存",
        "model_type": "hunyuan_1_5_480_t2v",
        "metadata_key": "hunyuan_1_5_480_t2v",
        "supports_chinese": True,
        "prompt_language_preference": "balanced",
        "default_resolution": "480x832",
        "frames_per_second": 24,
        "inference_steps": 30,
        "guidance_scale": 6.0,
        "flow_shift": 5.0,
        "max_frames": 337,
        "vram_min": 10,
    },
    "ltx2_22B": {
        "description": "LTX-2 2.3 Dev 22B - 原生带声音，LocalVideo 输出将自动去音轨",
        "model_type": "ltx2_22B",
        "supports_chinese": False,
        "prompt_language_preference": "en",
        "default_resolution": "720x1280",
        "frames_per_second": 24,
        "inference_steps": 30,
        "guidance_scale": 3.0,
        "guidance_phases": 2,
        "flow_shift": 0.0,
        "max_frames": 737,
        "vram_min": 12,
        "audio_guidance_scale": 7.0,
        "alt_guidance_scale": 3.0,
        "alt_scale": 0.7,
        "perturbation_switch": 2,
        "perturbation_layers": [28],
        "perturbation_start_perc": 0,
        "perturbation_end_perc": 100,
        "apg_switch": 0,
        "cfg_star_switch": 0,
        "strip_audio_output": True,
        "sliding_window_size": 481,
        "sliding_window_overlap": 17,
        "sliding_window_size_min": 5,
        "sliding_window_size_max": 501,
        "sliding_window_size_step": 4,
    },
    "ltx2_22B_distilled": {
        "description": "LTX-2 2.3 Distilled 22B - 更快，LocalVideo 输出将自动去音轨",
        "model_type": "ltx2_22B_distilled",
        "supports_chinese": False,
        "prompt_language_preference": "en",
        "default_resolution": "720x1280",
        "frames_per_second": 24,
        "inference_steps": 8,
        "guidance_scale": 1.0,
        "guidance_phases": 1,
        "flow_shift": 0.0,
        "max_frames": 737,
        "vram_min": 12,
        "strip_audio_output": True,
        "sliding_window_size": 481,
        "sliding_window_overlap": 17,
        "sliding_window_size_min": 5,
        "sliding_window_size_max": 501,
        "sliding_window_size_step": 4,
    },
}

WAN2GP_I2V_MODEL_PRESETS: dict[str, dict[str, Any]] = {
    "fun_inp_1.3B": {
        "description": "Fun InP 1.3B - 快速图生视频",
        "model_type": "fun_inp_1.3B",
        "supports_chinese": True,
        "prompt_language_preference": "balanced",
        "default_resolution": "480x832",
        "frames_per_second": 16,
        "inference_steps": 30,
        "guidance_scale": 5.0,
        "flow_shift": 7.0,
        "max_frames": 737,
        "vram_min": 6,
        "sliding_window_size": 81,
        "sliding_window_overlap": 1,
        "sliding_window_size_min": 5,
        "sliding_window_size_max": 257,
        "sliding_window_size_step": 4,
    },
    "i2v_720p": {
        "description": "Wan2.1 I2V 720p 14B - 标准图生视频",
        "model_type": "i2v_720p",
        "metadata_key": "i2v_720p",
        "supports_chinese": True,
        "prompt_language_preference": "balanced",
        "default_resolution": "720x1280",
        "frames_per_second": 16,
        "inference_steps": 30,
        "guidance_scale": 5.0,
        "flow_shift": 7.0,
        "max_frames": 737,
        "vram_min": 12,
        "sliding_window_size": 81,
        "sliding_window_overlap": 1,
        "sliding_window_size_min": 5,
        "sliding_window_size_max": 257,
        "sliding_window_size_step": 4,
    },
    "i2v_480p": {
        "description": "Wan2.1 I2V 480p 14B - 低显存图生视频",
        "model_type": "i2v",
        "metadata_key": "i2v",
        "supports_chinese": True,
        "prompt_language_preference": "balanced",
        "default_resolution": "480x832",
        "frames_per_second": 16,
        "inference_steps": 30,
        "guidance_scale": 5.0,
        "flow_shift": 7.0,
        "max_frames": 737,
        "vram_min": 10,
        "sliding_window_size": 81,
        "sliding_window_overlap": 1,
        "sliding_window_size_min": 5,
        "sliding_window_size_max": 257,
        "sliding_window_size_step": 4,
    },
    "i2v_2_2": {
        "description": "Wan2.2 I2V 14B - 高质量图生视频",
        "model_type": "i2v_2_2",
        "supports_chinese": True,
        "prompt_language_preference": "balanced",
        "default_resolution": "720x1280",
        "frames_per_second": 16,
        "inference_steps": 30,
        "guidance_scale": 3.5,
        "guidance2_scale": 3.5,
        "guidance_phases": 2,
        "switch_threshold": 900,
        "masking_strength": 0.1,
        "denoising_strength": 0.9,
        "flow_shift": 5.0,
        "max_frames": 737,
        "vram_min": 12,
        "sliding_window_size": 81,
        "sliding_window_overlap": 1,
        "sliding_window_size_min": 5,
        "sliding_window_size_max": 257,
        "sliding_window_size_step": 4,
    },
    "hunyuan_1.5_i2v": {
        "description": "Hunyuan 1.5 I2V 720p 8B - 最高质量",
        "model_type": "hunyuan_1_5_i2v",
        "metadata_key": "hunyuan_1_5_i2v",
        "supports_chinese": True,
        "prompt_language_preference": "balanced",
        "default_resolution": "720x1280",
        "frames_per_second": 24,
        "inference_steps": 30,
        "guidance_scale": 6.0,
        "flow_shift": 7.0,
        "max_frames": 337,
        "vram_min": 12,
        "sliding_window_size": 97,
        "sliding_window_overlap": 1,
        "sliding_window_size_min": 5,
        "sliding_window_size_max": 257,
        "sliding_window_size_step": 4,
    },
    "hunyuan_1_5_i2v_480p": {
        "description": "Hunyuan 1.5 I2V 8B 480p - 更省显存",
        "model_type": "hunyuan_1_5_480_i2v",
        "metadata_key": "hunyuan_1_5_480_i2v",
        "supports_chinese": True,
        "prompt_language_preference": "balanced",
        "default_resolution": "480x832",
        "frames_per_second": 24,
        "inference_steps": 30,
        "guidance_scale": 6.0,
        "flow_shift": 5.0,
        "max_frames": 337,
        "vram_min": 10,
        "sliding_window_size": 97,
        "sliding_window_overlap": 1,
        "sliding_window_size_min": 5,
        "sliding_window_size_max": 257,
        "sliding_window_size_step": 4,
    },
    "fun_inp_14B": {
        "description": "Fun InP 14B - 高质量图生视频",
        "model_type": "fun_inp",
        "metadata_key": "fun_inp",
        "supports_chinese": True,
        "prompt_language_preference": "balanced",
        "default_resolution": "720x1280",
        "frames_per_second": 16,
        "inference_steps": 30,
        "guidance_scale": 5.0,
        "flow_shift": 7.0,
        "max_frames": 737,
        "vram_min": 12,
        "sliding_window_size": 81,
        "sliding_window_overlap": 1,
        "sliding_window_size_min": 5,
        "sliding_window_size_max": 257,
        "sliding_window_size_step": 4,
    },
    "ltx2_22B": {
        "description": "LTX-2 2.3 Dev 22B - 原生带声音，LocalVideo 输出将自动去音轨",
        "model_type": "ltx2_22B",
        "supports_chinese": False,
        "prompt_language_preference": "en",
        "default_resolution": "720x1280",
        "frames_per_second": 24,
        "inference_steps": 30,
        "guidance_scale": 3.0,
        "guidance_phases": 2,
        "flow_shift": 0.0,
        "max_frames": 737,
        "vram_min": 12,
        "audio_guidance_scale": 7.0,
        "alt_guidance_scale": 3.0,
        "alt_scale": 0.7,
        "perturbation_switch": 2,
        "perturbation_layers": [28],
        "perturbation_start_perc": 0,
        "perturbation_end_perc": 100,
        "apg_switch": 0,
        "cfg_star_switch": 0,
        "strip_audio_output": True,
        "sliding_window_size": 481,
        "sliding_window_overlap": 17,
        "sliding_window_size_min": 5,
        "sliding_window_size_max": 501,
        "sliding_window_size_step": 4,
    },
    "ltx2_22B_distilled": {
        "description": "LTX-2 2.3 Distilled 22B - 更快，LocalVideo 输出将自动去音轨",
        "model_type": "ltx2_22B_distilled",
        "supports_chinese": False,
        "prompt_language_preference": "en",
        "default_resolution": "720x1280",
        "frames_per_second": 24,
        "inference_steps": 8,
        "guidance_scale": 1.0,
        "guidance_phases": 1,
        "flow_shift": 0.0,
        "max_frames": 737,
        "vram_min": 12,
        "strip_audio_output": True,
        "sliding_window_size": 481,
        "sliding_window_overlap": 17,
        "sliding_window_size_min": 5,
        "sliding_window_size_max": 501,
        "sliding_window_size_step": 4,
    },
}

WAN2GP_LAST_FRAME_SUPPORTED_I2V_PRESETS = {
    "fun_inp_1.3B",
    "fun_inp_14B",
    "i2v_720p",
    "i2v_480p",
    "i2v_2_2",
    "ltx2_22B",
    "ltx2_22B_distilled",
}

WAN2GP_LAST_FRAME_SUPPORTED_I2V_ALIASES = {
    "fun_inp_1.3b",
    "fun_inp",
    "i2v_720p",
    "i2v_480p",
    "i2v",
    "i2v_2_2",
    "ltx2_22b",
    "ltx2_22b_distilled",
}

WAN2GP_LAST_FRAME_UNSUPPORTED_I2V_ALIASES = {
    "hunyuan_1.5_i2v",
    "hunyuan_1_5_i2v",
    "hunyuan_1_5_i2v_480p",
    "hunyuan_1_5_480_i2v",
}


def _with_resolution_defaults(raw_preset: dict[str, Any]) -> dict[str, Any]:
    preset = raw_preset.copy()
    if "default_resolution" not in preset:
        preset["default_resolution"] = "720x1280"
    if "supported_resolutions" not in preset:
        preset["supported_resolutions"] = COMMON_RESOLUTIONS
    return preset


def supports_wan2gp_last_frame_preset(
    preset_name: str | None,
    *,
    mode: str | None = None,
) -> bool:
    normalized_mode = str(mode or "").strip().lower()
    normalized_name = str(preset_name or "").strip().lower()
    if not normalized_name:
        return False

    if normalized_name in WAN2GP_LAST_FRAME_UNSUPPORTED_I2V_ALIASES:
        return False
    if normalized_name in WAN2GP_LAST_FRAME_SUPPORTED_I2V_ALIASES:
        return True

    if normalized_mode == "t2v":
        return False

    normalized_t2v_presets = {name.lower() for name in WAN2GP_T2V_MODEL_PRESETS}
    if normalized_name in normalized_t2v_presets:
        return False

    normalized_i2v_presets = {
        name.lower(): preset for name, preset in WAN2GP_I2V_MODEL_PRESETS.items()
    }
    if normalized_name in normalized_i2v_presets:
        preset = normalized_i2v_presets[normalized_name]
        metadata_key = str(preset.get("metadata_key") or "").strip().lower()
        model_type = str(preset.get("model_type") or "").strip().lower()
        if metadata_key in WAN2GP_LAST_FRAME_UNSUPPORTED_I2V_ALIASES:
            return False
        if model_type in WAN2GP_LAST_FRAME_UNSUPPORTED_I2V_ALIASES:
            return False
        return normalized_name in WAN2GP_LAST_FRAME_SUPPORTED_I2V_ALIASES

    return False


def get_wan2gp_t2v_preset(preset_name: str) -> dict[str, Any]:
    if preset_name not in WAN2GP_T2V_MODEL_PRESETS:
        available = ", ".join(sorted(WAN2GP_T2V_MODEL_PRESETS.keys()))
        raise ValueError(f"Unknown Wan2GP T2V preset: {preset_name}. Available: {available}")
    return _with_resolution_defaults(WAN2GP_T2V_MODEL_PRESETS[preset_name])


def get_wan2gp_i2v_preset(preset_name: str) -> dict[str, Any]:
    if preset_name not in WAN2GP_I2V_MODEL_PRESETS:
        available = ", ".join(sorted(WAN2GP_I2V_MODEL_PRESETS.keys()))
        raise ValueError(f"Unknown Wan2GP I2V preset: {preset_name}. Available: {available}")
    return _with_resolution_defaults(WAN2GP_I2V_MODEL_PRESETS[preset_name])


def _load_defaults_metadata(
    defaults_dir: Path | None,
) -> tuple[dict[str, list[dict[str, str]]], dict[str, dict[str, str]]]:
    metadata_by_architecture: dict[str, list[dict[str, str]]] = {}
    metadata_by_stem: dict[str, dict[str, str]] = {}
    if defaults_dir is None or not defaults_dir.exists() or not defaults_dir.is_dir():
        return metadata_by_architecture, metadata_by_stem

    for config_file in sorted(defaults_dir.glob("*.json")):
        try:
            payload = json.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        model_info = payload.get("model")
        if not isinstance(model_info, dict):
            continue

        architecture = str(model_info.get("architecture") or "").strip()
        if not architecture:
            continue
        display_name = str(model_info.get("name") or "").strip()
        description = str(model_info.get("description") or "").strip()
        if not display_name and not description:
            continue
        entry = {
            "display_name": display_name,
            "description": description,
            "file_path": str(config_file),
        }
        metadata_by_stem[config_file.stem] = entry
        metadata_by_architecture.setdefault(architecture, []).append(entry)
    return metadata_by_architecture, metadata_by_stem


def _resolve_preset_metadata(
    preset_name: str,
    preset: dict[str, Any],
    metadata_by_architecture: dict[str, list[dict[str, str]]],
    metadata_by_stem: dict[str, dict[str, str]],
) -> tuple[str, str]:
    metadata_key = str(preset.get("metadata_key") or "").strip()
    architecture = str(preset.get("model_type") or "").strip()
    metadata = metadata_by_stem.get(metadata_key) if metadata_key else None
    if metadata is None:
        metadata = metadata_by_stem.get(preset_name)
    if metadata is None and architecture:
        metadata = metadata_by_stem.get(architecture)
    if metadata is None:
        candidates = metadata_by_architecture.get(architecture, [])
        metadata = candidates[0] if candidates else {}
    display_name = str(metadata.get("display_name") or "").strip()
    description = str(metadata.get("description") or "").strip()

    fallback_display_name = str(preset.get("description") or "").split(" - ", maxsplit=1)[0].strip()
    if not display_name:
        display_name = fallback_display_name or str(preset.get("model_type") or preset_name)
    if not description:
        description = str(preset.get("description") or "")
    return display_name, description


def get_wan2gp_video_presets(wan2gp_path: str | None = None) -> dict[str, list[dict[str, Any]]]:
    defaults_dir = None
    if wan2gp_path:
        defaults_dir = Path(wan2gp_path).expanduser() / "defaults"
    metadata_by_architecture, metadata_by_stem = _load_defaults_metadata(defaults_dir)

    def build_items(
        preset_dict: dict[str, dict[str, Any]],
        mode: str,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for preset_name in sorted(preset_dict.keys()):
            preset = _with_resolution_defaults(preset_dict[preset_name])
            display_name, description = _resolve_preset_metadata(
                preset_name,
                preset,
                metadata_by_architecture,
                metadata_by_stem,
            )
            rows.append(
                {
                    "id": preset_name,
                    "mode": mode,
                    "display_name": display_name,
                    "description": description,
                    "model_type": str(preset["model_type"]),
                    "supports_chinese": bool(preset.get("supports_chinese", False)),
                    "prompt_language_preference": str(
                        preset.get("prompt_language_preference", "balanced")
                    ),
                    "supports_last_frame": supports_wan2gp_last_frame_preset(
                        preset_name,
                        mode=mode,
                    ),
                    "default_resolution": str(preset["default_resolution"]),
                    "supported_resolutions": list(preset["supported_resolutions"]),
                    "frames_per_second": int(preset["frames_per_second"]),
                    "inference_steps": int(preset["inference_steps"]),
                    "guidance_scale": float(preset["guidance_scale"]),
                    "flow_shift": float(preset["flow_shift"]),
                    "max_frames": int(preset.get("max_frames", 129)),
                    "vram_min": int(preset.get("vram_min", 0)),
                    "sliding_window_size": (
                        int(preset["sliding_window_size"])
                        if preset.get("sliding_window_size") is not None
                        else None
                    ),
                    "sliding_window_size_min": (
                        int(preset["sliding_window_size_min"])
                        if preset.get("sliding_window_size_min") is not None
                        else None
                    ),
                    "sliding_window_size_max": (
                        int(preset["sliding_window_size_max"])
                        if preset.get("sliding_window_size_max") is not None
                        else None
                    ),
                    "sliding_window_size_step": (
                        int(preset["sliding_window_size_step"])
                        if preset.get("sliding_window_size_step") is not None
                        else None
                    ),
                }
            )
        return rows

    return {
        "t2v_presets": build_items(WAN2GP_T2V_MODEL_PRESETS, "t2v"),
        "i2v_presets": build_items(WAN2GP_I2V_MODEL_PRESETS, "i2v"),
    }


def _to_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed


def _to_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed


def _parse_resolution(resolution: str) -> tuple[int, int]:
    if "x" not in resolution:
        raise ValueError(f"Invalid resolution format: {resolution}")
    width_text, height_text = resolution.split("x", maxsplit=1)
    return int(width_text), int(height_text)


def _is_distilled_wan2gp_model(model_type: Any) -> bool:
    return str(model_type or "").strip().lower().endswith("_distilled")


@dataclass
class Wan2GPVideoBatchTask:
    task_id: str
    prompt: str
    output_path: Path
    duration: float | None = None
    fps: int | None = None
    resolution: str | None = None
    first_frame: Path | None = None
    last_frame: Path | None = None


class Wan2GPVideoProvider(Wan2GPBase, VideoProvider):
    name = "wan2gp"

    def __init__(
        self,
        wan2gp_path: str | None = None,
        python_executable: str | None = None,
        t2v_preset: str = "t2v_1.3B",
        i2v_preset: str = "i2v_720p",
        resolution: str = "",
        frames_per_second: int = 0,
        inference_steps: int = 0,
        guidance_scale: float = 0.0,
        flow_shift: float = 0.0,
        sliding_window_size: int = 0,
        seed: int = -1,
        sample_solver: str = "unipc",
        negative_prompt: str = "",
        fit_canvas: int = 0,
    ):
        self.wan2gp_path = Path(wan2gp_path or "../Wan2GP")
        self.python_executable = python_executable
        self.t2v_preset_name = t2v_preset
        self.i2v_preset_name = i2v_preset
        self.resolution_override = (resolution or "").strip()
        self.fps_override = _to_int(frames_per_second, 0)
        self.steps_override = _to_int(inference_steps, 0)
        self.guidance_override = _to_float(guidance_scale, 0.0)
        self.flow_shift_override = _to_float(flow_shift, 0.0)
        self.sliding_window_size_override = _to_int(sliding_window_size, 0)
        self.seed = _to_int(seed, -1)
        self.sample_solver = (sample_solver or "unipc").strip() or "unipc"
        self.negative_prompt = negative_prompt or ""
        resolved_fit_canvas = _to_int(fit_canvas, 0)
        if resolved_fit_canvas not in (0, 1, 2):
            resolved_fit_canvas = 0
        self.fit_canvas = resolved_fit_canvas

    def _get_video_config(
        self, use_i2v: bool, runtime_resolution: str | None = None
    ) -> dict[str, Any]:
        preset = (
            get_wan2gp_i2v_preset(self.i2v_preset_name)
            if use_i2v
            else get_wan2gp_t2v_preset(self.t2v_preset_name)
        )
        return {
            "preset_name": self.i2v_preset_name if use_i2v else self.t2v_preset_name,
            "model_type": preset["model_type"],
            "resolution": runtime_resolution
            or self.resolution_override
            or preset["default_resolution"],
            "frames_per_second": self.fps_override or preset["frames_per_second"],
            "inference_steps": self.steps_override or preset["inference_steps"],
            "guidance_scale": self.guidance_override or preset["guidance_scale"],
            "guidance2_scale": preset.get("guidance2_scale"),
            "guidance_phases": preset.get("guidance_phases"),
            "switch_threshold": preset.get("switch_threshold"),
            "switch_threshold2": preset.get("switch_threshold2"),
            "model_switch_phase": preset.get("model_switch_phase"),
            "flow_shift": self.flow_shift_override or preset["flow_shift"],
            "max_frames": preset.get("max_frames", 129),
            "seed": self.seed,
            "sample_solver": self.sample_solver,
            "negative_prompt": self.negative_prompt,
            "audio_guidance_scale": preset.get("audio_guidance_scale"),
            "alt_guidance_scale": preset.get("alt_guidance_scale"),
            "alt_scale": preset.get("alt_scale"),
            "perturbation_switch": preset.get("perturbation_switch"),
            "perturbation_layers": preset.get("perturbation_layers"),
            "perturbation_start_perc": preset.get("perturbation_start_perc"),
            "perturbation_end_perc": preset.get("perturbation_end_perc"),
            "apg_switch": preset.get("apg_switch"),
            "cfg_star_switch": preset.get("cfg_star_switch"),
            "strip_audio_output": bool(preset.get("strip_audio_output", False)),
            "denoising_strength": preset.get("denoising_strength"),
            "masking_strength": preset.get("masking_strength"),
            "sliding_window_size": (
                self.sliding_window_size_override
                if self.sliding_window_size_override > 0
                else preset.get("sliding_window_size")
            ),
            "sliding_window_overlap": preset.get("sliding_window_overlap"),
            "sliding_window_overlap_noise": preset.get("sliding_window_overlap_noise"),
            "sliding_window_discard_last_frames": preset.get("sliding_window_discard_last_frames"),
        }

    async def _finalize_generated_video(
        self,
        *,
        source_path: Path,
        target_path: Path,
        strip_audio_output: bool,
    ) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            target_path.unlink()

        if not strip_audio_output:
            shutil.move(str(source_path), str(target_path))
            return

        fd, temp_output_text = tempfile.mkstemp(
            prefix=f"{target_path.stem}.strip_",
            suffix=target_path.suffix or ".mp4",
            dir=str(target_path.parent),
        )
        os.close(fd)
        temp_output = Path(temp_output_text)
        if temp_output.exists():
            temp_output.unlink()

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-map",
            "0:v:0",
            "-c:v",
            "copy",
            "-an",
            "-movflags",
            "+faststart",
            str(temp_output),
        ]
        logger.info(
            "[Wan2GP Video] Strip audio track for output: source=%s target=%s",
            source_path,
            target_path,
        )
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0 or not temp_output.exists():
            if temp_output.exists():
                temp_output.unlink()
            error_text = (
                stderr.decode(errors="ignore").strip() or stdout.decode(errors="ignore").strip()
            )
            raise RuntimeError(
                "Wan2GP output audio stripping failed "
                f"(code={process.returncode}): {error_text or 'unknown error'}"
            )

        shutil.move(str(temp_output), str(target_path))
        if source_path.exists():
            source_path.unlink()

    def _prepare_runtime_config_dir(self) -> Path:
        config_dir = Path(tempfile.mkdtemp(prefix="wan2gp_cfg_"))
        config_path = config_dir / "wgp_config.json"
        source_config_path = self.wan2gp_path / "wgp_config.json"
        config_payload: dict[str, Any] = dict(WAN2GP_RUNTIME_CONFIG_DEFAULTS)
        if source_config_path.exists():
            try:
                loaded = json.loads(source_config_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    config_payload.update(loaded)
            except Exception as exc:
                logger.warning(
                    "[Wan2GP Video] Failed to read base config %s: %s",
                    source_config_path,
                    exc,
                )
        config_payload["fit_canvas"] = self.fit_canvas
        config_path.write_text(
            json.dumps(config_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return config_dir

    def _build_generation_plan(
        self,
        *,
        duration: float | None,
        fps: int | None,
        resolution: int | str | None,
        first_frame: Path | None,
        last_frame: Path | None = None,
        runtime_resolution: str | None = None,
    ) -> dict[str, Any]:
        use_i2v = bool(
            (first_frame and first_frame.exists()) or (last_frame and last_frame.exists())
        )

        resolved_runtime_resolution = runtime_resolution
        if resolved_runtime_resolution is None and isinstance(resolution, str):
            candidate = resolution.strip()
            resolved_runtime_resolution = candidate or None

        video_config = self._get_video_config(
            use_i2v=use_i2v,
            runtime_resolution=resolved_runtime_resolution,
        )
        model_fps = int(video_config["frames_per_second"])
        effective_fps = _to_int(fps, 0)
        if effective_fps <= 0:
            effective_fps = model_fps

        effective_duration = _to_float(duration, 5.0)
        if effective_duration <= 0:
            effective_duration = 5.0

        frames = int(effective_duration * max(model_fps, 1))
        frames = ((frames // 4) * 4) + 1
        frames = max(17, min(frames, int(video_config["max_frames"])))
        steps = int(video_config["inference_steps"])
        width_px, height_px = _parse_resolution(str(video_config["resolution"]))
        is_distilled_pipeline = _is_distilled_wan2gp_model(video_config.get("model_type"))

        requested_force_fps = _to_int(fps, 0)

        payload: dict[str, Any] = {
            "settings_version": WAN2GP_VIDEO_SETTINGS_VERSION,
            "prompt": "",
            # Keep each task isolated from runtime global UI state (primary_settings merge in Wan2GP).
            "multi_prompts_gen_type": 2,
            "model_type": video_config["model_type"],
            "type": video_config["model_type"],
            "resolution": video_config["resolution"],
            "image_mode": 0,
            "video_length": frames,
            "num_inference_steps": steps,
            "seed": int(video_config["seed"]),
            "guidance_scale": _to_float(video_config.get("guidance_scale"), 1.0),
            "guidance2_scale": _to_float(
                video_config.get("guidance2_scale"),
                _to_float(video_config.get("guidance_scale"), 1.0),
            ),
            "guidance_phases": _to_int(video_config.get("guidance_phases"), 1),
            "switch_threshold": _to_int(video_config.get("switch_threshold"), 900),
            "switch_threshold2": _to_int(video_config.get("switch_threshold2"), 880),
            "model_switch_phase": _to_int(video_config.get("model_switch_phase"), 1),
            "flow_shift": _to_float(video_config.get("flow_shift"), 0.0),
            "audio_guidance_scale": _to_float(video_config.get("audio_guidance_scale"), 4.0),
            "alt_guidance_scale": _to_float(video_config.get("alt_guidance_scale"), 1.0),
            "alt_scale": _to_float(video_config.get("alt_scale"), 0.0),
            "perturbation_switch": _to_int(video_config.get("perturbation_switch"), 0),
            "perturbation_layers": video_config.get("perturbation_layers"),
            "perturbation_start_perc": _to_int(video_config.get("perturbation_start_perc"), 0),
            "perturbation_end_perc": _to_int(video_config.get("perturbation_end_perc"), 100),
            "apg_switch": _to_int(video_config.get("apg_switch"), 0),
            "cfg_star_switch": _to_int(video_config.get("cfg_star_switch"), 0),
            "sample_solver": str(video_config["sample_solver"]),
            "negative_prompt": str(video_config["negative_prompt"]),
            "video_prompt_type": "",
            "image_prompt_type": "",
            "audio_prompt_type": "",
            "force_fps": str(effective_fps) if requested_force_fps > 0 else "",
            "MMAudio_setting": 0,
            "keep_frames_video_guide": "",
            "keep_frames_video_source": "",
            "frames_positions": "",
            "denoising_strength": _to_float(video_config.get("denoising_strength"), 1.0),
            "masking_strength": _to_float(video_config.get("masking_strength"), 1.0),
            "duration_seconds": effective_duration,
            "skip_steps_cache_type": "",
            "input_video_strength": 1.0,
            "spatial_upsampling": "",
            "video_guide_outpainting": "",
            "self_refiner_setting": 0,
            "self_refiner_plan": "",
            "model_mode": None,
            "motion_amplitude": 1.0,
            "activated_loras": [],
            "loras_multipliers": "",
            "image_start": None,
            "image_end": None,
            "image_refs": None,
            "video_source": None,
            "video_guide": None,
            "video_mask": None,
            "image_guide": None,
            "image_mask": None,
            "custom_guide": None,
            "audio_guide": None,
            "audio_guide2": None,
            "audio_source": None,
            "batch_size": 1,
        }
        sliding_window_size = _to_int(video_config.get("sliding_window_size"), 0)
        if sliding_window_size > 0:
            payload["sliding_window_size"] = sliding_window_size

        sliding_window_overlap = _to_int(video_config.get("sliding_window_overlap"), 0)
        if sliding_window_overlap > 0:
            payload["sliding_window_overlap"] = sliding_window_overlap

        sliding_window_overlap_noise = _to_int(video_config.get("sliding_window_overlap_noise"), 0)
        if sliding_window_overlap_noise > 0:
            payload["sliding_window_overlap_noise"] = sliding_window_overlap_noise

        sliding_window_discard_last_frames = _to_int(
            video_config.get("sliding_window_discard_last_frames"), 0
        )
        if sliding_window_discard_last_frames > 0:
            payload["sliding_window_discard_last_frames"] = sliding_window_discard_last_frames

        if is_distilled_pipeline:
            for key in (
                "audio_guidance_scale",
                "alt_guidance_scale",
                "alt_scale",
                "perturbation_switch",
                "perturbation_layers",
                "perturbation_start_perc",
                "perturbation_end_perc",
                "apg_switch",
                "cfg_star_switch",
            ):
                payload.pop(key, None)
        if use_i2v:
            prompt_types: list[str] = []
            if first_frame and first_frame.exists():
                # Wan2GP i2v flows require image_prompt_type containing "S" to keep image_start.
                # Without it (notably on Hunyuan 1.5 i2v), image_start is nulled during validation.
                prompt_types.append("S")
                first_frame_path = str(first_frame)
                # Wan2GP batch/CLI consumes image_start as the canonical start-frame field.
                payload["image_start"] = first_frame_path
            if last_frame and last_frame.exists():
                prompt_types.append("E")
                payload["image_end"] = str(last_frame)
            if prompt_types:
                payload["image_prompt_type"] = "".join(prompt_types)

        return {
            "video_config": video_config,
            "settings_payload": payload,
            "frames": frames,
            "steps": steps,
            "model_fps": model_fps,
            "effective_fps": effective_fps,
            "duration": float(frames / max(model_fps, 1)),
            "width": width_px,
            "height": height_px,
            "use_i2v": use_i2v,
            "strip_audio_output": bool(video_config.get("strip_audio_output", False)),
        }

    async def _run_wgp(
        self,
        *,
        python_executable: str,
        settings_path: Path,
        output_dir: Path,
        expected_steps: int,
        progress_callback: Any,
        status_callback: Callable[[str], Awaitable[None]] | None = None,
        line_callback: Callable[[str], Awaitable[str | None]] | None = None,
    ) -> list[str]:
        runtime_config_dir = self._prepare_runtime_config_dir()
        external_ui_processes = detect_external_wan2gp_ui_processes()
        cmd = [
            python_executable,
            "-u",
            str(self.wan2gp_path / "wgp.py"),
            "--process",
            str(settings_path),
            "--output-dir",
            str(output_dir),
            "--config",
            str(runtime_config_dir),
            "--verbose",
            "1",
        ]
        cmd_text = " ".join(shlex.quote(part) for part in cmd)
        logger.info("[Wan2GP Video] Start subprocess: %s", cmd_text)
        logger.info(
            "[Wan2GP Video] Runtime override fit_canvas=%d via config=%s",
            self.fit_canvas,
            runtime_config_dir,
        )
        if external_ui_processes:
            logger.warning(
                "[Wan2GP Video] Detected %d external Wan2GP UI process(es) before launch: %s. "
                "Running another wgp.py subprocess concurrently can duplicate RAM/VRAM usage and trigger OOM.",
                len(external_ui_processes),
                ", ".join(f"pid={pid}" for pid, _ in external_ui_processes),
            )

        try:
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
        except Exception:
            shutil.rmtree(runtime_config_dir, ignore_errors=True)
            raise
        register_wan2gp_pid(process.pid)
        download_monitor_stop: asyncio.Event | None = None
        monitor_task: asyncio.Task[None] | None = None

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

        try:
            step_pattern = re.compile(r"(?:Step\s+)?(\d+)\s*/\s*(\d+)")
            prompt_pattern = re.compile(r"Prompt\s+(\d+)\s*/\s*(\d+)", re.IGNORECASE)
            task_pattern = re.compile(r"\[Task\s+(\d+)\s*/\s*(\d+)\]", re.IGNORECASE)
            sliding_window_pattern = re.compile(
                r"(?:Sliding\s+Window|滑窗)\s*(\d+)\s*/\s*(\d+)",
                re.IGNORECASE,
            )
            ansi_escape_pattern = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
            download_progress_pattern = re.compile(r":\s*\d+%\|")
            download_start_pattern = re.compile(
                r"Downloading\s+['\"](?P<filename>[^'\"]+)['\"]",
                re.IGNORECASE,
            )
            tqdm_filename_pattern = re.compile(r"^(?P<filename>[^:\n]+?):\s*\d+(?:\.\d+)?%\|")
            output_tail: deque[str] = deque(maxlen=40)
            pending_text = ""
            last_progress = 0
            last_status_message: str | None = None
            prompt_scope_marker: tuple[int, int] | None = None
            task_scope_marker: tuple[int, int] | None = None
            sliding_window_scope_marker: tuple[int, int] | None = None
            process_start_ts = time.time()
            downloading_active = False
            loading_phase_active = False
            last_download_log_ts = 0.0
            last_download_progress_line: str | None = None
            last_download_progress_log_ts = 0.0
            download_progress_log_interval_seconds = 10.0
            download_lock_check_interval_seconds = 10.0
            current_download_filename: str | None = None

            download_monitor_stop = asyncio.Event()
            hf_download_dir = self.wan2gp_path / "ckpts" / ".cache" / "huggingface" / "download"

            async def monitor_download_locks() -> None:
                nonlocal downloading_active, loading_phase_active, last_download_log_ts
                last_snapshot: set[str] = set()
                was_downloading = False
                active_lock_min_mtime = process_start_ts - 2.0
                while not download_monitor_stop.is_set():
                    current_snapshot: set[str] = set()
                    if hf_download_dir.exists():
                        for lock_file in hf_download_dir.glob("*.lock"):
                            if not lock_file.exists():
                                continue
                            try:
                                if lock_file.stat().st_mtime >= active_lock_min_mtime:
                                    current_snapshot.add(lock_file.name)
                            except Exception:
                                continue

                    if current_snapshot:
                        now = time.time()
                        if (
                            current_snapshot != last_snapshot
                            or now - last_download_log_ts >= download_lock_check_interval_seconds
                        ):
                            last_download_log_ts = now
                        was_downloading = True
                        downloading_active = True
                        if not loading_phase_active and not (
                            last_status_message and last_status_message.startswith("模型下载中")
                        ):
                            await emit_status(STATUS_MODEL_DOWNLOADING)
                    elif was_downloading:
                        was_downloading = False
                        downloading_active = False
                        if not loading_phase_active:
                            await emit_status(STATUS_MODEL_LOADING)

                    last_snapshot = current_snapshot
                    try:
                        await asyncio.wait_for(
                            download_monitor_stop.wait(),
                            timeout=download_lock_check_interval_seconds,
                        )
                    except TimeoutError:
                        pass

            monitor_task = asyncio.create_task(monitor_download_locks())

            async def process_output_text(text: str) -> None:
                nonlocal last_progress
                nonlocal prompt_scope_marker
                nonlocal task_scope_marker
                nonlocal sliding_window_scope_marker
                nonlocal downloading_active
                nonlocal loading_phase_active
                nonlocal last_download_progress_line
                nonlocal last_download_progress_log_ts
                nonlocal current_download_filename
                cleaned = ansi_escape_pattern.sub("", text).strip()
                if not cleaned:
                    return

                download_start_match = download_start_pattern.search(cleaned)
                if download_start_match:
                    current_download_filename = Path(
                        download_start_match.group("filename").strip()
                    ).name

                tqdm_filename_match = tqdm_filename_pattern.search(cleaned)
                if tqdm_filename_match and current_download_filename:
                    displayed_filename = tqdm_filename_match.group("filename").strip()
                    if displayed_filename != current_download_filename and (
                        "…" in displayed_filename
                        or "..." in displayed_filename
                        or displayed_filename.endswith("(…)")
                        or displayed_filename.endswith("(...)")
                    ):
                        cleaned = cleaned.replace(
                            displayed_filename,
                            current_download_filename,
                            1,
                        )

                output_tail.append(cleaned)
                is_download_progress_line = (
                    bool(download_progress_pattern.search(cleaned)) and "/" in cleaned
                )
                should_log_line = True
                if is_download_progress_line:
                    now = time.time()
                    if cleaned == last_download_progress_line:
                        should_log_line = False
                    elif (
                        now - last_download_progress_log_ts < download_progress_log_interval_seconds
                        and "100%|" not in cleaned
                    ):
                        should_log_line = False
                    if should_log_line:
                        last_download_progress_line = cleaned
                        last_download_progress_log_ts = now
                line_override = cleaned
                if line_callback:
                    try:
                        maybe_override = await line_callback(cleaned)
                        if isinstance(maybe_override, str) and maybe_override.strip():
                            line_override = maybe_override.strip()
                    except Exception:
                        pass
                if should_log_line:
                    logger.info("[Wan2GP Video] %s", line_override)

                if "error" in cleaned.lower():
                    logger.warning("[Wan2GP Video] runtime error line: %s", cleaned)

                runtime_status = self._infer_runtime_status_message(cleaned)
                if runtime_status:
                    if runtime_status.startswith("模型下载中"):
                        downloading_active = True
                        loading_phase_active = False
                    elif runtime_status.startswith("模型加载中"):
                        downloading_active = False
                        loading_phase_active = True
                    await emit_status(runtime_status)

                if not progress_callback:
                    return

                scope_changed = False
                prompt_match = prompt_pattern.search(cleaned)
                if prompt_match:
                    marker = (int(prompt_match.group(1)), int(prompt_match.group(2)))
                    if marker != prompt_scope_marker:
                        prompt_scope_marker = marker
                        scope_changed = True
                task_match = task_pattern.search(cleaned)
                if task_match:
                    marker = (int(task_match.group(1)), int(task_match.group(2)))
                    if marker != task_scope_marker:
                        task_scope_marker = marker
                        scope_changed = True
                sliding_window_match = sliding_window_pattern.search(cleaned)
                if sliding_window_match:
                    marker = (
                        int(sliding_window_match.group(1)),
                        int(sliding_window_match.group(2)),
                    )
                    if marker != sliding_window_scope_marker:
                        sliding_window_scope_marker = marker
                        scope_changed = True
                if scope_changed:
                    last_progress = 0

                candidate_progress: int | None = None
                for match in step_pattern.finditer(cleaned):
                    current_step = int(match.group(1))
                    total_steps = int(match.group(2))
                    if total_steps <= 0:
                        continue
                    if expected_steps > 0:
                        tolerance = max(2, int(expected_steps * 0.3))
                        if abs(total_steps - expected_steps) > tolerance:
                            continue
                    progress = int(
                        min(99, max(1, (current_step / max(total_steps, expected_steps)) * 99))
                    )
                    if candidate_progress is None or progress > candidate_progress:
                        candidate_progress = progress
                if candidate_progress is None:
                    return

                cleaned_lower = cleaned.lower()
                looks_like_generation_line = (
                    "denoising" in cleaned_lower
                    or "vae decoding" in cleaned_lower
                    or "sampling" in cleaned_lower
                    or "step " in cleaned_lower
                )
                if downloading_active and not looks_like_generation_line:
                    return
                if looks_like_generation_line:
                    downloading_active = False
                    loading_phase_active = False

                generation_status = (
                    runtime_status
                    if runtime_status and runtime_status.startswith(STATUS_GENERATING)
                    else STATUS_GENERATING
                )
                await emit_status(generation_status)
                if candidate_progress <= last_progress:
                    return
                last_progress = candidate_progress
                try:
                    await progress_callback(candidate_progress)
                except Exception:
                    pass

            stdout = process.stdout
            if stdout is not None:
                while True:
                    chunk = await stdout.read(4096)
                    if not chunk:
                        break
                    pending_text += chunk.decode(errors="ignore")
                    parts = re.split(r"[\r\n]+", pending_text)
                    pending_text = parts.pop() if parts else ""
                    for part in parts:
                        await process_output_text(part)

                if pending_text:
                    await process_output_text(pending_text)

            return_code = await process.wait()
            if return_code != 0:
                tail_text = (
                    "\n".join(output_tail) if output_tail else "<no subprocess output captured>"
                )
                raise RuntimeError(
                    "Wan2GP video generation failed with return code "
                    f"{return_code}\nCommand: {cmd_text}\nLast output lines:\n{tail_text}"
                )
            if download_monitor_stop is not None:
                download_monitor_stop.set()
            if monitor_task is not None:
                try:
                    await monitor_task
                except Exception:
                    pass
            return list(output_tail)
        finally:
            if download_monitor_stop is not None:
                download_monitor_stop.set()
            if monitor_task is not None:
                try:
                    await monitor_task
                except Exception:
                    pass
            if process.returncode is None:
                terminate_pid_tree(process.pid, grace_seconds=2.0)
                try:
                    await asyncio.wait_for(process.wait(), timeout=3.0)
                except Exception:
                    pass
            unregister_wan2gp_pid(process.pid)
            if runtime_config_dir.exists():
                shutil.rmtree(runtime_config_dir, ignore_errors=True)

    async def generate(
        self,
        prompt: str,
        output_path: Path,
        duration: float | None = None,
        width: int | None = None,
        height: int | None = None,
        fps: int | None = None,
        resolution: int | str | None = None,
        aspect_ratio: str | None = None,
        first_frame: Path | None = None,
        last_frame: Path | None = None,
        reference_images: list[Path] | None = None,
        progress_callback: Any = None,
        **kwargs: Any,
    ) -> VideoResult:
        del width, height, aspect_ratio
        status_callback = kwargs.get("status_callback")
        if not callable(status_callback):
            status_callback = None

        self._validate_config()
        python_executable = self._resolve_python_executable()

        if first_frame and not first_frame.exists():
            logger.warning(
                "[Wan2GP Video] first_frame path does not exist, fallback to T2V: %s",
                first_frame,
            )
        if last_frame and not last_frame.exists():
            logger.warning(
                "[Wan2GP Video] last_frame path does not exist, fallback to no end-frame guidance: %s",
                last_frame,
            )
        if reference_images:
            logger.warning(
                "[Wan2GP Video] reference_images is currently unsupported and will be ignored: %s",
                [str(path) for path in reference_images],
            )

        runtime_resolution = None
        if isinstance(resolution, str):
            runtime_resolution = resolution.strip() or None
        elif isinstance(kwargs.get("runtime_resolution"), str):
            runtime_resolution = str(kwargs["runtime_resolution"]).strip() or None
        elif isinstance(kwargs.get("resolution"), str):
            runtime_resolution = str(kwargs["resolution"]).strip() or None

        plan = self._build_generation_plan(
            duration=duration,
            fps=fps,
            resolution=resolution,
            first_frame=first_frame,
            last_frame=last_frame,
            runtime_resolution=runtime_resolution,
        )
        video_config = dict(plan["video_config"])
        settings_payload = dict(plan["settings_payload"])
        settings_payload["prompt"] = prompt
        steps = int(plan["steps"])
        model_fps = int(plan["model_fps"])
        effective_fps = int(plan["effective_fps"])
        width_px = int(plan["width"])
        height_px = int(plan["height"])
        actual_duration = float(plan["duration"])

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_dir = Path(tempfile.mkdtemp(prefix="wan2gp_vid_out_"))
        settings_path = self.wan2gp_path / (
            f"_settings_vid_{os.getpid()}_{int(time.time() * 1000)}_{output_path.stem}.json"
        )

        model_cached = self._is_model_cached(str(video_config["model_type"]))
        await emit_bootstrap_status(status_callback, model_cached)

        try:
            settings_path.write_text(
                json.dumps(settings_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            start_time = time.time()
            task_start_pattern = re.compile(r"\[Task\s+(\d+)\s*/\s*(\d+)\]", re.IGNORECASE)

            async def on_line(line: str) -> str | None:
                start_match = task_start_pattern.search(line)
                if not start_match:
                    return None
                task_no = int(start_match.group(1))
                total_tasks = int(start_match.group(2))
                return f"[Task {task_no}/{total_tasks}] {prompt}"

            output_tail = await self._run_wgp(
                python_executable=python_executable,
                settings_path=settings_path,
                output_dir=output_dir,
                expected_steps=steps,
                progress_callback=progress_callback,
                status_callback=status_callback,
                line_callback=on_line,
            )

            generated = [
                path
                for path in output_dir.glob("*.mp4")
                if path.is_file() and path.stat().st_mtime >= start_time - 0.01
            ]
            if not generated:
                generated = [path for path in output_dir.glob("*.mp4") if path.is_file()]
            if not generated:
                tail_text = (
                    "\n".join(output_tail[-12:])
                    if output_tail
                    else "<no subprocess output captured>"
                )
                raise FileNotFoundError(
                    "Wan2GP did not output any video file.\n"
                    f"Output dir: {output_dir}\n"
                    f"Last output lines:\n{tail_text}"
                )

            latest = max(generated, key=lambda p: p.stat().st_mtime)
            await self._finalize_generated_video(
                source_path=latest,
                target_path=output_path,
                strip_audio_output=bool(plan["strip_audio_output"]),
            )

            if progress_callback:
                try:
                    await progress_callback(100)
                except Exception:
                    pass

            logger.info(
                "[Wan2GP Video] Completed preset=%s mode=%s fps=%s frames=%s file=%s",
                video_config["preset_name"],
                "i2v" if bool(plan["use_i2v"]) else "t2v",
                model_fps,
                int(plan["frames"]),
                output_path,
            )
            return VideoResult(
                file_path=output_path,
                duration=float(actual_duration),
                width=width_px,
                height=height_px,
                fps=effective_fps,
            )
        finally:
            if settings_path.exists():
                settings_path.unlink()
            if output_dir.exists():
                shutil.rmtree(output_dir, ignore_errors=True)

    async def generate_batch(
        self,
        tasks: list[Wan2GPVideoBatchTask],
        progress_callback: Callable[[str, int, str | None], Awaitable[None]] | None = None,
        status_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> dict[str, VideoResult]:
        if not tasks:
            return {}

        self._validate_config()
        python_executable = self._resolve_python_executable()
        output_dir = Path(tempfile.mkdtemp(prefix="wan2gp_vid_batch_out_"))
        settings_path = self.wan2gp_path / (
            f"_settings_vid_batch_{os.getpid()}_{int(time.time() * 1000)}.json"
        )

        payloads: list[dict[str, Any]] = []
        task_info: dict[str, dict[str, Any]] = {}
        current_task_idx = -1
        completed_task_ids: set[str] = set()
        assigned_source_paths: set[Path] = set()
        results: dict[str, VideoResult] = {}
        batch_model_cached: bool | None = None

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
                if path.is_file() and path.suffix.lower() == ".mp4"
            ]

        async def assign_result_for_task(
            task_id: str, candidates: list[Path]
        ) -> VideoResult | None:
            if task_id in results:
                return results[task_id]

            task_meta = task_info.get(task_id)
            if task_meta is None:
                return None
            output_key = str(task_meta["output_key"])
            output_path = Path(task_meta["output_path"])
            matched = [
                path
                for path in candidates
                if path not in assigned_source_paths
                and (
                    path.stem == output_key
                    or path.stem.startswith(f"{output_key}_")
                    or path.stem.startswith(f"{output_key}(")
                )
            ]
            if not matched:
                return None

            picked = max(matched, key=lambda p: p.stat().st_mtime)
            assigned_source_paths.add(picked)
            target_path = output_path.with_suffix(".mp4")
            await self._finalize_generated_video(
                source_path=picked,
                target_path=target_path,
                strip_audio_output=bool(task_meta.get("strip_audio_output", False)),
            )
            result = VideoResult(
                file_path=target_path,
                duration=float(task_meta["duration"]),
                width=int(task_meta["width"]),
                height=int(task_meta["height"]),
                fps=int(task_meta["fps"]),
            )
            results[task_id] = result
            return result

        task_start_pattern = re.compile(r"\[Task\s+(\d+)\s*/\s*(\d+)\]", re.IGNORECASE)
        task_done_pattern = re.compile(r"Task\s+(\d+)\s+completed", re.IGNORECASE)

        try:
            for i, task in enumerate(tasks):
                task_id = str(task.task_id)
                prompt = str(task.prompt or "").strip()
                if not prompt:
                    raise ValueError(f"Wan2GP batch task prompt is empty (task_id={task_id})")
                first_frame = None
                if task.first_frame:
                    first_frame = Path(task.first_frame)
                    if not first_frame.exists():
                        first_frame = None
                last_frame = None
                if task.last_frame:
                    last_frame = Path(task.last_frame)
                    if not last_frame.exists():
                        last_frame = None

                runtime_resolution = str(task.resolution or "").strip() or None
                plan = self._build_generation_plan(
                    duration=task.duration,
                    fps=task.fps,
                    resolution=task.resolution,
                    first_frame=first_frame,
                    last_frame=last_frame,
                    runtime_resolution=runtime_resolution,
                )
                payload = dict(plan["settings_payload"])
                payload["prompt"] = prompt
                output_key = f"yf_batch_vid_{i:04d}"
                payload["output_filename"] = output_key

                model_type = str(plan["video_config"]["model_type"])
                if batch_model_cached is None:
                    batch_model_cached = self._is_model_cached(model_type)

                output_path = Path(task.output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                task_info[task_id] = {
                    "output_key": output_key,
                    "output_path": output_path,
                    "duration": float(plan["duration"]),
                    "width": int(plan["width"]),
                    "height": int(plan["height"]),
                    "fps": int(plan["effective_fps"]),
                    "steps": int(plan["steps"]),
                    "strip_audio_output": bool(plan["strip_audio_output"]),
                }
                payloads.append(payload)

            await emit_bootstrap_status(status_callback, batch_model_cached)
            settings_path.write_text(
                json.dumps(payloads, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            async def on_line(line: str) -> str | None:
                nonlocal current_task_idx
                start_match = task_start_pattern.search(line)
                if start_match:
                    task_no = int(start_match.group(1))
                    if 1 <= task_no <= len(tasks):
                        current_task_idx = task_no - 1
                        task = tasks[current_task_idx]
                        return f"[Task {task_no}/{len(tasks)}] {str(task.prompt or '')}"
                    return None

                done_match = task_done_pattern.search(line)
                if done_match:
                    task_no = int(done_match.group(1))
                    if 1 <= task_no <= len(tasks):
                        done_task_id = str(tasks[task_no - 1].task_id)
                        completed_task_ids.add(done_task_id)
                        result = await assign_result_for_task(
                            done_task_id,
                            collect_generated_paths(),
                        )
                        await emit_progress(
                            done_task_id, 100, str(result.file_path) if result else None
                        )
                    return None
                return None

            async def on_progress(progress: int) -> None:
                if not (0 <= current_task_idx < len(tasks)):
                    return
                task_id = str(tasks[current_task_idx].task_id)
                if task_id in completed_task_ids:
                    return
                await emit_progress(task_id, progress, None)

            expected_steps = 0
            if task_info:
                steps_values = {int(meta["steps"]) for meta in task_info.values()}
                if len(steps_values) == 1:
                    expected_steps = next(iter(steps_values))

            output_tail = await self._run_wgp(
                python_executable=python_executable,
                settings_path=settings_path,
                output_dir=output_dir,
                expected_steps=expected_steps,
                progress_callback=on_progress,
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
                    "Wan2GP batch video run did not output any video file.\n"
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
