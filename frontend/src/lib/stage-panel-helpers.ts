import type {
  ImageProviderType,
  LLMProviderConfig,
  Settings,
  VertexVideoModel as ApiVertexVideoModel,
  Wan2gpImagePreset,
  Wan2gpVideoPreset,
} from '@/types/settings'
import type { StageConfig } from '@/types/stage-panel'
import { hasKlingCredentials } from '@/lib/kling'

export interface VertexVideoModelInfo {
  id: string
  label: string
  supportsReferenceImage: boolean
  supportsCombinedReference: boolean
  supportsLastFrame: boolean
  referenceRestrictions: string[]
}

/** Convert backend capabilities response to frontend format. */
export function fromApiVertexVideoModels(models: ApiVertexVideoModel[]): VertexVideoModelInfo[] {
  return models.map((m) => ({
    id: m.id,
    label: m.label,
    supportsReferenceImage: m.supports_reference_image,
    supportsCombinedReference: m.supports_combined_reference,
    supportsLastFrame: m.supports_last_frame,
    referenceRestrictions: m.reference_restrictions,
  }))
}

/** Hardcoded fallback — used when capabilities API is not yet loaded. */
export const VERTEX_VIDEO_MODELS: readonly VertexVideoModelInfo[] = [
  {
    id: 'veo-3.1',
    label: 'veo-3.1',
    supportsReferenceImage: false,
    supportsCombinedReference: false,
    supportsLastFrame: true,
    referenceRestrictions: [],
  },
  {
    id: 'veo-3.1-fast',
    label: 'veo-3.1-fast',
    supportsReferenceImage: false,
    supportsCombinedReference: false,
    supportsLastFrame: true,
    referenceRestrictions: [],
  },
  {
    id: 'veo-3.1-preview',
    label: 'veo-3.1-preview',
    supportsReferenceImage: true,
    supportsCombinedReference: false,
    supportsLastFrame: true,
    referenceRestrictions: ['最多 3 张参考图', '每张图需为单一主体'],
  },
  {
    id: 'veo-3.1-fast-preview',
    label: 'veo-3.1-fast-preview',
    supportsReferenceImage: true,
    supportsCombinedReference: false,
    supportsLastFrame: true,
    referenceRestrictions: ['最多 3 张参考图', '每张图需为单一主体'],
  },
] as const

export const CONCURRENCY_OPTIONS = ['1', '2', '4', '8', '16']
export const SECTION_TITLE_CLASS = 'text-base font-semibold tracking-tight'
export const BASE_IMAGE_ASPECT_RATIO_OPTIONS = ['1:1', '2:3', '3:2', '3:4', '4:3', '9:16', '16:9', '21:9']
export const GEMINI_IMAGE_ASPECT_RATIO_OPTIONS = ['1:1', '2:3', '3:2', '3:4', '4:3', '4:5', '5:4', '9:16', '16:9', '21:9']
export const GEMINI_FLASH_IMAGE_ASPECT_RATIO_OPTIONS = [
  '1:1', '1:4', '1:8', '2:3', '3:2', '3:4', '4:1', '4:3', '4:5', '5:4', '8:1', '9:16', '16:9', '21:9',
]
export const BASE_IMAGE_SIZE_OPTIONS = ['1K', '2K', '4K']
export const GEMINI_IMAGE_SIZE_OPTIONS = ['1K', '2K', '4K']
export const GEMINI_FLASH_IMAGE_SIZE_OPTIONS = ['512px', '1K', '2K', '4K']
export const VOLCENGINE_SEEDREAM_IMAGE_SIZE_OPTIONS: Record<string, string[]> = {
  'doubao-seedream-5.0': ['2K', '4K'],
  'doubao-seedream-4.5': ['2K', '4K'],
  'doubao-seedream-4.0': ['1K', '2K', '4K'],
}
export const VIDU_IMAGE_ASPECT_RATIO_OPTIONS = ['16:9', '9:16', '1:1', '3:4', '4:3', '21:9', '2:3', '3:2'] as const
export const VIDU_IMAGE_SIZE_OPTIONS = ['1080p', '2K', '4K'] as const
export const KLING_IMAGE_ASPECT_RATIO_OPTIONS = ['16:9', '9:16', '1:1', '4:3', '3:4', '3:2', '2:3', '21:9']
export const KLING_IMAGE_SIZE_OPTIONS_BY_MODEL: Record<string, string[]> = {
  'kling-v3': ['1K', '2K', '4K'],
  'kling-v3-omni': ['1K', '2K'],
}
export const KLING_VIDEO_ASPECT_RATIOS = ['16:9', '9:16', '1:1'] as const
export const KLING_VIDEO_RESOLUTIONS = ['1080'] as const
export const VIDU_VIDEO_ASPECT_RATIOS = ['16:9', '9:16', '3:4', '4:3', '1:1'] as const
export const VIDU_VIDEO_RESOLUTIONS = ['540p', '720p', '1080p'] as const

const GEMINI_FLASH_IMAGE_MODEL = 'gemini-3.1-flash-image-preview'

export function getImageSizeOptionsByProviderTypeAndModel(
  providerType: ImageProviderType | string | undefined,
  model: string | undefined
): string[] {
  const normalizedModel = String(model || '').trim().toLowerCase()
  const klingSizeOptions = KLING_IMAGE_SIZE_OPTIONS_BY_MODEL[normalizedModel]
  if (providerType === 'kling' || klingSizeOptions) {
    return klingSizeOptions || BASE_IMAGE_SIZE_OPTIONS
  }
  if (providerType === 'gemini_api') {
    return normalizedModel === GEMINI_FLASH_IMAGE_MODEL
      ? GEMINI_FLASH_IMAGE_SIZE_OPTIONS
      : GEMINI_IMAGE_SIZE_OPTIONS
  }
  if (providerType === 'volcengine_seedream') {
    const seedreamModel = String(model || '').trim()
    return VOLCENGINE_SEEDREAM_IMAGE_SIZE_OPTIONS[seedreamModel] ?? BASE_IMAGE_SIZE_OPTIONS
  }
  if (providerType === 'vidu' || normalizedModel === 'viduq2') {
    return [...VIDU_IMAGE_SIZE_OPTIONS]
  }
  return BASE_IMAGE_SIZE_OPTIONS
}

export function getImageAspectRatioOptionsByProviderTypeAndModel(
  providerType: ImageProviderType | string | undefined,
  model: string | undefined
): string[] {
  const normalizedModel = String(model || '').trim().toLowerCase()
  if (providerType === 'kling' || normalizedModel === 'kling-v3' || normalizedModel === 'kling-v3-omni') {
    return KLING_IMAGE_ASPECT_RATIO_OPTIONS
  }
  if (providerType === 'gemini_api') {
    return normalizedModel === GEMINI_FLASH_IMAGE_MODEL
      ? GEMINI_FLASH_IMAGE_ASPECT_RATIO_OPTIONS
      : GEMINI_IMAGE_ASPECT_RATIO_OPTIONS
  }
  if (providerType === 'vidu' || normalizedModel === 'viduq2') {
    return [...VIDU_IMAGE_ASPECT_RATIO_OPTIONS]
  }
  return BASE_IMAGE_ASPECT_RATIO_OPTIONS
}

export function formatImageSizeLabel(size: string): string {
  return size === '512px' ? '0.5K' : size
}

export function sanitizeDownloadFileName(value: string): string {
  const normalized = (value || '').trim()
  if (!normalized) return 'project'
  return normalized.replace(/[\\/:*?"<>|]/g, '_')
}

export function buildFinalVideoDownloadName(videoUrl: string, projectTitle?: string): string {
  const safeProjectTitle = sanitizeDownloadFileName(projectTitle || 'project')
  const urlWithoutQuery = videoUrl.split('?')[0] || ''
  const extensionMatch = urlWithoutQuery.match(/(\.[a-zA-Z0-9]+)$/)
  const extension = extensionMatch ? extensionMatch[1] : '.mp4'
  return `${safeProjectTitle}_final_video${extension}`
}

export function getImageDefaults(
  provider: string | undefined,
  settings: Settings | undefined,
  scene: 'reference' | 'frame'
): { aspectRatio: string; size: string } {
  const defaultAspectRatio = scene === 'reference' ? '1:1' : '9:16'
  const defaultSize = '1K'
  if (!settings) return { aspectRatio: defaultAspectRatio, size: defaultSize }
  if (provider === 'kling') {
    const model = scene === 'reference'
      ? String(settings.image_kling_t2i_model || 'kling-v3').trim().toLowerCase()
      : String(settings.image_kling_i2i_model || 'kling-v3').trim().toLowerCase()
    const aspect = scene === 'reference'
      ? String(settings.image_kling_reference_aspect_ratio || '').trim()
      : String(settings.image_kling_frame_aspect_ratio || '').trim()
    const size = scene === 'reference'
      ? String(settings.image_kling_reference_size || '').trim().toUpperCase()
      : String(settings.image_kling_frame_size || '').trim().toUpperCase()
    const ratioOptions = getImageAspectRatioOptionsByProviderTypeAndModel('kling', model)
    const sizeOptions = getImageSizeOptionsByProviderTypeAndModel('kling', model)
    return {
      aspectRatio: ratioOptions.includes(aspect) ? aspect : (ratioOptions.includes(defaultAspectRatio) ? defaultAspectRatio : (ratioOptions[0] || defaultAspectRatio)),
      size: sizeOptions.includes(size) ? size : (sizeOptions[0] || defaultSize),
    }
  }
  if (provider === 'vidu') {
    const aspect = scene === 'reference'
      ? String(settings.image_vidu_reference_aspect_ratio || '').trim()
      : String(settings.image_vidu_frame_aspect_ratio || '').trim()
    const sizeRaw = scene === 'reference'
      ? String(settings.image_vidu_reference_size || '').trim()
      : String(settings.image_vidu_frame_size || '').trim()
    const size = sizeRaw.toLowerCase() === '1k' ? '1080p' : sizeRaw
    return {
      aspectRatio: VIDU_IMAGE_ASPECT_RATIO_OPTIONS.includes(aspect as (typeof VIDU_IMAGE_ASPECT_RATIO_OPTIONS)[number])
        ? aspect
        : defaultAspectRatio,
      size: VIDU_IMAGE_SIZE_OPTIONS.includes(size as (typeof VIDU_IMAGE_SIZE_OPTIONS)[number])
        ? size
        : '1080p',
    }
  }
  const providers = settings.image_providers || []
  const normalizedId = provider === 'openai' ? 'builtin_openai_image' : provider
  const selected = providers.find((item) => item.id === normalizedId)
  if (!selected) return { aspectRatio: defaultAspectRatio, size: defaultSize }
  if (scene === 'reference') {
    return {
      aspectRatio: selected.reference_aspect_ratio || '1:1',
      size: selected.reference_size || '1K',
    }
  }
  return {
    aspectRatio: selected.frame_aspect_ratio || '9:16',
    size: selected.frame_size || '1K',
  }
}

export function getImageModelDefault(
  provider: string | undefined,
  settings: Settings | undefined,
  mode: 't2i' | 'i2i' = 't2i'
): string {
  if (!settings) return 'gemini-3-pro-image-preview'
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
  const normalizedId = provider === 'openai' ? 'builtin_openai_image' : provider
  const defaultBinding = String(
    mode === 'i2i'
      ? settings.default_image_i2i_model
      : settings.default_image_t2i_model
  ).trim()
  const separatorIndex = defaultBinding.indexOf('::')
  if (separatorIndex > 0) {
    const bindingProviderId = defaultBinding.slice(0, separatorIndex).trim()
    const bindingModelId = defaultBinding.slice(separatorIndex + 2).trim()
    if (bindingModelId && (!normalizedId || bindingProviderId === normalizedId)) {
      return bindingModelId
    }
  } else if (defaultBinding) {
    return defaultBinding
  }

  const providers = settings.image_providers || []
  const selected = providers.find((item) => item.id === normalizedId)
  if (!selected) return 'gemini-3-pro-image-preview'
  if (selected.default_model) return selected.default_model
  if (selected.enabled_models.length > 0) return selected.enabled_models[0]
  if (selected.catalog_models.length > 0) return selected.catalog_models[0]
  return 'gemini-3-pro-image-preview'
}

export function getWan2gpDefaults(
  settings: Settings | undefined
): {
  preset: string
  presetI2i: string
  referenceResolution: string
  frameResolution: string
  inferenceSteps: number
} {
  return {
    preset: settings?.image_wan2gp_preset || 'qwen_image_2512',
    presetI2i: settings?.image_wan2gp_preset_i2i || 'qwen_image_edit_plus2',
    referenceResolution: settings?.image_wan2gp_reference_resolution || '1024x1024',
    frameResolution: settings?.image_wan2gp_frame_resolution || '1088x1920',
    inferenceSteps: settings?.image_wan2gp_inference_steps || 0,
  }
}

export function getWan2gpPresetById(
  presets: Wan2gpImagePreset[],
  presetId: string
): Wan2gpImagePreset | undefined {
  return presets.find((preset) => preset.id === presetId)
}

export function getScopedWan2gpInferenceSteps(
  config: StageConfig,
  presetType: 't2i' | 'i2i'
): number | undefined {
  const scopedSteps = presetType === 'i2i'
    ? config.imageWan2gpInferenceStepsI2i
    : config.imageWan2gpInferenceStepsT2i
  if (typeof scopedSteps === 'number' && scopedSteps > 0) return scopedSteps
  if (typeof config.imageWan2gpInferenceSteps === 'number' && config.imageWan2gpInferenceSteps > 0) {
    return config.imageWan2gpInferenceSteps
  }
  return undefined
}

export function getWan2gpVideoPresetById(
  presets: Wan2gpVideoPreset[],
  presetId: string
): Wan2gpVideoPreset | undefined {
  return presets.find((preset) => preset.id === presetId)
}

export function isWan2gpT2iPreset(preset: Wan2gpImagePreset): boolean {
  if (Array.isArray(preset.supported_modes) && preset.supported_modes.includes('t2i')) return true
  if (preset.preset_type === 't2i') return true
  if (!preset.preset_type) return !preset.supports_reference
  return false
}

export function isWan2gpI2iPreset(preset: Wan2gpImagePreset): boolean {
  if (Array.isArray(preset.supported_modes) && preset.supported_modes.includes('i2i')) return true
  if (preset.preset_type === 'i2i') return true
  if (!preset.preset_type) return preset.supports_reference
  return false
}

function getDefaultVideoBinding(
  settings: Settings | undefined,
  mode: 't2v' | 'i2v'
): { providerId: string; modelId: string } | null {
  const rawBinding = String(
    mode === 'i2v'
      ? settings?.default_video_i2v_model
      : settings?.default_video_t2v_model
  ).trim()
  if (!rawBinding) return null
  const separatorIndex = rawBinding.indexOf(PROVIDER_MODEL_SEPARATOR)
  if (separatorIndex <= 0) return null
  const providerId = rawBinding.slice(0, separatorIndex).trim()
  const modelId = rawBinding.slice(separatorIndex + PROVIDER_MODEL_SEPARATOR.length).trim()
  if (!providerId || !modelId) return null
  return { providerId, modelId }
}

export function getVertexVideoDefaults(
  settings: Settings | undefined,
  mode: 't2v' | 'i2v' = 't2v'
): {
  model: string
  aspectRatio: string
  resolution: string
} {
  const fallbackModel = 'veo-3.1-fast-preview'
  const modelOptions = new Set<string>(VERTEX_VIDEO_MODELS.map((item) => String(item.id)))
  const defaultBinding = getDefaultVideoBinding(settings, mode)
  if (defaultBinding?.providerId === 'vertex_ai' && modelOptions.has(defaultBinding.modelId)) {
    return {
      model: defaultBinding.modelId,
      aspectRatio: settings?.video_vertex_ai_aspect_ratio || '16:9',
      resolution: settings?.video_vertex_ai_resolution || '1080',
    }
  }
  const configuredModel = String(settings?.video_vertex_ai_model || '').trim()
  if (!settings) return { model: 'veo-3.1-fast-preview', aspectRatio: '16:9', resolution: '1080' }
  return {
    model: modelOptions.has(configuredModel) ? configuredModel : fallbackModel,
    aspectRatio: settings.video_vertex_ai_aspect_ratio || '16:9',
    resolution: settings.video_vertex_ai_resolution || '1080',
  }
}

export function getSeedanceVideoDefaults(
  settings: Settings | undefined,
  mode: 't2v' | 'i2v' = 't2v'
): {
  model: string
  aspectRatio: string
  resolution: string
} {
  const defaultBinding = getDefaultVideoBinding(settings, mode)
  if (defaultBinding?.providerId === 'volcengine_seedance' && defaultBinding.modelId) {
    return {
      model: defaultBinding.modelId,
      aspectRatio: settings?.video_seedance_aspect_ratio || '9:16',
      resolution: settings?.video_seedance_resolution || '1080p',
    }
  }
  if (!settings) return { model: 'seedance-1-5-pro', aspectRatio: '9:16', resolution: '1080p' }
  return {
    model: settings.video_seedance_model || 'seedance-1-5-pro',
    aspectRatio: settings.video_seedance_aspect_ratio || '9:16',
    resolution: settings.video_seedance_resolution || '1080p',
  }
}

export function getKlingVideoDefaults(
  settings: Settings | undefined,
  mode: 't2v' | 'i2v' = 't2v'
): {
  model: string
  aspectRatio: string
  resolution: string
} {
  const defaultBinding = getDefaultVideoBinding(settings, mode)
  const configuredAspectRatio = String(settings?.video_kling_aspect_ratio || '').trim()
  const resolvedAspectRatio = KLING_VIDEO_ASPECT_RATIOS.includes(configuredAspectRatio as (typeof KLING_VIDEO_ASPECT_RATIOS)[number])
    ? configuredAspectRatio
    : '9:16'
  if (defaultBinding?.providerId === 'kling' && defaultBinding.modelId) {
    return {
      model: defaultBinding.modelId,
      aspectRatio: resolvedAspectRatio,
      resolution: '1080',
    }
  }
  return {
    model: settings?.video_kling_model || 'kling-v3',
    aspectRatio: resolvedAspectRatio,
    resolution: '1080',
  }
}

export function getViduVideoDefaults(
  settings: Settings | undefined,
  mode: 't2v' | 'i2v' = 't2v'
): {
  model: string
  aspectRatio: string
  resolution: string
} {
  const defaultBinding = getDefaultVideoBinding(settings, mode)
  const configuredAspectRatio = String(settings?.video_vidu_aspect_ratio || '').trim()
  const resolvedAspectRatio = VIDU_VIDEO_ASPECT_RATIOS.includes(configuredAspectRatio as (typeof VIDU_VIDEO_ASPECT_RATIOS)[number])
    ? configuredAspectRatio
    : '9:16'
  const configuredResolutionRaw = String(settings?.video_vidu_resolution || '').trim().toLowerCase()
  const resolvedResolution = configuredResolutionRaw === '540' || configuredResolutionRaw === '540p'
    ? '540p'
    : configuredResolutionRaw === '720' || configuredResolutionRaw === '720p'
      ? '720p'
      : configuredResolutionRaw === '1080' || configuredResolutionRaw === '1080p'
        ? '1080p'
        : '1080p'
  if (defaultBinding?.providerId === 'vidu' && defaultBinding.modelId) {
    return {
      model: defaultBinding.modelId,
      aspectRatio: resolvedAspectRatio,
      resolution: resolvedResolution,
    }
  }
  return {
    model: settings?.video_vidu_model || 'viduq3-turbo',
    aspectRatio: resolvedAspectRatio,
    resolution: resolvedResolution,
  }
}

export function getWan2gpVideoDefaults(
  settings: Settings | undefined
): {
  t2vPreset: string
  i2vPreset: string
  resolution: string
  inferenceSteps: number
  slidingWindowSize: number
} {
  const t2vBinding = getDefaultVideoBinding(settings, 't2v')
  const i2vBinding = getDefaultVideoBinding(settings, 'i2v')
  return {
    t2vPreset: (
      t2vBinding?.providerId === 'wan2gp' && t2vBinding.modelId
    )
      ? t2vBinding.modelId
      : (settings?.video_wan2gp_t2v_preset || 't2v_1.3B'),
    i2vPreset: (
      i2vBinding?.providerId === 'wan2gp' && i2vBinding.modelId
    )
      ? i2vBinding.modelId
      : (settings?.video_wan2gp_i2v_preset || 'i2v_720p'),
    resolution: settings?.video_wan2gp_resolution || '720x1280',
    inferenceSteps: 30,
    slidingWindowSize: 0,
  }
}

export interface ProviderModelOption {
  value: string
  provider: string
  model?: string
  label: string
  description?: string
  restrictions?: string[]
}

export const PROVIDER_MODEL_SEPARATOR = '::'

export function makeProviderModelValue(provider: string, model?: string): string {
  if (!model) return provider
  return `${provider}${PROVIDER_MODEL_SEPARATOR}${model}`
}

export function parseProviderModelValue(value: string): { provider: string; model?: string } {
  if (!value.includes(PROVIDER_MODEL_SEPARATOR)) {
    return { provider: value }
  }
  const [provider, model] = value.split(PROVIDER_MODEL_SEPARATOR, 2)
  return { provider, model }
}

export function resolveProviderDisplayLabel(provider: string, providerLabel?: string): string {
  const explicitLabel = (providerLabel || '').trim()
  if (explicitLabel) return explicitLabel
  if (provider.startsWith('custom_')) {
    const trimmed = provider.slice('custom_'.length)
    return trimmed || provider
  }
  return provider
}

export function buildProviderModelLabel(provider: string, model?: string, providerLabel?: string): string {
  const displayProvider = resolveProviderDisplayLabel(provider, providerLabel)
  const displayModel = String(model || '').trim()
  return displayModel ? `${displayProvider} | ${displayModel}` : displayProvider
}

export function getConfiguredLLMProviders(settings: Settings | undefined): LLMProviderConfig[] {
  return (settings?.llm_providers || [])
    .filter((provider) => provider.api_key.trim())
    .filter((provider) => provider.enabled_models.length > 0)
}

export function getConfiguredImageProviders(settings: Settings | undefined): string[] {
  const providers: string[] = []
  const configuredImageProviders = settings?.image_providers || []
  configuredImageProviders.forEach((provider) => {
    const hasKey = !!provider.api_key.trim()
    const hasModel = provider.enabled_models.length > 0
    if (hasKey && hasModel) {
      providers.push(provider.id)
    }
  })
  if (settings?.wan2gp_available) providers.push('wan2gp')
  if (hasKlingCredentials(settings)) providers.push('kling')
  if ((settings?.vidu_api_key || '').trim()) providers.push('vidu')
  return providers
}
