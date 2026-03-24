'use client'

import { useCallback, useMemo } from 'react'

import {
  useSettingsProvidersQuery,
  useSettingsQuery,
  useSettingsVoicesQuery,
  useWan2gpAudioPresetsQuery,
} from '@/hooks/use-settings-queries'
import {
  EDGE_TTS_DEFAULT_VOICE,
  KLING_TTS_DEFAULT_VOICE,
  XIAOMI_MIMO_TTS_DEFAULT_VOICE,
  VIDU_TTS_DEFAULT_VOICE,
  VOLCENGINE_TTS_DEFAULT_VOICE,
  WAN2GP_DEFAULT_MODE,
  clamp,
  mapEdgeVoiceOptions,
  mapVolcengineVoiceOptions,
  normalizeVoiceProvider,
  rateToSpeed,
  resolveAvailableAudioProviders,
  resolveDefaultAudioProvider,
  resolveDefaultWan2gpPresetId,
  resolveVoiceLabel as resolveVoiceLabelFromOptions,
  resolveVoiceOptions,
  resolveWan2gpPreset,
  toFiniteInt,
  toFiniteNumber,
  type ReferenceVoiceProvider,
  type VoiceOption,
} from '@/lib/reference-voice'
import type { Wan2gpAudioPreset } from '@/types/settings'

export { normalizeVoiceProvider, rateToSpeed, speedToRate } from '@/lib/reference-voice'

export interface ReferenceVoiceConfig {
  voice_audio_provider: ReferenceVoiceProvider
  voice_name: string
  voice_speed?: number
  voice_wan2gp_preset?: string
  voice_wan2gp_alt_prompt?: string
  voice_wan2gp_audio_guide?: string
  voice_wan2gp_temperature?: number
  voice_wan2gp_top_k?: number
  voice_wan2gp_seed?: number
}

export interface ReferenceVoiceMeta {
  availableAudioProviders: ReferenceVoiceProvider[]
  defaultAudioProvider: ReferenceVoiceProvider
  edgeVoiceOptions: VoiceOption[]
  volcengineVoiceOptions: VoiceOption[]
  wan2gpPresets: Wan2gpAudioPreset[]
  normalizeConfig: (raw: Partial<ReferenceVoiceConfig> | null | undefined) => ReferenceVoiceConfig
  toPayload: (
    canSpeak: boolean,
    raw: Partial<ReferenceVoiceConfig> | null | undefined
  ) => Partial<ReferenceVoiceConfig>
  getVoiceOptions: (provider: ReferenceVoiceProvider, presetId?: string) => VoiceOption[]
  getWan2gpPreset: (presetId?: string) => Wan2gpAudioPreset | undefined
  resolveVoiceLabel: (
    provider: ReferenceVoiceProvider,
    voiceName: string | undefined,
    presetId?: string
  ) => string
}

export function useReferenceVoiceMeta(): ReferenceVoiceMeta {
  const { data: settingsData } = useSettingsQuery()
  const { data: providerData } = useSettingsProvidersQuery()
  const volcengineVoiceQueryEnabled = Boolean(
    providerData?.audio?.includes('volcengine_tts')
  )
  const { data: edgeVoiceData } = useSettingsVoicesQuery('edge_tts')
  const { data: volcengineVoiceData } = useSettingsVoicesQuery(
    'volcengine_tts',
    volcengineVoiceQueryEnabled,
    { modelName: settingsData?.volcengine_tts_model_name }
  )

  const availableAudioProviders = useMemo<ReferenceVoiceProvider[]>(() => {
    return resolveAvailableAudioProviders(providerData?.audio, settingsData?.wan2gp_available)
  }, [providerData?.audio, settingsData?.wan2gp_available])

  const defaultAudioProvider = useMemo<ReferenceVoiceProvider>(() => {
    return resolveDefaultAudioProvider(
      settingsData?.default_audio_provider,
      availableAudioProviders
    )
  }, [availableAudioProviders, settingsData?.default_audio_provider])

  const edgeVoiceOptions = useMemo<VoiceOption[]>(() => {
    return mapEdgeVoiceOptions(edgeVoiceData?.voices)
  }, [edgeVoiceData?.voices])
  const volcengineVoiceOptions = useMemo<VoiceOption[]>(() => {
    return mapVolcengineVoiceOptions(volcengineVoiceData?.voices)
  }, [volcengineVoiceData?.voices])
  const edgeDefaultVoice = useMemo(() => {
    const configured = String(settingsData?.edge_tts_voice || '').trim()
    if (configured) return configured
    const hasYunjian = edgeVoiceOptions.some((item) => item.value === EDGE_TTS_DEFAULT_VOICE)
    if (hasYunjian) return EDGE_TTS_DEFAULT_VOICE
    return edgeVoiceOptions[0]?.value || EDGE_TTS_DEFAULT_VOICE
  }, [edgeVoiceOptions, settingsData?.edge_tts_voice])
  const volcengineDefaultVoice = useMemo(() => {
    const configured = String(settingsData?.audio_volcengine_tts_voice_type || '').trim()
    if (configured) return configured
    const hasDefault = volcengineVoiceOptions.some((item) => item.value === VOLCENGINE_TTS_DEFAULT_VOICE)
    if (hasDefault) return VOLCENGINE_TTS_DEFAULT_VOICE
    return volcengineVoiceOptions[0]?.value || VOLCENGINE_TTS_DEFAULT_VOICE
  }, [settingsData?.audio_volcengine_tts_voice_type, volcengineVoiceOptions])
  const klingDefaultVoice = useMemo(() => {
    const configured = String(settingsData?.audio_kling_voice_id || '').trim()
    return configured || KLING_TTS_DEFAULT_VOICE
  }, [settingsData?.audio_kling_voice_id])
  const viduDefaultVoice = useMemo(() => {
    const configured = String(settingsData?.audio_vidu_voice_id || '').trim()
    return configured || VIDU_TTS_DEFAULT_VOICE
  }, [settingsData?.audio_vidu_voice_id])
  const xiaomiMimoDefaultVoice = useMemo(() => {
    const configured = String(settingsData?.audio_xiaomi_mimo_voice || '').trim()
    return configured || XIAOMI_MIMO_TTS_DEFAULT_VOICE
  }, [settingsData?.audio_xiaomi_mimo_voice])

  const { data: wan2gpAudioPresetData } = useWan2gpAudioPresetsQuery(
    availableAudioProviders.includes('wan2gp')
  )
  const wan2gpPresets = useMemo(() => wan2gpAudioPresetData?.presets || [], [wan2gpAudioPresetData?.presets])
  const defaultWan2gpPresetId = useMemo(() => {
    return resolveDefaultWan2gpPresetId(settingsData?.audio_wan2gp_preset, wan2gpPresets)
  }, [settingsData?.audio_wan2gp_preset, wan2gpPresets])

  const getWan2gpPreset = useCallback((presetId?: string): Wan2gpAudioPreset | undefined => {
    return resolveWan2gpPreset(wan2gpPresets, defaultWan2gpPresetId, presetId)
  }, [defaultWan2gpPresetId, wan2gpPresets])

  const getVoiceOptions = useCallback((provider: ReferenceVoiceProvider, presetId?: string): VoiceOption[] => {
    return resolveVoiceOptions({
      provider,
      edgeVoiceOptions,
      volcengineVoiceOptions,
      wan2gpPresets,
      defaultWan2gpPresetId,
      presetId,
    })
  }, [defaultWan2gpPresetId, edgeVoiceOptions, volcengineVoiceOptions, wan2gpPresets])

  const resolveVoiceLabel = useCallback((
    provider: ReferenceVoiceProvider,
    voiceName: string | undefined,
    presetId?: string
  ): string => {
    return resolveVoiceLabelFromOptions({
      provider,
      voiceName,
      edgeVoiceOptions,
      volcengineVoiceOptions,
      wan2gpPresets,
      defaultWan2gpPresetId,
      presetId,
    })
  }, [defaultWan2gpPresetId, edgeVoiceOptions, volcengineVoiceOptions, wan2gpPresets])

  const edgeDefaultSpeed = useMemo(() => {
    const parsed = rateToSpeed(String(settingsData?.edge_tts_rate || '+30%'))
    return clamp(Number.isFinite(parsed) ? parsed : 1.3, 0.5, 2.0)
  }, [settingsData?.edge_tts_rate])
  const wanDefaultSpeed = useMemo(() => {
    const speed = toFiniteNumber(settingsData?.audio_wan2gp_speed)
    return clamp(speed ?? 1.0, 0.5, 2.0)
  }, [settingsData?.audio_wan2gp_speed])
  const volcengineDefaultSpeed = useMemo(() => {
    const speed = toFiniteNumber(settingsData?.audio_volcengine_tts_speed_ratio)
    return clamp(speed ?? 1.0, 0.5, 2.0)
  }, [settingsData?.audio_volcengine_tts_speed_ratio])
  const klingDefaultSpeed = useMemo(() => {
    const speed = toFiniteNumber(settingsData?.audio_kling_voice_speed)
    return clamp(speed ?? 1.0, 0.5, 2.0)
  }, [settingsData?.audio_kling_voice_speed])
  const viduDefaultSpeed = useMemo(() => {
    const speed = toFiniteNumber(settingsData?.audio_vidu_speed)
    return clamp(speed ?? 1.0, 0.5, 2.0)
  }, [settingsData?.audio_vidu_speed])
  const xiaomiMimoDefaultSpeed = useMemo(() => {
    const speed = toFiniteNumber(settingsData?.audio_xiaomi_mimo_speed)
    return clamp(speed ?? 1.0, 0.5, 2.0)
  }, [settingsData?.audio_xiaomi_mimo_speed])

  const normalizeConfig = useCallback((raw: Partial<ReferenceVoiceConfig> | null | undefined): ReferenceVoiceConfig => {
    const providerCandidate = normalizeVoiceProvider(raw?.voice_audio_provider)
    const provider = availableAudioProviders.includes(providerCandidate) ? providerCandidate : defaultAudioProvider
    if (
      provider === 'edge_tts'
      || provider === 'volcengine_tts'
      || provider === 'kling_tts'
      || provider === 'vidu_tts'
      || provider === 'minimax_tts'
      || provider === 'xiaomi_mimo_tts'
    ) {
      const options = getVoiceOptions(provider)
      const requestedVoice = String(raw?.voice_name || '').trim()
      const fallbackVoice = (() => {
        if (provider === 'volcengine_tts') return volcengineDefaultVoice
        if (provider === 'kling_tts') return klingDefaultVoice
        if (provider === 'vidu_tts') return viduDefaultVoice
        if (provider === 'minimax_tts') return String(settingsData?.audio_minimax_voice_id || '')
        if (provider === 'xiaomi_mimo_tts') return xiaomiMimoDefaultVoice
        return edgeDefaultVoice
      })()
      const voiceName = options.some((item) => item.value === requestedVoice)
        ? requestedVoice
        : fallbackVoice
      const fallbackSpeed = (() => {
        if (provider === 'volcengine_tts') return volcengineDefaultSpeed
        if (provider === 'kling_tts') return klingDefaultSpeed
        if (provider === 'vidu_tts') return viduDefaultSpeed
        if (provider === 'minimax_tts') return Number(settingsData?.audio_minimax_speed || 1.0)
        if (provider === 'xiaomi_mimo_tts') return xiaomiMimoDefaultSpeed
        return edgeDefaultSpeed
      })()
      const speed = clamp(
        toFiniteNumber(raw?.voice_speed) ?? fallbackSpeed,
        0.5,
        2.0
      )
      return {
        voice_audio_provider: provider,
        voice_name: voiceName,
        voice_speed: speed,
      }
    }

    const preset = getWan2gpPreset(raw?.voice_wan2gp_preset)
    const presetId = preset?.id || defaultWan2gpPresetId
    const modeOptions = getVoiceOptions('wan2gp', presetId)
    const requestedVoice = String(raw?.voice_name || '').trim()
    const fallbackMode = String(preset?.default_model_mode || '').trim() || modeOptions[0]?.value || WAN2GP_DEFAULT_MODE
    const voiceName = modeOptions.some((item) => item.value === requestedVoice)
      ? requestedVoice
      : fallbackMode
    const speed = clamp(
      toFiniteNumber(raw?.voice_speed) ?? wanDefaultSpeed,
      0.5,
      2.0
    )
    const temperature = clamp(
      toFiniteNumber(raw?.voice_wan2gp_temperature)
      ?? toFiniteNumber(settingsData?.audio_wan2gp_temperature)
      ?? toFiniteNumber(preset?.default_temperature)
      ?? 0.9,
      0.1,
      1.5
    )
    const topK = clamp(
      toFiniteInt(raw?.voice_wan2gp_top_k)
      ?? toFiniteInt(settingsData?.audio_wan2gp_top_k)
      ?? toFiniteInt(preset?.default_top_k)
      ?? 50,
      1,
      100
    )
    const seed = toFiniteInt(raw?.voice_wan2gp_seed)
      ?? toFiniteInt(settingsData?.audio_wan2gp_seed)
      ?? -1
    const isBasePreset = presetId === 'qwen3_tts_base'
    const presetSupportsReferenceAudio = Boolean(preset?.supports_reference_audio)
    const settingsWan2gpPresetId = String(settingsData?.audio_wan2gp_preset || '').trim()
    const settingsWan2gpAltPrompt = String(settingsData?.audio_wan2gp_alt_prompt ?? '')
    const fallbackAltPrompt = isBasePreset
      ? ''
      : (
        settingsWan2gpPresetId === presetId && settingsWan2gpAltPrompt
          ? settingsWan2gpAltPrompt
          : String(preset?.default_alt_prompt ?? '')
      )
    const altPrompt = raw?.voice_wan2gp_alt_prompt != null
      ? String(raw.voice_wan2gp_alt_prompt)
      : fallbackAltPrompt
    const audioGuide = raw?.voice_wan2gp_audio_guide != null
      ? String(raw.voice_wan2gp_audio_guide)
      : (presetSupportsReferenceAudio ? String(settingsData?.audio_wan2gp_audio_guide ?? '') : '')

    return {
      voice_audio_provider: 'wan2gp',
      voice_name: voiceName,
      voice_speed: speed,
      voice_wan2gp_preset: presetId,
      voice_wan2gp_alt_prompt: altPrompt,
      voice_wan2gp_audio_guide: audioGuide,
      voice_wan2gp_temperature: temperature,
      voice_wan2gp_top_k: topK,
      voice_wan2gp_seed: seed,
    }
  }, [
    availableAudioProviders,
    defaultAudioProvider,
    defaultWan2gpPresetId,
    edgeDefaultSpeed,
    edgeDefaultVoice,
    getVoiceOptions,
    getWan2gpPreset,
    klingDefaultSpeed,
    klingDefaultVoice,
    xiaomiMimoDefaultSpeed,
    xiaomiMimoDefaultVoice,
    viduDefaultSpeed,
    viduDefaultVoice,
    volcengineDefaultSpeed,
    volcengineDefaultVoice,
    settingsData?.audio_wan2gp_alt_prompt,
    settingsData?.audio_wan2gp_audio_guide,
    settingsData?.audio_wan2gp_preset,
    settingsData?.audio_wan2gp_seed,
    settingsData?.audio_wan2gp_temperature,
    settingsData?.audio_wan2gp_top_k,
    settingsData?.audio_minimax_speed,
    settingsData?.audio_minimax_voice_id,
    wanDefaultSpeed,
  ])

  const toPayload = useCallback((
    canSpeak: boolean,
    raw: Partial<ReferenceVoiceConfig> | null | undefined
  ): Partial<ReferenceVoiceConfig> => {
    if (!canSpeak) {
      return {
        voice_audio_provider: undefined,
        voice_name: undefined,
        voice_speed: undefined,
        voice_wan2gp_preset: undefined,
        voice_wan2gp_alt_prompt: undefined,
        voice_wan2gp_audio_guide: undefined,
        voice_wan2gp_temperature: undefined,
        voice_wan2gp_top_k: undefined,
        voice_wan2gp_seed: undefined,
      }
    }
    const normalized = normalizeConfig(raw)
    if (
      normalized.voice_audio_provider === 'edge_tts'
      || normalized.voice_audio_provider === 'volcengine_tts'
      || normalized.voice_audio_provider === 'kling_tts'
      || normalized.voice_audio_provider === 'vidu_tts'
      || normalized.voice_audio_provider === 'minimax_tts'
      || normalized.voice_audio_provider === 'xiaomi_mimo_tts'
    ) {
      return {
        voice_audio_provider: normalized.voice_audio_provider,
        voice_name: normalized.voice_name,
        voice_speed: normalized.voice_speed,
        voice_wan2gp_preset: undefined,
        voice_wan2gp_alt_prompt: undefined,
        voice_wan2gp_audio_guide: undefined,
        voice_wan2gp_temperature: undefined,
        voice_wan2gp_top_k: undefined,
        voice_wan2gp_seed: undefined,
      }
    }
    return {
      voice_audio_provider: 'wan2gp',
      voice_name: normalized.voice_name,
      voice_speed: normalized.voice_speed,
      voice_wan2gp_preset: normalized.voice_wan2gp_preset,
      voice_wan2gp_alt_prompt: normalized.voice_wan2gp_alt_prompt,
      voice_wan2gp_audio_guide: normalized.voice_wan2gp_audio_guide,
      voice_wan2gp_temperature: normalized.voice_wan2gp_temperature,
      voice_wan2gp_top_k: normalized.voice_wan2gp_top_k,
      voice_wan2gp_seed: normalized.voice_wan2gp_seed,
    }
  }, [normalizeConfig])

  return useMemo(() => ({
    availableAudioProviders,
    defaultAudioProvider,
    edgeVoiceOptions,
    volcengineVoiceOptions,
    wan2gpPresets,
    normalizeConfig,
    toPayload,
    getVoiceOptions,
    getWan2gpPreset,
    resolveVoiceLabel,
  }), [
    availableAudioProviders,
    defaultAudioProvider,
    edgeVoiceOptions,
    volcengineVoiceOptions,
    getVoiceOptions,
    getWan2gpPreset,
    normalizeConfig,
    resolveVoiceLabel,
    toPayload,
    wan2gpPresets,
  ])
}
