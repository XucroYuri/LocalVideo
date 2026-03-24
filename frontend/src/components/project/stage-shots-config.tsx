'use client'

import { useMemo } from 'react'
import { AlertCircle } from 'lucide-react'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { Slider } from '@/components/ui/slider'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { resolveEnabledModelIds } from '@/lib/provider-config'
import { cn } from '@/lib/utils'
import {
  getWan2gpResolutionChoices,
  getWan2gpResolutionTiers,
  getWan2gpPromptLanguageHint,
} from '@/lib/wan2gp'
import {
  SEEDANCE_ASPECT_RATIOS,
  SEEDANCE_MODEL_PRESETS,
  SEEDANCE_RESOLUTIONS,
} from '@/lib/seedance'
import {
  VERTEX_VIDEO_MODELS,
  CONCURRENCY_OPTIONS,
  SECTION_TITLE_CLASS,
  getImageDefaults,
  getImageModelDefault,
  getWan2gpDefaults,
  getScopedWan2gpInferenceSteps,
  getVertexVideoDefaults,
  getSeedanceVideoDefaults,
  getKlingVideoDefaults,
  getViduVideoDefaults,
  getWan2gpVideoDefaults,
  KLING_VIDEO_ASPECT_RATIOS,
  KLING_VIDEO_RESOLUTIONS,
  VIDU_VIDEO_ASPECT_RATIOS,
  VIDU_VIDEO_RESOLUTIONS,
  makeProviderModelValue,
  buildProviderModelLabel,
  formatImageSizeLabel,
} from '@/lib/stage-panel-helpers'
import { getImageProviderDisplayName } from '@/lib/provider-config'
import {
  IMAGE_STYLES,
  STORYBOARD_SHOT_DENSITIES,
  TEXT_PROMPT_COMPLEXITIES,
  TEXT_TARGET_LANGUAGES,
} from '@/lib/stage-panel-config'
import type { ProviderModelOption } from '@/lib/stage-panel-helpers'
import type {
  ImageProviderConfig,
  Settings,
  Wan2gpImagePreset,
  Wan2gpVideoPreset,
} from '@/types/settings'
import type { StageConfig } from '@/types/stage-panel'
const VIDEO_ASPECT_RATIOS = ['16:9', '9:16']
const VIDEO_RESOLUTIONS = ['720', '1080']
const WAN2GP_DREAMOMNI2_PRESET_ID = 'flux_dev_kontext_dreamomni2'
const VIDU_VIDEO_MODEL_OPTIONS = ['viduq3-turbo', 'viduq3-pro'] as const

interface StageShotsConfigProps {
  config: StageConfig
  updateConfig: (updates: Partial<StageConfig>) => void
  settings: Settings | undefined
  isSettingsLoading: boolean
  hasReferenceData: boolean
  isSingleTakeEnabled: boolean
  isSingleTakeForcedByMode: boolean
  effectiveUseFirstFrameRef: boolean
  wan2gpT2iPresets: Wan2gpImagePreset[]
  wan2gpI2iPresets: Wan2gpImagePreset[]
  wan2gpVideoT2vPresets: Wan2gpVideoPreset[]
  wan2gpVideoI2vPresets: Wan2gpVideoPreset[]
  getConfiguredVideoProviders: () => string[]
  getConfiguredImageProviders: () => string[]
  resolveEffectiveImageProvider: (providers: string[]) => string
  getImageProviderById: (providerId: string) => ImageProviderConfig | undefined
  getImageSizeOptionsByProviderModel: (providerId: string | undefined, model: string | undefined) => string[]
  getImageAspectRatioOptionsByProviderModel: (providerId: string | undefined, model: string | undefined) => string[]
  resolveWan2gpPreset: (presetId: string, presetType: 't2i' | 'i2i') => Wan2gpImagePreset | undefined
  resolveWan2gpVideoPreset: (presetId: string, mode: 't2v' | 'i2v') => Wan2gpVideoPreset | undefined
  handleVideoRuntimeModelChange: (value: string) => void
  handleImageRuntimeModelChange: (value: string, scene: 'reference' | 'frame') => void
  handleUseFirstFrameRefChange: (checked: boolean) => void
  handleUseReferenceImageRefChange: (checked: boolean) => void
  handleWan2gpResolutionTierChange: (
    choices: ReturnType<typeof getWan2gpResolutionChoices>,
    tier: string,
    field: 'referenceImageResolution' | 'frameImageResolution'
  ) => void
  handleWan2gpVideoResolutionTierChange: (
    choices: ReturnType<typeof getWan2gpResolutionChoices>,
    tier: string
  ) => void
  handleSingleTakeChange: (checked: boolean) => void
  handleUseReferenceConsistencyChange: (checked: boolean) => void
  renderLLMOptions: () => React.ReactNode
  renderNoConfigWarning: (type: string) => React.ReactNode
}

export function StageShotsConfig({
  config,
  updateConfig,
  settings,
  isSettingsLoading,
  hasReferenceData,
  isSingleTakeEnabled,
  isSingleTakeForcedByMode,
  effectiveUseFirstFrameRef,
  wan2gpT2iPresets,
  wan2gpI2iPresets,
  wan2gpVideoT2vPresets,
  wan2gpVideoI2vPresets,
  getConfiguredVideoProviders,
  getConfiguredImageProviders,
  resolveEffectiveImageProvider,
  getImageProviderById,
  getImageSizeOptionsByProviderModel,
  getImageAspectRatioOptionsByProviderModel,
  resolveWan2gpPreset,
  resolveWan2gpVideoPreset,
  handleVideoRuntimeModelChange,
  handleImageRuntimeModelChange,
  handleUseFirstFrameRefChange,
  handleUseReferenceImageRefChange,
  handleWan2gpResolutionTierChange,
  handleWan2gpVideoResolutionTierChange,
  handleSingleTakeChange,
  handleUseReferenceConsistencyChange,
  renderLLMOptions,
  renderNoConfigWarning,
}: StageShotsConfigProps) {
  const videoProviders = useMemo(() => getConfiguredVideoProviders(), [getConfiguredVideoProviders])
  const videoImageProviders = useMemo(() => getConfiguredImageProviders(), [getConfiguredImageProviders])
  const wan2gpDefaults = useMemo(() => getWan2gpDefaults(settings), [settings])

  const usingI2iPreset = config.useReferenceConsistency ?? false

  const selectedWan2gpT2iPreset = useMemo(
    () => resolveWan2gpPreset(config.imageWan2gpPreset || wan2gpDefaults.preset, 't2i'),
    [config.imageWan2gpPreset, wan2gpDefaults.preset, resolveWan2gpPreset]
  )
  const selectedWan2gpI2iPreset = useMemo(
    () => resolveWan2gpPreset(config.imageWan2gpPresetI2i || wan2gpDefaults.presetI2i, 'i2i'),
    [config.imageWan2gpPresetI2i, wan2gpDefaults.presetI2i, resolveWan2gpPreset]
  )
  const activeWan2gpPreset = usingI2iPreset ? selectedWan2gpI2iPreset : selectedWan2gpT2iPreset
  const isDreamOmni2Preset = activeWan2gpPreset?.id === WAN2GP_DREAMOMNI2_PRESET_ID

  const frameRuntimeOptions = useMemo<ProviderModelOption[]>(() => [
    ...videoImageProviders.flatMap((provider) => {
      if (provider === 'wan2gp') {
        const presets = usingI2iPreset ? wan2gpI2iPresets : wan2gpT2iPresets
        return presets.map((preset) => ({
          value: makeProviderModelValue('wan2gp', preset.id),
          provider: 'wan2gp',
          model: preset.id,
          label: buildProviderModelLabel('wan2gp', preset.display_name, 'Wan2GP'),
          description: preset.description,
        }))
      }
      if (provider === 'kling') {
        return ['kling-v3', 'kling-v3-omni'].map((modelId) => ({
          value: makeProviderModelValue('kling', modelId),
          provider: 'kling',
          model: modelId,
          label: buildProviderModelLabel('kling', modelId, '可灵'),
        }))
      }
      if (provider === 'vidu') {
        const modelId = usingI2iPreset
          ? (settings?.image_vidu_i2i_model || 'viduq2')
          : (settings?.image_vidu_t2i_model || 'viduq2')
        return [{
          value: makeProviderModelValue('vidu', modelId),
          provider: 'vidu',
          model: modelId,
          label: buildProviderModelLabel('vidu', modelId, 'Vidu'),
        }]
      }
      const configuredProvider = getImageProviderById(provider)
      if (!configuredProvider) return []
      const models = configuredProvider.enabled_models.length > 0
        ? configuredProvider.enabled_models
        : configuredProvider.catalog_models
      return models.map((modelId) => ({
        value: makeProviderModelValue(provider, modelId),
        provider,
        model: modelId,
        label: buildProviderModelLabel(
          provider,
          modelId,
          getImageProviderDisplayName(configuredProvider)
        ),
      }))
    }),
  ], [videoImageProviders, usingI2iPreset, wan2gpI2iPresets, wan2gpT2iPresets, getImageProviderById, settings])

  const effectiveVideoImageProvider = useMemo(
    () => resolveEffectiveImageProvider(videoImageProviders),
    [resolveEffectiveImageProvider, videoImageProviders]
  )
  const videoImageDefaults = useMemo(
    () => getImageDefaults(effectiveVideoImageProvider, settings, 'frame'),
    [effectiveVideoImageProvider, settings]
  )

  const effectiveFrameRuntimeValue = useMemo(() => {
    if (effectiveVideoImageProvider === 'wan2gp') {
      return makeProviderModelValue(
        'wan2gp',
        activeWan2gpPreset?.id || (usingI2iPreset ? wan2gpDefaults.presetI2i : wan2gpDefaults.preset)
      )
    }
    const defaultMode = usingI2iPreset ? 'i2i' : 't2i'
    const selectedFrameModel = config.frameImageModel || config.imageModel
    return makeProviderModelValue(
      effectiveVideoImageProvider,
      selectedFrameModel || getImageModelDefault(effectiveVideoImageProvider, settings, defaultMode)
    )
  }, [
    effectiveVideoImageProvider,
    activeWan2gpPreset?.id,
    usingI2iPreset,
    wan2gpDefaults,
    config.frameImageModel,
    config.imageModel,
    settings,
  ])

  const selectedFrameRuntimeOption = useMemo(
    () => frameRuntimeOptions.find((item) => item.value === effectiveFrameRuntimeValue) || frameRuntimeOptions[0],
    [frameRuntimeOptions, effectiveFrameRuntimeValue]
  )

  const frameSizeOptions = useMemo(
    () => getImageSizeOptionsByProviderModel(
      selectedFrameRuntimeOption?.provider || effectiveVideoImageProvider,
      selectedFrameRuntimeOption?.model
        || config.frameImageModel
        || config.imageModel
        || getImageModelDefault(effectiveVideoImageProvider, settings, usingI2iPreset ? 'i2i' : 't2i')
    ),
    [
      selectedFrameRuntimeOption,
      effectiveVideoImageProvider,
      config.frameImageModel,
      config.imageModel,
      settings,
      usingI2iPreset,
      getImageSizeOptionsByProviderModel,
    ]
  )
  const frameAspectRatioOptions = useMemo(
    () => getImageAspectRatioOptionsByProviderModel(
      selectedFrameRuntimeOption?.provider || effectiveVideoImageProvider,
      selectedFrameRuntimeOption?.model
        || config.frameImageModel
        || config.imageModel
        || getImageModelDefault(effectiveVideoImageProvider, settings, usingI2iPreset ? 'i2i' : 't2i')
    ),
    [
      selectedFrameRuntimeOption,
      effectiveVideoImageProvider,
      config.frameImageModel,
      config.imageModel,
      settings,
      usingI2iPreset,
      getImageAspectRatioOptionsByProviderModel,
    ]
  )

  const effectiveFrameImageSize = useMemo(() => {
    if (frameSizeOptions.includes(config.frameImageSize || '')) {
      return config.frameImageSize || ''
    }
    return frameSizeOptions.includes(videoImageDefaults.size)
      ? videoImageDefaults.size
      : (frameSizeOptions[0] || videoImageDefaults.size)
  }, [frameSizeOptions, config.frameImageSize, videoImageDefaults.size])
  const effectiveFrameAspectRatio = useMemo(() => {
    if (frameAspectRatioOptions.includes(config.frameAspectRatio || '')) {
      return config.frameAspectRatio || ''
    }
    if (frameAspectRatioOptions.includes(videoImageDefaults.aspectRatio)) {
      return videoImageDefaults.aspectRatio
    }
    if (frameAspectRatioOptions.includes('9:16')) {
      return '9:16'
    }
    return frameAspectRatioOptions[0] || videoImageDefaults.aspectRatio
  }, [frameAspectRatioOptions, config.frameAspectRatio, videoImageDefaults.aspectRatio])

  const wan2gpResolutionOptions = useMemo(
    () => activeWan2gpPreset?.supported_resolutions?.length
      ? activeWan2gpPreset.supported_resolutions
      : [activeWan2gpPreset?.default_resolution || wan2gpDefaults.frameResolution],
    [activeWan2gpPreset, wan2gpDefaults.frameResolution]
  )
  const wan2gpResolutionChoices = useMemo(
    () => getWan2gpResolutionChoices(wan2gpResolutionOptions),
    [wan2gpResolutionOptions]
  )
  const wan2gpResolutionTiers = useMemo(
    () => getWan2gpResolutionTiers(wan2gpResolutionChoices),
    [wan2gpResolutionChoices]
  )

  const effectiveWan2gpResolution = useMemo(() => {
    if (config.frameImageResolution && wan2gpResolutionOptions.includes(config.frameImageResolution)) {
      return config.frameImageResolution
    }
    return activeWan2gpPreset?.default_resolution || wan2gpResolutionOptions[0] || wan2gpDefaults.frameResolution
  }, [config.frameImageResolution, wan2gpResolutionOptions, activeWan2gpPreset, wan2gpDefaults.frameResolution])

  const effectiveWan2gpResolutionTier = useMemo(
    () => wan2gpResolutionChoices.find((choice) => choice.value === effectiveWan2gpResolution)?.tier
      || wan2gpResolutionTiers[0] || '720p',
    [wan2gpResolutionChoices, effectiveWan2gpResolution, wan2gpResolutionTiers]
  )
  const tierResolutionChoices = useMemo(
    () => wan2gpResolutionChoices.filter((choice) => choice.tier === effectiveWan2gpResolutionTier),
    [wan2gpResolutionChoices, effectiveWan2gpResolutionTier]
  )

  const effectiveWan2gpSteps = useMemo(
    () => getScopedWan2gpInferenceSteps(config, usingI2iPreset ? 'i2i' : 't2i')
      || activeWan2gpPreset?.inference_steps
      || wan2gpDefaults.inferenceSteps
      || 20,
    [config, usingI2iPreset, activeWan2gpPreset, wan2gpDefaults.inferenceSteps]
  )

  const useFirstFrameRef = effectiveUseFirstFrameRef
  const videoModelMode: 't2v' | 'i2v' = useFirstFrameRef ? 'i2v' : 't2v'
  const vertexVideoDefaults = useMemo(
    () => getVertexVideoDefaults(settings, videoModelMode),
    [settings, videoModelMode]
  )
  const seedanceVideoDefaults = useMemo(
    () => getSeedanceVideoDefaults(settings, videoModelMode),
    [settings, videoModelMode]
  )
  const klingVideoDefaults = useMemo(
    () => getKlingVideoDefaults(settings, videoModelMode),
    [settings, videoModelMode]
  )
  const viduVideoDefaults = useMemo(
    () => getViduVideoDefaults(settings, videoModelMode),
    [settings, videoModelMode]
  )
  const enabledViduVideoModels = useMemo(
    () => resolveEnabledModelIds(
      settings?.video_vidu_enabled_models,
      [...VIDU_VIDEO_MODEL_OPTIONS]
    ),
    [settings?.video_vidu_enabled_models]
  )
  const useReferenceImageRef = config.useReferenceImageRef ?? false
  const wan2gpVideoDefaults = useMemo(() => getWan2gpVideoDefaults(settings), [settings])

  const selectedWan2gpVideoT2vPreset = useMemo(
    () => resolveWan2gpVideoPreset(config.videoWan2gpT2vPreset || wan2gpVideoDefaults.t2vPreset, 't2v'),
    [config.videoWan2gpT2vPreset, wan2gpVideoDefaults.t2vPreset, resolveWan2gpVideoPreset]
  )
  const selectedWan2gpVideoI2vPreset = useMemo(
    () => resolveWan2gpVideoPreset(config.videoWan2gpI2vPreset || wan2gpVideoDefaults.i2vPreset, 'i2v'),
    [config.videoWan2gpI2vPreset, wan2gpVideoDefaults.i2vPreset, resolveWan2gpVideoPreset]
  )
  const activeWan2gpVideoPreset = useFirstFrameRef
    ? selectedWan2gpVideoI2vPreset
    : selectedWan2gpVideoT2vPreset

  const wan2gpVideoResolutionOptions = useMemo(
    () => activeWan2gpVideoPreset?.supported_resolutions?.length
      ? activeWan2gpVideoPreset.supported_resolutions
      : [activeWan2gpVideoPreset?.default_resolution || wan2gpVideoDefaults.resolution],
    [activeWan2gpVideoPreset, wan2gpVideoDefaults.resolution]
  )
  const wan2gpVideoResolutionChoices = useMemo(
    () => getWan2gpResolutionChoices(wan2gpVideoResolutionOptions),
    [wan2gpVideoResolutionOptions]
  )
  const wan2gpVideoResolutionTiers = useMemo(
    () => getWan2gpResolutionTiers(wan2gpVideoResolutionChoices),
    [wan2gpVideoResolutionChoices]
  )

  const effectiveWan2gpVideoResolution = useMemo(() => {
    if (config.videoWan2gpResolution && wan2gpVideoResolutionOptions.includes(config.videoWan2gpResolution)) {
      return config.videoWan2gpResolution
    }
    return activeWan2gpVideoPreset?.default_resolution || wan2gpVideoResolutionOptions[0] || wan2gpVideoDefaults.resolution
  }, [config.videoWan2gpResolution, wan2gpVideoResolutionOptions, activeWan2gpVideoPreset, wan2gpVideoDefaults.resolution])

  const effectiveWan2gpVideoResolutionTier = useMemo(
    () => wan2gpVideoResolutionChoices.find((choice) => choice.value === effectiveWan2gpVideoResolution)?.tier
      || wan2gpVideoResolutionTiers[0] || '720p',
    [wan2gpVideoResolutionChoices, effectiveWan2gpVideoResolution, wan2gpVideoResolutionTiers]
  )
  const videoTierResolutionChoices = useMemo(
    () => wan2gpVideoResolutionChoices.filter((choice) => choice.tier === effectiveWan2gpVideoResolutionTier),
    [wan2gpVideoResolutionChoices, effectiveWan2gpVideoResolutionTier]
  )

  const effectiveWan2gpVideoSteps = useMemo(() => {
    if (typeof config.videoWan2gpInferenceSteps === 'number' && config.videoWan2gpInferenceSteps > 0) {
      return config.videoWan2gpInferenceSteps
    }
    return activeWan2gpVideoPreset?.inference_steps
      || selectedWan2gpVideoT2vPreset?.inference_steps
      || selectedWan2gpVideoI2vPreset?.inference_steps
      || wan2gpVideoDefaults.inferenceSteps
  }, [config.videoWan2gpInferenceSteps, activeWan2gpVideoPreset, selectedWan2gpVideoT2vPreset, selectedWan2gpVideoI2vPreset, wan2gpVideoDefaults.inferenceSteps])

  const wan2gpVideoSlidingWindowConfig = useMemo(() => {
    const defaultValue = activeWan2gpVideoPreset?.sliding_window_size
    const minValue = activeWan2gpVideoPreset?.sliding_window_size_min
    const maxValue = activeWan2gpVideoPreset?.sliding_window_size_max
    const stepValue = activeWan2gpVideoPreset?.sliding_window_size_step
    if (
      typeof defaultValue !== 'number' || defaultValue <= 0
      || typeof minValue !== 'number' || minValue <= 0
      || typeof maxValue !== 'number' || maxValue < minValue
    ) {
      return null
    }
    return {
      defaultValue,
      minValue,
      maxValue,
      stepValue: typeof stepValue === 'number' && stepValue > 0 ? stepValue : 1,
    }
  }, [activeWan2gpVideoPreset])

  const effectiveWan2gpVideoSlidingWindowSize = useMemo(() => {
    if (!wan2gpVideoSlidingWindowConfig) return undefined
    const configuredValue = config.videoWan2gpSlidingWindowSize
    if (
      typeof configuredValue === 'number'
      && configuredValue >= wan2gpVideoSlidingWindowConfig.minValue
      && configuredValue <= wan2gpVideoSlidingWindowConfig.maxValue
    ) {
      return configuredValue
    }
    return wan2gpVideoSlidingWindowConfig.defaultValue
  }, [config.videoWan2gpSlidingWindowSize, wan2gpVideoSlidingWindowConfig])

  const wan2gpVideoSingleWindowDurationHint = useMemo(() => {
    if (
      !wan2gpVideoSlidingWindowConfig
      || effectiveWan2gpVideoSlidingWindowSize === undefined
      || typeof activeWan2gpVideoPreset?.frames_per_second !== 'number'
      || activeWan2gpVideoPreset.frames_per_second <= 0
    ) {
      return ''
    }
    const fps = activeWan2gpVideoPreset.frames_per_second
    const seconds = effectiveWan2gpVideoSlidingWindowSize / fps
    const roundedSeconds = seconds >= 10
      ? seconds.toFixed(1)
      : seconds.toFixed(2)
    return `当前设置下，单窗最长约 ${roundedSeconds} 秒（${effectiveWan2gpVideoSlidingWindowSize} 帧 @ ${fps} fps）；超过后会触发滑窗。`
  }, [
    activeWan2gpVideoPreset,
    effectiveWan2gpVideoSlidingWindowSize,
    wan2gpVideoSlidingWindowConfig,
  ])

  const videoRuntimeOptions = useMemo<ProviderModelOption[]>(() => [
    ...(
      videoProviders.includes('vertex_ai')
        ? VERTEX_VIDEO_MODELS
          .filter((model) => {
            if (isSingleTakeEnabled && !model.supportsLastFrame) {
              return false
            }
            if (useFirstFrameRef && useReferenceImageRef) {
              return model.supportsReferenceImage && model.supportsCombinedReference
            }
            if (useReferenceImageRef) {
              return model.supportsReferenceImage
            }
            return true
          })
          .map((model) => ({
            value: makeProviderModelValue('vertex_ai', model.id),
            provider: 'vertex_ai',
            model: model.id,
            label: buildProviderModelLabel('vertex_ai', model.label, 'Vertex AI'),
            restrictions: useReferenceImageRef ? [...(model.referenceRestrictions || [])] : undefined,
          }))
        : []
    ),
    ...(
      videoProviders.includes('volcengine_seedance')
        ? SEEDANCE_MODEL_PRESETS
          .filter((preset) => {
            if (isSingleTakeEnabled && !preset.supportsLastFrame) {
              return false
            }
            if (useFirstFrameRef && useReferenceImageRef) {
              return false
            }
            if (useReferenceImageRef) {
              return preset.supportsReferenceImage
            }
            return useFirstFrameRef ? preset.supportsI2v : preset.supportsT2v
          })
          .map((preset) => ({
            value: makeProviderModelValue('volcengine_seedance', preset.id),
            provider: 'volcengine_seedance',
            model: preset.id,
            label: buildProviderModelLabel('volcengine_seedance', preset.label, '火山引擎'),
            description: preset.description,
            restrictions: useReferenceImageRef ? [...(preset.referenceRestrictions || [])] : undefined,
          }))
        : []
    ),
    ...(
      videoProviders.includes('kling') && !useReferenceImageRef
        ? [{
            value: makeProviderModelValue('kling', klingVideoDefaults.model || 'kling-v3'),
            provider: 'kling',
            model: klingVideoDefaults.model || 'kling-v3',
            label: buildProviderModelLabel('kling', klingVideoDefaults.model || 'kling-v3', '可灵'),
          }]
        : []
    ),
    ...(
      videoProviders.includes('vidu') && !useReferenceImageRef
        ? enabledViduVideoModels.map((modelId) => ({
            value: makeProviderModelValue('vidu', modelId),
            provider: 'vidu',
            model: modelId,
            label: buildProviderModelLabel('vidu', modelId, 'Vidu'),
          }))
        : []
    ),
    ...(
      videoProviders.includes('wan2gp') && !useReferenceImageRef
        ? (useFirstFrameRef ? wan2gpVideoI2vPresets : wan2gpVideoT2vPresets)
          .filter((preset) => !isSingleTakeEnabled || preset.supports_last_frame !== false)
          .map((preset) => ({
            value: makeProviderModelValue('wan2gp', preset.id),
            provider: 'wan2gp',
            model: preset.id,
            label: buildProviderModelLabel('wan2gp', preset.display_name, 'Wan2GP'),
            description: preset.description,
          }))
        : []
    ),
  ], [
    enabledViduVideoModels,
    klingVideoDefaults.model,
    videoProviders,
    isSingleTakeEnabled,
    useFirstFrameRef,
    useReferenceImageRef,
    wan2gpVideoI2vPresets,
    wan2gpVideoT2vPresets,
  ])

  const defaultVideoProviderByMode = useMemo(() => {
    const rawBinding = String(
      useFirstFrameRef
        ? settings?.default_video_i2v_model
        : settings?.default_video_t2v_model
    ).trim()
    if (!rawBinding) return ''
    const separatorIndex = rawBinding.indexOf('::')
    if (separatorIndex <= 0) return ''
    const provider = rawBinding.slice(0, separatorIndex).trim()
    return videoProviders.includes(provider) ? provider : ''
  }, [settings, useFirstFrameRef, videoProviders])

  const effectiveVideoProvider = useMemo(() => {
    if (config.videoProvider && videoProviders.includes(config.videoProvider)) {
      return config.videoProvider
    }
    if (defaultVideoProviderByMode) {
      return defaultVideoProviderByMode
    }
    if (settings?.default_video_provider && videoProviders.includes(settings.default_video_provider)) {
      return settings.default_video_provider
    }
    return videoProviders[0] || ''
  }, [config.videoProvider, defaultVideoProviderByMode, videoProviders, settings])

  const currentVideoModelValue = useMemo(() => {
    if (effectiveVideoProvider === 'wan2gp') {
      return makeProviderModelValue(
        'wan2gp',
        useFirstFrameRef
          ? (config.videoWan2gpI2vPreset || wan2gpVideoDefaults.i2vPreset)
          : (config.videoWan2gpT2vPreset || wan2gpVideoDefaults.t2vPreset)
      )
    }
    const preferredVideoModel = String(
      useFirstFrameRef
        ? (config.videoModelI2v || '')
        : (config.videoModel || '')
    ).trim()
    if (effectiveVideoProvider === 'volcengine_seedance') {
      return makeProviderModelValue('volcengine_seedance', preferredVideoModel || seedanceVideoDefaults.model)
    }
    if (effectiveVideoProvider === 'kling') {
      return makeProviderModelValue('kling', preferredVideoModel || klingVideoDefaults.model)
    }
    if (effectiveVideoProvider === 'vidu') {
      return makeProviderModelValue('vidu', preferredVideoModel || viduVideoDefaults.model)
    }
    return makeProviderModelValue('vertex_ai', preferredVideoModel || vertexVideoDefaults.model)
  }, [
    effectiveVideoProvider,
    useFirstFrameRef,
    config.videoWan2gpI2vPreset,
    config.videoWan2gpT2vPreset,
    config.videoModelI2v,
    config.videoModel,
    wan2gpVideoDefaults,
    seedanceVideoDefaults.model,
    klingVideoDefaults.model,
    viduVideoDefaults.model,
    vertexVideoDefaults.model,
  ])

  const effectiveVideoRuntimeValue = useMemo(
    () => videoRuntimeOptions.some((item) => item.value === currentVideoModelValue)
      ? currentVideoModelValue
      : (videoRuntimeOptions[0]?.value || currentVideoModelValue),
    [videoRuntimeOptions, currentVideoModelValue]
  )
  const selectedVideoRuntimeOption = useMemo(
    () => videoRuntimeOptions.find((item) => item.value === effectiveVideoRuntimeValue),
    [videoRuntimeOptions, effectiveVideoRuntimeValue]
  )
  const runtimeVideoProvider = selectedVideoRuntimeOption?.provider || effectiveVideoProvider
  const isWan2gpVideoProvider = runtimeVideoProvider === 'wan2gp'
  const runtimeVideoDefaults = runtimeVideoProvider === 'volcengine_seedance'
    ? getSeedanceVideoDefaults(settings, videoModelMode)
    : (
      runtimeVideoProvider === 'kling'
        ? getKlingVideoDefaults(settings, videoModelMode)
        : (
          runtimeVideoProvider === 'vidu'
            ? getViduVideoDefaults(settings, videoModelMode)
            : getVertexVideoDefaults(settings, videoModelMode)
        )
    )
  const runtimeVideoAspectRatios = runtimeVideoProvider === 'volcengine_seedance'
    ? SEEDANCE_ASPECT_RATIOS
    : (
      runtimeVideoProvider === 'kling'
        ? [...KLING_VIDEO_ASPECT_RATIOS]
        : (runtimeVideoProvider === 'vidu' ? [...VIDU_VIDEO_ASPECT_RATIOS] : VIDEO_ASPECT_RATIOS)
    )
  const runtimeVideoResolutions = runtimeVideoProvider === 'volcengine_seedance'
    ? SEEDANCE_RESOLUTIONS
    : (
      runtimeVideoProvider === 'kling'
        ? [...KLING_VIDEO_RESOLUTIONS]
        : (runtimeVideoProvider === 'vidu' ? [...VIDU_VIDEO_RESOLUTIONS] : VIDEO_RESOLUTIONS)
    )
  const effectiveVideoAspectRatio = runtimeVideoAspectRatios.includes(config.videoAspectRatio || '')
    ? (config.videoAspectRatio || '')
    : runtimeVideoDefaults.aspectRatio
  const effectiveVideoResolution = runtimeVideoResolutions.includes(config.resolution || '')
    ? (config.resolution || '')
    : runtimeVideoDefaults.resolution
  const videoRestrictionLines = selectedVideoRuntimeOption?.restrictions || []
  const hasVideoModelOptions = videoRuntimeOptions.length > 0

  return (
    <>
      <div className="space-y-3">
        <h4 className={SECTION_TITLE_CLASS}>文本生成</h4>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 [&>*]:min-w-0">
          <div className="space-y-2">
            <Label>分镜镜头密度</Label>
            <Select
              value={config.storyboardShotDensity || 'medium'}
              onValueChange={(v) => updateConfig({ storyboardShotDensity: v as 'low' | 'medium' | 'high' })}
            >
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {STORYBOARD_SHOT_DENSITIES.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}：{item.hint}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {renderLLMOptions()}
          <div className="space-y-2">
            <Label>生成提示词目标语言</Label>
            <Select
              value={config.textTargetLanguage || 'zh'}
              onValueChange={(v) => updateConfig({ textTargetLanguage: v as 'zh' | 'en' })}
            >
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {TEXT_TARGET_LANGUAGES.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>生成提示词复杂度</Label>
            <Select
              value={config.textPromptComplexity || 'normal'}
              onValueChange={(v) => updateConfig({ textPromptComplexity: v as 'minimal' | 'simple' | 'normal' | 'detailed' | 'complex' | 'ultra' })}
            >
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {TEXT_PROMPT_COMPLEXITIES.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      <div className="border-t pt-4 mt-4 space-y-3">
        <h4 className={SECTION_TITLE_CLASS}>首帧图设置</h4>
        <div className="flex items-center space-x-2">
          <Checkbox
            id="useReferenceConsistency"
            checked={config.useReferenceConsistency ?? false}
            onCheckedChange={(checked) => handleUseReferenceConsistencyChange(!!checked)}
            disabled={!hasReferenceData}
          />
          <Label
            htmlFor="useReferenceConsistency"
            className={cn(
              "cursor-pointer",
              !hasReferenceData && "text-muted-foreground"
            )}
          >
            保持参考一致性
          </Label>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="inline-flex h-4 w-4 items-center justify-center rounded-full border text-[10px] text-muted-foreground hover:text-foreground"
                aria-label="保持参考一致性说明"
              >
                ?
              </button>
            </TooltipTrigger>
            <TooltipContent side="top">
              <div className="text-xs leading-relaxed max-w-[320px]">
                开启后会优先基于参考图进行首帧图生成。Wan2GP 会自动切换到 i2i 预设并使用该模型支持的分辨率/宽高比范围与默认推理步数；如果某个分镜实际没有拿到参考图，则会优先回退为当前模型的 t2i 方式生成，若该模型不支持 t2i，再回退到设置页中的 Wan2GP 文生图模型。
              </div>
            </TooltipContent>
          </Tooltip>
        </div>
        {!hasReferenceData && (
          <p className="text-xs text-muted-foreground">
            需先生成参考描述和参考图像才能启用
          </p>
        )}
        {isSettingsLoading ? (
          <div className="text-sm text-muted-foreground">加载配置中...</div>
        ) : videoImageProviders.length === 0 ? (
          renderNoConfigWarning('Image')
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 [&>*]:min-w-0">
              <div className="space-y-2">
                <Label>图像模型</Label>
                <Select
                  value={effectiveFrameRuntimeValue}
                  onValueChange={(value) => handleImageRuntimeModelChange(value, 'frame')}
                >
                  <SelectTrigger><SelectValue placeholder="选择模型" /></SelectTrigger>
                  <SelectContent>
                    {frameRuntimeOptions.map((item) => (
                      <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>图像风格</Label>
                <Select
                  value={config.imageStyle?.trim() ? config.imageStyle : '__none__'}
                  onValueChange={(v) => updateConfig({ imageStyle: v === '__none__' ? '' : v })}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {IMAGE_STYLES.map((s) => <SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            </div>
            {effectiveVideoImageProvider === 'wan2gp' ? (
              <div className="grid grid-cols-2 gap-3 [&>*]:min-w-0">
                {activeWan2gpPreset?.description && (
                  <p className="text-xs text-muted-foreground col-span-2">{activeWan2gpPreset.description}</p>
                )}
                {activeWan2gpPreset && (
                  <p className="text-xs text-amber-600 col-span-2">
                    {getWan2gpPromptLanguageHint(
                      '当前模型',
                      activeWan2gpPreset.prompt_language_preference,
                      activeWan2gpPreset.supports_chinese
                    )}
                  </p>
                )}
                {isDreamOmni2Preset && (
                  <p className="text-xs text-amber-600 col-span-2">
                    提示：多模态前处理链路，编码较慢。
                  </p>
                )}
                <div className="space-y-2">
                  <Label>分辨率档位</Label>
                  <Select
                    value={effectiveWan2gpResolutionTier}
                    onValueChange={(tier) => handleWan2gpResolutionTierChange(wan2gpResolutionChoices, tier, 'frameImageResolution')}
                  >
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {wan2gpResolutionTiers.map((tier) => (
                        <SelectItem key={tier} value={tier}>{tier}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>宽高比</Label>
                  <Select
                    value={effectiveWan2gpResolution}
                    onValueChange={(v) => updateConfig({ frameImageResolution: v })}
                  >
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {tierResolutionChoices.map((resolution) => (
                        <SelectItem key={resolution.value} value={resolution.value}>
                          {resolution.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2 md:col-span-2">
                  <Label>
                    推理步数 ({effectiveWan2gpSteps})
                  </Label>
                  <Slider
                    value={[effectiveWan2gpSteps]}
                    onValueChange={(v) => updateConfig(
                      usingI2iPreset
                        ? { imageWan2gpInferenceStepsI2i: v[0] }
                        : { imageWan2gpInferenceStepsT2i: v[0] }
                    )}
                    min={1}
                    max={100}
                    step={1}
                    className="mt-2"
                  />
                </div>
              </div>
            ) : (
              <>
                <div className="grid grid-cols-2 gap-3 [&>*]:min-w-0">
                  <div className="space-y-2">
                    <Label>图片宽高比</Label>
                    <Select
                      value={effectiveFrameAspectRatio}
                      onValueChange={(v) => updateConfig({ frameAspectRatio: v })}
                    >
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {frameAspectRatioOptions.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>图片分辨率</Label>
                    <Select
                      value={effectiveFrameImageSize}
                      onValueChange={(v) => updateConfig({ frameImageSize: v })}
                    >
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {frameSizeOptions.map((s) => (
                          <SelectItem key={s} value={s}>{formatImageSizeLabel(s)}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </>
            )}
            {effectiveVideoImageProvider !== 'wan2gp' && (
              <div className="space-y-2 w-full md:w-1/2">
                <Label>并发数</Label>
                <Select
                  value={String(config.maxConcurrency || 4)}
                  onValueChange={(v) => updateConfig({ maxConcurrency: parseInt(v) })}
                >
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {CONCURRENCY_OPTIONS.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            )}
          </>
        )}
      </div>

      <div className="border-t pt-4 mt-4 space-y-3">
        <h4 className={SECTION_TITLE_CLASS}>视频设置</h4>
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center space-x-2">
            <Checkbox
              id="singleTake"
              checked={isSingleTakeEnabled}
              onCheckedChange={(checked) => handleSingleTakeChange(!!checked)}
              disabled={isSingleTakeForcedByMode}
            />
            <div className="flex items-center gap-2">
              <Label
                htmlFor="singleTake"
                className={cn('cursor-pointer', isSingleTakeForcedByMode && 'text-muted-foreground')}
              >
                一镜到底
              </Label>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    className="inline-flex h-4 w-4 items-center justify-center rounded-full border text-[10px] text-muted-foreground hover:text-foreground"
                    aria-label="一镜到底尾帧说明"
                  >
                    ?
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top">
                  <div className="text-xs leading-relaxed max-w-[320px]">
                    一镜到底下，尾帧会自动判定：若当前分镜和下一分镜都已有首帧图，则优先使用“下一分镜首帧”作为当前分镜尾帧，此时不同分镜的视频生成任务可并行；否则需等待上一分镜生成完成并截取尾帧后再继续，任务只能串行。
                  </div>
                </TooltipContent>
              </Tooltip>
            </div>
          </div>
          <div className="flex items-center space-x-2">
            <Checkbox
              id="useFirstFrameRef"
              checked={effectiveUseFirstFrameRef}
              onCheckedChange={(checked) => handleUseFirstFrameRefChange(!!checked)}
              disabled={isSingleTakeEnabled}
            />
            <Label
              htmlFor="useFirstFrameRef"
              className={cn('cursor-pointer', isSingleTakeEnabled && 'text-muted-foreground')}
            >
              使用首帧图
            </Label>
          </div>
          <div className="flex items-center space-x-2">
            <Checkbox
              id="useReferenceImageRef"
              checked={config.useReferenceImageRef ?? false}
              onCheckedChange={(checked) => handleUseReferenceImageRefChange(!!checked)}
            />
            <Label htmlFor="useReferenceImageRef" className="cursor-pointer">借鉴参考图</Label>
          </div>
        </div>
        {isSingleTakeForcedByMode && (
          <p className="text-xs text-amber-600">
            双人播客模式默认开启「一镜到底」，并会自动强制开启「使用首帧图」。
          </p>
        )}
        {isSettingsLoading ? (
          <div className="text-sm text-muted-foreground">加载配置中...</div>
        ) : videoProviders.length === 0 ? (
          renderNoConfigWarning('Video')
        ) : !hasVideoModelOptions ? (
          <Alert>
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              当前筛选条件没有可用模型。请去掉部分参考选项（目前暂无同时支持首帧图+ 参考图的模型）。
            </AlertDescription>
          </Alert>
        ) : (
          <>
            <div className="space-y-2">
              <Label>视频模型</Label>
              <Select
                value={effectiveVideoRuntimeValue}
                onValueChange={handleVideoRuntimeModelChange}
              >
                <SelectTrigger><SelectValue placeholder="选择模型" /></SelectTrigger>
                <SelectContent>
                  {videoRuntimeOptions.map((item) => (
                    <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedVideoRuntimeOption?.description && (
                <p className="text-xs text-muted-foreground">{selectedVideoRuntimeOption.description}</p>
              )}
            </div>
            {videoRestrictionLines.length > 0 && (
              <div className="rounded-md border border-amber-300/60 bg-amber-50/40 px-3 py-2 text-xs text-amber-900">
                {videoRestrictionLines.join('；')}
              </div>
            )}
            {isWan2gpVideoProvider ? (
              <div className="grid grid-cols-2 gap-3 [&>*]:min-w-0">
                {activeWan2gpVideoPreset && (
                  <p className="text-xs text-amber-600 col-span-2">
                    {getWan2gpPromptLanguageHint(
                      '当前模型',
                      activeWan2gpVideoPreset.prompt_language_preference,
                      activeWan2gpVideoPreset.supports_chinese
                    )}
                  </p>
                )}
                <div className="space-y-2">
                  <Label>分辨率档位</Label>
                  <Select
                    value={effectiveWan2gpVideoResolutionTier}
                    onValueChange={(tier) => handleWan2gpVideoResolutionTierChange(wan2gpVideoResolutionChoices, tier)}
                  >
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {wan2gpVideoResolutionTiers.map((tier) => (
                        <SelectItem key={tier} value={tier}>{tier}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>宽高比</Label>
                  <Select
                    value={effectiveWan2gpVideoResolution}
                    onValueChange={(value) => updateConfig({ videoWan2gpResolution: value })}
                  >
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {videoTierResolutionChoices.map((item) => (
                        <SelectItem key={item.value} value={item.value}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2 col-span-2">
                  <Label>推理步数 ({effectiveWan2gpVideoSteps})</Label>
                  <Slider
                    value={[effectiveWan2gpVideoSteps]}
                    onValueChange={(v) => updateConfig({ videoWan2gpInferenceSteps: v[0] })}
                    min={1}
                    max={100}
                    step={1}
                    className="mt-2"
                  />
                </div>
                {wan2gpVideoSlidingWindowConfig && effectiveWan2gpVideoSlidingWindowSize !== undefined && (
                  <div className="space-y-2 col-span-2">
                    <div className="flex items-center gap-2">
                      <Label>滑窗大小 ({effectiveWan2gpVideoSlidingWindowSize} 帧)</Label>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <button
                            type="button"
                            className="inline-flex h-4 w-4 items-center justify-center rounded-full border text-[10px] text-muted-foreground hover:text-foreground"
                            aria-label="滑窗大小说明"
                          >
                            ?
                          </button>
                        </TooltipTrigger>
                        <TooltipContent side="top">
                          <div className="max-w-[320px] text-xs leading-relaxed">
                            当总帧数超过滑窗大小时，Wan2GP 会自动分多窗生成并拼接。窗口越大，越不容易触发滑窗，但显存和内存压力也更高。当前模型默认值为 {wan2gpVideoSlidingWindowConfig.defaultValue} 帧。
                          </div>
                        </TooltipContent>
                      </Tooltip>
                    </div>
                    <Slider
                      value={[effectiveWan2gpVideoSlidingWindowSize]}
                      onValueChange={(v) => updateConfig({ videoWan2gpSlidingWindowSize: v[0] })}
                      min={wan2gpVideoSlidingWindowConfig.minValue}
                      max={wan2gpVideoSlidingWindowConfig.maxValue}
                      step={wan2gpVideoSlidingWindowConfig.stepValue}
                      className="mt-2"
                    />
                    {wan2gpVideoSingleWindowDurationHint && (
                      <p className="text-xs text-muted-foreground">
                        {wan2gpVideoSingleWindowDurationHint}
                      </p>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <>
                <div className="grid grid-cols-2 gap-3 [&>*]:min-w-0">
                  <div className="space-y-2">
                    <Label>视频宽高比</Label>
                    <Select
                      value={effectiveVideoAspectRatio}
                      onValueChange={(v) => updateConfig({ videoAspectRatio: v })}
                    >
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {runtimeVideoAspectRatios.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>视频分辨率</Label>
                    <Select
                      value={effectiveVideoResolution}
                      onValueChange={(v) => updateConfig({ resolution: v })}
                    >
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {runtimeVideoResolutions.map((r) => (
                          <SelectItem key={r} value={r}>
                            {runtimeVideoProvider === 'volcengine_seedance' || r.endsWith('p') ? r : `${r}p`}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div className="space-y-2 w-full md:w-1/2">
                  <div className="flex items-center gap-2">
                    <Label>并发数</Label>
                    {isSingleTakeEnabled && (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <button
                            type="button"
                            className="inline-flex h-4 w-4 items-center justify-center rounded-full border text-[10px] text-muted-foreground hover:text-foreground"
                            aria-label="一镜到底并发说明"
                          >
                            ?
                          </button>
                        </TooltipTrigger>
                        <TooltipContent side="top">
                          <div className="text-xs leading-relaxed max-w-[300px]">
                            一镜到底会自动判定调度方式：非最后分镜若当前和下一分镜都已有首帧，则按首尾帧方式可并发；最后分镜有首帧可并发；其余情况需等待上一分镜完成并截取尾帧后再生成。
                          </div>
                        </TooltipContent>
                      </Tooltip>
                    )}
                  </div>
                  <Select
                    value={String(config.maxConcurrency || 2)}
                    onValueChange={(v) => updateConfig({ maxConcurrency: parseInt(v) })}
                  >
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {CONCURRENCY_OPTIONS.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              </>
            )}
          </>
        )}
      </div>
    </>
  )
}
