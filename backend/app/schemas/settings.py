from pydantic import BaseModel, ConfigDict, Field

from app.core.dialogue import DEFAULT_DIALOGUE_MAX_ROLES
from app.image_catalog import default_image_providers
from app.llm.catalog import default_llm_providers


class LLMProviderConfig(BaseModel):
    id: str
    name: str
    is_builtin: bool = False
    provider_type: str
    base_url: str
    api_key: str = ""
    catalog_models: list[str] = Field(default_factory=list)
    enabled_models: list[str] = Field(default_factory=list)
    default_model: str = ""
    supports_vision: bool = False


class ImageProviderConfig(BaseModel):
    id: str
    name: str
    is_builtin: bool = False
    provider_type: str
    base_url: str
    api_key: str = ""
    catalog_models: list[str] = Field(default_factory=list)
    enabled_models: list[str] = Field(default_factory=list)
    default_model: str = ""
    reference_aspect_ratio: str = "1:1"
    reference_size: str = "1K"
    frame_aspect_ratio: str = "9:16"
    frame_size: str = "1K"


class SettingsResponse(BaseModel):
    # Search Provider
    search_tavily_api_key_set: bool = False
    search_tavily_api_key: str | None = None
    jina_reader_api_key: str | None = None
    jina_reader_ignore_images: bool = True
    web_url_parser_provider: str = "jina_reader"
    crawl4ai_ignore_images: bool = True
    crawl4ai_ignore_links: bool = True
    is_containerized_runtime: bool = False

    # Text Generation (LLM)
    text_openai_api_key_set: bool = False
    text_openai_api_key: str | None = None
    text_openai_base_url: str | None = None
    text_openai_model: str = "gpt-4-turbo"
    llm_providers: list[LLMProviderConfig] = Field(default_factory=default_llm_providers)
    image_providers: list[ImageProviderConfig] = Field(default_factory=default_image_providers)

    # Audio Provider - Edge TTS
    edge_tts_voice: str = "zh-CN-YunjianNeural"
    edge_tts_rate: str = "+30%"
    volcengine_tts_app_key_set: bool = False
    volcengine_tts_app_key: str | None = None
    volcengine_tts_access_key_set: bool = False
    volcengine_tts_access_key: str | None = None
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
    kling_access_key_set: bool = False
    kling_access_key: str | None = None
    kling_secret_key_set: bool = False
    kling_secret_key: str | None = None
    kling_base_url: str = "https://api-beijing.klingai.com"
    audio_kling_voice_id: str = "zh_male_qn_qingse"
    audio_kling_voice_language: str = "zh"
    audio_kling_voice_speed: float = 1.0
    vidu_api_key_set: bool = False
    vidu_api_key: str | None = None
    vidu_base_url: str = "https://api.vidu.cn"
    audio_vidu_voice_id: str = "female-shaonv"
    audio_vidu_speed: float = 1.0
    audio_vidu_volume: float = 1.0
    audio_vidu_pitch: float = 0.0
    audio_vidu_emotion: str = ""
    minimax_api_key_set: bool = False
    minimax_api_key: str | None = None
    minimax_base_url: str = "https://api.minimaxi.com/v1"
    audio_minimax_model: str = "speech-2.8-turbo"
    audio_minimax_voice_id: str = "Chinese (Mandarin)_Reliable_Executive"
    audio_minimax_speed: float = 1.0
    xiaomi_mimo_api_key_set: bool = False
    xiaomi_mimo_api_key: str | None = None
    xiaomi_mimo_base_url: str = "https://api.xiaomimimo.com/v1"
    audio_xiaomi_mimo_voice: str = "mimo_default"
    audio_xiaomi_mimo_style_preset: str = ""
    audio_xiaomi_mimo_speed: float = 1.0
    audio_xiaomi_mimo_format: str = "wav"

    # Local model shared config
    deployment_profile: str = "cpu"
    wan2gp_path: str | None = None
    local_model_python_path: str | None = None
    wan2gp_fit_canvas: int = 0
    xhs_downloader_path: str | None = None
    tiktok_downloader_path: str | None = None
    ks_downloader_path: str | None = None
    speech_volcengine_app_key_set: bool = False
    speech_volcengine_app_key: str | None = None
    speech_volcengine_access_key_set: bool = False
    speech_volcengine_access_key: str | None = None
    speech_volcengine_resource_id: str = "volc.seedasr.auc"
    speech_volcengine_language: str | None = None
    faster_whisper_model: str = "large-v3"
    dialogue_script_max_roles: int = DEFAULT_DIALOGUE_MAX_ROLES
    wan2gp_validation_status: str = "not_ready"
    xhs_downloader_validation_status: str = "not_ready"
    tiktok_downloader_validation_status: str = "not_ready"
    ks_downloader_validation_status: str = "not_ready"
    faster_whisper_validation_status: str = "not_ready"
    speech_volcengine_validation_status: str = "not_ready"
    crawl4ai_validation_status: str = "not_ready"
    wan2gp_available: bool = False
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

    # Image Generation - OpenAI Chat Compatible
    image_openai_api_key_set: bool = False
    image_openai_api_key: str | None = None
    image_openai_base_url: str | None = None
    image_openai_model: str = "gemini-3-pro-image-preview"
    image_openai_reference_aspect_ratio: str = "1:1"
    image_openai_reference_size: str = "1K"
    image_openai_frame_aspect_ratio: str = "9:16"
    image_openai_frame_size: str = "1K"

    # Image Generation - Vertex AI
    image_vertex_ai_project: str | None = None
    image_vertex_ai_location: str = "us-central1"
    image_vertex_ai_model: str = "gemini-3-pro-image-preview"
    image_vertex_ai_reference_aspect_ratio: str = "1:1"
    image_vertex_ai_reference_size: str = "1K"
    image_vertex_ai_frame_aspect_ratio: str = "9:16"
    image_vertex_ai_frame_size: str = "1K"

    # Image Generation - Gemini API
    image_gemini_api_key_set: bool = False
    image_gemini_api_key: str | None = None
    image_gemini_model: str = "gemini-3-pro-image-preview"
    image_gemini_reference_aspect_ratio: str = "1:1"
    image_gemini_reference_size: str = "1K"
    image_gemini_frame_aspect_ratio: str = "9:16"
    image_gemini_frame_size: str = "1K"

    # Image Generation - Wan2GP
    image_wan2gp_preset: str = "qwen_image_2512"
    image_wan2gp_preset_i2i: str = "qwen_image_edit_plus2"
    image_wan2gp_reference_resolution: str = "1024x1024"
    image_wan2gp_frame_resolution: str = "1088x1920"
    image_wan2gp_inference_steps: int = 0
    image_wan2gp_guidance_scale: float = 0.0
    image_wan2gp_seed: int = -1
    image_wan2gp_negative_prompt: str = ""
    image_wan2gp_enabled_models: list[str] | None = None
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
    google_credentials_path: str | None = None

    # Video Generation - Vertex AI
    video_vertex_ai_project: str | None = None
    video_vertex_ai_location: str = "us-central1"
    video_vertex_ai_model: str = "veo-3.1-fast-preview"
    video_vertex_ai_aspect_ratio: str = "9:16"
    video_vertex_ai_resolution: str = "1080"
    video_vertex_ai_negative_prompt: str = ""
    video_vertex_ai_enabled_models: list[str] | None = None

    # Video Generation - Seedance
    video_seedance_api_key_set: bool = False
    video_seedance_api_key: str | None = None
    video_seedance_base_url: str = "https://kwjm.com"
    video_seedance_model: str = "seedance-2-0"
    video_seedance_aspect_ratio: str = "adaptive"
    video_seedance_resolution: str = "720p"
    video_seedance_watermark: bool = False
    video_seedance_enabled_models: list[str] | None = None

    # Video Generation - Wan2GP
    video_wan2gp_t2v_preset: str = "t2v_1.3B"
    video_wan2gp_i2v_preset: str = "i2v_720p"
    video_wan2gp_resolution: str = "720x1280"
    video_wan2gp_negative_prompt: str = ""
    video_wan2gp_enabled_models: list[str] | None = None
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
    default_search_provider: str = "tavily"
    default_audio_provider: str = "edge_tts"
    default_speech_recognition_provider: str = "faster_whisper"
    default_image_provider: str = ""
    default_video_provider: str = "volcengine_seedance"
    default_speech_recognition_model: str = ""
    default_general_llm_model: str = ""
    default_fast_llm_model: str = ""
    default_multimodal_llm_model: str = ""
    default_image_t2i_model: str = ""
    default_image_i2i_model: str = ""
    default_video_t2v_model: str = ""
    default_video_i2v_model: str = ""


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Search Provider
    search_tavily_api_key: str | None = Field(default=None)
    jina_reader_api_key: str | None = Field(default=None)
    jina_reader_ignore_images: bool | None = None
    web_url_parser_provider: str | None = Field(default=None)
    crawl4ai_ignore_images: bool | None = None
    crawl4ai_ignore_links: bool | None = None

    # Text Generation (LLM)
    text_openai_api_key: str | None = Field(default=None)
    text_openai_base_url: str | None = None
    text_openai_model: str | None = None
    llm_providers: list[LLMProviderConfig] | None = None
    image_providers: list[ImageProviderConfig] | None = None

    # Audio Provider - Edge TTS
    edge_tts_voice: str | None = None
    edge_tts_rate: str | None = None
    volcengine_tts_app_key: str | None = None
    volcengine_tts_access_key: str | None = None
    volcengine_tts_resource_id: str | None = None
    volcengine_tts_model_name: str | None = None
    audio_volcengine_tts_voice_type: str | None = None
    audio_volcengine_tts_speed_ratio: float | None = None
    audio_volcengine_tts_volume_ratio: float | None = None
    audio_volcengine_tts_pitch_ratio: float | None = None
    audio_volcengine_tts_encoding: str | None = None
    audio_wan2gp_preset: str | None = None
    audio_wan2gp_model_mode: str | None = None
    audio_wan2gp_alt_prompt: str | None = None
    audio_wan2gp_duration_seconds: int | None = None
    audio_wan2gp_temperature: float | None = None
    audio_wan2gp_top_k: int | None = None
    audio_wan2gp_seed: int | None = None
    audio_wan2gp_audio_guide: str | None = None
    audio_wan2gp_speed: float | None = None
    audio_wan2gp_split_strategy: str | None = None
    kling_access_key: str | None = None
    kling_secret_key: str | None = None
    kling_base_url: str | None = None
    audio_kling_voice_id: str | None = None
    audio_kling_voice_language: str | None = None
    audio_kling_voice_speed: float | None = None
    vidu_api_key: str | None = None
    vidu_base_url: str | None = None
    audio_vidu_voice_id: str | None = None
    audio_vidu_speed: float | None = None
    audio_vidu_volume: float | None = None
    audio_vidu_pitch: float | None = None
    audio_vidu_emotion: str | None = None
    minimax_api_key: str | None = None
    minimax_base_url: str | None = None
    audio_minimax_model: str | None = None
    audio_minimax_voice_id: str | None = None
    audio_minimax_speed: float | None = None
    xiaomi_mimo_api_key: str | None = None
    xiaomi_mimo_base_url: str | None = None
    audio_xiaomi_mimo_voice: str | None = None
    audio_xiaomi_mimo_style_preset: str | None = None
    audio_xiaomi_mimo_speed: float | None = None
    audio_xiaomi_mimo_format: str | None = None

    # Local model shared config
    deployment_profile: str | None = None
    wan2gp_path: str | None = None
    local_model_python_path: str | None = None
    wan2gp_fit_canvas: int | None = None
    xhs_downloader_path: str | None = None
    tiktok_downloader_path: str | None = None
    ks_downloader_path: str | None = None
    speech_volcengine_app_key: str | None = None
    speech_volcengine_access_key: str | None = None
    speech_volcengine_resource_id: str | None = None
    speech_volcengine_language: str | None = None
    faster_whisper_model: str | None = None
    dialogue_script_max_roles: int | None = None
    card_scheduler_max_concurrent_tasks: int | None = None
    card_scheduler_url_parse_concurrency: int | None = None
    card_scheduler_video_download_concurrency: int | None = None
    card_scheduler_audio_transcribe_concurrency: int | None = None
    card_scheduler_audio_prepare_concurrency: int | None = None
    card_scheduler_audio_proofread_concurrency: int | None = None
    card_scheduler_audio_name_concurrency: int | None = None
    card_scheduler_text_proofread_concurrency: int | None = None
    card_scheduler_text_name_concurrency: int | None = None
    card_scheduler_reference_describe_concurrency: int | None = None
    card_scheduler_reference_name_concurrency: int | None = None

    # Image Generation - OpenAI Chat Compatible
    image_openai_api_key: str | None = None
    image_openai_base_url: str | None = None
    image_openai_model: str | None = None
    image_openai_reference_aspect_ratio: str | None = None
    image_openai_reference_size: str | None = None
    image_openai_frame_aspect_ratio: str | None = None
    image_openai_frame_size: str | None = None

    # Image Generation - Vertex AI
    image_vertex_ai_project: str | None = None
    image_vertex_ai_location: str | None = None
    image_vertex_ai_model: str | None = None
    image_vertex_ai_reference_aspect_ratio: str | None = None
    image_vertex_ai_reference_size: str | None = None
    image_vertex_ai_frame_aspect_ratio: str | None = None
    image_vertex_ai_frame_size: str | None = None

    # Image Generation - Gemini API
    image_gemini_api_key: str | None = None
    image_gemini_model: str | None = None
    image_gemini_reference_aspect_ratio: str | None = None
    image_gemini_reference_size: str | None = None
    image_gemini_frame_aspect_ratio: str | None = None
    image_gemini_frame_size: str | None = None

    # Image Generation - Wan2GP
    image_wan2gp_preset: str | None = None
    image_wan2gp_preset_i2i: str | None = None
    image_wan2gp_reference_resolution: str | None = None
    image_wan2gp_frame_resolution: str | None = None
    image_wan2gp_inference_steps: int | None = None
    image_wan2gp_guidance_scale: float | None = None
    image_wan2gp_seed: int | None = None
    image_wan2gp_negative_prompt: str | None = None
    image_wan2gp_enabled_models: list[str] | None = None
    image_kling_t2i_model: str | None = None
    image_kling_i2i_model: str | None = None
    image_kling_reference_aspect_ratio: str | None = None
    image_kling_reference_size: str | None = None
    image_kling_frame_aspect_ratio: str | None = None
    image_kling_frame_size: str | None = None
    image_kling_enabled_models: list[str] | None = None
    image_vidu_t2i_model: str | None = None
    image_vidu_i2i_model: str | None = None
    image_vidu_reference_aspect_ratio: str | None = None
    image_vidu_reference_size: str | None = None
    image_vidu_frame_aspect_ratio: str | None = None
    image_vidu_frame_size: str | None = None
    image_vidu_enabled_models: list[str] | None = None
    image_minimax_model: str | None = None
    image_minimax_reference_aspect_ratio: str | None = None
    image_minimax_reference_size: str | None = None
    image_minimax_frame_aspect_ratio: str | None = None
    image_minimax_frame_size: str | None = None
    image_minimax_enabled_models: list[str] | None = None

    # Google Cloud 共享凭证
    google_credentials_path: str | None = None

    # Video Generation - Vertex AI
    video_vertex_ai_project: str | None = None
    video_vertex_ai_location: str | None = None
    video_vertex_ai_model: str | None = None
    video_vertex_ai_aspect_ratio: str | None = None
    video_vertex_ai_resolution: str | None = None
    video_vertex_ai_negative_prompt: str | None = None
    video_vertex_ai_enabled_models: list[str] | None = None

    # Video Generation - Seedance
    video_seedance_api_key: str | None = None
    video_seedance_base_url: str | None = None
    video_seedance_model: str | None = None
    video_seedance_aspect_ratio: str | None = None
    video_seedance_resolution: str | None = None
    video_seedance_watermark: bool | None = None
    video_seedance_enabled_models: list[str] | None = None

    # Video Generation - Wan2GP
    video_wan2gp_t2v_preset: str | None = None
    video_wan2gp_i2v_preset: str | None = None
    video_wan2gp_resolution: str | None = None
    video_wan2gp_negative_prompt: str | None = None
    video_wan2gp_enabled_models: list[str] | None = None
    video_kling_model: str | None = None
    video_kling_aspect_ratio: str | None = None
    video_kling_mode: str | None = None
    video_vidu_model: str | None = None
    video_vidu_aspect_ratio: str | None = None
    video_vidu_resolution: str | None = None
    video_vidu_enabled_models: list[str] | None = None
    video_minimax_model: str | None = None
    video_minimax_aspect_ratio: str | None = None
    video_minimax_resolution: str | None = None
    video_minimax_enabled_models: list[str] | None = None

    # Default Providers
    default_llm_provider: str | None = None
    default_search_provider: str | None = None
    default_audio_provider: str | None = None
    default_speech_recognition_provider: str | None = None
    default_image_provider: str | None = None
    default_video_provider: str | None = None
    default_speech_recognition_model: str | None = None
    default_general_llm_model: str | None = None
    default_fast_llm_model: str | None = None
    default_multimodal_llm_model: str | None = None
    default_image_t2i_model: str | None = None
    default_image_i2i_model: str | None = None
    default_video_t2v_model: str | None = None
    default_video_i2v_model: str | None = None
