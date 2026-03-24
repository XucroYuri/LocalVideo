from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.providers.audio.minimax_tts import (
    normalize_minimax_audio_model,
    normalize_minimax_audio_speed,
    normalize_minimax_voice_id,
)
from app.providers.audio.volcengine_tts_models import (
    VOLCENGINE_TTS_DEFAULT_MODEL_NAME,
    is_volcengine_tts_voice_supported,
    normalize_volcengine_tts_model_name,
    resolve_default_volcengine_tts_voice_type,
    resolve_volcengine_tts_resource_id,
)
from app.providers.audio.xiaomi_mimo_tts import (
    normalize_xiaomi_mimo_style_preset,
    normalize_xiaomi_mimo_voice,
)


def normalize_wan2gp_split_strategy(value: Any, default: str = "sentence_punct") -> str:
    text = str(value or "").strip().lower()
    if text == "anchor_tail":
        return "anchor_tail"
    if text == "sentence_punct":
        return "sentence_punct"
    return "anchor_tail" if default == "anchor_tail" else "sentence_punct"


def normalize_speed(value: Any, default: float = 1.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.5, min(2.0, parsed))


def normalize_volc_encoding(value: Any, default: str = "mp3") -> str:
    normalized = str(value or default).strip().lower() or default
    return normalized if normalized in {"mp3", "wav", "pcm", "ogg_opus"} else default


def normalize_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return None


@dataclass
class AudioConfigResolver:
    provider_name: str
    voice: str
    rate: str
    speed: float | None
    kling_voice_id: str
    kling_voice_language: str
    vidu_voice_id: str
    vidu_voice_speed: float
    vidu_voice_volume: float
    vidu_voice_pitch: float
    vidu_voice_emotion: str
    minimax_model: str
    minimax_voice_id: str
    minimax_voice_speed: float
    xiaomi_mimo_voice: str
    xiaomi_mimo_style_preset: str
    volcengine_tts_voice_type: str
    volcengine_tts_speed_ratio: float
    volcengine_tts_volume_ratio: float
    volcengine_tts_pitch_ratio: float
    volcengine_tts_encoding: str
    volcengine_tts_resource_id: str
    volcengine_tts_model_name: str
    wan2gp_preset: str
    wan2gp_model_mode: str
    wan2gp_alt_prompt: str
    wan2gp_duration_seconds: int | None
    wan2gp_temperature: float
    wan2gp_top_k: int
    wan2gp_seed: int
    wan2gp_audio_guide: str
    wan2gp_split_strategy: str
    wan2gp_local_stitch_keep_artifacts: bool | None

    @classmethod
    def resolve(cls, input_data: dict[str, Any], config: dict[str, Any]) -> "AudioConfigResolver":
        provider_name_raw = (
            input_data.get("audio_provider")
            or config.get("audio_provider")
            or settings.default_audio_provider
            or "edge_tts"
        )
        provider_name = str(provider_name_raw).strip().lower() or "edge_tts"
        if provider_name not in {
            "edge_tts",
            "wan2gp",
            "volcengine_tts",
            "kling_tts",
            "vidu_tts",
            "minimax_tts",
            "xiaomi_mimo_tts",
        }:
            provider_name = "edge_tts"

        voice = input_data.get("voice") or config.get("edge_tts_voice", "zh-CN-YunjianNeural")
        speed_raw = input_data.get("speed")
        speed: float | None = None
        if speed_raw is not None:
            speed = normalize_speed(speed_raw, 1.0)
        elif provider_name == "wan2gp":
            speed = normalize_speed(
                config.get("audio_wan2gp_speed", settings.audio_wan2gp_speed),
                settings.audio_wan2gp_speed,
            )
        elif provider_name == "kling_tts":
            speed = normalize_speed(
                input_data.get("audio_kling_voice_speed")
                if input_data.get("audio_kling_voice_speed") is not None
                else config.get("audio_kling_voice_speed", settings.audio_kling_voice_speed),
                settings.audio_kling_voice_speed,
            )
        elif provider_name == "vidu_tts":
            speed = normalize_speed(
                input_data.get("audio_vidu_speed")
                if input_data.get("audio_vidu_speed") is not None
                else config.get("audio_vidu_speed", settings.audio_vidu_speed),
                settings.audio_vidu_speed,
            )
        elif provider_name == "minimax_tts":
            speed = normalize_minimax_audio_speed(
                input_data.get("audio_minimax_speed")
                if input_data.get("audio_minimax_speed") is not None
                else config.get("audio_minimax_speed", settings.audio_minimax_speed),
                settings.audio_minimax_speed,
            )
        elif provider_name == "xiaomi_mimo_tts":
            speed = normalize_speed(
                input_data.get("audio_xiaomi_mimo_speed")
                if input_data.get("audio_xiaomi_mimo_speed") is not None
                else config.get("audio_xiaomi_mimo_speed", settings.audio_xiaomi_mimo_speed),
                settings.audio_xiaomi_mimo_speed,
            )

        if speed is not None:
            rate_percent = int((speed - 1) * 100)
            rate = f"+{rate_percent}%" if rate_percent >= 0 else f"{rate_percent}%"
        else:
            rate = config.get("edge_tts_rate", "+30%")

        volcengine_tts_speed_ratio = normalize_speed(
            input_data.get("audio_volcengine_tts_speed_ratio")
            if input_data.get("audio_volcengine_tts_speed_ratio") is not None
            else config.get(
                "audio_volcengine_tts_speed_ratio",
                settings.audio_volcengine_tts_speed_ratio,
            ),
            settings.audio_volcengine_tts_speed_ratio,
        )
        if speed_raw is not None and provider_name == "volcengine_tts":
            volcengine_tts_speed_ratio = normalize_speed(speed_raw, volcengine_tts_speed_ratio)
        if provider_name == "volcengine_tts":
            speed = volcengine_tts_speed_ratio
            rate_percent = int((volcengine_tts_speed_ratio - 1) * 100)
            rate = f"+{rate_percent}%" if rate_percent >= 0 else f"{rate_percent}%"

        kling_voice_id = (
            str(
                input_data.get("voice")
                or input_data.get("audio_kling_voice_id")
                or config.get("audio_kling_voice_id")
                or settings.audio_kling_voice_id
                or "zh_male_qn_qingse"
            ).strip()
            or "zh_male_qn_qingse"
        )
        kling_voice_language = (
            str(
                input_data.get("audio_kling_voice_language")
                or config.get("audio_kling_voice_language")
                or settings.audio_kling_voice_language
                or "zh"
            )
            .strip()
            .lower()
            or "zh"
        )
        if kling_voice_language not in {"zh", "en"}:
            kling_voice_language = "zh"
        vidu_voice_id = (
            str(
                input_data.get("voice")
                or input_data.get("audio_vidu_voice_id")
                or config.get("audio_vidu_voice_id")
                or settings.audio_vidu_voice_id
                or "female-shaonv"
            ).strip()
            or "female-shaonv"
        )
        vidu_voice_speed = normalize_speed(
            input_data.get("audio_vidu_speed")
            if input_data.get("audio_vidu_speed") is not None
            else config.get("audio_vidu_speed", settings.audio_vidu_speed),
            settings.audio_vidu_speed,
        )
        try:
            vidu_voice_volume = float(
                input_data.get("audio_vidu_volume")
                if input_data.get("audio_vidu_volume") is not None
                else config.get("audio_vidu_volume", settings.audio_vidu_volume)
            )
        except (TypeError, ValueError):
            vidu_voice_volume = float(settings.audio_vidu_volume or 1.0)
        vidu_voice_volume = max(0.0, min(10.0, vidu_voice_volume))
        try:
            vidu_voice_pitch = float(
                input_data.get("audio_vidu_pitch")
                if input_data.get("audio_vidu_pitch") is not None
                else config.get("audio_vidu_pitch", settings.audio_vidu_pitch)
            )
        except (TypeError, ValueError):
            vidu_voice_pitch = float(settings.audio_vidu_pitch or 0.0)
        vidu_voice_pitch = max(-12.0, min(12.0, vidu_voice_pitch))
        vidu_voice_emotion = str(
            input_data.get("audio_vidu_emotion")
            if input_data.get("audio_vidu_emotion") is not None
            else config.get("audio_vidu_emotion", settings.audio_vidu_emotion) or ""
        ).strip()
        minimax_model = normalize_minimax_audio_model(
            input_data.get("audio_minimax_model")
            or config.get("audio_minimax_model")
            or settings.audio_minimax_model
            or "speech-2.8-turbo"
        )
        minimax_voice_id = normalize_minimax_voice_id(
            input_data.get("voice")
            or input_data.get("audio_minimax_voice_id")
            or config.get("audio_minimax_voice_id")
            or settings.audio_minimax_voice_id
            or "Chinese (Mandarin)_Reliable_Executive"
        )
        minimax_voice_speed = normalize_minimax_audio_speed(
            input_data.get("audio_minimax_speed")
            if input_data.get("audio_minimax_speed") is not None
            else config.get("audio_minimax_speed", settings.audio_minimax_speed),
            settings.audio_minimax_speed,
        )
        xiaomi_mimo_voice = normalize_xiaomi_mimo_voice(
            input_data.get("voice")
            or input_data.get("audio_xiaomi_mimo_voice")
            or config.get("audio_xiaomi_mimo_voice")
            or settings.audio_xiaomi_mimo_voice
            or "mimo_default"
        )
        xiaomi_mimo_style_preset = normalize_xiaomi_mimo_style_preset(
            input_data.get("audio_xiaomi_mimo_style_preset")
            if input_data.get("audio_xiaomi_mimo_style_preset") is not None
            else config.get(
                "audio_xiaomi_mimo_style_preset",
                settings.audio_xiaomi_mimo_style_preset,
            )
        )

        volcengine_tts_model_name = normalize_volcengine_tts_model_name(
            input_data.get("volcengine_tts_model_name")
            or config.get("volcengine_tts_model_name")
            or settings.volcengine_tts_model_name
            or VOLCENGINE_TTS_DEFAULT_MODEL_NAME
        )
        default_volc_voice = resolve_default_volcengine_tts_voice_type(volcengine_tts_model_name)
        volcengine_tts_voice_type = (
            str(
                input_data.get("voice")
                or input_data.get("audio_volcengine_tts_voice_type")
                or config.get("audio_volcengine_tts_voice_type")
                or settings.audio_volcengine_tts_voice_type
                or default_volc_voice
            ).strip()
            or default_volc_voice
        )
        if not is_volcengine_tts_voice_supported(
            volcengine_tts_model_name, volcengine_tts_voice_type
        ):
            volcengine_tts_voice_type = default_volc_voice
        volcengine_tts_volume_ratio = normalize_speed(
            input_data.get("audio_volcengine_tts_volume_ratio")
            if input_data.get("audio_volcengine_tts_volume_ratio") is not None
            else config.get(
                "audio_volcengine_tts_volume_ratio",
                settings.audio_volcengine_tts_volume_ratio,
            ),
            settings.audio_volcengine_tts_volume_ratio,
        )
        volcengine_tts_pitch_ratio = normalize_speed(
            input_data.get("audio_volcengine_tts_pitch_ratio")
            if input_data.get("audio_volcengine_tts_pitch_ratio") is not None
            else config.get(
                "audio_volcengine_tts_pitch_ratio",
                settings.audio_volcengine_tts_pitch_ratio,
            ),
            settings.audio_volcengine_tts_pitch_ratio,
        )
        volcengine_tts_encoding = normalize_volc_encoding(
            input_data.get("audio_volcengine_tts_encoding")
            if input_data.get("audio_volcengine_tts_encoding") is not None
            else config.get(
                "audio_volcengine_tts_encoding",
                settings.audio_volcengine_tts_encoding,
            ),
            settings.audio_volcengine_tts_encoding,
        )
        volcengine_tts_resource_id = resolve_volcengine_tts_resource_id(volcengine_tts_model_name)

        wan2gp_preset = str(
            input_data.get("audio_wan2gp_preset")
            or config.get("audio_wan2gp_preset")
            or settings.audio_wan2gp_preset
            or "qwen3_tts_base"
        ).strip()
        wan2gp_model_mode = str(
            input_data.get("audio_wan2gp_model_mode")
            or config.get("audio_wan2gp_model_mode")
            or settings.audio_wan2gp_model_mode
            or ""
        ).strip()
        wan2gp_alt_prompt = (
            input_data.get("audio_wan2gp_alt_prompt")
            if input_data.get("audio_wan2gp_alt_prompt") is not None
            else config.get("audio_wan2gp_alt_prompt", settings.audio_wan2gp_alt_prompt)
        )
        if wan2gp_alt_prompt is None:
            wan2gp_alt_prompt = ""

        wan2gp_duration_seconds_raw = input_data.get("audio_wan2gp_duration_seconds")
        wan2gp_duration_seconds: int | None = None
        if wan2gp_duration_seconds_raw is not None:
            try:
                parsed_duration = int(wan2gp_duration_seconds_raw)
            except (TypeError, ValueError):
                parsed_duration = 0
            if parsed_duration > 0:
                wan2gp_duration_seconds = parsed_duration

        wan2gp_temperature = input_data.get("audio_wan2gp_temperature")
        if wan2gp_temperature is None:
            wan2gp_temperature = config.get(
                "audio_wan2gp_temperature",
                settings.audio_wan2gp_temperature,
            )
        try:
            wan2gp_temperature = float(wan2gp_temperature)
        except (TypeError, ValueError):
            wan2gp_temperature = settings.audio_wan2gp_temperature
        if wan2gp_temperature <= 0:
            wan2gp_temperature = settings.audio_wan2gp_temperature

        wan2gp_top_k = input_data.get("audio_wan2gp_top_k")
        if wan2gp_top_k is None:
            wan2gp_top_k = config.get("audio_wan2gp_top_k", settings.audio_wan2gp_top_k)
        try:
            wan2gp_top_k = int(wan2gp_top_k)
        except (TypeError, ValueError):
            wan2gp_top_k = settings.audio_wan2gp_top_k
        if wan2gp_top_k <= 0:
            wan2gp_top_k = settings.audio_wan2gp_top_k

        wan2gp_seed = input_data.get("audio_wan2gp_seed")
        if wan2gp_seed is None:
            wan2gp_seed = config.get("audio_wan2gp_seed", settings.audio_wan2gp_seed)
        try:
            wan2gp_seed = int(wan2gp_seed)
        except (TypeError, ValueError):
            wan2gp_seed = settings.audio_wan2gp_seed

        wan2gp_audio_guide = (
            input_data.get("audio_wan2gp_audio_guide")
            if input_data.get("audio_wan2gp_audio_guide") is not None
            else config.get("audio_wan2gp_audio_guide", settings.audio_wan2gp_audio_guide)
        )
        wan2gp_audio_guide = str(wan2gp_audio_guide or "").strip()
        wan2gp_split_strategy = normalize_wan2gp_split_strategy(
            input_data.get("audio_wan2gp_split_strategy")
            if input_data.get("audio_wan2gp_split_strategy") is not None
            else config.get(
                "audio_wan2gp_split_strategy",
                settings.audio_wan2gp_split_strategy,
            ),
            settings.audio_wan2gp_split_strategy,
        )
        wan2gp_local_stitch_keep_artifacts = normalize_optional_bool(
            input_data.get("audio_wan2gp_local_stitch_keep_artifacts")
            if input_data.get("audio_wan2gp_local_stitch_keep_artifacts") is not None
            else config.get("audio_wan2gp_local_stitch_keep_artifacts")
        )

        return cls(
            provider_name=provider_name,
            voice=voice,
            rate=rate,
            speed=speed,
            kling_voice_id=kling_voice_id,
            kling_voice_language=kling_voice_language,
            vidu_voice_id=vidu_voice_id,
            vidu_voice_speed=vidu_voice_speed,
            vidu_voice_volume=vidu_voice_volume,
            vidu_voice_pitch=vidu_voice_pitch,
            vidu_voice_emotion=vidu_voice_emotion,
            minimax_model=minimax_model,
            minimax_voice_id=minimax_voice_id,
            minimax_voice_speed=minimax_voice_speed,
            xiaomi_mimo_voice=xiaomi_mimo_voice,
            xiaomi_mimo_style_preset=xiaomi_mimo_style_preset,
            volcengine_tts_voice_type=volcengine_tts_voice_type,
            volcengine_tts_speed_ratio=volcengine_tts_speed_ratio,
            volcengine_tts_volume_ratio=volcengine_tts_volume_ratio,
            volcengine_tts_pitch_ratio=volcengine_tts_pitch_ratio,
            volcengine_tts_encoding=volcengine_tts_encoding,
            volcengine_tts_resource_id=volcengine_tts_resource_id,
            volcengine_tts_model_name=volcengine_tts_model_name,
            wan2gp_preset=wan2gp_preset,
            wan2gp_model_mode=wan2gp_model_mode,
            wan2gp_alt_prompt=wan2gp_alt_prompt,
            wan2gp_duration_seconds=wan2gp_duration_seconds,
            wan2gp_temperature=wan2gp_temperature,
            wan2gp_top_k=wan2gp_top_k,
            wan2gp_seed=wan2gp_seed,
            wan2gp_audio_guide=wan2gp_audio_guide,
            wan2gp_split_strategy=wan2gp_split_strategy,
            wan2gp_local_stitch_keep_artifacts=wan2gp_local_stitch_keep_artifacts,
        )
