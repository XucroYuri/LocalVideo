from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any

import httpx
from mutagen.mp3 import MP3

from app.providers.base.audio import AudioProvider, AudioResult
from app.providers.kling_auth import (
    build_kling_auth_headers,
    is_kling_configured,
    normalize_kling_access_key,
    normalize_kling_base_url,
    normalize_kling_secret_key,
)
from app.providers.registry import audio_registry

logger = logging.getLogger(__name__)

DEFAULT_KLING_BASE_URL = "https://api-beijing.klingai.com"
TERMINAL_SUCCESS_STATUSES = {"succeed", "success", "succeeded", "completed", "finished"}
TERMINAL_FAILED_STATUSES = {"failed", "error", "cancelled", "canceled", "rejected"}


def _normalize_base_url(raw_base_url: str | None) -> str:
    return normalize_kling_base_url(raw_base_url or DEFAULT_KLING_BASE_URL)


def _parse_rate_to_speed(rate: str | None) -> float | None:
    text = str(rate or "").strip()
    if not text:
        return None
    matched = re.search(r"([+-]?\d+(?:\.\d+)?)%", text)
    if not matched:
        return None
    try:
        percent = float(matched.group(1))
    except (TypeError, ValueError):
        return None
    return 1.0 + percent / 100.0


def _normalize_voice_speed(value: Any, default: float = 1.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    parsed = max(0.8, min(2.0, parsed))
    return round(parsed, 1)


def _normalize_voice_language(value: Any) -> str:
    normalized = str(value or "zh").strip().lower() or "zh"
    return "en" if normalized == "en" else "zh"


def _coerce_code(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _extract_payload_error_message(payload: dict[str, Any]) -> str:
    message = str(payload.get("message") or payload.get("msg") or "").strip()
    if message:
        return message
    error = payload.get("error")
    if isinstance(error, str):
        return error.strip()
    if isinstance(error, dict):
        nested = str(error.get("message") or error.get("msg") or "").strip()
        if nested:
            return nested
    return ""


def _extract_http_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            return _extract_payload_error_message(payload) or response.text.strip()
    except Exception:
        pass
    return response.text.strip() or f"HTTP {response.status_code}"


def _extract_task_id(payload: dict[str, Any]) -> str:
    data = payload.get("data")
    if isinstance(data, dict):
        task_id = str(data.get("task_id") or data.get("id") or "").strip()
        if task_id:
            return task_id
    task_id = str(payload.get("task_id") or payload.get("id") or "").strip()
    return task_id


def _extract_task_status(payload: dict[str, Any]) -> str:
    data = payload.get("data")
    if isinstance(data, dict):
        return str(data.get("task_status") or data.get("status") or "").strip().lower()
    return str(payload.get("task_status") or payload.get("status") or "").strip().lower()


def _extract_task_result_audios(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    task_result = data.get("task_result")
    if not isinstance(task_result, dict):
        return []
    audios = task_result.get("audios")
    if not isinstance(audios, list):
        return []
    return [item for item in audios if isinstance(item, dict)]


@audio_registry.register("kling_tts")
class KlingTTSProvider(AudioProvider):
    DEFAULT_VOICE_ID = "zh_male_qn_qingse"

    def __init__(
        self,
        access_key: str = "",
        secret_key: str = "",
        base_url: str = DEFAULT_KLING_BASE_URL,
        voice_id: str = DEFAULT_VOICE_ID,
        voice_language: str = "zh",
        voice_speed: float = 1.0,
        request_timeout: float = 60.0,
        poll_interval: float = 2.0,
        max_wait_time: float = 120.0,
    ) -> None:
        self.access_key = normalize_kling_access_key(access_key)
        self.secret_key = normalize_kling_secret_key(secret_key)
        self.base_url = _normalize_base_url(base_url)
        self.voice_id = str(voice_id or self.DEFAULT_VOICE_ID).strip() or self.DEFAULT_VOICE_ID
        self.voice_language = _normalize_voice_language(voice_language)
        self.voice_speed = _normalize_voice_speed(voice_speed, 1.0)
        self.request_timeout = max(float(request_timeout or 60.0), 10.0)
        self.poll_interval = max(float(poll_interval or 2.0), 0.5)
        self.max_wait_time = max(float(max_wait_time or 120.0), self.poll_interval)

    def _validate_config(self) -> None:
        if not is_kling_configured(
            access_key=self.access_key,
            secret_key=self.secret_key,
        ):
            raise ValueError("Kling TTS 需要配置 Access Key 和 Secret Key")

    def _build_headers(self) -> dict[str, str]:
        return {
            **build_kling_auth_headers(
                access_key=self.access_key,
                secret_key=self.secret_key,
            ),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @staticmethod
    async def _download_audio(client: httpx.AsyncClient, url: str, output_path: Path) -> None:
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)

    @staticmethod
    def _get_audio_duration(file_path: Path) -> float:
        try:
            audio = MP3(str(file_path))
            return float(audio.info.length)
        except Exception:
            return 0.0

    async def _query_task(self, client: httpx.AsyncClient, task_id: str) -> dict[str, Any] | None:
        task_url = f"{self.base_url}/v1/audio/tts/{task_id}"
        response = await client.get(task_url, headers=self._build_headers())
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"Kling TTS 查询响应结构异常: {payload}")
        code = _coerce_code(payload.get("code"))
        if code != 0:
            message = _extract_payload_error_message(payload) or f"code={code}"
            raise RuntimeError(f"Kling TTS 查询任务失败: {message}")
        return payload

    async def synthesize(
        self,
        text: str,
        output_path: Path,
        voice: str | None = None,
        rate: str | None = None,
        **kwargs: Any,
    ) -> AudioResult:
        self._validate_config()
        content = str(text or "").strip()
        if not content:
            raise ValueError("文本为空，无法合成语音")

        voice_id = (
            str(voice or kwargs.get("voice_id") or self.voice_id or self.DEFAULT_VOICE_ID).strip()
            or self.DEFAULT_VOICE_ID
        )
        voice_language = _normalize_voice_language(
            kwargs.get("voice_language") or self.voice_language
        )
        requested_speed = kwargs.get("voice_speed")
        if requested_speed is None:
            requested_speed = kwargs.get("speed")
        if requested_speed is None:
            parsed_from_rate = _parse_rate_to_speed(rate)
            requested_speed = parsed_from_rate if parsed_from_rate is not None else self.voice_speed
        voice_speed = _normalize_voice_speed(requested_speed, self.voice_speed)

        request_payload = {
            "text": content,
            "voice_id": voice_id,
            "voice_language": voice_language,
            "voice_speed": voice_speed,
        }

        timeout = httpx.Timeout(self.request_timeout, connect=20.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=True) as client:
            response = await client.post(
                f"{self.base_url}/v1/audio/tts",
                headers=self._build_headers(),
                json=request_payload,
            )
            if response.status_code >= 400:
                raise RuntimeError(f"Kling TTS 请求失败: {_extract_http_error_message(response)}")
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError(f"Kling TTS 响应结构异常: {payload}")
            code = _coerce_code(payload.get("code"))
            if code != 0:
                message = _extract_payload_error_message(payload) or f"code={code}"
                raise RuntimeError(f"Kling TTS 创建任务失败: {message}")

            task_id = _extract_task_id(payload)
            status = _extract_task_status(payload)
            task_audios = _extract_task_result_audios(payload)

            if not task_audios and task_id and status not in TERMINAL_FAILED_STATUSES:
                deadline = time.monotonic() + self.max_wait_time
                while time.monotonic() <= deadline:
                    await asyncio.sleep(self.poll_interval)
                    queried_payload = await self._query_task(client, task_id)
                    if queried_payload is None:
                        # 当前账号可能无查询接口权限，退出轮询并使用已有响应。
                        break
                    status = _extract_task_status(queried_payload)
                    task_audios = _extract_task_result_audios(queried_payload)
                    if status in TERMINAL_SUCCESS_STATUSES and task_audios:
                        break
                    if status in TERMINAL_FAILED_STATUSES:
                        message = _extract_payload_error_message(queried_payload)
                        raise RuntimeError(f"Kling TTS 任务失败: {message or status}")

            if not task_audios:
                raise RuntimeError("Kling TTS 未返回可下载音频；请确认账号是否支持同步返回结果。")

            first_audio = task_audios[0]
            audio_url = str(
                first_audio.get("url") or first_audio.get("watermark_url") or ""
            ).strip()
            if not audio_url:
                raise RuntimeError(f"Kling TTS 响应中缺少音频地址: {first_audio}")

            await self._download_audio(client, audio_url, output_path)

            duration = 0.0
            try:
                duration = float(first_audio.get("duration") or 0.0)
            except (TypeError, ValueError):
                duration = 0.0
            if duration <= 0:
                duration = self._get_audio_duration(output_path)

        return AudioResult(
            file_path=output_path,
            duration=max(duration, 0.0),
            sample_rate=24000,
        )

    def list_voices(self) -> list[str]:
        # Kling 开发文档未提供可查询的公开音色列表接口。
        return []
