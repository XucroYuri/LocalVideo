from dataclasses import dataclass
from typing import Any

from app.config import settings


@dataclass
class VideoConfigResolver:
    video_provider_name: str
    aspect_ratio: str
    resolution_value: str
    video_model: str | None
    audio_gap_seconds: float
    max_concurrency: int
    effective_video_fit_mode: str
    vertex_resolution: int
    wan2gp_resolution: str
    wan2gp_t2v_preset: str
    wan2gp_i2v_preset: str
    wan2gp_inference_steps: int
    wan2gp_sliding_window_size: int
    wan2gp_negative_prompt: str
    vertex_negative_prompt: str
    provider_kwargs: dict[str, Any]

    @classmethod
    def resolve(
        cls,
        input_data: dict[str, Any] | None,
        config: dict[str, Any],
        *,
        single_take_enabled: bool = False,
    ) -> "VideoConfigResolver":
        stage_input = input_data or {}

        aspect_ratio = str(
            stage_input.get("video_aspect_ratio") or config.get("video_aspect_ratio") or ""
        ).strip()
        resolution_value = stage_input.get("resolution") or config.get("resolution") or "1080"
        video_model = stage_input.get("video_model") or config.get("video_model")
        video_provider_name = (
            str(
                stage_input.get("video_provider")
                or config.get("video_provider")
                or settings.default_video_provider
                or "volcengine_seedance"
            )
            .strip()
            .lower()
        )
        supported_video_providers = {
            "volcengine_seedance",
            "wan2gp",
        }
        if video_provider_name not in supported_video_providers:
            default_provider = str(settings.default_video_provider or "").strip().lower()
            video_provider_name = (
                default_provider
                if default_provider in supported_video_providers
                else "volcengine_seedance"
            )

        raw_audio_gap_seconds = (
            stage_input.get("audio_gap_seconds")
            if stage_input.get("audio_gap_seconds") is not None
            else config.get("audio_gap_seconds", 0.2)
        )
        try:
            audio_gap_seconds = max(0.0, float(raw_audio_gap_seconds))
        except (TypeError, ValueError):
            audio_gap_seconds = 0.2

        raw_max_concurrency = stage_input.get("max_concurrency", 2)
        try:
            max_concurrency = max(1, int(raw_max_concurrency))
        except (TypeError, ValueError):
            max_concurrency = 2

        requested_video_fit_mode = (
            str(stage_input.get("video_fit_mode") or config.get("video_fit_mode") or "truncate")
            .strip()
            .lower()
        )
        effective_video_fit_mode = "scale" if single_take_enabled else requested_video_fit_mode

        vertex_resolution = 0
        if resolution_value:
            try:
                vertex_resolution = int(str(resolution_value).replace("p", "").strip())
            except ValueError:
                vertex_resolution = 0

        wan2gp_resolution = (
            stage_input.get("video_wan2gp_resolution")
            or (
                stage_input.get("resolution")
                if isinstance(stage_input.get("resolution"), str)
                and "x" in str(stage_input.get("resolution"))
                else None
            )
            or config.get("video_wan2gp_resolution")
            or settings.video_wan2gp_resolution
        )
        wan2gp_t2v_preset = (
            stage_input.get("video_wan2gp_t2v_preset")
            or config.get("video_wan2gp_t2v_preset")
            or settings.video_wan2gp_t2v_preset
        )
        wan2gp_i2v_preset = (
            stage_input.get("video_wan2gp_i2v_preset")
            or config.get("video_wan2gp_i2v_preset")
            or settings.video_wan2gp_i2v_preset
        )
        raw_wan2gp_inference_steps = (
            stage_input.get("video_wan2gp_inference_steps")
            if stage_input.get("video_wan2gp_inference_steps") is not None
            else config.get("video_wan2gp_inference_steps")
        )
        try:
            wan2gp_inference_steps = int(raw_wan2gp_inference_steps or 0)
        except (TypeError, ValueError):
            wan2gp_inference_steps = 0
        if wan2gp_inference_steps < 0:
            wan2gp_inference_steps = 0

        raw_wan2gp_sliding_window_size = (
            stage_input.get("video_wan2gp_sliding_window_size")
            if stage_input.get("video_wan2gp_sliding_window_size") is not None
            else config.get("video_wan2gp_sliding_window_size")
        )
        try:
            wan2gp_sliding_window_size = int(raw_wan2gp_sliding_window_size or 0)
        except (TypeError, ValueError):
            wan2gp_sliding_window_size = 0
        if wan2gp_sliding_window_size < 0:
            wan2gp_sliding_window_size = 0

        try:
            wan2gp_fit_canvas = int(settings.wan2gp_fit_canvas)
        except (TypeError, ValueError):
            wan2gp_fit_canvas = 0
        if wan2gp_fit_canvas not in (0, 1, 2):
            wan2gp_fit_canvas = 0

        wan2gp_negative_prompt = settings.video_wan2gp_negative_prompt
        vertex_negative_prompt = str(
            stage_input.get("video_vertex_ai_negative_prompt")
            if stage_input.get("video_vertex_ai_negative_prompt") is not None
            else (
                config.get("video_vertex_ai_negative_prompt") if isinstance(config, dict) else None
            )
            or settings.video_vertex_ai_negative_prompt
            or ""
        ).strip()

        provider_kwargs: dict[str, Any]
        if video_provider_name == "volcengine_seedance":
            provider_kwargs = {
                "api_key": settings.video_seedance_api_key or "",
                "base_url": settings.video_seedance_base_url,
                "model": video_model or settings.video_seedance_model or "seedance-2-0",
                "aspect_ratio": aspect_ratio or settings.video_seedance_aspect_ratio,
                "resolution": (
                    str(resolution_value).strip()
                    if resolution_value is not None and str(resolution_value).strip()
                    else (settings.video_seedance_resolution or "720p")
                ),
                "watermark": False,
            }
        else:
            provider_kwargs = {
                "wan2gp_path": settings.wan2gp_path,
                "python_executable": settings.local_model_python_path,
                "t2v_preset": str(wan2gp_t2v_preset),
                "i2v_preset": str(wan2gp_i2v_preset),
                "resolution": str(wan2gp_resolution or ""),
                "negative_prompt": str(wan2gp_negative_prompt or ""),
                "inference_steps": wan2gp_inference_steps,
                "sliding_window_size": wan2gp_sliding_window_size,
                "fit_canvas": wan2gp_fit_canvas,
            }
            max_concurrency = 1

        return cls(
            video_provider_name=video_provider_name,
            aspect_ratio=aspect_ratio,
            resolution_value=resolution_value,
            video_model=video_model,
            audio_gap_seconds=audio_gap_seconds,
            max_concurrency=max_concurrency,
            effective_video_fit_mode=effective_video_fit_mode,
            vertex_resolution=vertex_resolution,
            wan2gp_resolution=wan2gp_resolution,
            wan2gp_t2v_preset=wan2gp_t2v_preset,
            wan2gp_i2v_preset=wan2gp_i2v_preset,
            wan2gp_inference_steps=wan2gp_inference_steps,
            wan2gp_sliding_window_size=wan2gp_sliding_window_size,
            wan2gp_negative_prompt=wan2gp_negative_prompt,
            vertex_negative_prompt=vertex_negative_prompt,
            provider_kwargs=provider_kwargs,
        )
