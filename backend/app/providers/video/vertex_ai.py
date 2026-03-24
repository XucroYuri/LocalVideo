"""
Vertex AI Video Provider

使用 Google Vertex AI Veo 模型生成视频
"""

import asyncio
import base64
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.providers.base.video import VideoProvider, VideoResult

logger = logging.getLogger(__name__)


VERTEX_AI_MODEL_PRESETS = {
    "veo-3.1": {
        "model_id": "veo-3.1-generate-001",
        "description": "Veo 3.1 - 高质量视频生成",
        "supports_last_frame": True,
        "aspect_ratios": ["16:9", "9:16"],
        "resolutions": [720, 1080],
        "durations": [4, 6, 8],
        "default_resolution": 1080,
        "default_aspect_ratio": "16:9",
    },
    "veo-3.1-fast": {
        "model_id": "veo-3.1-fast-generate-001",
        "description": "Veo 3.1 Fast - 快速视频生成",
        "supports_last_frame": True,
        "aspect_ratios": ["16:9", "9:16"],
        "resolutions": [720, 1080],
        "durations": [4, 6, 8],
        "default_resolution": 1080,
        "default_aspect_ratio": "16:9",
    },
    "veo-3.1-preview": {
        "model_id": "veo-3.1-generate-preview",
        "description": "Veo 3.1 Preview - 预览版高质量视频生成",
        "supports_last_frame": True,
        "aspect_ratios": ["16:9", "9:16"],
        "resolutions": [720, 1080],
        "durations": [4, 6, 8],
        "default_resolution": 1080,
        "default_aspect_ratio": "16:9",
    },
    "veo-3.1-fast-preview": {
        "model_id": "veo-3.1-fast-generate-preview",
        "description": "Veo 3.1 Fast Preview - 预览版快速视频生成",
        "supports_last_frame": True,
        "aspect_ratios": ["16:9", "9:16"],
        "resolutions": [720, 1080],
        "durations": [4, 6, 8],
        "default_resolution": 1080,
        "default_aspect_ratio": "16:9",
    },
}

DEFAULT_VERTEX_VIDEO_LOCATION = "us-central1"

VERTEX_REFERENCE_SUBJECT_MODEL_KEYS = {
    "veo-3.1-preview",
    "veo-3.1-fast-preview",
    "veo-3.1-generate-preview",
    "veo-3.1-fast-generate-preview",
}

VERTEX_LAST_FRAME_SUPPORTED_MODEL_KEYS = {
    # Public preset names
    "veo-3.1",
    "veo-3.1-fast",
    "veo-3.1-preview",
    "veo-3.1-fast-preview",
    # API model ids
    "veo-3.1-generate-001",
    "veo-3.1-fast-generate-001",
    "veo-3.1-generate-preview",
    "veo-3.1-fast-generate-preview",
}


def normalize_vertex_video_location(location: str | None) -> str:
    normalized = str(location or "").strip().lower()
    if not normalized:
        return DEFAULT_VERTEX_VIDEO_LOCATION
    # Veo 视频模型在 global 位置下经常返回 404，统一回退到 us-central1。
    if normalized == "global":
        return DEFAULT_VERTEX_VIDEO_LOCATION
    return normalized


def get_vertex_video_model_id_candidates(model: str | None) -> list[str]:
    raw_model = str(model or "").strip()
    if not raw_model:
        return []

    candidates: list[str] = []
    preset = VERTEX_AI_MODEL_PRESETS.get(raw_model)
    if preset:
        preset_model_id = str(preset.get("model_id") or "").strip()
        if preset_model_id:
            candidates.append(preset_model_id)
    candidates.append(raw_model)

    deduped: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def get_vertex_ai_preset(preset_name: str) -> dict:
    if preset_name not in VERTEX_AI_MODEL_PRESETS:
        available = ", ".join(VERTEX_AI_MODEL_PRESETS.keys())
        raise ValueError(f"未知的 Vertex AI 预设: {preset_name}，可用选项: {available}")
    return VERTEX_AI_MODEL_PRESETS[preset_name].copy()


def list_vertex_ai_presets() -> str:
    lines = ["Vertex AI 视频模型预设：\n"]
    lines.append(f"{'预设名称':<20} {'说明':<30} {'分辨率':<15} {'时长选项'}")
    lines.append("-" * 85)

    for name, preset in VERTEX_AI_MODEL_PRESETS.items():
        resolutions = ", ".join(f"{r}p" for r in preset["resolutions"])
        durations = ", ".join(f"{d}s" for d in preset["durations"])
        lines.append(f"{name:<20} {preset['description']:<30} {resolutions:<15} {durations}")

    return "\n".join(lines)


class VertexAIVideoProvider(VideoProvider):
    """Google Vertex AI 视频生成 Provider"""

    name = "vertex_ai"

    def __init__(
        self,
        project_id: str | None = None,
        location: str = DEFAULT_VERTEX_VIDEO_LOCATION,
        model: str = "veo-3.1-fast-preview",
        resolution: int = 0,
        aspect_ratio: str = "",
        negative_prompt: str = "",
        poll_interval: int = 15,
        max_wait_time: int = 3600,
        retry_max_attempts: int = 3,
        retry_interval: int = 60,
    ):
        self.project_id = project_id or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        self.location = normalize_vertex_video_location(location)
        self.model = model
        self.resolution = resolution
        self.aspect_ratio = aspect_ratio
        self.negative_prompt = str(negative_prompt or "").strip()
        self.poll_interval = poll_interval
        self.max_wait_time = max_wait_time
        self.retry_max_attempts = retry_max_attempts
        self.retry_interval = retry_interval

        self._preset = VERTEX_AI_MODEL_PRESETS.get(self.model, VERTEX_AI_MODEL_PRESETS["veo-3.1"])

    def _validate_config(
        self,
        resolution: int | None = None,
        aspect_ratio: str | None = None,
    ) -> None:
        if not self.project_id:
            raise ValueError(
                "Vertex AI Provider 需要配置 project_id 或设置 GOOGLE_CLOUD_PROJECT 环境变量"
            )
        if self.model not in VERTEX_AI_MODEL_PRESETS:
            available = ", ".join(VERTEX_AI_MODEL_PRESETS.keys())
            raise ValueError(f"未知的 Vertex AI 模型: {self.model}，可用选项: {available}")

        effective_resolution = resolution if resolution is not None else self.resolution
        effective_aspect_ratio = aspect_ratio if aspect_ratio is not None else self.aspect_ratio

        if effective_resolution and effective_resolution not in self._preset["resolutions"]:
            available = ", ".join(f"{r}p" for r in self._preset["resolutions"])
            raise ValueError(
                f"模型 {self.model} 不支持 {effective_resolution}p 分辨率，可用选项: {available}"
            )

        if effective_aspect_ratio and effective_aspect_ratio not in self._preset["aspect_ratios"]:
            available = ", ".join(self._preset["aspect_ratios"])
            raise ValueError(
                f"模型 {self.model} 不支持 {effective_aspect_ratio} 宽高比，可用选项: {available}"
            )

    async def _get_access_token(self) -> str:
        try:
            import google.auth
            import google.auth.transport.requests
            from google.auth import exceptions as google_auth_exceptions
            from google.oauth2 import service_account
        except ImportError:
            raise ImportError("请安装 google-auth 库: pip install google-auth")

        def _refresh():
            scopes = ["https://www.googleapis.com/auth/cloud-platform"]
            credentials = None
            credentials_json = str(
                os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON") or ""
            ).strip()
            credentials_path = str(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip()
            adc_path = str(
                Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
            )

            if credentials_json:
                info = json.loads(credentials_json)
                credentials = service_account.Credentials.from_service_account_info(
                    info,
                    scopes=scopes,
                )
            elif credentials_path and Path(credentials_path).exists():
                credentials = service_account.Credentials.from_service_account_file(
                    credentials_path,
                    scopes=scopes,
                )
            else:
                try:
                    credentials, _project = google.auth.default(scopes=scopes)
                except google_auth_exceptions.DefaultCredentialsError as exc:
                    raise RuntimeError(
                        "Vertex AI 鉴权失败：未找到可用凭证。"
                        f"已检查 GOOGLE_APPLICATION_CREDENTIALS={credentials_path or '<empty>'} "
                        f"和 ADC 文件 {adc_path}。"
                        "请配置 GOOGLE_APPLICATION_CREDENTIALS(服务账号json路径) "
                        "或 GOOGLE_APPLICATION_CREDENTIALS_JSON(服务账号json内容) 后重启后端。"
                    ) from exc

            auth_req = google.auth.transport.requests.Request()
            credentials.refresh(auth_req)
            return credentials.token

        return await asyncio.to_thread(_refresh)

    def _get_model_id(self) -> str:
        return self._preset["model_id"]

    def _get_target_duration(self, audio_duration: float) -> int:
        supported = self._preset["durations"]
        for d in sorted(supported):
            if d >= audio_duration:
                return d
        return max(supported)

    def _get_resolution(self, resolution: int | None = None) -> int:
        if resolution is not None:
            return resolution
        if self.resolution:
            return self.resolution
        return self._preset["default_resolution"]

    def _get_aspect_ratio(self, aspect_ratio: str | None = None) -> str:
        if aspect_ratio:
            return aspect_ratio
        if self.aspect_ratio:
            return self.aspect_ratio
        return self._preset["default_aspect_ratio"]

    def _get_dimensions(
        self,
        resolution: int | None = None,
        aspect_ratio: str | None = None,
    ) -> tuple[int, int]:
        actual_resolution = self._get_resolution(resolution)
        actual_aspect = self._get_aspect_ratio(aspect_ratio)

        if actual_aspect == "16:9":
            if actual_resolution == 1080:
                return 1920, 1080
            return 1280, 720
        else:  # 9:16
            if actual_resolution == 1080:
                return 1080, 1920
            return 720, 1280

    def _supports_last_frame(self, model: str | None = None) -> bool:
        model_key = str(model or self.model or "").strip().lower()
        return model_key in VERTEX_LAST_FRAME_SUPPORTED_MODEL_KEYS

    @staticmethod
    def _encode_image(image_path: Path) -> dict[str, str]:
        image_data = base64.b64encode(image_path.read_bytes()).decode("utf-8")
        ext = image_path.suffix.lower()
        mime_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }.get(ext, "image/png")
        return {"bytesBase64Encoded": image_data, "mimeType": mime_type}

    async def _submit_task(
        self,
        prompt: str,
        duration: float,
        resolution: int | None = None,
        aspect_ratio: str | None = None,
        negative_prompt: str | None = None,
        first_frame: Path | None = None,
        last_frame: Path | None = None,
        reference_images: list[Path] | None = None,
    ) -> str:
        try:
            import httpx
        except ImportError:
            raise ImportError("请安装 httpx 库: pip install httpx")

        self._validate_config(resolution=resolution, aspect_ratio=aspect_ratio)

        target_duration = self._get_target_duration(duration)
        if duration > target_duration:
            logger.info(
                "[VertexAI Video] Requested duration %.3fs exceeds model limit for %s, auto-adjusted to %ss",
                duration,
                self.model,
                target_duration,
            )
        access_token = await self._get_access_token()
        model_id = self._get_model_id()

        url = f"https://{self.location}-aiplatform.googleapis.com/v1/projects/{self.project_id}/locations/{self.location}/publishers/google/models/{model_id}:predictLongRunning"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        parameters = {
            "sampleCount": 1,
            "durationSeconds": target_duration,
            "aspectRatio": self._get_aspect_ratio(aspect_ratio),
            "generateAudio": False,
        }

        actual_resolution = self._get_resolution(resolution)
        if actual_resolution:
            parameters["resolution"] = f"{actual_resolution}p"
        effective_negative_prompt = str(
            self.negative_prompt if negative_prompt is None else negative_prompt
        ).strip()
        if effective_negative_prompt:
            parameters["negativePrompt"] = effective_negative_prompt

        instance: dict = {"prompt": prompt}

        if first_frame and first_frame.exists():
            instance["image"] = self._encode_image(first_frame)

        if last_frame and last_frame.exists():
            if self._supports_last_frame():
                # Vertex API schema requires `lastFrame` to be in VideoGenerationModelInstance,
                # not in `parameters`.
                instance["lastFrame"] = self._encode_image(last_frame)
            else:
                logger.warning(
                    "[VertexAI Video] last_frame is ignored because model does not support it: model=%s",
                    self.model,
                )

        if reference_images:
            refs: list[dict] = []
            for ref_path in reference_images:
                if not ref_path.exists():
                    continue
                image_data = base64.b64encode(ref_path.read_bytes()).decode("utf-8")
                ext = ref_path.suffix.lower()
                mime_type = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".webp": "image/webp",
                }.get(ext, "image/png")
                refs.append(
                    {
                        "referenceType": "asset",
                        "image": {
                            "bytesBase64Encoded": image_data,
                            "mimeType": mime_type,
                        },
                    }
                )
            if refs:
                instance["referenceImages"] = refs

        request_body = {"instances": [instance], "parameters": parameters}
        logger.info(
            "[VertexAI Video] Request summary: model=%s duration=%ss aspect=%s resolution=%s "
            "has_first_frame=%s has_last_frame=%s reference_images=%d has_negative_prompt=%s",
            model_id,
            target_duration,
            parameters.get("aspectRatio"),
            parameters.get("resolution"),
            "image" in instance,
            "lastFrame" in instance,
            len(instance.get("referenceImages", []))
            if isinstance(instance.get("referenceImages"), list)
            else 0,
            bool(parameters.get("negativePrompt")),
        )

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(url, headers=headers, json=request_body)
                response.raise_for_status()
                result = response.json()
                operation_name = result.get("name", "")
                logger.info("[VertexAI Video] Task submitted, operation: %s", operation_name)
                return operation_name
            except httpx.HTTPStatusError as e:
                logger.error(
                    "[VertexAI Video] Submit task failed: HTTP %d - %s",
                    e.response.status_code,
                    e.response.text,
                )
                raise
            except Exception as e:
                logger.error("[VertexAI Video] Submit task failed: %s", str(e))
                raise

    async def _poll_task(self, operation_name: str) -> dict:
        import httpx

        access_token = await self._get_access_token()
        model_id = self._get_model_id()

        url = f"https://{self.location}-aiplatform.googleapis.com/v1/projects/{self.project_id}/locations/{self.location}/publishers/google/models/{model_id}:fetchPredictOperation"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        request_body = {"operationName": operation_name}

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(url, headers=headers, json=request_body)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(
                    "[VertexAI Video] Poll task failed: HTTP %d - %s",
                    e.response.status_code,
                    e.response.text,
                )
                raise
            except Exception as e:
                logger.error("[VertexAI Video] Poll task failed: %s", str(e))
                raise

    async def _wait_for_completion(
        self,
        operation_name: str,
        progress_callback: Callable[[int], Awaitable[None]] | None = None,
    ) -> dict:
        start_time = time.time()
        poll_count = 0
        progress = 0
        last_progress: int | None = None

        while True:
            elapsed = time.time() - start_time
            if elapsed > self.max_wait_time:
                logger.error(
                    "[VertexAI Video] Timeout waiting for video generation after %d seconds",
                    self.max_wait_time,
                )
                raise TimeoutError(f"视频生成超时，已等待 {self.max_wait_time} 秒")

            try:
                result = await self._poll_task(operation_name)
            except Exception as e:
                logger.error(
                    "[VertexAI Video] Error polling task (attempt %d): %s", poll_count + 1, str(e)
                )
                raise

            done = result.get("done", False)
            poll_count += 1

            if done:
                if "error" in result:
                    error_msg = result["error"]
                    logger.error("[VertexAI Video] Video generation failed: %s", error_msg)
                    raise RuntimeError(f"视频生成失败: {error_msg}")
                logger.info(
                    "[VertexAI Video] Video generation completed after %d polls (%.1f seconds)",
                    poll_count,
                    elapsed,
                )
                progress = 100
                if progress_callback:
                    try:
                        await progress_callback(progress)
                    except Exception:
                        pass
                return result.get("response", result)

            metadata = result.get("metadata", {}) or {}
            state = metadata.get("state", "RUNNING")
            if state == "RUNNING":
                progress = min(progress + 10, 99)

            if progress != last_progress:
                logger.info("[VertexAI Video] Progress: %d%% (state=%s)", progress, state)
                if progress_callback:
                    try:
                        await progress_callback(progress)
                    except Exception:
                        pass
                last_progress = progress

            logger.debug(
                "[VertexAI Video] Poll %d: still processing (elapsed: %.1fs)", poll_count, elapsed
            )
            await asyncio.sleep(self.poll_interval)

    def _extract_video_data(self, response: dict) -> bytes:
        # Vertex AI 可能返回 done=true 但媒体被 RAI 过滤，此时没有 videos 字段。
        def _extract_filtered_reason(payload: dict) -> str | None:
            candidates = [payload]
            nested = payload.get("response")
            if isinstance(nested, dict):
                candidates.append(nested)
            for item in candidates:
                try:
                    filtered_count = int(item.get("raiMediaFilteredCount", 0) or 0)
                except (TypeError, ValueError):
                    filtered_count = 0
                if filtered_count > 0:
                    reasons = item.get("raiMediaFilteredReasons")
                    if isinstance(reasons, list):
                        joined = "；".join(str(r).strip() for r in reasons if str(r).strip())
                        if joined:
                            return joined
                    return f"共 {filtered_count} 个视频被平台安全策略拦截"
            return None

        filtered_reason = _extract_filtered_reason(response)
        if filtered_reason:
            raise ValueError(f"视频被 Vertex AI 安全策略拦截：{filtered_reason}")

        videos = response.get("response", {}).get("videos", [])
        if not videos:
            videos = response.get("generatedSamples", [])
        if not videos:
            videos = response.get("videos", [])

        if not videos:
            raise ValueError("未找到视频数据")

        video = videos[0]

        video_bytes = video.get("bytesBase64Encoded") or (
            video.get("video", {}).get("bytesBase64Encoded")
        )
        if video_bytes:
            return base64.b64decode(video_bytes)

        gcs_uri = video.get("gcsUri") or (video.get("video", {}).get("gcsUri"))
        if gcs_uri:
            raise NotImplementedError(f"GCS 下载尚未实现: {gcs_uri}")

        raise ValueError("未找到可下载的视频数据")

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
        negative_prompt: str | None = None,
        first_frame: Path | None = None,
        last_frame: Path | None = None,
        reference_images: list[Path] | None = None,
        progress_callback: Callable[[int], Awaitable[None]] | None = None,
        **kwargs,
    ) -> VideoResult:
        del width, height
        effective_duration = duration if duration is not None else 5.0
        effective_fps = fps if fps is not None else 24
        runtime_negative_prompt = str(
            negative_prompt
            if negative_prompt is not None
            else (kwargs.get("negative_prompt") or self.negative_prompt) or ""
        ).strip()

        try:
            operation_name = await self._submit_task(
                prompt=prompt,
                duration=effective_duration,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                negative_prompt=runtime_negative_prompt,
                first_frame=first_frame,
                last_frame=last_frame,
                reference_images=reference_images,
            )

            if progress_callback:
                try:
                    await progress_callback(1)
                except Exception:
                    pass

            response = await self._wait_for_completion(
                operation_name, progress_callback=progress_callback
            )

            video_data = self._extract_video_data(response)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(video_data)

            actual_width, actual_height = self._get_dimensions(
                resolution=resolution, aspect_ratio=aspect_ratio
            )
            target_duration = self._get_target_duration(effective_duration)

            logger.info("[VertexAI Video] Video saved to %s", output_path)
            return VideoResult(
                file_path=output_path,
                duration=float(target_duration),
                width=actual_width,
                height=actual_height,
                fps=effective_fps,
            )
        except Exception as e:
            logger.error("[VertexAI Video] Generate failed: %s", str(e))
            raise

    def get_supported_durations(self) -> list[int]:
        return self._preset["durations"]

    def get_supported_resolutions(self) -> list[str]:
        return [f"{r}p" for r in self._preset["resolutions"]]
