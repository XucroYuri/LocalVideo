export type LLMProviderType = 'openai_chat' | 'openai_responses' | 'anthropic_messages' | 'gemini'
export type ImageProviderType = 'openai_chat' | 'gemini_api' | 'volcengine_seedream' | 'kling'
export type RuntimeValidationStatus = 'not_ready' | 'pending' | 'failed' | 'ready'

export interface LLMProviderConfig {
  id: string
  name: string
  is_builtin: boolean
  provider_type: LLMProviderType
  base_url: string
  api_key: string
  catalog_models: string[]
  enabled_models: string[]
  default_model: string
  supports_vision: boolean
}

export interface ImageProviderConfig {
  id: string
  name: string
  is_builtin: boolean
  provider_type: ImageProviderType
  base_url: string
  api_key: string
  catalog_models: string[]
  enabled_models: string[]
  default_model: string
  reference_aspect_ratio: string
  reference_size: string
  frame_aspect_ratio: string
  frame_size: string
}

export interface Settings {
  // Search Provider
  search_tavily_api_key_set: boolean
  search_tavily_api_key?: string
  jina_reader_api_key?: string
  jina_reader_ignore_images: boolean
  web_url_parser_provider: 'jina_reader' | 'crawl4ai' | string
  crawl4ai_ignore_images: boolean
  crawl4ai_ignore_links: boolean
  is_containerized_runtime: boolean

  // Text Generation (LLM) - OpenAI
  text_openai_api_key_set: boolean
  text_openai_api_key?: string
  text_openai_base_url?: string
  text_openai_model: string
  llm_providers: LLMProviderConfig[]
  image_providers: ImageProviderConfig[]

  // Image Provider - OpenAI Chat Compatible
  image_openai_api_key_set: boolean
  image_openai_api_key?: string
  image_openai_base_url?: string
  image_openai_model: string
  image_openai_reference_aspect_ratio: string
  image_openai_reference_size: string
  image_openai_frame_aspect_ratio: string
  image_openai_frame_size: string

  // Image Provider - Vertex AI
  image_vertex_ai_project?: string
  image_vertex_ai_location: string
  image_vertex_ai_model: string
  image_vertex_ai_reference_aspect_ratio: string
  image_vertex_ai_reference_size: string
  image_vertex_ai_frame_aspect_ratio: string
  image_vertex_ai_frame_size: string

  // Image Provider - Gemini API
  image_gemini_api_key_set: boolean
  image_gemini_api_key?: string
  image_gemini_model: string
  image_gemini_reference_aspect_ratio: string
  image_gemini_reference_size: string
  image_gemini_frame_aspect_ratio: string
  image_gemini_frame_size: string

  // Image Provider - Wan2GP
  image_wan2gp_preset: string
  image_wan2gp_preset_i2i: string
  image_wan2gp_reference_resolution: string
  image_wan2gp_frame_resolution: string
  image_wan2gp_inference_steps: number
  image_wan2gp_guidance_scale: number
  image_wan2gp_seed: number
  image_wan2gp_negative_prompt: string
  image_wan2gp_enabled_models?: string[] | null
  image_kling_t2i_model: string
  image_kling_i2i_model: string
  image_kling_reference_aspect_ratio: string
  image_kling_reference_size: string
  image_kling_frame_aspect_ratio: string
  image_kling_frame_size: string
  image_kling_enabled_models?: string[] | null
  image_vidu_t2i_model: string
  image_vidu_i2i_model: string
  image_vidu_reference_aspect_ratio: string
  image_vidu_reference_size: string
  image_vidu_frame_aspect_ratio: string
  image_vidu_frame_size: string
  image_vidu_enabled_models?: string[] | null
  image_minimax_model: string
  image_minimax_reference_aspect_ratio: string
  image_minimax_reference_size: string
  image_minimax_frame_aspect_ratio: string
  image_minimax_frame_size: string
  image_minimax_enabled_models?: string[] | null

  // Google Cloud 共享凭证
  google_credentials_path?: string

  // Video Provider - Seedance
  video_seedance_api_key_set: boolean
  video_seedance_api_key?: string
  video_seedance_base_url: string
  video_seedance_model: string
  video_seedance_aspect_ratio: string
  video_seedance_resolution: string
  video_seedance_watermark: boolean
  video_seedance_enabled_models?: string[] | null

  // Video Provider - Wan2GP
  video_wan2gp_t2v_preset: string
  video_wan2gp_i2v_preset: string
  video_wan2gp_resolution: string
  video_wan2gp_negative_prompt: string
  video_wan2gp_enabled_models?: string[] | null

  // Audio Provider - Edge TTS
  edge_tts_voice: string
  edge_tts_rate: string
  volcengine_tts_app_key_set: boolean
  volcengine_tts_app_key?: string
  volcengine_tts_access_key_set: boolean
  volcengine_tts_access_key?: string
  volcengine_tts_resource_id: string
  volcengine_tts_model_name: string
  audio_volcengine_tts_voice_type: string
  audio_volcengine_tts_speed_ratio: number
  audio_volcengine_tts_volume_ratio: number
  audio_volcengine_tts_pitch_ratio: number
  audio_volcengine_tts_encoding: 'mp3' | 'wav' | 'pcm' | 'ogg_opus' | string
  audio_wan2gp_preset: string
  audio_wan2gp_model_mode: string
  audio_wan2gp_alt_prompt: string
  audio_wan2gp_duration_seconds: number
  audio_wan2gp_temperature: number
  audio_wan2gp_top_k: number
  audio_wan2gp_seed: number
  audio_wan2gp_audio_guide: string
  audio_wan2gp_speed: number
  audio_wan2gp_split_strategy: 'sentence_punct' | 'anchor_tail'
  kling_access_key_set: boolean
  kling_access_key?: string
  kling_secret_key_set: boolean
  kling_secret_key?: string
  kling_base_url: string
  audio_kling_voice_id: string
  audio_kling_voice_language: string
  audio_kling_voice_speed: number
  vidu_api_key_set: boolean
  vidu_api_key?: string
  vidu_base_url: string
  audio_vidu_voice_id: string
  audio_vidu_speed: number
  audio_vidu_volume: number
  audio_vidu_pitch: number
  audio_vidu_emotion: string
  minimax_api_key_set: boolean
  minimax_api_key?: string
  minimax_base_url: string
  audio_minimax_model: string
  audio_minimax_voice_id: string
  audio_minimax_speed: number
  xiaomi_mimo_api_key_set: boolean
  xiaomi_mimo_api_key?: string
  xiaomi_mimo_base_url: string
  audio_xiaomi_mimo_voice: string
  audio_xiaomi_mimo_style_preset: string
  audio_xiaomi_mimo_speed: number
  audio_xiaomi_mimo_format: 'wav' | 'mp3' | string

  // Local model shared config
  deployment_profile: 'cpu' | 'gpu' | string
  wan2gp_path?: string
  local_model_python_path?: string
  wan2gp_fit_canvas: number
  xhs_downloader_path?: string
  tiktok_downloader_path?: string
  ks_downloader_path?: string
  speech_volcengine_app_key_set: boolean
  speech_volcengine_app_key?: string
  speech_volcengine_access_key_set: boolean
  speech_volcengine_access_key?: string
  speech_volcengine_resource_id: string
  speech_volcengine_language: string | null
  faster_whisper_model: string
  dialogue_script_max_roles: number
  wan2gp_validation_status: RuntimeValidationStatus
  xhs_downloader_validation_status: RuntimeValidationStatus
  tiktok_downloader_validation_status: RuntimeValidationStatus
  ks_downloader_validation_status: RuntimeValidationStatus
  faster_whisper_validation_status: RuntimeValidationStatus
  speech_volcengine_validation_status: RuntimeValidationStatus
  crawl4ai_validation_status: RuntimeValidationStatus
  wan2gp_available: boolean

  // Default Providers
  default_llm_provider: string
  default_search_provider: string
  default_audio_provider: string
  default_speech_recognition_provider: string
  default_image_provider: string
  default_video_provider: string
  default_speech_recognition_model: string
  default_general_llm_model: string
  default_fast_llm_model: string
  default_multimodal_llm_model: string
  default_image_t2i_model: string
  default_image_i2i_model: string
  default_video_t2v_model: string
  default_video_i2v_model: string
}

export interface SettingsUpdate {
  // Search Provider
  search_tavily_api_key?: string
  jina_reader_api_key?: string
  jina_reader_ignore_images?: boolean
  web_url_parser_provider?: 'jina_reader' | 'crawl4ai' | string
  crawl4ai_ignore_images?: boolean
  crawl4ai_ignore_links?: boolean

  // Text Generation (LLM) - OpenAI
  text_openai_api_key?: string
  text_openai_base_url?: string
  text_openai_model?: string
  llm_providers?: LLMProviderConfig[]
  image_providers?: ImageProviderConfig[]

  // Image Provider - OpenAI Chat Compatible
  image_openai_api_key?: string
  image_openai_base_url?: string
  image_openai_model?: string
  image_openai_reference_aspect_ratio?: string
  image_openai_reference_size?: string
  image_openai_frame_aspect_ratio?: string
  image_openai_frame_size?: string

  // Image Provider - Vertex AI
  image_vertex_ai_project?: string
  image_vertex_ai_location?: string
  image_vertex_ai_model?: string
  image_vertex_ai_reference_aspect_ratio?: string
  image_vertex_ai_reference_size?: string
  image_vertex_ai_frame_aspect_ratio?: string
  image_vertex_ai_frame_size?: string

  // Image Provider - Gemini API
  image_gemini_api_key?: string
  image_gemini_model?: string
  image_gemini_reference_aspect_ratio?: string
  image_gemini_reference_size?: string
  image_gemini_frame_aspect_ratio?: string
  image_gemini_frame_size?: string

  // Image Provider - Wan2GP
  image_wan2gp_preset?: string
  image_wan2gp_preset_i2i?: string
  image_wan2gp_reference_resolution?: string
  image_wan2gp_frame_resolution?: string
  image_wan2gp_inference_steps?: number
  image_wan2gp_guidance_scale?: number
  image_wan2gp_seed?: number
  image_wan2gp_negative_prompt?: string
  image_wan2gp_enabled_models?: string[] | null
  image_kling_t2i_model?: string
  image_kling_i2i_model?: string
  image_kling_reference_aspect_ratio?: string
  image_kling_reference_size?: string
  image_kling_frame_aspect_ratio?: string
  image_kling_frame_size?: string
  image_kling_enabled_models?: string[] | null
  image_vidu_t2i_model?: string
  image_vidu_i2i_model?: string
  image_vidu_reference_aspect_ratio?: string
  image_vidu_reference_size?: string
  image_vidu_frame_aspect_ratio?: string
  image_vidu_frame_size?: string
  image_vidu_enabled_models?: string[] | null
  image_minimax_model?: string
  image_minimax_reference_aspect_ratio?: string
  image_minimax_reference_size?: string
  image_minimax_frame_aspect_ratio?: string
  image_minimax_frame_size?: string
  image_minimax_enabled_models?: string[] | null

  // Google Cloud 共享凭证
  google_credentials_path?: string

  // Video Provider - Seedance
  video_seedance_api_key?: string
  video_seedance_base_url?: string
  video_seedance_model?: string
  video_seedance_aspect_ratio?: string
  video_seedance_resolution?: string
  video_seedance_watermark?: boolean
  video_seedance_enabled_models?: string[] | null

  // Video Provider - Wan2GP
  video_wan2gp_t2v_preset?: string
  video_wan2gp_i2v_preset?: string
  video_wan2gp_resolution?: string
  video_wan2gp_negative_prompt?: string
  video_wan2gp_enabled_models?: string[] | null

  // Audio Provider - Edge TTS
  edge_tts_voice?: string
  edge_tts_rate?: string
  volcengine_tts_app_key?: string
  volcengine_tts_access_key?: string
  volcengine_tts_resource_id?: string
  volcengine_tts_model_name?: string
  audio_volcengine_tts_voice_type?: string
  audio_volcengine_tts_speed_ratio?: number
  audio_volcengine_tts_volume_ratio?: number
  audio_volcengine_tts_pitch_ratio?: number
  audio_volcengine_tts_encoding?: 'mp3' | 'wav' | 'pcm' | 'ogg_opus' | string
  audio_wan2gp_preset?: string
  audio_wan2gp_model_mode?: string
  audio_wan2gp_alt_prompt?: string
  audio_wan2gp_duration_seconds?: number
  audio_wan2gp_temperature?: number
  audio_wan2gp_top_k?: number
  audio_wan2gp_seed?: number
  audio_wan2gp_audio_guide?: string
  audio_wan2gp_speed?: number
  audio_wan2gp_split_strategy?: 'sentence_punct' | 'anchor_tail'
  kling_access_key?: string
  kling_secret_key?: string
  kling_base_url?: string
  audio_kling_voice_id?: string
  audio_kling_voice_language?: string
  audio_kling_voice_speed?: number
  vidu_api_key?: string
  vidu_base_url?: string
  audio_vidu_voice_id?: string
  audio_vidu_speed?: number
  audio_vidu_volume?: number
  audio_vidu_pitch?: number
  audio_vidu_emotion?: string
  minimax_api_key?: string
  minimax_base_url?: string
  audio_minimax_model?: string
  audio_minimax_voice_id?: string
  audio_minimax_speed?: number
  xiaomi_mimo_api_key?: string
  xiaomi_mimo_base_url?: string
  audio_xiaomi_mimo_voice?: string
  audio_xiaomi_mimo_style_preset?: string
  audio_xiaomi_mimo_speed?: number
  audio_xiaomi_mimo_format?: 'wav' | 'mp3' | string

  // Local model shared config
  deployment_profile?: 'cpu' | 'gpu' | string
  wan2gp_path?: string
  local_model_python_path?: string
  wan2gp_fit_canvas?: number
  xhs_downloader_path?: string
  tiktok_downloader_path?: string
  ks_downloader_path?: string
  speech_volcengine_app_key?: string
  speech_volcengine_access_key?: string
  speech_volcengine_resource_id?: string
  speech_volcengine_language?: string
  faster_whisper_model?: string
  dialogue_script_max_roles?: number

  // Default Providers
  default_llm_provider?: string
  default_search_provider?: string
  default_audio_provider?: string
  default_speech_recognition_provider?: string
  default_image_provider?: string
  default_video_provider?: string
  default_speech_recognition_model?: string
  default_general_llm_model?: string
  default_fast_llm_model?: string
  default_multimodal_llm_model?: string
  default_image_t2i_model?: string
  default_image_i2i_model?: string
  default_video_t2v_model?: string
  default_video_i2v_model?: string
}

export interface VoiceInfo {
  id: string
  name: string
  locale: string
}

export interface AvailableProviders {
  llm: string[]
  audio: string[]
  speech: string[]
  image: string[]
  video: string[]
}

export interface Wan2gpImagePreset {
  id: string
  display_name: string
  description: string
  preset_type: 't2i' | 'i2i' | string
  supported_modes: Array<'t2i' | 'i2i' | string>
  supports_reference: boolean
  supports_chinese: boolean
  prompt_language_preference: 'zh' | 'balanced' | 'en' | string
  default_resolution: string
  supported_resolutions: string[]
  inference_steps: number
}

export interface Wan2gpVideoPreset {
  id: string
  mode: 't2v' | 'i2v' | string
  display_name: string
  description: string
  model_type: string
  supports_chinese: boolean
  prompt_language_preference: 'zh' | 'balanced' | 'en' | string
  supports_last_frame: boolean
  default_resolution: string
  supported_resolutions: string[]
  frames_per_second: number
  inference_steps: number
  guidance_scale: number
  flow_shift: number
  max_frames: number
  vram_min: number
  sliding_window_size?: number | null
  sliding_window_size_min?: number | null
  sliding_window_size_max?: number | null
  sliding_window_size_step?: number | null
}

export interface Wan2gpAudioModeOption {
  id: string
  label: string
}

export interface Wan2gpAudioPreset {
  id: string
  display_name: string
  description: string
  model_type: string
  supports_reference_audio: boolean
  model_mode_label: string
  model_mode_choices: Wan2gpAudioModeOption[]
  default_model_mode: string
  default_alt_prompt: string
  default_duration_seconds: number
  default_temperature: number
  default_top_k: number
}

export interface JinaReaderUsage {
  available: boolean
  remaining_tokens?: number | null
  rate_limit_rpm?: number | null
  raw_preview?: string | null
}

export interface TavilyUsage {
  available: boolean
  remaining_credits?: number
  used_credits?: number
  total_credits?: number
  source?: 'account' | 'key' | string
  account_used_credits?: number
  account_total_credits?: number
  account_remaining_credits?: number
  key_used_credits?: number
  key_total_credits?: number
  key_remaining_credits?: number
  reset_at?: string
  raw?: Record<string, unknown>
}

export interface VertexVideoModel {
  id: string
  label: string
  supports_reference_image: boolean
  supports_combined_reference: boolean
  supports_last_frame: boolean
  reference_restrictions: string[]
}

export interface SeedanceModelPreset {
  id: string
  label: string
  description: string
  supports_t2v: boolean
  supports_i2v: boolean
  supports_last_frame: boolean
  supports_reference_image: boolean
  reference_restrictions: string[]
}

export interface ProviderVideoModelPreset {
  id: string
  label: string
  description: string
  supported_durations_seconds: number[]
  supported_aspect_ratios: string[]
  supported_resolutions: string[]
  default_aspect_ratio: string
  default_resolution: string
  supports_t2v: boolean
  supports_i2v: boolean
  supports_last_frame: boolean
  supports_reference_image: boolean
  supports_combined_reference: boolean
  max_reference_images: number
  reference_restrictions: string[]
}

export interface Capabilities {
  seedance_model_presets: SeedanceModelPreset[]
  seedance_aspect_ratios: string[]
  seedance_resolutions: string[]
}
