import { type ReactNode, useEffect, useState } from 'react'

import { AlertCircle } from 'lucide-react'
import Link from 'next/link'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import {
  DEFAULT_DUO_TARGET_DURATION,
  DEFAULT_SINGLE_TARGET_DURATION,
  IMAGE_STYLES,
  TEXT_PROMPT_COMPLEXITIES,
  TEXT_TARGET_LANGUAGES,
} from '@/lib/stage-panel-config'
import {
  getImageDefaults,
  getImageModelDefault,
  makeProviderModelValue,
  buildProviderModelLabel,
  formatImageSizeLabel,
  getWan2gpDefaults,
  isWan2gpT2iPreset,
  type ProviderModelOption,
} from '@/lib/stage-panel-helpers'
import {
  getWan2gpResolutionChoices,
  getWan2gpResolutionTiers,
  getWan2gpPromptLanguageHint,
} from '@/lib/wan2gp'
import { DUO_NARRATOR_STYLE_OPTIONS, SINGLE_NARRATOR_STYLE_OPTIONS } from '@/lib/narrator-style'
import { CONCURRENCY_OPTIONS } from '@/lib/stage-panel-helpers'
import { getScopedWan2gpInferenceSteps } from '@/lib/stage-input-builder'
import { getImageProviderDisplayName } from '@/lib/provider-config'
import type {
  ImageProviderConfig,
  Settings,
  Wan2gpImagePreset,
} from '@/types/settings'
import type { StageConfig } from '@/types/stage-panel'

interface StagePanelScriptTabProps {
  config: StageConfig
  settings: Settings | undefined
  isSettingsLoading: boolean
  effectiveScriptMode: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'
  updateConfig: (updates: Partial<StageConfig>) => void
  onNarratorStyleChange?: (nextStyle: string, prevStyle: string) => void
  renderLLMOptions: () => ReactNode
  getConfiguredImageProviders: () => string[]
  resolveEffectiveImageProvider: (providers: string[]) => string
  getImageProviderById: (providerId: string) => ImageProviderConfig | undefined
  getImageSizeOptionsByProviderModel: (providerId: string | undefined, model: string | undefined) => string[]
  getImageAspectRatioOptionsByProviderModel: (providerId: string | undefined, model: string | undefined) => string[]
  resolveWan2gpPreset: (presetId: string, presetType: 't2i' | 'i2i') => Wan2gpImagePreset | undefined
  handleWan2gpResolutionTierChange: (
    choices: ReturnType<typeof getWan2gpResolutionChoices>,
    tier: string,
    field: 'referenceImageResolution' | 'frameImageResolution'
  ) => void
  handleImageRuntimeModelChange: (value: string, scene: 'reference' | 'frame') => void
  wan2gpImagePresets: Wan2gpImagePreset[]
}

function renderNoConfigWarning(type: string) {
  return (
    <Alert variant="destructive" className="mb-4">
      <AlertCircle className="h-4 w-4" />
      <AlertDescription>
        请先在<Link href="/settings" className="underline font-medium">设置页面</Link>配置 {type} Provider
      </AlertDescription>
    </Alert>
  )
}

export function StagePanelScriptTab(props: StagePanelScriptTabProps) {
  const {
    config,
    settings,
    isSettingsLoading,
    effectiveScriptMode,
    updateConfig,
    onNarratorStyleChange,
    renderLLMOptions,
    getConfiguredImageProviders,
    resolveEffectiveImageProvider,
    getImageProviderById,
    getImageSizeOptionsByProviderModel,
    getImageAspectRatioOptionsByProviderModel,
    resolveWan2gpPreset,
    handleWan2gpResolutionTierChange,
    handleImageRuntimeModelChange,
    wan2gpImagePresets,
  } = props

  const targetDurationDefault = effectiveScriptMode === 'duo_podcast'
    ? DEFAULT_DUO_TARGET_DURATION
    : DEFAULT_SINGLE_TARGET_DURATION
  const resolvedTargetDuration = (
    typeof config.targetDuration === 'number'
    && Number.isFinite(config.targetDuration)
  )
    ? config.targetDuration
    : targetDurationDefault
  const [targetDurationInput, setTargetDurationInput] = useState(String(resolvedTargetDuration))

  useEffect(() => {
    setTargetDurationInput(String(resolvedTargetDuration))
  }, [resolvedTargetDuration])

  let targetDurationHint = ''
  if (targetDurationInput.trim() === '') {
    targetDurationHint = '请输入 10-600 秒'
  } else {
    const parsedTargetDuration = Number.parseInt(targetDurationInput, 10)
    if (!Number.isFinite(parsedTargetDuration)) {
      targetDurationHint = '请输入整数秒'
    } else if (parsedTargetDuration < 10) {
      targetDurationHint = '最少 10 秒'
    } else if (parsedTargetDuration > 600) {
      targetDurationHint = '最多 600 秒'
    }
  }

  const imageProviders = getConfiguredImageProviders()
  const effectiveImageProvider = resolveEffectiveImageProvider(imageProviders)
  const imageDefaults = getImageDefaults(effectiveImageProvider, settings, 'reference')
  const wan2gpDefaults = getWan2gpDefaults(settings)
  const wan2gpT2iPresets = wan2gpImagePresets.filter((preset) => isWan2gpT2iPreset(preset))
  const selectedWan2gpPreset = resolveWan2gpPreset(
    config.imageWan2gpPreset || wan2gpDefaults.preset,
    't2i'
  )

  const referenceRuntimeOptions: ProviderModelOption[] = [
    ...imageProviders.flatMap((provider) => {
      if (provider === 'wan2gp') {
        return wan2gpT2iPresets.map((preset) => ({
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
        const modelId = settings?.image_vidu_t2i_model || 'viduq2'
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
  ]

  const effectiveReferenceRuntimeValue = effectiveImageProvider === 'wan2gp'
    ? makeProviderModelValue('wan2gp', selectedWan2gpPreset?.id || wan2gpDefaults.preset)
    : makeProviderModelValue(effectiveImageProvider, config.imageModel || getImageModelDefault(effectiveImageProvider, settings))
  const selectedReferenceRuntimeOption = referenceRuntimeOptions.find((item) => item.value === effectiveReferenceRuntimeValue)
    || referenceRuntimeOptions[0]

  const referenceSizeOptions = getImageSizeOptionsByProviderModel(
    selectedReferenceRuntimeOption?.provider || effectiveImageProvider,
    selectedReferenceRuntimeOption?.model || config.imageModel || getImageModelDefault(effectiveImageProvider, settings)
  )
  const referenceAspectRatioOptions = getImageAspectRatioOptionsByProviderModel(
    selectedReferenceRuntimeOption?.provider || effectiveImageProvider,
    selectedReferenceRuntimeOption?.model || config.imageModel || getImageModelDefault(effectiveImageProvider, settings)
  )

  const effectiveReferenceImageSize = referenceSizeOptions.includes(config.referenceImageSize || '')
    ? (config.referenceImageSize || '')
    : (
        referenceSizeOptions.includes(imageDefaults.size)
          ? imageDefaults.size
          : (referenceSizeOptions[0] || imageDefaults.size)
      )
  const effectiveReferenceAspectRatio = referenceAspectRatioOptions.includes(config.referenceAspectRatio || '')
    ? (config.referenceAspectRatio || '')
    : (
        referenceAspectRatioOptions.includes(imageDefaults.aspectRatio)
          ? imageDefaults.aspectRatio
          : (
              referenceAspectRatioOptions.includes('1:1')
                ? '1:1'
                : (referenceAspectRatioOptions[0] || imageDefaults.aspectRatio)
            )
      )

  const wan2gpResolutionOptions = selectedWan2gpPreset?.supported_resolutions?.length
    ? selectedWan2gpPreset.supported_resolutions
    : [selectedWan2gpPreset?.default_resolution || wan2gpDefaults.referenceResolution]
  const wan2gpResolutionChoices = getWan2gpResolutionChoices(wan2gpResolutionOptions)
  const wan2gpResolutionTiers = getWan2gpResolutionTiers(wan2gpResolutionChoices)
  const effectiveWan2gpResolution = (
    config.referenceImageResolution && wan2gpResolutionOptions.includes(config.referenceImageResolution)
  )
    ? config.referenceImageResolution
    : (
        wan2gpResolutionOptions.find((item) => item === wan2gpDefaults.referenceResolution)
        || selectedWan2gpPreset?.default_resolution
        || wan2gpResolutionOptions[0]
        || wan2gpDefaults.referenceResolution
      )

  const effectiveWan2gpResolutionTier = wan2gpResolutionChoices.find(
    (choice) => choice.value === effectiveWan2gpResolution
  )?.tier || wan2gpResolutionTiers[0] || '720p'
  const tierResolutionChoices = wan2gpResolutionChoices.filter(
    (choice) => choice.tier === effectiveWan2gpResolutionTier
  )

  const effectiveWan2gpSteps = (
    getScopedWan2gpInferenceSteps(config, 't2i')
    || selectedWan2gpPreset?.inference_steps
    || wan2gpDefaults.inferenceSteps
    || 20
  )

  const styleOptions = effectiveScriptMode === 'duo_podcast'
    ? DUO_NARRATOR_STYLE_OPTIONS
    : SINGLE_NARRATOR_STYLE_OPTIONS
  const currentStyleValue = String(config.style || '').trim()
  const selectedStyleValue = styleOptions.some((item) => item.value === currentStyleValue)
    ? currentStyleValue
    : '__default__'

  return (
    <>
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <h4 className="font-medium text-sm text-foreground/90">文本生成</h4>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 [&>*]:min-w-0">
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-3">
              <Label>目标时长 (秒)</Label>
              {targetDurationHint ? (
                <span className="text-xs text-amber-600">{targetDurationHint}</span>
              ) : null}
            </div>
            <Input
              type="number"
              value={targetDurationInput}
              onChange={(e) => {
                const rawValue = e.target.value
                if (rawValue === '') {
                  setTargetDurationInput('')
                  return
                }
                const parsedValue = Number.parseInt(rawValue, 10)
                if (!Number.isFinite(parsedValue)) return
                setTargetDurationInput(rawValue)
                if (parsedValue >= 10 && parsedValue <= 600) {
                  updateConfig({ targetDuration: parsedValue })
                }
              }}
              onBlur={() => {
                const parsedValue = Number.parseInt(targetDurationInput, 10)
                if (!Number.isFinite(parsedValue)) {
                  setTargetDurationInput(String(resolvedTargetDuration))
                  return
                }
                const normalizedValue = Math.max(10, Math.min(600, parsedValue))
                setTargetDurationInput(String(normalizedValue))
                if (normalizedValue !== config.targetDuration) {
                  updateConfig({ targetDuration: normalizedValue })
                }
              }}
              min={10}
              max={600}
            />
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
          {(effectiveScriptMode === 'single' || effectiveScriptMode === 'duo_podcast') && (
            <div className="space-y-2">
              <Label>讲述者风格</Label>
              <Select
                value={selectedStyleValue}
                onValueChange={(v) => {
                  const prevStyle = String(config.style || '').trim()
                  const nextStyle = v === '__default__' ? '' : v
                  updateConfig({ style: nextStyle })
                  onNarratorStyleChange?.(nextStyle, prevStyle)
                }}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {styleOptions.map((item) => (
                    <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>
      </div>

      <div className="border-t pt-4 mt-4 space-y-3">
        <h4 className="font-medium text-sm text-foreground/90">参考图设置</h4>
        {isSettingsLoading ? (
          <div className="text-sm text-muted-foreground">加载配置中...</div>
        ) : imageProviders.length === 0 ? (
          renderNoConfigWarning('Image')
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 [&>*]:min-w-0">
              <div className="space-y-2">
                <Label>图像模型</Label>
                <Select
                  value={effectiveReferenceRuntimeValue}
                  onValueChange={(value) => handleImageRuntimeModelChange(value, 'reference')}
                >
                  <SelectTrigger><SelectValue placeholder="选择模型" /></SelectTrigger>
                  <SelectContent>
                    {referenceRuntimeOptions.map((item) => (
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

            {effectiveImageProvider === 'wan2gp' ? (
              <div className="grid grid-cols-2 gap-3 [&>*]:min-w-0">
                {selectedWan2gpPreset?.description && (
                  <p className="text-xs text-muted-foreground col-span-2">{selectedWan2gpPreset.description}</p>
                )}
                {selectedWan2gpPreset && (
                  <p className="text-xs text-amber-600 col-span-2">
                    {getWan2gpPromptLanguageHint(
                      '当前模型',
                      selectedWan2gpPreset.prompt_language_preference,
                      selectedWan2gpPreset.supports_chinese
                    )}
                  </p>
                )}
                <div className="space-y-2">
                  <Label>分辨率档位</Label>
                  <Select
                    value={effectiveWan2gpResolutionTier}
                    onValueChange={(tier) => handleWan2gpResolutionTierChange(wan2gpResolutionChoices, tier, 'referenceImageResolution')}
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
                    onValueChange={(v) => updateConfig({ referenceImageResolution: v })}
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
                <div className="space-y-2 col-span-2">
                  <Label>推理步数 ({effectiveWan2gpSteps})</Label>
                  <Slider
                    value={[effectiveWan2gpSteps]}
                    onValueChange={(v) => updateConfig({ imageWan2gpInferenceStepsT2i: v[0] })}
                    min={1}
                    max={100}
                    step={1}
                    className="mt-2"
                  />
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-3 [&>*]:min-w-0">
                <div className="space-y-2">
                  <Label>图片宽高比</Label>
                  <Select
                    value={effectiveReferenceAspectRatio}
                    onValueChange={(v) => updateConfig({ referenceAspectRatio: v })}
                  >
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {referenceAspectRatioOptions.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>图片分辨率</Label>
                  <Select
                    value={effectiveReferenceImageSize}
                    onValueChange={(v) => updateConfig({ referenceImageSize: v })}
                  >
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {referenceSizeOptions.map((s) => (
                        <SelectItem key={s} value={s}>{formatImageSizeLabel(s)}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
            )}

            {effectiveImageProvider !== 'wan2gp' && (
              <div className="space-y-2 w-full md:w-1/2">
                <Label>并发数</Label>
                <Select
                  value={String(config.maxConcurrency || 4)}
                  onValueChange={(v) => updateConfig({ maxConcurrency: parseInt(v, 10) })}
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
    </>
  )
}
