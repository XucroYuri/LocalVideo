'use client'

import { SlidersHorizontal } from 'lucide-react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  getImageProviderDisplayName,
  getLlmProviderDisplayName,
  normalizeModelIds,
  resolveEnabledModelIds,
} from '@/lib/provider-config'
import { hasKlingCredentials } from '@/lib/kling'
import { isWan2gpI2iPreset, isWan2gpT2iPreset } from '@/lib/stage-panel-helpers'
import type {
  ImageProviderConfig,
  LLMProviderConfig,
  Settings,
  SettingsUpdate,
  Wan2gpImagePreset,
  Wan2gpVideoPreset,
} from '@/types/settings'
import { SEEDANCE_MODEL_PRESETS } from '@/lib/seedance'

interface ModelOption {
  value: string
  label: string
}

interface SettingsDefaultModelsSectionProps {
  settings: Settings | undefined
  formData: SettingsUpdate
  updateField: <K extends keyof SettingsUpdate>(key: K, value: SettingsUpdate[K]) => void
  llmProviders: LLMProviderConfig[]
  imageProviders: ImageProviderConfig[]
  wan2gpImagePresets: Wan2gpImagePreset[]
  wan2gpVideoPresetData?: { t2v_presets: Wan2gpVideoPreset[]; i2v_presets: Wan2gpVideoPreset[] }
}

const COMPOSITE_SEPARATOR = '::'
const PROVIDER_MODEL_LABEL_SEPARATOR = ' | '

function makeCompositeModelValue(providerId: string, modelId: string): string {
  return `${providerId}${COMPOSITE_SEPARATOR}${modelId}`
}

function parseCompositeModelValue(value: string): { providerId: string; modelId: string } | null {
  const normalized = String(value || '').trim()
  if (!normalized) return null
  const separatorIndex = normalized.indexOf(COMPOSITE_SEPARATOR)
  if (separatorIndex <= 0) return null
  const providerId = normalized.slice(0, separatorIndex).trim()
  const modelId = normalized.slice(separatorIndex + COMPOSITE_SEPARATOR.length).trim()
  if (!providerId || !modelId) return null
  return { providerId, modelId }
}

function resolveSelectValue(options: ModelOption[], preferred: string): string | undefined {
  const normalized = String(preferred || '').trim()
  if (normalized && options.some((item) => item.value === normalized)) return normalized
  return options[0]?.value
}

function makeProviderModelLabel(providerName: string, modelName: string): string {
  return `${providerName}${PROVIDER_MODEL_LABEL_SEPARATOR}${modelName}`
}

function resolveSpeechProviderFromBinding(value: string | undefined): string {
  const text = String(value || '').trim()
  if (!text) return ''
  if (text.includes(COMPOSITE_SEPARATOR)) {
    const parsed = parseCompositeModelValue(text)
    return parsed?.providerId || ''
  }
  if (text === 'volcengine_asr' || text === 'faster_whisper') return text
  return ''
}

export function SettingsDefaultModelsSection(props: SettingsDefaultModelsSectionProps) {
  const {
    settings,
    formData,
    updateField,
    llmProviders,
    imageProviders,
    wan2gpImagePresets,
    wan2gpVideoPresetData,
  } = props
  const hasKlingConfig = hasKlingCredentials({
    kling_access_key: formData.kling_access_key ?? settings?.kling_access_key,
    kling_secret_key: formData.kling_secret_key ?? settings?.kling_secret_key,
  })

  const llmModelOptions = (() => {
    const options: ModelOption[] = []
    for (const provider of llmProviders) {
      const isConfigured = String(provider.api_key || '').trim().length > 0
      if (!isConfigured) continue
      const models = normalizeModelIds(provider.enabled_models ?? [])
      if (models.length === 0) continue
      for (const modelId of models) {
        options.push({
          value: makeCompositeModelValue(provider.id, modelId),
          label: makeProviderModelLabel(getLlmProviderDisplayName(provider), modelId),
        })
      }
    }
    return normalizeModelIds(options.map((item) => item.value)).map((value) => {
      return options.find((item) => item.value === value) || { value, label: value }
    })
  })()

  const llmVisionModelOptions = (() => {
    const options: ModelOption[] = []
    for (const provider of llmProviders.filter((item) => item.supports_vision)) {
      const isConfigured = String(provider.api_key || '').trim().length > 0
      if (!isConfigured) continue
      const models = normalizeModelIds(provider.enabled_models ?? [])
      if (models.length === 0) continue
      for (const modelId of models) {
        options.push({
          value: makeCompositeModelValue(provider.id, modelId),
          label: makeProviderModelLabel(getLlmProviderDisplayName(provider), modelId),
        })
      }
    }
    return normalizeModelIds(options.map((item) => item.value)).map((value) => {
      return options.find((item) => item.value === value) || { value, label: value }
    })
  })()

  const searchOptions: ModelOption[] = (() => {
    const configuredSearchApiKey = String(
      formData.search_tavily_api_key
      ?? settings?.search_tavily_api_key
      ?? ''
    ).trim()
    const isTavilyConfigured = configuredSearchApiKey.length > 0 || Boolean(settings?.search_tavily_api_key_set)
    return isTavilyConfigured ? [{ value: 'tavily', label: 'Tavily' }] : []
  })()
  const webParserOptions: ModelOption[] = (() => {
    const options: ModelOption[] = [{ value: 'jina_reader', label: 'Jina Reader' }]
    if (settings?.crawl4ai_validation_status === 'ready') {
      options.push({ value: 'crawl4ai', label: 'Crawl4AI' })
    }
    return options
  })()
  const audioOptions: ModelOption[] = (() => {
    const options: ModelOption[] = [{ value: 'edge_tts', label: 'Edge TTS' }]
    if (settings?.wan2gp_available) {
      options.push({ value: 'wan2gp', label: 'Wan2GP' })
    }
    const volcengineAppKey = String(
      formData.volcengine_tts_app_key ?? settings?.volcengine_tts_app_key ?? ''
    ).trim()
    const volcengineAccessKey = String(
      formData.volcengine_tts_access_key ?? settings?.volcengine_tts_access_key ?? ''
    ).trim()
    if (volcengineAppKey && volcengineAccessKey) {
      options.push({ value: 'volcengine_tts', label: '火山引擎 TTS' })
    }
    if (hasKlingConfig) {
      options.push({ value: 'kling_tts', label: '可灵 TTS' })
    }
    const viduApiKey = String(
      formData.vidu_api_key ?? settings?.vidu_api_key ?? ''
    ).trim()
    if (viduApiKey) {
      options.push({ value: 'vidu_tts', label: 'Vidu TTS' })
    }
    const minimaxApiKey = String(
      formData.minimax_api_key ?? settings?.minimax_api_key ?? ''
    ).trim()
    if (minimaxApiKey) {
      options.push({ value: 'minimax_tts', label: 'MiniMax TTS' })
    }
    return options
  })()
  const speechRecognitionProviderOptions: ModelOption[] = (() => {
    const options: ModelOption[] = [
      {
        value: 'faster_whisper',
        label: 'fast-whisper',
      },
    ]
    const speechVolcengineAppKey = String(
      formData.speech_volcengine_app_key ?? settings?.speech_volcengine_app_key ?? ''
    ).trim()
    const speechVolcengineAccessKey = String(
      formData.speech_volcengine_access_key ?? settings?.speech_volcengine_access_key ?? ''
    ).trim()
    const speechVolcengineResourceId = String(
      formData.speech_volcengine_resource_id ?? settings?.speech_volcengine_resource_id ?? 'volc.seedasr.auc'
    ).trim() || 'volc.seedasr.auc'

    if (speechVolcengineAppKey && speechVolcengineAccessKey && speechVolcengineResourceId) {
      options.push({
        value: 'volcengine_asr',
        label: '火山引擎 ASR',
      })
    }
    return options
  })()

  const imageT2iOptions = (() => {
    const options: ModelOption[] = []
    for (const provider of imageProviders) {
      const isConfigured = String(provider.api_key || '').trim().length > 0
      if (!isConfigured) continue
      const models = normalizeModelIds(provider.enabled_models ?? [])
      if (models.length === 0) continue
      for (const modelId of models) {
        options.push({
          value: makeCompositeModelValue(provider.id, modelId),
          label: makeProviderModelLabel(getImageProviderDisplayName(provider), modelId),
        })
      }
    }

    const t2iPresets = wan2gpImagePresets.filter((preset) => isWan2gpT2iPreset(preset))
    const wan2gpCatalogIds = normalizeModelIds(t2iPresets.map((preset) => preset.id))
    const enabledWan2gpIds = resolveEnabledModelIds(
      formData.image_wan2gp_enabled_models ?? settings?.image_wan2gp_enabled_models,
      wan2gpCatalogIds
    )
    if (settings?.wan2gp_available) {
      for (const preset of t2iPresets.filter((item) => enabledWan2gpIds.includes(item.id))) {
        options.push({
          value: makeCompositeModelValue('wan2gp', preset.id),
          label: makeProviderModelLabel('Wan2GP', preset.display_name),
        })
      }
    }
    if (hasKlingConfig) {
      const klingCatalog = ['kling-v3', 'kling-v3-omni']
      const klingEnabled = resolveEnabledModelIds(
        formData.image_kling_enabled_models ?? settings?.image_kling_enabled_models,
        klingCatalog
      )
      for (const modelId of klingEnabled) {
        options.push({
          value: makeCompositeModelValue('kling', modelId),
          label: makeProviderModelLabel('可灵', modelId),
        })
      }
    }
    const viduApiKey = String(formData.vidu_api_key ?? settings?.vidu_api_key ?? '').trim()
    if (viduApiKey) {
      const viduCatalog = ['viduq2']
      const viduEnabled = resolveEnabledModelIds(
        formData.image_vidu_enabled_models ?? settings?.image_vidu_enabled_models,
        viduCatalog
      )
      for (const modelId of viduEnabled) {
        options.push({
          value: makeCompositeModelValue('vidu', modelId),
          label: makeProviderModelLabel('Vidu', modelId),
        })
      }
    }
    const minimaxApiKey = String(formData.minimax_api_key ?? settings?.minimax_api_key ?? '').trim()
    if (minimaxApiKey) {
      const minimaxCatalog = ['image-01', 'image-01-live']
      const minimaxEnabled = resolveEnabledModelIds(
        formData.image_minimax_enabled_models ?? settings?.image_minimax_enabled_models,
        minimaxCatalog
      )
      for (const modelId of minimaxEnabled) {
        options.push({
          value: makeCompositeModelValue('minimax', modelId),
          label: makeProviderModelLabel('MiniMax', modelId),
        })
      }
    }

    return normalizeModelIds(options.map((item) => item.value)).map((value) => {
      return options.find((item) => item.value === value) || { value, label: value }
    })
  })()

  const imageI2iOptions = (() => {
    const options: ModelOption[] = []
    for (const provider of imageProviders) {
      const isConfigured = String(provider.api_key || '').trim().length > 0
      if (!isConfigured) continue
      const models = normalizeModelIds(provider.enabled_models ?? [])
      if (models.length === 0) continue
      for (const modelId of models) {
        options.push({
          value: makeCompositeModelValue(provider.id, modelId),
          label: makeProviderModelLabel(getImageProviderDisplayName(provider), modelId),
        })
      }
    }

    const i2iPresets = wan2gpImagePresets.filter((preset) => isWan2gpI2iPreset(preset))
    const wan2gpCatalogIds = normalizeModelIds(i2iPresets.map((preset) => preset.id))
    const enabledWan2gpIds = resolveEnabledModelIds(
      formData.image_wan2gp_enabled_models ?? settings?.image_wan2gp_enabled_models,
      wan2gpCatalogIds
    )
    if (settings?.wan2gp_available) {
      for (const preset of i2iPresets.filter((item) => enabledWan2gpIds.includes(item.id))) {
        options.push({
          value: makeCompositeModelValue('wan2gp', preset.id),
          label: makeProviderModelLabel('Wan2GP', preset.display_name),
        })
      }
    }
    if (hasKlingConfig) {
      const klingCatalog = ['kling-v3', 'kling-v3-omni']
      const klingEnabled = resolveEnabledModelIds(
        formData.image_kling_enabled_models ?? settings?.image_kling_enabled_models,
        klingCatalog
      )
      for (const modelId of klingEnabled) {
        options.push({
          value: makeCompositeModelValue('kling', modelId),
          label: makeProviderModelLabel('可灵', modelId),
        })
      }
    }
    const viduApiKey = String(formData.vidu_api_key ?? settings?.vidu_api_key ?? '').trim()
    if (viduApiKey) {
      const viduCatalog = ['viduq2']
      const viduEnabled = resolveEnabledModelIds(
        formData.image_vidu_enabled_models ?? settings?.image_vidu_enabled_models,
        viduCatalog
      )
      for (const modelId of viduEnabled) {
        options.push({
          value: makeCompositeModelValue('vidu', modelId),
          label: makeProviderModelLabel('Vidu', modelId),
        })
      }
    }
    const minimaxApiKey = String(formData.minimax_api_key ?? settings?.minimax_api_key ?? '').trim()
    if (minimaxApiKey) {
      const minimaxCatalog = ['image-01', 'image-01-live']
      const minimaxEnabled = resolveEnabledModelIds(
        formData.image_minimax_enabled_models ?? settings?.image_minimax_enabled_models,
        minimaxCatalog
      )
      for (const modelId of minimaxEnabled) {
        options.push({
          value: makeCompositeModelValue('minimax', modelId),
          label: makeProviderModelLabel('MiniMax', modelId),
        })
      }
    }

    return normalizeModelIds(options.map((item) => item.value)).map((value) => {
      return options.find((item) => item.value === value) || { value, label: value }
    })
  })()

  const videoT2vOptions = (() => {
    const options: ModelOption[] = []

    const seedanceCatalog = normalizeModelIds([
      ...SEEDANCE_MODEL_PRESETS.map((item) => item.id),
      formData.video_seedance_model ?? settings?.video_seedance_model ?? '',
    ])
    const seedanceEnabled = resolveEnabledModelIds(
      formData.video_seedance_enabled_models ?? settings?.video_seedance_enabled_models,
      seedanceCatalog
    )
    const isSeedanceConfigured = Boolean(String(formData.video_seedance_api_key ?? settings?.video_seedance_api_key ?? '').trim())
    if (isSeedanceConfigured) {
      for (const modelId of seedanceEnabled) {
        const preset = SEEDANCE_MODEL_PRESETS.find((item) => item.id === modelId)
        if (!preset || !preset.supportsT2v) continue
        options.push({
          value: makeCompositeModelValue('volcengine_seedance', modelId),
          label: makeProviderModelLabel('火山引擎', preset.label),
        })
      }
    }

    const wan2gpT2vPresets = wan2gpVideoPresetData?.t2v_presets ?? []
    const wan2gpI2vPresets = wan2gpVideoPresetData?.i2v_presets ?? []
    const wan2gpCatalog = normalizeModelIds([
      ...wan2gpT2vPresets.map((item) => item.id),
      ...wan2gpI2vPresets.map((item) => item.id),
    ])
    const wan2gpEnabled = resolveEnabledModelIds(
      formData.video_wan2gp_enabled_models ?? settings?.video_wan2gp_enabled_models,
      wan2gpCatalog
    )
    if (settings?.wan2gp_available) {
      for (const preset of wan2gpT2vPresets.filter((item) => wan2gpEnabled.includes(item.id))) {
        options.push({
          value: makeCompositeModelValue('wan2gp', preset.id),
          label: makeProviderModelLabel('Wan2GP', preset.display_name),
        })
      }
    }

    return normalizeModelIds(options.map((item) => item.value)).map((value) => {
      return options.find((item) => item.value === value) || { value, label: value }
    })
  })()

  const videoI2vOptions = (() => {
    const options: ModelOption[] = []

    const seedanceCatalog = normalizeModelIds([
      ...SEEDANCE_MODEL_PRESETS.map((item) => item.id),
      formData.video_seedance_model ?? settings?.video_seedance_model ?? '',
    ])
    const seedanceEnabled = resolveEnabledModelIds(
      formData.video_seedance_enabled_models ?? settings?.video_seedance_enabled_models,
      seedanceCatalog
    )
    const isSeedanceConfigured = Boolean(String(formData.video_seedance_api_key ?? settings?.video_seedance_api_key ?? '').trim())
    if (isSeedanceConfigured) {
      for (const modelId of seedanceEnabled) {
        const preset = SEEDANCE_MODEL_PRESETS.find((item) => item.id === modelId)
        if (!preset || !preset.supportsI2v) continue
        options.push({
          value: makeCompositeModelValue('volcengine_seedance', modelId),
          label: makeProviderModelLabel('火山引擎', preset.label),
        })
      }
    }

    const wan2gpT2vPresets = wan2gpVideoPresetData?.t2v_presets ?? []
    const wan2gpI2vPresets = wan2gpVideoPresetData?.i2v_presets ?? []
    const wan2gpCatalog = normalizeModelIds([
      ...wan2gpT2vPresets.map((item) => item.id),
      ...wan2gpI2vPresets.map((item) => item.id),
    ])
    const wan2gpEnabled = resolveEnabledModelIds(
      formData.video_wan2gp_enabled_models ?? settings?.video_wan2gp_enabled_models,
      wan2gpCatalog
    )
    if (settings?.wan2gp_available) {
      for (const preset of wan2gpI2vPresets.filter((item) => wan2gpEnabled.includes(item.id))) {
        options.push({
          value: makeCompositeModelValue('wan2gp', preset.id),
          label: makeProviderModelLabel('Wan2GP', preset.display_name),
        })
      }
    }

    return normalizeModelIds(options.map((item) => item.value)).map((value) => {
      return options.find((item) => item.value === value) || { value, label: value }
    })
  })()

  const currentDefaultLlmProviderId = formData.default_llm_provider ?? settings?.default_llm_provider ?? llmProviders[0]?.id ?? ''
  const currentDefaultLlmProvider = llmProviders.find((item) => item.id === currentDefaultLlmProviderId)
  const fallbackGeneralLlmModelId = currentDefaultLlmProvider?.enabled_models?.[0] || ''
  const fallbackGeneralLlmValue = currentDefaultLlmProvider
    && fallbackGeneralLlmModelId
    ? makeCompositeModelValue(currentDefaultLlmProvider.id, fallbackGeneralLlmModelId)
    : ''

  const fallbackImageT2iValue = (() => {
    const providerId = formData.default_image_provider ?? settings?.default_image_provider ?? imageProviders[0]?.id ?? ''
    if (providerId === 'wan2gp') {
      const modelId = formData.image_wan2gp_preset ?? settings?.image_wan2gp_preset ?? ''
      return modelId ? makeCompositeModelValue('wan2gp', modelId) : ''
    }
    if (providerId === 'kling') {
      const modelId = formData.image_kling_t2i_model ?? settings?.image_kling_t2i_model ?? 'kling-v3'
      return modelId ? makeCompositeModelValue('kling', modelId) : ''
    }
    if (providerId === 'vidu') {
      const modelId = formData.image_vidu_t2i_model ?? settings?.image_vidu_t2i_model ?? 'viduq2'
      return modelId ? makeCompositeModelValue('vidu', modelId) : ''
    }
    if (providerId === 'minimax') {
      const modelId = formData.image_minimax_model ?? settings?.image_minimax_model ?? 'image-01'
      return modelId ? makeCompositeModelValue('minimax', modelId) : ''
    }
    const provider = imageProviders.find((item) => item.id === providerId)
    if (!provider) return ''
    const modelId = provider.enabled_models?.[0] || ''
    return modelId ? makeCompositeModelValue(provider.id, modelId) : ''
  })()

  const fallbackImageI2iValue = (() => {
    const providerId = formData.default_image_provider ?? settings?.default_image_provider ?? imageProviders[0]?.id ?? ''
    if (providerId === 'wan2gp') {
      const modelId = formData.image_wan2gp_preset_i2i ?? settings?.image_wan2gp_preset_i2i ?? ''
      return modelId ? makeCompositeModelValue('wan2gp', modelId) : ''
    }
    if (providerId === 'kling') {
      const modelId = formData.image_kling_i2i_model ?? settings?.image_kling_i2i_model ?? 'kling-v3'
      return modelId ? makeCompositeModelValue('kling', modelId) : ''
    }
    if (providerId === 'vidu') {
      const modelId = formData.image_vidu_i2i_model ?? settings?.image_vidu_i2i_model ?? 'viduq2'
      return modelId ? makeCompositeModelValue('vidu', modelId) : ''
    }
    if (providerId === 'minimax') {
      const modelId = formData.image_minimax_model ?? settings?.image_minimax_model ?? 'image-01'
      return modelId ? makeCompositeModelValue('minimax', modelId) : ''
    }
    const provider = imageProviders.find((item) => item.id === providerId)
    if (!provider) return ''
    const modelId = provider.enabled_models?.[0] || ''
    return modelId ? makeCompositeModelValue(provider.id, modelId) : ''
  })()

  const fallbackVideoT2vValue = (() => {
    const providerId = formData.default_video_provider ?? settings?.default_video_provider ?? 'volcengine_seedance'
    if (providerId === 'wan2gp') {
      const modelId = formData.video_wan2gp_t2v_preset ?? settings?.video_wan2gp_t2v_preset ?? ''
      return modelId ? makeCompositeModelValue('wan2gp', modelId) : ''
    }
    if (providerId === 'volcengine_seedance') {
      const modelId = formData.video_seedance_model ?? settings?.video_seedance_model ?? ''
      return modelId ? makeCompositeModelValue('volcengine_seedance', modelId) : ''
    }
    return ''
  })()

  const fallbackVideoI2vValue = (() => {
    const providerId = formData.default_video_provider ?? settings?.default_video_provider ?? 'volcengine_seedance'
    if (providerId === 'wan2gp') {
      const modelId = formData.video_wan2gp_i2v_preset ?? settings?.video_wan2gp_i2v_preset ?? ''
      return modelId ? makeCompositeModelValue('wan2gp', modelId) : ''
    }
    if (providerId === 'volcengine_seedance') {
      const modelId = formData.video_seedance_model ?? settings?.video_seedance_model ?? ''
      return modelId ? makeCompositeModelValue('volcengine_seedance', modelId) : ''
    }
    return ''
  })()

  const generalLlmOptions = llmModelOptions
  const fastLlmOptions = llmModelOptions
  const multimodalLlmOptions = llmVisionModelOptions
  const imageT2iModelOptions = imageT2iOptions
  const imageI2iModelOptions = imageI2iOptions
  const videoT2vModelOptions = videoT2vOptions
  const videoI2vModelOptions = videoI2vOptions

  const selectedGeneralLlm = resolveSelectValue(
    generalLlmOptions,
    formData.default_general_llm_model ?? settings?.default_general_llm_model ?? fallbackGeneralLlmValue
  )
  const selectedFastLlm = resolveSelectValue(
    fastLlmOptions,
    formData.default_fast_llm_model ?? settings?.default_fast_llm_model ?? selectedGeneralLlm ?? ''
  )
  const selectedMultimodalLlm = resolveSelectValue(
    multimodalLlmOptions,
    formData.default_multimodal_llm_model ?? settings?.default_multimodal_llm_model ?? selectedGeneralLlm ?? ''
  )
  const selectedSearchProvider = resolveSelectValue(
    searchOptions,
    formData.default_search_provider ?? settings?.default_search_provider ?? 'tavily'
  )
  const llmProviderNotConfiguredText = '未配置任何 LLM 供应商，请去往 LLM 项中配置'
  const searchProviderNotConfiguredText = '未配置任何搜索供应商，请去往搜索项中配置'
  const speechProviderNotConfiguredText = '未配置任何语音识别服务，请去往语音识别项中配置'
  const imageProviderNotConfiguredText = '未配置任何图像供应商，请去往图像生成项中配置'
  const videoProviderNotConfiguredText = '未配置任何视频供应商，请去往视频生成项中配置'
  const selectedWebParserProvider = resolveSelectValue(
    webParserOptions,
    formData.web_url_parser_provider ?? settings?.web_url_parser_provider ?? 'jina_reader'
  )
  const selectedAudioProvider = resolveSelectValue(
    audioOptions,
    formData.default_audio_provider ?? settings?.default_audio_provider ?? 'edge_tts'
  )
  const fallbackSpeechRecognitionProvider = (
    String(
      formData.default_speech_recognition_provider
      ?? settings?.default_speech_recognition_provider
      ?? resolveSpeechProviderFromBinding(
        formData.default_speech_recognition_model ?? settings?.default_speech_recognition_model
      )
      ?? 'faster_whisper'
    ).trim()
    || 'faster_whisper'
  )
  const selectedSpeechRecognitionProvider = resolveSelectValue(
    speechRecognitionProviderOptions,
    fallbackSpeechRecognitionProvider
  )
  const selectedImageT2i = resolveSelectValue(
    imageT2iModelOptions,
    formData.default_image_t2i_model ?? settings?.default_image_t2i_model ?? fallbackImageT2iValue
  )
  const selectedImageI2i = resolveSelectValue(
    imageI2iModelOptions,
    formData.default_image_i2i_model ?? settings?.default_image_i2i_model ?? fallbackImageI2iValue
  )
  const selectedVideoT2v = resolveSelectValue(
    videoT2vModelOptions,
    formData.default_video_t2v_model ?? settings?.default_video_t2v_model ?? fallbackVideoT2vValue
  )
  const selectedVideoI2v = resolveSelectValue(
    videoI2vModelOptions,
    formData.default_video_i2v_model ?? settings?.default_video_i2v_model ?? fallbackVideoI2vValue
  )

  const applyImageProviderModel = (providerId: string, modelId: string, mode: 't2i' | 'i2i') => {
    if (providerId === 'wan2gp') {
      if (mode === 't2i') {
        updateField('image_wan2gp_preset', modelId)
      } else {
        updateField('image_wan2gp_preset_i2i', modelId)
      }
      return
    }
    if (providerId === 'kling') {
      if (mode === 't2i') {
        updateField('image_kling_t2i_model', modelId)
      } else {
        updateField('image_kling_i2i_model', modelId)
      }
      return
    }
    if (providerId === 'vidu') {
      if (mode === 't2i') {
        updateField('image_vidu_t2i_model', modelId)
      } else {
        updateField('image_vidu_i2i_model', modelId)
      }
      return
    }
    if (providerId === 'minimax') {
      updateField('image_minimax_model', modelId)
      return
    }
  }

  const applyVideoProviderModel = (providerId: string, modelId: string, mode: 't2v' | 'i2v') => {
    if (providerId === 'wan2gp') {
      if (mode === 't2v') {
        updateField('video_wan2gp_t2v_preset', modelId)
      } else {
        updateField('video_wan2gp_i2v_preset', modelId)
      }
      return
    }
    if (providerId === 'volcengine_seedance') {
      updateField('video_seedance_model', modelId)
      return
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <SlidersHorizontal className="h-5 w-5" />
          默认模型
        </CardTitle>
        <CardDescription>按任务类型配置默认模型选择，其他参数沿用对应 Provider 的配置</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="default_general_llm_model">默认 LLM 模型</Label>
          <Select
            value={selectedGeneralLlm}
            disabled={generalLlmOptions.length === 0}
            onValueChange={(value) => {
              updateField('default_general_llm_model', value)
              const parsed = parseCompositeModelValue(value)
              if (!parsed) return
              updateField('default_llm_provider', parsed.providerId)
            }}
          >
            <SelectTrigger id="default_general_llm_model">
              <SelectValue
                placeholder={generalLlmOptions.length > 0 ? '请选择默认 LLM 模型' : llmProviderNotConfiguredText}
              />
            </SelectTrigger>
            <SelectContent>
              {generalLlmOptions.length > 0 ? (
                generalLlmOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                ))
              ) : (
                <div className="px-2 py-1.5 text-sm text-muted-foreground">
                  {llmProviderNotConfiguredText}
                </div>
              )}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="default_fast_llm_model">默认快速模型</Label>
          <Select
            value={selectedFastLlm}
            disabled={fastLlmOptions.length === 0}
            onValueChange={(value) => updateField('default_fast_llm_model', value)}
          >
            <SelectTrigger id="default_fast_llm_model">
              <SelectValue
                placeholder={fastLlmOptions.length > 0 ? '请选择快速任务模型' : llmProviderNotConfiguredText}
              />
            </SelectTrigger>
            <SelectContent>
              {fastLlmOptions.length > 0 ? (
                fastLlmOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                ))
              ) : (
                <div className="px-2 py-1.5 text-sm text-muted-foreground">
                  {llmProviderNotConfiguredText}
                </div>
              )}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="default_multimodal_llm_model">默认多模态模型</Label>
          <Select
            value={selectedMultimodalLlm}
            disabled={multimodalLlmOptions.length === 0}
            onValueChange={(value) => updateField('default_multimodal_llm_model', value)}
          >
            <SelectTrigger id="default_multimodal_llm_model">
              <SelectValue
                placeholder={multimodalLlmOptions.length > 0 ? '请选择多模态任务模型' : llmProviderNotConfiguredText}
              />
            </SelectTrigger>
            <SelectContent>
              {multimodalLlmOptions.length > 0 ? (
                multimodalLlmOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                ))
              ) : (
                <div className="px-2 py-1.5 text-sm text-muted-foreground">
                  {llmProviderNotConfiguredText}
                </div>
              )}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2 md:col-span-2">
          <Label htmlFor="default_search_provider">默认搜索</Label>
          <Select
            value={selectedSearchProvider}
            disabled={searchOptions.length === 0}
            onValueChange={(value) => updateField('default_search_provider', value)}
          >
            <SelectTrigger id="default_search_provider">
              <SelectValue
                placeholder={searchOptions.length > 0 ? '请选择默认搜索' : searchProviderNotConfiguredText}
              />
            </SelectTrigger>
            <SelectContent>
              {searchOptions.length > 0 ? (
                searchOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                ))
              ) : (
                <div className="px-2 py-1.5 text-sm text-muted-foreground">
                  {searchProviderNotConfiguredText}
                </div>
              )}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2 md:col-span-2">
          <Label htmlFor="web_url_parser_provider">默认网页链接解析</Label>
          <Select
            value={selectedWebParserProvider}
            onValueChange={(value) => updateField('web_url_parser_provider', value)}
          >
            <SelectTrigger id="web_url_parser_provider">
              <SelectValue placeholder="请选择默认网页链接解析" />
            </SelectTrigger>
            <SelectContent>
              {webParserOptions.map((option) => (
                <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2 md:col-span-2">
          <Label htmlFor="default_audio_provider">默认音频生成</Label>
          <Select
            value={selectedAudioProvider}
            onValueChange={(value) => updateField('default_audio_provider', value)}
          >
            <SelectTrigger id="default_audio_provider">
              <SelectValue placeholder="请选择默认音频生成" />
            </SelectTrigger>
            <SelectContent>
              {audioOptions.map((option) => (
                <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2 md:col-span-2">
          <Label htmlFor="default_speech_recognition_provider">默认语音识别服务</Label>
          <Select
            value={selectedSpeechRecognitionProvider}
            disabled={speechRecognitionProviderOptions.length === 0}
            onValueChange={(value) => {
              updateField('default_speech_recognition_provider', value)
              // 默认页只选服务层级，具体模型在“语音识别”页配置。
              updateField('default_speech_recognition_model', '')
            }}
          >
            <SelectTrigger id="default_speech_recognition_provider">
              <SelectValue
                placeholder={
                  speechRecognitionProviderOptions.length > 0
                    ? '请选择默认语音识别服务'
                    : speechProviderNotConfiguredText
                }
              />
            </SelectTrigger>
            <SelectContent>
              {speechRecognitionProviderOptions.length > 0 ? (
                speechRecognitionProviderOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                ))
              ) : (
                <div className="px-2 py-1.5 text-sm text-muted-foreground">
                  {speechProviderNotConfiguredText}
                </div>
              )}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="default_image_t2i_model">默认图像生成（t2i）</Label>
          <Select
            value={selectedImageT2i}
            disabled={imageT2iModelOptions.length === 0}
            onValueChange={(value) => {
              updateField('default_image_t2i_model', value)
              const parsed = parseCompositeModelValue(value)
              if (!parsed) return
              updateField('default_image_provider', parsed.providerId)
              applyImageProviderModel(parsed.providerId, parsed.modelId, 't2i')
            }}
          >
            <SelectTrigger id="default_image_t2i_model">
              <SelectValue
                placeholder={imageT2iModelOptions.length > 0 ? '请选择默认 t2i 模型' : imageProviderNotConfiguredText}
              />
            </SelectTrigger>
            <SelectContent>
              {imageT2iModelOptions.length > 0 ? (
                imageT2iModelOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                ))
              ) : (
                <div className="px-2 py-1.5 text-sm text-muted-foreground">
                  {imageProviderNotConfiguredText}
                </div>
              )}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="default_image_i2i_model">默认图像生成（i2i）</Label>
          <Select
            value={selectedImageI2i}
            disabled={imageI2iModelOptions.length === 0}
            onValueChange={(value) => {
              updateField('default_image_i2i_model', value)
              const parsed = parseCompositeModelValue(value)
              if (!parsed) return
              applyImageProviderModel(parsed.providerId, parsed.modelId, 'i2i')
            }}
          >
            <SelectTrigger id="default_image_i2i_model">
              <SelectValue
                placeholder={imageI2iModelOptions.length > 0 ? '请选择默认 i2i 模型' : imageProviderNotConfiguredText}
              />
            </SelectTrigger>
            <SelectContent>
              {imageI2iModelOptions.length > 0 ? (
                imageI2iModelOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                ))
              ) : (
                <div className="px-2 py-1.5 text-sm text-muted-foreground">
                  {imageProviderNotConfiguredText}
                </div>
              )}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="default_video_t2v_model">默认视频生成（t2v）</Label>
          <Select
            value={selectedVideoT2v}
            disabled={videoT2vModelOptions.length === 0}
            onValueChange={(value) => {
              updateField('default_video_t2v_model', value)
              const parsed = parseCompositeModelValue(value)
              if (!parsed) return
              updateField('default_video_provider', parsed.providerId)
              applyVideoProviderModel(parsed.providerId, parsed.modelId, 't2v')
            }}
          >
            <SelectTrigger id="default_video_t2v_model">
              <SelectValue
                placeholder={videoT2vModelOptions.length > 0 ? '请选择默认 t2v 模型' : videoProviderNotConfiguredText}
              />
            </SelectTrigger>
            <SelectContent>
              {videoT2vModelOptions.length > 0 ? (
                videoT2vModelOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                ))
              ) : (
                <div className="px-2 py-1.5 text-sm text-muted-foreground">
                  {videoProviderNotConfiguredText}
                </div>
              )}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="default_video_i2v_model">默认视频生成（i2v）</Label>
          <Select
            value={selectedVideoI2v}
            disabled={videoI2vModelOptions.length === 0}
            onValueChange={(value) => {
              updateField('default_video_i2v_model', value)
              const parsed = parseCompositeModelValue(value)
              if (!parsed) return
              updateField('default_video_provider', parsed.providerId)
              applyVideoProviderModel(parsed.providerId, parsed.modelId, 'i2v')
            }}
          >
            <SelectTrigger id="default_video_i2v_model">
              <SelectValue
                placeholder={videoI2vModelOptions.length > 0 ? '请选择默认 i2v 模型' : videoProviderNotConfiguredText}
              />
            </SelectTrigger>
            <SelectContent>
              {videoI2vModelOptions.length > 0 ? (
                videoI2vModelOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                ))
              ) : (
                <div className="px-2 py-1.5 text-sm text-muted-foreground">
                  {videoProviderNotConfiguredText}
                </div>
              )}
            </SelectContent>
          </Select>
        </div>
      </CardContent>
    </Card>
  )
}
