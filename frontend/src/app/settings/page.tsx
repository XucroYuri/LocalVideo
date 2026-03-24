'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Loader2 } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'

import { api } from '@/lib/api-client'
import { hasKlingCredentials } from '@/lib/kling'
import { queryKeys } from '@/lib/query-keys'
import { Button } from '@/components/ui/button'

import { VideoProviderCard } from '@/components/settings/video-provider-card'
import { ImageProviderCard } from '@/components/settings/image-provider-card'
import { useSettingsBundle } from '@/hooks/use-settings-queries'
import type {
  ImageProviderConfig,
  JinaReaderUsage,
  LLMProviderConfig,
  SettingsUpdate,
  TavilyUsage,
} from '@/types/settings'
import {
  isVideoProviderId,
} from './video-provider-adapters'
import { SettingsDefaultModelsSection } from './settings-default-models-section'
import { SettingsLlmProviderSection } from './settings-llm-provider-section'
import { SettingsSearchProviderSection } from './settings-search-provider-section'
import { SettingsLocalModelDependencySection } from './settings-local-model-dependency-section'
import { SettingsSpeechRecognitionSection } from './settings-speech-recognition-section'
import { SettingsAudioProviderSection } from './settings-audio-provider-section'
import { SettingsWebParserSection } from './settings-web-parser-section'
import { SettingsVideoDownloaderSection } from './settings-video-downloader-section'

export const dynamic = 'force-dynamic'

const FASTER_WHISPER_MODEL_OPTIONS = ['tiny', 'base', 'small', 'medium', 'large-v1', 'large-v2', 'large-v3'] as const

type SettingsPrimaryTabId =
  | 'default_models'
  | 'local_models'
  | 'external_links'
  | 'search'
  | 'llm'
  | 'speech'
  | 'audio'
  | 'image'
  | 'video'

interface SettingsNavigationItem {
  id: SettingsPrimaryTabId
  label: string
}

const SETTINGS_NAVIGATION: SettingsNavigationItem[] = [
  { id: 'default_models', label: '默认模型 & 服务' },
  { id: 'local_models', label: '本地环境配置' },
  { id: 'external_links', label: '外部链接解析' },
  { id: 'search', label: '搜索' },
  { id: 'llm', label: 'LLM' },
  { id: 'speech', label: '语音识别' },
  { id: 'audio', label: '音频生成' },
  { id: 'image', label: '图像生成' },
  { id: 'video', label: '视频生成' },
]

const BUILTIN_VOLCENGINE_LLM_PROVIDER_ID = 'builtin_volcengine'
const BUILTIN_VOLCENGINE_SEEDREAM_PROVIDER_ID = 'builtin_volcengine_seedream'
const BUILTIN_MINIMAX_LLM_PROVIDER_ID = 'builtin_minimax'
const BUILTIN_XIAOMI_MIMO_LLM_PROVIDER_ID = 'builtin_xiaomi_mimo'

function syncVolcengineLlmProvider(
  providers: LLMProviderConfig[],
  apiKey: string
): LLMProviderConfig[] {
  if (providers.length === 0) return providers
  let updated = false
  const nextProviders = providers.map((provider) => {
    if (provider.id !== BUILTIN_VOLCENGINE_LLM_PROVIDER_ID) return provider
    updated = true
    return {
      ...provider,
      api_key: apiKey,
    }
  })
  return updated ? nextProviders : providers
}

function syncVolcengineSeedreamProvider(
  providers: ImageProviderConfig[],
  apiKey: string
): ImageProviderConfig[] {
  if (providers.length === 0) return providers
  let updated = false
  const nextProviders = providers.map((provider) => {
    if (provider.id !== BUILTIN_VOLCENGINE_SEEDREAM_PROVIDER_ID) return provider
    updated = true
    return {
      ...provider,
      api_key: apiKey,
    }
  })
  return updated ? nextProviders : providers
}

function findVolcengineSeedreamProvider(
  providers: ImageProviderConfig[] | undefined
): ImageProviderConfig | undefined {
  return providers?.find((provider) => provider.id === BUILTIN_VOLCENGINE_SEEDREAM_PROVIDER_ID)
}

function findVolcengineLlmProvider(
  providers: LLMProviderConfig[] | undefined
): LLMProviderConfig | undefined {
  return providers?.find((provider) => provider.id === BUILTIN_VOLCENGINE_LLM_PROVIDER_ID)
}

function syncXiaomiMimoLlmProvider(
  providers: LLMProviderConfig[],
  apiKey: string
): LLMProviderConfig[] {
  if (providers.length === 0) return providers
  let updated = false
  const nextProviders = providers.map((provider) => {
    if (provider.id !== BUILTIN_XIAOMI_MIMO_LLM_PROVIDER_ID) return provider
    updated = true
    return {
      ...provider,
      api_key: apiKey,
    }
  })
  return updated ? nextProviders : providers
}

function findXiaomiMimoLlmProvider(
  providers: LLMProviderConfig[] | undefined
): LLMProviderConfig | undefined {
  return providers?.find((provider) => provider.id === BUILTIN_XIAOMI_MIMO_LLM_PROVIDER_ID)
}

function syncMinimaxLlmProvider(
  providers: LLMProviderConfig[],
  apiKey: string
): LLMProviderConfig[] {
  if (providers.length === 0) return providers
  let updated = false
  const nextProviders = providers.map((provider) => {
    if (provider.id !== BUILTIN_MINIMAX_LLM_PROVIDER_ID) return provider
    updated = true
    return {
      ...provider,
      api_key: apiKey,
    }
  })
  return updated ? nextProviders : providers
}

function findMinimaxLlmProvider(
  providers: LLMProviderConfig[] | undefined
): LLMProviderConfig | undefined {
  return providers?.find((provider) => provider.id === BUILTIN_MINIMAX_LLM_PROVIDER_ID)
}

export default function SettingsPage() {
  const router = useRouter()
  const queryClient = useQueryClient()
  const [showApiKeys, setShowApiKeys] = useState<Record<string, boolean>>({})
  const [activePrimaryTab, setActivePrimaryTab] = useState<SettingsPrimaryTabId>('default_models')

  const [isFetchingJinaReaderUsage, setIsFetchingJinaReaderUsage] = useState(false)
  const [isValidatingXhsDownloader, setIsValidatingXhsDownloader] = useState(false)
  const [isValidatingTiktokDownloader, setIsValidatingTiktokDownloader] = useState(false)
  const [isValidatingKsDownloader, setIsValidatingKsDownloader] = useState(false)
  const [isValidatingWan2gp, setIsValidatingWan2gp] = useState(false)
  const [isTestingFasterWhisper, setIsTestingFasterWhisper] = useState(false)
  const [isTestingVolcengineSpeechRecognition, setIsTestingVolcengineSpeechRecognition] = useState(false)
  const [isValidatingCrawl4ai, setIsValidatingCrawl4ai] = useState(false)
  const [isCheckingTavilyUsage, setIsCheckingTavilyUsage] = useState(false)
  const [hasAutoSaved, setHasAutoSaved] = useState(false)
  const [jinaReaderUsage, setJinaReaderUsage] = useState<JinaReaderUsage | null>(null)
  const [tavilyUsage, setTavilyUsage] = useState<TavilyUsage | null>(null)

  const {
    settings,
    isSettingsLoading: isLoading,
    wan2gpImagePresets: wan2gpPresets,
    wan2gpVideoPresetData,
    wan2gpAudioPresets,
    activeVoiceLibraryItems,
  } = useSettingsBundle({
    includeWan2gpVideoPresets: true,
    includeWan2gpAudioPresets: true,
    includeActiveVoiceLibrary: true,
  })

  const { mutate: saveSettings, isPending: isSavingSettings } = useMutation({
    mutationFn: (data: SettingsUpdate) => api.settings.update(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.settings.root })
      setHasAutoSaved(true)
    },
    onError: (error) => {
      toast.error(`保存失败: ${error.message}`)
    },
  })

  const [formData, setFormData] = useState<SettingsUpdate>({})
  const updateField = useCallback(<K extends keyof SettingsUpdate>(key: K, value: SettingsUpdate[K]) => {
    setHasAutoSaved(false)
    setFormData((prev) => {
      const next: SettingsUpdate = { ...prev, [key]: value }

      if (key === 'volcengine_tts_app_key') {
        next.speech_volcengine_app_key = value as SettingsUpdate['speech_volcengine_app_key']
      } else if (key === 'speech_volcengine_app_key') {
        next.volcengine_tts_app_key = value as SettingsUpdate['volcengine_tts_app_key']
      } else if (key === 'volcengine_tts_access_key') {
        next.speech_volcengine_access_key = value as SettingsUpdate['speech_volcengine_access_key']
      } else if (key === 'speech_volcengine_access_key') {
        next.volcengine_tts_access_key = value as SettingsUpdate['volcengine_tts_access_key']
      } else if (key === 'video_seedance_api_key') {
        const baseImageProviders = prev.image_providers ?? settings?.image_providers ?? []
        const baseLlmProviders = prev.llm_providers ?? settings?.llm_providers ?? []
        next.image_providers = syncVolcengineSeedreamProvider(
          baseImageProviders,
          String(value ?? '')
        )
        next.llm_providers = syncVolcengineLlmProvider(
          baseLlmProviders,
          String(value ?? '')
        )
      } else if (key === 'image_providers') {
        const seedreamProvider = findVolcengineSeedreamProvider(value as ImageProviderConfig[] | undefined)
        if (seedreamProvider) {
          next.video_seedance_api_key = seedreamProvider.api_key
          const baseLlmProviders = prev.llm_providers ?? settings?.llm_providers ?? []
          next.llm_providers = syncVolcengineLlmProvider(baseLlmProviders, seedreamProvider.api_key)
        }
      } else if (key === 'xiaomi_mimo_api_key') {
        const baseLlmProviders = prev.llm_providers ?? settings?.llm_providers ?? []
        next.llm_providers = syncXiaomiMimoLlmProvider(
          baseLlmProviders,
          String(value ?? '')
        )
      } else if (key === 'minimax_api_key') {
        const baseLlmProviders = prev.llm_providers ?? settings?.llm_providers ?? []
        next.llm_providers = syncMinimaxLlmProvider(
          baseLlmProviders,
          String(value ?? '')
        )
      } else if (key === 'llm_providers') {
        const volcengineProvider = findVolcengineLlmProvider(value as LLMProviderConfig[] | undefined)
        if (volcengineProvider) {
          next.video_seedance_api_key = volcengineProvider.api_key
          const baseImageProviders = prev.image_providers ?? settings?.image_providers ?? []
          next.image_providers = syncVolcengineSeedreamProvider(baseImageProviders, volcengineProvider.api_key)
        }
        const minimaxProvider = findMinimaxLlmProvider(value as LLMProviderConfig[] | undefined)
        if (minimaxProvider) {
          next.minimax_api_key = minimaxProvider.api_key
        }
        const xiaomiMimoProvider = findXiaomiMimoLlmProvider(value as LLMProviderConfig[] | undefined)
        if (xiaomiMimoProvider) {
          next.xiaomi_mimo_api_key = xiaomiMimoProvider.api_key
        }
      }

      return next
    })
  }, [settings?.image_providers, settings?.llm_providers])
  const llmProviders: LLMProviderConfig[] = useMemo(
    () => formData.llm_providers ?? settings?.llm_providers ?? [],
    [formData.llm_providers, settings?.llm_providers]
  )
  const imageProviders: ImageProviderConfig[] = useMemo(
    () => formData.image_providers ?? settings?.image_providers ?? [],
    [formData.image_providers, settings?.image_providers]
  )
  const llmProviderIds = llmProviders.map((provider) => provider.id)
  const imageProviderIds = imageProviders.map((provider) => provider.id)
  const rawSelectedLlmProvider = formData.default_llm_provider ?? settings?.default_llm_provider ?? ''
  const selectedLlmProvider = llmProviderIds.includes(rawSelectedLlmProvider)
    ? rawSelectedLlmProvider
    : (llmProviders[0]?.id || '')
  const rawSelectedSearchProvider = formData.default_search_provider ?? settings?.default_search_provider
  const selectedSearchProvider = rawSelectedSearchProvider === 'tavily' ? rawSelectedSearchProvider : 'tavily'
  const rawSelectedAudioProvider = formData.default_audio_provider ?? settings?.default_audio_provider ?? 'edge_tts'
  const rawSelectedImageProvider = formData.default_image_provider ?? settings?.default_image_provider ?? ''
  const hasKlingConfig = hasKlingCredentials({
    kling_access_key: formData.kling_access_key ?? settings?.kling_access_key,
    kling_secret_key: formData.kling_secret_key ?? settings?.kling_secret_key,
  })
  const viduApiKey = String(formData.vidu_api_key ?? settings?.vidu_api_key ?? '').trim()
  const minimaxApiKey = String(formData.minimax_api_key ?? settings?.minimax_api_key ?? '').trim()
  const xiaomiMimoApiKey = String(formData.xiaomi_mimo_api_key ?? settings?.xiaomi_mimo_api_key ?? '').trim()
  const volcengineTtsAppKey = String(formData.volcengine_tts_app_key ?? settings?.volcengine_tts_app_key ?? '').trim()
  const volcengineTtsAccessKey = String(formData.volcengine_tts_access_key ?? settings?.volcengine_tts_access_key ?? '').trim()
  const selectableAudioProviderIds = [
    'edge_tts',
    ...(settings?.wan2gp_available ? ['wan2gp'] : []),
    ...(volcengineTtsAppKey && volcengineTtsAccessKey ? ['volcengine_tts'] : []),
    ...(hasKlingConfig ? ['kling_tts'] : []),
    ...(viduApiKey ? ['vidu_tts'] : []),
    ...(minimaxApiKey ? ['minimax_tts'] : []),
    ...(xiaomiMimoApiKey ? ['xiaomi_mimo_tts'] : []),
  ]
  const selectedAudioProvider = selectableAudioProviderIds.includes(rawSelectedAudioProvider)
    ? rawSelectedAudioProvider
    : selectableAudioProviderIds[0]
  const selectableImageProviderIds = [
    ...imageProviderIds,
    ...(settings?.wan2gp_available ? ['wan2gp'] : []),
    ...(hasKlingConfig ? ['kling'] : []),
    ...(viduApiKey ? ['vidu'] : []),
  ]
  const selectedImageProvider = selectableImageProviderIds.includes(rawSelectedImageProvider)
    ? rawSelectedImageProvider
    : (selectableImageProviderIds[0] || imageProviders[0]?.id || '')
  const rawSelectedVideoProvider = formData.default_video_provider ?? settings?.default_video_provider
  const selectableVideoProviderIds = [
    ...(String(formData.video_seedance_api_key ?? settings?.video_seedance_api_key ?? '').trim() ? ['volcengine_seedance'] : []),
    ...(settings?.wan2gp_available ? ['wan2gp'] : []),
  ]
  const selectedVideoProvider = (
    isVideoProviderId(rawSelectedVideoProvider)
    && selectableVideoProviderIds.includes(rawSelectedVideoProvider)
  )
    ? rawSelectedVideoProvider
    : (selectableVideoProviderIds[0] || 'volcengine_seedance')
  const rawSelectedSpeechRecognitionProvider = (
    formData.default_speech_recognition_provider
    ?? settings?.default_speech_recognition_provider
    ?? 'faster_whisper'
  ).trim()
  const selectedSpeechRecognitionProvider = rawSelectedSpeechRecognitionProvider === 'volcengine_asr'
    ? 'volcengine_asr'
    : 'faster_whisper'
  const buildSettingsPayload = useCallback((source: SettingsUpdate): SettingsUpdate => ({
    ...source,
    default_llm_provider: source.default_llm_provider ?? (selectedLlmProvider || llmProviders[0]?.id),
    default_search_provider: source.default_search_provider ?? selectedSearchProvider,
    default_audio_provider: source.default_audio_provider ?? selectedAudioProvider,
    default_speech_recognition_provider: source.default_speech_recognition_provider ?? selectedSpeechRecognitionProvider,
    default_image_provider: source.default_image_provider ?? selectedImageProvider,
    default_video_provider: isVideoProviderId(source.default_video_provider)
      ? source.default_video_provider
      : selectedVideoProvider,
    video_seedance_watermark: false,
  }), [
    selectedAudioProvider,
    selectedImageProvider,
    selectedLlmProvider,
    llmProviders,
    selectedSearchProvider,
    selectedSpeechRecognitionProvider,
    selectedVideoProvider,
  ])

  const selectedFasterWhisperModel = (
    formData.faster_whisper_model
    ?? settings?.faster_whisper_model
    ?? 'large-v3'
  )

  useEffect(() => {
    if (!settings) return
    if (Object.keys(formData).length === 0) return

    const timer = window.setTimeout(() => {
      saveSettings(buildSettingsPayload(formData))
    }, 500)

    return () => window.clearTimeout(timer)
  }, [buildSettingsPayload, formData, saveSettings, settings])

  const handleFetchTavilyUsage = async () => {
    setIsCheckingTavilyUsage(true)
    try {
      const usage = await api.settings.getTavilyUsage()
      setTavilyUsage(usage)
      if (usage.available) {
        toast.success('已获取 Tavily 额度信息')
      } else {
        toast.error('当前 Tavily 不可用')
      }
    } catch (error) {
      setTavilyUsage(null)
      toast.error(error instanceof Error ? error.message : '获取 Tavily 额度失败')
    } finally {
      setIsCheckingTavilyUsage(false)
    }
  }

  const handleBack = useCallback(() => {
    if (typeof window === 'undefined') {
      router.push('/')
      return
    }
    if (window.history.length > 1) {
      router.back()
      return
    }
    router.push('/')
  }, [router])

  const toggleApiKeyVisibility = (key: string) => {
    setShowApiKeys((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  const handleValidateWan2gp = async () => {
    const wan2gpPath = (formData.wan2gp_path ?? settings?.wan2gp_path ?? '').trim()
    const localModelPythonPath = (formData.local_model_python_path ?? settings?.local_model_python_path ?? '').trim()

    if (!wan2gpPath) {
      toast.error('请先填写 Wan2GP 路径')
      return
    }
    if (!localModelPythonPath) {
      toast.error('请先填写共享本地 Python 路径')
      return
    }

    setIsValidatingWan2gp(true)
    try {
      await api.settings.update({
        wan2gp_path: wan2gpPath,
        local_model_python_path: localModelPythonPath,
      })
      const result = await api.settings.validateWan2gp({
        wan2gp_path: wan2gpPath,
        local_model_python_path: localModelPythonPath || undefined,
      })
      toast.success(`校验通过: ${result.python_path} (torch ${result.torch_version})。设置会自动保存并生效。`)
    } catch (error) {
      toast.error(`校验失败: ${error instanceof Error ? error.message : '未知错误'}`)
    } finally {
      queryClient.invalidateQueries({ queryKey: queryKeys.settings.root })
      setIsValidatingWan2gp(false)
    }
  }

  const handleFetchJinaReaderUsage = async () => {
    const jinaReaderApiKey = (formData.jina_reader_api_key ?? settings?.jina_reader_api_key ?? '').trim()
    const hasApiKey = jinaReaderApiKey.length > 0

    setIsFetchingJinaReaderUsage(true)
    try {
      if (hasApiKey) {
        await api.settings.update({
          jina_reader_api_key: jinaReaderApiKey,
        })
      }
      const result = await api.settings.getJinaReaderUsage({
        jina_reader_api_key: hasApiKey ? jinaReaderApiKey : undefined,
      })
      setJinaReaderUsage(result)
      if (!result.available) {
        toast.error('查询失败：当前 key 不可用')
      } else if (!hasApiKey) {
        toast.success('Jina Reader 免费模式校验通过')
      } else {
        toast.success('已获取 Jina Reader 额度信息')
      }
    } catch (error) {
      setJinaReaderUsage(null)
      toast.error(`查询失败: ${error instanceof Error ? error.message : '未知错误'}`)
    } finally {
      queryClient.invalidateQueries({ queryKey: queryKeys.settings.root })
      setIsFetchingJinaReaderUsage(false)
    }
  }

  const handleValidateXhsDownloader = async () => {
    const xhsDownloaderPath = (formData.xhs_downloader_path ?? settings?.xhs_downloader_path ?? '').trim()

    if (!xhsDownloaderPath) {
      toast.error('请先填写 XHS-Downloader 路径')
      return
    }

    setIsValidatingXhsDownloader(true)
    try {
      await api.settings.update({
        xhs_downloader_path: xhsDownloaderPath,
      })
      const result = await api.settings.validateXhsDownloader({
        xhs_downloader_path: xhsDownloaderPath,
      })
      toast.success(`校验通过: ${result.uv_path} (${result.entry})。设置会自动保存并生效。`)
    } catch (error) {
      toast.error(`校验失败: ${error instanceof Error ? error.message : '未知错误'}`)
    } finally {
      queryClient.invalidateQueries({ queryKey: queryKeys.settings.root })
      setIsValidatingXhsDownloader(false)
    }
  }

  const handleValidateTiktokDownloader = async () => {
    const tiktokDownloaderPath = (formData.tiktok_downloader_path ?? settings?.tiktok_downloader_path ?? '').trim()

    if (!tiktokDownloaderPath) {
      toast.error('请先填写 TikTokDownloader 路径')
      return
    }

    setIsValidatingTiktokDownloader(true)
    try {
      await api.settings.update({
        tiktok_downloader_path: tiktokDownloaderPath,
      })
      const result = await api.settings.validateTiktokDownloader({
        tiktok_downloader_path: tiktokDownloaderPath,
      })
      toast.success(`校验通过: ${result.uv_path} (${result.entry})。设置会自动保存并生效。`)
    } catch (error) {
      toast.error(`校验失败: ${error instanceof Error ? error.message : '未知错误'}`)
    } finally {
      queryClient.invalidateQueries({ queryKey: queryKeys.settings.root })
      setIsValidatingTiktokDownloader(false)
    }
  }

  const handleValidateKsDownloader = async () => {
    const ksDownloaderPath = (formData.ks_downloader_path ?? settings?.ks_downloader_path ?? '').trim()

    if (!ksDownloaderPath) {
      toast.error('请先填写 KS-Downloader 路径')
      return
    }

    setIsValidatingKsDownloader(true)
    try {
      await api.settings.update({
        ks_downloader_path: ksDownloaderPath,
      })
      const result = await api.settings.validateKsDownloader({
        ks_downloader_path: ksDownloaderPath,
      })
      toast.success(`校验通过: ${result.uv_path} (${result.entry})。设置会自动保存并生效。`)
    } catch (error) {
      toast.error(`校验失败: ${error instanceof Error ? error.message : '未知错误'}`)
    } finally {
      queryClient.invalidateQueries({ queryKey: queryKeys.settings.root })
      setIsValidatingKsDownloader(false)
    }
  }

  const handleTestFasterWhisper = async () => {
    const model = selectedFasterWhisperModel || 'large-v3'
    const deploymentProfile = (formData.deployment_profile ?? settings?.deployment_profile ?? 'cpu').trim()
    const localModelPythonPath = (formData.local_model_python_path ?? settings?.local_model_python_path ?? '').trim()

    if (deploymentProfile === 'gpu' && !localModelPythonPath) {
      toast.error('GPU 模式下请先填写共享本地 Python 路径')
      return
    }

    setIsTestingFasterWhisper(true)
    try {
      await api.settings.update({
        faster_whisper_model: model,
        ...(deploymentProfile === 'gpu' ? { local_model_python_path: localModelPythonPath } : {}),
      })
      const result = await api.settings.validateFasterWhisper({
        model,
      })
      const summary = [
        `模型=${result.model}`,
        `device=${result.device}`,
        `compute=${result.compute_type}`,
        `耗时=${result.elapsed_ms}ms`,
        `utterances=${result.utterance_count}`,
        `words=${result.word_count}`,
      ].join('，')
      if (result.utterance_count === 0 && result.word_count === 0) {
        toast.success(`校验通过: ${summary}。默认样例为纯音频，0 属正常（仅验证运行链路）。设置会自动保存并生效。`)
      } else {
        toast.success(`校验通过: ${summary}。设置会自动保存并生效。`)
      }
    } catch (error) {
      toast.error(`校验失败: ${error instanceof Error ? error.message : '未知错误'}`)
    } finally {
      queryClient.invalidateQueries({ queryKey: queryKeys.settings.root })
      setIsTestingFasterWhisper(false)
    }
  }

  const handleTestVolcengineSpeechRecognition = async () => {
    const appKey = (formData.speech_volcengine_app_key ?? settings?.speech_volcengine_app_key ?? '').trim()
    const accessKey = (formData.speech_volcengine_access_key ?? settings?.speech_volcengine_access_key ?? '').trim()
    const resourceId = (formData.speech_volcengine_resource_id ?? settings?.speech_volcengine_resource_id ?? 'volc.seedasr.auc').trim()

    if (!appKey) {
      toast.error('请先填写火山语音识别 APP ID')
      return
    }
    if (!accessKey) {
      toast.error('请先填写火山语音识别 Access Token')
      return
    }
    if (!resourceId) {
      toast.error('请先填写火山语音识别 Resource ID')
      return
    }

    setIsTestingVolcengineSpeechRecognition(true)
    try {
      await api.settings.update({
        speech_volcengine_app_key: appKey,
        speech_volcengine_access_key: accessKey,
        speech_volcengine_resource_id: resourceId,
        speech_volcengine_language: '',
      })
      const result = await api.settings.testVolcengineSpeechRecognition({
        app_key: appKey,
        access_key: accessKey,
        resource_id: resourceId,
      })
      const summary = [
        `resource=${result.resource_id}`,
        `耗时=${result.elapsed_ms}ms`,
        `utterances=${result.utterance_count}`,
        `words=${result.word_count}`,
      ].join('，')
      toast.success(`校验通过: ${summary}。设置会自动保存并生效。`)
    } catch (error) {
      toast.error(`校验失败: ${error instanceof Error ? error.message : '未知错误'}`)
    } finally {
      queryClient.invalidateQueries({ queryKey: queryKeys.settings.root })
      setIsTestingVolcengineSpeechRecognition(false)
    }
  }

  const handleValidateCrawl4ai = async () => {
    setIsValidatingCrawl4ai(true)
    try {
      await api.settings.validateCrawl4ai()
      toast.success('Crawl4AI 校验通过')
    } catch (error) {
      toast.error(`校验失败: ${error instanceof Error ? error.message : '未知错误'}`)
    } finally {
      queryClient.invalidateQueries({ queryKey: queryKeys.settings.root })
      setIsValidatingCrawl4ai(false)
    }
  }

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="absolute inset-0 overflow-auto">
      <div className="sticky top-0 z-20 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <div className="container mx-auto max-w-6xl px-6 py-4">
          <div className="flex items-center gap-4">
            <Button variant="ghost" size="icon" type="button" onClick={handleBack}>
              <ArrowLeft className="h-5 w-5" />
            </Button>
            <div>
              <h1 className="text-2xl font-bold">设置</h1>
              <p className="text-muted-foreground">配置任务默认模型与各 Provider 参数</p>
            </div>
          </div>
        </div>
      </div>

      <div className="container mx-auto p-6 max-w-6xl">
        <form onSubmit={(e) => e.preventDefault()} className="pb-24">
          <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
            <aside className="self-start rounded-lg border bg-muted/25 p-2 lg:sticky lg:top-[88px]">
              <nav className="space-y-1">
                {SETTINGS_NAVIGATION.map((item) => {
                  const isActive = item.id === activePrimaryTab
                  return (
                    <Button
                      key={item.id}
                      type="button"
                    variant={isActive ? 'secondary' : 'ghost'}
                    className="w-full justify-start"
                    onClick={() => setActivePrimaryTab(item.id)}
                  >
                    {item.label}
                  </Button>
                )
              })}
            </nav>
          </aside>

            <div className="space-y-4">
              {activePrimaryTab === 'default_models' && (
                <SettingsDefaultModelsSection
                  settings={settings}
                  formData={formData}
                  updateField={updateField}
                  llmProviders={llmProviders}
                  imageProviders={imageProviders}
                  wan2gpImagePresets={wan2gpPresets}
                  wan2gpVideoPresetData={wan2gpVideoPresetData}
                />
              )}

              {activePrimaryTab === 'local_models' && (
                <>
                  <SettingsLocalModelDependencySection
                    settings={settings}
                    formData={formData}
                    updateField={updateField}
                    onValidateWan2gp={handleValidateWan2gp}
                    isValidatingWan2gp={isValidatingWan2gp}
                  />
                </>
              )}

              {activePrimaryTab === 'external_links' && (
                <>
                  <SettingsWebParserSection
                    settings={settings}
                    formData={formData}
                    updateField={updateField}
                    showApiKeys={showApiKeys}
                    onToggleApiKey={toggleApiKeyVisibility}
                    onFetchJinaReaderUsage={handleFetchJinaReaderUsage}
                    isFetchingJinaReaderUsage={isFetchingJinaReaderUsage}
                    jinaReaderUsage={jinaReaderUsage}
                    onValidateCrawl4ai={handleValidateCrawl4ai}
                    isValidatingCrawl4ai={isValidatingCrawl4ai}
                  />
                  <SettingsVideoDownloaderSection
                    settings={settings}
                    formData={formData}
                    updateField={updateField}
                    onValidateXhsDownloader={handleValidateXhsDownloader}
                    isValidatingXhsDownloader={isValidatingXhsDownloader}
                    onValidateTiktokDownloader={handleValidateTiktokDownloader}
                    isValidatingTiktokDownloader={isValidatingTiktokDownloader}
                    onValidateKsDownloader={handleValidateKsDownloader}
                    isValidatingKsDownloader={isValidatingKsDownloader}
                  />
                </>
              )}

              {activePrimaryTab === 'search' && (
                <SettingsSearchProviderSection
                  updateField={updateField}
                  settings={settings}
                  formData={formData}
                  showApiKeys={showApiKeys}
                  onToggleApiKey={toggleApiKeyVisibility}
                  onFetchTavilyUsage={handleFetchTavilyUsage}
                  isCheckingTavilyUsage={isCheckingTavilyUsage}
                  tavilyUsage={tavilyUsage}
                />
              )}

              {activePrimaryTab === 'llm' && (
                <SettingsLlmProviderSection
                  currentDefaultLlmProviderId={selectedLlmProvider}
                  updateField={updateField}
                  llmProviders={llmProviders}
                  showApiKeys={showApiKeys}
                  onToggleApiKey={toggleApiKeyVisibility}
                />
              )}

              {activePrimaryTab === 'speech' && (
                <SettingsSpeechRecognitionSection
                  settings={settings}
                  formData={formData}
                  updateField={updateField}
                  showApiKeys={showApiKeys}
                  onToggleApiKey={toggleApiKeyVisibility}
                  selectedFasterWhisperModel={selectedFasterWhisperModel}
                  fasterWhisperModelOptions={FASTER_WHISPER_MODEL_OPTIONS}
                  onTestFasterWhisper={handleTestFasterWhisper}
                  isTestingFasterWhisper={isTestingFasterWhisper}
                  onTestVolcengineSpeechRecognition={handleTestVolcengineSpeechRecognition}
                  isTestingVolcengineSpeechRecognition={isTestingVolcengineSpeechRecognition}
                />
              )}

              {activePrimaryTab === 'audio' && (
                <SettingsAudioProviderSection
                  settings={settings}
                  formData={formData}
                  updateField={updateField}
                  showApiKeys={showApiKeys}
                  onToggleApiKey={toggleApiKeyVisibility}
                  wan2gpAudioPresets={wan2gpAudioPresets}
                  activeVoiceLibraryItems={activeVoiceLibraryItems}
                />
              )}

              {activePrimaryTab === 'image' && (
                <ImageProviderCard
                  settings={settings}
                  formData={formData}
                  updateField={updateField}
                  showApiKeys={showApiKeys}
                  onToggleApiKey={toggleApiKeyVisibility}
                  wan2gpPresets={wan2gpPresets}
                />
              )}

              {activePrimaryTab === 'video' && (
                <VideoProviderCard
                  settings={settings}
                  formData={formData}
                  updateField={updateField}
                  showApiKeys={showApiKeys}
                  onToggleApiKey={toggleApiKeyVisibility}
                  wan2gpVideoPresetData={wan2gpVideoPresetData}
                />
              )}
            </div>
          </div>
        </form>
      </div>

      <div className="fixed inset-x-0 bottom-0 z-30 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/75">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-end px-6 py-4">
          <div className="text-sm text-muted-foreground">
            {isSavingSettings
              ? '正在自动保存...'
              : (hasAutoSaved ? '已自动保存并生效' : '修改后自动保存并生效')}
          </div>
        </div>
      </div>
    </div>
  )
}
