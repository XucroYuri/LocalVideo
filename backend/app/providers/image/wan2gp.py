"""Wan2GP local image provider."""

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
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image

from app.providers.base.image import ImageProvider, ImageResult
from app.providers.wan2gp import (
    COMMON_RESOLUTIONS,
    STATUS_GENERATING,
    STATUS_MODEL_DOWNLOADING,
    STATUS_MODEL_LOADING,
    Wan2GPBase,
    emit_bootstrap_status,
    register_wan2gp_pid,
    terminate_pid_tree,
    unregister_wan2gp_pid,
)

logger = logging.getLogger(__name__)

WAN2GP_IMAGE_MODEL_PRESETS: dict[str, dict[str, Any]] = {
    "flux": {
        "description": "Flux 1 Dev 12B - high quality (English prompt only)",
        "model_type": "flux",
        "preset_type": "t2i",
        "prompt_language_preference": "en",
        "inference_steps": 30,
        "embedded_guidance_scale": 2.5,
        "supports_reference": False,
        "supports_chinese": False,
    },
    "flux_schnell": {
        "description": "Flux Schnell 12B - fast (English prompt only)",
        "model_type": "flux_schnell",
        "preset_type": "t2i",
        "prompt_language_preference": "en",
        "inference_steps": 10,
        "embedded_guidance_scale": 2.5,
        "supports_reference": False,
        "supports_chinese": False,
    },
    "z_image": {
        "description": "Z-Image Turbo 6B - fast, supports Chinese",
        "model_type": "z_image",
        "preset_type": "t2i",
        "prompt_language_preference": "balanced",
        "inference_steps": 8,
        "guidance_scale": 0.0,
        "supports_reference": False,
        "supports_chinese": True,
    },
    "z_image_base": {
        "description": "Z-Image Base 6B - high quality, supports Chinese",
        "model_type": "z_image_base",
        "preset_type": "t2i",
        "prompt_language_preference": "balanced",
        "inference_steps": 30,
        "supports_reference": False,
        "supports_chinese": True,
    },
    "qwen_image": {
        "description": "Qwen Image 20B - strong Chinese understanding",
        "model_type": "qwen_image_20B",
        "preset_type": "t2i",
        "prompt_language_preference": "zh",
        "inference_steps": 30,
        "guidance_scale": 4.0,
        "supports_reference": False,
        "supports_chinese": True,
    },
    "qwen_image_2512": {
        "description": "Qwen Image 2512 Release 20B - enhanced realism and text rendering",
        "model_type": "qwen_image_2512_20B",
        "preset_type": "t2i",
        "prompt_language_preference": "zh",
        "inference_steps": 30,
        "guidance_scale": 4.0,
        "supports_reference": False,
        "supports_chinese": True,
    },
    "flux2_dev": {
        "description": "Flux 2 Dev 32B - supports reference images",
        "model_type": "flux2_dev",
        "preset_type": "i2i",
        "prompt_language_preference": "en",
        "supported_modes": ["t2i", "i2i"],
        "inference_steps": 30,
        "embedded_guidance_scale": 4.0,
        "supports_reference": True,
        "reference_mode": "KI",
        "supports_chinese": True,
    },
    "flux2_dev_nvfp4": {
        "description": "Flux 2 Dev NVFP4 32B - quantized generation and editing",
        "model_type": "flux2_dev_nvfp4",
        "preset_type": "i2i",
        "prompt_language_preference": "en",
        "supported_modes": ["t2i", "i2i"],
        "inference_steps": 30,
        "embedded_guidance_scale": 4.0,
        "supports_reference": True,
        "reference_mode": "KI",
        "supports_chinese": True,
    },
    "pi_flux2": {
        "description": "pi-FLUX.2 Dev 32B - fast generation and editing",
        "model_type": "pi_flux2",
        "preset_type": "i2i",
        "prompt_language_preference": "en",
        "supported_modes": ["t2i", "i2i"],
        "inference_steps": 4,
        "embedded_guidance_scale": 4.0,
        "supports_reference": True,
        "reference_mode": "KI",
        "supports_chinese": True,
    },
    "pi_flux2_nvfp4": {
        "description": "pi-FLUX.2 Dev NVFP4 32B - quantized fast generation and editing",
        "model_type": "pi_flux2_nvfp4",
        "preset_type": "i2i",
        "prompt_language_preference": "en",
        "supported_modes": ["t2i", "i2i"],
        "inference_steps": 4,
        "embedded_guidance_scale": 4.0,
        "supports_reference": True,
        "reference_mode": "KI",
        "supports_chinese": True,
    },
    "flux2_klein_4b": {
        "description": "Flux 2 Klein 4B - fast generation and editing",
        "model_type": "flux2_klein_4b",
        "preset_type": "i2i",
        "prompt_language_preference": "balanced",
        "supported_modes": ["t2i", "i2i"],
        "inference_steps": 4,
        "embedded_guidance_scale": 1.0,
        "supports_reference": True,
        "reference_mode": "KI",
        "supports_chinese": True,
    },
    "flux2_klein_9b": {
        "description": "Flux 2 Klein 9B - stronger generation and editing",
        "model_type": "flux2_klein_9b",
        "preset_type": "i2i",
        "prompt_language_preference": "balanced",
        "supported_modes": ["t2i", "i2i"],
        "inference_steps": 4,
        "embedded_guidance_scale": 1.0,
        "supports_reference": True,
        "reference_mode": "KI",
        "supports_chinese": True,
    },
    "flux2_klein_base_4b": {
        "description": "Flux 2 Klein Base 4B - non-distilled generation and editing",
        "model_type": "flux2_klein_base_4b",
        "preset_type": "i2i",
        "prompt_language_preference": "balanced",
        "supported_modes": ["t2i", "i2i"],
        "inference_steps": 30,
        "guidance_scale": 4.0,
        "supports_reference": True,
        "reference_mode": "KI",
        "supports_chinese": True,
    },
    "flux2_klein_base_9b": {
        "description": "Flux 2 Klein Base 9B - non-distilled generation and editing",
        "model_type": "flux2_klein_base_9b",
        "preset_type": "i2i",
        "prompt_language_preference": "balanced",
        "supported_modes": ["t2i", "i2i"],
        "inference_steps": 30,
        "guidance_scale": 4.0,
        "supports_reference": True,
        "reference_mode": "KI",
        "supports_chinese": True,
    },
    "flux_dev_kontext": {
        "description": "Flux Dev Kontext 12B - supports reference images",
        "model_type": "flux_dev_kontext",
        "preset_type": "i2i",
        "prompt_language_preference": "en",
        "inference_steps": 30,
        "embedded_guidance_scale": 2.5,
        "supports_reference": True,
        "reference_mode": "KI",
        "supports_chinese": False,
    },
    "flux_dev_kontext_dreamomni2": {
        "description": "Flux DreamOmni2 12B - multimodal edit",
        "model_type": "flux_dev_kontext_dreamomni2",
        "preset_type": "i2i",
        "prompt_language_preference": "en",
        "inference_steps": 30,
        "embedded_guidance_scale": 2.5,
        "supports_reference": True,
        "reference_mode": "KI",
        "supports_chinese": False,
    },
    "flux_dev_uso": {
        "description": "Flux USO Dev 12B - style transfer",
        "model_type": "flux_dev_uso",
        "preset_type": "i2i",
        "prompt_language_preference": "en",
        "inference_steps": 30,
        "embedded_guidance_scale": 4.0,
        "supports_reference": True,
        "reference_mode": "KI",
        "supports_chinese": False,
    },
    "flux_dev_umo": {
        "description": "Flux UMO 12B - multi image merge",
        "model_type": "flux_dev_umo",
        "preset_type": "i2i",
        "prompt_language_preference": "en",
        "default_resolution": "768x768",
        "supported_resolutions": [
            "768x768",
            "1024x1024",
            "768x1024",
            "1024x768",
            "512x1024",
            "1024x512",
            "768x512",
            "512x768",
        ],
        "inference_steps": 30,
        "embedded_guidance_scale": 4.0,
        "supports_reference": True,
        "reference_mode": "I",
        "supports_chinese": False,
    },
    "qwen_image_edit": {
        "description": "Qwen Image Edit 20B - multi subject edit",
        "model_type": "qwen_image_edit_20B",
        "preset_type": "i2i",
        "prompt_language_preference": "zh",
        "supported_modes": ["t2i", "i2i"],
        "inference_steps": 30,
        "guidance_scale": 4.0,
        "supports_reference": True,
        "reference_mode": "KI",
        "supports_chinese": True,
    },
    "qwen_image_edit_plus": {
        "description": "Qwen Image Edit Plus 20B - enhanced edit",
        "model_type": "qwen_image_edit_plus_20B",
        "preset_type": "i2i",
        "prompt_language_preference": "zh",
        "supported_modes": ["t2i", "i2i"],
        "inference_steps": 30,
        "guidance_scale": 4.0,
        "supports_reference": True,
        "reference_mode": "KI",
        "supports_chinese": True,
    },
    "qwen_image_edit_plus2": {
        "description": "Qwen Image Edit Plus (2511) 20B - improved identity preservation",
        "model_type": "qwen_image_edit_plus2_20B",
        "preset_type": "i2i",
        "prompt_language_preference": "zh",
        "supported_modes": ["t2i", "i2i"],
        "inference_steps": 30,
        "guidance_scale": 4.0,
        "supports_reference": True,
        "reference_mode": "KI",
        "supports_chinese": True,
    },
    "qwen_image_edit_plus_20B_nunchaku_r128_fp4": {
        "description": "Qwen Image Edit Plus (2509) Nunchaku FP4 20B - accelerated edit and generation",
        "model_type": "qwen_image_edit_plus_20B_nunchaku_r128_fp4",
        "preset_type": "i2i",
        "prompt_language_preference": "zh",
        "supported_modes": ["t2i", "i2i"],
        "inference_steps": 4,
        "guidance_scale": 1.0,
        "supports_reference": True,
        "reference_mode": "KI",
        "supports_chinese": True,
    },
}

WAN2GP_IMAGE_HIDDEN_PRESETS: set[str] = {"flux_dev_uso", "flux_dev_umo"}


def get_wan2gp_image_preset(preset_name: str) -> dict[str, Any]:
    if preset_name not in WAN2GP_IMAGE_MODEL_PRESETS:
        available = ", ".join(sorted(WAN2GP_IMAGE_MODEL_PRESETS.keys()))
        raise ValueError(f"Unknown Wan2GP image preset: {preset_name}. Available: {available}")

    preset = WAN2GP_IMAGE_MODEL_PRESETS[preset_name].copy()
    if "default_resolution" not in preset:
        preset["default_resolution"] = "1088x1920"
    if "supported_resolutions" not in preset:
        preset["supported_resolutions"] = COMMON_RESOLUTIONS
    raw_supported_modes = preset.get("supported_modes")
    supported_modes = [
        str(mode).strip()
        for mode in list(raw_supported_modes or [])
        if str(mode).strip() in {"t2i", "i2i"}
    ]
    if not supported_modes:
        preset_type = str(preset.get("preset_type") or "").strip()
        if preset_type in {"t2i", "i2i"}:
            supported_modes = [preset_type]
        else:
            supported_modes = ["i2i" if preset.get("supports_reference") else "t2i"]
    preset["supported_modes"] = list(dict.fromkeys(supported_modes))
    if "preset_type" not in preset:
        preset["preset_type"] = preset["supported_modes"][0]
    return preset


@lru_cache(maxsize=8)
def _load_defaults_metadata(
    defaults_dir_str: str,
) -> tuple[dict[str, list[dict[str, str]]], dict[str, dict[str, str]]]:
    metadata_by_architecture: dict[str, list[dict[str, str]]] = {}
    metadata_by_stem: dict[str, dict[str, str]] = {}
    defaults_dir = Path(defaults_dir_str)
    if not defaults_dir.exists() or not defaults_dir.is_dir():
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
    architecture = str(preset.get("model_type") or "").strip()
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
        display_name = fallback_display_name or str(preset.get("model_type") or "")
    if not description:
        description = str(preset.get("description") or "")
    return display_name, description


def get_wan2gp_image_presets(wan2gp_path: str | None = None) -> list[dict[str, Any]]:
    defaults_dir = None
    if wan2gp_path:
        defaults_dir = Path(wan2gp_path).expanduser() / "defaults"
    metadata_by_architecture, metadata_by_stem = (
        _load_defaults_metadata(str(defaults_dir)) if defaults_dir is not None else ({}, {})
    )

    presets: list[dict[str, Any]] = []
    for preset_name in sorted(WAN2GP_IMAGE_MODEL_PRESETS.keys()):
        if preset_name in WAN2GP_IMAGE_HIDDEN_PRESETS:
            continue
        preset = get_wan2gp_image_preset(preset_name)
        display_name, description = _resolve_preset_metadata(
            preset_name,
            preset,
            metadata_by_architecture,
            metadata_by_stem,
        )
        presets.append(
            {
                "id": preset_name,
                "display_name": display_name,
                "description": description,
                "preset_type": str(preset.get("preset_type", "t2i")),
                "supported_modes": [
                    str(mode).strip()
                    for mode in list(preset.get("supported_modes") or [])
                    if str(mode).strip()
                ],
                "supports_reference": bool(preset.get("supports_reference", False)),
                "supports_chinese": bool(preset.get("supports_chinese", False)),
                "prompt_language_preference": str(
                    preset.get("prompt_language_preference", "balanced")
                ),
                "default_resolution": str(preset.get("default_resolution", "1088x1920")),
                "supported_resolutions": list(
                    preset.get("supported_resolutions", COMMON_RESOLUTIONS)
                ),
                "inference_steps": int(preset.get("inference_steps", 30)),
            }
        )
    return presets


def _parse_resolution(resolution: str) -> tuple[int, int]:
    if "x" in resolution:
        w_text, h_text = resolution.split("x", maxsplit=1)
        return int(w_text), int(h_text)
    size = int(resolution)
    return size, size


def _resize_image_to_aspect_ratio(
    src_path: Path, target_width: int, target_height: int, output_dir: Path
) -> Path:
    img = Image.open(src_path)
    src_width, src_height = img.size
    target_ratio = target_width / target_height
    src_ratio = src_width / src_height

    if abs(src_ratio - target_ratio) >= 0.01:
        if src_ratio > target_ratio:
            new_width = int(src_height * target_ratio)
            left = (src_width - new_width) // 2
            img = img.crop((left, 0, left + new_width, src_height))
        else:
            new_height = int(src_width / target_ratio)
            top = (src_height - new_height) // 2
            img = img.crop((0, top, src_width, top + new_height))

    output_path = output_dir / f"ref_{src_path.name}"
    img.save(output_path, quality=95)
    return output_path


@dataclass
class Wan2GPBatchTask:
    task_id: str
    prompt: str
    output_path: Path
    resolution: str | None = None
    reference_images: list[Path] | None = None


class Wan2GPImageProvider(Wan2GPBase, ImageProvider):
    name = "wan2gp"
    supports_reference = True

    def __init__(
        self,
        wan2gp_path: str | None = None,
        python_executable: str | None = None,
        image_preset: str = "qwen_image_2512",
        image_resolution: str = "1088x1920",
        image_inference_steps: int = 0,
        image_guidance_scale: float = 0.0,
        seed: int = -1,
        negative_prompt: str = "",
    ):
        self.wan2gp_path = Path(wan2gp_path or "../Wan2GP")
        self.python_executable = python_executable
        self.preset_name = image_preset
        self.resolution_override = image_resolution
        self.steps_override = image_inference_steps
        self.guidance_override = image_guidance_scale
        self.seed = seed
        self.negative_prompt = negative_prompt

    def _get_image_config(self) -> dict[str, Any]:
        preset = get_wan2gp_image_preset(self.preset_name)
        guidance = preset.get("guidance_scale") or preset.get("embedded_guidance_scale", 2.5)
        if self.guidance_override > 0:
            guidance = self.guidance_override
        return {
            "model_type": preset["model_type"],
            "resolution": self.resolution_override or preset["default_resolution"],
            "inference_steps": self.steps_override or preset["inference_steps"],
            "guidance_scale": guidance,
            "seed": self.seed,
            "negative_prompt": self.negative_prompt,
            "supports_reference": bool(preset.get("supports_reference", False)),
            "reference_mode": str(preset.get("reference_mode", "")),
        }

    def _build_settings_payload(
        self,
        *,
        prompt: str,
        image_config: dict[str, Any],
        target_width: int,
        target_height: int,
        output_filename: str = "",
        image_refs: list[Path] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "settings_version": 2.43,
            "prompt": prompt,
            # Wan2GP defaults split prompt by newline and may consume only the first line for
            # single-window generations. Force "one full prompt" mode to preserve multi-line text.
            "multi_prompts_gen_type": 2,
            "model_type": image_config["model_type"],
            "type": image_config["model_type"],
            "resolution": f"{target_width}x{target_height}",
            "num_inference_steps": image_config["inference_steps"],
            "seed": image_config["seed"],
            "guidance_scale": image_config["guidance_scale"],
            "embedded_guidance_scale": image_config["guidance_scale"],
            "negative_prompt": image_config["negative_prompt"],
            "batch_size": 1,
            "image_mode": 1,
        }
        if output_filename:
            payload["output_filename"] = output_filename
        if image_config["supports_reference"] and image_refs:
            payload["video_prompt_type"] = image_config.get("reference_mode", "KI")
            payload["image_refs"] = [str(p) for p in image_refs]
            payload["denoising_strength"] = 1.0
        return payload

    async def _run_wgp(
        self,
        python_executable: str,
        settings_path: Path,
        output_dir: Path,
        expected_steps: int,
        progress_callback: Callable[[int], Awaitable[None]] | None = None,
        line_callback: Callable[[str], Awaitable[None]] | None = None,
        status_callback: Callable[[str], Awaitable[None]] | None = None,
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
        logger.info("[Wan2GP CLI] Start subprocess: %s", cmd_text)

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
        download_monitor_stop: asyncio.Event | None = None
        monitor_task: asyncio.Task[None] | None = None

        try:
            step_pattern = re.compile(r"(?:Step\s+)?(\d+)\s*/\s*(\d+)")
            prompt_pattern = re.compile(r"Prompt\s+(\d+)\s*/\s*(\d+)", re.IGNORECASE)
            ansi_escape_pattern = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
            download_progress_pattern = re.compile(r":\s*\d+%\|")
            download_start_pattern = re.compile(
                r"Downloading\s+['\"](?P<filename>[^'\"]+)['\"]",
                re.IGNORECASE,
            )
            tqdm_filename_pattern = re.compile(r"^(?P<filename>[^:\n]+?):\s*\d+(?:\.\d+)?%\|")
            output_tail: deque[str] = deque(maxlen=40)
            pending_text = ""
            last_progress_sent = 0
            current_prompt_marker: tuple[int, int] | None = None
            last_status_message: str | None = None
            process_start_ts = time.time()
            downloading_active = False
            loading_phase_active = False
            last_download_log_ts = 0.0
            last_download_progress_line: str | None = None
            last_download_progress_log_ts = 0.0
            download_progress_log_interval_seconds = 10.0
            download_lock_check_interval_seconds = 10.0
            current_download_filename: str | None = None

            async def emit_status(message: str) -> None:
                nonlocal last_status_message
                if not message:
                    return
                if message == last_status_message:
                    return
                last_status_message = message
                if status_callback:
                    try:
                        await status_callback(message)
                    except Exception:
                        pass

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
                        if loading_phase_active:
                            pass
                        elif not (
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
                nonlocal last_progress_sent
                nonlocal current_prompt_marker
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
                # Keep raw wan2gp runtime lines visible in backend logs (same style as CLI),
                # but throttle high-frequency tqdm refreshes to avoid log flooding.
                is_download_progress_line = (
                    bool(download_progress_pattern.search(cleaned)) and "/" in cleaned
                )
                should_log_cli_line = True
                if is_download_progress_line:
                    now = time.time()
                    if cleaned == last_download_progress_line:
                        should_log_cli_line = False
                    elif (
                        now - last_download_progress_log_ts < download_progress_log_interval_seconds
                        and "100%|" not in cleaned
                    ):
                        should_log_cli_line = False
                    if should_log_cli_line:
                        last_download_progress_line = cleaned
                        last_download_progress_log_ts = now
                if should_log_cli_line:
                    logger.info("[Wan2GP CLI] %s", cleaned)
                if line_callback:
                    try:
                        await line_callback(cleaned)
                    except Exception:
                        pass

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

                # Batch mode can generate multiple prompts in one subprocess run.
                # Reset monotonic guard when entering a new "Prompt x/y" scope.
                prompt_match = prompt_pattern.search(cleaned)
                if prompt_match:
                    prompt_marker = (int(prompt_match.group(1)), int(prompt_match.group(2)))
                    if prompt_marker != current_prompt_marker:
                        current_prompt_marker = prompt_marker
                        last_progress_sent = 0

                # A single log line may include multiple "x / y" fragments.
                # Use the highest valid progress candidate to avoid jitter.
                candidate_progress = None
                for step_match in step_pattern.finditer(cleaned):
                    current_step = int(step_match.group(1))
                    total = int(step_match.group(2))
                    if total <= 0:
                        continue

                    # Ignore unrelated fractions and only keep progress-like totals.
                    if expected_steps > 0:
                        tolerance = max(2, int(expected_steps * 0.3))
                        if abs(total - expected_steps) > tolerance:
                            continue

                    # Keep headroom for result move/metadata parse.
                    progress = int(
                        min(99, max(1, (current_step / max(total, expected_steps)) * 99))
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

                await emit_status(STATUS_GENERATING)

                # Some wgp outputs can briefly restart progress fragments (e.g. 99 -> 1).
                # Keep progress monotonic within one generation task.
                if candidate_progress < last_progress_sent:
                    return
                if candidate_progress == last_progress_sent:
                    return

                last_progress_sent = candidate_progress
                logger.info("[Wan2GP Image] 生成进度: %d%%", candidate_progress)
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
                hint = ""
                if any("No module named 'torch'" in line for line in output_tail):
                    hint = (
                        "\nHint: the selected python does not have torch installed. "
                        "Configure `local_model_python_path` to a Wan2GP environment "
                        "or install torch in this interpreter."
                    )
                raise RuntimeError(
                    "Wan2GP generation failed with return code "
                    f"{return_code}\n"
                    f"Command: {cmd_text}\n"
                    f"Last output lines:\n{tail_text}"
                    f"{hint}"
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

    async def generate(
        self,
        prompt: str,
        output_path: Path,
        width: int | None = None,
        height: int | None = None,
        reference_images: list[Path] | None = None,
        aspect_ratio: str | None = None,
        image_size: str | None = None,
        resolution: str | None = None,
        progress_callback: Callable[[int], Awaitable[None]] | None = None,
        status_callback: Callable[[str], Awaitable[None]] | None = None,
        **kwargs,
    ) -> ImageResult:
        del width, height, aspect_ratio, image_size, kwargs

        self._validate_config()
        python_executable = self._resolve_python_executable()

        image_config = self._get_image_config()
        final_resolution = resolution or image_config["resolution"]
        target_width, target_height = _parse_resolution(final_resolution)

        model_cached = self._is_model_cached(str(image_config["model_type"]))
        await emit_bootstrap_status(status_callback, model_cached)

        ref_images = reference_images
        temp_ref_dir: Path | None = None
        processed_refs: list[Path] = []
        if image_config["supports_reference"] and ref_images:
            valid_refs = [Path(p) for p in ref_images if p and Path(p).exists()]
            if valid_refs:
                temp_ref_dir = Path(tempfile.mkdtemp(prefix="wan2gp_refs_"))
                processed_refs = [
                    _resize_image_to_aspect_ratio(ref, target_width, target_height, temp_ref_dir)
                    for ref in valid_refs[:4]
                ]

        settings_payload = self._build_settings_payload(
            prompt=prompt,
            image_config=image_config,
            target_width=target_width,
            target_height=target_height,
            image_refs=processed_refs,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_dir = Path(tempfile.mkdtemp(prefix="wan2gp_img_out_"))
        settings_path = self.wan2gp_path / (
            f"_settings_img_{os.getpid()}_{int(time.time() * 1000)}_{output_path.stem}.json"
        )

        try:
            logger.info("[Wan2GP Image] Final prompt:\n%s", prompt)
            settings_path.write_text(
                json.dumps(settings_payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            start_time = time.time()
            output_tail = await self._run_wgp(
                python_executable=python_executable,
                settings_path=settings_path,
                output_dir=output_dir,
                expected_steps=int(image_config["inference_steps"]),
                progress_callback=progress_callback,
                status_callback=status_callback,
            )

            all_generated = [
                path
                for path in output_dir.rglob("*")
                if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
            ]
            generated = [
                path for path in all_generated if path.stat().st_mtime >= start_time - 0.01
            ]
            if not generated:
                generated = all_generated
            if not generated:
                cmd_hint = (
                    "\n".join(output_tail[-12:])
                    if output_tail
                    else "<no subprocess output captured>"
                )
                raise FileNotFoundError(
                    "Wan2GP did not output any image file. "
                    "Subprocess finished without non-zero exit code, but no image file was found in output dir.\n"
                    f"Output dir: {output_dir}\n"
                    f"Last output lines:\n{cmd_hint}"
                )

            latest = max(generated, key=lambda p: p.stat().st_mtime)
            target_path = output_path.with_suffix(latest.suffix.lower())
            if target_path.exists():
                target_path.unlink()
            shutil.move(str(latest), str(target_path))

            with Image.open(target_path) as img:
                actual_width, actual_height = img.size

            if progress_callback:
                try:
                    await progress_callback(100)
                except Exception:
                    pass

            return ImageResult(file_path=target_path, width=actual_width, height=actual_height)
        finally:
            if settings_path.exists():
                settings_path.unlink()
            if temp_ref_dir and temp_ref_dir.exists():
                shutil.rmtree(temp_ref_dir, ignore_errors=True)
            if output_dir.exists():
                shutil.rmtree(output_dir, ignore_errors=True)

    async def generate_batch(
        self,
        tasks: list[Wan2GPBatchTask],
        progress_callback: Callable[[str, int, str | None], Awaitable[None]] | None = None,
        status_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> dict[str, ImageResult]:
        if not tasks:
            return {}

        self._validate_config()
        python_executable = self._resolve_python_executable()
        image_config = self._get_image_config()
        model_cached = self._is_model_cached(str(image_config["model_type"]))
        await emit_bootstrap_status(status_callback, model_cached)

        output_dir = Path(tempfile.mkdtemp(prefix="wan2gp_batch_out_"))
        settings_path = self.wan2gp_path / (
            f"_settings_img_batch_{os.getpid()}_{int(time.time() * 1000)}.json"
        )
        temp_ref_root: Path | None = None

        task_info: dict[str, tuple[str, Path]] = {}
        payloads: list[dict[str, Any]] = []
        current_task_idx = -1
        completed_task_ids: set[str] = set()
        assigned_source_paths: set[Path] = set()
        results: dict[str, ImageResult] = {}

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
                if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
            ]

        def assign_result_for_task(task_id: str, candidates: list[Path]) -> ImageResult | None:
            if task_id in results:
                return results[task_id]

            output_key, output_path = task_info[task_id]
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
            if target_path.exists():
                target_path.unlink()
            shutil.move(str(picked), str(target_path))
            with Image.open(target_path) as img:
                width, height = img.size
            result = ImageResult(file_path=target_path, width=width, height=height)
            results[task_id] = result
            return result

        task_start_pattern = re.compile(r"\[Task\s+(\d+)\s*/\s*(\d+)\]")
        task_done_pattern = re.compile(r"Task\s+(\d+)\s+completed")

        try:
            for i, task in enumerate(tasks):
                final_resolution = task.resolution or image_config["resolution"]
                target_width, target_height = _parse_resolution(final_resolution)
                output_key = f"yf_batch_{i:04d}"
                task.output_path.parent.mkdir(parents=True, exist_ok=True)
                task_info[task.task_id] = (output_key, task.output_path)
                image_refs: list[Path] | None = None
                if image_config["supports_reference"] and task.reference_images:
                    if temp_ref_root is None:
                        temp_ref_root = Path(tempfile.mkdtemp(prefix="wan2gp_refs_batch_"))
                    safe_task_id = (
                        re.sub(r"[^0-9A-Za-z_.-]+", "_", task.task_id).strip("_") or f"task_{i}"
                    )
                    task_ref_dir = temp_ref_root / safe_task_id
                    task_ref_dir.mkdir(parents=True, exist_ok=True)
                    processed_refs: list[Path] = []
                    for ref in task.reference_images[:4]:
                        ref_path = Path(ref)
                        if not ref_path.exists():
                            continue
                        processed_refs.append(
                            _resize_image_to_aspect_ratio(
                                ref_path,
                                target_width,
                                target_height,
                                task_ref_dir,
                            )
                        )
                    if processed_refs:
                        image_refs = processed_refs
                payloads.append(
                    self._build_settings_payload(
                        prompt=task.prompt,
                        image_config=image_config,
                        target_width=target_width,
                        target_height=target_height,
                        output_filename=output_key,
                        image_refs=image_refs,
                    )
                )

            settings_path.write_text(
                json.dumps(payloads, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            start_time = time.time()

            async def on_line(line: str) -> None:
                nonlocal current_task_idx
                start_match = task_start_pattern.search(line)
                if start_match:
                    task_no = int(start_match.group(1))
                    if 1 <= task_no <= len(tasks):
                        current_task_idx = task_no - 1
                        task = tasks[current_task_idx]
                        logger.info(
                            "[Wan2GP CLI] [Task %d/%d] %s",
                            task_no,
                            len(tasks),
                            str(task.prompt or ""),
                        )
                    return

                done_match = task_done_pattern.search(line)
                if done_match:
                    task_no = int(done_match.group(1))
                    if 1 <= task_no <= len(tasks):
                        task_id = tasks[task_no - 1].task_id
                        completed_task_ids.add(task_id)
                        result = assign_result_for_task(task_id, collect_generated_paths())
                        await emit_progress(
                            task_id,
                            100,
                            str(result.file_path) if result else None,
                        )
                    return

            async def on_progress(progress: int) -> None:
                if not (0 <= current_task_idx < len(tasks)):
                    return
                task_id = tasks[current_task_idx].task_id
                if task_id in completed_task_ids:
                    return
                # Fallback: some CLI outputs may miss/merge "Task X completed" lines.
                # If this task's output file is already present, mark it completed immediately
                # so caller can persist per-item result without waiting for batch end.
                result = assign_result_for_task(task_id, collect_generated_paths())
                if result:
                    completed_task_ids.add(task_id)
                    await emit_progress(task_id, 100, str(result.file_path))
                    return
                await emit_progress(task_id, progress, None)

            output_tail = await self._run_wgp(
                python_executable=python_executable,
                settings_path=settings_path,
                output_dir=output_dir,
                expected_steps=int(image_config["inference_steps"]),
                progress_callback=on_progress,
                line_callback=on_line,
                status_callback=status_callback,
            )

            all_generated = collect_generated_paths()
            # In streaming mode we may have already moved files out of output_dir.
            # If all tasks are resolved, return early instead of treating empty temp dir as failure.
            if len(results) == len(tasks):
                return results

            if not all_generated and not results:
                tail_text = (
                    "\n".join(output_tail[-12:])
                    if output_tail
                    else "<no subprocess output captured>"
                )
                raise FileNotFoundError(
                    "Wan2GP batch run did not output any image file.\n"
                    f"Output dir: {output_dir}\n"
                    f"Last output lines:\n{tail_text}"
                )

            generated = [
                path for path in all_generated if path.stat().st_mtime >= start_time - 0.01
            ]
            if not generated:
                generated = all_generated

            missing_task_ids: list[str] = []
            for task in tasks:
                if task.task_id in results:
                    continue
                result = assign_result_for_task(task.task_id, generated)
                if result:
                    await emit_progress(task.task_id, 100, str(result.file_path))
                else:
                    logger.warning("[Wan2GP Batch] Missing output for task_id=%s", task.task_id)
                    missing_task_ids.append(task.task_id)

            if missing_task_ids:
                tail_text = (
                    "\n".join(output_tail[-12:])
                    if output_tail
                    else "<no subprocess output captured>"
                )
                raise FileNotFoundError(
                    "Wan2GP batch run finished but some task outputs are missing.\n"
                    f"Missing task IDs: {', '.join(missing_task_ids)}\n"
                    f"Output dir: {output_dir}\n"
                    f"Last output lines:\n{tail_text}"
                )

            return results
        finally:
            if settings_path.exists():
                settings_path.unlink()
            if temp_ref_root and temp_ref_root.exists():
                shutil.rmtree(temp_ref_root, ignore_errors=True)
            if output_dir.exists():
                shutil.rmtree(output_dir, ignore_errors=True)
