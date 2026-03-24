'use client'

import { useEffect, useMemo } from 'react'

import { useActiveVoiceLibraryQuery } from '@/hooks/use-settings-queries'
import { getReferenceVoiceProviderLabel } from '@/lib/reference-voice'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import type { ReferenceVoiceConfig, ReferenceVoiceMeta } from '@/hooks/use-reference-voice-meta'

interface ReferenceVoiceFieldsProps {
  value: Partial<ReferenceVoiceConfig>
  onChange: (next: ReferenceVoiceConfig) => void
  meta: ReferenceVoiceMeta
  disabled?: boolean
}

const WAN2GP_PRESET_LABELS: Record<string, string> = {
  qwen3_tts_base: 'TTS Qwen3 Base (12Hz) 1.7B',
  qwen3_tts_customvoice: 'TTS Qwen3 Custom Voice (12Hz) 1.7B',
  qwen3_tts_voicedesign: 'TTS Qwen3 Voice Design (12Hz) 1.7B',
}

function resolveVoiceGuideValue(item: { audio_url?: string | null; audio_file_path?: string | null } | undefined): string {
  return String(item?.audio_url || item?.audio_file_path || '').trim()
}

function isVoiceGuideMatch(
  item: { audio_url?: string | null; audio_file_path?: string | null },
  guide: string | undefined
): boolean {
  const normalizedGuide = String(guide || '').trim()
  if (!normalizedGuide) return false
  const audioUrl = String(item.audio_url || '').trim()
  if (audioUrl && audioUrl === normalizedGuide) return true
  const audioPath = String(item.audio_file_path || '').trim()
  return Boolean(audioPath && audioPath === normalizedGuide)
}

function FieldRow({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="grid grid-cols-1 items-center gap-2 md:grid-cols-[140px_minmax(0,1fr)] md:gap-3">
      <Label className="text-sm">{label}</Label>
      <div className="min-w-0">{children}</div>
    </div>
  )
}

export function ReferenceVoiceFields(props: ReferenceVoiceFieldsProps) {
  const { value, onChange, meta, disabled } = props
  const normalized = meta.normalizeConfig(value)
  const selectedPreset = normalized.voice_audio_provider === 'wan2gp'
    ? meta.getWan2gpPreset(normalized.voice_wan2gp_preset)
    : undefined
  const { data: voiceLibraryData } = useActiveVoiceLibraryQuery()
  const activeVoiceLibraryItems = useMemo(
    () => (voiceLibraryData?.items || []) as Array<{
      id: string | number
      name?: string | null
      audio_url?: string | null
      audio_file_path?: string | null
      reference_text?: string | null
    }>,
    [voiceLibraryData?.items]
  )
  const baseVoiceOptions = useMemo(
    () => activeVoiceLibraryItems,
    [activeVoiceLibraryItems]
  )
  const selectedBaseVoice = useMemo(
    () => baseVoiceOptions.find(
      (item) => isVoiceGuideMatch(item, normalized.voice_wan2gp_audio_guide)
    ),
    [baseVoiceOptions, normalized.voice_wan2gp_audio_guide]
  )
  const hasBaseVoiceOptions = baseVoiceOptions.length > 0
  const baseVoiceSelectValue = selectedBaseVoice
    ? String(selectedBaseVoice.id)
    : (hasBaseVoiceOptions ? String(baseVoiceOptions[0].id) : '__empty__')

  const handleProviderChange = (nextProvider: string) => {
    const resolvedProvider = (
      nextProvider === 'wan2gp'
      || nextProvider === 'volcengine_tts'
      || nextProvider === 'kling_tts'
      || nextProvider === 'vidu_tts'
      || nextProvider === 'xiaomi_mimo_tts'
    )
      ? nextProvider
      : 'edge_tts'
    onChange(meta.normalizeConfig({
      voice_audio_provider: resolvedProvider,
    }))
  }

  useEffect(() => {
    if (!selectedPreset?.supports_reference_audio) return
    if (!hasBaseVoiceOptions) return
    if (selectedBaseVoice) return
    const firstVoice = baseVoiceOptions[0]
    onChange(meta.normalizeConfig({
      ...normalized,
      voice_wan2gp_audio_guide: resolveVoiceGuideValue(firstVoice),
      voice_wan2gp_alt_prompt: String(firstVoice?.reference_text || ''),
    }))
  }, [
    baseVoiceOptions,
    hasBaseVoiceOptions,
    meta,
    normalized,
    onChange,
    selectedBaseVoice,
    selectedPreset?.supports_reference_audio,
  ])

  const renderProviderRow = () => {
    if (normalized.voice_audio_provider === 'wan2gp') {
      return (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <div className="space-y-2">
            <Label className="text-sm">声音 Provider</Label>
            <Select
              value={normalized.voice_audio_provider}
              onValueChange={handleProviderChange}
              disabled={disabled}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {meta.availableAudioProviders.map((provider) => (
                  <SelectItem key={provider} value={provider}>
                    {getReferenceVoiceProviderLabel(provider)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label className="text-sm">模型</Label>
            <Select
              value={normalized.voice_wan2gp_preset || ''}
              onValueChange={(presetId) => {
                const nextPreset = meta.getWan2gpPreset(presetId)
                const defaultBaseVoice = baseVoiceOptions[0]
                const nextAltPrompt = presetId === 'qwen3_tts_base'
                  ? String(defaultBaseVoice?.reference_text || '')
                  : String(nextPreset?.default_alt_prompt || '')
                onChange(meta.normalizeConfig({
                  ...normalized,
                  voice_wan2gp_preset: presetId,
                  voice_wan2gp_alt_prompt: nextAltPrompt,
                  voice_wan2gp_audio_guide: nextPreset?.supports_reference_audio
                    ? resolveVoiceGuideValue(defaultBaseVoice)
                    : '',
                }))
              }}
              disabled={disabled}
            >
              <SelectTrigger>
                <SelectValue placeholder="选择模型" />
              </SelectTrigger>
              <SelectContent>
                {meta.wan2gpPresets.length > 0 ? (
                  meta.wan2gpPresets.map((preset) => (
                    <SelectItem key={preset.id} value={preset.id}>
                      {WAN2GP_PRESET_LABELS[preset.id] || preset.display_name}
                    </SelectItem>
                  ))
                ) : (
                  <SelectItem value={normalized.voice_wan2gp_preset || '__wan_default__'}>
                    {WAN2GP_PRESET_LABELS[normalized.voice_wan2gp_preset || ''] || normalized.voice_wan2gp_preset || 'qwen3_tts_base'}
                  </SelectItem>
                )}
              </SelectContent>
            </Select>
          </div>
        </div>
      )
    }

    return (
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="space-y-2">
          <Label className="text-sm">声音 Provider</Label>
          <Select
            value={normalized.voice_audio_provider}
            onValueChange={handleProviderChange}
            disabled={disabled}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {meta.availableAudioProviders.map((provider) => (
                <SelectItem key={provider} value={provider}>
                  {getReferenceVoiceProviderLabel(provider)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-2">
          <Label className="text-sm">语音</Label>
          <Select
            value={normalized.voice_name}
            onValueChange={(nextVoice) => {
              onChange(meta.normalizeConfig({
                ...normalized,
                voice_name: nextVoice,
              }))
            }}
            disabled={disabled}
          >
            <SelectTrigger>
              <SelectValue placeholder="选择语音" />
            </SelectTrigger>
            <SelectContent>
              {meta.getVoiceOptions(normalized.voice_audio_provider).map((voice) => (
                <SelectItem key={voice.value} value={voice.value}>
                  {voice.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3 rounded-md border p-3">
      {renderProviderRow()}

      {normalized.voice_audio_provider === 'wan2gp' && normalized.voice_wan2gp_preset === 'qwen3_tts_base' && (
        <FieldRow label="语音库预设">
          <Select
            value={baseVoiceSelectValue}
            onValueChange={(nextId) => {
              const selected = baseVoiceOptions.find((item) => String(item.id) === nextId)
              onChange(meta.normalizeConfig({
                ...normalized,
                voice_wan2gp_audio_guide: resolveVoiceGuideValue(selected),
                voice_wan2gp_alt_prompt: String(selected?.reference_text || ''),
              }))
            }}
            disabled={disabled || !hasBaseVoiceOptions}
          >
            <SelectTrigger>
              <SelectValue placeholder="请选择语音库预设" />
            </SelectTrigger>
            <SelectContent>
              {hasBaseVoiceOptions ? (
                baseVoiceOptions.map((item) => (
                  <SelectItem key={item.id} value={String(item.id)}>
                    {item.name}
                  </SelectItem>
                ))
              ) : (
                <SelectItem value="__empty__" disabled>暂无可用语音</SelectItem>
              )}
            </SelectContent>
          </Select>
        </FieldRow>
      )}

      {normalized.voice_audio_provider === 'wan2gp' && normalized.voice_wan2gp_preset === 'qwen3_tts_customvoice' && (
        <>
          <FieldRow label="音色">
            <Select
              value={normalized.voice_name}
              onValueChange={(nextMode) => {
                onChange(meta.normalizeConfig({
                  ...normalized,
                  voice_name: nextMode,
                }))
              }}
              disabled={disabled}
            >
              <SelectTrigger>
                <SelectValue placeholder="选择音色" />
              </SelectTrigger>
              <SelectContent>
                {meta.getVoiceOptions('wan2gp', normalized.voice_wan2gp_preset).map((mode) => (
                  <SelectItem key={mode.value} value={mode.value}>
                    {mode.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FieldRow>
          <FieldRow label="风格指令（可选）">
            <Input
              value={normalized.voice_wan2gp_alt_prompt || ''}
              onChange={(event) => {
                onChange(meta.normalizeConfig({
                  ...normalized,
                  voice_wan2gp_alt_prompt: event.target.value,
                }))
              }}
              disabled={disabled}
            />
          </FieldRow>
        </>
      )}

      {normalized.voice_audio_provider === 'wan2gp' && normalized.voice_wan2gp_preset === 'qwen3_tts_voicedesign' && (
        <FieldRow label="音色指令（可选）">
          <Input
            value={normalized.voice_wan2gp_alt_prompt || ''}
            onChange={(event) => {
              onChange(meta.normalizeConfig({
                ...normalized,
                voice_wan2gp_alt_prompt: event.target.value,
              }))
            }}
            disabled={disabled}
          />
        </FieldRow>
      )}

      <div className="space-y-2">
        <Label>语速 ({(normalized.voice_speed ?? 1.0).toFixed(1)}x)</Label>
        <Slider
          value={[normalized.voice_speed ?? 1.0]}
          onValueChange={(next) => {
            onChange(meta.normalizeConfig({
              ...normalized,
              voice_speed: next[0],
            }))
          }}
          min={0.5}
          max={2.0}
          step={0.1}
          className="mt-3"
          disabled={disabled}
        />
      </div>
    </div>
  )
}
