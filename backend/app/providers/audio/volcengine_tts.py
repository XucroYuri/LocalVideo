from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from mutagen.mp3 import MP3

from app.providers.audio.volcengine_tts_models import (
    VOLCENGINE_TTS_DEFAULT_MODEL_NAME,
    VOLCENGINE_TTS_DEFAULT_RESOURCE_ID,
    is_volcengine_tts_voice_supported,
    list_volcengine_tts_voices,
    normalize_volcengine_tts_model_name,
    resolve_default_volcengine_tts_voice_type,
    resolve_volcengine_tts_resource_id,
)
from app.providers.base.audio import AudioProvider, AudioResult
from app.providers.registry import audio_registry
from app.services.volcengine_speaker_service import VolcengineSpeakerService

logger = logging.getLogger(__name__)

VOLCENGINE_TTS_ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
STREAM_SUCCESS_CODES = {0}
STREAM_DONE_CODE = 20000000
SUPPORTED_ENCODINGS = {"mp3", "wav", "pcm", "ogg_opus"}


@audio_registry.register("volcengine_tts")
class VolcengineTTSProvider(AudioProvider):
    DEFAULT_RESOURCE_ID = VOLCENGINE_TTS_DEFAULT_RESOURCE_ID
    DEFAULT_MODEL_NAME = VOLCENGINE_TTS_DEFAULT_MODEL_NAME
    DEFAULT_VOICE_TYPE = resolve_default_volcengine_tts_voice_type(
        VOLCENGINE_TTS_DEFAULT_MODEL_NAME
    )
    DEFAULT_ENCODING = "mp3"

    def __init__(
        self,
        app_key: str = "",
        access_key: str = "",
        resource_id: str = DEFAULT_RESOURCE_ID,
        model_name: str = DEFAULT_MODEL_NAME,
        request_timeout: float = 60.0,
    ) -> None:
        self.app_key = str(app_key or "").strip()
        self.access_key = str(access_key or "").strip()
        self.model_name = normalize_volcengine_tts_model_name(model_name)
        self.resource_id = resolve_volcengine_tts_resource_id(
            self.model_name if model_name is not None else resource_id
        )
        self.request_timeout = max(5.0, float(request_timeout or 60.0))

        if not self.app_key:
            raise ValueError("volcengine_tts 缺少 APP ID")
        if not self.access_key:
            raise ValueError("volcengine_tts 缺少 Access Token")

    @staticmethod
    def _normalize_ratio(value: Any, default: float = 1.0) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = default
        return max(0.5, min(2.0, parsed))

    @classmethod
    def _normalize_encoding(cls, value: Any) -> str:
        normalized = str(value or cls.DEFAULT_ENCODING).strip().lower() or cls.DEFAULT_ENCODING
        return normalized if normalized in SUPPORTED_ENCODINGS else cls.DEFAULT_ENCODING

    def _build_headers(self, *, resource_id: str) -> dict[str, str]:
        return {
            "X-Api-App-Id": self.app_key,
            "X-Api-Access-Key": self.access_key,
            "X-Api-Resource-Id": resource_id,
            "Content-Type": "application/json",
            "Connection": "keep-alive",
        }

    def _build_payload(
        self,
        *,
        request_id: str,
        text: str,
        voice_type: str,
        encoding: str,
        speed_ratio: float,
        volume_ratio: float,
        pitch_ratio: float,
        model_name: str,
    ) -> dict[str, Any]:
        return {
            "user": {
                "uid": f"localvideo_{uuid4().hex[:12]}",
            },
            "req_params": {
                "text": text,
                "speaker": voice_type,
                "model_name": model_name,
                "reqid": request_id,
                "audio_params": {
                    "format": encoding,
                    "sample_rate": 24000,
                },
                "additions": json.dumps(
                    {
                        "explicit_language": "zh",
                        "disable_markdown_filter": True,
                    },
                    ensure_ascii=False,
                ),
                "speed_ratio": speed_ratio,
                "volume_ratio": volume_ratio,
                "pitch_ratio": pitch_ratio,
            },
        }

    @staticmethod
    def _should_retry_status(status_code: int) -> bool:
        return int(status_code) in RETRYABLE_STATUS_CODES

    @staticmethod
    def _get_audio_duration(file_path: Path, encoding: str) -> float:
        if encoding != "mp3":
            return 0.0
        try:
            audio = MP3(str(file_path))
            return float(audio.info.length)
        except Exception:
            return 0.0

    @staticmethod
    def _extract_http_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
            for key in ("message", "msg", "error", "error_msg"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            if isinstance(payload, dict):
                header = payload.get("header")
                if isinstance(header, dict):
                    for key in ("message", "msg", "error", "error_msg"):
                        value = header.get(key)
                        if isinstance(value, str) and value.strip():
                            return value.strip()
        except Exception:
            pass
        return response.text.strip() or f"HTTP {response.status_code}"

    @staticmethod
    async def _parse_stream_response(response: httpx.Response) -> tuple[bytes, str]:
        audio_data = bytearray()
        last_error_message = ""
        async for line in response.aiter_lines():
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            code = int(payload.get("code") or 0)
            if code in STREAM_SUCCESS_CODES:
                chunk = payload.get("data")
                if isinstance(chunk, str) and chunk.strip():
                    audio_data.extend(base64.b64decode(chunk))
                continue
            if code == STREAM_DONE_CODE:
                break
            if code > 0:
                last_error_message = str(
                    payload.get("message") or payload.get("msg") or payload.get("error") or payload
                ).strip()
                break
        return bytes(audio_data), last_error_message

    async def synthesize(
        self,
        text: str,
        output_path: Path,
        voice: str | None = None,
        rate: str | None = None,
        **kwargs: Any,
    ) -> AudioResult:
        del rate
        if not str(text or "").strip():
            raise ValueError("文本为空，无法合成语音")

        model_name = normalize_volcengine_tts_model_name(
            kwargs.get("model_name") or self.model_name
        )
        resource_id = str(
            kwargs.get("resource_id") or resolve_volcengine_tts_resource_id(model_name)
        ).strip() or resolve_volcengine_tts_resource_id(model_name)
        self.model_name = model_name
        self.resource_id = resource_id

        default_voice = resolve_default_volcengine_tts_voice_type(model_name)
        voice_type = (
            str(voice or kwargs.get("voice_type") or default_voice).strip() or default_voice
        )
        if not is_volcengine_tts_voice_supported(model_name, voice_type):
            supported = ", ".join(
                str(item.get("id") or "").strip() for item in list_volcengine_tts_voices(model_name)
            )
            raise ValueError(
                f"音色不属于当前模型({model_name})，voice={voice_type}。可选: {supported}"
            )

        encoding = self._normalize_encoding(kwargs.get("encoding"))
        speed_ratio = self._normalize_ratio(
            kwargs.get("speed_ratio", kwargs.get("speed", 1.0)), 1.0
        )
        volume_ratio = self._normalize_ratio(kwargs.get("volume_ratio", 1.0), 1.0)
        pitch_ratio = self._normalize_ratio(kwargs.get("pitch_ratio", 1.0), 1.0)
        request_id = str(kwargs.get("request_id") or uuid4())

        payload = self._build_payload(
            request_id=request_id,
            text=str(text),
            voice_type=voice_type,
            encoding=encoding,
            speed_ratio=speed_ratio,
            volume_ratio=volume_ratio,
            pitch_ratio=pitch_ratio,
            model_name=model_name,
        )
        headers = self._build_headers(resource_id=resource_id)

        timeout = httpx.Timeout(self.request_timeout, connect=15.0, read=self.request_timeout)
        attempts = 3
        last_error: Exception | None = None
        started_at = time.perf_counter()

        async with httpx.AsyncClient(timeout=timeout, trust_env=True) as client:
            for attempt in range(1, attempts + 1):
                try:
                    async with client.stream(
                        "POST",
                        VOLCENGINE_TTS_ENDPOINT,
                        headers=headers,
                        json=payload,
                    ) as response:
                        if response.status_code >= 400:
                            detail = self._extract_http_error_message(response)
                            last_error = RuntimeError(f"火山 TTS 请求失败: {detail}")
                            if (
                                self._should_retry_status(response.status_code)
                                and attempt < attempts
                            ):
                                await asyncio.sleep(0.4 * attempt)
                                continue
                            break

                        audio_bytes, stream_error = await self._parse_stream_response(response)
                        if stream_error:
                            last_error = RuntimeError(stream_error)
                            break
                        if not audio_bytes:
                            last_error = RuntimeError("火山 TTS 响应为空，未返回音频数据")
                            if attempt < attempts:
                                await asyncio.sleep(0.4 * attempt)
                                continue
                            break

                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        output_path.write_bytes(audio_bytes)
                        duration = self._get_audio_duration(output_path, encoding)

                        elapsed_ms = (time.perf_counter() - started_at) * 1000
                        logger.info(
                            "[VolcengineTTS] request_id=%s model=%s resource_id=%s voice=%s text_len=%d status=success elapsed_ms=%.1f",
                            request_id,
                            model_name,
                            resource_id,
                            voice_type,
                            len(str(text)),
                            elapsed_ms,
                        )
                        return AudioResult(
                            file_path=output_path,
                            duration=duration,
                            sample_rate=24000,
                        )
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error = RuntimeError(f"火山 TTS 网络异常: {exc}")
                    if attempt < attempts:
                        await asyncio.sleep(0.4 * attempt)
                        continue
                    break
                except Exception as exc:
                    last_error = exc
                    break

        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.error(
            "[VolcengineTTS] request_id=%s model=%s resource_id=%s voice=%s text_len=%d status=failed elapsed_ms=%.1f error=%s",
            request_id,
            model_name,
            resource_id,
            voice_type,
            len(str(text)),
            elapsed_ms,
            str(last_error),
        )
        raise RuntimeError(str(last_error) or "火山 TTS 合成失败")

    def list_voices(self) -> list[str]:
        voices = list_volcengine_tts_voices(self.model_name)
        return [
            str(item.get("id") or "").strip()
            for item in voices
            if str(item.get("id") or "").strip()
        ]

    async def list_voices_async(self, *, force_refresh: bool = False) -> list[dict[str, str]]:
        service = VolcengineSpeakerService(
            model_name=self.model_name,
            app_key=self.app_key,
            access_key=self.access_key,
            resource_id=self.resource_id,
        )
        return await service.list_speakers(
            force_refresh=force_refresh,
            model_name=self.model_name,
        )
