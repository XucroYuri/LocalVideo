"""MiniMax video generation provider (t2v / i2v)."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.providers.base.video import VideoProvider, VideoResult

logger = logging.getLogger(__name__)

TERMINAL_SUCCESS_STATUSES = {"success", "succeed", "succeeded", "completed", "finished"}
TERMINAL_FAILED_STATUSES = {"fail", "failed", "error", "cancelled", "canceled", "rejected"}
DEFAULT_MINIMAX_BASE_URL = "https://api.minimaxi.com/v1"
DEFAULT_MINIMAX_VIDEO_MODEL = "MiniMax-Hailuo-2.3"
MINIMAX_VIDEO_MODEL_PRESETS: dict[str, dict[str, Any]] = {
    "MiniMax-Hailuo-2.3": {
        "display_name": "MiniMax Hailuo 2.3",
        "description": "支持文生视频与图生视频",
        "supports_t2v": True,
        "supports_i2v": True,
        "supports_last_frame": False,
        "supports_reference_image": False,
        "supports_combined_reference": False,
        "max_reference_images": 0,
        "aspect_ratios": ["16:9", "9:16", "1:1"],
        "resolutions": ["768P", "1080P"],
        "default_aspect_ratio": "9:16",
        "default_resolution": "1080P",
        "supported_durations_by_resolution": {
            "768P": [6, 10],
            "1080P": [6],
        },
    },
    "MiniMax-Hailuo-2.3-Fast": {
        "display_name": "MiniMax Hailuo 2.3 Fast",
        "description": "仅支持图生视频，生成速度更快",
        "supports_t2v": False,
        "supports_i2v": True,
        "supports_last_frame": False,
        "supports_reference_image": False,
        "supports_combined_reference": False,
        "max_reference_images": 0,
        "aspect_ratios": ["16:9", "9:16", "1:1"],
        "resolutions": ["768P", "1080P"],
        "default_aspect_ratio": "9:16",
        "default_resolution": "1080P",
        "supported_durations_by_resolution": {
            "768P": [6, 10],
            "1080P": [6],
        },
    },
}
MINIMAX_VIDEO_ASPECT_RATIOS = ["16:9", "9:16", "1:1"]
MINIMAX_VIDEO_RESOLUTIONS = ["768P", "1080P"]


def normalize_minimax_api_key(raw_api_key: str | None) -> str:
    value = str(raw_api_key or "").strip().strip("\"'").strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    return value


def normalize_minimax_base_url(raw_base_url: str | None) -> str:
    normalized = str(raw_base_url or DEFAULT_MINIMAX_BASE_URL).strip().rstrip("/")
    parsed = urlparse(normalized)
    if not parsed.scheme or not parsed.netloc:
        return DEFAULT_MINIMAX_BASE_URL
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/v1"):
        return normalized
    if path:
        return f"{normalized}/v1"
    return f"{normalized}/v1"


def get_minimax_video_preset(model: str | None) -> dict[str, Any]:
    normalized = str(model or "").strip()
    preset = (
        MINIMAX_VIDEO_MODEL_PRESETS.get(normalized)
        or MINIMAX_VIDEO_MODEL_PRESETS[DEFAULT_MINIMAX_VIDEO_MODEL]
    )
    return dict(preset)


def normalize_minimax_video_model(value: Any, default: str = DEFAULT_MINIMAX_VIDEO_MODEL) -> str:
    normalized = str(value or default).strip() or default
    return normalized if normalized in MINIMAX_VIDEO_MODEL_PRESETS else default


def normalize_minimax_video_aspect_ratio(
    value: Any,
    *,
    default: str = "9:16",
) -> str:
    normalized = str(value or default).strip().replace("：", ":")
    if normalized in MINIMAX_VIDEO_ASPECT_RATIOS:
        return normalized
    fallback = str(default or "9:16").strip().replace("：", ":")
    return fallback if fallback in MINIMAX_VIDEO_ASPECT_RATIOS else "9:16"


def normalize_minimax_video_resolution(
    value: Any,
    *,
    default: str = "1080P",
) -> str:
    normalized = str(value or default).strip().upper()
    if normalized in {"768", "768P"}:
        return "768P"
    if normalized in {"1080", "1080P"}:
        return "1080P"
    fallback = str(default or "1080P").strip().upper()
    if fallback in {"768", "768P"}:
        return "768P"
    if fallback in {"1080", "1080P"}:
        return "1080P"
    return "1080P"


def get_supported_minimax_video_durations(
    model: str | None,
    resolution: str | None,
) -> list[int]:
    preset = get_minimax_video_preset(model)
    normalized_resolution = normalize_minimax_video_resolution(
        resolution,
        default=str(preset.get("default_resolution") or "1080P"),
    )
    durations = preset.get("supported_durations_by_resolution") or {}
    candidates = durations.get(normalized_resolution) or durations.get(
        str(preset.get("default_resolution") or "1080P")
    )
    return [int(item) for item in (candidates or [6]) if int(item) > 0]


def normalize_minimax_video_duration(
    value: Any,
    *,
    model: str | None,
    resolution: str | None,
    default: int = 6,
) -> int:
    supported = get_supported_minimax_video_durations(model, resolution)
    fallback = default if default in supported else supported[0]
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError):
        parsed = fallback
    if parsed in supported:
        return parsed
    for candidate in supported:
        if candidate >= parsed:
            return candidate
    return supported[-1]


def _extract_error_message(payload: Any) -> str:
    if isinstance(payload, dict):
        base_resp = payload.get("base_resp")
        if isinstance(base_resp, dict):
            message = str(base_resp.get("status_msg") or "").strip()
            if message:
                return message
        for key in ("error_message", "message", "msg", "detail", "error"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _extract_http_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        payload = None
    message = _extract_error_message(payload)
    if message:
        return message
    return response.text.strip() or f"HTTP {response.status_code}"


def _extract_task_id(payload: dict[str, Any]) -> str:
    return str(payload.get("task_id") or payload.get("id") or "").strip()


def _extract_status(payload: dict[str, Any]) -> str:
    return str(payload.get("status") or payload.get("state") or "").strip().lower()


def _extract_file_id(payload: dict[str, Any]) -> str:
    file_id = str(payload.get("file_id") or "").strip()
    if file_id:
        return file_id
    data = payload.get("data")
    if isinstance(data, dict):
        return str(data.get("file_id") or "").strip()
    return ""


def _extract_download_url(payload: dict[str, Any]) -> str:
    file_info = payload.get("file")
    if isinstance(file_info, dict):
        return str(file_info.get("download_url") or file_info.get("url") or "").strip()
    return ""


def _guess_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def _encode_image_to_data_uri(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{_guess_mime_type(path)};base64,{encoded}"


async def _probe_video_metadata(video_path: Path) -> tuple[float, int, int, int]:
    import asyncio.subprocess
    import json

    process = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(video_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await process.communicate()
    if process.returncode != 0:
        return 0.0, 0, 0, 0
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except Exception:
        return 0.0, 0, 0, 0
    width = 0
    height = 0
    fps = 0
    streams = payload.get("streams")
    if isinstance(streams, list):
        for stream in streams:
            if not isinstance(stream, dict):
                continue
            if str(stream.get("codec_type") or "") != "video":
                continue
            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
            rate_text = str(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "")
            if "/" in rate_text:
                numerator, denominator = rate_text.split("/", 1)
                try:
                    den = float(denominator)
                    fps = int(round(float(numerator) / den)) if den else 0
                except (TypeError, ValueError, ZeroDivisionError):
                    fps = 0
            break
    duration = 0.0
    file_format = payload.get("format")
    if isinstance(file_format, dict):
        try:
            duration = float(file_format.get("duration") or 0.0)
        except (TypeError, ValueError):
            duration = 0.0
    return duration, width, height, fps


def list_minimax_video_presets() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model_id in MINIMAX_VIDEO_MODEL_PRESETS:
        preset = get_minimax_video_preset(model_id)
        durations = sorted(
            {
                int(duration)
                for items in (preset.get("supported_durations_by_resolution") or {}).values()
                for duration in items
                if int(duration) > 0
            }
        )
        rows.append(
            {
                "id": model_id,
                "label": str(preset.get("display_name") or model_id),
                "description": str(preset.get("description") or ""),
                "supports_t2v": bool(preset.get("supports_t2v", True)),
                "supports_i2v": bool(preset.get("supports_i2v", True)),
                "supports_last_frame": bool(preset.get("supports_last_frame", False)),
                "supports_reference_image": bool(preset.get("supports_reference_image", False)),
                "supports_combined_reference": bool(
                    preset.get("supports_combined_reference", False)
                ),
                "max_reference_images": int(preset.get("max_reference_images") or 0),
                "supported_aspect_ratios": list(preset.get("aspect_ratios") or []),
                "supported_resolutions": list(preset.get("resolutions") or []),
                "default_aspect_ratio": str(preset.get("default_aspect_ratio") or "9:16"),
                "default_resolution": str(preset.get("default_resolution") or "1080P"),
                "supported_durations_seconds": durations,
            }
        )
    return rows


class MiniMaxVideoProvider(VideoProvider):
    name = "minimax"

    def __init__(
        self,
        api_key: str = "",
        base_url: str = DEFAULT_MINIMAX_BASE_URL,
        model: str = DEFAULT_MINIMAX_VIDEO_MODEL,
        aspect_ratio: str = "9:16",
        resolution: str = "1080P",
        timeout: float = 300.0,
        poll_interval: float = 5.0,
        max_wait_time: float = 900.0,
    ) -> None:
        self.api_key = normalize_minimax_api_key(api_key)
        self.base_url = normalize_minimax_base_url(base_url)
        self.model = normalize_minimax_video_model(model)
        self.aspect_ratio = normalize_minimax_video_aspect_ratio(aspect_ratio, default="9:16")
        self.resolution = normalize_minimax_video_resolution(resolution, default="1080P")
        self.timeout = max(float(timeout or 300.0), 30.0)
        self.poll_interval = max(float(poll_interval or 5.0), 1.0)
        self.max_wait_time = max(float(max_wait_time or 900.0), self.poll_interval)

    def _validate_config(self) -> None:
        if not self.api_key:
            raise ValueError("MiniMax 视频生成需要配置 API Key")

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _query_task(self, client: httpx.AsyncClient, task_id: str) -> dict[str, Any]:
        response = await client.get(
            f"{self.base_url}/query/video_generation",
            headers=self._build_headers(),
            params={"task_id": task_id},
        )
        if response.status_code >= 400:
            raise RuntimeError(f"MiniMax 视频查询任务失败: {_extract_http_error_message(response)}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"MiniMax 视频查询响应结构异常: {payload}")
        return payload

    async def _retrieve_file(self, client: httpx.AsyncClient, file_id: str) -> dict[str, Any]:
        response = await client.get(
            f"{self.base_url}/files/retrieve",
            headers=self._build_headers(),
            params={"file_id": file_id},
        )
        if response.status_code >= 400:
            raise RuntimeError(f"MiniMax 视频文件查询失败: {_extract_http_error_message(response)}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"MiniMax 视频文件响应结构异常: {payload}")
        return payload

    @staticmethod
    async def _download_video(client: httpx.AsyncClient, video_url: str, output_path: Path) -> None:
        response = await client.get(video_url, follow_redirects=True)
        response.raise_for_status()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)

    async def generate(
        self,
        prompt: str,
        output_path: Path,
        duration: float | None = None,
        width: int | None = None,
        height: int | None = None,
        fps: int | None = None,
        resolution: int | None = None,
        aspect_ratio: str | None = None,
        first_frame: Path | None = None,
        last_frame: Path | None = None,
        reference_images: list[Path] | None = None,
        progress_callback=None,
    ) -> VideoResult:
        del width, height, fps, reference_images
        self._validate_config()
        content = str(prompt or "").strip()
        if not content:
            raise ValueError("提示词为空，无法生成视频")
        if last_frame is not None:
            raise ValueError("MiniMax 当前接入暂不支持尾帧视频生成")

        resolved_model = normalize_minimax_video_model(self.model)
        preset = get_minimax_video_preset(resolved_model)
        resolved_aspect_ratio = normalize_minimax_video_aspect_ratio(
            aspect_ratio or self.aspect_ratio,
            default=str(preset.get("default_aspect_ratio") or "9:16"),
        )
        resolution_input = (
            f"{int(resolution)}P"
            if isinstance(resolution, int) and resolution > 0
            else self.resolution
        )
        resolved_resolution = normalize_minimax_video_resolution(
            resolution_input,
            default=str(preset.get("default_resolution") or "1080P"),
        )
        resolved_duration = normalize_minimax_video_duration(
            duration,
            model=resolved_model,
            resolution=resolved_resolution,
            default=6,
        )
        supports_t2v = bool(preset.get("supports_t2v", True))
        supports_i2v = bool(preset.get("supports_i2v", True))
        if first_frame is None and not supports_t2v:
            raise ValueError(f"MiniMax 视频模型不支持文生视频: {resolved_model}")
        if first_frame is not None and not supports_i2v:
            raise ValueError(f"MiniMax 视频模型不支持图生视频: {resolved_model}")

        request_payload: dict[str, Any] = {
            "model": resolved_model,
            "prompt": content,
            "duration": resolved_duration,
            "resolution": resolved_resolution,
            "aspect_ratio": resolved_aspect_ratio,
        }
        if first_frame is not None:
            if not first_frame.exists():
                raise ValueError("首帧图不存在，无法生成视频")
            request_payload["first_frame_image"] = _encode_image_to_data_uri(first_frame)
        else:
            request_payload["prompt_optimizer"] = True
            request_payload["fast_pretreatment"] = False
        if resolved_aspect_ratio:
            request_payload["prompt"] = content

        timeout = httpx.Timeout(self.timeout, connect=20.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=True) as client:
            response = await client.post(
                f"{self.base_url}/video_generation",
                headers=self._build_headers(),
                json=request_payload,
            )
            if response.status_code >= 400:
                raise RuntimeError(f"MiniMax 视频请求失败: {_extract_http_error_message(response)}")
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError(f"MiniMax 视频响应结构异常: {payload}")
            task_id = _extract_task_id(payload)
            if not task_id:
                raise RuntimeError(f"MiniMax 视频响应缺少 task_id: {payload}")

            started_at = time.monotonic()
            last_progress = 5
            if callable(progress_callback):
                await progress_callback(last_progress)

            while True:
                if time.monotonic() - started_at > self.max_wait_time:
                    raise TimeoutError("MiniMax 视频生成超时")
                await asyncio.sleep(self.poll_interval)
                queried_payload = await self._query_task(client, task_id)
                status = _extract_status(queried_payload)
                if status in TERMINAL_FAILED_STATUSES:
                    message = _extract_error_message(queried_payload)
                    raise RuntimeError(f"MiniMax 视频任务失败: {message or status}")
                if status in TERMINAL_SUCCESS_STATUSES:
                    file_id = _extract_file_id(queried_payload)
                    if not file_id:
                        raise RuntimeError(f"MiniMax 视频任务成功但缺少 file_id: {queried_payload}")
                    file_payload = await self._retrieve_file(client, file_id)
                    download_url = _extract_download_url(file_payload)
                    if not download_url:
                        raise RuntimeError(f"MiniMax 视频文件响应缺少下载地址: {file_payload}")
                    await self._download_video(client, download_url, output_path)
                    if callable(progress_callback):
                        await progress_callback(100)
                    break
                if callable(progress_callback):
                    last_progress = min(95, last_progress + 10)
                    await progress_callback(last_progress)

        (
            resolved_duration,
            resolved_width,
            resolved_height,
            resolved_fps,
        ) = await _probe_video_metadata(output_path)
        return VideoResult(
            file_path=output_path,
            duration=resolved_duration,
            width=resolved_width,
            height=resolved_height,
            fps=resolved_fps or 24,
        )
