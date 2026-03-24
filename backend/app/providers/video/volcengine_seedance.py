"""Volcengine Seedance video provider."""

from __future__ import annotations

import asyncio
import base64
import logging
import math
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from app.providers.base.video import VideoProvider, VideoResult

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://kwjm.com"
RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
SEEDANCE_REFERENCE_SUPPORTED_MODELS = {"seedance-2-0", "seedance-2-0-fast", "seedance-1-0-lite-i2v"}
SEEDANCE_REFERENCE_MAX_IMAGES = 9
SEEDANCE_FRAME_RATE = 24.0
SEEDANCE_FRAMES_MIN = 29
SEEDANCE_FRAMES_MAX = 289
SEEDANCE_FRAMES_STEP = 4

SEEDANCE_MODEL_PRESETS: dict[str, dict[str, Any]] = {
    "seedance-2-0": {
        "model": "doubao-seedance-2-0",
        "display_name": "Seedance 2.0",
        "description": "Seedance 2.0（支持文生视频、图生视频、多模态参考）",
        "supports_t2v": True,
        "supports_i2v": True,
        "supports_last_frame": True,
        "supports_reference_image": True,
        "supports_reference_video": True,
        "supports_reference_audio": True,
        "max_reference_images": SEEDANCE_REFERENCE_MAX_IMAGES,
        "aspect_ratios": ["16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "adaptive"],
        "resolutions": ["480p", "720p"],
        "default_aspect_ratio": "adaptive",
        "default_resolution": "720p",
        "supported_durations": list(range(4, 16)),
        "duration_control": "duration",
    },
    "seedance-2-0-fast": {
        "model": "doubao-seedance-2-0-fast",
        "display_name": "Seedance 2.0 fast",
        "description": "Seedance 2.0 fast（支持文生视频、图生视频、多模态参考）",
        "supports_t2v": True,
        "supports_i2v": True,
        "supports_last_frame": True,
        "supports_reference_image": True,
        "supports_reference_video": True,
        "supports_reference_audio": True,
        "max_reference_images": SEEDANCE_REFERENCE_MAX_IMAGES,
        "aspect_ratios": ["16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "adaptive"],
        "resolutions": ["480p", "720p"],
        "default_aspect_ratio": "adaptive",
        "default_resolution": "720p",
        "supported_durations": list(range(4, 16)),
        "duration_control": "duration",
    },
    "seedance-1-5-pro": {
        "model": "doubao-seedance-1-5-pro-251215",
        "display_name": "Seedance 1.5 pro",
        "description": "Seedance 1.5 pro（支持文生视频与图生视频）",
        "supports_t2v": True,
        "supports_i2v": True,
        "supports_last_frame": True,
        "supports_reference_image": False,
        "max_reference_images": 0,
        "aspect_ratios": ["16:9", "9:16", "1:1"],
        "resolutions": ["480p", "720p", "1080p"],
        "default_aspect_ratio": "9:16",
        "default_resolution": "1080p",
        "supported_durations": [4, 5, 6, 7, 8, 9, 10, 11, 12],
        "duration_control": "duration",
    },
    "seedance-1-0-pro": {
        "model": "doubao-seedance-1-0-pro-250528",
        "display_name": "Seedance 1.0 pro",
        "description": "Seedance 1.0 pro（支持文生视频与图生视频）",
        "supports_t2v": True,
        "supports_i2v": True,
        "supports_last_frame": True,
        "supports_reference_image": False,
        "max_reference_images": 0,
        "aspect_ratios": ["16:9", "9:16", "1:1"],
        "resolutions": ["480p", "720p", "1080p"],
        "default_aspect_ratio": "9:16",
        "default_resolution": "1080p",
        "supported_durations": [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "duration_control": "frames",
        "frames_per_second": SEEDANCE_FRAME_RATE,
        "frames_min": SEEDANCE_FRAMES_MIN,
        "frames_max": SEEDANCE_FRAMES_MAX,
        "frames_step": SEEDANCE_FRAMES_STEP,
    },
    "seedance-1-0-pro-fast": {
        "model": "doubao-seedance-1-0-pro-fast-251015",
        "display_name": "Seedance 1.0 pro fast",
        "description": "Seedance 1.0 pro fast（支持文生视频与图生视频）",
        "supports_t2v": True,
        "supports_i2v": True,
        "supports_last_frame": True,
        "supports_reference_image": False,
        "max_reference_images": 0,
        "aspect_ratios": ["16:9", "9:16", "1:1"],
        "resolutions": ["480p", "720p", "1080p"],
        "default_aspect_ratio": "9:16",
        "default_resolution": "1080p",
        "supported_durations": [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "duration_control": "frames",
        "frames_per_second": SEEDANCE_FRAME_RATE,
        "frames_min": SEEDANCE_FRAMES_MIN,
        "frames_max": SEEDANCE_FRAMES_MAX,
        "frames_step": SEEDANCE_FRAMES_STEP,
    },
    "seedance-1-0-lite-t2v": {
        "model": "doubao-seedance-1-0-lite-t2v-250428",
        "display_name": "Seedance-1.0-lite-t2v",
        "description": "Seedance 1.0 lite t2v（文生视频）",
        "supports_t2v": True,
        "supports_i2v": False,
        "supports_last_frame": False,
        "supports_reference_image": False,
        "max_reference_images": 0,
        "aspect_ratios": ["16:9", "9:16", "1:1"],
        "resolutions": ["480p", "720p", "1080p"],
        "default_aspect_ratio": "9:16",
        "default_resolution": "720p",
        "supported_durations": [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "duration_control": "frames",
        "frames_per_second": SEEDANCE_FRAME_RATE,
        "frames_min": SEEDANCE_FRAMES_MIN,
        "frames_max": SEEDANCE_FRAMES_MAX,
        "frames_step": SEEDANCE_FRAMES_STEP,
    },
    "seedance-1-0-lite-i2v": {
        "model": "doubao-seedance-1-0-lite-i2v-250428",
        "display_name": "Seedance-1.0-lite-i2v",
        "description": "Seedance 1.0 lite i2v（图生视频）",
        "supports_t2v": False,
        "supports_i2v": True,
        "supports_last_frame": True,
        "supports_reference_image": True,
        "max_reference_images": SEEDANCE_REFERENCE_MAX_IMAGES,
        "aspect_ratios": ["16:9", "9:16", "1:1"],
        "resolutions": ["480p", "720p", "1080p"],
        "default_aspect_ratio": "9:16",
        "default_resolution": "720p",
        "supported_durations": [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "duration_control": "frames",
        "frames_per_second": SEEDANCE_FRAME_RATE,
        "frames_min": SEEDANCE_FRAMES_MIN,
        "frames_max": SEEDANCE_FRAMES_MAX,
        "frames_step": SEEDANCE_FRAMES_STEP,
    },
}

TERMINAL_SUCCESS_STATUSES = {"succeeded", "success", "completed", "finished"}
TERMINAL_FAILED_STATUSES = {"failed", "error", "cancelled", "canceled", "deleted", "rejected"}


def resolve_seedance_model_id(model: str | None) -> str:
    normalized = _normalize_model(model)
    preset = SEEDANCE_MODEL_PRESETS.get(normalized)
    if preset is None:
        return normalized
    resolved = str(preset.get("model") or "").strip()
    return resolved or normalized


def get_seedance_video_presets() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for preset_id in sorted(SEEDANCE_MODEL_PRESETS.keys()):
        preset = SEEDANCE_MODEL_PRESETS[preset_id]
        raw_supported = preset.get("supported_durations") or []
        supported_durations = [
            int(item) for item in raw_supported if isinstance(item, int | float) and int(item) > 0
        ]
        supported_durations = sorted(set(supported_durations))
        duration_min = int(preset.get("duration_min") or 0)
        duration_max = int(preset.get("duration_max") or 0)
        if supported_durations:
            duration_min = supported_durations[0]
            duration_max = supported_durations[-1]
        items.append(
            {
                "id": preset_id,
                "model": resolve_seedance_model_id(preset_id),
                "display_name": str(preset["display_name"]),
                "description": str(preset["description"]),
                "supports_t2v": bool(preset.get("supports_t2v", True)),
                "supports_i2v": bool(preset.get("supports_i2v", True)),
                "supports_last_frame": bool(preset.get("supports_last_frame", False)),
                "supports_reference_image": bool(preset.get("supports_reference_image", False)),
                "max_reference_images": int(preset.get("max_reference_images") or 0),
                "aspect_ratios": list(preset.get("aspect_ratios") or ["16:9", "9:16"]),
                "resolutions": list(preset.get("resolutions") or ["720p", "1080p"]),
                "default_aspect_ratio": str(preset.get("default_aspect_ratio") or "9:16"),
                "default_resolution": str(preset.get("default_resolution") or "1080p"),
                "duration_min": duration_min,
                "duration_max": duration_max,
                "supported_durations": supported_durations,
            }
        )
    return items


def _normalize_api_key(raw_api_key: str | None) -> str:
    value = str(raw_api_key or "").strip().strip("\"'").strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    return value


def _normalize_base_url(raw_base_url: str | None) -> str:
    raw = (raw_base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    if not raw:
        return DEFAULT_BASE_URL
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return DEFAULT_BASE_URL

    scheme = parsed.scheme
    host = parsed.netloc
    path = (parsed.path or "").rstrip("/")

    if host.endswith("kwjm.com"):
        if path in {"", "/v1", "/api", "/api/v1", "/api/v3"}:
            return urlunparse((scheme, host, "", "", "", "")).rstrip("/")
        return urlunparse((scheme, host, path, "", "", "")).rstrip("/")

    if path.endswith("/api/v3"):
        normalized_path = "/api/v3"
    elif path.endswith("/api/v1/online"):
        normalized_path = "/api/v3"
    elif path.endswith("/api/v1"):
        normalized_path = "/api/v3"
    elif path.endswith("/api"):
        normalized_path = "/api/v3"
    elif not path:
        normalized_path = "/api/v3"
    else:
        normalized_path = path

    return urlunparse((scheme, host, normalized_path, "", "", "")).rstrip("/")


def _normalize_resolution(value: str | int | None) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    if not text:
        return ""
    if text.endswith("p"):
        head = text[:-1].strip()
        if head.isdigit():
            return f"{head}p"
        return text
    if text.isdigit():
        return f"{text}p"
    if "x" in text:
        try:
            width_text, height_text = text.split("x", maxsplit=1)
            width = int(width_text.strip())
            height = int(height_text.strip())
            short_edge = min(width, height)
            if short_edge >= 1080:
                return "1080p"
            if short_edge >= 720:
                return "720p"
            return "480p"
        except Exception:
            return text
    return text


def _normalize_aspect_ratio(value: str | None) -> str:
    text = str(value or "").strip().replace("：", ":")
    if text in {"16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "adaptive"}:
        return text
    return "adaptive"


def _normalize_model(model: str | None) -> str:
    text = str(model or "").strip()
    if not text:
        return "seedance-2-0"
    return text


def _get_seedance_model_preset(model: str | None) -> dict[str, Any] | None:
    normalized = _normalize_model(model)
    preset = SEEDANCE_MODEL_PRESETS.get(normalized)
    if preset is not None:
        return preset

    for candidate in SEEDANCE_MODEL_PRESETS.values():
        candidate_model = str(candidate.get("model") or "").strip()
        if candidate_model and candidate_model == normalized:
            return candidate
    return None


def get_seedance_duration_control_mode(model: str | None) -> str:
    preset = _get_seedance_model_preset(model)
    mode = str((preset or {}).get("duration_control") or "duration").strip().lower()
    return mode if mode in {"duration", "frames"} else "duration"


def get_seedance_frame_duration_bounds_seconds(model: str | None) -> tuple[float, float] | None:
    preset = _get_seedance_model_preset(model)
    if preset is None or get_seedance_duration_control_mode(model) != "frames":
        return None

    fps = float(preset.get("frames_per_second") or SEEDANCE_FRAME_RATE)
    frame_min = _coerce_int(preset.get("frames_min"), SEEDANCE_FRAMES_MIN)
    frame_max = _coerce_int(preset.get("frames_max"), SEEDANCE_FRAMES_MAX)
    if fps <= 0 or frame_min <= 0 or frame_max < frame_min:
        return None
    return float(frame_min / fps), float(frame_max / fps)


def _should_disable_audio_by_default(model: str | None) -> bool:
    normalized = _normalize_model(model).lower()
    return normalized == "seedance-1-5-pro" or "doubao-seedance-1-5-pro" in normalized


def _guess_mime_type(image_path: Path) -> str:
    suffix = image_path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def _coerce_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _resolve_duration_seconds(model: str | None, duration: float | None) -> int:
    requested = _coerce_float(duration, 0.0) or 0.0
    if requested <= 0:
        return 0
    normalized = _normalize_model(model)
    preset = _get_seedance_model_preset(normalized)
    # Use ceil to avoid under-shooting requested speech duration.
    target = int(math.ceil(requested))
    if preset is None:
        return max(target, 1)

    raw_supported = preset.get("supported_durations")
    supported_durations: list[int] = []
    if isinstance(raw_supported, list):
        for item in raw_supported:
            value = _coerce_int(item, -1)
            if value > 0:
                supported_durations.append(value)
    if supported_durations:
        choices = sorted(set(supported_durations))
        for choice in choices:
            if target <= choice:
                return choice
        return choices[-1]

    duration_min = max(_coerce_int(preset.get("duration_min"), 1), 1)
    duration_max = max(_coerce_int(preset.get("duration_max"), duration_min), duration_min)
    return max(duration_min, min(target, duration_max))


def _resolve_seedance_frames(model: str | None, duration: float | None) -> int:
    requested = _coerce_float(duration, 0.0) or 0.0
    if requested <= 0:
        return 0
    preset = _get_seedance_model_preset(model)
    if preset is None or get_seedance_duration_control_mode(model) != "frames":
        return 0

    fps = float(preset.get("frames_per_second") or SEEDANCE_FRAME_RATE)
    frame_min = _coerce_int(preset.get("frames_min"), SEEDANCE_FRAMES_MIN)
    frame_max = _coerce_int(preset.get("frames_max"), SEEDANCE_FRAMES_MAX)
    frame_step = max(_coerce_int(preset.get("frames_step"), SEEDANCE_FRAMES_STEP), 1)
    if fps <= 0 or frame_min <= 0 or frame_max < frame_min:
        return 0

    target_frames = requested * fps
    allowed_frames = list(range(frame_min, frame_max + 1, frame_step))
    if not allowed_frames:
        return 0

    # Keep non-underflow behavior consistent with duration mode: choose the first allowed
    # frame count that is not shorter than the requested target.
    for frame in allowed_frames:
        if frame >= target_frames:
            return frame
    return allowed_frames[-1]


def _format_http_error(exc: httpx.HTTPStatusError) -> str:
    status = exc.response.status_code
    body_text = ""
    try:
        payload = exc.response.json()
        body_text = payload if isinstance(payload, str) else str(payload)
    except Exception:
        body_text = str(exc.response.text or "").strip()
    body_text = body_text[:1000]
    return f"HTTP {status}: {body_text}" if body_text else f"HTTP {status}"


class VolcengineSeedanceVideoProvider(VideoProvider):
    """Volcengine Seedance 视频生成 Provider。"""

    name = "volcengine_seedance"

    def __init__(
        self,
        api_key: str = "",
        base_url: str = DEFAULT_BASE_URL,
        model: str = "seedance-2-0",
        aspect_ratio: str = "adaptive",
        resolution: str = "720p",
        watermark: bool = False,
        seed: int = -1,
        poll_interval: float = 6.0,
        max_wait_time: float = 1800.0,
        request_timeout: float = 60.0,
        max_retries: int = 3,
        retry_interval: float = 2.0,
    ) -> None:
        self.api_key = _normalize_api_key(api_key)
        self.base_url = _normalize_base_url(base_url)
        self.model = _normalize_model(model)
        self.aspect_ratio = _normalize_aspect_ratio(aspect_ratio)
        self.resolution = _normalize_resolution(resolution) or "1080p"
        self.watermark = bool(watermark)
        self.seed = _coerce_int(seed, -1)
        self.poll_interval = max(float(poll_interval), 1.0)
        self.max_wait_time = max(float(max_wait_time), 30.0)
        self.request_timeout = max(float(request_timeout), 15.0)
        self.max_retries = max(_coerce_int(max_retries, 3), 1)
        self.retry_interval = max(float(retry_interval), 0.5)

    def _validate_config(self) -> None:
        if not self.api_key:
            raise ValueError("Seedance 需要配置 API Key。")
        if not self.base_url:
            raise ValueError("Seedance 需要配置 Base URL。")

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _resolve_model(self) -> str:
        return resolve_seedance_model_id(self.model)

    def _supports_last_frame(self, model: str | None = None) -> bool:
        resolved = _normalize_model(model if model is not None else self.model)
        preset = _get_seedance_model_preset(resolved)
        if not preset:
            lowered = resolved.lower()
            return (
                "seedance-1-5-pro" in lowered
                or "seedance-1-0-pro" in lowered
                or "seedance-1-0-lite-i2v" in lowered
            )
        return bool(preset.get("supports_last_frame", False))

    def _supports_reference_images(self, model: str | None = None) -> bool:
        resolved = _normalize_model(model if model is not None else self.model)
        preset = _get_seedance_model_preset(resolved)
        if preset is not None:
            return bool(preset.get("supports_reference_image", False))
        lowered = resolved.lower()
        return resolved in SEEDANCE_REFERENCE_SUPPORTED_MODELS or "seedance-1-0-lite-i2v" in lowered

    def _max_reference_images(self, model: str | None = None) -> int:
        resolved = _normalize_model(model if model is not None else self.model)
        preset = _get_seedance_model_preset(resolved)
        if preset is not None:
            return max(_coerce_int(preset.get("max_reference_images"), 0), 0)
        lowered = resolved.lower()
        if resolved in SEEDANCE_REFERENCE_SUPPORTED_MODELS or "seedance-1-0-lite-i2v" in lowered:
            return SEEDANCE_REFERENCE_MAX_IMAGES
        return 0

    def _resolve_aspect_ratio(self, aspect_ratio: str | None) -> str:
        if aspect_ratio:
            return _normalize_aspect_ratio(aspect_ratio)
        preset = _get_seedance_model_preset(self.model)
        if preset:
            return str(preset.get("default_aspect_ratio") or self.aspect_ratio)
        return self.aspect_ratio

    def _resolve_resolution(self, resolution: str | int | None) -> str:
        normalized = _normalize_resolution(resolution)
        if normalized:
            return normalized
        preset = _get_seedance_model_preset(self.model)
        if preset:
            return str(preset.get("default_resolution") or self.resolution)
        return self.resolution

    def _get_dimensions(
        self,
        resolution: str | int | None,
        aspect_ratio: str | None,
    ) -> tuple[int, int]:
        dimensions_map = {
            "480p": {
                "16:9": (864, 496),
                "4:3": (752, 560),
                "1:1": (640, 640),
                "3:4": (560, 752),
                "9:16": (496, 864),
                "21:9": (992, 432),
            },
            "720p": {
                "16:9": (1280, 720),
                "4:3": (1112, 834),
                "1:1": (960, 960),
                "3:4": (834, 1112),
                "9:16": (720, 1280),
                "21:9": (1470, 630),
            },
            "1080p": {
                "16:9": (1920, 1080),
                "1:1": (1080, 1080),
                "9:16": (1080, 1920),
            },
        }
        actual_resolution = self._resolve_resolution(resolution)
        actual_aspect = self._resolve_aspect_ratio(aspect_ratio)
        if actual_aspect == "adaptive":
            actual_aspect = "9:16"
        resolution_map = dimensions_map.get(actual_resolution) or dimensions_map["720p"]
        return resolution_map.get(actual_aspect, resolution_map["9:16"])

    def _build_content(
        self,
        prompt: str,
        first_frame: Path | None = None,
        last_frame: Path | None = None,
        reference_images: list[Path] | None = None,
        include_last_frame: bool = False,
        model: str | None = None,
    ) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]

        def append_image(image_path: Path, role: str | None = None) -> None:
            if not image_path.exists():
                return
            encoded = base64.b64encode(image_path.read_bytes()).decode("utf-8")
            mime_type = _guess_mime_type(image_path)
            payload: dict[str, Any] = {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
            }
            if role:
                payload["role"] = role
            content.append(payload)

        resolved_model = _normalize_model(model if model is not None else self._resolve_model())
        supports_reference_images = self._supports_reference_images(resolved_model)
        max_reference_images = self._max_reference_images(resolved_model)

        if first_frame is not None:
            append_image(first_frame, role="first_frame")

        if reference_images:
            filtered_reference_images: list[Path] = []
            seen_reference_paths: set[str] = set()
            for ref_path in reference_images:
                if first_frame is not None and ref_path == first_frame:
                    continue
                if last_frame is not None and ref_path == last_frame:
                    continue
                path_key = str(ref_path)
                if path_key in seen_reference_paths:
                    continue
                seen_reference_paths.add(path_key)
                filtered_reference_images.append(ref_path)

            if not supports_reference_images and filtered_reference_images:
                logger.warning(
                    "[Seedance Video] reference_images ignored because model does not support reference mode: model=%s count=%d",
                    resolved_model,
                    len(filtered_reference_images),
                )
                filtered_reference_images = []
            if max_reference_images > 0 and len(filtered_reference_images) > max_reference_images:
                logger.warning(
                    "[Seedance Video] reference_images exceed limit %d, truncated from %d (model=%s)",
                    max_reference_images,
                    len(filtered_reference_images),
                    resolved_model,
                )
                filtered_reference_images = filtered_reference_images[:max_reference_images]

            for ref_path in filtered_reference_images:
                append_image(ref_path, role="reference_image")

        if include_last_frame and last_frame is not None:
            append_image(last_frame, role="last_frame")
        return content

    def _build_payload(
        self,
        prompt: str,
        duration: float | None = None,
        aspect_ratio: str | None = None,
        resolution: str | int | None = None,
        first_frame: Path | None = None,
        last_frame: Path | None = None,
        reference_images: list[Path] | None = None,
        seed: int | None = None,
        watermark: bool | None = None,
    ) -> dict[str, Any]:
        resolved_model = self._resolve_model()
        target_duration = _resolve_duration_seconds(resolved_model, duration)
        target_frames = _resolve_seedance_frames(resolved_model, duration)

        effective_seed = self.seed if seed is None else _coerce_int(seed, -1)

        supports_last_frame = self._supports_last_frame(resolved_model)
        payload: dict[str, Any] = {
            "model": resolved_model,
            "content": self._build_content(
                prompt=prompt,
                first_frame=first_frame,
                last_frame=last_frame,
                reference_images=reference_images,
                include_last_frame=supports_last_frame,
                model=resolved_model,
            ),
            "ratio": self._resolve_aspect_ratio(aspect_ratio),
            "resolution": self._resolve_resolution(resolution),
            "watermark": self.watermark if watermark is None else bool(watermark),
        }
        if get_seedance_duration_control_mode(resolved_model) == "frames":
            if target_frames > 0:
                payload["frames"] = target_frames
        elif target_duration > 0:
            payload["duration"] = target_duration
        # Seedance 1.5 Pro should default to silent video generation.
        if _should_disable_audio_by_default(resolved_model) or _should_disable_audio_by_default(
            self.model
        ):
            payload["generate_audio"] = False
        if effective_seed >= 0:
            payload["seed"] = effective_seed
        return payload

    async def _request_with_retry(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_payload,
                )
                if response.status_code >= 400:
                    if (
                        response.status_code in RETRYABLE_STATUS_CODES
                        and attempt < self.max_retries - 1
                    ):
                        await asyncio.sleep(self.retry_interval * (2**attempt))
                        continue
                    response.raise_for_status()
                data = response.json()
                return data if isinstance(data, dict) else {"data": data}
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if (
                    exc.response.status_code in RETRYABLE_STATUS_CODES
                    and attempt < self.max_retries - 1
                ):
                    await asyncio.sleep(self.retry_interval * (2**attempt))
                    continue
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_interval * (2**attempt))
                    continue
                break
        if isinstance(last_error, httpx.HTTPStatusError):
            raise RuntimeError(_format_http_error(last_error)) from last_error
        if last_error is not None:
            raise RuntimeError(str(last_error)) from last_error
        raise RuntimeError("Unknown Seedance request failure")

    @staticmethod
    def _extract_task_id(payload: dict[str, Any]) -> str:
        candidates = [
            payload.get("id"),
            payload.get("task_id"),
        ]
        data_block = payload.get("data")
        if isinstance(data_block, dict):
            candidates.append(data_block.get("id"))
            candidates.append(data_block.get("task_id"))
        for item in candidates:
            text = str(item or "").strip()
            if text:
                return text
        raise ValueError(f"Seedance create task response missing task id: {payload}")

    @staticmethod
    def _extract_status(payload: dict[str, Any]) -> str:
        status = str(payload.get("status") or "").strip()
        if status:
            return status.lower()
        data_block = payload.get("data")
        if isinstance(data_block, dict):
            status = str(data_block.get("status") or "").strip().lower()
            if status:
                return status
        return ""

    @staticmethod
    def _extract_failure_reason(payload: dict[str, Any]) -> str:
        for key in ("message", "error_msg", "error"):
            value = payload.get(key)
            if value:
                return str(value)
        data_block = payload.get("data")
        if isinstance(data_block, dict):
            for key in ("message", "error_msg", "error"):
                value = data_block.get(key)
                if value:
                    return str(value)
        return ""

    @staticmethod
    def _extract_video_url(payload: dict[str, Any]) -> str:
        candidates: list[Any] = []
        candidates.extend(
            [
                payload.get("video_url"),
                payload.get("url"),
            ]
        )

        content_block = payload.get("content")
        if isinstance(content_block, dict):
            candidates.extend(
                [
                    content_block.get("video_url"),
                    content_block.get("url"),
                ]
            )
            video_urls = content_block.get("video_urls")
            if isinstance(video_urls, list):
                candidates.extend(video_urls)

        data_block = payload.get("data")
        if isinstance(data_block, dict):
            candidates.extend(
                [
                    data_block.get("video_url"),
                    data_block.get("url"),
                ]
            )
            nested_content = data_block.get("content")
            if isinstance(nested_content, dict):
                candidates.extend(
                    [
                        nested_content.get("video_url"),
                        nested_content.get("url"),
                    ]
                )
                nested_video_urls = nested_content.get("video_urls")
                if isinstance(nested_video_urls, list):
                    candidates.extend(nested_video_urls)

        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        raise ValueError(f"Seedance query response missing video_url: {payload}")

    @staticmethod
    def _extract_duration(payload: dict[str, Any]) -> float | None:
        for block in (payload, payload.get("content"), payload.get("data")):
            if not isinstance(block, dict):
                continue
            for key in ("duration", "video_duration", "duration_seconds"):
                value = _coerce_float(block.get(key))
                if value is not None and value > 0:
                    return value
            nested_content = block.get("content")
            if isinstance(nested_content, dict):
                for key in ("duration", "video_duration", "duration_seconds"):
                    value = _coerce_float(nested_content.get(key))
                    if value is not None and value > 0:
                        return value
        return None

    async def _create_task(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, Any],
    ) -> str:
        url = f"{self.base_url}/v1/videos/generations"
        response_payload = await self._request_with_retry(
            client=client,
            method="POST",
            url=url,
            headers=self._build_headers(),
            json_payload=payload,
        )
        return self._extract_task_id(response_payload)

    async def _query_task(
        self,
        client: httpx.AsyncClient,
        task_id: str,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/v1/videos/generations/{task_id}"
        return await self._request_with_retry(
            client=client,
            method="GET",
            url=url,
            headers=self._build_headers(),
        )

    async def _delete_task(
        self,
        client: httpx.AsyncClient,
        task_id: str,
    ) -> None:
        url = f"{self.base_url}/v1/videos/generations/{task_id}"
        try:
            await self._request_with_retry(
                client=client,
                method="DELETE",
                url=url,
                headers=self._build_headers(),
            )
        except Exception:
            logger.warning("[Seedance Video] Failed to delete task %s", task_id, exc_info=True)

    async def _download_video(
        self,
        client: httpx.AsyncClient,
        video_url: str,
    ) -> bytes:
        response = await client.get(video_url, timeout=max(self.request_timeout, 120.0))
        response.raise_for_status()
        return response.content

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
        progress_callback: Callable[[int], Awaitable[None]] | None = None,
        **kwargs,
    ) -> VideoResult:
        del width, height
        self._validate_config()
        seed_override = kwargs.get("seed")
        watermark_override = kwargs.get("watermark")
        if last_frame is not None and not self._supports_last_frame():
            logger.warning(
                "[Seedance Video] last_frame is ignored because model does not support it: model=%s",
                self._resolve_model(),
            )

        payload = self._build_payload(
            prompt=prompt,
            duration=duration,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            first_frame=first_frame,
            last_frame=last_frame,
            reference_images=reference_images,
            seed=seed_override if seed_override is not None else None,
            watermark=bool(watermark_override) if watermark_override is not None else None,
        )
        content_items = payload.get("content") if isinstance(payload, dict) else None
        image_items = (
            [
                item
                for item in (content_items or [])
                if isinstance(item, dict) and str(item.get("type") or "").strip() == "image_url"
            ]
            if isinstance(content_items, list)
            else []
        )
        first_frame_count = sum(
            1 for item in image_items if str(item.get("role") or "").strip() == "first_frame"
        )
        last_frame_count = sum(
            1 for item in image_items if str(item.get("role") or "").strip() == "last_frame"
        )
        reference_image_count = len(image_items) - first_frame_count - last_frame_count
        logger.info(
            "[Seedance Video] content summary model=%s first_frame=%d last_frame=%d reference_images=%d",
            payload.get("model"),
            first_frame_count,
            last_frame_count,
            max(reference_image_count, 0),
        )
        logger.info(
            "[Seedance Video] submit task model=%s ratio=%s resolution=%s duration=%s frames=%s requested_duration=%.3fs watermark=%s generate_audio=%s",
            payload.get("model"),
            payload.get("ratio"),
            payload.get("resolution"),
            payload.get("duration"),
            payload.get("frames"),
            float(duration or 0.0),
            payload.get("watermark"),
            payload.get("generate_audio"),
        )

        task_id = ""
        start_time = time.time()
        progress = 1
        final_payload: dict[str, Any] | None = None

        timeout = httpx.Timeout(self.request_timeout, connect=20.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                task_id = await self._create_task(client=client, payload=payload)
                logger.info("[Seedance Video] task submitted: %s", task_id)
                if progress_callback:
                    try:
                        await progress_callback(progress)
                    except Exception:
                        pass

                while True:
                    elapsed = time.time() - start_time
                    if elapsed > self.max_wait_time:
                        raise TimeoutError(f"视频生成超时，已等待 {int(self.max_wait_time)} 秒")

                    polled = await self._query_task(client=client, task_id=task_id)
                    status = self._extract_status(polled)
                    if status in TERMINAL_SUCCESS_STATUSES:
                        final_payload = polled
                        if progress_callback:
                            try:
                                await progress_callback(100)
                            except Exception:
                                pass
                        break

                    if status in TERMINAL_FAILED_STATUSES:
                        reason = self._extract_failure_reason(polled)
                        raise RuntimeError(reason or f"Seedance 任务失败，status={status}")

                    progress = min(progress + 8, 95)
                    if progress_callback:
                        try:
                            await progress_callback(progress)
                        except Exception:
                            pass
                    await asyncio.sleep(self.poll_interval)

                if final_payload is None:
                    raise RuntimeError("Seedance 任务完成状态异常：未获取到结果")

                video_url = self._extract_video_url(final_payload)
                video_data = await self._download_video(client=client, video_url=video_url)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(video_data)

                actual_duration = self._extract_duration(final_payload)
                if actual_duration is None:
                    requested_frames = _coerce_int(payload.get("frames"), 0)
                    if requested_frames > 0:
                        actual_duration = float(requested_frames / SEEDANCE_FRAME_RATE)
                    else:
                        actual_duration = float(max(_coerce_int(round(duration or 0), 1), 1))
                actual_fps = _coerce_int(fps, 24) if fps is not None else 24
                actual_width, actual_height = self._get_dimensions(
                    resolution=resolution,
                    aspect_ratio=aspect_ratio,
                )
                return VideoResult(
                    file_path=output_path,
                    duration=float(actual_duration),
                    width=int(actual_width),
                    height=int(actual_height),
                    fps=int(actual_fps),
                )
            except Exception:
                if task_id:
                    await self._delete_task(client=client, task_id=task_id)
                raise
