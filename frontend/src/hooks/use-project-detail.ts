'use client'

import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query'

import { api } from '@/lib/api-client'
import { hasKlingCredentials } from '@/lib/kling'
import { resolveStorageFileUrl } from '@/lib/media-url'
import { queryKeys } from '@/lib/query-keys'
import { useSettingsQuery } from '@/hooks/use-settings-queries'
import type { ContentSyncSnapshot } from '@/hooks/use-project-detail.types'
import { useStages } from '@/hooks/use-stage'
import { useStageRunner } from '@/hooks/use-stage-runner'
import { useProjectDetailSourceActions } from '@/hooks/use-project-detail-source-actions'
import { useProjectDetailStageActions } from '@/hooks/use-project-detail-stage-actions'
import { useProjectDetailNarratorSync } from '@/hooks/use-project-detail-narrator-sync'
import { useNavbar } from '@/components/layout/navbar-context'
import type { StageConfig, TabType, StageStatus } from '@/types/stage-panel'
import { resolveWan2gpAudioMode } from '@/lib/stage-input-builder'
import { resolveVideoProvider } from '@/lib/stage-runtime'
import { rateToSpeed } from '@/lib/reference-voice'
import { resolveScriptModeFromVideoType } from '@/lib/project-mode'
import {
  DUO_NARRATOR_STYLE_OPTIONS,
  SINGLE_NARRATOR_STYLE_OPTIONS,
} from '@/lib/narrator-style'
import {
  getDefaultLlmModel,
  getDefaultImageModelBinding,
  getDefaultVideoModelBinding,
  getImageModel,
  getReferenceImageAspectRatio,
  getReferenceImageSize,
  getFrameImageAspectRatio,
  getFrameImageSize,
  getWan2gpPreset,
  getWan2gpPresetI2i,
  getWan2gpReferenceResolution,
  getWan2gpFrameResolution,
  getWan2gpVideoT2vPreset,
  getWan2gpVideoI2vPreset,
  getWan2gpVideoResolution,
  getVideoModelByProvider,
  getVideoAspectRatioByProvider,
  getVideoResolutionByProvider,
  getWan2gpAudioPreset,
  getWan2gpAudioAltPrompt,
  getWan2gpAudioTemperature,
  getWan2gpAudioTopK,
  getWan2gpAudioSeed,
  getWan2gpAudioGuide,
  getWan2gpAudioSpeed,
  asRecord,
  normalizeProjectConfig,
  pickPersistedGroupConfig,
  extractPersistedStageConfig,
  collectChangedPersistGroups,
  buildDefaultStageStatus,
  STAGE_CONFIG_AUTOSAVE_DELAY_MS,
  STAGE_PANEL_CONFIG_KEY,
  buildStageData,
  computeStageCompletion,
} from '@/lib/project-detail-helpers'
import type { ReferenceVoiceFields, StageConfigPersistGroup } from '@/lib/project-detail-helpers'
import type { Project, ProjectListResponse } from '@/types/project'
import type { BackendStageType, Stage } from '@/types/stage'
import type { Source, SourceListResponse } from '@/types/source'
import type { ReferenceLibraryItem } from '@/types/reference'
import type { TextLibraryItem } from '@/types/text-library'
import { toast } from 'sonner'

async function fetchStageData(projectId: number, stageType: string): Promise<Stage | null> {
  try {
    return await api.stages.get(projectId, stageType)
  } catch {
    return null
  }
}

const LLM_MODEL_BINDING_SEPARATOR = '::'

function parseLlmModelBinding(rawValue: unknown): { providerId: string; modelId: string } | null {
  const text = String(rawValue || '').trim()
  if (!text) return null
  const separatorIndex = text.indexOf(LLM_MODEL_BINDING_SEPARATOR)
  if (separatorIndex <= 0) return null
  const providerId = text.slice(0, separatorIndex).trim()
  const modelId = text.slice(separatorIndex + LLM_MODEL_BINDING_SEPARATOR.length).trim()
  if (!providerId || !modelId) return null
  return { providerId, modelId }
}

function normalizeNarratorStyleForMode(
  mode: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script',
  rawStyle: unknown
): string {
  const normalized = String(rawStyle || '').trim()
  if (!normalized || normalized === '__default__') return ''
  if (mode === 'single') {
    const allowedSingleStyles = new Set<string>(
      SINGLE_NARRATOR_STYLE_OPTIONS
        .map((item) => item.value)
        .filter((value) => value !== '__default__')
    )
    return allowedSingleStyles.has(normalized) ? normalized : ''
  }
  if (mode === 'duo_podcast') {
    const allowedDuoStyles = new Set<string>(
      DUO_NARRATOR_STYLE_OPTIONS
        .map((item) => item.value)
        .filter((value) => value !== '__default__')
    )
    return allowedDuoStyles.has(normalized) ? normalized : ''
  }
  return ''
}

export default function useProjectDetail(projectId: number) {
  const queryClient = useQueryClient()
  const { setProject } = useNavbar()
  const stageStreamDebugEnabled =
    typeof window !== 'undefined' && window.localStorage.getItem('localvideo_debug_stage_stream') === '1'

  const [activeTab, setActiveTab] = useState<TabType>('script')
  const [isRunning, setIsRunning] = useState(false)
  const [runningStage, setRunningStage] = useState<BackendStageType>()
  const [runningAction, setRunningAction] = useState<string>()
  const [progress, setProgress] = useState(0)
  const [progressMessage, setProgressMessage] = useState<string>()
  const [completedItems, setCompletedItems] = useState<number>()
  const [totalItems, setTotalItems] = useState<number>()
  const [skippedItems, setSkippedItems] = useState<number>()
  const [generatingShots, setGeneratingShots] = useState<Record<string, { status: string; progress: number }>>()
  const [runningShotIndex, setRunningShotIndex] = useState<number>()
  const [runningReferenceId, setRunningReferenceId] = useState<string | number>()
  const lastCompletedItemsRef = useRef<number | undefined>(undefined)
  const lastItemCompleteRef = useRef<number | undefined>(undefined)
  const activeStageEventSourceRef = useRef<EventSource | null>(null)
  const activeFallbackPollingStopRef = useRef<(() => void) | null>(null)
  const activeSearchEventSourceRef = useRef<EventSource | null>(null)
  const manualCancelSuppressUntilRef = useRef(0)

  const [isSearching, setIsSearching] = useState(false)
  const [settingsApplied, setSettingsApplied] = useState(false)

  const [stageConfig, setStageConfig] = useState<StageConfig>({
    duoPodcastCameraMode: 'same_frame',
    textTargetLanguage: 'zh',
    textPromptComplexity: 'normal',
    storyboardShotDensity: 'medium',
    style: '',
    targetDuration: 60,
    singleTake: false,
    useFirstFrameRef: true,
    useReferenceImageRef: false,
    videoFitMode: 'truncate',
    composeCanvasStrategy: 'max_size',
    composeFixedAspectRatio: '9:16',
    composeFixedResolution: '1080x1920',
    includeSubtitle: true,
    subtitleFontSize: 12,
    subtitlePositionPercent: 80,
    audioMaxConcurrency: 4,
    useReferenceConsistency: true,
  })
  const stageConfigRef = useRef<StageConfig>(stageConfig)
  const projectRef = useRef<Project | null>(null)
  const projectConfigDraftRef = useRef<Record<string, unknown>>({})
  const stageConfigAutosaveQueueRef = useRef<Promise<void>>(Promise.resolve())
  const stageConfigAutosaveTimersRef = useRef<
    Partial<Record<StageConfigPersistGroup, ReturnType<typeof setTimeout>>>
  >({})
  const lastStageConfigAutosaveErrorToastAtRef = useRef(0)
  const stageConfigHydratedProjectIdRef = useRef<number | null>(null)
  const stageConfigHydratedVideoTypeRef = useRef<string | null>(null)
  const llmAutoInitLockedProjectIdsRef = useRef<Set<number>>(new Set())
  const imageAutoInitLockedProjectIdsRef = useRef<Set<number>>(new Set())

  useEffect(() => {
    stageConfigRef.current = stageConfig
  }, [stageConfig])

  const { data: settings } = useSettingsQuery()

  useEffect(() => {
    if (settings && !settingsApplied) {
      // Existing project config has already been hydrated from persistence;
      // never let global defaults override project-specific settings afterward.
      if (stageConfigHydratedProjectIdRef.current !== null) {
        const hydratedTimer = window.setTimeout(() => {
          setSettingsApplied(true)
        }, 0)
        return () => window.clearTimeout(hydratedTimer)
      }
      const llmProviders = settings.llm_providers || []
      const defaultGeneralBinding = parseLlmModelBinding(settings.default_general_llm_model)
      const defaultGeneralProviderId = String(defaultGeneralBinding?.providerId || '').trim()
      const defaultGeneralProviderValid = llmProviders.some(
        (provider) => provider.id === defaultGeneralProviderId
      )
      const defaultLlmProviderId = String(
        (defaultGeneralProviderValid
          ? defaultGeneralProviderId
          : settings.default_llm_provider)
        || llmProviders[0]?.id
        || ''
      ).trim()
      const imageProviders = settings.image_providers || []

      const defaultAudioProvider = settings.default_audio_provider || 'edge_tts'
      const defaultAudioPreset = getWan2gpAudioPreset(settings)
      const defaultAudioMode = resolveWan2gpAudioMode(
        defaultAudioPreset,
        settings.audio_wan2gp_model_mode
      )
      const defaultAudioVoice = defaultAudioProvider === 'volcengine_tts'
        ? (settings.audio_volcengine_tts_voice_type || 'zh_female_vv_uranus_bigtts')
        : settings.edge_tts_voice
      const defaultAudioSpeed = defaultAudioProvider === 'wan2gp'
        ? getWan2gpAudioSpeed(settings)
        : (
          defaultAudioProvider === 'volcengine_tts'
            ? (settings.audio_volcengine_tts_speed_ratio || 1.0)
            : rateToSpeed(settings.edge_tts_rate)
        )
      const timer = setTimeout(() => {
        // Re-check after timeout: project config may have been hydrated
        // while the timer was pending; persisted project values must not
        // be overwritten by global settings defaults.
        if (stageConfigHydratedProjectIdRef.current !== null) {
          setSettingsApplied(true)
          return
        }
        setStageConfig(prev => {
          const defaultImageMode = (prev.useReferenceConsistency ?? false) ? 'i2i' : 't2i'
          const defaultImageBinding = getDefaultImageModelBinding(settings, defaultImageMode)
          const defaultImageProviderId = String(defaultImageBinding?.providerId || '').trim()
          const defaultImageProviderValid = imageProviders.some(
            (provider) => provider.id === defaultImageProviderId
          )
          const resolvedDefaultImageProvider = String(
            (defaultImageProviderValid
              ? defaultImageProviderId
              : settings.default_image_provider)
            || imageProviders[0]?.id
            || ''
          ).trim()
          const resolvedDefaultImageModel = String(defaultImageBinding?.modelId || '').trim()
          const defaultVideoMode = (prev.useFirstFrameRef ?? true) ? 'i2v' : 't2v'
          const defaultVideoBinding = getDefaultVideoModelBinding(settings, defaultVideoMode)
          const defaultVideoProviderCandidate = String(
            defaultVideoBinding?.providerId
            || settings.default_video_provider
            || ''
          ).trim()
          const resolvedDefaultVideoProvider = resolveVideoProvider(
            defaultVideoProviderCandidate,
            settings
          )

          return {
            ...prev,
          llmProvider: defaultLlmProviderId,
          llmModel: String(defaultGeneralBinding?.modelId || '').trim() || getDefaultLlmModel(settings),
          audioProvider: defaultAudioProvider,
          voice: defaultAudioVoice,
          speed: defaultAudioSpeed,
          audioWan2gpPreset: defaultAudioPreset,
          audioWan2gpModelMode: defaultAudioMode,
          audioWan2gpAltPrompt: getWan2gpAudioAltPrompt(settings),
          audioWan2gpTemperature: getWan2gpAudioTemperature(settings),
          audioWan2gpTopK: getWan2gpAudioTopK(settings),
          audioWan2gpSeed: getWan2gpAudioSeed(settings),
          audioWan2gpAudioGuide: getWan2gpAudioGuide(settings),
          imageProvider: resolvedDefaultImageProvider,
          imageModel: resolvedDefaultImageProvider === 'wan2gp'
            ? ''
            : getImageModel(resolvedDefaultImageProvider, settings, 't2i'),
          frameImageModel: resolvedDefaultImageProvider === 'wan2gp'
            ? ''
            : (resolvedDefaultImageModel || getImageModel(resolvedDefaultImageProvider, settings, defaultImageMode)),
          videoProvider: resolvedDefaultVideoProvider,
          videoModel: getVideoModelByProvider(resolvedDefaultVideoProvider, settings, 't2v'),
          videoModelI2v: getVideoModelByProvider(resolvedDefaultVideoProvider, settings, 'i2v'),
          videoAspectRatio: getVideoAspectRatioByProvider(resolvedDefaultVideoProvider, settings),
          resolution: getVideoResolutionByProvider(resolvedDefaultVideoProvider, settings),
          videoWan2gpT2vPreset: getWan2gpVideoT2vPreset(settings),
          videoWan2gpI2vPreset: getWan2gpVideoI2vPreset(settings),
          videoWan2gpResolution: getWan2gpVideoResolution(settings),
          useReferenceImageRef: false,
          referenceAspectRatio: getReferenceImageAspectRatio(resolvedDefaultImageProvider, settings),
          referenceImageSize: getReferenceImageSize(resolvedDefaultImageProvider, settings),
          frameAspectRatio: getFrameImageAspectRatio(resolvedDefaultImageProvider, settings),
          frameImageSize: getFrameImageSize(resolvedDefaultImageProvider, settings),
          imageWan2gpPreset: getWan2gpPreset(settings),
          imageWan2gpPresetI2i: getWan2gpPresetI2i(settings),
          referenceImageResolution: getWan2gpReferenceResolution(settings),
          frameImageResolution: getWan2gpFrameResolution(settings),
          imageWan2gpInferenceSteps: settings.image_wan2gp_inference_steps > 0
            ? settings.image_wan2gp_inference_steps
            : undefined,
          imageWan2gpInferenceStepsT2i: settings.image_wan2gp_inference_steps > 0
            ? settings.image_wan2gp_inference_steps
            : undefined,
          }
        })
        setSettingsApplied(true)
      }, 0)
      return () => clearTimeout(timer)
    }
  }, [settings, settingsApplied])

  const { data: project, isLoading: projectLoading, refetch: refetchProject } = useQuery({
    queryKey: queryKeys.projects.detail(projectId),
    queryFn: () => api.projects.get(projectId),
    enabled: !isNaN(projectId),
  })

  const persistStageConfigGroup = useCallback((group: StageConfigPersistGroup) => {
    stageConfigAutosaveQueueRef.current = stageConfigAutosaveQueueRef.current
      .then(async () => {
        if (isNaN(projectId)) return
        const currentProject = projectRef.current
        if (!currentProject) return

        const currentConfig = { ...projectConfigDraftRef.current }
        const stagePanelConfig = asRecord(currentConfig[STAGE_PANEL_CONFIG_KEY])
        const nextStagePanelConfig: Record<string, unknown> = stagePanelConfig
          ? { ...stagePanelConfig }
          : {}
        nextStagePanelConfig[group] = pickPersistedGroupConfig(stageConfigRef.current, group) as Record<string, unknown>
        nextStagePanelConfig.version = 1
        nextStagePanelConfig.updated_at = new Date().toISOString()

        const nextProjectConfig: Record<string, unknown> = {
          ...currentConfig,
          [STAGE_PANEL_CONFIG_KEY]: nextStagePanelConfig,
        }
        projectConfigDraftRef.current = nextProjectConfig

        const nextStageConfig = stageConfigRef.current
        const updatePayload: {
          config: Record<string, unknown>
          style?: string
          target_duration?: number
        } = {
          config: nextProjectConfig,
        }
        if (group === 'script') {
          if (typeof nextStageConfig.style === 'string') {
            updatePayload.style = nextStageConfig.style
          }
          if (
            typeof nextStageConfig.targetDuration === 'number'
            && Number.isFinite(nextStageConfig.targetDuration)
          ) {
            updatePayload.target_duration = Math.max(
              10,
              Math.min(600, Math.round(nextStageConfig.targetDuration))
            )
          }
        }

        const updatedProject = await api.projects.update(projectId, updatePayload)
        projectRef.current = updatedProject
        projectConfigDraftRef.current = normalizeProjectConfig(updatedProject.config)
        queryClient.setQueryData<Project>(queryKeys.projects.detail(projectId), updatedProject)
      })
      .catch((error) => {
        console.error(`[StageConfig Autosave] Failed to persist group: ${group}`, error)
        const now = Date.now()
        if (now - lastStageConfigAutosaveErrorToastAtRef.current > 3000) {
          lastStageConfigAutosaveErrorToastAtRef.current = now
          toast.error('项目设置自动保存失败')
        }
      })
  }, [projectId, queryClient])

  const schedulePersistStageConfigGroup = useCallback((group: StageConfigPersistGroup) => {
    const timers = stageConfigAutosaveTimersRef.current
    const existingTimer = timers[group]
    if (existingTimer) clearTimeout(existingTimer)
    timers[group] = setTimeout(() => {
      delete timers[group]
      persistStageConfigGroup(group)
    }, STAGE_CONFIG_AUTOSAVE_DELAY_MS[group])
  }, [persistStageConfigGroup])

  const handleStageConfigChange = useCallback((nextConfig: StageConfig) => {
    const prevConfig = stageConfigRef.current
    stageConfigRef.current = nextConfig
    setStageConfig(nextConfig)
    const changedGroups = collectChangedPersistGroups(prevConfig, nextConfig)
    changedGroups.forEach((group) => {
      schedulePersistStageConfigGroup(group)
    })
  }, [schedulePersistStageConfigGroup])

  useEffect(() => {
    const timers = stageConfigAutosaveTimersRef.current
    return () => {
      ;(Object.keys(timers) as StageConfigPersistGroup[]).forEach((group) => {
        const timer = timers[group]
        if (!timer) return
        clearTimeout(timer)
        delete timers[group]
        persistStageConfigGroup(group)
      })
    }
  }, [persistStageConfigGroup])

  // Sources from API
  const { data: sourcesData } = useQuery({
    queryKey: queryKeys.projectResources.sources(projectId),
    queryFn: () => api.sources.list(projectId),
    enabled: !isNaN(projectId),
  })

  const sources: Source[] = sourcesData?.items || []

  // Source mutations
  const createSourceMutation = useMutation({
    mutationFn: (data: { type: 'search' | 'deep_research' | 'text'; title: string; content: string }) =>
      api.sources.create(projectId, data),
    onSuccess: (createdSource) => {
      queryClient.setQueryData<SourceListResponse>(queryKeys.projectResources.sources(projectId), (current) => {
        if (!current) {
          return { items: [createdSource], total: 1 }
        }
        return {
          ...current,
          items: [createdSource, ...current.items],
          total: current.total + 1,
        }
      })
    },
  })

  const updateSourceMutation = useMutation({
    mutationFn: ({ sourceId, data }: { sourceId: number; data: { selected?: boolean; content?: string } }) =>
      api.sources.update(projectId, sourceId, data),
    onSuccess: (updatedSource, variables) => {
      queryClient.setQueryData<SourceListResponse>(queryKeys.projectResources.sources(projectId), (current) => {
        if (!current) return current
        return {
          ...current,
          items: current.items.map((one) =>
            one.id === variables.sourceId ? updatedSource : one
          ),
        }
      })
    },
  })

  const deleteSourceMutation = useMutation({
    mutationFn: (sourceId: number) => api.sources.delete(projectId, sourceId),
    onSuccess: (_, sourceId) => {
      queryClient.setQueryData<SourceListResponse>(queryKeys.projectResources.sources(projectId), (current) => {
        if (!current) return current
        return {
          ...current,
          items: current.items.filter((one) => one.id !== sourceId),
          total: Math.max(0, current.total - 1),
        }
      })
      toast.success('来源已删除')
    },
    onError: () => {
      toast.error('删除失败')
    },
  })

  const importFromTextLibraryMutation = useMutation({
    mutationFn: (textLibraryIds: number[]) => api.sources.importFromTextLibrary(projectId, textLibraryIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projectResources.sources(projectId) })
    },
  })

  const cancelRunningTasksMutation = useMutation({
    mutationFn: () => api.stages.cancelRunningTasks(projectId),
  })

  const { stages, refetch: refetchStages } = useStages(projectId)

  const stageStatusFromList = useMemo<Record<BackendStageType, string>>(() => {
    const defaults = buildDefaultStageStatus()
    for (const stage of stages) {
      const stageType = stage.stage_type as BackendStageType
      if (stageType in defaults) {
        defaults[stageType] = stage.status
      }
    }
    return defaults
  }, [stages])

  const shouldFetchContentStageDetail =
    activeTab === 'script'
    || runningStage === 'content'
    || stageStatusFromList.content === 'running'
  const shouldFetchStoryboardStageDetail =
    activeTab === 'script'
    || activeTab === 'shots'
    || runningStage === 'storyboard'
    || stageStatusFromList.storyboard === 'running'
  const shouldFetchAudioStageDetail =
    activeTab === 'script'
    || activeTab === 'shots'
    || runningStage === 'audio'
    || stageStatusFromList.audio === 'running'
  const shouldFetchReferenceStageDetail =
    activeTab === 'script'
    || activeTab === 'shots'
    || runningStage === 'reference'
    || stageStatusFromList.reference === 'running'
  const shouldFetchFrameStageDetail =
    activeTab === 'compose'
    || activeTab === 'shots'
    || runningStage === 'first_frame_desc'
    || runningStage === 'frame'
    || runningStage === 'video'
    || stageStatusFromList.first_frame_desc === 'running'
    || stageStatusFromList.frame === 'running'
    || stageStatusFromList.video === 'running'
  const shouldFetchVideoStageDetail =
    activeTab === 'shots'
    || runningStage === 'video'
    || stageStatusFromList.video === 'running'
  const shouldFetchComposeStageDetail =
    activeTab === 'compose'
    || runningStage === 'compose'
    || runningStage === 'subtitle'
    || runningStage === 'burn_subtitle'
    || runningStage === 'finalize'
    || stageStatusFromList.compose === 'running'
  const shouldFetchSubtitleStageDetail =
    activeTab === 'compose'
    || runningStage === 'subtitle'
    || runningStage === 'burn_subtitle'
    || runningStage === 'finalize'
    || stageStatusFromList.subtitle === 'running'
  const shouldFetchBurnSubtitleStageDetail =
    activeTab === 'compose'
    || runningStage === 'burn_subtitle'
    || runningStage === 'finalize'
    || stageStatusFromList.burn_subtitle === 'running'
  const shouldFetchFinalizeStageDetail =
    activeTab === 'compose'
    || runningStage === 'finalize'
    || stageStatusFromList.finalize === 'running'

  const { data: contentStage, refetch: refetchContentStage } = useQuery({
    queryKey: queryKeys.projectResources.stageDetail(projectId, 'content'),
    queryFn: () => fetchStageData(projectId, 'content'),
    enabled: !isNaN(projectId) && shouldFetchContentStageDetail,
  })

  const { data: storyboardStage, refetch: refetchStoryboardStage } = useQuery({
    queryKey: queryKeys.projectResources.stageDetail(projectId, 'storyboard'),
    queryFn: () => fetchStageData(projectId, 'storyboard'),
    enabled: !isNaN(projectId) && shouldFetchStoryboardStageDetail,
  })

  const { data: audioStage, refetch: refetchAudioStage } = useQuery({
    queryKey: queryKeys.projectResources.stageDetail(projectId, 'audio'),
    queryFn: () => fetchStageData(projectId, 'audio'),
    enabled: !isNaN(projectId) && shouldFetchAudioStageDetail,
  })

  const { data: referenceStage, refetch: refetchReferenceStage } = useQuery({
    queryKey: queryKeys.projectResources.stageDetail(projectId, 'reference'),
    queryFn: () => fetchStageData(projectId, 'reference'),
    enabled: !isNaN(projectId) && shouldFetchReferenceStageDetail,
  })

  const { data: videoStage, refetch: refetchVideoStage } = useQuery({
    queryKey: queryKeys.projectResources.stageDetail(projectId, 'video'),
    queryFn: () => fetchStageData(projectId, 'video'),
    enabled: !isNaN(projectId) && shouldFetchVideoStageDetail,
  })

  const { data: frameStage, refetch: refetchFrameStage } = useQuery({
    queryKey: queryKeys.projectResources.stageDetail(projectId, 'frame'),
    queryFn: () => fetchStageData(projectId, 'frame'),
    enabled: !isNaN(projectId) && shouldFetchFrameStageDetail,
  })

  const { data: composeStage, refetch: refetchComposeStage } = useQuery({
    queryKey: queryKeys.projectResources.stageDetail(projectId, 'compose'),
    queryFn: () => fetchStageData(projectId, 'compose'),
    enabled: !isNaN(projectId) && shouldFetchComposeStageDetail,
  })

  const { data: subtitleStage, refetch: refetchSubtitleStage } = useQuery({
    queryKey: queryKeys.projectResources.stageDetail(projectId, 'subtitle'),
    queryFn: () => fetchStageData(projectId, 'subtitle'),
    enabled: !isNaN(projectId) && shouldFetchSubtitleStageDetail,
  })

  const { data: burnSubtitleStage, refetch: refetchBurnSubtitleStage } = useQuery({
    queryKey: queryKeys.projectResources.stageDetail(projectId, 'burn_subtitle'),
    queryFn: () => fetchStageData(projectId, 'burn_subtitle'),
    enabled: !isNaN(projectId) && shouldFetchBurnSubtitleStageDetail,
  })

  const { data: finalizeStage, refetch: refetchFinalizeStage } = useQuery({
    queryKey: queryKeys.projectResources.stageDetail(projectId, 'finalize'),
    queryFn: () => fetchStageData(projectId, 'finalize'),
    enabled: !isNaN(projectId) && shouldFetchFinalizeStageDetail,
  })

  const { data: referenceLibraryData } = useQuery({
    queryKey: queryKeys.references.projectImportOptions,
    queryFn: () => api.references.list({ enabledOnly: true }),
    enabled: !isNaN(projectId) && activeTab === 'script',
  })
  const { data: textLibraryImportData } = useQuery({
    queryKey: queryKeys.textLibrary.projectImportOptions,
    queryFn: () => api.textLibrary.list({ enabledOnly: true, page: 1, pageSize: 100 }),
    enabled: !isNaN(projectId) && activeTab === 'script',
  })

  const refetchSingleStageDetail = useCallback((stage: BackendStageType) => {
    switch (stage) {
      case 'content':
        refetchContentStage()
        refetchReferenceStage()
        break
      case 'storyboard':
        refetchAudioStage()
        refetchStoryboardStage()
        refetchFrameStage()
        refetchVideoStage()
        refetchComposeStage()
        refetchSubtitleStage()
        refetchBurnSubtitleStage()
        refetchFinalizeStage()
        break
      case 'audio':
        refetchAudioStage()
        refetchComposeStage()
        refetchSubtitleStage()
        refetchBurnSubtitleStage()
        refetchFinalizeStage()
        break
      case 'reference':
        refetchReferenceStage()
        break
      case 'first_frame_desc':
        refetchStoryboardStage()
        refetchFrameStage()
        break
      case 'frame':
        refetchStoryboardStage()
        refetchFrameStage()
        break
      case 'video':
        refetchVideoStage()
        refetchComposeStage()
        refetchSubtitleStage()
        refetchBurnSubtitleStage()
        refetchFinalizeStage()
        break
      case 'compose':
        refetchComposeStage()
        break
      case 'subtitle':
        refetchSubtitleStage()
        break
      case 'burn_subtitle':
        refetchBurnSubtitleStage()
        break
      case 'finalize':
        refetchComposeStage()
        refetchSubtitleStage()
        refetchBurnSubtitleStage()
        refetchFinalizeStage()
        break
      default:
        break
    }
  }, [
    refetchContentStage,
    refetchStoryboardStage,
    refetchAudioStage,
    refetchReferenceStage,
    refetchFrameStage,
    refetchVideoStage,
    refetchComposeStage,
    refetchSubtitleStage,
    refetchBurnSubtitleStage,
    refetchFinalizeStage,
  ])

  const refetchStageScope = useCallback((stage: BackendStageType) => {
    refetchStages()
    refetchSingleStageDetail(stage)
  }, [refetchStages, refetchSingleStageDetail])

  const stageDataForInput = useMemo(() => {
    const contentOutput = (contentStage?.output_data || {}) as {
      roles?: Array<{ id?: string }>
    }
    const storyboardOutput = (storyboardStage?.output_data || {}) as {
      shots?: Array<{ speaker_id?: string }>
      references?: Array<{
        id?: string | number
        can_speak?: boolean
      } & ReferenceVoiceFields>
    }
    const referenceOutput = (referenceStage?.output_data || {}) as {
      references?: Array<{
        id?: string | number
        can_speak?: boolean
      } & ReferenceVoiceFields>
    }
    return {
      content: {
        roles: contentOutput.roles || [],
      },
      storyboard: {
        shots: storyboardOutput.shots || [],
      },
      reference: {
        references: referenceOutput.references || storyboardOutput.references || [],
      },
    }
  }, [contentStage?.output_data, storyboardStage?.output_data, referenceStage?.output_data])

  const {
    stopActiveStageStream,
    applyRunningStateFromStage,
    clearRunningState,
    runStage,
  } = useStageRunner({
    projectId,
    queryClient,
    settings,
    stageDataForInput,
    isRunning,
    runningStage,
    stageStreamDebugEnabled,
    activeStageEventSourceRef,
    activeFallbackPollingStopRef,
    lastCompletedItemsRef,
    lastItemCompleteRef,
    refetchStages,
    refetchProject,
    refetchSingleStageDetail,
    setIsRunning,
    setRunningStage,
    setRunningAction,
    setProgress,
    setProgressMessage,
    setCompletedItems,
    setTotalItems,
    setSkippedItems,
    setGeneratingShots,
    setRunningShotIndex,
    setRunningReferenceId: (value) => setRunningReferenceId(value),
  })

  const toStorageUrl = resolveStorageFileUrl

  const stageData = useMemo(() => buildStageData({
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
  }), [
    audioStage,
    burnSubtitleStage,
    composeStage,
    contentStage,
    frameStage,
    finalizeStage,
    referenceStage,
    storyboardStage,
    subtitleStage,
    toStorageUrl,
    videoStage,
  ])

  const hasStoryboardClearableOutputs = useMemo(() => {
    const storyboardShots = stageData?.storyboard?.shots || []
    const frameShots = stageData?.frame?.shots || []
    const videoShots = stageData?.video?.shots || []

    const hasVideoPrompts = storyboardShots.some((shot) => {
      const text = String(shot?.video_prompt || '').trim()
      return !!text
    })
    const hasFirstFrameDescriptions = storyboardShots.some((shot) => {
      const text = String(shot?.first_frame_description || '').trim()
      return !!text
    })
    const hasFirstFrameImages = frameShots.some((shot) => {
      const url = String(shot?.first_frame_url || '').trim()
      return !!url
    })
    const hasVideos = videoShots.some((shot) => {
      const url = String(shot?.video_url || '').trim()
      return !!url
    })

    return hasVideoPrompts || hasFirstFrameDescriptions || hasFirstFrameImages || hasVideos
  }, [stageData?.frame?.shots, stageData?.storyboard?.shots, stageData?.video?.shots])

  const effectiveScriptMode = useMemo<'custom' | 'single' | 'duo_podcast' | 'dialogue_script'>(() => {
    const projectVideoType = String(project?.video_type || '').trim()
    const projectScriptMode = resolveScriptModeFromVideoType(projectVideoType)
    if (
      projectVideoType === 'single_narration'
      || projectVideoType === 'duo_podcast'
      || projectVideoType === 'dialogue_script'
    ) {
      return projectScriptMode
    }
    const mode = String(
      stageData?.content?.script_mode || stageConfig.scriptMode || projectScriptMode || 'single'
    ).trim()
    if (mode === 'custom' || mode === 'duo_podcast' || mode === 'dialogue_script' || mode === 'single') {
      return mode
    }
    return 'single'
  }, [project?.video_type, stageConfig.scriptMode, stageData?.content?.script_mode])
  const effectiveStageConfig = useMemo<StageConfig>(() => ({
    ...stageConfig,
    scriptMode: effectiveScriptMode,
  }), [effectiveScriptMode, stageConfig])
  const contentGenerationEnabled = true
  const isSingleTakeEnabled = (effectiveStageConfig.singleTake ?? false) || effectiveScriptMode === 'duo_podcast'
  const effectiveUseFirstFrameRef = isSingleTakeEnabled ? true : (effectiveStageConfig.useFirstFrameRef ?? true)

  const hasReferenceData = useMemo(() => {
    const references = stageData?.reference?.references || stageData?.storyboard?.references || []
    return references.length > 0
  }, [stageData])
  const referenceNameById = useMemo(() => {
    const references = stageData?.reference?.references || stageData?.storyboard?.references || []
    const mapping = new Map<string, string>()
    references.forEach((reference) => {
      const referenceId = String(reference?.id || '').trim()
      if (!referenceId) return
      const referenceName = String(reference?.name || '').trim()
      if (referenceName) mapping.set(referenceId, referenceName)
    })
    return mapping
  }, [stageData?.reference?.references, stageData?.storyboard?.references])
  const lockedNarratorReferences = useMemo(() => {
    if (!contentGenerationEnabled) return []
    const references = stageData?.reference?.references || stageData?.storyboard?.references || []
    if (effectiveScriptMode === 'single') {
      return references.slice(0, 1)
        .map((reference, narratorIndex) => ({
          referenceId: String(reference?.id || '').trim(),
          reference,
          narratorIndex,
        }))
        .filter((item) => !!item.referenceId)
    }
    if (effectiveScriptMode === 'duo_podcast') {
      return references.slice(0, 2)
        .map((reference, narratorIndex) => ({
          referenceId: String(reference?.id || '').trim(),
          reference,
          narratorIndex,
      }))
        .filter((item) => !!item.referenceId)
    }
    return []
  }, [contentGenerationEnabled, effectiveScriptMode, stageData?.reference?.references, stageData?.storyboard?.references])
  const lockedDuoSceneReferenceId = useMemo(() => {
    if (!contentGenerationEnabled || effectiveScriptMode !== 'duo_podcast') return ''
    const references = stageData?.reference?.references || stageData?.storyboard?.references || []
    return String(references[2]?.id || '').trim()
  }, [contentGenerationEnabled, effectiveScriptMode, stageData?.reference?.references, stageData?.storyboard?.references])

  const stageCompletion = useMemo(() => computeStageCompletion(stageData, isSingleTakeEnabled), [isSingleTakeEnabled, stageData])

  const buildContentSyncSnapshot = useCallback((payload: unknown): ContentSyncSnapshot => {
    const data = asRecord(payload) || {}
    const rawRoles = Array.isArray(data.roles) ? data.roles : []
    const rawLines = Array.isArray(data.dialogue_lines) ? data.dialogue_lines : []
    const roles = rawRoles.map((item) => {
      const role = asRecord(item) || {}
      return {
        id: String(role.id || ''),
        name: String(role.name || ''),
      }
    })
    const dialogueLines = rawLines.map((item) => {
      const line = asRecord(item) || {}
      return {
        speaker_id: String(line.speaker_id || ''),
        speaker_name: String(line.speaker_name || ''),
        text: String(line.text || ''),
      }
    })
    return {
      roles,
      dialogue_lines: dialogueLines,
      content: String(data.content || ''),
    }
  }, [])

  const snapshotCurrentContent = useCallback((): ContentSyncSnapshot => {
    const currentOutput = (contentStage?.output_data || {}) as Record<string, unknown>
    return buildContentSyncSnapshot(currentOutput)
  }, [buildContentSyncSnapshot, contentStage?.output_data])

  const notifyIfContentSyncedByReferenceChange = useCallback(async (
    before: ContentSyncSnapshot
  ) => {
    const contentStageLatest = await api.stages.get(projectId, 'content')
    const after = buildContentSyncSnapshot(contentStageLatest?.output_data || {})
    const roleChanged = JSON.stringify(before.roles) !== JSON.stringify(after.roles)
    const lineChanged = JSON.stringify(before.dialogue_lines) !== JSON.stringify(after.dialogue_lines)
    const contentChanged = before.content !== after.content
    if (!roleChanged && !lineChanged && !contentChanged) return

    refetchStageScope('content')
    const changedParts: string[] = []
    if (roleChanged) changedParts.push('角色名称')
    if (lineChanged) changedParts.push('对白')
    if (contentChanged) changedParts.push('整段文案')
    toast.info(`参考区变更已同步到文案区：${changedParts.join('、')}`)
  }, [buildContentSyncSnapshot, projectId, refetchStageScope])

  const runReferenceMutationWithContentSync = useCallback(async <T,>(
    mutation: () => Promise<T>
  ): Promise<T> => {
    const contentSnapshotBefore = snapshotCurrentContent()
    const result = await mutation()
    refetchStageScope('reference')
    await notifyIfContentSyncedByReferenceChange(contentSnapshotBefore)
    return result
  }, [notifyIfContentSyncedByReferenceChange, refetchStageScope, snapshotCurrentContent])

  // Content editing handler
  const handleSaveContent = useCallback(async (data: {
    title?: string
    content?: string
    script_mode?: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'
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
  }) => {
    try {
      await api.stages.updateContent(projectId, data)
      refetchStageScope('content')
    } catch (error) {
      console.error('Failed to save content:', error)
      const message = error instanceof Error ? error.message : '保存失败'
      toast.error(message)
      throw error
    }
  }, [projectId, refetchStageScope])

  const handleContentChatSend = useCallback(async (message: string) => {
    const normalizedMessage = message.trim()
    if (!normalizedMessage) {
      toast.info('请输入文案需求后再发送')
      return
    }
    try {
      await runStage('content', effectiveStageConfig, {
        user_message: normalizedMessage,
      })
    } catch (error) {
      console.error('Failed to send content chat message:', error)
      toast.error('发送失败')
      throw error
    }
  }, [effectiveStageConfig, runStage])

  const handleContentChatReset = useCallback(async () => {
    try {
      await runStage('content', effectiveStageConfig, {
        reset_chat: true,
      })
    } catch (error) {
      console.error('Failed to reset content chat:', error)
      toast.error('重置失败')
      throw error
    }
  }, [effectiveStageConfig, runStage])

  const { handleNarratorStyleChange } = useProjectDetailNarratorSync({
    projectId,
    contentGenerationEnabled,
    effectiveScriptMode,
    lockedNarratorReferences,
    snapshotCurrentContent,
    notifyIfContentSyncedByReferenceChange,
    refetchStageScope,
    project,
    referenceStage,
    stageConfigStyle: stageConfig.style || '',
    stageConfigHydratedProjectIdRef,
  })

  const {
    handleDeleteContent,
    handleImportDialogue,
    handleSaveReference,
    handleDeleteReference,
    handleUploadReferenceImage,
    handleCreateReference,
    handleGenerateDescriptionFromImage,
    handleSaveFrameDescription,
    handleSaveFrameReferences,
    handleSaveVideoDescription,
    handleSaveVideoReferences,
    handleUploadFrameImage,
    handleDeleteFrameImage,
    handleSingleTakeModeTransition,
    handleDeleteVideo,
    handleClearAllAudio,
    handleClearAllFrameImages,
    handleClearAllVideos,
    handleClearAllShotContent,
    handleDeleteComposeVideo,
    handleInsertShots,
    handleMoveShot,
    handleDeleteShot,
    handleUpdateShot,
    handleUnlockContentByClearingShots,
    handleDeleteReferenceImage,
    handleImportReferencesFromLibrary,
    handleRegenerateReferenceImage,
    handleGenerateFrameDescription,
    handleGenerateVideoDescription,
    handleRegenerateFrameImage,
    handleReuseFirstFrameToOthers,
    handleRegenerateAudio,
    handleRegenerateVideo,
    handleSmartMergeShots,
    handleRunStageWithStoryboardConfirm,
  } = useProjectDetailStageActions({
    projectId,
    effectiveScriptMode,
    lockedDuoSceneReferenceId,
    lockedNarratorReferences,
    runReferenceMutationWithContentSync,
    stageConfig: effectiveStageConfig,
    refetchStageScope,
    referenceNameById,
    stageData,
    refetchFrameStage,
    refetchStages,
    refetchVideoStage,
    refetchComposeStage,
    refetchSubtitleStage,
    refetchBurnSubtitleStage,
    refetchFinalizeStage,
    refetchStoryboardStage,
    refetchAudioStage,
    settings,
    runStage,
    isSingleTakeEnabled,
    effectiveUseFirstFrameRef,
    hasStoryboardClearableOutputs,
  })

  const handleTitleChange = useCallback(async (newTitle: string) => {
    const updatedProject = await api.projects.update(projectId, { title: newTitle })
    projectRef.current = updatedProject
    queryClient.setQueryData<Project>(queryKeys.projects.detail(projectId), updatedProject)
    queryClient.setQueriesData<ProjectListResponse>(
      { queryKey: queryKeys.projects.listBase },
      (current) => {
        if (!current) return current
        return {
          ...current,
          items: current.items.map((item) => (
            item.id === updatedProject.id
              ? { ...item, ...updatedProject }
              : item
          )),
        }
      }
    )
    await queryClient.invalidateQueries({ queryKey: queryKeys.projects.listBase })
    toast.success('标题已更新')
  }, [projectId, queryClient])

  useEffect(() => {
    if (!project) {
      setProject(null)
      projectRef.current = null
      return
    }
    projectRef.current = project
    projectConfigDraftRef.current = normalizeProjectConfig(project.config)
    const projectScriptMode = resolveScriptModeFromVideoType(project.video_type)
    setProject({
      id: projectId,
      title: project.title,
      onTitleChange: handleTitleChange,
    })
    const shouldHydrateStageConfig = (
      stageConfigHydratedProjectIdRef.current !== project.id
      || stageConfigHydratedVideoTypeRef.current !== project.video_type
    )
    if (shouldHydrateStageConfig) {
      const persistedConfig = extractPersistedStageConfig(project.config)
      setStageConfig((prev) => {
        const hasProjectTargetDuration = (
          typeof project.target_duration === 'number'
          && Number.isFinite(project.target_duration)
        )
        const targetDurationFromProject = hasProjectTargetDuration
          ? project.target_duration
          : prev.targetDuration
        const hasProjectStyle = typeof project.style === 'string'
        const hasPersistedStyle = typeof persistedConfig.style === 'string'
        const normalizedProjectStyle = hasProjectStyle ? String(project.style).trim() : ''
        const normalizedPersistedStyle = hasPersistedStyle ? String(persistedConfig.style).trim() : ''
        const styleSource = hasPersistedStyle ? normalizedPersistedStyle : normalizedProjectStyle
        const resolvedStyle = normalizeNarratorStyleForMode(projectScriptMode, styleSource)
        const duoTargetDuration = (
          projectScriptMode === 'duo_podcast'
          && !hasProjectTargetDuration
        )
          ? 300
          : targetDurationFromProject
        const nextConfig: StageConfig = {
          ...prev,
          ...persistedConfig,
          style: resolvedStyle,
          ...(typeof duoTargetDuration === 'number' && Number.isFinite(duoTargetDuration)
            ? { targetDuration: duoTargetDuration }
            : {}),
          scriptMode: projectScriptMode,
          singleTake: projectScriptMode === 'duo_podcast'
            ? true
            : (
                typeof persistedConfig.singleTake === 'boolean'
                  ? persistedConfig.singleTake
                  : prev.singleTake
              ),
          useFirstFrameRef: projectScriptMode === 'duo_podcast'
            ? true
            : (
                typeof persistedConfig.useFirstFrameRef === 'boolean'
                  ? persistedConfig.useFirstFrameRef
                  : prev.useFirstFrameRef
              ),
        }
        stageConfigRef.current = nextConfig
        return nextConfig
      })
      stageConfigHydratedProjectIdRef.current = project.id
    }
    stageConfigHydratedVideoTypeRef.current = project.video_type
  }, [project, projectId, setProject, handleTitleChange])

  useEffect(() => {
    if (!project || !settings) return
    if (stageConfigHydratedProjectIdRef.current !== project.id) return
    if (llmAutoInitLockedProjectIdsRef.current.has(project.id)) return
    const persistedConfig = extractPersistedStageConfig(project.config)
    const persistedLlmProvider = String(persistedConfig.llmProvider || '').trim()
    const persistedLlmModel = String(persistedConfig.llmModel || '').trim()
    // Project-level LLM selection must stay independent once persisted.
    if (persistedLlmProvider || persistedLlmModel) {
      llmAutoInitLockedProjectIdsRef.current.add(project.id)
      return
    }

    const configuredProviders = (settings.llm_providers || [])
      .filter((provider) => String(provider.api_key || '').trim().length > 0)
      .filter((provider) => (provider.enabled_models || []).length > 0)
    if (configuredProviders.length === 0) return

    const providerById = new Map(configuredProviders.map((provider) => [provider.id, provider]))
    const currentConfig = stageConfigRef.current
    const defaultBinding = parseLlmModelBinding(settings.default_general_llm_model)

    let nextProviderId = String(currentConfig.llmProvider || '').trim()
    let nextModelId = String(currentConfig.llmModel || '').trim()
    const modelBinding = parseLlmModelBinding(nextModelId)
    if (modelBinding) {
      nextProviderId = nextProviderId || modelBinding.providerId
      nextModelId = modelBinding.modelId
    }

    const defaultProviderId = String(
      defaultBinding?.providerId
      || settings.default_llm_provider
      || configuredProviders[0]?.id
      || ''
    ).trim()
    const fallbackProvider = providerById.get(defaultProviderId) || configuredProviders[0]
    if (!fallbackProvider) return

    let shouldPersistMigration = false
    if (!nextProviderId || !providerById.has(nextProviderId)) {
      nextProviderId = fallbackProvider.id
      shouldPersistMigration = true
    }

    const selectedProvider = providerById.get(nextProviderId) || fallbackProvider
    const selectedEnabledModels = selectedProvider.enabled_models || []
    const providerDefaultModel = String(
      selectedProvider.default_model || selectedEnabledModels[0] || ''
    ).trim()
    const bindingPreferredModel = (
      selectedProvider.id === defaultBinding?.providerId
      && defaultBinding?.modelId
      && selectedEnabledModels.includes(defaultBinding.modelId)
    )
      ? defaultBinding.modelId
      : ''
    const fallbackModelId = String(bindingPreferredModel || providerDefaultModel).trim()

    if (!nextModelId || !selectedEnabledModels.includes(nextModelId)) {
      if (nextModelId !== fallbackModelId) {
        nextModelId = fallbackModelId
        shouldPersistMigration = true
      }
    }

    if (!shouldPersistMigration) {
      llmAutoInitLockedProjectIdsRef.current.add(project.id)
      return
    }

    handleStageConfigChange({
      ...currentConfig,
      llmProvider: nextProviderId,
      llmModel: nextModelId,
    })
    llmAutoInitLockedProjectIdsRef.current.add(project.id)
  }, [project, settings, handleStageConfigChange])

  useEffect(() => {
    if (!project || !settings) return
    if (stageConfigHydratedProjectIdRef.current !== project.id) return
    if (imageAutoInitLockedProjectIdsRef.current.has(project.id)) return
    const persistedConfig = extractPersistedStageConfig(project.config)
    const persistedImageProvider = String(persistedConfig.imageProvider || '').trim()
    const persistedImageModel = String(persistedConfig.imageModel || '').trim()
    const persistedFrameImageModel = String(persistedConfig.frameImageModel || '').trim()
    const persistedImagePreset = String(persistedConfig.imageWan2gpPreset || '').trim()
    const persistedImagePresetI2i = String(persistedConfig.imageWan2gpPresetI2i || '').trim()
    const currentConfig = stageConfigRef.current

    // Legacy repair: old versions used a single imageModel for both reference(t2i) and frame(i2i).
    // If it was polluted with i2i default, split it into reference=t2i default and frame=legacy value.
    if (
      persistedImageModel
      && !persistedFrameImageModel
      && String(persistedImageProvider || '').trim() !== 'wan2gp'
    ) {
      const resolvedProvider = String(
        persistedImageProvider
        || currentConfig.imageProvider
        || settings.default_image_provider
        || settings.image_providers?.[0]?.id
        || ''
      ).trim()
      if (resolvedProvider && resolvedProvider !== 'wan2gp') {
        const defaultT2iModel = String(getImageModel(resolvedProvider, settings, 't2i') || '').trim()
        const defaultI2iModel = String(getImageModel(resolvedProvider, settings, 'i2i') || '').trim()
        if (
          defaultT2iModel
          && defaultI2iModel
          && persistedImageModel === defaultI2iModel
          && persistedImageModel !== defaultT2iModel
        ) {
          handleStageConfigChange({
            ...currentConfig,
            imageProvider: resolvedProvider,
            imageModel: defaultT2iModel,
            frameImageModel: persistedImageModel,
          })
          imageAutoInitLockedProjectIdsRef.current.add(project.id)
          return
        }
      }
    }
    // Project-level image selection must stay independent once persisted.
    if (
      persistedImageProvider
      || persistedImageModel
      || persistedFrameImageModel
      || persistedImagePreset
      || persistedImagePresetI2i
    ) {
      imageAutoInitLockedProjectIdsRef.current.add(project.id)
      return
    }

    const configuredProviders = (settings.image_providers || [])
      .filter((provider) => String(provider.api_key || '').trim().length > 0)
      .filter((provider) => (provider.enabled_models || []).length > 0)
    const availableProviderIds = configuredProviders.map((provider) => provider.id)
    if (settings.wan2gp_available && !availableProviderIds.includes('wan2gp')) {
      availableProviderIds.push('wan2gp')
    }
    if (hasKlingCredentials(settings) && !availableProviderIds.includes('kling')) {
      availableProviderIds.push('kling')
    }
    if ((settings.vidu_api_key || '').trim() && !availableProviderIds.includes('vidu')) {
      availableProviderIds.push('vidu')
    }
    if (availableProviderIds.length === 0) return

    const providerById = new Map(configuredProviders.map((provider) => [provider.id, provider]))
    const defaultImageMode = (currentConfig.useReferenceConsistency ?? false) ? 'i2i' : 't2i'
    const defaultBinding = getDefaultImageModelBinding(settings, defaultImageMode)
    const referenceBinding = getDefaultImageModelBinding(settings, 't2i')

    let nextProviderId = String(currentConfig.imageProvider || '').trim()
    let nextReferenceModelId = String(currentConfig.imageModel || '').trim()
    let nextFrameModelId = String(currentConfig.frameImageModel || '').trim()
    let shouldPersistMigration = false

    const defaultProviderId = String(
      (defaultBinding?.providerId && availableProviderIds.includes(defaultBinding.providerId))
        ? defaultBinding.providerId
        : (
            availableProviderIds.includes(String(settings.default_image_provider || '').trim())
              ? String(settings.default_image_provider || '').trim()
              : availableProviderIds[0]
          )
    ).trim()

    if (!nextProviderId || !availableProviderIds.includes(nextProviderId)) {
      nextProviderId = defaultProviderId
      shouldPersistMigration = true
    }
    if (!nextProviderId) return

    if (nextProviderId === 'wan2gp') {
      const nextUpdates: Partial<StageConfig> = {
        imageProvider: 'wan2gp',
      }
      if (nextReferenceModelId) {
        nextReferenceModelId = ''
        nextUpdates.imageModel = ''
        shouldPersistMigration = true
      }
      if (nextFrameModelId) {
        nextFrameModelId = ''
        nextUpdates.frameImageModel = ''
        shouldPersistMigration = true
      }
      const t2iBinding = getDefaultImageModelBinding(settings, 't2i')
      const i2iBinding = getDefaultImageModelBinding(settings, 'i2i')
      if (
        t2iBinding?.providerId === 'wan2gp'
        && t2iBinding.modelId
        && String(currentConfig.imageWan2gpPreset || '').trim() !== t2iBinding.modelId
      ) {
        nextUpdates.imageWan2gpPreset = t2iBinding.modelId
        shouldPersistMigration = true
      }
      if (
        i2iBinding?.providerId === 'wan2gp'
        && i2iBinding.modelId
        && String(currentConfig.imageWan2gpPresetI2i || '').trim() !== i2iBinding.modelId
      ) {
        nextUpdates.imageWan2gpPresetI2i = i2iBinding.modelId
        shouldPersistMigration = true
      }
      if (!shouldPersistMigration) {
        imageAutoInitLockedProjectIdsRef.current.add(project.id)
        return
      }
      handleStageConfigChange({
        ...currentConfig,
        ...nextUpdates,
      })
      imageAutoInitLockedProjectIdsRef.current.add(project.id)
      return
    }

    const selectedProvider = providerById.get(nextProviderId)
    if (!selectedProvider) {
      if (nextProviderId === 'kling' || nextProviderId === 'vidu') {
        const fallbackReferenceModelId = getImageModel(nextProviderId, settings, 't2i')
        const fallbackFrameModelId = getImageModel(
          nextProviderId,
          settings,
          defaultImageMode
        )
        if (nextReferenceModelId !== fallbackReferenceModelId || nextFrameModelId !== fallbackFrameModelId) {
          shouldPersistMigration = true
        }
        if (!shouldPersistMigration) {
          imageAutoInitLockedProjectIdsRef.current.add(project.id)
          return
        }
        handleStageConfigChange({
          ...currentConfig,
          imageProvider: nextProviderId,
          imageModel: fallbackReferenceModelId,
          frameImageModel: fallbackFrameModelId,
        })
        imageAutoInitLockedProjectIdsRef.current.add(project.id)
        return
      }
      if (!shouldPersistMigration) {
        imageAutoInitLockedProjectIdsRef.current.add(project.id)
        return
      }
      handleStageConfigChange({
        ...currentConfig,
        imageProvider: nextProviderId,
      })
      imageAutoInitLockedProjectIdsRef.current.add(project.id)
      return
    }

    const selectedEnabledModels = selectedProvider.enabled_models || []
    const providerDefaultModel = String(
      selectedProvider.default_model || selectedEnabledModels[0] || ''
    ).trim()
    const referencePreferredModel = (
      selectedProvider.id === referenceBinding?.providerId
      && referenceBinding?.modelId
      && selectedEnabledModels.includes(referenceBinding.modelId)
    )
      ? referenceBinding.modelId
      : ''
    const bindingPreferredModel = (
      selectedProvider.id === defaultBinding?.providerId
      && defaultBinding?.modelId
      && selectedEnabledModels.includes(defaultBinding.modelId)
    )
      ? defaultBinding.modelId
      : ''
    const fallbackReferenceModelId = String(referencePreferredModel || providerDefaultModel).trim()
    const fallbackModelId = String(bindingPreferredModel || providerDefaultModel).trim()

    if (!nextReferenceModelId || !selectedEnabledModels.includes(nextReferenceModelId)) {
      if (nextReferenceModelId !== fallbackReferenceModelId) {
        nextReferenceModelId = fallbackReferenceModelId
        shouldPersistMigration = true
      }
    }
    if (!nextFrameModelId || !selectedEnabledModels.includes(nextFrameModelId)) {
      if (nextFrameModelId !== fallbackModelId) {
        nextFrameModelId = fallbackModelId
        shouldPersistMigration = true
      }
    }

    if (!shouldPersistMigration) {
      imageAutoInitLockedProjectIdsRef.current.add(project.id)
      return
    }

    handleStageConfigChange({
      ...currentConfig,
      imageProvider: nextProviderId,
      imageModel: nextReferenceModelId,
      frameImageModel: nextFrameModelId,
    })
    imageAutoInitLockedProjectIdsRef.current.add(project.id)
  }, [project, settings, handleStageConfigChange])

  useEffect(() => {
    return () => {
      setProject(null)
    }
  }, [setProject])

  const stageStatus: StageStatus = useMemo(() => {
    const baseStatus = stages.reduce((acc, s) => {
      const stageType = s.stage_type as BackendStageType
      acc[stageType] = s.status as 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
      return acc
    }, {} as StageStatus)

    const hasContentDetail = contentStage !== undefined
    const hasStoryboardDetail = storyboardStage !== undefined
    const hasAudioDetail = audioStage !== undefined
    const hasReferenceDetail = referenceStage !== undefined || storyboardStage !== undefined
    const hasFrameDetail = frameStage !== undefined
    const hasVideoDetail = videoStage !== undefined
    const hasComposeDetail = composeStage !== undefined
    const hasSubtitleDetail = subtitleStage !== undefined
    const hasBurnSubtitleDetail = burnSubtitleStage !== undefined
    const hasFinalizeDetail = finalizeStage !== undefined

    const normalizeStageStatusByData = (
      stage: keyof StageStatus,
      hasDetail: boolean,
      isReady: boolean
    ) => {
      if (!hasDetail) return

      // Data completeness has higher priority than stale failed status.
      // Keep running state untouched so current execution still shows as running.
      if (isReady) {
        if (baseStatus[stage] !== 'running') {
          baseStatus[stage] = 'completed'
        }
        return
      }

      if (baseStatus[stage] === 'completed') {
        baseStatus[stage] = 'pending'
      }
    }

    normalizeStageStatusByData('content', hasContentDetail, stageCompletion.contentReady)
    normalizeStageStatusByData('storyboard', hasStoryboardDetail, stageCompletion.storyboardReady)
    normalizeStageStatusByData('first_frame_desc', hasFrameDetail, stageCompletion.firstFrameDescReady)
    normalizeStageStatusByData('audio', hasAudioDetail, stageCompletion.audioReady)
    normalizeStageStatusByData('frame', hasFrameDetail, stageCompletion.frameReady)
    normalizeStageStatusByData('video', hasVideoDetail, stageCompletion.videoReady)
    normalizeStageStatusByData('compose', hasComposeDetail, stageCompletion.composeReady)
    normalizeStageStatusByData('subtitle', hasSubtitleDetail, stageCompletion.subtitleReady)
    normalizeStageStatusByData('burn_subtitle', hasBurnSubtitleDetail, stageCompletion.burnSubtitleReady)
    normalizeStageStatusByData('finalize', hasFinalizeDetail, stageCompletion.finalizeReady)
    normalizeStageStatusByData('reference', hasReferenceDetail, stageCompletion.referenceInfoReady)

    return baseStatus
  }, [
    stages,
    stageCompletion,
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
  ])

  const runningStageFromBackend = useMemo<BackendStageType | undefined>(() => {
    const runningStages = stages
      .filter((one) => one.status === 'running')
      .sort((a, b) => a.stage_number - b.stage_number)
    return runningStages[0]?.stage_type as BackendStageType | undefined
  }, [stages])

  useEffect(() => {
    if (!runningStageFromBackend || Number.isNaN(projectId)) return
    if (activeStageEventSourceRef.current || activeFallbackPollingStopRef.current) return

    let stopped = false
    let timeoutId: ReturnType<typeof setTimeout> | null = null

    const syncRunningStage = async () => {
      if (stopped) return
      try {
        const stageData = await api.stages.get(projectId, runningStageFromBackend)
        if (stopped) return

        const withinManualCancelSuppress = Date.now() < manualCancelSuppressUntilRef.current
        if (withinManualCancelSuppress) {
          if (stageData.status === 'running' || stageData.status === 'pending') {
            timeoutId = setTimeout(syncRunningStage, 1200)
            return
          }
        }

        if (stageData.status === 'running') {
          applyRunningStateFromStage(runningStageFromBackend, stageData)

          timeoutId = setTimeout(syncRunningStage, 1200)
          return
        }
        if (stageData.status === 'pending') {
          timeoutId = setTimeout(syncRunningStage, 1200)
          return
        }

        if (runningStage === runningStageFromBackend) {
          clearRunningState()
          setGeneratingShots(undefined)
        }
        refetchStages()
        refetchProject()
      } catch (error) {
        if (stageStreamDebugEnabled) {
          console.warn('[Stage Recovery Poll][ERROR]', {
            stage: runningStageFromBackend,
            projectId,
            error,
          })
        }
        timeoutId = setTimeout(syncRunningStage, 1500)
      }
    }

    void syncRunningStage()
    return () => {
      stopped = true
      if (timeoutId) clearTimeout(timeoutId)
    }
  }, [
    applyRunningStateFromStage,
    clearRunningState,
    projectId,
    runningStageFromBackend,
    runningStage,
    refetchStages,
    refetchProject,
    stageStreamDebugEnabled,
  ])

  const formatResearchDisplayContent = useCallback((raw: string): string => {
    return String(raw || '').replace(/\r\n/g, '\n')
  }, [])
  const {
    handleSearch,
    handleAddText,
    handleToggleSelected,
    handleDeleteSource,
    handleImportFromTextLibrary,
    handleCancelAllRunningTasks,
  } = useProjectDetailSourceActions({
    projectId,
    isRunning,
    isSearching,
    runningStage,
    stageConfig,
    activeSearchEventSourceRef,
    manualCancelSuppressUntilRef,
    createSourceMutation,
    updateSourceMutation,
    deleteSourceMutation,
    importFromTextLibraryMutation,
    cancelRunningTasksMutation,
    stopActiveStageStream,
    refetchStages,
    refetchProject,
    refetchSingleStageDetail,
    setIsSearching,
    setIsRunning,
    setRunningStage,
    setRunningAction,
    setRunningShotIndex,
    setRunningReferenceId,
    setGeneratingShots,
    setCompletedItems,
    setTotalItems,
    setSkippedItems,
    setProgress,
    setProgressMessage,
    stageStreamDebugEnabled,
    formatResearchDisplayContent,
  })

  const referenceStageStatus = referenceStage?.status || stageStatusFromList.reference
  const frameStageStatus = frameStage?.status || stageStatusFromList.frame
  const videoStageStatus = videoStage?.status || stageStatusFromList.video
  const libraryReferences = (referenceLibraryData?.items || []) as ReferenceLibraryItem[]
  const textLibraryItems = (textLibraryImportData?.items || []) as TextLibraryItem[]
  const cancelIsPending = cancelRunningTasksMutation.isPending
  const includeSubtitleForDelivery = effectiveStageConfig.includeSubtitle !== false
  const composeVideoUrl = includeSubtitleForDelivery
    ? (
        stageData?.finalize?.video_url
        || stageData?.burn_subtitle?.video_url
      )
    : (
        stageData?.finalize?.video_url
        || stageData?.compose?.video_url
      )
  const contentScriptMode = stageData?.content?.script_mode

  return {
    projectLoading,
    project,
    activeTab,
    setActiveTab,
    isRunning,
    runningStage,
    runningAction,
    progress,
    progressMessage,
    completedItems,
    totalItems,
    skippedItems,
    generatingShots,
    runningShotIndex,
    runningReferenceId,
    isSearching,
    stageConfig: effectiveStageConfig,
    handleStageConfigChange,
    sources,
    stageData,
    stageStatus,
    stageCompletion,
    settings,
    stageStatusFromList,
    isSingleTakeEnabled,
    effectiveUseFirstFrameRef,
    hasReferenceData,
    effectiveScriptMode,
    stageDataForInput,
    toStorageUrl,
    referenceStageStatus,
    frameStageStatus,
    videoStageStatus,
    libraryReferences,
    textLibraryItems,
    cancelIsPending,
    composeVideoUrl,
    contentScriptMode,
    handleSearch,
    handleAddText,
    handleImportFromTextLibrary,
    handleToggleSelected,
    handleDeleteSource,
    handleSaveContent,
    handleContentChatSend,
    handleContentChatReset,
    handleDeleteContent,
    handleUnlockContentByClearingShots,
    handleImportDialogue,
    handleSaveReference,
    handleDeleteReference,
    handleUploadReferenceImage,
    handleCreateReference,
    handleGenerateDescriptionFromImage,
    handleSaveFrameDescription,
    handleSaveFrameReferences,
    handleSaveVideoDescription,
    handleSaveVideoReferences,
    handleUploadFrameImage,
    handleDeleteFrameImage,
    handleSingleTakeModeTransition,
    handleDeleteVideo,
    handleClearAllAudio,
    handleClearAllFrameImages,
    handleClearAllVideos,
    handleClearAllShotContent,
    handleInsertShots,
    handleMoveShot,
    handleDeleteShot,
    handleUpdateShot,
    handleDeleteComposeVideo,
    handleDeleteReferenceImage,
    handleImportReferencesFromLibrary,
    handleRegenerateReferenceImage,
    handleGenerateFrameDescription,
    handleGenerateVideoDescription,
    handleRegenerateFrameImage,
    handleReuseFirstFrameToOthers,
    handleRegenerateAudio,
    handleRegenerateVideo,
    handleSmartMergeShots,
    handleCancelAllRunningTasks,
    handleRunStageWithStoryboardConfirm,
    handleNarratorStyleChange,
  }
}
