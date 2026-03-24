'use client'

import { useState, useCallback, useMemo } from 'react'
import { Check, Video } from 'lucide-react'
import { toast } from 'sonner'

import { api } from '@/lib/api-client'
import { normalizeModelIds, resolveEnabledModelIds } from '@/lib/provider-config'
import { SecretInput } from '@/components/settings/secret-input'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { ModelManagerDialog } from '@/components/settings/model-manager-dialog'
import { useModelManager } from '@/hooks/use-model-manager'
import type { Settings, SettingsUpdate, Wan2gpVideoPreset } from '@/types/settings'
import {
  getWan2gpPromptLanguageHint,
  getWan2gpResolutionChoices,
  getWan2gpResolutionTiers,
  pickDefaultResolutionForTier,
} from '@/lib/wan2gp'
import {
  SEEDANCE_ASPECT_RATIOS,
  SEEDANCE_MODEL_PRESETS,
  SEEDANCE_RESOLUTIONS,
  resolveSeedancePreset,
} from '@/lib/seedance'
import {
  createVideoProviderAdapters,
  isVideoProviderId,
  type VideoProviderId,
} from '@/app/settings/video-provider-adapters'

const DEFAULT_VIDEO_SEEDANCE_BASE_URL = 'https://kwjm.com'
const WAN2GP_FIT_CANVAS_OPTIONS = [
  { value: '0', label: 'Pixel Budget' },
  { value: '1', label: 'Max Width/Height' },
  { value: '2', label: 'Exact Output' },
]
const WAN2GP_FIT_CANVAS_DESCRIPTIONS: Record<0 | 1 | 2, string> = {
  0: '按“像素预算”缩放，保持宽高比，但不保证严格落在目标宽高框里（某一边可能超过），不裁剪',
  1: '按“最大宽高框”做等比缩放，目标是完整保留内容并装进框内（不裁剪），另外部分参考图路径会做白底居中填充',
  2: '先按目标比例中心裁剪，再缩放到精确输出分辨率（严格输出尺寸，但会裁掉一部分画面）',
}

export interface VideoProviderCardProps {
  settings: Settings | undefined
  formData: SettingsUpdate
  updateField: <K extends keyof SettingsUpdate>(key: K, value: SettingsUpdate[K]) => void
  showApiKeys: Record<string, boolean>
  onToggleApiKey: (key: string) => void
  wan2gpVideoPresetData?: { t2v_presets: Wan2gpVideoPreset[]; i2v_presets: Wan2gpVideoPreset[] }
}

export function VideoProviderCard({
  settings,
  formData,
  updateField,
  showApiKeys,
  onToggleApiKey,
  wan2gpVideoPresetData,
}: VideoProviderCardProps) {
  const videoModelManager = useModelManager()
  const [wan2gpVideoResolutionTierOverride, setWan2gpVideoResolutionTierOverride] = useState<string | null>(null)

  const wan2gpVideoT2vPresets: Wan2gpVideoPreset[] = useMemo(
    () => wan2gpVideoPresetData?.t2v_presets ?? [],
    [wan2gpVideoPresetData?.t2v_presets]
  )
  const wan2gpVideoI2vPresets: Wan2gpVideoPreset[] = useMemo(
    () => wan2gpVideoPresetData?.i2v_presets ?? [],
    [wan2gpVideoPresetData?.i2v_presets]
  )

  const wan2gpVideoCatalogIds = useMemo(
    () => normalizeModelIds([
      ...wan2gpVideoT2vPresets.map((preset) => preset.id),
      ...wan2gpVideoI2vPresets.map((preset) => preset.id),
    ]),
    [wan2gpVideoI2vPresets, wan2gpVideoT2vPresets]
  )
  const rawVideoWan2gpEnabledModels = formData.video_wan2gp_enabled_models ?? settings?.video_wan2gp_enabled_models
  const effectiveVideoWan2gpEnabledModels = useMemo(
    () => resolveEnabledModelIds(rawVideoWan2gpEnabledModels, wan2gpVideoCatalogIds),
    [rawVideoWan2gpEnabledModels, wan2gpVideoCatalogIds]
  )
  const videoWan2gpEnabledSet = useMemo(
    () => new Set(effectiveVideoWan2gpEnabledModels),
    [effectiveVideoWan2gpEnabledModels]
  )
  const visibleWan2gpVideoT2vPresets = wan2gpVideoT2vPresets.filter((preset) => videoWan2gpEnabledSet.has(preset.id))
  const visibleWan2gpVideoI2vPresets = wan2gpVideoI2vPresets.filter((preset) => videoWan2gpEnabledSet.has(preset.id))
  const configuredWan2gpVideoT2vPreset = formData.video_wan2gp_t2v_preset ?? settings?.video_wan2gp_t2v_preset ?? ''
  const configuredWan2gpVideoI2vPreset = formData.video_wan2gp_i2v_preset ?? settings?.video_wan2gp_i2v_preset ?? ''
  const selectedWan2gpVideoT2vPreset = visibleWan2gpVideoT2vPresets.some((preset) => preset.id === configuredWan2gpVideoT2vPreset)
    ? configuredWan2gpVideoT2vPreset
    : (visibleWan2gpVideoT2vPresets[0]?.id ?? '')
  const selectedWan2gpVideoI2vPreset = visibleWan2gpVideoI2vPresets.some((preset) => preset.id === configuredWan2gpVideoI2vPreset)
    ? configuredWan2gpVideoI2vPreset
    : (visibleWan2gpVideoI2vPresets[0]?.id ?? '')
  const selectedWan2gpVideoT2vPresetConfig = wan2gpVideoT2vPresets.find((preset) => preset.id === selectedWan2gpVideoT2vPreset)
  const selectedWan2gpVideoI2vPresetConfig = wan2gpVideoI2vPresets.find((preset) => preset.id === selectedWan2gpVideoI2vPreset)
  const wan2gpVideoResolutionOptions = selectedWan2gpVideoT2vPresetConfig?.supported_resolutions?.length
    ? selectedWan2gpVideoT2vPresetConfig.supported_resolutions
    : [formData.video_wan2gp_resolution ?? settings?.video_wan2gp_resolution ?? '720x1280']
  const wan2gpVideoResolutionChoices = getWan2gpResolutionChoices(wan2gpVideoResolutionOptions)
  const wan2gpVideoResolutionTiers = getWan2gpResolutionTiers(wan2gpVideoResolutionChoices)
  const currentWan2gpVideoResolution = formData.video_wan2gp_resolution ?? settings?.video_wan2gp_resolution
  const selectedWan2gpVideoResolution = (
    currentWan2gpVideoResolution && wan2gpVideoResolutionOptions.includes(currentWan2gpVideoResolution)
  )
    ? currentWan2gpVideoResolution
    : (selectedWan2gpVideoT2vPresetConfig?.default_resolution || wan2gpVideoResolutionOptions[0] || '720x1280')
  const derivedWan2gpVideoResolutionTier = wan2gpVideoResolutionChoices.find(
    (choice) => choice.value === selectedWan2gpVideoResolution
  )?.tier || wan2gpVideoResolutionTiers[0] || '720p'
  const selectedWan2gpVideoResolutionTier = (
    wan2gpVideoResolutionTierOverride
    && wan2gpVideoResolutionTiers.includes(wan2gpVideoResolutionTierOverride)
  )
    ? wan2gpVideoResolutionTierOverride
    : derivedWan2gpVideoResolutionTier
  const selectedVideoTierChoices = wan2gpVideoResolutionChoices.filter(
    (choice) => choice.tier === selectedWan2gpVideoResolutionTier
  )
  const resolvedVideoTierChoices = selectedVideoTierChoices.length > 0
    ? selectedVideoTierChoices
    : wan2gpVideoResolutionChoices
  const selectedWan2gpVideoResolutionValue = resolvedVideoTierChoices.some(
    (choice) => choice.value === selectedWan2gpVideoResolution
  )
    ? selectedWan2gpVideoResolution
    : (resolvedVideoTierChoices[0]?.value || selectedWan2gpVideoResolution)
  const rawWan2gpFitCanvas = formData.wan2gp_fit_canvas ?? settings?.wan2gp_fit_canvas
  const selectedWan2gpFitCanvas = rawWan2gpFitCanvas === 1 || rawWan2gpFitCanvas === 2
    ? rawWan2gpFitCanvas
    : 0

  const seedanceVideoCatalogIds = useMemo(
    () => normalizeModelIds([
      ...SEEDANCE_MODEL_PRESETS.map((item) => item.id),
      formData.video_seedance_model ?? settings?.video_seedance_model ?? '',
    ]),
    [formData.video_seedance_model, settings?.video_seedance_model]
  )
  const rawVideoSeedanceEnabledModels = formData.video_seedance_enabled_models ?? settings?.video_seedance_enabled_models
  const effectiveVideoSeedanceEnabledModels = useMemo(
    () => resolveEnabledModelIds(rawVideoSeedanceEnabledModels, seedanceVideoCatalogIds),
    [rawVideoSeedanceEnabledModels, seedanceVideoCatalogIds]
  )
  const configuredSeedanceModel = formData.video_seedance_model ?? settings?.video_seedance_model ?? ''
  const selectedSeedanceModel = effectiveVideoSeedanceEnabledModels.includes(configuredSeedanceModel)
    ? configuredSeedanceModel
    : (effectiveVideoSeedanceEnabledModels[0] ?? '')
  const selectedSeedancePreset = resolveSeedancePreset(selectedSeedanceModel)
  const selectedSeedanceAspectRatio = formData.video_seedance_aspect_ratio
    ?? settings?.video_seedance_aspect_ratio
    ?? SEEDANCE_ASPECT_RATIOS[0]
    ?? 'adaptive'
  const selectedSeedanceResolution = formData.video_seedance_resolution
    ?? settings?.video_seedance_resolution
    ?? SEEDANCE_RESOLUTIONS[SEEDANCE_RESOLUTIONS.length - 1]
    ?? '720p'

  const seedanceModelNameMap = useMemo(
    () => new Map(SEEDANCE_MODEL_PRESETS.map((item) => [item.id, item.label] as const)),
    []
  )
  const seedanceModelTagMap = useMemo(
    () =>
      new Map(
        SEEDANCE_MODEL_PRESETS.map((item) => {
          const tags: string[] = []
          if (item.supportsT2v) tags.push('t2v')
          if (item.supportsI2v) tags.push('i2v')
          return [item.id, tags] as const
        })
      ),
    []
  )
  const wan2gpVideoPresetNameMap = useMemo(
    () =>
      new Map([
        ...wan2gpVideoT2vPresets.map((item) => [item.id, item.display_name] as const),
        ...wan2gpVideoI2vPresets.map((item) => [item.id, item.display_name] as const),
      ]),
    [wan2gpVideoI2vPresets, wan2gpVideoT2vPresets]
  )

  const videoProviderAdapters = useMemo(() => createVideoProviderAdapters({
    normalizeModelIds,
    resolveEnabledModelIds,
    updateField,
    formData,
    settings,
    rawVideoSeedanceEnabledModels,
    rawVideoWan2gpEnabledModels,
    seedanceModelIds: SEEDANCE_MODEL_PRESETS.map((item) => item.id),
    seedanceModelNameMap,
    seedanceModelTagMap,
    wan2gpVideoT2vPresets,
    wan2gpVideoI2vPresets,
    wan2gpVideoPresetNameMap,
    currentVideoSeedanceModel: formData.video_seedance_model ?? settings?.video_seedance_model ?? '',
    currentVideoWan2gpT2vPreset: formData.video_wan2gp_t2v_preset ?? settings?.video_wan2gp_t2v_preset ?? '',
    currentVideoWan2gpI2vPreset: formData.video_wan2gp_i2v_preset ?? settings?.video_wan2gp_i2v_preset ?? '',
    setWan2gpVideoResolutionTierOverride,
    seedanceDefaultBaseUrl: DEFAULT_VIDEO_SEEDANCE_BASE_URL,
  }), [
    formData,
    rawVideoSeedanceEnabledModels,
    rawVideoWan2gpEnabledModels,
    seedanceModelNameMap,
    seedanceModelTagMap,
    settings,
    updateField,
    wan2gpVideoI2vPresets,
    wan2gpVideoPresetNameMap,
    wan2gpVideoT2vPresets,
  ])

  const videoModelManagerCatalogIds = videoModelManager.catalogIds
  const videoModelManagerSelectedIds = useMemo(() => {
    const providerId = videoModelManager.providerId
    if (!isVideoProviderId(providerId)) return []
    return videoProviderAdapters[providerId].getSelectedIds(videoModelManagerCatalogIds)
  }, [
    videoModelManagerCatalogIds,
    videoModelManager.providerId,
    videoProviderAdapters,
  ])
  const videoModelManagerAllSelected = videoModelManagerCatalogIds.length > 0
    && videoModelManagerCatalogIds.every((id) => videoModelManagerSelectedIds.includes(id))

  const handleOpenVideoModelManager = useCallback((providerId: VideoProviderId) => {
    const modelIds = videoProviderAdapters[providerId].getCatalogIds()
    videoModelManager.openManager(providerId, modelIds.map((id) => ({ id })))
  }, [videoModelManager, videoProviderAdapters])

  const handleVideoModelEnabledChange = useCallback((modelId: string, checked: boolean) => {
    const providerId = videoModelManager.providerId
    if (!isVideoProviderId(providerId)) return
    const adapter = videoProviderAdapters[providerId]
    const enabled = new Set(adapter.getSelectedIds(videoModelManagerCatalogIds))
    if (checked) enabled.add(modelId)
    else enabled.delete(modelId)
    adapter.setEnabledIds(normalizeModelIds(Array.from(enabled)))
  }, [
    videoModelManager.providerId,
    videoModelManagerCatalogIds,
    videoProviderAdapters,
  ])

  const handleToggleAllVideoModels = useCallback(() => {
    const providerId = videoModelManager.providerId
    if (!isVideoProviderId(providerId)) return
    const nextEnabled = videoModelManagerAllSelected ? [] : videoModelManagerCatalogIds
    videoProviderAdapters[providerId].setEnabledIds(nextEnabled)
  }, [
    videoModelManager.providerId,
    videoModelManagerAllSelected,
    videoModelManagerCatalogIds,
    videoProviderAdapters,
  ])

  const handleTestVideoModel = useCallback(async (modelId: string) => {
    const providerId = videoModelManager.providerId
    if (!isVideoProviderId(providerId)) return
    videoModelManager.setModelTesting(modelId)
    try {
      const payload = videoProviderAdapters[providerId].buildTestPayload(modelId)
      const result = await api.settings.testVideoModel(payload)
      if (result.success) {
        const latencyLabel = typeof result.latency_ms === 'number' ? `（${result.latency_ms}ms）` : ''
        videoModelManager.setModelResult(modelId, {
          success: true,
          message: result.message || 'OK',
        })
        toast.success(`模型 ${modelId} 检测通过${latencyLabel}`)
        return
      }
      const errorMessage = result.error || result.message || '未知错误'
      videoModelManager.setModelResult(modelId, {
        success: false,
        message: errorMessage,
      })
      toast.error(`模型 ${modelId} 检测失败: ${errorMessage}`)
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : '检测失败'
      videoModelManager.setModelResult(modelId, {
        success: false,
        message: errorMessage,
      })
      toast.error(`模型 ${modelId} 检测失败: ${errorMessage}`)
    }
  }, [
    videoModelManager,
    videoProviderAdapters,
  ])

  const handleWan2gpVideoT2vPresetChange = (presetId: string) => {
    setWan2gpVideoResolutionTierOverride(null)
    updateField('video_wan2gp_t2v_preset', presetId)
    const preset = wan2gpVideoT2vPresets.find((item) => item.id === presetId)
    if (!preset) return

    const options = preset.supported_resolutions?.length
      ? preset.supported_resolutions
      : [preset.default_resolution]
    const currentResolution = formData.video_wan2gp_resolution ?? settings?.video_wan2gp_resolution
    if (!currentResolution || !options.includes(currentResolution)) {
      updateField('video_wan2gp_resolution', preset.default_resolution || options[0])
    }
  }

  const handleWan2gpVideoResolutionTierChange = (tier: string) => {
    setWan2gpVideoResolutionTierOverride(tier)
    const nextResolution = pickDefaultResolutionForTier(wan2gpVideoResolutionChoices, tier)
    if (nextResolution) {
      updateField('video_wan2gp_resolution', nextResolution)
      return
    }
    const fallback = wan2gpVideoResolutionChoices.find((choice) => choice.tier === tier)?.value
    if (fallback) {
      updateField('video_wan2gp_resolution', fallback)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Video className="h-5 w-5" />
          视频生成
        </CardTitle>
        <CardDescription>主引擎使用 Seedance 2.0，API 不可用时可回退到本地 Wan2GP。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="flex flex-col gap-4">
          <div className="border rounded-lg p-4 space-y-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2 flex-wrap">
                <div className="font-medium">Seedance 2.0</div>
                <Badge variant="outline">主引擎</Badge>
                {(formData.video_seedance_api_key ?? settings?.video_seedance_api_key ?? '').trim() ? (
                  <Badge variant="outline" className="text-green-600">
                    <Check className="h-3 w-3 mr-1" />
                    已配置
                  </Badge>
                ) : (
                  <Badge variant="secondary">需配置 API Key</Badge>
                )}
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="shrink-0"
                onClick={() => handleOpenVideoModelManager('volcengine_seedance')}
              >
                管理模型列表
              </Button>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="video_seedance_api_key">API Key</Label>
                <SecretInput
                  id="video_seedance_api_key"
                  visible={Boolean(showApiKeys.video_seedance_api_key)}
                  onToggleVisibility={() => onToggleApiKey('video_seedance_api_key')}
                  placeholder="输入 kwjm.com Seedance API Key"
                  value={formData.video_seedance_api_key ?? settings?.video_seedance_api_key ?? ''}
                  onChange={(e) => updateField('video_seedance_api_key', e.target.value)}
                  buttonClassName="h-7 w-7"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="video_seedance_base_url">Base URL</Label>
                <Input
                  id="video_seedance_base_url"
                  placeholder={DEFAULT_VIDEO_SEEDANCE_BASE_URL}
                  value={formData.video_seedance_base_url ?? settings?.video_seedance_base_url ?? DEFAULT_VIDEO_SEEDANCE_BASE_URL}
                  onChange={(e) => updateField('video_seedance_base_url', e.target.value)}
                />
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label htmlFor="video_seedance_model">Model</Label>
                <Select
                  value={selectedSeedanceModel || undefined}
                  onValueChange={(value) => updateField('video_seedance_model', value)}
                >
                  <SelectTrigger id="video_seedance_model">
                    <SelectValue placeholder="选择模型" />
                  </SelectTrigger>
                  <SelectContent>
                    {effectiveVideoSeedanceEnabledModels.length > 0 ? (
                      effectiveVideoSeedanceEnabledModels.map((modelId) => (
                        <SelectItem key={modelId} value={modelId}>
                          {seedanceModelNameMap.get(modelId) || modelId}
                        </SelectItem>
                      ))
                    ) : (
                      <div className="px-2 py-1.5 text-sm text-muted-foreground">
                        请在「管理模型列表」中勾选模型
                      </div>
                    )}
                  </SelectContent>
                </Select>
                {selectedSeedancePreset?.description && (
                  <p className="text-xs text-muted-foreground">{selectedSeedancePreset.description}</p>
                )}
              </div>
              <div className="space-y-2">
                <Label htmlFor="video_seedance_aspect_ratio">视频宽高比</Label>
                <Select
                  value={selectedSeedanceAspectRatio}
                  onValueChange={(value) => updateField('video_seedance_aspect_ratio', value)}
                >
                  <SelectTrigger id="video_seedance_aspect_ratio">
                    <SelectValue placeholder="选择宽高比" />
                  </SelectTrigger>
                  <SelectContent>
                    {SEEDANCE_ASPECT_RATIOS.map((ratio) => (
                      <SelectItem key={ratio} value={ratio}>
                        {ratio}
                      </SelectItem>
                    ))}
                    {!SEEDANCE_ASPECT_RATIOS.includes(selectedSeedanceAspectRatio) && (
                      <SelectItem value={selectedSeedanceAspectRatio}>
                        {selectedSeedanceAspectRatio}
                      </SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="video_seedance_resolution">视频分辨率</Label>
                <Select
                  value={selectedSeedanceResolution}
                  onValueChange={(value) => updateField('video_seedance_resolution', value)}
                >
                  <SelectTrigger id="video_seedance_resolution">
                    <SelectValue placeholder="选择分辨率" />
                  </SelectTrigger>
                  <SelectContent>
                    {SEEDANCE_RESOLUTIONS.map((item) => (
                      <SelectItem key={item} value={item}>
                        {item}
                      </SelectItem>
                    ))}
                    {!SEEDANCE_RESOLUTIONS.includes(selectedSeedanceResolution) && (
                      <SelectItem value={selectedSeedanceResolution}>
                        {selectedSeedanceResolution}
                      </SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>

          <div className="border rounded-lg p-4 space-y-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2 flex-wrap">
                <div className="font-medium">Wan2GP</div>
                <Badge variant="outline">本地兜底</Badge>
                {settings?.wan2gp_available ? (
                  <Badge variant="outline" className="text-green-600">
                    <Check className="h-3 w-3 mr-1" />
                    已就绪
                  </Badge>
                ) : (
                  <Badge variant="secondary">需配置路径</Badge>
                )}
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="shrink-0"
                onClick={() => handleOpenVideoModelManager('wan2gp')}
              >
                管理模型列表
              </Button>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="video_wan2gp_t2v_preset">文生视频模型 (t2v)</Label>
                <Select
                  value={selectedWan2gpVideoT2vPreset || undefined}
                  onValueChange={handleWan2gpVideoT2vPresetChange}
                >
                  <SelectTrigger id="video_wan2gp_t2v_preset">
                    <SelectValue placeholder="选择模型" />
                  </SelectTrigger>
                  <SelectContent>
                    {visibleWan2gpVideoT2vPresets.length > 0 ? (
                      visibleWan2gpVideoT2vPresets.map((preset) => (
                        <SelectItem key={preset.id} value={preset.id}>
                          {preset.display_name}
                        </SelectItem>
                      ))
                    ) : (
                      <div className="px-2 py-1.5 text-sm text-muted-foreground">
                        请在「管理模型列表」中勾选模型
                      </div>
                    )}
                  </SelectContent>
                </Select>
                {selectedWan2gpVideoT2vPresetConfig?.description && (
                  <p className="text-xs text-muted-foreground">{selectedWan2gpVideoT2vPresetConfig.description}</p>
                )}
                {selectedWan2gpVideoT2vPresetConfig && (
                  <p className="text-xs text-amber-600">
                    {getWan2gpPromptLanguageHint(
                      '该模型',
                      selectedWan2gpVideoT2vPresetConfig.prompt_language_preference,
                      selectedWan2gpVideoT2vPresetConfig.supports_chinese
                    )}
                  </p>
                )}
              </div>
              <div className="space-y-2">
                <Label htmlFor="video_wan2gp_i2v_preset">图生视频模型 (i2v)</Label>
                <Select
                  value={selectedWan2gpVideoI2vPreset || undefined}
                  onValueChange={(value) => updateField('video_wan2gp_i2v_preset', value)}
                >
                  <SelectTrigger id="video_wan2gp_i2v_preset">
                    <SelectValue placeholder="选择模型" />
                  </SelectTrigger>
                  <SelectContent>
                    {visibleWan2gpVideoI2vPresets.length > 0 ? (
                      visibleWan2gpVideoI2vPresets.map((preset) => (
                        <SelectItem key={preset.id} value={preset.id}>
                          {preset.display_name}
                        </SelectItem>
                      ))
                    ) : (
                      <div className="px-2 py-1.5 text-sm text-muted-foreground">
                        请在「管理模型列表」中勾选模型
                      </div>
                    )}
                  </SelectContent>
                </Select>
                {selectedWan2gpVideoI2vPresetConfig?.description && (
                  <p className="text-xs text-muted-foreground">{selectedWan2gpVideoI2vPresetConfig.description}</p>
                )}
                {selectedWan2gpVideoI2vPresetConfig && (
                  <p className="text-xs text-amber-600">
                    {getWan2gpPromptLanguageHint(
                      '该模型',
                      selectedWan2gpVideoI2vPresetConfig.prompt_language_preference,
                      selectedWan2gpVideoI2vPresetConfig.supports_chinese
                    )}
                  </p>
                )}
              </div>
              <div className="space-y-2">
                <Label htmlFor="video_wan2gp_resolution_tier">视频分辨率档位</Label>
                <Select
                  value={selectedWan2gpVideoResolutionTier}
                  onValueChange={handleWan2gpVideoResolutionTierChange}
                >
                  <SelectTrigger id="video_wan2gp_resolution_tier">
                    <SelectValue placeholder="选择档位" />
                  </SelectTrigger>
                  <SelectContent>
                    {wan2gpVideoResolutionTiers.map((tier) => (
                      <SelectItem key={tier} value={tier}>
                        {tier}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="video_wan2gp_resolution">视频宽高比</Label>
                <Select
                  value={selectedWan2gpVideoResolutionValue}
                  onValueChange={(value) => {
                    updateField('video_wan2gp_resolution', value)
                    const tier = wan2gpVideoResolutionChoices.find((choice) => choice.value === value)?.tier
                    if (tier) {
                      setWan2gpVideoResolutionTierOverride(tier)
                    }
                  }}
                >
                  <SelectTrigger id="video_wan2gp_resolution">
                    <SelectValue placeholder="选择宽高比" />
                  </SelectTrigger>
                  <SelectContent>
                    {resolvedVideoTierChoices.map((item) => (
                      <SelectItem key={item.value} value={item.value}>
                        {item.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label htmlFor="wan2gp_fit_canvas">输入图/视频预处理模式 (fit_canvas)</Label>
                <p className="text-xs text-muted-foreground">
                  Wan2GP 全局参数，影响本地视频生成时的输入缩放/裁剪策略。
                </p>
                <Select
                  value={String(selectedWan2gpFitCanvas)}
                  onValueChange={(value) => {
                    const parsed = Number.parseInt(value, 10)
                    const fitCanvas = parsed === 1 || parsed === 2 ? parsed : 0
                    updateField('wan2gp_fit_canvas', fitCanvas)
                  }}
                >
                  <SelectTrigger id="wan2gp_fit_canvas">
                    <SelectValue placeholder="选择预处理模式" />
                  </SelectTrigger>
                  <SelectContent>
                    {WAN2GP_FIT_CANVAS_OPTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <div className="rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground">
                  <p>{WAN2GP_FIT_CANVAS_DESCRIPTIONS[selectedWan2gpFitCanvas]}</p>
                </div>
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label htmlFor="video_wan2gp_negative_prompt">Negative Prompt（可选）</Label>
                <Input
                  id="video_wan2gp_negative_prompt"
                  value={formData.video_wan2gp_negative_prompt ?? settings?.video_wan2gp_negative_prompt ?? ''}
                  onChange={(e) => updateField('video_wan2gp_negative_prompt', e.target.value)}
                />
              </div>
              {!settings?.wan2gp_available && (
                <p className="text-xs text-muted-foreground md:col-span-2">
                  当前 Wan2GP 未就绪，请先在本地环境配置中填写路径并完成校验。
                </p>
              )}
            </div>
          </div>
        </div>

        <ModelManagerDialog
          open={videoModelManager.isOpen}
          onOpenChange={videoModelManager.onOpenChange}
          selectedCount={videoModelManagerSelectedIds.length}
          totalCount={videoModelManagerCatalogIds.length}
          rows={videoModelManagerCatalogIds.map((modelId) => {
            const providerId = videoModelManager.providerId
            const adapter = isVideoProviderId(providerId) ? videoProviderAdapters[providerId] : null
            return {
              id: modelId,
              label: adapter?.getModelLabel(modelId) || modelId,
              tags: adapter?.getModelTags(modelId) ?? [],
              checked: videoModelManagerSelectedIds.includes(modelId),
              connectivity: videoModelManager.getModelConnectivity(modelId),
              canTest: Boolean(adapter),
              onTest: () => {
                if (!adapter) return
                void handleTestVideoModel(modelId)
              },
              onCheckedChange: (checked) => handleVideoModelEnabledChange(modelId, checked),
            }
          })}
          allSelected={videoModelManagerAllSelected}
          onToggleAll={handleToggleAllVideoModels}
          description="只有勾选模型会出现在下拉列表中，可逐个检测连通性。"
          emptyText="暂无模型。"
        />
      </CardContent>
    </Card>
  )
}
