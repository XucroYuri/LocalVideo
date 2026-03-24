from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from mutagen import File as MutagenFile

from app.providers.base.audio import AudioProvider, AudioResult
from app.providers.registry import audio_registry

logger = logging.getLogger(__name__)

DEFAULT_MINIMAX_BASE_URL = "https://api.minimaxi.com/v1"
DEFAULT_MINIMAX_AUDIO_MODEL = "speech-2.8-turbo"
DEFAULT_MINIMAX_VOICE_ID = "Chinese (Mandarin)_Reliable_Executive"
MINIMAX_AUDIO_MODEL_OPTIONS = [
    "speech-2.8-hd",
    "speech-2.8-turbo",
    "speech-2.6-hd",
    "speech-2.6-turbo",
    "speech-02-hd",
    "speech-02-turbo",
    "speech-01-hd",
    "speech-01-turbo",
]
MINIMAX_TTS_PRESET_VOICES: list[dict[str, str]] = [
    {"id": "male-qn-qingse", "name": "青涩青年音色", "locale": "zh-CN"},
    {"id": "male-qn-jingying", "name": "精英青年音色", "locale": "zh-CN"},
    {"id": "male-qn-badao", "name": "霸道青年音色", "locale": "zh-CN"},
    {"id": "male-qn-daxuesheng", "name": "青年大学生音色", "locale": "zh-CN"},
    {"id": "female-shaonv", "name": "少女音色", "locale": "zh-CN"},
    {"id": "female-yujie", "name": "御姐音色", "locale": "zh-CN"},
    {"id": "female-chengshu", "name": "成熟女性音色", "locale": "zh-CN"},
    {"id": "female-tianmei", "name": "甜美女性音色", "locale": "zh-CN"},
    {"id": "male-qn-qingse-jingpin", "name": "青涩青年音色-beta", "locale": "zh-CN"},
    {"id": "male-qn-jingying-jingpin", "name": "精英青年音色-beta", "locale": "zh-CN"},
    {"id": "male-qn-badao-jingpin", "name": "霸道青年音色-beta", "locale": "zh-CN"},
    {"id": "male-qn-daxuesheng-jingpin", "name": "青年大学生音色-beta", "locale": "zh-CN"},
    {"id": "female-shaonv-jingpin", "name": "少女音色-beta", "locale": "zh-CN"},
    {"id": "female-yujie-jingpin", "name": "御姐音色-beta", "locale": "zh-CN"},
    {"id": "female-chengshu-jingpin", "name": "成熟女性音色-beta", "locale": "zh-CN"},
    {"id": "female-tianmei-jingpin", "name": "甜美女性音色-beta", "locale": "zh-CN"},
    {"id": "clever_boy", "name": "聪明男童", "locale": "zh-CN"},
    {"id": "cute_boy", "name": "可爱男童", "locale": "zh-CN"},
    {"id": "lovely_girl", "name": "萌萌女童", "locale": "zh-CN"},
    {"id": "cartoon_pig", "name": "卡通猪小琪", "locale": "zh-CN"},
    {"id": "bingjiao_didi", "name": "病娇弟弟", "locale": "zh-CN"},
    {"id": "junlang_nanyou", "name": "俊朗男友", "locale": "zh-CN"},
    {"id": "chunzhen_xuedi", "name": "纯真学弟", "locale": "zh-CN"},
    {"id": "lengdan_xiongzhang", "name": "冷淡学长", "locale": "zh-CN"},
    {"id": "badao_shaoye", "name": "霸道少爷", "locale": "zh-CN"},
    {"id": "tianxin_xiaoling", "name": "甜心小玲", "locale": "zh-CN"},
    {"id": "qiaopi_mengmei", "name": "俏皮萌妹", "locale": "zh-CN"},
    {"id": "wumei_yujie", "name": "妩媚御姐", "locale": "zh-CN"},
    {"id": "diadia_xuemei", "name": "嗲嗲学妹", "locale": "zh-CN"},
    {"id": "danya_xuejie", "name": "淡雅学姐", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Reliable_Executive", "name": "沉稳高管", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_News_Anchor", "name": "新闻女声", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Mature_Woman", "name": "傲娇御姐", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Unrestrained_Young_Man", "name": "不羁青年", "locale": "zh-CN"},
    {"id": "Arrogant_Miss", "name": "嚣张小姐", "locale": "zh-CN"},
    {"id": "Robot_Armor", "name": "机械战甲", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Kind-hearted_Antie", "name": "热心大婶", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_HK_Flight_Attendant", "name": "港普空姐", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Humorous_Elder", "name": "搞笑大爷", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Gentleman", "name": "温润男声", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Warm_Bestie", "name": "温暖闺蜜", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Male_Announcer", "name": "播报男声", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Sweet_Lady", "name": "甜美女声", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Southern_Young_Man", "name": "南方小哥", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Wise_Women", "name": "阅历姐姐", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Gentle_Youth", "name": "温润青年", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Warm_Girl", "name": "温暖少女", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Kind-hearted_Elder", "name": "花甲奶奶", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Cute_Spirit", "name": "憨憨萌兽", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Radio_Host", "name": "电台男主播", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Lyrical_Voice", "name": "抒情男声", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Straightforward_Boy", "name": "率真弟弟", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Sincere_Adult", "name": "真诚青年", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Gentle_Senior", "name": "温柔学姐", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Stubborn_Friend", "name": "嘴硬竹马", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Crisp_Girl", "name": "清脆少女", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Pure-hearted_Boy", "name": "清澈邻家弟弟", "locale": "zh-CN"},
    {"id": "Chinese (Mandarin)_Soft_Girl", "name": "软软女孩", "locale": "zh-CN"},
    {"id": "Cantonese_ProfessionalHost（F)", "name": "专业女主持", "locale": "zh-HK"},
    {"id": "Cantonese_GentleLady", "name": "温柔女声", "locale": "zh-HK"},
    {"id": "Cantonese_ProfessionalHost（M)", "name": "专业男主持", "locale": "zh-HK"},
    {"id": "Cantonese_PlayfulMan", "name": "活泼男声", "locale": "zh-HK"},
    {"id": "Cantonese_CuteGirl", "name": "可爱女孩", "locale": "zh-HK"},
    {"id": "Cantonese_KindWoman", "name": "善良女声", "locale": "zh-HK"},
]
MINIMAX_TTS_FALLBACK_VOICES = MINIMAX_TTS_PRESET_VOICES


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


def normalize_minimax_audio_model(value: Any, default: str = DEFAULT_MINIMAX_AUDIO_MODEL) -> str:
    normalized = str(value or default).strip() or default
    return normalized if normalized in MINIMAX_AUDIO_MODEL_OPTIONS else default


def normalize_minimax_voice_id(value: Any, default: str = DEFAULT_MINIMAX_VOICE_ID) -> str:
    normalized = str(value or default).strip()
    return normalized or default


def normalize_minimax_audio_speed(value: Any, default: float = 1.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.5, min(2.0, parsed))


def _extract_error_message(payload: Any) -> str:
    if isinstance(payload, dict):
        base_resp = payload.get("base_resp")
        if isinstance(base_resp, dict):
            message = str(base_resp.get("status_msg") or "").strip()
            if message:
                return message
        for key in ("error_message", "message", "msg", "error", "detail"):
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


def _extract_audio_hex(payload: dict[str, Any]) -> str:
    data = payload.get("data")
    if not isinstance(data, dict):
        return ""
    return str(data.get("audio") or "").strip()


def _is_sync_success(payload: dict[str, Any]) -> bool:
    base_resp = payload.get("base_resp")
    if not isinstance(base_resp, dict):
        return False
    try:
        status_code = base_resp.get("status_code")
        if status_code is None:
            return False
        return int(status_code) == 0
    except (TypeError, ValueError):
        return False


def _resolve_duration(file_path: Path) -> float:
    try:
        parsed = MutagenFile(str(file_path))
        if parsed is None or parsed.info is None:
            return 0.0
        return float(parsed.info.length)
    except Exception:
        return 0.0


@audio_registry.register("minimax_tts")
class MiniMaxTTSProvider(AudioProvider):
    DEFAULT_VOICE_ID = DEFAULT_MINIMAX_VOICE_ID
    DEFAULT_MODEL = DEFAULT_MINIMAX_AUDIO_MODEL

    def __init__(
        self,
        api_key: str = "",
        base_url: str = DEFAULT_MINIMAX_BASE_URL,
        model: str = DEFAULT_MINIMAX_AUDIO_MODEL,
        voice_id: str = DEFAULT_MINIMAX_VOICE_ID,
        speed: float = 1.0,
        request_timeout: float = 60.0,
        poll_interval: float = 2.0,
        max_wait_time: float = 300.0,
    ) -> None:
        self.api_key = normalize_minimax_api_key(api_key)
        self.base_url = normalize_minimax_base_url(base_url)
        self.model = normalize_minimax_audio_model(model)
        self.voice_id = normalize_minimax_voice_id(voice_id)
        self.speed = normalize_minimax_audio_speed(speed, 1.0)
        self.request_timeout = max(float(request_timeout or 60.0), 10.0)
        self.poll_interval = max(float(poll_interval or 2.0), 0.5)
        self.max_wait_time = max(float(max_wait_time or 300.0), self.poll_interval)

    def _validate_config(self) -> None:
        if not self.api_key:
            raise ValueError("MiniMax TTS 需要配置 API Key")

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _synthesize_once(
        self,
        *,
        output_path: Path,
        request_payload: dict[str, Any],
        trust_env: bool,
    ) -> None:
        timeout = httpx.Timeout(self.request_timeout, connect=20.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=trust_env) as client:
            response = await client.post(
                f"{self.base_url}/t2a_v2",
                headers=self._build_headers(),
                json=request_payload,
            )
            if response.status_code >= 400:
                raise RuntimeError(f"MiniMax TTS 请求失败: {_extract_http_error_message(response)}")
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError(f"MiniMax TTS 响应结构异常: {payload}")
            if not _is_sync_success(payload):
                raise RuntimeError(
                    f"MiniMax TTS 请求失败: {_extract_error_message(payload) or payload}"
                )
            audio_hex = _extract_audio_hex(payload)
            if not audio_hex:
                raise RuntimeError(f"MiniMax TTS 响应缺少音频数据: {payload}")
            try:
                audio_bytes = bytes.fromhex(audio_hex)
            except ValueError as exc:
                raise RuntimeError("MiniMax TTS 返回的音频数据无法解码") from exc

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio_bytes)

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

        resolved_model = normalize_minimax_audio_model(
            kwargs.get("model") or kwargs.get("audio_minimax_model") or self.model
        )
        resolved_voice_id = normalize_minimax_voice_id(
            voice or kwargs.get("voice_id") or kwargs.get("audio_minimax_voice_id") or self.voice_id
        )
        resolved_speed = normalize_minimax_audio_speed(
            kwargs.get("speed")
            if kwargs.get("speed") is not None
            else kwargs.get("audio_minimax_speed", self.speed),
            self.speed,
        )
        request_payload: dict[str, Any] = {
            "model": resolved_model,
            "text": content,
            "stream": False,
            "voice_setting": {
                "voice_id": resolved_voice_id,
                "speed": resolved_speed,
                "vol": 1,
                "pitch": 0,
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1,
            },
            "language_boost": "auto",
            "subtitle_enable": False,
            "output_format": "hex",
        }

        try:
            await self._synthesize_once(
                output_path=output_path,
                request_payload=request_payload,
                trust_env=True,
            )
        except (httpx.ConnectTimeout, httpx.ProxyError, httpx.ConnectError) as exc:
            logger.warning(
                "[MiniMax TTS] proxy/network connect failed with trust_env=True, retrying direct connection: %s",
                exc,
            )
            await self._synthesize_once(
                output_path=output_path,
                request_payload=request_payload,
                trust_env=False,
            )

        duration = _resolve_duration(output_path)
        return AudioResult(file_path=output_path, duration=max(duration, 0.0), sample_rate=32000)

    def list_voices(self) -> list[str]:
        return [
            str(item.get("id") or "").strip()
            for item in MINIMAX_TTS_PRESET_VOICES
            if item.get("id")
        ]
