from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from mutagen import File as MutagenFile

from app.providers.base.audio import AudioProvider, AudioResult
from app.providers.registry import audio_registry

logger = logging.getLogger(__name__)

DEFAULT_XIAOMI_MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"
DEFAULT_XIAOMI_MIMO_TTS_MODEL = "mimo-v2-tts"
DEFAULT_XIAOMI_MIMO_TTS_VOICE = "mimo_default"
DEFAULT_XIAOMI_MIMO_TTS_STYLE_PRESET = ""
SUPPORTED_XIAOMI_MIMO_TTS_FORMATS = {"wav", "mp3", "pcm"}
SUPPORTED_XIAOMI_MIMO_TTS_VOICES = {
    "mimo_default",
    "default_zh",
    "default_en",
}
XIAOMI_MIMO_TTS_STYLE_PRESET_VALUES = {
    "sun_wukong": "孙悟空",
    "lin_dai_yu": "林黛玉",
    "jia_zi_yin": "夹子音",
    "tai_wan_qiang": "台湾腔",
    "dong_bei_lao_tie": "东北话",
    "yue_yu_zhu_bo": "粤语",
    "ao_jiao_yu_jie": "傲娇御姐",
    "wen_rou_xue_jie": "温柔学姐",
    "bing_jiao_di_di": "病娇弟弟",
    "ba_dao_shao_ye": "霸道少爷",
    "sa_jiao_nv_you": "撒娇女友",
    "gang_pu_kong_jie": "港普空姐",
    "bo_bao_nan_sheng": "播报男声",
    "ruan_ruan_nv_hai": "软软女孩",
    "wen_nuan_shao_nv": "温暖少女",
}


def _normalize_base_url(raw_base_url: str | None) -> str:
    normalized = str(raw_base_url or DEFAULT_XIAOMI_MIMO_BASE_URL).strip().rstrip("/")
    if not normalized:
        return DEFAULT_XIAOMI_MIMO_BASE_URL
    parsed = urlparse(normalized)
    if not parsed.scheme or not parsed.netloc:
        return DEFAULT_XIAOMI_MIMO_BASE_URL
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/v1"):
        return normalized
    if path:
        return f"{normalized}/v1"
    return f"{normalized}/v1"


def _normalize_format(value: Any, default: str = "wav") -> str:
    normalized = str(value or default).strip().lower() or default
    return normalized if normalized in SUPPORTED_XIAOMI_MIMO_TTS_FORMATS else default


def normalize_xiaomi_mimo_voice(
    value: Any,
    default: str = DEFAULT_XIAOMI_MIMO_TTS_VOICE,
) -> str:
    normalized = str(value or default).strip() or default
    return normalized if normalized in SUPPORTED_XIAOMI_MIMO_TTS_VOICES else default


def normalize_xiaomi_mimo_style_preset(
    value: Any,
    default: str = DEFAULT_XIAOMI_MIMO_TTS_STYLE_PRESET,
) -> str:
    normalized = str(value or default).strip()
    return normalized if normalized in XIAOMI_MIMO_TTS_STYLE_PRESET_VALUES else default


def apply_xiaomi_mimo_style_preset(text: str, style_preset: Any = None) -> str:
    content = str(text or "").strip()
    if not content:
        return ""
    normalized_style_preset = normalize_xiaomi_mimo_style_preset(style_preset)
    if not normalized_style_preset:
        return content
    if content.startswith("<style>") and "</style>" in content:
        return content
    style_value = XIAOMI_MIMO_TTS_STYLE_PRESET_VALUES.get(normalized_style_preset, "").strip()
    if not style_value:
        return content
    return f"<style>{style_value}</style>{content}"


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


def _extract_audio_payload(payload: dict[str, Any]) -> tuple[str, str]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return "", ""
    first_choice = choices[0] if isinstance(choices[0], dict) else {}
    message = first_choice.get("message")
    if not isinstance(message, dict):
        return "", ""
    audio = message.get("audio")
    if not isinstance(audio, dict):
        return "", ""
    return (
        str(audio.get("data") or "").strip(),
        str(audio.get("transcript") or "").strip(),
    )


def _resolve_duration(file_path: Path) -> float:
    try:
        parsed = MutagenFile(str(file_path))
        if parsed is None or parsed.info is None:
            return 0.0
        return float(parsed.info.length)
    except Exception:
        return 0.0


@audio_registry.register("xiaomi_mimo_tts")
class XiaomiMiMoTTSProvider(AudioProvider):
    DEFAULT_VOICE = DEFAULT_XIAOMI_MIMO_TTS_VOICE
    DEFAULT_MODEL = DEFAULT_XIAOMI_MIMO_TTS_MODEL

    def __init__(
        self,
        api_key: str = "",
        base_url: str = DEFAULT_XIAOMI_MIMO_BASE_URL,
        model: str = DEFAULT_XIAOMI_MIMO_TTS_MODEL,
        voice: str = DEFAULT_XIAOMI_MIMO_TTS_VOICE,
        audio_format: str = "wav",
        request_timeout: float = 60.0,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self.base_url = _normalize_base_url(base_url)
        self.model = str(model or self.DEFAULT_MODEL).strip() or self.DEFAULT_MODEL
        self.voice = normalize_xiaomi_mimo_voice(voice or self.DEFAULT_VOICE)
        self.audio_format = _normalize_format(audio_format)
        self.request_timeout = max(float(request_timeout or 60.0), 10.0)

    def _validate_config(self) -> None:
        if not self.api_key:
            raise ValueError("小米 MiMo TTS 需要配置 API Key")

    def _build_headers(self) -> dict[str, str]:
        return {
            "api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

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

        resolved_voice = normalize_xiaomi_mimo_voice(
            voice
            or kwargs.get("voice")
            or kwargs.get("audio_xiaomi_mimo_voice")
            or self.voice
            or self.DEFAULT_VOICE
        )
        resolved_format = _normalize_format(
            kwargs.get("audio_format")
            if kwargs.get("audio_format") is not None
            else kwargs.get("audio_xiaomi_mimo_format", self.audio_format),
            self.audio_format,
        )
        resolved_style_preset = normalize_xiaomi_mimo_style_preset(
            kwargs.get("style_preset") or kwargs.get("audio_xiaomi_mimo_style_preset")
        )
        resolved_model = (
            str(kwargs.get("model") or kwargs.get("audio_xiaomi_mimo_model") or self.model).strip()
            or self.DEFAULT_MODEL
        )
        user_text = (
            str(
                kwargs.get("user_text") or "Please synthesize the assistant message as speech."
            ).strip()
            or "Please synthesize the assistant message as speech."
        )
        styled_content = apply_xiaomi_mimo_style_preset(content, resolved_style_preset)

        request_payload = {
            "model": resolved_model,
            "messages": [
                {
                    "role": "user",
                    "content": user_text,
                },
                {
                    "role": "assistant",
                    "content": styled_content,
                },
            ],
            "audio": {
                "format": resolved_format,
                "voice": resolved_voice,
            },
        }

        timeout = httpx.Timeout(self.request_timeout, connect=20.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=True) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._build_headers(),
                json=request_payload,
            )
            if response.status_code >= 400:
                raise RuntimeError(
                    f"小米 MiMo TTS 请求失败: {_extract_http_error_message(response)}"
                )
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError(f"小米 MiMo TTS 响应结构异常: {payload}")
            audio_data_base64, transcript = _extract_audio_payload(payload)
            if not audio_data_base64:
                raise RuntimeError("小米 MiMo TTS 未返回音频数据")

            try:
                audio_bytes = base64.b64decode(audio_data_base64)
            except Exception as exc:
                raise RuntimeError("小米 MiMo TTS 返回的音频数据无法解码") from exc

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)
        duration = _resolve_duration(output_path)
        logger.info(
            "[Xiaomi MiMo TTS] synthesized model=%s voice=%s style_preset=%s format=%s duration=%.3f transcript=%s",
            resolved_model,
            resolved_voice,
            resolved_style_preset or "-",
            resolved_format,
            duration,
            "yes" if transcript else "no",
        )
        return AudioResult(
            file_path=output_path,
            duration=duration,
            sample_rate=24000,
        )

    def list_voices(self) -> list[str]:
        return [
            DEFAULT_XIAOMI_MIMO_TTS_VOICE,
            "default_zh",
            "default_en",
        ]
