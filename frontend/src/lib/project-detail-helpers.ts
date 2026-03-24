import type { Settings } from '@/types/settings'
import type { StageConfig } from '@/types/stage-panel'
import type { BackendStageType, Stage } from '@/types/stage'

// --- Settings-derived defaults ---

export type DefaultImageModelMode = 't2i' | 'i2i'
export type DefaultVideoModelMode = 't2v' | 'i2v'
const KLING_IMAGE_ASPECT_RATIO_OPTIONS = ['16:9', '9:16', '1:1', '4:3', '3:4', '3:2', '2:3', '21:9']
const KLING_IMAGE_SIZE_OPTIONS_BY_MODEL: Record<string, string[]> = {
  'kling-v3': ['1K', '2K', '4K'],
  'kling-v3-omni': ['1K', '2K'],
}
const VIDU_IMAGE_ASPECT_RATIO_OPTIONS = ['16:9', '9:16', '1:1', '3:4', '4:3', '21:9', '2:3', '3:2']
const VIDU_IMAGE_SIZE_OPTIONS = ['1080p', '2K', '4K']
const DEFAULT_SEEDANCE_MODEL = 'seedance-2-0'
const DEFAULT_SEEDANCE_ASPECT_RATIO = 'adaptive'
const DEFAULT_SEEDANCE_RESOLUTION = '720p'
const DEFAULT_WAN2GP_VIDEO_RESOLUTION = '720x1280'

function getKlingImageSizeOptions(model: string | undefined): string[] {
  return KLING_IMAGE_SIZE_OPTIONS_BY_MODEL[String(model || '').trim().toLowerCase()] || ['1K', '2K', '4K']
}

function parseProviderModelBinding(rawValue: unknown): { providerId: string; modelId: string } | null {
  const text = String(rawValue || '').trim()
  if (!text) return null
  const separatorIndex = text.indexOf('::')
  if (separatorIndex <= 0) return null
  const providerId = text.slice(0, separatorIndex).trim()
  const modelId = text.slice(separatorIndex + 2).trim()
  if (!providerId || !modelId) return null
  return { providerId, modelId }
}

export function getDefaultImageModelBinding(
  settings: Settings,
  mode: DefaultImageModelMode = 't2i'
): { providerId: string; modelId: string } | null {
  const rawBinding = mode === 'i2i'
    ? settings.default_image_i2i_model
    : settings.default_image_t2i_model
  return parseProviderModelBinding(rawBinding)
}

function getDefaultImageModelRaw(
  settings: Settings,
  mode: DefaultImageModelMode = 't2i'
): string {
  return String(
    mode === 'i2i'
      ? settings.default_image_i2i_model
      : settings.default_image_t2i_model
  ).trim()
}

export function getDefaultVideoModelBinding(
  settings: Settings,
  mode: DefaultVideoModelMode = 't2v'
): { providerId: string; modelId: string } | null {
  const rawBinding = mode === 'i2v'
    ? settings.default_video_i2v_model
    : settings.default_video_t2v_model
  return parseProviderModelBinding(rawBinding)
}

export function getDefaultLlmModel(settings: Settings): string {
  const defaultBinding = String(settings.default_general_llm_model || '').trim()
  const separatorIndex = defaultBinding.indexOf('::')
  if (separatorIndex > 0) {
    const modelId = defaultBinding.slice(separatorIndex + 2).trim()
    if (modelId) return modelId
  }
  if (defaultBinding) return defaultBinding

  const providers = settings.llm_providers || []
  const selected = providers.find((provider) => provider.id === settings.default_llm_provider)
    || providers[0]
  if (!selected) return ''
  if (selected.default_model) return selected.default_model
  if (selected.enabled_models.length > 0) return selected.enabled_models[0]
  if (selected.catalog_models.length > 0) return selected.catalog_models[0]
  return ''
}

export function getImageProviderConfig(providerId: string | undefined, settings: Settings) {
  const normalizedId = providerId === 'openai' ? 'builtin_openai_image' : providerId
  return (settings.image_providers || []).find((provider) => provider.id === normalizedId)
}

export function getReferenceImageAspectRatio(provider: string | undefined, settings: Settings): string {
  if (provider === 'kling') {
    const ratio = String(settings.image_kling_reference_aspect_ratio || '').trim()
    if (KLING_IMAGE_ASPECT_RATIO_OPTIONS.includes(ratio)) return ratio
    return '1:1'
  }
  if (provider === 'vidu') {
    const ratio = String(settings.image_vidu_reference_aspect_ratio || '').trim()
    if (VIDU_IMAGE_ASPECT_RATIO_OPTIONS.includes(ratio)) return ratio
    return '1:1'
  }
  return getImageProviderConfig(provider, settings)?.reference_aspect_ratio || '1:1'
}

export function getImageModel(
  provider: string | undefined,
  settings: Settings,
  mode: DefaultImageModelMode = 't2i'
): string {
  const binding = getDefaultImageModelBinding(settings, mode)
  if (binding && (!provider || binding.providerId === provider)) {
    return binding.modelId
  }
  if (provider === 'kling') {
    return mode === 'i2i'
      ? (settings.image_kling_i2i_model || 'kling-v3')
      : (settings.image_kling_t2i_model || 'kling-v3')
  }
  if (provider === 'vidu') {
    return mode === 'i2i'
      ? (settings.image_vidu_i2i_model || 'viduq2')
      : (settings.image_vidu_t2i_model || 'viduq2')
  }
  const defaultRaw = getDefaultImageModelRaw(settings, mode)
  if (defaultRaw && !binding) {
    return defaultRaw
  }

  const selected = getImageProviderConfig(provider, settings)
  if (!selected) return 'gemini-3-pro-image-preview'
  if (selected.default_model) return selected.default_model
  if (selected.enabled_models.length > 0) return selected.enabled_models[0]
  if (selected.catalog_models.length > 0) return selected.catalog_models[0]
  return 'gemini-3-pro-image-preview'
}

export function getReferenceImageSize(provider: string | undefined, settings: Settings): string {
  if (provider === 'kling') {
    const model = settings.image_kling_t2i_model || 'kling-v3'
    const options = getKlingImageSizeOptions(model)
    const size = String(settings.image_kling_reference_size || '').trim().toUpperCase()
    return options.includes(size) ? size : (options[0] || '1K')
  }
  if (provider === 'vidu') {
    const raw = String(settings.image_vidu_reference_size || '').trim()
    const size = raw.toLowerCase() === '1k' ? '1080p' : raw
    return VIDU_IMAGE_SIZE_OPTIONS.includes(size) ? size : '1080p'
  }
  return getImageProviderConfig(provider, settings)?.reference_size || '1K'
}

export function getFrameImageAspectRatio(provider: string | undefined, settings: Settings): string {
  if (provider === 'kling') {
    const ratio = String(settings.image_kling_frame_aspect_ratio || '').trim()
    if (KLING_IMAGE_ASPECT_RATIO_OPTIONS.includes(ratio)) return ratio
    return '9:16'
  }
  if (provider === 'vidu') {
    const ratio = String(settings.image_vidu_frame_aspect_ratio || '').trim()
    if (VIDU_IMAGE_ASPECT_RATIO_OPTIONS.includes(ratio)) return ratio
    return '9:16'
  }
  return getImageProviderConfig(provider, settings)?.frame_aspect_ratio || '9:16'
}

export function getFrameImageSize(provider: string | undefined, settings: Settings): string {
  if (provider === 'kling') {
    const model = settings.image_kling_i2i_model || 'kling-v3'
    const options = getKlingImageSizeOptions(model)
    const size = String(settings.image_kling_frame_size || '').trim().toUpperCase()
    return options.includes(size) ? size : (options[0] || '1K')
  }
  if (provider === 'vidu') {
    const raw = String(settings.image_vidu_frame_size || '').trim()
    const size = raw.toLowerCase() === '1k' ? '1080p' : raw
    return VIDU_IMAGE_SIZE_OPTIONS.includes(size) ? size : '1080p'
  }
  return getImageProviderConfig(provider, settings)?.frame_size || '1K'
}

export function getWan2gpPreset(settings: Settings): string {
  const binding = getDefaultImageModelBinding(settings, 't2i')
  if (binding?.providerId === 'wan2gp' && binding.modelId) {
    return binding.modelId
  }
  return settings.image_wan2gp_preset || 'qwen_image_2512'
}

export function getWan2gpPresetI2i(settings: Settings): string {
  const binding = getDefaultImageModelBinding(settings, 'i2i')
  if (binding?.providerId === 'wan2gp' && binding.modelId) {
    return binding.modelId
  }
  return settings.image_wan2gp_preset_i2i || 'qwen_image_edit_plus2'
}

export function getWan2gpReferenceResolution(settings: Settings): string {
  return settings.image_wan2gp_reference_resolution || '1024x1024'
}

export function getWan2gpFrameResolution(settings: Settings): string {
  return settings.image_wan2gp_frame_resolution || '1088x1920'
}

export function getWan2gpVideoT2vPreset(settings: Settings): string {
  return settings.video_wan2gp_t2v_preset || 't2v_1.3B'
}

export function getWan2gpVideoI2vPreset(settings: Settings): string {
  return settings.video_wan2gp_i2v_preset || 'i2v_720p'
}

export function getWan2gpVideoResolution(settings: Settings): string {
  return settings.video_wan2gp_resolution || DEFAULT_WAN2GP_VIDEO_RESOLUTION
}

function deriveWan2gpVideoAspectRatio(resolution: string | undefined): string {
  const normalized = String(resolution || '').trim().toLowerCase()
  const match = normalized.match(/^(\d+)\s*x\s*(\d+)$/)
  if (!match) return '9:16'

  const width = Number(match[1])
  const height = Number(match[2])
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return '9:16'
  }

  const ratio = width / height
  if (Math.abs(ratio - 1) < 0.03) return '1:1'
  if (Math.abs(ratio - (16 / 9)) < 0.03) return '16:9'
  if (Math.abs(ratio - (9 / 16)) < 0.03) return '9:16'
  if (Math.abs(ratio - (4 / 3)) < 0.03) return '4:3'
  if (Math.abs(ratio - (3 / 4)) < 0.03) return '3:4'
  return ratio >= 1 ? '16:9' : '9:16'
}

export function getVideoModelByProvider(
  provider: string | undefined,
  settings: Settings,
  mode: DefaultVideoModelMode = 't2v'
): string {
  const binding = getDefaultVideoModelBinding(settings, mode)
  if (binding && (!provider || binding.providerId === provider)) {
    return binding.modelId
  }
  if (provider === 'wan2gp') {
    return mode === 'i2v'
      ? getWan2gpVideoI2vPreset(settings)
      : getWan2gpVideoT2vPreset(settings)
  }
  if (provider === 'volcengine_seedance') {
    return settings.video_seedance_model || DEFAULT_SEEDANCE_MODEL
  }
  return settings.video_seedance_model || DEFAULT_SEEDANCE_MODEL
}

export function getVideoAspectRatioByProvider(provider: string | undefined, settings: Settings): string {
  if (provider === 'wan2gp') {
    return deriveWan2gpVideoAspectRatio(getWan2gpVideoResolution(settings))
  }
  if (provider === 'volcengine_seedance') {
    return settings.video_seedance_aspect_ratio || DEFAULT_SEEDANCE_ASPECT_RATIO
  }
  return settings.video_seedance_aspect_ratio || DEFAULT_SEEDANCE_ASPECT_RATIO
}

export function getVideoResolutionByProvider(provider: string | undefined, settings: Settings): string {
  if (provider === 'wan2gp') {
    return getWan2gpVideoResolution(settings)
  }
  if (provider === 'volcengine_seedance') {
    return settings.video_seedance_resolution || DEFAULT_SEEDANCE_RESOLUTION
  }
  return settings.video_seedance_resolution || DEFAULT_SEEDANCE_RESOLUTION
}

export function getWan2gpAudioPreset(settings: Settings): string {
  return settings.audio_wan2gp_preset || 'qwen3_tts_base'
}

export function getWan2gpAudioAltPrompt(settings: Settings): string {
  return settings.audio_wan2gp_alt_prompt || ''
}

export function getWan2gpAudioTemperature(settings: Settings): number {
  return settings.audio_wan2gp_temperature || 0.9
}

export function getWan2gpAudioTopK(settings: Settings): number {
  return settings.audio_wan2gp_top_k || 50
}

export function getWan2gpAudioSeed(settings: Settings): number {
  return settings.audio_wan2gp_seed ?? -1
}

export function getWan2gpAudioGuide(settings: Settings): string {
  return settings.audio_wan2gp_audio_guide || ''
}

export function getWan2gpAudioSpeed(settings: Settings): number {
  return settings.audio_wan2gp_speed || 1.0
}

// --- ReferenceVoiceFields type (used by stageData merging) ---

export type ReferenceVoiceProvider =
  | 'edge_tts'
  | 'wan2gp'
  | 'volcengine_tts'
  | 'kling_tts'
  | 'vidu_tts'
  | 'minimax_tts'
  | 'xiaomi_mimo_tts'

export interface ReferenceVoiceFields {
  voice_audio_provider?: ReferenceVoiceProvider
  voice_name?: string
  voice_speed?: number
  voice_wan2gp_preset?: string
  voice_wan2gp_alt_prompt?: string
  voice_wan2gp_audio_guide?: string
  voice_wan2gp_temperature?: number
  voice_wan2gp_top_k?: number
  voice_wan2gp_seed?: number
}

// --- StageConfig persistence ---

export type StageConfigPersistGroup = 'script' | 'shots' | 'compose'

export const STAGE_CONFIG_PERSIST_FIELDS: Record<StageConfigPersistGroup, Array<keyof StageConfig>> = {
  script: [
    'scriptMode',
    'llmProvider',
    'llmModel',
    'textTargetLanguage',
    'textPromptComplexity',
    'style',
    'targetDuration',
    'audioProvider',
    'voice',
    'speed',
    'audioMaxConcurrency',
    'audioWan2gpPreset',
    'audioWan2gpModelMode',
    'audioWan2gpAltPrompt',
    'audioWan2gpDurationSeconds',
    'audioWan2gpTemperature',
    'audioWan2gpTopK',
    'audioWan2gpSeed',
    'audioWan2gpAudioGuide',
    'audioRoleConfigs',
  ],
  shots: [
    'duoPodcastCameraMode',
    'storyboardShotDensity',
    'imageProvider',
    'imageModel',
    'frameImageModel',
    'referenceAspectRatio',
    'referenceImageSize',
    'referenceImageResolution',
    'frameAspectRatio',
    'frameImageSize',
    'frameImageResolution',
    'imageWan2gpPreset',
    'imageWan2gpPresetI2i',
    'imageWan2gpInferenceSteps',
    'imageWan2gpInferenceStepsT2i',
    'imageWan2gpInferenceStepsI2i',
    'imageStyle',
    'videoProvider',
    'videoModel',
    'videoModelI2v',
    'videoAspectRatio',
    'resolution',
    'videoWan2gpT2vPreset',
    'videoWan2gpI2vPreset',
    'videoWan2gpResolution',
    'videoWan2gpInferenceSteps',
    'videoWan2gpSlidingWindowSize',
    'singleTake',
    'useFirstFrameRef',
    'useReferenceImageRef',
    'useReferenceConsistency',
    'maxConcurrency',
  ],
  compose: [
    'videoFitMode',
    'composeCanvasStrategy',
    'composeFixedAspectRatio',
    'composeFixedResolution',
    'includeSubtitle',
    'subtitleFontSize',
    'subtitlePositionPercent',
  ],
}

export const STAGE_CONFIG_AUTOSAVE_DELAY_MS: Record<StageConfigPersistGroup, number> = {
  script: 800,
  shots: 800,
  compose: 800,
}

export const STAGE_PANEL_CONFIG_KEY = 'stage_panel_config'

export function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

export function normalizeProjectConfig(value: unknown): Record<string, unknown> {
  const record = asRecord(value)
  return record ? { ...record } : {}
}

export function pickPersistedGroupConfig(
  config: StageConfig,
  group: StageConfigPersistGroup
): Partial<StageConfig> {
  const payload: Partial<StageConfig> = {}
  for (const field of STAGE_CONFIG_PERSIST_FIELDS[group]) {
    const value = config[field]
    if (value !== undefined) {
      ;(payload as Record<string, unknown>)[field] = value
    }
  }
  return payload
}

export function extractPersistedStageConfig(configValue: unknown): Partial<StageConfig> {
  const projectConfig = asRecord(configValue)
  if (!projectConfig) return {}
  const stagePanelConfig = asRecord(projectConfig[STAGE_PANEL_CONFIG_KEY])
  if (!stagePanelConfig) return {}

  const merged: Partial<StageConfig> = {}
  ;(Object.keys(STAGE_CONFIG_PERSIST_FIELDS) as StageConfigPersistGroup[]).forEach((group) => {
    const groupConfig = asRecord(stagePanelConfig[group])
    if (!groupConfig) return
    for (const field of STAGE_CONFIG_PERSIST_FIELDS[group]) {
      if (field in groupConfig) {
        const value = groupConfig[field as string]
        if (value !== undefined) {
          ;(merged as Record<string, unknown>)[field] = value
        }
      }
    }
  })
  return merged
}

export function areStageConfigValuesEqual(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true
  if (typeof a === 'object' && a !== null && typeof b === 'object' && b !== null) {
    try {
      return JSON.stringify(a) === JSON.stringify(b)
    } catch {
      return false
    }
  }
  return false
}

export function collectChangedPersistGroups(prev: StageConfig, next: StageConfig): StageConfigPersistGroup[] {
  const changed = new Set<StageConfigPersistGroup>()
  ;(Object.keys(STAGE_CONFIG_PERSIST_FIELDS) as StageConfigPersistGroup[]).forEach((group) => {
    for (const field of STAGE_CONFIG_PERSIST_FIELDS[group]) {
      if (!areStageConfigValuesEqual(prev[field], next[field])) {
        changed.add(group)
        break
      }
    }
  })
  return Array.from(changed)
}

// --- Stage status defaults ---

export function buildDefaultStageStatus(): Record<BackendStageType, string> {
  return {
    research: 'pending',
    content: 'pending',
    storyboard: 'pending',
    audio: 'pending',
    subtitle: 'pending',
    burn_subtitle: 'pending',
    finalize: 'pending',
    reference: 'pending',
    first_frame_desc: 'pending',
    frame: 'pending',
    video: 'pending',
    compose: 'pending',
  }
}

// --- StageData types & builder ---

export interface MergedReference {
  id: string
  name: string
  setting?: string
  appearance_description?: string
  can_speak?: boolean
  voice_audio_provider?: ReferenceVoiceProvider
  voice_name?: string
  voice_speed?: number
  voice_wan2gp_preset?: string
  voice_wan2gp_alt_prompt?: string
  voice_wan2gp_audio_guide?: string
  voice_wan2gp_temperature?: number
  voice_wan2gp_top_k?: number
  voice_wan2gp_seed?: number
  image_url?: string
}

export interface StageDataResult {
  content: {
    title?: string
    content?: string
    char_count?: number
    shots_locked?: boolean
    script_mode?: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'
    chat_history?: Array<{
      role?: 'user' | 'assistant'
      text?: string
    }>
    chat_summary?: string
    last_user_message?: string
    roles?: Array<{
      id?: string
      name?: string
      description?: string
      seat_side?: 'left' | 'right' | null
      locked?: boolean
    }>
    dialogue_lines?: Array<{
      id?: string
      speaker_id?: string
      speaker_name?: string
      text?: string
      order?: number
    }>
  } | undefined
  storyboard: {
    shots: Array<{
      shot_id?: string
      shot_index?: number
      order?: number
      voice_content?: string
      speaker_id?: string
      speaker_name?: string
      video_prompt?: string
      first_frame_description?: string
      first_frame_reference_slots?: Array<{ order?: number; id?: string; name?: string }>
      video_reference_slots?: Array<{ order?: number; id?: string; name?: string }>
    }>
    references?: MergedReference[]
  } | undefined
  audio: {
    shots: Array<{
      shot_id?: string
      shot_index?: number
      voice_content?: string
      speaker_id?: string
      speaker_name?: string
      audio_url?: string
      duration?: number
      updated_at?: number
    }>
  } | undefined
  reference: {
    references?: MergedReference[]
    reference_images: Array<{
      id: string
      name: string
      setting?: string
      appearance_description?: string
      can_speak?: boolean
      voice_audio_provider?: ReferenceVoiceProvider
      voice_name?: string
      voice_speed?: number
      voice_wan2gp_preset?: string
      voice_wan2gp_alt_prompt?: string
      voice_wan2gp_audio_guide?: string
      voice_wan2gp_temperature?: number
      voice_wan2gp_top_k?: number
      voice_wan2gp_seed?: number
      file_path?: string
      generated?: boolean
      updated_at?: number
    }>
  }
  frame: {
    shots: Array<{
      shot_id?: string
      shot_index?: number
      first_frame_url?: string
      first_frame_description?: string
      updated_at?: number
    }>
  } | undefined
  video: {
    shots: Array<{
      shot_id?: string
      shot_index?: number
      video_url?: string
      duration?: number
      width?: number
      height?: number
      updated_at?: number
    }>
  } | undefined
  compose: {
    video_url?: string
    poster_url?: string
    duration?: number
    width?: number
    height?: number
  } | undefined
  subtitle: {
    subtitle_url?: string
    duration?: number
    line_count?: number
  } | undefined
  burn_subtitle: {
    video_url?: string
    duration?: number
    width?: number
    height?: number
  } | undefined
  finalize: {
    video_url?: string
    poster_url?: string
    duration?: number
    width?: number
    height?: number
    has_subtitle?: boolean
    source_stage?: string
  } | undefined
}

export function buildStageData(params: {
  contentStage: Stage | null | undefined
  storyboardStage: Stage | null | undefined
  audioStage: Stage | null | undefined
  referenceStage: Stage | null | undefined
  frameStage: Stage | null | undefined
  videoStage: Stage | null | undefined
  composeStage: Stage | null | undefined
  subtitleStage: Stage | null | undefined
  burnSubtitleStage: Stage | null | undefined
  finalizeStage: Stage | null | undefined
  toStorageUrl: (path: string | undefined) => string | undefined
}): StageDataResult {
  const {
    contentStage,
    storyboardStage,
    audioStage,
    referenceStage,
    frameStage,
    videoStage,
    composeStage,
    subtitleStage,
    burnSubtitleStage,
    finalizeStage,
    toStorageUrl,
  } = params

  const audioOutputData = audioStage?.output_data as {
    audio_assets?: Array<{
      shot_index?: number
      shot_id?: string
      voice_content?: string
      speaker_id?: string
      speaker_name?: string
      file_path?: string
      duration?: number
      updated_at?: number
    }>
  } | undefined
  const audioAssets = audioOutputData?.audio_assets
  const videoAssets = (videoStage?.output_data as {
    video_assets?: Array<{
      shot_index?: number
      shot_id?: string
      file_path?: string
      duration?: number
      width?: number
      height?: number
      updated_at?: number
    }>
  } | undefined)?.video_assets
  const composeData = composeStage?.output_data as {
    master_video_path?: string
    duration?: number
    merged_files?: Array<{ file_path?: string }>
    width?: number
    height?: number
    updated_at?: number
  } | undefined
  const subtitleData = subtitleStage?.output_data as {
    subtitle_file_path?: string
    duration?: number
    line_count?: number
    updated_at?: number
  } | undefined
  const burnSubtitleData = burnSubtitleStage?.output_data as {
    burned_video_path?: string
    duration?: number
    width?: number
    height?: number
    updated_at?: number
  } | undefined
  const finalizeData = finalizeStage?.output_data as {
    final_video_path?: string
    duration?: number
    width?: number
    height?: number
    has_subtitle?: boolean
    source_stage?: string
    updated_at?: number
  } | undefined

  // Get storyboard data (voice_content + video_prompt + first_frame_description)
  const storyboardData = storyboardStage?.output_data as {
    shots?: Array<{
      shot_index?: number
      shot_id?: string
      order?: number
      voice_content?: string
      speaker_id?: string
      speaker_name?: string
      video_prompt?: string
      first_frame_description?: string
      first_frame_reference_slots?: Array<{ order?: number; id?: string; name?: string }>
      video_reference_slots?: Array<{ order?: number; id?: string; name?: string }>
    }>
    references?: Array<{
      id: string
      name: string
      setting?: string
      appearance_description?: string
      can_speak?: boolean
    } & ReferenceVoiceFields>
  } | undefined

  const storyboardShots = (
    (Array.isArray(storyboardData?.shots) && storyboardData.shots.length > 0 ? storyboardData.shots : undefined)
    || []
  )
  const mergedShots = storyboardShots
  const normalizedShots = mergedShots.map((shot, index) => {
    const shotId = String(shot?.shot_id || '').trim() || `shot_${index + 1}`
    const order = Number.isFinite(shot?.shot_index)
      ? Number(shot?.shot_index)
      : (Number.isFinite(shot?.order) ? Number(shot?.order) : index)
    return {
      ...shot,
      shot_id: shotId,
      shot_index: order,
      order,
    }
  })

  const referenceData = referenceStage?.output_data as {
    references?: Array<{
      id: string
      name: string
      setting?: string
      appearance_description?: string
      can_speak?: boolean
    } & ReferenceVoiceFields>
    reference_images?: Array<{
      id: string
      name: string
      setting?: string
      appearance_description?: string
      can_speak?: boolean
      voice_audio_provider?: ReferenceVoiceProvider
      voice_name?: string
      voice_speed?: number
      voice_wan2gp_preset?: string
      voice_wan2gp_alt_prompt?: string
      voice_wan2gp_audio_guide?: string
      voice_wan2gp_temperature?: number
      voice_wan2gp_top_k?: number
      voice_wan2gp_seed?: number
      file_path?: string
      generated?: boolean
      updated_at?: number
    }>
  } | undefined
  const frameData = frameStage?.output_data as {
    frame_images?: Array<{
      shot_index?: number
      shot_id?: string
      file_path?: string
      first_frame_description?: string
      updated_at?: number
    }>
  } | undefined

  const references = referenceData?.references || storyboardData?.references || []
  const referenceImages = referenceData?.reference_images || []
  const mergedReferences = references.map((reference) => {
    const img = referenceImages.find((item) => item.id === reference.id)
    // Add cache-busting timestamp to image URL (use 0 as fallback if updated_at not available)
    const baseUrl = img?.file_path ? toStorageUrl(img.file_path) : undefined
    const imageUrl = baseUrl ? `${baseUrl}?t=${img?.updated_at || 0}` : undefined
    const setting = String(reference.setting || '').trim()
      || String(img?.setting || '').trim()
    const appearanceDescription = String(reference.appearance_description || '').trim()
      || String(img?.appearance_description || '').trim()
    const referenceName = String(reference.name || img?.name || '').trim()
    const inferredCanSpeak = !referenceName.includes('场景')
    const canSpeak = typeof reference.can_speak === 'boolean'
      ? reference.can_speak
      : (typeof img?.can_speak === 'boolean' ? img.can_speak : inferredCanSpeak)
    const voiceAudioProvider = canSpeak
      ? (
          (
            reference.voice_audio_provider === 'edge_tts'
            || reference.voice_audio_provider === 'wan2gp'
            || reference.voice_audio_provider === 'volcengine_tts'
            || reference.voice_audio_provider === 'kling_tts'
            || reference.voice_audio_provider === 'vidu_tts'
            || reference.voice_audio_provider === 'minimax_tts'
            || reference.voice_audio_provider === 'xiaomi_mimo_tts'
          )
            ? reference.voice_audio_provider
            : (
                (
                  img?.voice_audio_provider === 'edge_tts'
                  || img?.voice_audio_provider === 'wan2gp'
                  || img?.voice_audio_provider === 'volcengine_tts'
                  || img?.voice_audio_provider === 'kling_tts'
                  || img?.voice_audio_provider === 'vidu_tts'
                  || img?.voice_audio_provider === 'minimax_tts'
                  || img?.voice_audio_provider === 'xiaomi_mimo_tts'
                )
                  ? img.voice_audio_provider
                  : undefined
              )
        )
      : undefined
    const voiceName = canSpeak
      ? (
          String(reference.voice_name || '').trim()
          || String(img?.voice_name || '').trim()
          || undefined
        )
      : undefined
    const firstFiniteNumber = (...values: unknown[]): number | undefined => {
      for (const value of values) {
        if (typeof value === 'number' && Number.isFinite(value)) return value
      }
      return undefined
    }
    const firstFiniteInt = (...values: unknown[]): number | undefined => {
      for (const value of values) {
        if (typeof value === 'number' && Number.isFinite(value)) return Math.trunc(value)
      }
      return undefined
    }
    const voiceSpeed = canSpeak
      ? firstFiniteNumber(reference.voice_speed, img?.voice_speed)
      : undefined
    const voiceWan2gpPreset = canSpeak
      ? (String(reference.voice_wan2gp_preset || '').trim() || String(img?.voice_wan2gp_preset || '').trim() || undefined)
      : undefined
    const voiceWan2gpAltPrompt = canSpeak
      ? (reference.voice_wan2gp_alt_prompt ?? img?.voice_wan2gp_alt_prompt)
      : undefined
    const voiceWan2gpAudioGuide = canSpeak
      ? (reference.voice_wan2gp_audio_guide ?? img?.voice_wan2gp_audio_guide)
      : undefined
    const voiceWan2gpTemperature = canSpeak
      ? firstFiniteNumber(reference.voice_wan2gp_temperature, img?.voice_wan2gp_temperature)
      : undefined
    const voiceWan2gpTopK = canSpeak
      ? firstFiniteInt(reference.voice_wan2gp_top_k, img?.voice_wan2gp_top_k)
      : undefined
    const voiceWan2gpSeed = canSpeak
      ? firstFiniteInt(reference.voice_wan2gp_seed, img?.voice_wan2gp_seed)
      : undefined
    return {
      ...reference,
      setting,
      appearance_description: appearanceDescription,
      can_speak: canSpeak,
      voice_audio_provider: voiceAudioProvider,
      voice_name: voiceName,
      voice_speed: voiceSpeed,
      voice_wan2gp_preset: voiceWan2gpPreset,
      voice_wan2gp_alt_prompt: voiceWan2gpAltPrompt,
      voice_wan2gp_audio_guide: voiceWan2gpAudioGuide,
      voice_wan2gp_temperature: voiceWan2gpTemperature,
      voice_wan2gp_top_k: voiceWan2gpTopK,
      voice_wan2gp_seed: voiceWan2gpSeed,
      image_url: imageUrl,
    }
  })

  const resolveShotAssetByShot = <T extends { shot_id?: string; shot_index?: number }>(
    assets: T[] | undefined,
    shot: { shot_id?: string },
    shotIndex: number
  ): T | undefined => {
    const shotId = String(shot.shot_id || '').trim()
    if (shotId) {
      const byId = assets?.find((item) => String(item.shot_id || '').trim() === shotId)
      if (byId) return byId
    }
    return assets?.find((item) => item.shot_index === shotIndex)
  }

  const contentOutput = contentStage?.output_data as StageDataResult['content'] | undefined
  const normalizedContent = contentOutput
    ? {
        ...contentOutput,
        shots_locked: typeof contentOutput.shots_locked === 'boolean'
          ? contentOutput.shots_locked
          : normalizedShots.length > 0,
      }
    : (
        normalizedShots.length > 0
          ? { shots_locked: true }
          : undefined
      )

  return {
    content: normalizedContent,
    storyboard: normalizedShots ? {
      shots: normalizedShots,
      references: mergedReferences.length > 0 ? mergedReferences : undefined,
    } : undefined,
    audio: (() => {
      const shotAudios = normalizedShots?.map((shot, shotIndex) => {
        const audioAsset = resolveShotAssetByShot(audioAssets, shot, shotIndex)
        const bUrl = audioAsset?.file_path ? toStorageUrl(audioAsset.file_path) : undefined
        return {
          shot_id: shot?.shot_id,
          shot_index: shotIndex,
          voice_content: audioAsset?.voice_content,
          speaker_id: shot?.speaker_id || audioAsset?.speaker_id,
          speaker_name: shot?.speaker_name || audioAsset?.speaker_name,
          audio_url: bUrl ? `${bUrl}?t=${audioAsset?.updated_at || 0}` : undefined,
          duration: typeof audioAsset?.duration === 'number' ? audioAsset.duration : undefined,
          updated_at: audioAsset?.updated_at,
        }
      }) || []

      if (shotAudios.length === 0) {
        return undefined
      }

      return {
        shots: shotAudios,
      }
    })(),
    reference: {
      references: mergedReferences.length > 0 ? mergedReferences : undefined,
      reference_images: referenceImages,
    },
    frame: normalizedShots ? {
      shots: normalizedShots.map((shot, shotIndex) => {
        const frameImg = resolveShotAssetByShot(frameData?.frame_images, shot, shotIndex)
        const frameBaseUrl = frameImg?.file_path ? toStorageUrl(frameImg.file_path) : undefined
        return {
          shot_id: shot?.shot_id,
          shot_index: shotIndex,
          first_frame_url: frameBaseUrl
            ? `${frameBaseUrl}?t=${frameImg?.updated_at || 0}`
            : undefined,
          first_frame_description: normalizedShots[shotIndex]?.first_frame_description || frameImg?.first_frame_description,
          updated_at: frameImg?.updated_at,
        }
      })
    } : undefined,
    video: normalizedShots ? {
      shots: normalizedShots.map((shot, shotIndex) => {
        const videoAsset = resolveShotAssetByShot(videoAssets, shot, shotIndex)
        const bUrl = videoAsset?.file_path ? toStorageUrl(videoAsset.file_path) : undefined
        return {
          shot_id: shot?.shot_id,
          shot_index: shotIndex,
          video_url: bUrl ? `${bUrl}?t=${videoAsset?.updated_at || 0}` : undefined,
          duration: typeof videoAsset?.duration === 'number' ? videoAsset.duration : undefined,
          width: typeof videoAsset?.width === 'number' ? videoAsset.width : undefined,
          height: typeof videoAsset?.height === 'number' ? videoAsset.height : undefined,
          updated_at: videoAsset?.updated_at,
        }
      })
    } : undefined,
    compose: composeData?.master_video_path ? {
      video_url: (() => {
        const bUrl = toStorageUrl(composeData.master_video_path)
        if (!bUrl) return undefined
        return composeData.updated_at ? `${bUrl}?t=${composeData.updated_at}` : bUrl
      })(),
      poster_url: (() => {
        const firstFrameShot = normalizedShots[0]
        if (!firstFrameShot) return undefined
        const frameImg = resolveShotAssetByShot(frameData?.frame_images, firstFrameShot, 0)
        const frameBaseUrl = frameImg?.file_path ? toStorageUrl(frameImg.file_path) : undefined
        return frameBaseUrl
          ? `${frameBaseUrl}?t=${frameImg?.updated_at || 0}`
          : undefined
      })(),
      duration: typeof composeData?.duration === 'number' ? composeData.duration : undefined,
      width: (() => {
        if (typeof composeData?.width === 'number') return composeData.width
        const firstShot = normalizedShots[0]
        if (!firstShot) return undefined
        const videoAsset = resolveShotAssetByShot(videoAssets, firstShot, 0)
        return typeof videoAsset?.width === 'number' ? videoAsset.width : undefined
      })(),
      height: (() => {
        if (typeof composeData?.height === 'number') return composeData.height
        const firstShot = normalizedShots[0]
        if (!firstShot) return undefined
        const videoAsset = resolveShotAssetByShot(videoAssets, firstShot, 0)
        return typeof videoAsset?.height === 'number' ? videoAsset.height : undefined
      })(),
    } : undefined,
    subtitle: subtitleData?.subtitle_file_path ? {
      subtitle_url: (() => {
        const bUrl = toStorageUrl(subtitleData.subtitle_file_path)
        if (!bUrl) return undefined
        return subtitleData.updated_at ? `${bUrl}?t=${subtitleData.updated_at}` : bUrl
      })(),
      duration: typeof subtitleData?.duration === 'number' ? subtitleData.duration : undefined,
      line_count: typeof subtitleData?.line_count === 'number' ? subtitleData.line_count : undefined,
    } : undefined,
    burn_subtitle: burnSubtitleData?.burned_video_path ? {
      video_url: (() => {
        const bUrl = toStorageUrl(burnSubtitleData.burned_video_path)
        if (!bUrl) return undefined
        return burnSubtitleData.updated_at ? `${bUrl}?t=${burnSubtitleData.updated_at}` : bUrl
      })(),
      duration: typeof burnSubtitleData?.duration === 'number' ? burnSubtitleData.duration : undefined,
      width: typeof burnSubtitleData?.width === 'number' ? burnSubtitleData.width : undefined,
      height: typeof burnSubtitleData?.height === 'number' ? burnSubtitleData.height : undefined,
    } : undefined,
    finalize: finalizeData?.final_video_path ? {
      video_url: (() => {
        const bUrl = toStorageUrl(finalizeData.final_video_path)
        if (!bUrl) return undefined
        return finalizeData.updated_at ? `${bUrl}?t=${finalizeData.updated_at}` : bUrl
      })(),
      poster_url: (() => {
        const firstFrameShot = normalizedShots[0]
        if (!firstFrameShot) return undefined
        const frameImg = resolveShotAssetByShot(frameData?.frame_images, firstFrameShot, 0)
        const frameBaseUrl = frameImg?.file_path ? toStorageUrl(frameImg.file_path) : undefined
        return frameBaseUrl ? `${frameBaseUrl}?t=${frameImg?.updated_at || 0}` : undefined
      })(),
      duration: typeof finalizeData?.duration === 'number' ? finalizeData.duration : undefined,
      width: typeof finalizeData?.width === 'number' ? finalizeData.width : undefined,
      height: typeof finalizeData?.height === 'number' ? finalizeData.height : undefined,
      has_subtitle: typeof finalizeData?.has_subtitle === 'boolean' ? finalizeData.has_subtitle : undefined,
      source_stage: typeof finalizeData?.source_stage === 'string' ? finalizeData.source_stage : undefined,
    } : undefined,
  }
}

// --- Stage completion computation ---

export interface StageCompletionResult {
  contentReady: boolean
  shotTextReady: boolean
  storyboardReady: boolean
  firstFrameDescReady: boolean
  audioReady: boolean
  frameReady: boolean
  videoReady: boolean
  composeReady: boolean
  subtitleReady: boolean
  burnSubtitleReady: boolean
  finalizeReady: boolean
  referenceInfoReady: boolean
  referenceImageReady: boolean
}

export function computeStageCompletion(
  stageData: StageDataResult | undefined,
  isSingleTakeEnabled: boolean,
): StageCompletionResult {
  const shots = stageData?.storyboard?.shots || []
  const shotCount = shots.length
  const references = stageData?.reference?.references || stageData?.storyboard?.references || []

  const hasText = (value: unknown): boolean =>
    typeof value === 'string' && value.trim().length > 0

  const contentReady = hasText(stageData?.content?.content)
  const shotTextReady =
    shotCount > 0 && shots.every((shot) => hasText(shot.voice_content))
  const storyboardReady =
    shotCount > 0 && shots.every((shot) => hasText(shot.video_prompt))
  const firstShot = shots[0]
  const firstFrameDescReady =
    shotCount > 0
    && (
      isSingleTakeEnabled
        ? hasText(firstShot?.first_frame_description)
        : shots.every((shot) => hasText(shot.first_frame_description))
    )
  const audioReady =
    shotCount > 0
    && (stageData?.audio?.shots || []).filter((shot) => !!shot.audio_url).length >= shotCount
  const frameShots = stageData?.frame?.shots || []
  const firstFrameShot = frameShots[0]
  const frameReady =
    shotCount > 0
    && (
      isSingleTakeEnabled
        ? !!firstFrameShot?.first_frame_url
        : frameShots.filter((shot) => !!shot.first_frame_url).length >= shotCount
    )
  const videoReady =
    shotCount > 0
    && (stageData?.video?.shots || []).filter((shot) => !!shot.video_url).length >= shotCount
  const composeReady = !!stageData?.compose?.video_url
  const subtitleReady = !!stageData?.subtitle?.subtitle_url
  const burnSubtitleReady = !!stageData?.burn_subtitle?.video_url
  const finalizeReady = !!stageData?.finalize?.video_url
  const referenceInfoReady =
    references.length > 0
    && references.every((reference) => hasText(reference.name))
  const referenceImageReady =
    references.length > 0 && references.every((reference) => !!reference.image_url)

  return {
    contentReady,
    shotTextReady,
    storyboardReady,
    firstFrameDescReady,
    audioReady,
    frameReady,
    videoReady,
    composeReady,
    subtitleReady,
    burnSubtitleReady,
    finalizeReady,
    referenceInfoReady,
    referenceImageReady,
  }
}
