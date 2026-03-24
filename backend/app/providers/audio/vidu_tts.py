from __future__ import annotations

import asyncio
import logging
import mimetypes
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from mutagen import File as MutagenFile

from app.providers.base.audio import AudioProvider, AudioResult
from app.providers.registry import audio_registry

logger = logging.getLogger(__name__)

DEFAULT_VIDU_BASE_URL = "https://api.vidu.cn"
TERMINAL_SUCCESS_STATUSES = {"succeed", "success", "succeeded", "completed", "finished"}
TERMINAL_FAILED_STATUSES = {"failed", "error", "cancelled", "canceled", "rejected"}


def _normalize_api_key(raw_api_key: str | None) -> str:
    value = str(raw_api_key or "").strip().strip("\"'").strip()
    if value.lower().startswith("token "):
        value = value[6:].strip()
    return value


def _normalize_base_url(raw_base_url: str | None) -> str:
    normalized = str(raw_base_url or DEFAULT_VIDU_BASE_URL).strip().rstrip("/")
    parsed = urlparse(normalized)
    if not parsed.scheme or not parsed.netloc:
        return DEFAULT_VIDU_BASE_URL
    return f"{parsed.scheme}://{parsed.netloc}"


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_speed(value: Any, default: float = 1.0) -> float:
    return max(0.5, min(2.0, _coerce_float(value, default)))


def _normalize_volume(value: Any, default: float = 1.0) -> float:
    return max(0.0, min(10.0, _coerce_float(value, default)))


def _normalize_pitch(value: Any, default: float = 0.0) -> float:
    return max(-12.0, min(12.0, _coerce_float(value, default)))


def _extract_error_message(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("message", "msg", "error", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        error = payload.get("error")
        if isinstance(error, dict):
            nested = _extract_error_message(error)
            if nested:
                return nested
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
    task_id = str(payload.get("task_id") or payload.get("id") or "").strip()
    if task_id:
        return task_id
    data = payload.get("data")
    if isinstance(data, dict):
        return str(data.get("task_id") or data.get("id") or "").strip()
    return ""


def _extract_state(payload: Any) -> str:
    if isinstance(payload, dict):
        state = str(payload.get("state") or payload.get("status") or "").strip().lower()
        if state:
            return state
        data = payload.get("data")
        if isinstance(data, dict):
            return str(data.get("state") or data.get("status") or "").strip().lower()
    return ""


def _extract_audio_url(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""

    # tts create response
    for key in ("file_url", "url", "audio_url", "watermarked_url"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value

    data = payload.get("data")
    if isinstance(data, dict):
        nested = _extract_audio_url(data)
        if nested:
            return nested

    creations = payload.get("creations")
    if isinstance(creations, list):
        for item in creations:
            if not isinstance(item, dict):
                continue
            for key in ("url", "file_url", "audio_url", "watermarked_url"):
                value = str(item.get(key) or "").strip()
                if value:
                    return value
    return ""


@audio_registry.register("vidu_tts")
class ViduTTSProvider(AudioProvider):
    DEFAULT_VOICE_ID = "female-shaonv"

    def __init__(
        self,
        api_key: str = "",
        base_url: str = DEFAULT_VIDU_BASE_URL,
        voice_id: str = DEFAULT_VOICE_ID,
        speed: float = 1.0,
        volume: float = 1.0,
        pitch: float = 0.0,
        emotion: str = "",
        request_timeout: float = 60.0,
        poll_interval: float = 2.0,
        max_wait_time: float = 180.0,
    ) -> None:
        self.api_key = _normalize_api_key(api_key)
        self.base_url = _normalize_base_url(base_url)
        self.voice_id = str(voice_id or self.DEFAULT_VOICE_ID).strip() or self.DEFAULT_VOICE_ID
        self.speed = _normalize_speed(speed, 1.0)
        self.volume = _normalize_volume(volume, 1.0)
        self.pitch = _normalize_pitch(pitch, 0.0)
        self.emotion = str(emotion or "").strip()
        self.request_timeout = max(float(request_timeout or 60.0), 10.0)
        self.poll_interval = max(float(poll_interval or 2.0), 0.5)
        self.max_wait_time = max(float(max_wait_time or 180.0), self.poll_interval)

    def _validate_config(self) -> None:
        if not self.api_key:
            raise ValueError("Vidu TTS 需要配置 API Key")

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _query_task(self, client: httpx.AsyncClient, task_id: str) -> dict[str, Any]:
        response = await client.get(
            f"{self.base_url}/ent/v2/tasks/{task_id}/creations",
            headers=self._build_headers(),
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Vidu TTS 查询任务失败: {_extract_http_error_message(response)}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Vidu TTS 查询响应结构异常: {payload}")
        return payload

    @staticmethod
    async def _download_audio(client: httpx.AsyncClient, url: str, output_path: Path) -> None:
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)

    @staticmethod
    def _resolve_duration(file_path: Path) -> float:
        try:
            parsed = MutagenFile(str(file_path))
            if parsed is None or parsed.info is None:
                return 0.0
            return float(parsed.info.length)
        except Exception:
            return 0.0

    async def synthesize(
        self,
        text: str,
        output_path: Path,
        voice: str | None = None,
        rate: str | None = None,
        **kwargs: Any,
    ) -> AudioResult:
        del rate
        self._validate_config()
        content = str(text or "").strip()
        if not content:
            raise ValueError("文本为空，无法合成语音")

        voice_id = (
            str(
                voice
                or kwargs.get("voice_id")
                or kwargs.get("audio_vidu_voice_id")
                or self.voice_id
                or self.DEFAULT_VOICE_ID
            ).strip()
            or self.DEFAULT_VOICE_ID
        )
        speed = _normalize_speed(
            kwargs.get("speed")
            if kwargs.get("speed") is not None
            else kwargs.get("audio_vidu_speed", self.speed),
            self.speed,
        )
        volume = _normalize_volume(
            kwargs.get("volume")
            if kwargs.get("volume") is not None
            else kwargs.get("audio_vidu_volume", self.volume),
            self.volume,
        )
        pitch = _normalize_pitch(
            kwargs.get("pitch")
            if kwargs.get("pitch") is not None
            else kwargs.get("audio_vidu_pitch", self.pitch),
            self.pitch,
        )
        emotion = str(
            kwargs.get("emotion")
            if kwargs.get("emotion") is not None
            else kwargs.get("audio_vidu_emotion", self.emotion)
        ).strip()

        request_payload: dict[str, Any] = {
            "text": content,
            "voice_setting_voice_id": voice_id,
            "voice_setting_speed": speed,
            "voice_setting_volume": volume,
            "voice_setting_pitch": pitch,
        }
        if emotion:
            request_payload["voice_setting_emotion"] = emotion
        pronunciation_dict_tone = kwargs.get("pronunciation_dict_tone")
        if pronunciation_dict_tone is not None:
            request_payload["pronunciation_dict_tone"] = pronunciation_dict_tone
        custom_payload = kwargs.get("payload")
        if custom_payload is not None:
            request_payload["payload"] = custom_payload

        timeout = httpx.Timeout(self.request_timeout, connect=20.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=True) as client:
            response = await client.post(
                f"{self.base_url}/ent/v2/audio-tts",
                headers=self._build_headers(),
                json=request_payload,
            )
            if response.status_code >= 400:
                raise RuntimeError(f"Vidu TTS 请求失败: {_extract_http_error_message(response)}")

            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError(f"Vidu TTS 响应结构异常: {payload}")

            audio_url = _extract_audio_url(payload)
            state = _extract_state(payload)
            task_id = _extract_task_id(payload)

            if not audio_url and task_id:
                deadline = time.monotonic() + self.max_wait_time
                while time.monotonic() <= deadline:
                    if state in TERMINAL_FAILED_STATUSES:
                        message = _extract_error_message(payload)
                        raise RuntimeError(f"Vidu TTS 任务失败: {message or state}")
                    if state in TERMINAL_SUCCESS_STATUSES and audio_url:
                        break
                    await asyncio.sleep(self.poll_interval)
                    task_payload = await self._query_task(client, task_id)
                    state = _extract_state(task_payload)
                    audio_url = _extract_audio_url(task_payload)
                    if state in TERMINAL_SUCCESS_STATUSES and audio_url:
                        break

            if not audio_url:
                raise RuntimeError("Vidu TTS 未返回可下载音频地址")

            await self._download_audio(client, audio_url, output_path)

        duration = self._resolve_duration(output_path)
        sample_rate = 24000
        guessed_mime = mimetypes.guess_type(str(output_path))[0] or ""
        if guessed_mime == "audio/wav":
            sample_rate = 16000

        return AudioResult(
            file_path=output_path,
            duration=max(duration, 0.0),
            sample_rate=sample_rate,
        )

    def list_voices(self) -> list[str]:
        return []
