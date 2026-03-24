from __future__ import annotations

from math import floor
from typing import Any

from app.providers.video.kling import (
    DEFAULT_KLING_VIDEO_MODEL,
    KLING_VIDEO_MODEL_PRESETS,
    get_kling_video_preset,
)
from app.providers.video.minimax import (
    DEFAULT_MINIMAX_VIDEO_MODEL,
    MINIMAX_VIDEO_MODEL_PRESETS,
    get_minimax_video_preset,
    get_supported_minimax_video_durations,
    normalize_minimax_video_resolution,
)
from app.providers.video.vertex_ai import (
    VERTEX_AI_MODEL_PRESETS,
    VERTEX_LAST_FRAME_SUPPORTED_MODEL_KEYS,
    VERTEX_REFERENCE_SUBJECT_MODEL_KEYS,
)
from app.providers.video.vidu import (
    DEFAULT_VIDU_VIDEO_MODEL,
    VIDU_VIDEO_MODEL_PRESETS,
    get_vidu_video_preset,
)
from app.providers.video.volcengine_seedance import (
    SEEDANCE_MODEL_PRESETS,
    get_seedance_duration_control_mode,
    get_seedance_frame_duration_bounds_seconds,
)
from app.providers.video.wan2gp import (
    WAN2GP_I2V_MODEL_PRESETS,
    WAN2GP_T2V_MODEL_PRESETS,
    get_wan2gp_i2v_preset,
    get_wan2gp_t2v_preset,
    supports_wan2gp_last_frame_preset,
)


def _dedupe_positive_ints(values: list[int]) -> list[int]:
    return sorted({int(value) for value in values if int(value) > 0})


def _dedupe_non_empty_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _normalize_resolution_values(values: list[Any]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        if text.isdigit():
            text = f"{text}p"
        normalized.append(text)
    return _dedupe_non_empty_strings(normalized)


def get_video_model_capability(
    provider_name: str | None,
    model: str | None,
    mode: str | None,
) -> dict[str, Any] | None:
    provider = str(provider_name or "").strip().lower()
    model_name = str(model or "").strip()
    video_mode = str(mode or "t2v").strip().lower()

    if provider == "vertex_ai":
        resolved_model = model_name or "veo-3.1-fast-preview"
        preset = VERTEX_AI_MODEL_PRESETS.get(resolved_model) or VERTEX_AI_MODEL_PRESETS.get(
            "veo-3.1-fast-preview"
        )
        if not preset:
            return None
        supports_reference_image = resolved_model in VERTEX_REFERENCE_SUBJECT_MODEL_KEYS
        supports_last_frame = bool(
            preset.get(
                "supports_last_frame", resolved_model in VERTEX_LAST_FRAME_SUPPORTED_MODEL_KEYS
            )
        )
        return {
            "id": resolved_model,
            "label": resolved_model,
            "description": str(preset.get("description") or ""),
            "supports_t2v": True,
            "supports_i2v": True,
            "supports_last_frame": supports_last_frame,
            "supports_reference_image": supports_reference_image,
            "supports_combined_reference": False,
            "max_reference_images": 3 if supports_reference_image else 0,
            "supported_durations_seconds": _dedupe_positive_ints(
                list(preset.get("durations") or [])
            ),
            "supported_aspect_ratios": _dedupe_non_empty_strings(
                [str(item) for item in preset.get("aspect_ratios") or []]
            ),
            "supported_resolutions": _normalize_resolution_values(
                list(preset.get("resolutions") or [])
            ),
            "default_aspect_ratio": str(preset.get("default_aspect_ratio") or ""),
            "default_resolution": (
                f"{int(preset.get('default_resolution'))}p"
                if str(preset.get("default_resolution") or "").strip().isdigit()
                else str(preset.get("default_resolution") or "")
            ),
            "reference_restrictions": ["最多 3 张参考图", "每张图需为单一主体"]
            if supports_reference_image
            else [],
        }

    if provider == "volcengine_seedance":
        preset = SEEDANCE_MODEL_PRESETS.get(model_name)
        if not preset:
            return None
        return {
            "id": model_name,
            "label": str(preset.get("display_name") or model_name),
            "description": str(preset.get("description") or ""),
            "supports_t2v": bool(preset.get("supports_t2v", True)),
            "supports_i2v": bool(preset.get("supports_i2v", True)),
            "supports_last_frame": bool(preset.get("supports_last_frame", False)),
            "supports_reference_image": bool(preset.get("supports_reference_image", False)),
            "supports_combined_reference": False,
            "max_reference_images": int(preset.get("max_reference_images") or 0),
            "supported_durations_seconds": _dedupe_positive_ints(
                [int(item) for item in preset.get("supported_durations") or []]
            ),
            "supported_aspect_ratios": _dedupe_non_empty_strings(
                [str(item) for item in preset.get("aspect_ratios") or []]
            ),
            "supported_resolutions": _dedupe_non_empty_strings(
                [str(item) for item in preset.get("resolutions") or []]
            ),
            "default_aspect_ratio": str(preset.get("default_aspect_ratio") or ""),
            "default_resolution": str(preset.get("default_resolution") or ""),
            "reference_restrictions": ["参考图模式支持 1~4 张图片"]
            if bool(preset.get("supports_reference_image", False))
            else [],
        }

    if provider == "kling":
        resolved_model = model_name or DEFAULT_KLING_VIDEO_MODEL
        preset = get_kling_video_preset(resolved_model)
        return {
            "id": (
                resolved_model
                if resolved_model in KLING_VIDEO_MODEL_PRESETS
                else DEFAULT_KLING_VIDEO_MODEL
            ),
            "label": str(preset.get("display_name") or DEFAULT_KLING_VIDEO_MODEL),
            "description": str(preset.get("description") or ""),
            "supports_t2v": bool(preset.get("supports_t2v", True)),
            "supports_i2v": bool(preset.get("supports_i2v", True)),
            "supports_last_frame": bool(preset.get("supports_last_frame", True)),
            "supports_reference_image": bool(preset.get("supports_reference_image", False)),
            "supports_combined_reference": bool(preset.get("supports_combined_reference", False)),
            "max_reference_images": int(preset.get("max_reference_images") or 0),
            "supported_durations_seconds": _dedupe_positive_ints(
                [int(item) for item in preset.get("supported_durations") or []]
            ),
            "supported_aspect_ratios": _dedupe_non_empty_strings(
                [str(item) for item in preset.get("aspect_ratios") or []]
            ),
            "supported_resolutions": _dedupe_non_empty_strings(
                [str(item) for item in preset.get("resolutions") or []]
            ),
            "default_aspect_ratio": str(preset.get("default_aspect_ratio") or ""),
            "default_resolution": str(preset.get("default_resolution") or ""),
            "reference_restrictions": [],
        }

    if provider == "vidu":
        resolved_model = model_name or DEFAULT_VIDU_VIDEO_MODEL
        preset = get_vidu_video_preset(resolved_model)
        return {
            "id": (
                resolved_model
                if resolved_model in VIDU_VIDEO_MODEL_PRESETS
                else DEFAULT_VIDU_VIDEO_MODEL
            ),
            "label": str(preset.get("display_name") or DEFAULT_VIDU_VIDEO_MODEL),
            "description": str(preset.get("description") or ""),
            "supports_t2v": bool(preset.get("supports_t2v", True)),
            "supports_i2v": bool(preset.get("supports_i2v", True)),
            "supports_last_frame": bool(preset.get("supports_last_frame", True)),
            "supports_reference_image": bool(preset.get("supports_reference_image", False)),
            "supports_combined_reference": bool(preset.get("supports_combined_reference", False)),
            "max_reference_images": int(preset.get("max_reference_images") or 0),
            "supported_durations_seconds": _dedupe_positive_ints(
                [int(item) for item in preset.get("supported_durations") or []]
            ),
            "supported_aspect_ratios": _dedupe_non_empty_strings(
                [str(item) for item in preset.get("aspect_ratios") or []]
            ),
            "supported_resolutions": _dedupe_non_empty_strings(
                [str(item) for item in preset.get("resolutions") or []]
            ),
            "default_aspect_ratio": str(preset.get("default_aspect_ratio") or ""),
            "default_resolution": str(preset.get("default_resolution") or ""),
            "reference_restrictions": [],
        }

    if provider == "minimax":
        resolved_model = model_name or DEFAULT_MINIMAX_VIDEO_MODEL
        preset = get_minimax_video_preset(resolved_model)
        resolved_resolution = normalize_minimax_video_resolution(
            str(preset.get("default_resolution") or "1080P"),
            default="1080P",
        )
        return {
            "id": (
                resolved_model
                if resolved_model in MINIMAX_VIDEO_MODEL_PRESETS
                else DEFAULT_MINIMAX_VIDEO_MODEL
            ),
            "label": str(preset.get("display_name") or DEFAULT_MINIMAX_VIDEO_MODEL),
            "description": str(preset.get("description") or ""),
            "supports_t2v": bool(preset.get("supports_t2v", True)),
            "supports_i2v": bool(preset.get("supports_i2v", True)),
            "supports_last_frame": bool(preset.get("supports_last_frame", False)),
            "supports_reference_image": bool(preset.get("supports_reference_image", False)),
            "supports_combined_reference": bool(preset.get("supports_combined_reference", False)),
            "max_reference_images": int(preset.get("max_reference_images") or 0),
            "supported_durations_seconds": get_supported_minimax_video_durations(
                resolved_model,
                resolved_resolution,
            ),
            "supported_aspect_ratios": _dedupe_non_empty_strings(
                [str(item) for item in preset.get("aspect_ratios") or []]
            ),
            "supported_resolutions": _dedupe_non_empty_strings(
                [str(item) for item in preset.get("resolutions") or []]
            ),
            "default_aspect_ratio": str(preset.get("default_aspect_ratio") or ""),
            "default_resolution": resolved_resolution,
            "reference_restrictions": [],
        }

    if provider == "wan2gp":
        if video_mode == "i2v":
            preset_map = WAN2GP_I2V_MODEL_PRESETS
            preset = get_wan2gp_i2v_preset(model_name) if model_name in preset_map else None
        else:
            preset_map = WAN2GP_T2V_MODEL_PRESETS
            preset = get_wan2gp_t2v_preset(model_name) if model_name in preset_map else None
        if not preset:
            fps = 16
            max_frames = fps * 8
            supported_resolutions: list[str] = []
            default_resolution = ""
        else:
            fps = int(preset.get("frames_per_second") or 16)
            max_frames = int(preset.get("max_frames") or (fps * 8))
            supported_resolutions = _dedupe_non_empty_strings(
                [str(item) for item in preset.get("supported_resolutions") or []]
            )
            default_resolution = str(preset.get("default_resolution") or "")
        max_duration = max(1, floor(max_frames / fps)) if fps > 0 and max_frames > 0 else 8
        return {
            "id": model_name,
            "label": model_name,
            "description": str((preset or {}).get("description") or ""),
            "supports_t2v": video_mode != "i2v",
            "supports_i2v": video_mode == "i2v",
            "supports_last_frame": supports_wan2gp_last_frame_preset(
                model_name,
                mode=video_mode,
            ),
            "supports_reference_image": False,
            "supports_combined_reference": False,
            "max_reference_images": 0,
            "supported_durations_seconds": list(range(1, max_duration + 1)),
            "supported_aspect_ratios": [],
            "supported_resolutions": supported_resolutions,
            "default_aspect_ratio": "",
            "default_resolution": default_resolution,
            "reference_restrictions": [],
        }

    return None


def get_supported_durations_seconds(
    provider_name: str | None,
    model: str | None,
    mode: str | None,
) -> list[int]:
    provider = str(provider_name or "").strip().lower()
    capability = get_video_model_capability(provider_name, model, mode)
    supported = _dedupe_positive_ints(
        list((capability or {}).get("supported_durations_seconds") or [])
    )
    if supported:
        return supported
    if provider == "vertex_ai":
        return [4, 6, 8]
    if provider == "volcengine_seedance":
        return list(range(2, 13))
    if provider == "wan2gp":
        return list(range(2, 13))
    if provider == "minimax":
        return get_supported_minimax_video_durations(model, None)
    return []


def get_supported_aspect_ratios(
    provider_name: str | None,
    model: str | None,
    mode: str | None,
) -> list[str]:
    capability = get_video_model_capability(provider_name, model, mode)
    return _dedupe_non_empty_strings(list((capability or {}).get("supported_aspect_ratios") or []))


def get_supported_resolutions(
    provider_name: str | None,
    model: str | None,
    mode: str | None,
) -> list[str]:
    capability = get_video_model_capability(provider_name, model, mode)
    return _dedupe_non_empty_strings(list((capability or {}).get("supported_resolutions") or []))


def supports_last_frame(
    provider_name: str | None,
    model: str | None,
    mode: str | None,
) -> bool:
    capability = get_video_model_capability(provider_name, model, mode)
    return bool((capability or {}).get("supports_last_frame", False))


def supports_reference_image(
    provider_name: str | None,
    model: str | None,
    mode: str | None,
) -> bool:
    capability = get_video_model_capability(provider_name, model, mode)
    return bool((capability or {}).get("supports_reference_image", False))


def supports_combined_reference(
    provider_name: str | None,
    model: str | None,
    mode: str | None,
) -> bool:
    capability = get_video_model_capability(provider_name, model, mode)
    return bool((capability or {}).get("supports_combined_reference", False))


def get_max_reference_images(
    provider_name: str | None,
    model: str | None,
    mode: str | None,
) -> int:
    capability = get_video_model_capability(provider_name, model, mode)
    return int((capability or {}).get("max_reference_images") or 0)


def choose_supported_duration_seconds(
    provider_name: str | None,
    model: str | None,
    mode: str | None,
    target_seconds: float,
) -> int | None:
    supported = get_supported_durations_seconds(provider_name, model, mode)
    if not supported:
        return None

    safe_target = max(float(target_seconds or 0.0), 0.0)
    for duration in supported:
        if duration >= safe_target:
            return duration
    return None


def resolve_requested_duration_seconds(
    provider_name: str | None,
    model: str | None,
    mode: str | None,
    target_seconds: float,
) -> float | None:
    provider = str(provider_name or "").strip().lower()
    safe_target = max(float(target_seconds or 0.0), 0.0)
    if safe_target <= 0:
        return None

    if provider == "volcengine_seedance" and get_seedance_duration_control_mode(model) == "frames":
        bounds = get_seedance_frame_duration_bounds_seconds(model)
        if bounds is None:
            return safe_target
        min_seconds, max_seconds = bounds
        if safe_target < min_seconds or safe_target > max_seconds:
            return None
        return safe_target

    if provider == "wan2gp":
        supported = get_supported_durations_seconds(provider_name, model, mode)
        if supported and safe_target > float(max(supported)):
            return None
        return safe_target

    selected = choose_supported_duration_seconds(provider_name, model, mode, safe_target)
    return float(selected) if selected is not None else None


def get_recommended_single_generation_limit_seconds(
    provider_name: str | None,
    model: str | None,
    mode: str | None,
    *,
    wan2gp_sliding_window_size: int | None = None,
) -> float | None:
    provider = str(provider_name or "").strip().lower()
    video_mode = str(mode or "t2v").strip().lower()

    if provider == "wan2gp":
        preset = None
        if video_mode == "i2v":
            if model and model in WAN2GP_I2V_MODEL_PRESETS:
                preset = get_wan2gp_i2v_preset(str(model))
        else:
            if model and model in WAN2GP_T2V_MODEL_PRESETS:
                preset = get_wan2gp_t2v_preset(str(model))

        fps = int((preset or {}).get("frames_per_second") or 16)
        if fps <= 0:
            fps = 16

        sliding_window = wan2gp_sliding_window_size
        if sliding_window is None:
            raw_window = (preset or {}).get("sliding_window_size")
            try:
                parsed_window = int(raw_window)
            except (TypeError, ValueError):
                parsed_window = 0
            sliding_window = parsed_window if parsed_window > 0 else None

        if sliding_window is None:
            return 5.0
        return max(float(sliding_window) / float(fps), 0.0)

    supported = get_supported_durations_seconds(provider_name, model, mode)
    if supported:
        return float(max(supported))

    capability = get_video_model_capability(provider_name, model, mode)
    raw_supported = list((capability or {}).get("supported_durations_seconds") or [])
    deduped = _dedupe_positive_ints(raw_supported)
    if deduped:
        return float(max(deduped))
    return None


def get_theoretical_single_generation_limit_seconds(
    provider_name: str | None,
    model: str | None,
    mode: str | None,
) -> float | None:
    capability = get_video_model_capability(provider_name, model, mode)
    supported = _dedupe_positive_ints(
        list((capability or {}).get("supported_durations_seconds") or [])
    )
    if supported:
        return float(max(supported))
    return get_recommended_single_generation_limit_seconds(provider_name, model, mode)
