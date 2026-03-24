'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Check, Loader2, Volume2 } from 'lucide-react'

import { SecretInput } from '@/components/settings/secret-input'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { AudioPlayer } from '@/components/ui/audio-player'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Slider } from '@/components/ui/slider'
import { useSettingsAudioPreview } from '@/hooks/use-settings-audio-preview'
import { useSettingsEdgeVoices } from '@/hooks/use-settings-edge-voices'
import { api } from '@/lib/api-client'
import { hasKlingCredentials } from '@/lib/kling'
import type {
  Settings,
  SettingsUpdate,
  VoiceInfo,
  Wan2gpAudioPreset,
} from '@/types/settings'
import type { VoiceLibraryItem } from '@/types/voice-library'
import {
  KLING_TTS_VOICE_CATALOG,
  MINIMAX_TTS_FALLBACK_OPTIONS,
  XIAOMI_MIMO_TTS_COMBINED_VOICE_OPTIONS,
  XIAOMI_MIMO_TTS_FALLBACK_OPTIONS,
  VIDU_TTS_FALLBACK_OPTIONS,
  mapWan2gpModeOptions,
  rateToSpeed,
  resolveDefaultWan2gpPresetId,
  resolveWan2gpPreset,
  speedToRate,
  toKlingVoiceOptionValue,
} from '@/lib/reference-voice'
import {
  AUDIO_PREVIEW_TEXT,
  loadCachedVoices,
  normalizeAudioPreviewLocale,
  resolveAudioPreviewText,
  saveCachedVoices,
} from './settings-audio-preview-helpers'

function resolveVoiceGuideValue(item: VoiceLibraryItem | undefined): string {
  return String(item?.audio_url || item?.audio_file_path || '').trim()
}

function isVoiceGuideMatch(item: VoiceLibraryItem, guide: string): boolean {
  const normalizedGuide = String(guide || '').trim()
  if (!normalizedGuide) return false
  const audioUrl = String(item.audio_url || '').trim()
  if (audioUrl && audioUrl === normalizedGuide) return true
  const audioPath = String(item.audio_file_path || '').trim()
  return Boolean(audioPath && audioPath === normalizedGuide)
}

function stripSplitHintFromPresetDescription(description: string): string {
  const normalized = String(description || '').trim()
  if (!normalized) return ''
  return normalized
    .replace(/\s*Use Manual Split[\s\S]*$/i, '')
    .replace(/\s*使用手动切分[\s\S]*$/, '')
    .trim()
}

function toVoiceDisplayName(voice: VoiceInfo): string {
  const rawName = String(voice.name || '').trim()
  const voiceId = String(voice.id || '').trim()
  if (!rawName) return voiceId
  if (!voiceId) return rawName
  const fullWidthSuffix = `（${voiceId}）`
  if (rawName.endsWith(fullWidthSuffix)) {
    return rawName.slice(0, -fullWidthSuffix.length).trim() || rawName
  }
  const halfWidthSuffix = `(${voiceId})`
  if (rawName.endsWith(halfWidthSuffix)) {
    return rawName.slice(0, -halfWidthSuffix.length).trim() || rawName
  }
  return rawName
}

function resolveVoiceLocale(voices: VoiceInfo[], voiceId: string, fallbackLocale = 'zh-CN'): string {
  const normalizedVoiceId = String(voiceId || '').trim()
  const matched = voices.find((voice) => String(voice.id || '').trim() === normalizedVoiceId)
  return matched?.locale || fallbackLocale
}

const VOLCENGINE_TTS_MODEL_OPTIONS = [
  { value: 'seed-tts-1.0', label: '豆包语音合成模型 1.0（seed-tts-1.0）' },
  { value: 'seed-tts-2.0', label: '豆包语音合成模型 2.0（seed-tts-2.0）' },
]

const VOLCENGINE_TTS_DEFAULT_VOICE_BY_MODEL: Record<string, string> = {
  'seed-tts-1.0': 'zh_female_wanqudashu_moon_bigtts',
  'seed-tts-2.0': 'zh_female_vv_uranus_bigtts',
}

const KLING_TTS_VOICE_OPTIONS = KLING_TTS_VOICE_CATALOG
interface SettingsAudioProviderSectionProps {
  settings: Settings | undefined
  formData: SettingsUpdate
  updateField: <K extends keyof SettingsUpdate>(key: K, value: SettingsUpdate[K]) => void
  showApiKeys: Record<string, boolean>
  onToggleApiKey: (key: string) => void
  wan2gpAudioPresets: Wan2gpAudioPreset[]
  activeVoiceLibraryItems: VoiceLibraryItem[]
}

export function SettingsAudioProviderSection({
  settings,
  formData,
  updateField,
  showApiKeys,
  onToggleApiKey,
  wan2gpAudioPresets,
  activeVoiceLibraryItems,
}: SettingsAudioProviderSectionProps) {
  const { availableVoices, isLoadingVoices } = useSettingsEdgeVoices()
  const [volcengineVoices, setVolcengineVoices] = useState<VoiceInfo[]>([])
  const [volcengineVoiceError, setVolcengineVoiceError] = useState<string | null>(null)
  const minimaxVoices = useMemo<VoiceInfo[]>(
    () => MINIMAX_TTS_FALLBACK_OPTIONS.map((option) => ({
      id: option.value,
      name: option.label,
      locale: option.value.startsWith('Cantonese_') ? 'zh-HK' : 'zh-CN',
    })),
    []
  )
  const xiaomiMimoVoices = useMemo<VoiceInfo[]>(
    () => XIAOMI_MIMO_TTS_FALLBACK_OPTIONS.map((option) => ({
      id: option.value,
      name: option.label,
      locale: option.value === 'default_en' ? 'en-US' : 'zh-CN',
    })),
    []
  )

  const defaultWan2gpAudioPresetId = resolveDefaultWan2gpPresetId(
    settings?.audio_wan2gp_preset,
    wan2gpAudioPresets
  )
  const selectedWan2gpAudioPreset = formData.audio_wan2gp_preset
    ?? defaultWan2gpAudioPresetId
  const selectedWan2gpAudioPresetConfig = resolveWan2gpPreset(
    wan2gpAudioPresets,
    defaultWan2gpAudioPresetId,
    selectedWan2gpAudioPreset
  )
  const selectedWan2gpAudioPresetDescription = stripSplitHintFromPresetDescription(
    selectedWan2gpAudioPresetConfig?.description || ''
  )
  const selectedWan2gpAudioModeOptions = mapWan2gpModeOptions(selectedWan2gpAudioPresetConfig)
  const selectedWan2gpAudioMode = formData.audio_wan2gp_model_mode
    ?? settings?.audio_wan2gp_model_mode
    ?? selectedWan2gpAudioPresetConfig?.default_model_mode
    ?? ''
  const selectedWan2gpAudioModeValue = selectedWan2gpAudioModeOptions.some(
    (option) => option.value === selectedWan2gpAudioMode
  )
    ? selectedWan2gpAudioMode
    : (selectedWan2gpAudioPresetConfig?.default_model_mode || selectedWan2gpAudioModeOptions[0]?.value || '__empty__')
  const selectedWan2gpTemperature = formData.audio_wan2gp_temperature
    ?? settings?.audio_wan2gp_temperature
    ?? selectedWan2gpAudioPresetConfig?.default_temperature
    ?? 0.9
  const selectedWan2gpTopK = formData.audio_wan2gp_top_k
    ?? settings?.audio_wan2gp_top_k
    ?? selectedWan2gpAudioPresetConfig?.default_top_k
    ?? 50
  const selectedWan2gpSpeed = formData.audio_wan2gp_speed
    ?? settings?.audio_wan2gp_speed
    ?? 1.0
  const selectedWan2gpBaseAudioGuide = String(
    formData.audio_wan2gp_audio_guide
    ?? settings?.audio_wan2gp_audio_guide
    ?? ''
  ).trim()
  const selectedWan2gpSplitStrategy = (
    formData.audio_wan2gp_split_strategy
    ?? settings?.audio_wan2gp_split_strategy
    ?? 'sentence_punct'
  ) as 'sentence_punct' | 'anchor_tail'
  const selectedWan2gpBaseVoice = useMemo(
    () => activeVoiceLibraryItems.find((item) => isVoiceGuideMatch(item, selectedWan2gpBaseAudioGuide)),
    [activeVoiceLibraryItems, selectedWan2gpBaseAudioGuide]
  )
  const selectedWan2gpBaseVoiceId = selectedWan2gpBaseVoice
    ? String(selectedWan2gpBaseVoice.id)
    : (activeVoiceLibraryItems[0] ? String(activeVoiceLibraryItems[0].id) : '__empty__')
  const edgeSpeed = useMemo(
    () => rateToSpeed(formData.edge_tts_rate ?? settings?.edge_tts_rate ?? '0%'),
    [formData.edge_tts_rate, settings?.edge_tts_rate]
  )
  const selectedKlingAccessKey = String(
    formData.kling_access_key ?? settings?.kling_access_key ?? ''
  ).trim()
  const selectedKlingSecretKey = String(
    formData.kling_secret_key ?? settings?.kling_secret_key ?? ''
  ).trim()
  const hasSelectedKlingConfig = hasKlingCredentials({
    kling_access_key: selectedKlingAccessKey,
    kling_secret_key: selectedKlingSecretKey,
  })
  const selectedKlingBaseUrl = String(
    formData.kling_base_url ?? settings?.kling_base_url ?? 'https://api-beijing.klingai.com'
  ).trim() || 'https://api-beijing.klingai.com'
  const selectedKlingVoiceId = String(
    formData.audio_kling_voice_id ?? settings?.audio_kling_voice_id ?? 'zh_male_qn_qingse'
  ).trim() || 'zh_male_qn_qingse'
  const selectedKlingVoiceLanguage = String(
    formData.audio_kling_voice_language ?? settings?.audio_kling_voice_language ?? 'zh'
  ).trim().toLowerCase() || 'zh'
  const defaultKlingVoiceOption = KLING_TTS_VOICE_OPTIONS[0]
  const selectedKlingVoiceOptionValue = useMemo(() => {
    const exactMatch = KLING_TTS_VOICE_OPTIONS.find(
      (item) => item.voiceId === selectedKlingVoiceId && item.language === selectedKlingVoiceLanguage
    )
    if (exactMatch) return toKlingVoiceOptionValue(exactMatch.voiceId, exactMatch.language)
    return toKlingVoiceOptionValue(defaultKlingVoiceOption.voiceId, defaultKlingVoiceOption.language)
  }, [defaultKlingVoiceOption.language, defaultKlingVoiceOption.voiceId, selectedKlingVoiceId, selectedKlingVoiceLanguage])
  const selectedKlingVoiceSpeed = Number(
    formData.audio_kling_voice_speed ?? settings?.audio_kling_voice_speed ?? 1.0
  )
  const selectedViduApiKey = String(
    formData.vidu_api_key ?? settings?.vidu_api_key ?? ''
  ).trim()
  const selectedViduBaseUrl = String(
    formData.vidu_base_url ?? settings?.vidu_base_url ?? 'https://api.vidu.cn'
  ).trim() || 'https://api.vidu.cn'
  const selectedViduVoiceId = String(
    formData.audio_vidu_voice_id ?? settings?.audio_vidu_voice_id ?? 'female-shaonv'
  ).trim() || 'female-shaonv'
  const selectedViduVoiceOptionValue = useMemo(() => {
    const exists = VIDU_TTS_FALLBACK_OPTIONS.some((item) => item.value === selectedViduVoiceId)
    return exists ? selectedViduVoiceId : '__custom__'
  }, [selectedViduVoiceId])
  const selectedViduVoiceSpeed = Number(
    formData.audio_vidu_speed ?? settings?.audio_vidu_speed ?? 1.0
  )
  const selectedMinimaxApiKey = String(
    formData.minimax_api_key ?? settings?.minimax_api_key ?? ''
  ).trim()
  const selectedMinimaxBaseUrl = String(
    formData.minimax_base_url ?? settings?.minimax_base_url ?? 'https://api.minimaxi.com/v1'
  ).trim() || 'https://api.minimaxi.com/v1'
  const selectedMinimaxModel = String(
    formData.audio_minimax_model ?? settings?.audio_minimax_model ?? 'speech-2.8-turbo'
  ).trim() || 'speech-2.8-turbo'
  const selectedMinimaxVoiceId = String(
    formData.audio_minimax_voice_id ?? settings?.audio_minimax_voice_id ?? 'Chinese (Mandarin)_Reliable_Executive'
  ).trim() || 'Chinese (Mandarin)_Reliable_Executive'
  const selectedMinimaxVoiceSpeed = Number(
    formData.audio_minimax_speed ?? settings?.audio_minimax_speed ?? 1.0
  )
  const selectedMinimaxVoiceOptionValue = useMemo(() => {
    const availableOptions = minimaxVoices.length > 0
      ? minimaxVoices.map((voice) => voice.id)
      : MINIMAX_TTS_FALLBACK_OPTIONS.map((option) => option.value)
    return availableOptions.includes(selectedMinimaxVoiceId) ? selectedMinimaxVoiceId : '__custom__'
  }, [minimaxVoices, selectedMinimaxVoiceId])
  const selectedXiaomiMimoApiKey = String(
    formData.xiaomi_mimo_api_key ?? settings?.xiaomi_mimo_api_key ?? ''
  ).trim()
  const selectedXiaomiMimoBaseUrl = String(
    formData.xiaomi_mimo_base_url ?? settings?.xiaomi_mimo_base_url ?? 'https://api.xiaomimimo.com/v1'
  ).trim() || 'https://api.xiaomimimo.com/v1'
  const selectedXiaomiMimoVoice = String(
    formData.audio_xiaomi_mimo_voice ?? settings?.audio_xiaomi_mimo_voice ?? 'mimo_default'
  ).trim() || 'mimo_default'
  const selectedXiaomiMimoStylePreset = String(
    formData.audio_xiaomi_mimo_style_preset ?? settings?.audio_xiaomi_mimo_style_preset ?? ''
  ).trim()
  const selectedXiaomiMimoCombinedVoice = useMemo(() => {
    const exactStyleMatch = XIAOMI_MIMO_TTS_COMBINED_VOICE_OPTIONS.find(
      (option) => option.stylePreset === selectedXiaomiMimoStylePreset
    )
    if (exactStyleMatch) return exactStyleMatch.value
    const exactVoiceMatch = XIAOMI_MIMO_TTS_COMBINED_VOICE_OPTIONS.find(
      (option) => !option.stylePreset && option.voice === selectedXiaomiMimoVoice
    )
    return exactVoiceMatch?.value || 'voice::mimo_default'
  }, [selectedXiaomiMimoStylePreset, selectedXiaomiMimoVoice])
  const selectedXiaomiMimoSpeed = Number(
    formData.audio_xiaomi_mimo_speed ?? settings?.audio_xiaomi_mimo_speed ?? 1.0
  )
  const selectedVolcengineAppKey = String(
    formData.volcengine_tts_app_key ?? settings?.volcengine_tts_app_key ?? ''
  ).trim()
  const selectedVolcengineAccessKey = String(
    formData.volcengine_tts_access_key ?? settings?.volcengine_tts_access_key ?? ''
  ).trim()
  const selectedVolcengineModelNameRaw = String(
    formData.volcengine_tts_model_name ?? settings?.volcengine_tts_model_name ?? 'seed-tts-2.0'
  ).trim() || 'seed-tts-2.0'
  const selectedVolcengineModelName = VOLCENGINE_TTS_MODEL_OPTIONS.some(
    (item) => item.value === selectedVolcengineModelNameRaw
  )
    ? selectedVolcengineModelNameRaw
    : 'seed-tts-2.0'
  const selectedVolcengineDefaultVoice = VOLCENGINE_TTS_DEFAULT_VOICE_BY_MODEL[selectedVolcengineModelName]
    || VOLCENGINE_TTS_DEFAULT_VOICE_BY_MODEL['seed-tts-2.0']
  const selectedVolcengineVoiceType = String(
    formData.audio_volcengine_tts_voice_type ?? settings?.audio_volcengine_tts_voice_type ?? selectedVolcengineDefaultVoice
  ).trim() || selectedVolcengineDefaultVoice
  const selectedVolcengineSpeedRatio = Number(
    formData.audio_volcengine_tts_speed_ratio ?? settings?.audio_volcengine_tts_speed_ratio ?? 1.0
  )
  const clampRatio = (value: number, fallback = 1.0) => {
    if (!Number.isFinite(value)) return fallback
    return Math.max(0.5, Math.min(2.0, value))
  }
  const resolvedVolcengineVoiceSelectValue = useMemo(() => {
    if (volcengineVoices.some((item) => item.id === selectedVolcengineVoiceType)) {
      return selectedVolcengineVoiceType
    }
    return volcengineVoices[0]?.id || selectedVolcengineVoiceType
  }, [selectedVolcengineVoiceType, volcengineVoices])
  const edgePreviewText = useMemo(
    () => resolveAudioPreviewText(
      resolveVoiceLocale(
        availableVoices.length > 0 ? availableVoices : loadCachedVoices('edge_tts'),
        String(formData.edge_tts_voice ?? settings?.edge_tts_voice ?? ''),
        'zh-CN'
      )
    ),
    [availableVoices, formData.edge_tts_voice, settings?.edge_tts_voice]
  )
  const wan2gpPreviewText = AUDIO_PREVIEW_TEXT
  const volcenginePreviewText = useMemo(
    () => resolveAudioPreviewText(
      resolveVoiceLocale(volcengineVoices, selectedVolcengineVoiceType, 'zh-CN')
    ),
    [selectedVolcengineVoiceType, volcengineVoices]
  )
  const klingPreviewText = useMemo(
    () => resolveAudioPreviewText(selectedKlingVoiceLanguage === 'en' ? 'en-US' : 'zh-CN'),
    [selectedKlingVoiceLanguage]
  )
  const viduPreviewText = AUDIO_PREVIEW_TEXT
  const minimaxPreviewText = useMemo(
    () => resolveAudioPreviewText(resolveVoiceLocale(minimaxVoices, selectedMinimaxVoiceId, 'zh-CN')),
    [minimaxVoices, selectedMinimaxVoiceId]
  )
  const xiaomiMimoPreviewLocale = useMemo(() => {
    if (selectedXiaomiMimoStylePreset === 'tai_wan_qiang') return 'zh-TW'
    if (selectedXiaomiMimoStylePreset === 'yue_yu_zhu_bo') return 'zh-HK'
    return normalizeAudioPreviewLocale(
      resolveVoiceLocale(xiaomiMimoVoices, selectedXiaomiMimoVoice, 'zh-CN')
    )
  }, [selectedXiaomiMimoStylePreset, selectedXiaomiMimoVoice, xiaomiMimoVoices])
  const xiaomiMimoPreviewText = useMemo(
    () => resolveAudioPreviewText(xiaomiMimoPreviewLocale),
    [xiaomiMimoPreviewLocale]
  )
  const selectedXiaomiMimoCombinedVoiceMeta = useMemo(
    () => XIAOMI_MIMO_TTS_COMBINED_VOICE_OPTIONS.find((option) => option.value === selectedXiaomiMimoCombinedVoice),
    [selectedXiaomiMimoCombinedVoice]
  )
  const xiaomiMimoVoiceHelperText = selectedXiaomiMimoCombinedVoiceMeta?.stylePreset
    ? <>固定人设音色，会自动注入官方 <code>{'<style>'}</code> 标签。</>
    : '官方基础音色，直接使用 voice 参数。'
  const audioPreviewTexts: Record<
    'wan2gp' | 'edge_tts' | 'volcengine_tts' | 'kling_tts' | 'vidu_tts' | 'minimax_tts' | 'xiaomi_mimo_tts',
    string
  > = {
    wan2gp: wan2gpPreviewText,
    edge_tts: edgePreviewText,
    volcengine_tts: volcenginePreviewText,
    kling_tts: klingPreviewText,
    vidu_tts: viduPreviewText,
    minimax_tts: minimaxPreviewText,
    xiaomi_mimo_tts: xiaomiMimoPreviewText,
  }

  useEffect(() => {
    if (selectedWan2gpAudioPreset !== 'qwen3_tts_base') return
    if (activeVoiceLibraryItems.length === 0) return
    if (selectedWan2gpBaseVoice) return
    const firstVoice = activeVoiceLibraryItems[0]
    updateField('audio_wan2gp_audio_guide', resolveVoiceGuideValue(firstVoice))
    updateField('audio_wan2gp_alt_prompt', String(firstVoice?.reference_text || ''))
  }, [
    activeVoiceLibraryItems,
    selectedWan2gpAudioPreset,
    selectedWan2gpBaseVoice,
    updateField,
  ])

  const fetchVolcengineVoices = useCallback(async (forceRefresh = false, modelName?: string) => {
    const resolvedModelName = String(modelName || selectedVolcengineModelName || 'seed-tts-2.0').trim() || 'seed-tts-2.0'
    const cacheKey = `volcengine_tts_${resolvedModelName}`
    setVolcengineVoiceError(null)
    try {
      const response = await api.settings.fetchVoices('volcengine_tts', { forceRefresh, modelName: resolvedModelName })
      if (response.voices.length > 0) {
        setVolcengineVoices(response.voices)
        saveCachedVoices(response.voices, cacheKey)
      } else {
        setVolcengineVoiceError('未获取到可用音色')
      }
    } catch (error) {
      const cached = loadCachedVoices(cacheKey)
      if (cached.length > 0) {
        setVolcengineVoices(cached)
        setVolcengineVoiceError('在线音色加载失败，已使用缓存')
      } else {
        setVolcengineVoices([])
        setVolcengineVoiceError(error instanceof Error ? error.message : '音色加载失败')
      }
    }
  }, [selectedVolcengineModelName])

  useEffect(() => {
    const cacheKey = `volcengine_tts_${selectedVolcengineModelName}`
    const cached = loadCachedVoices(cacheKey)
    if (cached.length > 0) {
      const timer = window.setTimeout(() => {
        setVolcengineVoices(cached)
      }, 0)
      return () => window.clearTimeout(timer)
    }
  }, [selectedVolcengineModelName])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void fetchVolcengineVoices(false, selectedVolcengineModelName)
    }, 0)
    return () => window.clearTimeout(timer)
  }, [
    fetchVolcengineVoices,
    selectedVolcengineModelName,
  ])

  useEffect(() => {
    if (!selectedVolcengineVoiceType) return
    if (volcengineVoices.length === 0) return
    const exists = volcengineVoices.some((item) => item.id === selectedVolcengineVoiceType)
    if (exists) return
    const fallbackVoice = volcengineVoices[0]?.id || selectedVolcengineDefaultVoice
    if (!fallbackVoice) return
    updateField('audio_volcengine_tts_voice_type', fallbackVoice)
  }, [
    selectedVolcengineVoiceType,
    selectedVolcengineDefaultVoice,
    updateField,
    volcengineVoices,
  ])

  useEffect(() => {
    if (!selectedMinimaxVoiceId) return
    if (minimaxVoices.length === 0) return
    const exists = minimaxVoices.some((item) => item.id === selectedMinimaxVoiceId)
    if (exists) return
    const fallbackVoice = minimaxVoices[0]?.id || 'Chinese (Mandarin)_Reliable_Executive'
    if (!fallbackVoice) return
    updateField('audio_minimax_voice_id', fallbackVoice)
  }, [minimaxVoices, selectedMinimaxVoiceId, updateField])

  useEffect(() => {
    const exactMatch = KLING_TTS_VOICE_OPTIONS.find(
      (item) => item.voiceId === selectedKlingVoiceId && item.language === selectedKlingVoiceLanguage
    )
    if (exactMatch) return
    updateField('audio_kling_voice_id', defaultKlingVoiceOption.voiceId)
    updateField('audio_kling_voice_language', defaultKlingVoiceOption.language)
  }, [
    defaultKlingVoiceOption.language,
    defaultKlingVoiceOption.voiceId,
    selectedKlingVoiceId,
    selectedKlingVoiceLanguage,
    updateField,
  ])

  const handleEdgeSpeedChange = (value: number[]) => {
    const newSpeed = value[0]
    updateField('edge_tts_rate', speedToRate(newSpeed))
  }

  const handleWan2gpSpeedChange = (value: number[]) => {
    const newSpeed = value[0]
    updateField('audio_wan2gp_speed', newSpeed)
  }

  const handleVolcengineSpeedRatioChange = (value: number[]) => {
    updateField('audio_volcengine_tts_speed_ratio', value[0])
  }

  const handleKlingVoiceSpeedChange = (value: number[]) => {
    updateField('audio_kling_voice_speed', value[0])
  }

  const handleKlingVoiceChange = (value: string) => {
    const [voiceId, language] = value.split('::')
    if (!voiceId || (language !== 'zh' && language !== 'en')) return
    updateField('audio_kling_voice_id', voiceId)
    updateField('audio_kling_voice_language', language)
  }

  const handleViduVoiceSpeedChange = (value: number[]) => {
    updateField('audio_vidu_speed', value[0])
  }

  const handleXiaomiMimoVoiceSpeedChange = (value: number[]) => {
    updateField('audio_xiaomi_mimo_speed', value[0])
  }

  const handleViduVoiceChange = (value: string) => {
    if (value === '__custom__') return
    updateField('audio_vidu_voice_id', value)
  }

  const handleMinimaxVoiceSpeedChange = (value: number[]) => {
    updateField('audio_minimax_speed', value[0])
  }

  const handleMinimaxVoiceChange = (value: string) => {
    if (value === '__custom__') return
    updateField('audio_minimax_voice_id', value)
  }

  const handleXiaomiMimoCombinedVoiceChange = (value: string) => {
    const matched = XIAOMI_MIMO_TTS_COMBINED_VOICE_OPTIONS.find((option) => option.value === value)
    if (!matched) return
    updateField('audio_xiaomi_mimo_voice', matched.voice)
    updateField('audio_xiaomi_mimo_style_preset', matched.stylePreset)
  }

  const handleWan2gpAudioPresetChange = (presetId: string) => {
    updateField('audio_wan2gp_preset', presetId)
    const preset = wan2gpAudioPresets.find((item) => item.id === presetId)
    if (!preset) return
    const modeChoices = mapWan2gpModeOptions(preset)
    const resolvedMode = modeChoices.some((option) => option.value === preset.default_model_mode)
      ? preset.default_model_mode
      : (modeChoices[0]?.value || '')
    const defaultBaseVoice = activeVoiceLibraryItems[0]
    updateField('audio_wan2gp_model_mode', resolvedMode)
    updateField(
      'audio_wan2gp_alt_prompt',
      presetId === 'qwen3_tts_base'
        ? String(defaultBaseVoice?.reference_text || '')
        : preset.default_alt_prompt
    )
    updateField(
      'audio_wan2gp_audio_guide',
      presetId === 'qwen3_tts_base'
        ? resolveVoiceGuideValue(defaultBaseVoice)
        : ''
    )
    updateField('audio_wan2gp_temperature', preset.default_temperature)
    updateField('audio_wan2gp_top_k', preset.default_top_k)
    updateField('audio_wan2gp_seed', -1)
  }

  const buildAudioPreviewInput = (
    provider: 'wan2gp' | 'edge_tts' | 'volcengine_tts' | 'kling_tts' | 'vidu_tts' | 'minimax_tts' | 'xiaomi_mimo_tts'
  ): Record<string, unknown> => {
    const baseInput = {
      preview_text: audioPreviewTexts[provider],
    }
    if (provider === 'wan2gp') {
      return {
        ...baseInput,
        wan2gp_path: (formData.wan2gp_path ?? settings?.wan2gp_path ?? '').trim(),
        local_model_python_path: (formData.local_model_python_path ?? settings?.local_model_python_path ?? '').trim(),
        audio_wan2gp_preset: selectedWan2gpAudioPreset,
        audio_wan2gp_model_mode: selectedWan2gpAudioModeValue === '__empty__' ? '' : selectedWan2gpAudioModeValue,
        audio_wan2gp_alt_prompt: formData.audio_wan2gp_alt_prompt ?? settings?.audio_wan2gp_alt_prompt ?? '',
        audio_wan2gp_duration_seconds: formData.audio_wan2gp_duration_seconds ?? settings?.audio_wan2gp_duration_seconds ?? 600,
        audio_wan2gp_temperature: selectedWan2gpTemperature,
        audio_wan2gp_top_k: selectedWan2gpTopK,
        audio_wan2gp_seed: formData.audio_wan2gp_seed ?? settings?.audio_wan2gp_seed ?? -1,
        audio_wan2gp_audio_guide: formData.audio_wan2gp_audio_guide ?? settings?.audio_wan2gp_audio_guide ?? '',
        audio_wan2gp_speed: selectedWan2gpSpeed,
        audio_wan2gp_split_strategy: selectedWan2gpSplitStrategy,
      }
    }
    if (provider === 'volcengine_tts') {
      return {
        ...baseInput,
        volcengine_tts_app_key: selectedVolcengineAppKey,
        volcengine_tts_access_key: selectedVolcengineAccessKey,
        volcengine_tts_model_name: selectedVolcengineModelName,
        audio_volcengine_tts_voice_type: selectedVolcengineVoiceType,
        audio_volcengine_tts_speed_ratio: clampRatio(selectedVolcengineSpeedRatio),
        audio_volcengine_tts_volume_ratio: 1.0,
        audio_volcengine_tts_pitch_ratio: 1.0,
        audio_volcengine_tts_encoding: 'mp3',
      }
    }
    if (provider === 'kling_tts') {
      return {
        ...baseInput,
        kling_access_key: selectedKlingAccessKey,
        kling_secret_key: selectedKlingSecretKey,
        kling_base_url: selectedKlingBaseUrl,
        audio_kling_voice_id: selectedKlingVoiceId,
        audio_kling_voice_language: selectedKlingVoiceLanguage,
        audio_kling_voice_speed: clampRatio(selectedKlingVoiceSpeed),
      }
    }
    if (provider === 'vidu_tts') {
      return {
        ...baseInput,
        vidu_api_key: selectedViduApiKey,
        vidu_base_url: selectedViduBaseUrl,
        audio_vidu_voice_id: selectedViduVoiceId,
        audio_vidu_speed: clampRatio(selectedViduVoiceSpeed),
      }
    }
    if (provider === 'minimax_tts') {
      return {
        ...baseInput,
        minimax_api_key: selectedMinimaxApiKey,
        minimax_base_url: selectedMinimaxBaseUrl,
        audio_minimax_model: selectedMinimaxModel,
        audio_minimax_voice_id: selectedMinimaxVoiceId,
        audio_minimax_speed: clampRatio(selectedMinimaxVoiceSpeed),
      }
    }
    if (provider === 'xiaomi_mimo_tts') {
      return {
        ...baseInput,
        xiaomi_mimo_api_key: selectedXiaomiMimoApiKey,
        xiaomi_mimo_base_url: selectedXiaomiMimoBaseUrl,
        audio_xiaomi_mimo_voice: selectedXiaomiMimoVoice,
        audio_xiaomi_mimo_style_preset: selectedXiaomiMimoStylePreset,
        speed: clampRatio(selectedXiaomiMimoSpeed),
      }
    }
    return {
      ...baseInput,
      edge_tts_voice: formData.edge_tts_voice ?? settings?.edge_tts_voice ?? 'zh-CN-YunjianNeural',
      edge_tts_rate: formData.edge_tts_rate ?? settings?.edge_tts_rate ?? speedToRate(edgeSpeed),
    }
  }

  const { audioPreviewState, startAudioPreview } = useSettingsAudioPreview({
    buildAudioPreviewInput,
  })
  const deploymentProfile = (formData.deployment_profile ?? settings?.deployment_profile ?? 'cpu').trim().toLowerCase()
  const showWan2gpCard = deploymentProfile !== 'cpu'

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Volume2 className="h-5 w-5" />
          音频生成
        </CardTitle>
        <CardDescription>用于 TTS 语音合成</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-4">
          <div className="border rounded-lg p-4 space-y-4">
            <div className="flex items-center gap-2 flex-wrap">
              <div className="font-medium">
                Edge TTS
              </div>
              <Badge variant="outline">内置</Badge>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2 md:col-span-2">
                  <Label htmlFor="edge_tts_voice">音色</Label>
                  <Select
                    value={formData.edge_tts_voice ?? settings?.edge_tts_voice ?? ''}
                    onValueChange={(v) => updateField('edge_tts_voice', v)}
                  >
                    <SelectTrigger id="edge_tts_voice">
                      <SelectValue placeholder="选择语音" />
                    </SelectTrigger>
                    <SelectContent>
                      {availableVoices.length > 0 ? (
                        availableVoices.map((voice) => (
                          <SelectItem key={voice.id} value={voice.id}>
                            {voice.name}
                          </SelectItem>
                        ))
                      ) : isLoadingVoices ? (
                        <div className="px-2 py-1.5 text-sm text-muted-foreground">加载中...</div>
                      ) : (
                        <div className="px-2 py-1.5 text-sm text-muted-foreground">无可用语音</div>
                      )}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2 md:col-span-2">
                  <Label>语速 ({edgeSpeed.toFixed(1)}x)</Label>
                  <Slider
                    value={[edgeSpeed]}
                    onValueChange={handleEdgeSpeedChange}
                    min={0.5}
                    max={2.0}
                    step={0.1}
                    className="mt-3"
                  />
                </div>
                <div className="md:col-span-2 rounded-md border p-3 space-y-3">
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-medium">试用语音（固定文案）</p>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => startAudioPreview('edge_tts')}
                      disabled={audioPreviewState.edge_tts.isRunning}
                    >
                      {audioPreviewState.edge_tts.isRunning && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
                      试用
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground">{audioPreviewTexts.edge_tts}</p>
                  <p className="text-xs text-muted-foreground">
                    当前状态：{audioPreviewState.edge_tts.status}
                  </p>
                  {audioPreviewState.edge_tts.error && (
                    <p className="text-xs text-destructive">{audioPreviewState.edge_tts.error}</p>
                  )}
                  {audioPreviewState.edge_tts.audioUrl && (
                    <AudioPlayer src={audioPreviewState.edge_tts.audioUrl} className="w-full" />
                  )}
                </div>
            </div>
          </div>

          {showWan2gpCard && (
            <div className="border rounded-lg p-4 space-y-4 order-1">
            <div className="flex items-center gap-2 flex-wrap">
              <div className="font-medium">
                Wan2GP
              </div>
              <Badge variant="outline">本地</Badge>
              {settings?.wan2gp_available ? (
                <Badge variant="outline" className="text-green-600">
                  <Check className="h-3 w-3 mr-1" />
                  已就绪
                </Badge>
              ) : (
                  <Badge variant="outline">需配置路径</Badge>
              )}
            </div>
            <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2 md:col-span-2">
                  <Label htmlFor="audio_wan2gp_preset">TTS 模型</Label>
                  <Select
                    value={selectedWan2gpAudioPreset}
                    onValueChange={handleWan2gpAudioPresetChange}
                  >
                    <SelectTrigger id="audio_wan2gp_preset">
                      <SelectValue placeholder="选择模型" />
                    </SelectTrigger>
                    <SelectContent>
                      {wan2gpAudioPresets.length > 0 ? (
                        wan2gpAudioPresets.map((preset) => (
                          <SelectItem key={preset.id} value={preset.id}>
                            {preset.display_name}
                          </SelectItem>
                        ))
                      ) : (
                        <SelectItem value={selectedWan2gpAudioPreset}>
                          {selectedWan2gpAudioPreset}
                        </SelectItem>
                      )}
                    </SelectContent>
                  </Select>
                  {selectedWan2gpAudioPresetDescription && (
                    <p className="text-xs text-muted-foreground">
                      {selectedWan2gpAudioPresetDescription}
                    </p>
                  )}
                </div>
                <div className="space-y-2 md:col-span-2">
                  <Label htmlFor="audio_wan2gp_model_mode">
                    {selectedWan2gpAudioPresetConfig?.model_mode_label || '模式'}
                  </Label>
                  <Select
                    value={selectedWan2gpAudioModeValue || '__empty__'}
                    onValueChange={(v) => updateField('audio_wan2gp_model_mode', v === '__empty__' ? '' : v)}
                  >
                    <SelectTrigger id="audio_wan2gp_model_mode">
                      <SelectValue placeholder={`选择${selectedWan2gpAudioPresetConfig?.model_mode_label || '模式'}`} />
                    </SelectTrigger>
                    <SelectContent>
                      {selectedWan2gpAudioModeOptions.length > 0 ? (
                        selectedWan2gpAudioModeOptions.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))
                      ) : (
                        <SelectItem value="__empty__">无</SelectItem>
                      )}
                    </SelectContent>
                  </Select>
                </div>
                {selectedWan2gpAudioPreset === 'qwen3_tts_base' ? (
                  <div className="space-y-2 md:col-span-2">
                    <Label htmlFor="audio_wan2gp_voice_library">语音库预设</Label>
                    <Select
                      value={selectedWan2gpBaseVoiceId}
                      onValueChange={(voiceId) => {
                        const selectedVoice = activeVoiceLibraryItems.find((item) => String(item.id) === voiceId)
                        updateField('audio_wan2gp_audio_guide', resolveVoiceGuideValue(selectedVoice))
                        updateField('audio_wan2gp_alt_prompt', String(selectedVoice?.reference_text || ''))
                      }}
                      disabled={activeVoiceLibraryItems.length === 0}
                    >
                      <SelectTrigger id="audio_wan2gp_voice_library">
                        <SelectValue placeholder="请选择语音库预设" />
                      </SelectTrigger>
                      <SelectContent>
                        {activeVoiceLibraryItems.length > 0 ? (
                          activeVoiceLibraryItems.map((item) => (
                            <SelectItem key={item.id} value={String(item.id)}>
                              {item.name}
                            </SelectItem>
                          ))
                        ) : (
                          <SelectItem value="__empty__" disabled>暂无可用语音</SelectItem>
                        )}
                      </SelectContent>
                    </Select>
                    {selectedWan2gpBaseVoice?.reference_text && (
                      <p className="text-xs text-muted-foreground">
                        参考文本：{selectedWan2gpBaseVoice.reference_text}
                      </p>
                    )}
                    {activeVoiceLibraryItems.length === 0 && (
                      <p className="text-xs text-amber-700">
                        当前没有可用语音，请先在语音库中启用并上传音频。
                      </p>
                    )}
                  </div>
                ) : (
                  <div className="space-y-2 md:col-span-2">
                    <Label htmlFor="audio_wan2gp_alt_prompt">
                      {selectedWan2gpAudioPreset === 'qwen3_tts_voicedesign'
                        ? '音色指令（可选）'
                        : '风格指令（可选）'}
                    </Label>
                    <Input
                      id="audio_wan2gp_alt_prompt"
                      value={formData.audio_wan2gp_alt_prompt ?? settings?.audio_wan2gp_alt_prompt ?? ''}
                      onChange={(e) => updateField('audio_wan2gp_alt_prompt', e.target.value)}
                    />
                  </div>
                )}
                <div className="space-y-2">
                  <Label>Temperature ({selectedWan2gpTemperature.toFixed(2)})</Label>
                  <Slider
                    value={[selectedWan2gpTemperature]}
                    onValueChange={(value) => updateField('audio_wan2gp_temperature', value[0])}
                    min={0.1}
                    max={1.5}
                    step={0.05}
                    className="mt-3"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Top-K ({selectedWan2gpTopK})</Label>
                  <Slider
                    value={[selectedWan2gpTopK]}
                    onValueChange={(value) => updateField('audio_wan2gp_top_k', value[0])}
                    min={1}
                    max={100}
                    step={1}
                    className="mt-3"
                  />
                </div>
                <div className="space-y-2 md:col-span-2">
                  <Label htmlFor="audio_wan2gp_seed">Seed（-1 为随机）</Label>
                  <Input
                    id="audio_wan2gp_seed"
                    type="number"
                    value={formData.audio_wan2gp_seed ?? settings?.audio_wan2gp_seed ?? -1}
                    onChange={(e) => {
                      const next = parseInt(e.target.value, 10)
                      updateField('audio_wan2gp_seed', Number.isFinite(next) ? next : -1)
                    }}
                  />
                </div>
                <div className="space-y-2 md:col-span-2">
                  <Label>语速 ({selectedWan2gpSpeed.toFixed(1)}x)</Label>
                  <Slider
                    value={[selectedWan2gpSpeed]}
                    onValueChange={handleWan2gpSpeedChange}
                    min={0.5}
                    max={2.0}
                    step={0.1}
                    className="mt-3"
                  />
                </div>
                {!settings?.wan2gp_available && (
                  <p className="text-xs text-muted-foreground md:col-span-2">
                    当前 Wan2GP 未就绪，请先在下方本地模型配置中设置路径并校验。
                  </p>
                )}
                <div className="md:col-span-2 rounded-md border p-3 space-y-3">
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-medium">试用语音（固定文案）</p>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => startAudioPreview('wan2gp')}
                      disabled={audioPreviewState.wan2gp.isRunning}
                    >
                      {audioPreviewState.wan2gp.isRunning && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
                      试用
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground">{audioPreviewTexts.wan2gp}</p>
                  <p className="text-xs text-muted-foreground">
                    当前状态：{audioPreviewState.wan2gp.status}
                  </p>
                  {audioPreviewState.wan2gp.error && (
                    <p className="text-xs text-destructive">{audioPreviewState.wan2gp.error}</p>
                  )}
                  {audioPreviewState.wan2gp.audioUrl && (
                    <AudioPlayer src={audioPreviewState.wan2gp.audioUrl} className="w-full" />
                  )}
                </div>
            </div>
            </div>
          )}

          <div className="border rounded-lg p-4 space-y-4 order-2">
            <div className="flex items-center gap-2 flex-wrap">
              <div className="font-medium">火山引擎 TTS</div>
              <Badge variant="outline">在线</Badge>
              {settings?.volcengine_tts_app_key_set && settings?.volcengine_tts_access_key_set ? (
                <Badge variant="outline" className="text-green-600">
                  <Check className="h-3 w-3 mr-1" />
                  已配置
                </Badge>
              ) : (
                <Badge variant="outline">需配置密钥</Badge>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              参数获取教程：
              <a
                href="https://www.volcengine.com/docs/6561/196768?lang=zh#q1%EF%BC%9A%E5%93%AA%E9%87%8C%E5%8F%AF%E4%BB%A5%E8%8E%B7%E5%8F%96%E5%88%B0%E4%BB%A5%E4%B8%8B%E5%8F%82%E6%95%B0appid%EF%BC%8Ccluster%EF%BC%8Ctoken%EF%BC%8Cauthorization-type%EF%BC%8Csecret-key-%EF%BC%9F"
                target="_blank"
                rel="noopener noreferrer"
                className="ml-1 text-primary underline underline-offset-2"
              >
                查看如何获取 APP ID / Access Token
              </a>
            </p>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="volcengine_tts_app_key">APP ID</Label>
                <SecretInput
                  id="volcengine_tts_app_key"
                  visible={Boolean(showApiKeys.volcengine_tts_app_key)}
                  onToggleVisibility={() => onToggleApiKey('volcengine_tts_app_key')}
                  value={formData.volcengine_tts_app_key ?? settings?.volcengine_tts_app_key ?? ''}
                  onChange={(e) => updateField('volcengine_tts_app_key', e.target.value)}
                  placeholder="输入火山语音合成 APP ID"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="volcengine_tts_access_key">Access Token</Label>
                <SecretInput
                  id="volcengine_tts_access_key"
                  visible={Boolean(showApiKeys.volcengine_tts_access_key)}
                  onToggleVisibility={() => onToggleApiKey('volcengine_tts_access_key')}
                  value={formData.volcengine_tts_access_key ?? settings?.volcengine_tts_access_key ?? ''}
                  onChange={(e) => updateField('volcengine_tts_access_key', e.target.value)}
                  placeholder="输入火山语音合成 Access Token"
                />
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label htmlFor="volcengine_tts_model_name">合成模型</Label>
                <Select
                  value={selectedVolcengineModelName}
                  onValueChange={(v) => updateField('volcengine_tts_model_name', v)}
                >
                  <SelectTrigger id="volcengine_tts_model_name">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {VOLCENGINE_TTS_MODEL_OPTIONS.map((item) => (
                      <SelectItem key={item.value} value={item.value}>
                        {item.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label htmlFor="audio_volcengine_tts_voice_type">音色（voice_type）</Label>
                <Select
                  value={resolvedVolcengineVoiceSelectValue}
                  onValueChange={(v) => updateField('audio_volcengine_tts_voice_type', v)}
                >
                  <SelectTrigger id="audio_volcengine_tts_voice_type">
                    <SelectValue placeholder="选择音色" />
                  </SelectTrigger>
                  <SelectContent>
                    {volcengineVoices.length > 0 ? (
                      volcengineVoices.map((voice) => (
                        <SelectItem key={voice.id} value={voice.id}>
                          {toVoiceDisplayName(voice)}
                        </SelectItem>
                      ))
                    ) : (
                      <div className="px-2 py-1.5 text-sm text-muted-foreground">无可用音色</div>
                    )}
                  </SelectContent>
                </Select>
                {volcengineVoiceError && (
                  <p className="text-xs text-amber-700">{volcengineVoiceError}</p>
                )}
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label>语速 ({clampRatio(selectedVolcengineSpeedRatio).toFixed(1)}x)</Label>
                <Slider
                  value={[clampRatio(selectedVolcengineSpeedRatio)]}
                  onValueChange={handleVolcengineSpeedRatioChange}
                  min={0.5}
                  max={2.0}
                  step={0.1}
                  className="mt-3"
                />
              </div>
              <div className="md:col-span-2 rounded-md border p-3 space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium">试用语音（固定文案）</p>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => startAudioPreview('volcengine_tts')}
                    disabled={audioPreviewState.volcengine_tts.isRunning}
                  >
                    {audioPreviewState.volcengine_tts.isRunning && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
                    试用
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">{audioPreviewTexts.volcengine_tts}</p>
                <p className="text-xs text-muted-foreground">
                  当前状态：{audioPreviewState.volcengine_tts.status}
                </p>
                {audioPreviewState.volcengine_tts.error && (
                  <p className="text-xs text-destructive">{audioPreviewState.volcengine_tts.error}</p>
                )}
                {audioPreviewState.volcengine_tts.audioUrl && (
                  <AudioPlayer src={audioPreviewState.volcengine_tts.audioUrl} className="w-full" />
                )}
              </div>
            </div>
          </div>

          <div className="border rounded-lg p-4 space-y-4 order-3">
            <div className="flex items-center gap-2 flex-wrap">
              <div className="font-medium">可灵 TTS</div>
              <Badge variant="outline">在线</Badge>
              {hasKlingCredentials(settings) ? (
                <Badge variant="outline" className="text-green-600">
                  <Check className="h-3 w-3 mr-1" />
                  已配置
                </Badge>
              ) : (
                <Badge variant="outline">需配置密钥</Badge>
              )}
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="kling_access_key">Access Key</Label>
                <SecretInput
                  id="kling_access_key"
                  visible={Boolean(showApiKeys.kling_access_key)}
                  onToggleVisibility={() => onToggleApiKey('kling_access_key')}
                  value={formData.kling_access_key ?? settings?.kling_access_key ?? ''}
                  onChange={(e) => updateField('kling_access_key', e.target.value)}
                  placeholder="输入可灵 Access Key"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="kling_secret_key">Secret Key</Label>
                <SecretInput
                  id="kling_secret_key"
                  visible={Boolean(showApiKeys.kling_secret_key)}
                  onToggleVisibility={() => onToggleApiKey('kling_secret_key')}
                  value={formData.kling_secret_key ?? settings?.kling_secret_key ?? ''}
                  onChange={(e) => updateField('kling_secret_key', e.target.value)}
                  placeholder="输入可灵 Secret Key"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="kling_base_url">Base URL</Label>
                <Input
                  id="kling_base_url"
                  value={formData.kling_base_url ?? settings?.kling_base_url ?? 'https://api-beijing.klingai.com'}
                  onChange={(e) => updateField('kling_base_url', e.target.value)}
                />
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label htmlFor="audio_kling_voice_id">音色（voice_id）</Label>
                <Select
                  value={selectedKlingVoiceOptionValue}
                  onValueChange={handleKlingVoiceChange}
                >
                  <SelectTrigger id="audio_kling_voice_id">
                    <SelectValue placeholder="选择音色" />
                  </SelectTrigger>
                  <SelectContent>
                    {KLING_TTS_VOICE_OPTIONS.map((option) => (
                      <SelectItem
                        key={toKlingVoiceOptionValue(option.voiceId, option.language)}
                        value={toKlingVoiceOptionValue(option.voiceId, option.language)}
                      >
                        {option.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label>语速 ({clampRatio(selectedKlingVoiceSpeed).toFixed(1)}x)</Label>
                <Slider
                  value={[clampRatio(selectedKlingVoiceSpeed)]}
                  onValueChange={handleKlingVoiceSpeedChange}
                  min={0.8}
                  max={2.0}
                  step={0.1}
                  className="mt-3"
                />
              </div>
              <div className="md:col-span-2 rounded-md border p-3 space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium">试用语音（固定文案）</p>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => startAudioPreview('kling_tts')}
                    disabled={!hasSelectedKlingConfig || audioPreviewState.kling_tts.isRunning}
                  >
                    {audioPreviewState.kling_tts.isRunning && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
                    试用
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">{audioPreviewTexts.kling_tts}</p>
                <p className="text-xs text-muted-foreground">
                  当前状态：{audioPreviewState.kling_tts.status}
                </p>
                {audioPreviewState.kling_tts.error && (
                  <p className="text-xs text-destructive">{audioPreviewState.kling_tts.error}</p>
                )}
                {audioPreviewState.kling_tts.audioUrl && (
                  <AudioPlayer src={audioPreviewState.kling_tts.audioUrl} className="w-full" />
                )}
              </div>
            </div>
          </div>

          <div className="border rounded-lg p-4 space-y-4 order-4">
            <div className="flex items-center gap-2 flex-wrap">
              <div className="font-medium">Vidu TTS</div>
              <Badge variant="outline">在线</Badge>
              {settings?.vidu_api_key_set ? (
                <Badge variant="outline" className="text-green-600">
                  <Check className="h-3 w-3 mr-1" />
                  已配置
                </Badge>
              ) : (
                <Badge variant="outline">需配置密钥</Badge>
              )}
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="vidu_api_key">API Key</Label>
                <SecretInput
                  id="vidu_api_key"
                  visible={Boolean(showApiKeys.vidu_api_key)}
                  onToggleVisibility={() => onToggleApiKey('vidu_api_key')}
                  value={formData.vidu_api_key ?? settings?.vidu_api_key ?? ''}
                  onChange={(e) => updateField('vidu_api_key', e.target.value)}
                  placeholder="输入 Vidu API Key"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="vidu_base_url">Base URL</Label>
                <Input
                  id="vidu_base_url"
                  value={formData.vidu_base_url ?? settings?.vidu_base_url ?? 'https://api.vidu.cn'}
                  onChange={(e) => updateField('vidu_base_url', e.target.value)}
                />
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label htmlFor="audio_vidu_voice_id">音色</Label>
                <Select
                  value={selectedViduVoiceOptionValue}
                  onValueChange={handleViduVoiceChange}
                >
                  <SelectTrigger id="audio_vidu_voice_id">
                    <SelectValue placeholder="选择音色" />
                  </SelectTrigger>
                  <SelectContent>
                    {selectedViduVoiceOptionValue === '__custom__' && (
                      <SelectItem value="__custom__">
                        当前值（未收录）：{selectedViduVoiceId}
                      </SelectItem>
                    )}
                    {VIDU_TTS_FALLBACK_OPTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label>语速 ({clampRatio(selectedViduVoiceSpeed).toFixed(1)}x)</Label>
                <Slider
                  value={[clampRatio(selectedViduVoiceSpeed)]}
                  onValueChange={handleViduVoiceSpeedChange}
                  min={0.5}
                  max={2.0}
                  step={0.1}
                  className="mt-3"
                />
              </div>
              <div className="md:col-span-2 rounded-md border p-3 space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium">试用语音（固定文案）</p>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => startAudioPreview('vidu_tts')}
                    disabled={audioPreviewState.vidu_tts.isRunning}
                  >
                    {audioPreviewState.vidu_tts.isRunning && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
                    试用
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">{audioPreviewTexts.vidu_tts}</p>
                <p className="text-xs text-muted-foreground">
                  当前状态：{audioPreviewState.vidu_tts.status}
                </p>
                {audioPreviewState.vidu_tts.error && (
                  <p className="text-xs text-destructive">{audioPreviewState.vidu_tts.error}</p>
                )}
                {audioPreviewState.vidu_tts.audioUrl && (
                  <AudioPlayer src={audioPreviewState.vidu_tts.audioUrl} className="w-full" />
                )}
              </div>
            </div>
          </div>

          <div className="border rounded-lg p-4 space-y-4 order-5">
            <div className="flex items-center gap-2 flex-wrap">
              <div className="font-medium">MiniMax TTS</div>
              <Badge variant="outline">在线</Badge>
              {settings?.minimax_api_key_set ? (
                <Badge variant="outline" className="text-green-600">
                  <Check className="h-3 w-3 mr-1" />
                  已配置
                </Badge>
              ) : (
                <Badge variant="outline">需配置密钥</Badge>
              )}
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="minimax_api_key">API Key</Label>
                <SecretInput
                  id="minimax_api_key"
                  visible={Boolean(showApiKeys.minimax_api_key)}
                  onToggleVisibility={() => onToggleApiKey('minimax_api_key')}
                  value={formData.minimax_api_key ?? settings?.minimax_api_key ?? ''}
                  onChange={(e) => updateField('minimax_api_key', e.target.value)}
                  placeholder="输入 MiniMax API Key"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="minimax_base_url">Base URL</Label>
                <Input
                  id="minimax_base_url"
                  value={formData.minimax_base_url ?? settings?.minimax_base_url ?? 'https://api.minimaxi.com/v1'}
                  onChange={(e) => updateField('minimax_base_url', e.target.value)}
                />
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label htmlFor="audio_minimax_model">模型</Label>
                <Select
                  value={selectedMinimaxModel}
                  onValueChange={(value) => updateField('audio_minimax_model', value)}
                >
                  <SelectTrigger id="audio_minimax_model">
                    <SelectValue placeholder="选择模型" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="speech-2.8-turbo">speech-2.8-turbo</SelectItem>
                    <SelectItem value="speech-2.8-hd">speech-2.8-hd</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label htmlFor="audio_minimax_voice_id">音色</Label>
                <Select
                  value={selectedMinimaxVoiceOptionValue}
                  onValueChange={handleMinimaxVoiceChange}
                >
                  <SelectTrigger id="audio_minimax_voice_id">
                    <SelectValue placeholder="选择音色" />
                  </SelectTrigger>
                  <SelectContent>
                    {selectedMinimaxVoiceOptionValue === '__custom__' && (
                      <SelectItem value="__custom__">
                        当前值（未收录）：{selectedMinimaxVoiceId}
                      </SelectItem>
                    )}
                    {(minimaxVoices.length > 0
                      ? minimaxVoices.map((voice) => ({
                        value: voice.id,
                        label: toVoiceDisplayName(voice),
                      }))
                      : MINIMAX_TTS_FALLBACK_OPTIONS
                    ).map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label>语速 ({clampRatio(selectedMinimaxVoiceSpeed).toFixed(1)}x)</Label>
                <Slider
                  value={[clampRatio(selectedMinimaxVoiceSpeed)]}
                  onValueChange={handleMinimaxVoiceSpeedChange}
                  min={0.5}
                  max={2.0}
                  step={0.1}
                  className="mt-3"
                />
              </div>
              <div className="md:col-span-2 rounded-md border p-3 space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium">试用语音（固定文案）</p>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => startAudioPreview('minimax_tts')}
                    disabled={audioPreviewState.minimax_tts.isRunning}
                  >
                    {audioPreviewState.minimax_tts.isRunning && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
                    试用
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">{audioPreviewTexts.minimax_tts}</p>
                <p className="text-xs text-muted-foreground">
                  当前状态：{audioPreviewState.minimax_tts.status}
                </p>
                {audioPreviewState.minimax_tts.error && (
                  <p className="text-xs text-destructive">{audioPreviewState.minimax_tts.error}</p>
                )}
                {audioPreviewState.minimax_tts.audioUrl && (
                  <AudioPlayer src={audioPreviewState.minimax_tts.audioUrl} className="w-full" />
                )}
              </div>
            </div>
          </div>

          <div className="border rounded-lg p-4 space-y-4 order-6">
            <div className="flex items-center gap-2 flex-wrap">
              <div className="font-medium">小米 MiMo TTS</div>
              <Badge variant="outline">在线</Badge>
              {settings?.xiaomi_mimo_api_key_set ? (
                <Badge variant="outline" className="text-green-600">
                  <Check className="h-3 w-3 mr-1" />
                  已配置
                </Badge>
              ) : (
                <Badge variant="outline">需配置密钥</Badge>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              参考文档：
              <a
                href="https://platform.xiaomimimo.com/#/docs/api/chat/openai-api"
                target="_blank"
                rel="noopener noreferrer"
                className="ml-1 text-primary underline underline-offset-2"
              >
                OpenAI 兼容接口
              </a>
              <a
                href="https://platform.xiaomimimo.com/#/docs/usage-guide/speech-synthesis"
                target="_blank"
                rel="noopener noreferrer"
                className="ml-3 text-primary underline underline-offset-2"
              >
                语音合成风格指南
              </a>
            </p>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="xiaomi_mimo_api_key">API Key</Label>
                <SecretInput
                  id="xiaomi_mimo_api_key"
                  visible={Boolean(showApiKeys.xiaomi_mimo_api_key)}
                  onToggleVisibility={() => onToggleApiKey('xiaomi_mimo_api_key')}
                  value={formData.xiaomi_mimo_api_key ?? settings?.xiaomi_mimo_api_key ?? ''}
                  onChange={(e) => updateField('xiaomi_mimo_api_key', e.target.value)}
                  placeholder="输入小米 MiMo API Key"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="xiaomi_mimo_base_url">Base URL</Label>
                <Input
                  id="xiaomi_mimo_base_url"
                  value={formData.xiaomi_mimo_base_url ?? settings?.xiaomi_mimo_base_url ?? 'https://api.xiaomimimo.com/v1'}
                  onChange={(e) => updateField('xiaomi_mimo_base_url', e.target.value)}
                />
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label htmlFor="audio_xiaomi_mimo_voice">音色</Label>
                <Select
                  value={selectedXiaomiMimoCombinedVoice}
                  onValueChange={handleXiaomiMimoCombinedVoiceChange}
                >
                  <SelectTrigger id="audio_xiaomi_mimo_voice">
                    <SelectValue placeholder="选择音色" />
                  </SelectTrigger>
                  <SelectContent>
                    {XIAOMI_MIMO_TTS_COMBINED_VOICE_OPTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  {xiaomiMimoVoiceHelperText}
                </p>
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label>语速 ({clampRatio(selectedXiaomiMimoSpeed).toFixed(1)}x)</Label>
                <Slider
                  value={[clampRatio(selectedXiaomiMimoSpeed)]}
                  onValueChange={handleXiaomiMimoVoiceSpeedChange}
                  min={0.5}
                  max={2.0}
                  step={0.1}
                  className="mt-3"
                />
              </div>
              <div className="md:col-span-2 rounded-md border p-3 space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium">试用语音（固定文案）</p>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => startAudioPreview('xiaomi_mimo_tts')}
                    disabled={audioPreviewState.xiaomi_mimo_tts.isRunning}
                  >
                    {audioPreviewState.xiaomi_mimo_tts.isRunning && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
                    试用
                  </Button>
                </div>
                <p className="text-xs text-muted-foreground">{audioPreviewTexts.xiaomi_mimo_tts}</p>
                <p className="text-xs text-muted-foreground">
                  当前状态：{audioPreviewState.xiaomi_mimo_tts.status}
                </p>
                {audioPreviewState.xiaomi_mimo_tts.error && (
                  <p className="text-xs text-destructive">{audioPreviewState.xiaomi_mimo_tts.error}</p>
                )}
                {audioPreviewState.xiaomi_mimo_tts.audioUrl && (
                  <AudioPlayer src={audioPreviewState.xiaomi_mimo_tts.audioUrl} className="w-full" />
                )}
              </div>
            </div>
          </div>

        </div>
      </CardContent>
    </Card>
  )
}
