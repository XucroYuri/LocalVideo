import type { StageConfig } from '@/types/stage-panel'
import type { BackendStageType } from '@/types/stage'
import type { Settings } from '@/types/settings'

export function normalizeProviderName(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const normalized = value.trim().toLowerCase()
  return normalized || undefined
}

export type VideoProviderName = 'volcengine_seedance' | 'wan2gp'

export function normalizeVideoProvider(value: unknown): VideoProviderName | undefined {
  const normalized = normalizeProviderName(value)
  if (normalized === 'volcengine_seedance' || normalized === 'wan2gp') {
    return normalized
  }
  return undefined
}

export function getConfiguredVideoProviders(settings: Settings | undefined): VideoProviderName[] {
  const providers: VideoProviderName[] = []
  if ((settings?.video_seedance_api_key || '').trim()) providers.push('volcengine_seedance')
  if (settings?.wan2gp_available) providers.push('wan2gp')
  return providers
}

export function resolveVideoProvider(
  preferred: unknown,
  settings: Settings | undefined
): VideoProviderName {
  const configuredProviders = getConfiguredVideoProviders(settings)
  const normalizedPreferred = normalizeVideoProvider(preferred)
  if (normalizedPreferred && configuredProviders.includes(normalizedPreferred)) {
    return normalizedPreferred
  }

  const normalizedDefault = normalizeVideoProvider(settings?.default_video_provider)
  if (normalizedDefault && configuredProviders.includes(normalizedDefault)) {
    return normalizedDefault
  }

  if (configuredProviders.length > 0) {
    return configuredProviders[0]
  }
  if (normalizedDefault) {
    return normalizedDefault
  }
  return 'volcengine_seedance'
}

export function providerKeyForStage(stage: BackendStageType | undefined): string | undefined {
  switch (stage) {
    case 'audio':
      return 'audio_provider'
    case 'frame':
    case 'reference':
      return 'image_provider'
    case 'video':
      return 'video_provider'
    default:
      return undefined
  }
}

export function isWan2gpStageRuntime(params: {
  stage: BackendStageType | undefined
  inputData?: Record<string, unknown> | null
  outputData?: Record<string, unknown> | null
}): boolean {
  const { stage, inputData, outputData } = params
  const providerKey = providerKeyForStage(stage)
  if (!providerKey) return false

  const inputProvider = normalizeProviderName(inputData?.[providerKey])
  if (inputProvider === 'wan2gp') return true

  const outputProviderCandidates = [
    outputData?.[providerKey],
    outputData?.runtime_provider,
    outputData?.provider,
  ]
  return outputProviderCandidates.some((value) => normalizeProviderName(value) === 'wan2gp')
}

export function buildProviderHintInput(params: {
  stage: BackendStageType
  inputData?: Record<string, unknown>
  config?: StageConfig | null
  settings?: Settings
}): Record<string, unknown> {
  const { stage, inputData, config, settings } = params
  const merged: Record<string, unknown> = { ...(inputData || {}) }
  switch (stage) {
    case 'audio':
      if (!merged.audio_provider && config?.audioRoleConfigs) {
        const roleProvider = Object.values(config.audioRoleConfigs)
          .map((item) => (item && typeof item === 'object' ? item.audioProvider : undefined))
          .find((provider) => (
            provider === 'wan2gp'
            || provider === 'edge_tts'
            || provider === 'volcengine_tts'
            || provider === 'kling_tts'
            || provider === 'vidu_tts'
            || provider === 'minimax_tts'
            || provider === 'xiaomi_mimo_tts'
          ))
        if (roleProvider) {
          merged.audio_provider = roleProvider
        }
      }
      merged.audio_provider =
        merged.audio_provider
        || config?.audioProvider
        || settings?.default_audio_provider
      break
    case 'frame':
    case 'reference':
      merged.image_provider =
        merged.image_provider
        || config?.imageProvider
        || settings?.default_image_provider
      break
    case 'video':
      merged.video_provider = (
        normalizeVideoProvider(merged.video_provider)
        || resolveVideoProvider(config?.videoProvider, settings)
      )
      break
    default:
      break
  }
  return merged
}

export function runningFallbackMessage(params: {
  stage: BackendStageType | undefined
  progress: number
  inputData?: Record<string, unknown> | null
  outputData?: Record<string, unknown> | null
}): string {
  const { stage, progress, inputData, outputData } = params
  const isWan2gp = isWan2gpStageRuntime({ stage, inputData, outputData })
  if (isWan2gp) {
    return progress > 0 ? '生成中...' : '准备中...'
  }
  return progress > 0 ? '生成中...' : '准备中...'
}

export function normalizeRunningMessage(params: {
  stage: BackendStageType | undefined
  message?: string | null
  progress: number
  inputData?: Record<string, unknown> | null
  outputData?: Record<string, unknown> | null
}): string {
  const { stage, message, progress, inputData, outputData } = params
  const trimmed = (message || '').trim()
  const isWan2gp = isWan2gpStageRuntime({ stage, inputData, outputData })
  if (!trimmed) {
    return runningFallbackMessage({ stage, progress, inputData, outputData })
  }
  if (trimmed.startsWith('启动中')) {
    return runningFallbackMessage({ stage, progress, inputData, outputData })
  }
  if (isWan2gp && trimmed.startsWith('执行中')) {
    return runningFallbackMessage({ stage, progress, inputData, outputData })
  }
  return trimmed
}
