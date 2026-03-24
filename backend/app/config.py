from pathlib import Path
from typing import Any, ClassVar

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.dialogue import DEFAULT_DIALOGUE_MAX_ROLES
from app.image_catalog import default_image_providers
from app.llm.catalog import default_llm_providers

BASE_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        case_sensitive=False,
    )

    project_name: str = "LocalVideo Backend"
    project_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    debug: bool = False

    database_url: str = Field(default=f"sqlite+aiosqlite:///{BASE_DIR / 'app.db'}")

    # Search Provider - Tavily
    search_tavily_api_key: str | None = Field(default=None)
    jina_reader_api_key: str | None = Field(default=None)
    jina_reader_ignore_images: bool = True
    web_url_parser_provider: str = "jina_reader"
    crawl4ai_ignore_images: bool = True
    crawl4ai_ignore_links: bool = True

    # Text Generation (LLM) - OpenAI Compatible
    text_openai_api_key: str | None = Field(default=None)
    text_openai_base_url: str | None = Field(default=None)
    text_openai_model: str = "gpt-4-turbo"

    # Audio Provider - Edge TTS
    edge_tts_voice: str = "zh-CN-YunjianNeural"
    edge_tts_rate: str = "+30%"
    volcengine_tts_app_key: str | None = Field(default=None)
    volcengine_tts_access_key: str | None = Field(default=None)
    volcengine_tts_resource_id: str = "seed-tts-2.0"
    volcengine_tts_model_name: str = "seed-tts-2.0"
    audio_volcengine_tts_voice_type: str = "zh_female_vv_uranus_bigtts"
    audio_volcengine_tts_speed_ratio: float = 1.0
    audio_volcengine_tts_volume_ratio: float = 1.0
    audio_volcengine_tts_pitch_ratio: float = 1.0
    audio_volcengine_tts_encoding: str = "mp3"
    audio_wan2gp_preset: str = "qwen3_tts_base"
    audio_wan2gp_model_mode: str = "serena"
    audio_wan2gp_alt_prompt: str = "calm, friendly, slightly husky"
    audio_wan2gp_duration_seconds: int = 600
    audio_wan2gp_temperature: float = 0.9
    audio_wan2gp_top_k: int = 50
    audio_wan2gp_seed: int = -1
    audio_wan2gp_audio_guide: str = ""
    audio_wan2gp_speed: float = 1.0
    audio_wan2gp_split_strategy: str = "sentence_punct"
    kling_access_key: str | None = Field(default=None)
    kling_secret_key: str | None = Field(default=None)
    kling_base_url: str = "https://api-beijing.klingai.com"
    audio_kling_voice_id: str = "zh_male_qn_qingse"
    audio_kling_voice_language: str = "zh"
    audio_kling_voice_speed: float = 1.0
    vidu_api_key: str | None = Field(default=None)
    vidu_base_url: str = "https://api.vidu.cn"
    audio_vidu_voice_id: str = "female-shaonv"
    audio_vidu_speed: float = 1.0
    audio_vidu_volume: float = 1.0
    audio_vidu_pitch: float = 0.0
    audio_vidu_emotion: str = ""
    minimax_api_key: str | None = Field(default=None)
    minimax_base_url: str = "https://api.minimaxi.com/v1"
    audio_minimax_model: str = "speech-2.8-turbo"
    audio_minimax_voice_id: str = "Chinese (Mandarin)_Reliable_Executive"
    audio_minimax_speed: float = 1.0
    xiaomi_mimo_api_key: str | None = Field(default=None)
    xiaomi_mimo_base_url: str = "https://api.xiaomimimo.com/v1"
    audio_xiaomi_mimo_voice: str = "mimo_default"
    audio_xiaomi_mimo_style_preset: str = ""
    audio_xiaomi_mimo_speed: float = 1.0
    audio_xiaomi_mimo_format: str = "wav"

    # Local model shared config
    deployment_profile: str = Field(default="cpu")
    wan2gp_path: str | None = Field(default=None)
    local_model_python_path: str | None = Field(default=None)
    wan2gp_fit_canvas: int = 0
    xhs_downloader_path: str | None = Field(default=None)
    tiktok_downloader_path: str | None = Field(default=None)
    ks_downloader_path: str | None = Field(default=None)
    speech_volcengine_app_key: str | None = Field(default=None)
    speech_volcengine_access_key: str | None = Field(default=None)
    speech_volcengine_resource_id: str = "volc.seedasr.auc"
    speech_volcengine_language: str | None = Field(default=None)
    faster_whisper_model: str = "large-v3"
    dialogue_script_max_roles: int = DEFAULT_DIALOGUE_MAX_ROLES
    wan2gp_validation_status: str = "not_ready"
    xhs_downloader_validation_status: str = "not_ready"
    tiktok_downloader_validation_status: str = "not_ready"
    ks_downloader_validation_status: str = "not_ready"
    faster_whisper_validation_status: str = "not_ready"
    speech_volcengine_validation_status: str = "not_ready"
    crawl4ai_validation_status: str = "not_ready"
    card_scheduler_max_concurrent_tasks: int = 6
    card_scheduler_url_parse_concurrency: int = 4
    card_scheduler_video_download_concurrency: int = 1
    card_scheduler_audio_transcribe_concurrency: int = 1
    card_scheduler_audio_prepare_concurrency: int = 1
    card_scheduler_audio_proofread_concurrency: int = 2
    card_scheduler_audio_name_concurrency: int = 2
    card_scheduler_text_proofread_concurrency: int = 2
    card_scheduler_text_name_concurrency: int = 3
    card_scheduler_reference_describe_concurrency: int = 2
    card_scheduler_reference_name_concurrency: int = 2
    library_import_stale_timeout_seconds: int = 300
    library_import_reconcile_interval_seconds: int = 30
    library_batch_max_items: int = 50
    library_batch_max_total_upload_mb: int = 1024

    # Image Generation - OpenAI Chat Compatible
    image_openai_api_key: str | None = Field(default=None)
    image_openai_base_url: str | None = Field(default=None)
    image_openai_model: str = "gemini-3-pro-image-preview"
    image_openai_reference_aspect_ratio: str = "1:1"
    image_openai_reference_size: str = "1K"
    image_openai_frame_aspect_ratio: str = "9:16"
    image_openai_frame_size: str = "1K"

    # Image Generation - Vertex AI
    image_vertex_ai_project: str | None = Field(default=None)
    image_vertex_ai_location: str = "us-central1"
    image_vertex_ai_model: str = "gemini-3-pro-image-preview"
    image_vertex_ai_reference_aspect_ratio: str = "1:1"
    image_vertex_ai_reference_size: str = "1K"
    image_vertex_ai_frame_aspect_ratio: str = "9:16"
    image_vertex_ai_frame_size: str = "1K"

    # Image Generation - Gemini API
    image_gemini_api_key: str | None = Field(default=None)
    image_gemini_model: str = "gemini-3-pro-image-preview"
    image_gemini_reference_aspect_ratio: str = "1:1"
    image_gemini_reference_size: str = "1K"
    image_gemini_frame_aspect_ratio: str = "9:16"
    image_gemini_frame_size: str = "1K"

    # Image Generation - Wan2GP (local)
    image_wan2gp_preset: str = "qwen_image_2512"
    image_wan2gp_preset_i2i: str = "qwen_image_edit_plus2"
    image_wan2gp_reference_resolution: str = "1024x1024"
    image_wan2gp_frame_resolution: str = "1088x1920"
    image_wan2gp_inference_steps: int = 0
    image_wan2gp_guidance_scale: float = 0.0
    image_wan2gp_seed: int = -1
    image_wan2gp_negative_prompt: str = ""
    image_wan2gp_enabled_models: list[str] | None = Field(default=None)
    image_kling_t2i_model: str = "kling-v3"
    image_kling_i2i_model: str = "kling-v3"
    image_kling_reference_aspect_ratio: str = "1:1"
    image_kling_reference_size: str = "1K"
    image_kling_frame_aspect_ratio: str = "9:16"
    image_kling_frame_size: str = "1K"
    image_kling_enabled_models: list[str] | None = None
    image_vidu_t2i_model: str = "viduq2"
    image_vidu_i2i_model: str = "viduq2"
    image_vidu_reference_aspect_ratio: str = "1:1"
    image_vidu_reference_size: str = "1080p"
    image_vidu_frame_aspect_ratio: str = "9:16"
    image_vidu_frame_size: str = "1080p"
    image_vidu_enabled_models: list[str] | None = None
    image_minimax_model: str = "image-01"
    image_minimax_reference_aspect_ratio: str = "1:1"
    image_minimax_reference_size: str = "2K"
    image_minimax_frame_aspect_ratio: str = "9:16"
    image_minimax_frame_size: str = "2K"
    image_minimax_enabled_models: list[str] | None = None

    # Google Cloud 共享凭证
    google_credentials_path: str | None = Field(default=None)

    # Video Generation - Seedance (Volcengine Ark)
    video_seedance_api_key: str | None = Field(default=None)
    video_seedance_base_url: str = "https://kwjm.com"
    video_seedance_model: str = "seedance-2-0"
    video_seedance_aspect_ratio: str = "adaptive"
    video_seedance_resolution: str = "720p"
    video_seedance_watermark: bool = False
    video_seedance_enabled_models: list[str] | None = Field(default=None)

    # Video Generation - Wan2GP (local)
    video_wan2gp_t2v_preset: str = "t2v_1.3B"
    video_wan2gp_i2v_preset: str = "i2v_720p"
    video_wan2gp_resolution: str = "720x1280"
    video_wan2gp_negative_prompt: str = ""
    video_wan2gp_enabled_models: list[str] | None = Field(default=None)
    video_kling_model: str = "kling-v3"
    video_kling_aspect_ratio: str = "9:16"
    video_kling_mode: str = "std"
    video_vidu_model: str = "viduq3-turbo"
    video_vidu_aspect_ratio: str = "9:16"
    video_vidu_resolution: str = "1080p"
    video_vidu_enabled_models: list[str] | None = None
    video_minimax_model: str = "MiniMax-Hailuo-2.3"
    video_minimax_aspect_ratio: str = "9:16"
    video_minimax_resolution: str = "1080P"
    video_minimax_enabled_models: list[str] | None = None

    # Default Providers
    default_llm_provider: str = "builtin_openai"
    llm_providers: list[dict[str, Any]] = Field(default_factory=default_llm_providers)
    default_search_provider: str = "tavily"
    default_audio_provider: str = "edge_tts"
    default_speech_recognition_provider: str = "faster_whisper"
    default_image_provider: str = ""
    image_providers: list[dict[str, Any]] = Field(default_factory=default_image_providers)
    default_video_provider: str = "volcengine_seedance"
    default_speech_recognition_model: str = ""
    default_general_llm_model: str = ""
    default_fast_llm_model: str = ""
    default_multimodal_llm_model: str = ""
    default_image_t2i_model: str = ""
    default_image_i2i_model: str = ""
    default_video_t2v_model: str = ""
    default_video_i2v_model: str = ""

    storage_path: str = Field(default=str(BASE_DIR / "storage"))
    subtitle_font_name: str | None = Field(default=None)
    subtitle_font_file: str | None = Field(default=None)

    cors_origins: list[str] = Field(default=["http://localhost:3000", "http://localhost:8000"])
    cors_origin_regex: str = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

    workers_enabled: bool = False
    celery_broker_url: str | None = Field(default=None)
    celery_result_backend_url: str | None = Field(default=None)

    @field_validator("database_url", mode="after")
    @classmethod
    def normalize_sqlite_url(cls, value: str) -> str:
        prefixes = ("sqlite+aiosqlite:///", "sqlite:///")
        for prefix in prefixes:
            if not value.startswith(prefix):
                continue

            path_and_query = value[len(prefix) :]
            if path_and_query.startswith("/") or path_and_query.startswith(":memory:"):
                return value

            if "?" in path_and_query:
                raw_path, query = path_and_query.split("?", 1)
                suffix = f"?{query}"
            else:
                raw_path = path_and_query
                suffix = ""

            absolute_path = (BASE_DIR / raw_path).resolve()
            return f"{prefix}{absolute_path}{suffix}"

        return value

    @field_validator("debug", mode="before")
    @classmethod
    def normalize_debug_flag(cls, value: object) -> bool:
        if isinstance(value, bool):
            return value
        text = str(value or "").strip().lower()
        if text in {"1", "true", "yes", "on", "debug", "dev", "development"}:
            return True
        if text in {"0", "false", "no", "off", "release", "prod", "production", ""}:
            return False
        return bool(value)

    @field_validator("deployment_profile", mode="before")
    @classmethod
    def normalize_deployment_profile(cls, value: object) -> str:
        candidate = str(value or "").strip().lower()
        return "gpu" if candidate == "gpu" else "cpu"

    @field_validator("storage_path", mode="after")
    @classmethod
    def normalize_storage_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute():
            return str(path)
        return str((BASE_DIR / path).resolve())

    @field_validator("subtitle_font_file", mode="after")
    @classmethod
    def normalize_subtitle_font_file(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        path = Path(normalized)
        if path.is_absolute():
            return str(path)
        return str((BASE_DIR / path).resolve())


settings = Settings()
