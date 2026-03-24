'use client'

import { useMemo, useCallback, useState } from 'react'
import { Loader2, AlertCircle } from 'lucide-react'
import Link from 'next/link'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Progress } from '@/components/ui/progress'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useSettingsBundle } from '@/hooks/use-settings-queries'
import {
  getWan2gpResolutionChoices,
  pickDefaultResolutionForTier,
} from '@/lib/wan2gp'
import {
  SEEDANCE_MODEL_PRESETS,
} from '@/lib/seedance'
import {
  SECTION_TITLE_CLASS,
  buildFinalVideoDownloadName,
  getConfiguredImageProviders,
  getConfiguredLLMProviders,
  getImageDefaults,
  getImageModelDefault,
  getWan2gpDefaults,
  getWan2gpPresetById,
  getWan2gpVideoPresetById,
  isWan2gpT2iPreset,
  isWan2gpI2iPreset,
  getVertexVideoDefaults,
  getSeedanceVideoDefaults,
  getKlingVideoDefaults,
  getViduVideoDefaults,
  getWan2gpVideoDefaults,
  makeProviderModelValue,
  parseProviderModelValue,
  buildProviderModelLabel,
  getImageSizeOptionsByProviderTypeAndModel,
  getImageAspectRatioOptionsByProviderTypeAndModel,
} from '@/lib/stage-panel-helpers'
import type { ProviderModelOption } from '@/lib/stage-panel-helpers'
import type {
  ImageProviderConfig,
  Wan2gpImagePreset,
  Wan2gpVideoPreset,
} from '@/types/settings'
import type { StageConfig, StageStatus, TabType } from '@/types/stage-panel'

import { StageShotsConfig } from '@/components/project/stage-shots-config'
import { StagePanelScriptTab } from '@/components/project/stage-panel-script-tab'
import { StagePanelComposeTab } from '@/components/project/stage-panel-compose-tab'
import { StagePanelActionButtons } from '@/components/project/stage-panel-action-buttons'
import type { BackendStageType } from '@/types/stage'

const TAB_OPTIONS: Array<{ value: TabType; label: string }> = [
  { value: 'script', label: '脚本' },
  { value: 'shots', label: '分镜' },
  { value: 'compose', label: '合成' },
]

interface StagePanelProps {
  activeTab: TabType
  onTabChange: (tab: TabType) => void
  stageStatus: StageStatus
  isRunning: boolean
  runningStage?: BackendStageType
  runningAction?: string
  progress: number
  progressMessage?: string
  completedItems?: number
  totalItems?: number
  skippedItems?: number
  isCancelling?: boolean
  onCancelAllRunningTasks?: () => void
  onRunStage: (stage: BackendStageType, config: StageConfig, inputData?: Record<string, unknown>) => void
  config: StageConfig
  onConfigChange: (config: StageConfig) => void
  hasReferenceData?: boolean
  isReferenceImageComplete?: boolean
  hasVideoPromptReady?: boolean
  projectTitle?: string
  composeVideoUrl?: string
  composeVideoShots?: Array<{ width?: number; height?: number }>
  contentScriptMode?: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'
  onSingleTakeModeTransition?: (params: {
    nextEnabled: boolean
    reason: 'toggle' | 'duo_mode'
  }) => Promise<boolean> | boolean
  onNarratorStyleChange?: (nextStyle: string, prevStyle: string) => void
}
export function StagePanel({
  activeTab,
  onTabChange,
  stageStatus,
  isRunning,
  runningStage,
  runningAction,
  progress,
  progressMessage,
  completedItems,
  totalItems,
  skippedItems,
  isCancelling = false,
  onCancelAllRunningTasks,
  onRunStage,
  config,
  onConfigChange,
  hasReferenceData = false,
  isReferenceImageComplete = false,
  hasVideoPromptReady = false,
  projectTitle,
  composeVideoUrl,
  composeVideoShots = [],
  contentScriptMode,
  onSingleTakeModeTransition,
  onNarratorStyleChange,
}: StagePanelProps) {
  const [isExportingVideo, setIsExportingVideo] = useState(false)
  const normalizedProgressMessage = (progressMessage || (progress > 0 ? '生成中...' : '准备中...'))
    .replace(/\s*[（(]\d+%[）)]\s*/g, '')
    .trim()

  const {
    settings,
    isSettingsLoading,
    wan2gpImagePresets,
    wan2gpVideoPresetData,
  } = useSettingsBundle({
    includeWan2gpVideoPresets: true,
  })
  const wan2gpPresets = useMemo<Wan2gpImagePreset[]>(
    () => wan2gpImagePresets,
    [wan2gpImagePresets]
  )
  const wan2gpVideoT2vPresets = useMemo<Wan2gpVideoPreset[]>(
    () => wan2gpVideoPresetData?.t2v_presets ?? [],
    [wan2gpVideoPresetData?.t2v_presets]
  )
  const wan2gpVideoI2vPresets = useMemo<Wan2gpVideoPreset[]>(
    () => wan2gpVideoPresetData?.i2v_presets ?? [],
    [wan2gpVideoPresetData?.i2v_presets]
  )

  const updateConfig = useCallback((updates: Partial<StageConfig>) => {
    onConfigChange({ ...config, ...updates })
  }, [config, onConfigChange])

  const resolveScriptMode = useCallback((): 'custom' | 'single' | 'duo_podcast' | 'dialogue_script' => {
    const value = String(config.scriptMode || contentScriptMode || 'single').trim()
    if (value === 'custom' || value === 'duo_podcast' || value === 'dialogue_script' || value === 'single') {
      return value
    }
    return 'single'
  }, [config.scriptMode, contentScriptMode])
  const effectiveScriptMode = resolveScriptMode()
  const isSingleTakeForcedByMode = effectiveScriptMode === 'duo_podcast'
  const isSingleTakeEnabled = (config.singleTake ?? false) || isSingleTakeForcedByMode
  const effectiveUseFirstFrameRef = isSingleTakeEnabled ? true : (config.useFirstFrameRef ?? true)
  const effectiveComposeVideoFitMode: 'truncate' | 'scale' | 'none' = isSingleTakeEnabled
    ? 'scale'
    : (config.videoFitMode || 'truncate')

  const handleSingleTakeChange = useCallback((checked: boolean) => {
    if (!checked && isSingleTakeForcedByMode) {
      toast.info('双人播客模式下已强制开启一镜到底')
      return
    }
    if (checked === isSingleTakeEnabled) return
    void (async () => {
      if (checked) {
        const proceed = onSingleTakeModeTransition
          ? await onSingleTakeModeTransition({ nextEnabled: true, reason: 'toggle' })
          : true
        if (!proceed) return
      }
      updateConfig({
        singleTake: checked,
        ...(checked ? { useFirstFrameRef: true } : {}),
      })
    })()
  }, [
    isSingleTakeEnabled,
    isSingleTakeForcedByMode,
    onSingleTakeModeTransition,
    updateConfig,
  ])

  const handleExportVideo = useCallback(async () => {
    if (!composeVideoUrl || isExportingVideo) return

    const exportName = buildFinalVideoDownloadName(composeVideoUrl, projectTitle)
    setIsExportingVideo(true)
    try {
      const response = await fetch(composeVideoUrl, { method: 'GET' })
      if (!response.ok) {
        throw new Error(`Export failed with status ${response.status}`)
      }

      const blob = await response.blob()
      const objectUrl = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = objectUrl
      link.download = exportName
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
      toast.success('已开始下载视频')
    } catch (error) {
      console.error('Failed to export final video:', error)
      toast.error('视频导出失败，已为你打开视频链接')
      window.open(composeVideoUrl, '_blank', 'noopener,noreferrer')
    } finally {
      setIsExportingVideo(false)
    }
  }, [composeVideoUrl, isExportingVideo, projectTitle])

  const getConfiguredLLMProviders_ = () => getConfiguredLLMProviders(settings)
  const getConfiguredImageProviders_ = () => getConfiguredImageProviders(settings)

  const getImageProviderById = useCallback((providerId: string): ImageProviderConfig | undefined => {
    return (settings?.image_providers || []).find((provider) => provider.id === providerId)
  }, [settings?.image_providers])

  const getImageSizeOptionsByProviderModel = useCallback((providerId: string | undefined, model: string | undefined): string[] => {
    if (!providerId || providerId === 'wan2gp') {
      return getImageSizeOptionsByProviderTypeAndModel(undefined, model)
    }
    const configuredProvider = getImageProviderById(providerId)
    return getImageSizeOptionsByProviderTypeAndModel(configuredProvider?.provider_type, model)
  }, [getImageProviderById])

  const getImageAspectRatioOptionsByProviderModel = useCallback((providerId: string | undefined, model: string | undefined): string[] => {
    if (!providerId || providerId === 'wan2gp') {
      return getImageAspectRatioOptionsByProviderTypeAndModel(undefined, model)
    }
    const configuredProvider = getImageProviderById(providerId)
    return getImageAspectRatioOptionsByProviderTypeAndModel(configuredProvider?.provider_type, model)
  }, [getImageProviderById])

  const resolveEffectiveImageProvider = useCallback((providers: string[]): string => {
    if (config.imageProvider && providers.includes(config.imageProvider)) {
      return config.imageProvider
    }
    if (settings?.default_image_provider && providers.includes(settings.default_image_provider)) {
      return settings.default_image_provider
    }
    return providers[0] || ''
  }, [config.imageProvider, settings])

  const wan2gpT2iPresets = useMemo(
    () => wan2gpPresets.filter((preset) => isWan2gpT2iPreset(preset)),
    [wan2gpPresets]
  )
  const wan2gpI2iPresets = useMemo(
    () => wan2gpPresets.filter((preset) => isWan2gpI2iPreset(preset)),
    [wan2gpPresets]
  )

  const resolveWan2gpPreset = useCallback((
    presetId: string,
    presetType: 't2i' | 'i2i'
  ): Wan2gpImagePreset | undefined => {
    const source = presetType === 'i2i' ? wan2gpI2iPresets : wan2gpT2iPresets
    return getWan2gpPresetById(source, presetId) || source[0]
  }, [wan2gpI2iPresets, wan2gpT2iPresets])

  const handleWan2gpResolutionTierChange = useCallback((
    choices: ReturnType<typeof getWan2gpResolutionChoices>,
    tier: string,
    field: 'referenceImageResolution' | 'frameImageResolution'
  ) => {
    const nextResolution = pickDefaultResolutionForTier(choices, tier)
    if (nextResolution) {
      updateConfig({ [field]: nextResolution } as Partial<StageConfig>)
    }
  }, [updateConfig])

  const handleUseReferenceConsistencyChange = useCallback((checked: boolean) => {
    const defaults = getWan2gpDefaults(settings)
    const nextUpdates: Partial<StageConfig> = {
      useReferenceConsistency: checked,
    }
    if ((config.imageProvider || settings?.default_image_provider) === 'wan2gp') {
      const presetId = checked
        ? (config.imageWan2gpPresetI2i || defaults.presetI2i)
        : (config.imageWan2gpPreset || defaults.preset)
      const preset = resolveWan2gpPreset(presetId, checked ? 'i2i' : 't2i')
      const resolutionOptions =
        preset?.supported_resolutions?.length
          ? preset.supported_resolutions
          : [preset?.default_resolution || defaults.frameResolution]
      nextUpdates.frameImageResolution = preset?.default_resolution || resolutionOptions[0] || defaults.frameResolution
      if (checked) {
        nextUpdates.imageWan2gpInferenceStepsI2i = preset?.inference_steps || defaults.inferenceSteps || 20
      } else {
        nextUpdates.imageWan2gpInferenceStepsT2i = preset?.inference_steps || defaults.inferenceSteps || 20
      }
    }
    updateConfig(nextUpdates)
  }, [
    config.imageProvider,
    config.imageWan2gpPreset,
    config.imageWan2gpPresetI2i,
    resolveWan2gpPreset,
    settings,
    updateConfig,
  ])

  const resolveWan2gpVideoPreset = useCallback((
    presetId: string,
    mode: 't2v' | 'i2v'
  ): Wan2gpVideoPreset | undefined => {
    const source = mode === 'i2v' ? wan2gpVideoI2vPresets : wan2gpVideoT2vPresets
    return getWan2gpVideoPresetById(source, presetId) || source[0]
  }, [wan2gpVideoI2vPresets, wan2gpVideoT2vPresets])

  const handleWan2gpVideoResolutionTierChange = useCallback((
    choices: ReturnType<typeof getWan2gpResolutionChoices>,
    tier: string
  ) => {
    const nextResolution = pickDefaultResolutionForTier(choices, tier)
    if (nextResolution) {
      updateConfig({ videoWan2gpResolution: nextResolution })
    }
  }, [updateConfig])

  const handleVideoRuntimeModelChange = useCallback((value: string) => {
    const parsed = parseProviderModelValue(value)
    const videoModelMode: 't2v' | 'i2v' = effectiveUseFirstFrameRef ? 'i2v' : 't2v'
    if (parsed.provider === 'vertex_ai') {
      const defaults = getVertexVideoDefaults(settings, videoModelMode)
      const model = parsed.model || defaults.model
      updateConfig({
        videoProvider: 'vertex_ai',
        ...(videoModelMode === 'i2v'
          ? { videoModelI2v: model }
          : { videoModel: model }),
        videoAspectRatio: config.videoAspectRatio || defaults.aspectRatio,
        resolution: config.resolution || defaults.resolution,
      })
      return
    }
    if (parsed.provider === 'volcengine_seedance') {
      const defaults = getSeedanceVideoDefaults(settings, videoModelMode)
      const model = parsed.model || defaults.model
      updateConfig({
        videoProvider: 'volcengine_seedance',
        ...(videoModelMode === 'i2v'
          ? { videoModelI2v: model }
          : { videoModel: model }),
        videoAspectRatio: config.videoAspectRatio || defaults.aspectRatio,
        resolution: config.resolution || defaults.resolution,
      })
      return
    }
    if (parsed.provider === 'kling') {
      const defaults = getKlingVideoDefaults(settings, videoModelMode)
      const model = parsed.model || defaults.model
      updateConfig({
        videoProvider: 'kling',
        ...(videoModelMode === 'i2v'
          ? { videoModelI2v: model }
          : { videoModel: model }),
        videoAspectRatio: config.videoAspectRatio || defaults.aspectRatio,
        resolution: config.resolution || defaults.resolution,
      })
      return
    }
    if (parsed.provider === 'vidu') {
      const defaults = getViduVideoDefaults(settings, videoModelMode)
      const model = parsed.model || defaults.model
      updateConfig({
        videoProvider: 'vidu',
        ...(videoModelMode === 'i2v'
          ? { videoModelI2v: model }
          : { videoModel: model }),
        videoAspectRatio: config.videoAspectRatio || defaults.aspectRatio,
        resolution: config.resolution || defaults.resolution,
      })
      return
    }
    if (parsed.provider !== 'wan2gp') return

    const defaults = getWan2gpVideoDefaults(settings)
    const useFirstFrameRef = effectiveUseFirstFrameRef
    const nextPresetId = parsed.model || (useFirstFrameRef ? defaults.i2vPreset : defaults.t2vPreset)
    const activePreset = resolveWan2gpVideoPreset(nextPresetId, useFirstFrameRef ? 'i2v' : 't2v')
    const updates: Partial<StageConfig> = {
      videoProvider: 'wan2gp',
    }
    if (useFirstFrameRef) {
      updates.videoWan2gpI2vPreset = nextPresetId
    } else {
      updates.videoWan2gpT2vPreset = nextPresetId
      const resolutionOptions = activePreset?.supported_resolutions?.length
        ? activePreset.supported_resolutions
        : [activePreset?.default_resolution || defaults.resolution]
      const currentResolution = config.videoWan2gpResolution || defaults.resolution
      updates.videoWan2gpResolution = resolutionOptions.includes(currentResolution)
        ? currentResolution
        : (activePreset?.default_resolution || resolutionOptions[0] || defaults.resolution)
    }
    updates.videoWan2gpInferenceSteps = activePreset?.inference_steps || defaults.inferenceSteps
    updates.videoWan2gpSlidingWindowSize = activePreset?.sliding_window_size || undefined
    updateConfig(updates)
  }, [
    config.resolution,
    config.videoAspectRatio,
    config.videoWan2gpResolution,
    effectiveUseFirstFrameRef,
    resolveWan2gpVideoPreset,
    settings,
    updateConfig,
  ])

  const handleUseFirstFrameRefChange = useCallback((checked: boolean) => {
    if (isSingleTakeEnabled) return
    const updates: Partial<StageConfig> = { useFirstFrameRef: checked }
    if ((config.videoProvider || settings?.default_video_provider) === 'wan2gp') {
      const defaults = getWan2gpVideoDefaults(settings)
      const t2vPreset = resolveWan2gpVideoPreset(config.videoWan2gpT2vPreset || defaults.t2vPreset, 't2v')
      const i2vPreset = resolveWan2gpVideoPreset(config.videoWan2gpI2vPreset || defaults.i2vPreset, 'i2v')
      const activePreset = checked ? i2vPreset : t2vPreset
      updates.videoWan2gpInferenceSteps =
        activePreset?.inference_steps
        || t2vPreset?.inference_steps
        || i2vPreset?.inference_steps
        || defaults.inferenceSteps
      updates.videoWan2gpSlidingWindowSize = activePreset?.sliding_window_size || undefined
    }
    updateConfig(updates)
  }, [
    config.videoProvider,
    config.videoWan2gpI2vPreset,
    config.videoWan2gpT2vPreset,
    isSingleTakeEnabled,
    resolveWan2gpVideoPreset,
    settings,
    updateConfig,
  ])

  const handleUseReferenceImageRefChange = useCallback((checked: boolean) => {
    const updates: Partial<StageConfig> = { useReferenceImageRef: checked }
    if (checked && !effectiveUseFirstFrameRef) {
      const configuredProviders: string[] = []
      if ((settings?.video_seedance_api_key || '').trim()) configuredProviders.push('volcengine_seedance')
      const currentProvider = (config.videoProvider || settings?.default_video_provider || '').trim()
      const currentModel = (config.videoModel || '').trim()
      const currentSeedanceModel = SEEDANCE_MODEL_PRESETS.find(
        (preset) =>
          currentProvider === 'volcengine_seedance'
          && preset.id === currentModel
          && preset.supportsReferenceImage
      )

      if (currentSeedanceModel) {
        updates.videoProvider = 'volcengine_seedance'
        updates.videoModel = currentSeedanceModel.id
      } else if (configuredProviders.includes('volcengine_seedance')) {
        updates.videoProvider = 'volcengine_seedance'
        updates.videoModel = 'seedance-2-0'
      }
    }
    updateConfig(updates)
  }, [
    config.videoModel,
    config.videoProvider,
    effectiveUseFirstFrameRef,
    settings?.default_video_provider,
    settings?.video_seedance_api_key,
    updateConfig,
  ])

  const handleImageRuntimeModelChange = useCallback((
    value: string,
    scene: 'reference' | 'frame'
  ) => {
    const parsed = parseProviderModelValue(value)
    if (parsed.provider === 'wan2gp') {
      const defaults = getWan2gpDefaults(settings)
      const updates: Partial<StageConfig> = { imageProvider: 'wan2gp' }
      if (scene === 'reference') {
        const presetId = parsed.model || defaults.preset
        const preset = resolveWan2gpPreset(presetId, 't2i')
        const resolutionOptions = preset?.supported_resolutions?.length
          ? preset.supported_resolutions
          : [preset?.default_resolution || defaults.referenceResolution]
        const currentResolution = config.referenceImageResolution || defaults.referenceResolution
        updates.imageWan2gpPreset = presetId
        updates.referenceImageResolution = resolutionOptions.includes(currentResolution)
          ? currentResolution
          : (
              resolutionOptions.find((item) => item === '1024x1024')
              || preset?.default_resolution
              || resolutionOptions[0]
              || defaults.referenceResolution
            )
        updates.imageWan2gpInferenceStepsT2i = preset?.inference_steps || defaults.inferenceSteps || 20
      } else {
        const useI2i = config.useReferenceConsistency ?? false
        const presetType = useI2i ? 'i2i' : 't2i'
        const presetId = parsed.model || (useI2i ? defaults.presetI2i : defaults.preset)
        const preset = resolveWan2gpPreset(presetId, presetType)
        const resolutionOptions = preset?.supported_resolutions?.length
          ? preset.supported_resolutions
          : [preset?.default_resolution || defaults.frameResolution]
        const currentResolution = config.frameImageResolution || defaults.frameResolution
        updates.frameImageResolution = resolutionOptions.includes(currentResolution)
          ? currentResolution
          : (preset?.default_resolution || resolutionOptions[0] || defaults.frameResolution)
        if (useI2i) {
          updates.imageWan2gpPresetI2i = presetId
          updates.imageWan2gpInferenceStepsI2i = preset?.inference_steps || defaults.inferenceSteps || 20
        } else {
          updates.imageWan2gpPreset = presetId
          updates.imageWan2gpInferenceStepsT2i = preset?.inference_steps || defaults.inferenceSteps || 20
        }
      }
      updateConfig(updates)
      return
    }

    const referenceDefaults = getImageDefaults(parsed.provider, settings, 'reference')
    const frameDefaults = getImageDefaults(parsed.provider, settings, 'frame')
    const nextModel = parsed.model || getImageModelDefault(
      parsed.provider,
      settings,
      scene === 'reference'
        ? 't2i'
        : ((config.useReferenceConsistency ?? false) ? 'i2i' : 't2i')
    )
    const referenceSizeOptions = getImageSizeOptionsByProviderModel(parsed.provider, nextModel)
    const frameSizeOptions = getImageSizeOptionsByProviderModel(parsed.provider, nextModel)
    const referenceAspectRatioOptions = getImageAspectRatioOptionsByProviderModel(parsed.provider, nextModel)
    const frameAspectRatioOptions = getImageAspectRatioOptionsByProviderModel(parsed.provider, nextModel)
    const referenceDefaultSize = referenceSizeOptions.includes(referenceDefaults.size)
      ? referenceDefaults.size
      : (referenceSizeOptions[0] || referenceDefaults.size)
    const frameDefaultSize = frameSizeOptions.includes(frameDefaults.size)
      ? frameDefaults.size
      : (frameSizeOptions[0] || frameDefaults.size)
    const referenceDefaultAspectRatio = referenceAspectRatioOptions.includes(referenceDefaults.aspectRatio)
      ? referenceDefaults.aspectRatio
      : (
          referenceAspectRatioOptions.includes('1:1')
            ? '1:1'
            : (referenceAspectRatioOptions[0] || referenceDefaults.aspectRatio)
        )
    const frameDefaultAspectRatio = frameAspectRatioOptions.includes(frameDefaults.aspectRatio)
      ? frameDefaults.aspectRatio
      : (
          frameAspectRatioOptions.includes('9:16')
            ? '9:16'
            : (frameAspectRatioOptions[0] || frameDefaults.aspectRatio)
        )
    const resolvedReferenceSize = referenceSizeOptions.includes(config.referenceImageSize || '')
      ? (config.referenceImageSize || '')
      : referenceDefaultSize
    const resolvedFrameSize = frameSizeOptions.includes(config.frameImageSize || '')
      ? (config.frameImageSize || '')
      : frameDefaultSize
    const resolvedReferenceAspectRatio = referenceAspectRatioOptions.includes(config.referenceAspectRatio || '')
      ? (config.referenceAspectRatio || '')
      : referenceDefaultAspectRatio
    const resolvedFrameAspectRatio = frameAspectRatioOptions.includes(config.frameAspectRatio || '')
      ? (config.frameAspectRatio || '')
      : frameDefaultAspectRatio
    updateConfig({
      imageProvider: parsed.provider,
      ...(scene === 'reference'
        ? { imageModel: nextModel }
        : { frameImageModel: nextModel }),
      referenceAspectRatio: resolvedReferenceAspectRatio,
      referenceImageSize: resolvedReferenceSize,
      frameAspectRatio: resolvedFrameAspectRatio,
      frameImageSize: resolvedFrameSize,
    })
  }, [
    config.frameAspectRatio,
    config.frameImageResolution,
    config.frameImageSize,
    config.referenceAspectRatio,
    config.referenceImageResolution,
    config.referenceImageSize,
    config.useReferenceConsistency,
    getImageAspectRatioOptionsByProviderModel,
    getImageSizeOptionsByProviderModel,
    resolveWan2gpPreset,
    settings,
    updateConfig,
  ])

  const getConfiguredVideoProviders = useCallback(() => {
    const providers: string[] = []
    if ((settings?.video_seedance_api_key || '').trim()) providers.push('volcengine_seedance')
    if (settings?.wan2gp_available) providers.push('wan2gp')
    return providers
  }, [settings])

  const renderNoConfigWarning = (type: string) => (
    <Alert variant="destructive" className="mb-4">
      <AlertCircle className="h-4 w-4" />
      <AlertDescription>
        请先在<Link href="/settings" className="underline font-medium">设置页面</Link>配置 {type} Provider
      </AlertDescription>
    </Alert>
  )

  const renderLLMOptions = () => {
    const providers = getConfiguredLLMProviders_()
    if (providers.length === 0) {
      return renderNoConfigWarning('LLM')
    }

    const llmOptions: ProviderModelOption[] = providers.flatMap((provider) => {
      const models = provider.enabled_models.length > 0
        ? provider.enabled_models
        : provider.catalog_models
      return models.map((modelId) => ({
        value: makeProviderModelValue(provider.id, modelId),
        provider: provider.id,
        model: modelId,
        label: buildProviderModelLabel(provider.id, modelId, provider.name),
      }))
    })

    const defaultProviderId = providers.some((item) => item.id === settings?.default_llm_provider)
      ? settings?.default_llm_provider
      : providers[0]?.id
    const selectedProviderId = providers.some((item) => item.id === config.llmProvider)
      ? config.llmProvider
      : defaultProviderId
    const selectedProvider = providers.find((item) => item.id === selectedProviderId) || providers[0]
    const currentValue = makeProviderModelValue(
      selectedProvider.id,
      config.llmModel || selectedProvider.default_model || selectedProvider.enabled_models[0] || ''
    )
    const selectedValue = llmOptions.some((item) => item.value === currentValue)
      ? currentValue
      : (llmOptions.find((item) => item.provider === selectedProvider.id)?.value || llmOptions[0]?.value || currentValue)

    return (
      <div className="space-y-2">
        <Label>LLM 模型</Label>
        <Select
          value={selectedValue}
          onValueChange={(v) => {
            const parsed = parseProviderModelValue(v)
            updateConfig({
              llmProvider: parsed.provider,
              llmModel: parsed.model || '',
            })
          }}
        >
          <SelectTrigger><SelectValue placeholder="选择模型" /></SelectTrigger>
          <SelectContent>
            {llmOptions.map((item) => (
              <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    )
  }

  const renderScriptTabContent = () => {
    return (
      <StagePanelScriptTab
        config={config}
        settings={settings}
        isSettingsLoading={isSettingsLoading}
        effectiveScriptMode={effectiveScriptMode}
        updateConfig={updateConfig}
        onNarratorStyleChange={onNarratorStyleChange}
        renderLLMOptions={renderLLMOptions}
        getConfiguredImageProviders={getConfiguredImageProviders_}
        resolveEffectiveImageProvider={resolveEffectiveImageProvider}
        getImageProviderById={getImageProviderById}
        getImageSizeOptionsByProviderModel={getImageSizeOptionsByProviderModel}
        getImageAspectRatioOptionsByProviderModel={getImageAspectRatioOptionsByProviderModel}
        resolveWan2gpPreset={resolveWan2gpPreset}
        handleWan2gpResolutionTierChange={handleWan2gpResolutionTierChange}
        handleImageRuntimeModelChange={handleImageRuntimeModelChange}
        wan2gpImagePresets={wan2gpPresets}
      />
    )
  }

  const renderShotsTabContent = () => {
    return (
      <StageShotsConfig
        config={config}
        updateConfig={updateConfig}
        settings={settings}
        isSettingsLoading={isSettingsLoading}
        hasReferenceData={hasReferenceData}
        isSingleTakeEnabled={isSingleTakeEnabled}
        isSingleTakeForcedByMode={isSingleTakeForcedByMode}
        effectiveUseFirstFrameRef={effectiveUseFirstFrameRef}
        wan2gpT2iPresets={wan2gpT2iPresets}
        wan2gpI2iPresets={wan2gpI2iPresets}
        wan2gpVideoT2vPresets={wan2gpVideoT2vPresets}
        wan2gpVideoI2vPresets={wan2gpVideoI2vPresets}
        getConfiguredVideoProviders={getConfiguredVideoProviders}
        getConfiguredImageProviders={getConfiguredImageProviders_}
        resolveEffectiveImageProvider={resolveEffectiveImageProvider}
        getImageProviderById={getImageProviderById}
        getImageSizeOptionsByProviderModel={getImageSizeOptionsByProviderModel}
        getImageAspectRatioOptionsByProviderModel={getImageAspectRatioOptionsByProviderModel}
        resolveWan2gpPreset={resolveWan2gpPreset}
        resolveWan2gpVideoPreset={resolveWan2gpVideoPreset}
        handleVideoRuntimeModelChange={handleVideoRuntimeModelChange}
        handleImageRuntimeModelChange={handleImageRuntimeModelChange}
        handleUseFirstFrameRefChange={handleUseFirstFrameRefChange}
        handleUseReferenceImageRefChange={handleUseReferenceImageRefChange}
        handleWan2gpResolutionTierChange={handleWan2gpResolutionTierChange}
        handleWan2gpVideoResolutionTierChange={handleWan2gpVideoResolutionTierChange}
        handleSingleTakeChange={handleSingleTakeChange}
        handleUseReferenceConsistencyChange={handleUseReferenceConsistencyChange}
        renderLLMOptions={renderLLMOptions}
        renderNoConfigWarning={renderNoConfigWarning}
      />
    )
  }

  const renderComposeTabContent = () => {
    return (
      <StagePanelComposeTab
        config={config}
        updateConfig={updateConfig}
        videoShots={composeVideoShots}
        effectiveComposeVideoFitMode={effectiveComposeVideoFitMode}
        isSingleTakeEnabled={isSingleTakeEnabled}
        sectionTitleClass={SECTION_TITLE_CLASS}
      />
    )
  }

  const renderTabContent = () => {
    switch (activeTab) {
      case 'script':
        return renderScriptTabContent()
      case 'shots':
        return renderShotsTabContent()
      case 'compose':
        return renderComposeTabContent()
      default:
        return null
    }
  }

  return (
    <div className="h-full flex flex-col bg-background border-l overflow-hidden">
      <div className="px-4 py-3 border-b flex-shrink-0">
        <Tabs value={activeTab} onValueChange={(v) => onTabChange(v as TabType)}>
          <TabsList className="w-full grid grid-cols-3 h-auto">
            {TAB_OPTIONS.map((tab) => (
              <TabsTrigger
                key={tab.value}
                value={tab.value}
                className="text-sm py-2"
              >
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      <ScrollArea className="flex-1 min-h-0 overflow-hidden">
        <div className="p-4 space-y-4">
          {renderTabContent()}
        </div>
      </ScrollArea>

      <div className="p-4 border-t space-y-3 flex-shrink-0">
        {isRunning && (
          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">{normalizedProgressMessage || (progress > 0 ? '生成中...' : '准备中...')}</span>
              <span>
                {totalItems !== undefined && completedItems !== undefined ? (
                  <>
                    {completedItems}/{totalItems}
                    {skippedItems ? ` (跳过${skippedItems})` : ''}
                  </>
                ) : null}
              </span>
            </div>
            <Progress value={progress} />
            {onCancelAllRunningTasks && (
              <Button
                variant="destructive"
                size="sm"
                onClick={onCancelAllRunningTasks}
                disabled={isCancelling}
                className="w-full"
              >
                {isCancelling ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                {isCancelling ? '中断中...' : '中断当前所有生成任务'}
              </Button>
            )}
          </div>
        )}

        <StagePanelActionButtons
          activeTab={activeTab}
          stageStatus={stageStatus}
          isRunning={isRunning}
          runningStage={runningStage}
          runningAction={runningAction}
          onRunStage={onRunStage}
          config={config}
          effectiveScriptMode={effectiveScriptMode}
          isSingleTakeEnabled={isSingleTakeEnabled}
          effectiveUseFirstFrameRef={effectiveUseFirstFrameRef}
          hasReferenceData={hasReferenceData}
          isReferenceImageComplete={isReferenceImageComplete}
          hasVideoPromptReady={hasVideoPromptReady}
          settings={settings}
          getConfiguredImageProviders={getConfiguredImageProviders_}
          resolveEffectiveImageProvider={resolveEffectiveImageProvider}
          resolveWan2gpPreset={resolveWan2gpPreset}
          composeVideoUrl={composeVideoUrl}
          isExportingVideo={isExportingVideo}
          onExportVideo={handleExportVideo}
        />
      </div>
    </div>
  )
}
