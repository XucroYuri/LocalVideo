'use client'

import { useState, useCallback, useEffect, useMemo } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Check, Image as ImageIcon, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import { api } from '@/lib/api-client'
import { useConfirmDialog } from '@/components/common/confirm-dialog-provider'
import { SecretInput } from '@/components/settings/secret-input'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { ModelManagerDialog } from '@/components/settings/model-manager-dialog'
import { useModelManager } from '@/hooks/use-model-manager'
import {
  getImageProviderDisplayName,
  normalizeModelIds,
  normalizeProviderId,
  resolveEnabledModelIds,
} from '@/lib/provider-config'
import { queryKeys } from '@/lib/query-keys'
import { hasKlingCredentials } from '@/lib/kling'
import type {
  ImageProviderConfig,
  ImageProviderType,
  Settings,
  SettingsUpdate,
  Wan2gpImagePreset,
} from '@/types/settings'
import {
  getWan2gpResolutionChoices,
  getWan2gpResolutionTiers,
  getWan2gpPromptLanguageHint,
  pickDefaultResolutionForTier,
} from '@/lib/wan2gp'
import { createImageProviderAdapters } from '@/app/settings/image-provider-adapters'
import { isWan2gpI2iPreset, isWan2gpT2iPreset } from '@/lib/stage-panel-helpers'

interface ModelInfo {
  id: string
}

const IMAGE_ASPECT_RATIO_OPTIONS = ['1:1', '2:3', '3:2', '3:4', '4:3', '9:16', '16:9', '21:9']
const IMAGE_SIZE_OPTIONS = ['1K', '2K', '4K']
const GEMINI_FLASH_IMAGE_MODEL = 'gemini-3.1-flash-image-preview'
const GEMINI_PRO_IMAGE_MODEL = 'gemini-3-pro-image-preview'
const GEMINI_ASPECT_RATIO_OPTIONS = ['1:1', '2:3', '3:2', '3:4', '4:3', '4:5', '5:4', '9:16', '16:9', '21:9']
const GEMINI_FLASH_ASPECT_RATIO_OPTIONS = [
  '1:1', '1:4', '1:8', '2:3', '3:2', '3:4', '4:1', '4:3', '4:5', '5:4', '8:1', '9:16', '16:9', '21:9',
]
const GEMINI_IMAGE_SIZE_OPTIONS = ['1K', '2K', '4K']
const GEMINI_FLASH_IMAGE_SIZE_OPTIONS = ['512px', '1K', '2K', '4K']
const VOLCENGINE_SEEDREAM_IMAGE_SIZE_OPTIONS: Record<string, string[]> = {
  'doubao-seedream-5.0': ['2K', '4K'],
  'doubao-seedream-4.5': ['2K', '4K'],
  'doubao-seedream-4.0': ['1K', '2K', '4K'],
}
const CUSTOM_IMAGE_PROVIDER_TYPES: Array<{ value: ImageProviderType; label: string; endpoint: string }> = [
  { value: 'openai_chat', label: 'OpenAI', endpoint: '/chat/completions' },
]
const DEFAULT_IMAGE_MODEL = GEMINI_PRO_IMAGE_MODEL
const DEFAULT_CUSTOM_IMAGE_MODELS = [GEMINI_FLASH_IMAGE_MODEL, GEMINI_PRO_IMAGE_MODEL]
const WAN2GP_DREAMOMNI2_PRESET_ID = 'flux_dev_kontext_dreamomni2'
const DEFAULT_KLING_BASE_URL = 'https://api-beijing.klingai.com'
const KLING_MODEL_OPTIONS = ['kling-v3', 'kling-v3-omni']
const KLING_IMAGE_ASPECT_RATIO_OPTIONS = ['16:9', '9:16', '1:1', '4:3', '3:4', '3:2', '2:3', '21:9']
const KLING_IMAGE_SIZE_OPTIONS_BY_MODEL: Record<string, string[]> = {
  'kling-v3': ['1K', '2K', '4K'],
  'kling-v3-omni': ['1K', '2K'],
}
const DEFAULT_VIDU_BASE_URL = 'https://api.vidu.cn'
const VIDU_IMAGE_MODEL_OPTIONS = ['viduq2']
const VIDU_IMAGE_ASPECT_RATIO_OPTIONS = ['16:9', '9:16', '1:1', '3:4', '4:3', '21:9', '2:3', '3:2']
const VIDU_IMAGE_SIZE_OPTIONS = ['1080p', '2K', '4K']
const DEFAULT_MINIMAX_BASE_URL = 'https://api.minimaxi.com/v1'
const MINIMAX_IMAGE_MODEL_OPTIONS = ['image-01', 'image-01-live']
const MINIMAX_IMAGE_ASPECT_RATIO_OPTIONS = ['1:1', '16:9', '4:3', '3:2', '2:3', '3:4', '9:16', '21:9']
const MINIMAX_IMAGE_SIZE_OPTIONS = ['1K', '2K', '4K']

function isGeminiImageModel(model: string): boolean {
  const normalizedModel = model.trim().toLowerCase()
  if (normalizedModel === GEMINI_FLASH_IMAGE_MODEL) return true
  if (normalizedModel === GEMINI_PRO_IMAGE_MODEL) return true
  return normalizedModel.startsWith('gemini-') && normalizedModel.endsWith('-image-preview')
}

function getImageSizeOptionsByProviderModel(
  providerType: ImageProviderType,
  model: string
): string[] {
  if (providerType === 'kling') {
    return KLING_IMAGE_SIZE_OPTIONS_BY_MODEL[model.trim().toLowerCase()] ?? ['1K', '2K', '4K']
  }
  if (providerType === 'gemini_api' || isGeminiImageModel(model)) {
    const normalizedModel = model.trim().toLowerCase()
    return normalizedModel === GEMINI_FLASH_IMAGE_MODEL ? GEMINI_FLASH_IMAGE_SIZE_OPTIONS : GEMINI_IMAGE_SIZE_OPTIONS
  }
  if (providerType !== 'volcengine_seedream') return IMAGE_SIZE_OPTIONS
  const normalizedModel = model.trim()
  return VOLCENGINE_SEEDREAM_IMAGE_SIZE_OPTIONS[normalizedModel] ?? IMAGE_SIZE_OPTIONS
}

function getImageAspectRatioOptionsByProviderModel(
  providerType: ImageProviderType,
  model: string
): string[] {
  if (providerType === 'kling') {
    return KLING_IMAGE_ASPECT_RATIO_OPTIONS
  }
  if (providerType === 'gemini_api' || isGeminiImageModel(model)) {
    const normalizedModel = model.trim().toLowerCase()
    return normalizedModel === GEMINI_FLASH_IMAGE_MODEL
      ? GEMINI_FLASH_ASPECT_RATIO_OPTIONS
      : GEMINI_ASPECT_RATIO_OPTIONS
  }
  return IMAGE_ASPECT_RATIO_OPTIONS
}

function getKlingImageSizeOptions(model: string): string[] {
  return KLING_IMAGE_SIZE_OPTIONS_BY_MODEL[model.trim().toLowerCase()] ?? ['1K', '2K', '4K']
}

function normalizeViduImageSize(value: string | undefined): string {
  const normalized = String(value || '').trim().toLowerCase()
  if (!normalized || normalized === '1k' || normalized === '1080' || normalized === '1080p') return '1080p'
  if (normalized === '2k') return '2K'
  if (normalized === '4k') return '4K'
  return VIDU_IMAGE_SIZE_OPTIONS.find((item) => item.toLowerCase() === normalized) || '1080p'
}

function formatImageSizeLabel(size: string): string {
  return size === '512px' ? '0.5K' : size
}

export interface ImageProviderCardProps {
  settings: Settings | undefined
  formData: SettingsUpdate
  updateField: <K extends keyof SettingsUpdate>(key: K, value: SettingsUpdate[K]) => void
  showApiKeys: Record<string, boolean>
  onToggleApiKey: (key: string) => void
  wan2gpPresets: Wan2gpImagePreset[]
}

export function ImageProviderCard({
  settings,
  formData,
  updateField,
  showApiKeys,
  onToggleApiKey,
  wan2gpPresets,
}: ImageProviderCardProps) {
  const confirmDialog = useConfirmDialog()
  const queryClient = useQueryClient()
  const imageModelManager = useModelManager()

  const [isCreatingCustomImageProvider, setIsCreatingCustomImageProvider] = useState(false)
  const [customImageProviderName, setCustomImageProviderName] = useState('')
  const [customImageProviderType, setCustomImageProviderType] = useState<ImageProviderType>('openai_chat')
  const [isLoadingImageModels, setIsLoadingImageModels] = useState(false)
  const [wan2gpReferenceResolutionTierOverride, setWan2gpReferenceResolutionTierOverride] = useState<string | null>(null)
  const [wan2gpFrameResolutionTierOverride, setWan2gpFrameResolutionTierOverride] = useState<string | null>(null)

  // Derived image providers
  const imageProviders: ImageProviderConfig[] = useMemo(
    () => formData.image_providers ?? settings?.image_providers ?? [],
    [formData.image_providers, settings?.image_providers]
  )
  const orderedImageProviders: ImageProviderConfig[] = useMemo(() => {
    const builtins = imageProviders.filter((provider) => provider.is_builtin)
    const customs = imageProviders.filter((provider) => !provider.is_builtin)
    return [...builtins, ...customs]
  }, [imageProviders])

  // Wan2GP image preset derived values
  const wan2gpT2iPresets = wan2gpPresets.filter((preset) => {
    return isWan2gpT2iPreset(preset)
  })
  const wan2gpI2iPresets = wan2gpPresets.filter((preset) => {
    return isWan2gpI2iPreset(preset)
  })
  const wan2gpPresetNameMap = useMemo(
    () =>
      new Map(
        wan2gpPresets.map((preset) => [preset.id, preset.display_name] as const)
      ),
    [wan2gpPresets]
  )
  const rawWan2gpEnabledModels = formData.image_wan2gp_enabled_models ?? settings?.image_wan2gp_enabled_models
  const wan2gpImageCatalogIds = useMemo(
    () => normalizeModelIds(wan2gpPresets.map((preset) => preset.id)),
    [wan2gpPresets]
  )
  const effectiveWan2gpEnabledModels = useMemo(() => {
    return resolveEnabledModelIds(rawWan2gpEnabledModels, wan2gpImageCatalogIds)
  }, [rawWan2gpEnabledModels, wan2gpImageCatalogIds])
  const wan2gpEnabledSet = useMemo(
    () => new Set(effectiveWan2gpEnabledModels),
    [effectiveWan2gpEnabledModels]
  )
  const visibleWan2gpT2iPresets = wan2gpT2iPresets.filter((preset) => wan2gpEnabledSet.has(preset.id))
  const visibleWan2gpI2iPresets = wan2gpI2iPresets.filter((preset) => wan2gpEnabledSet.has(preset.id))
  const effectiveWan2gpT2iCatalog = visibleWan2gpT2iPresets
  const effectiveWan2gpI2iCatalog = visibleWan2gpI2iPresets
  const availableWan2gpT2iIds = new Set(effectiveWan2gpT2iCatalog.map((item) => item.id))
  const availableWan2gpI2iIds = new Set(effectiveWan2gpI2iCatalog.map((item) => item.id))
  const preferredWan2gpT2iPreset = effectiveWan2gpT2iCatalog.find((preset) => preset.id === 'qwen_image_2512')?.id
  const preferredWan2gpI2iPreset = effectiveWan2gpI2iCatalog.find((preset) => preset.id === 'qwen_image_edit_plus2')?.id
  const configuredWan2gpT2iPreset = formData.image_wan2gp_preset ?? settings?.image_wan2gp_preset ?? ''
  const configuredWan2gpI2iPreset = formData.image_wan2gp_preset_i2i ?? settings?.image_wan2gp_preset_i2i ?? ''
  const selectedWan2gpT2iPreset = availableWan2gpT2iIds.has(configuredWan2gpT2iPreset)
    ? configuredWan2gpT2iPreset
    : (preferredWan2gpT2iPreset ?? effectiveWan2gpT2iCatalog[0]?.id ?? '')
  const selectedWan2gpI2iPreset = availableWan2gpI2iIds.has(configuredWan2gpI2iPreset)
    ? configuredWan2gpI2iPreset
    : (preferredWan2gpI2iPreset ?? effectiveWan2gpI2iCatalog[0]?.id ?? '')
  const selectedWan2gpT2iPresetConfig = wan2gpT2iPresets.find((preset) => preset.id === selectedWan2gpT2iPreset)
  const selectedWan2gpI2iPresetConfig = wan2gpI2iPresets.find((preset) => preset.id === selectedWan2gpI2iPreset)
  const wan2gpImageResolutionOptions = selectedWan2gpT2iPresetConfig?.supported_resolutions?.length
    ? selectedWan2gpT2iPresetConfig.supported_resolutions
    : [formData.image_wan2gp_frame_resolution ?? settings?.image_wan2gp_frame_resolution ?? '1088x1920']
  const wan2gpImageResolutionChoices = getWan2gpResolutionChoices(wan2gpImageResolutionOptions)
  const wan2gpImageResolutionTiers = getWan2gpResolutionTiers(wan2gpImageResolutionChoices)

  // Reference resolution
  const currentWan2gpReferenceResolution =
    formData.image_wan2gp_reference_resolution ?? settings?.image_wan2gp_reference_resolution
  const selectedWan2gpReferenceResolution = (
    currentWan2gpReferenceResolution
    && wan2gpImageResolutionOptions.includes(currentWan2gpReferenceResolution)
  )
    ? currentWan2gpReferenceResolution
    : (wan2gpImageResolutionOptions.find((item) => item === '1024x1024')
      || selectedWan2gpT2iPresetConfig?.default_resolution
      || wan2gpImageResolutionOptions[0]
      || '1024x1024')
  const derivedWan2gpReferenceResolutionTier = wan2gpImageResolutionChoices.find(
    (choice) => choice.value === selectedWan2gpReferenceResolution
  )?.tier || wan2gpImageResolutionTiers[0] || '720p'
  const selectedWan2gpReferenceResolutionTier = (
    wan2gpReferenceResolutionTierOverride
    && wan2gpImageResolutionTiers.includes(wan2gpReferenceResolutionTierOverride)
  )
    ? wan2gpReferenceResolutionTierOverride
    : derivedWan2gpReferenceResolutionTier
  const selectedReferenceTierChoices = wan2gpImageResolutionChoices.filter(
    (choice) => choice.tier === selectedWan2gpReferenceResolutionTier
  )
  const resolvedReferenceTierChoices = selectedReferenceTierChoices.length > 0
    ? selectedReferenceTierChoices
    : wan2gpImageResolutionChoices
  const selectedWan2gpReferenceResolutionValue = resolvedReferenceTierChoices.some(
    (choice) => choice.value === selectedWan2gpReferenceResolution
  )
    ? selectedWan2gpReferenceResolution
    : (resolvedReferenceTierChoices[0]?.value || selectedWan2gpReferenceResolution)

  // Frame resolution
  const currentWan2gpFrameResolution =
    formData.image_wan2gp_frame_resolution ?? settings?.image_wan2gp_frame_resolution
  const selectedWan2gpFrameResolution = (
    currentWan2gpFrameResolution
    && wan2gpImageResolutionOptions.includes(currentWan2gpFrameResolution)
  )
    ? currentWan2gpFrameResolution
    : (selectedWan2gpT2iPresetConfig?.default_resolution || wan2gpImageResolutionOptions[0] || '1088x1920')
  const derivedWan2gpFrameResolutionTier = wan2gpImageResolutionChoices.find(
    (choice) => choice.value === selectedWan2gpFrameResolution
  )?.tier || wan2gpImageResolutionTiers[0] || '720p'
  const selectedWan2gpFrameResolutionTier = (
    wan2gpFrameResolutionTierOverride
    && wan2gpImageResolutionTiers.includes(wan2gpFrameResolutionTierOverride)
  )
    ? wan2gpFrameResolutionTierOverride
    : derivedWan2gpFrameResolutionTier
  const selectedFrameTierChoices = wan2gpImageResolutionChoices.filter(
    (choice) => choice.tier === selectedWan2gpFrameResolutionTier
  )
  const resolvedFrameTierChoices = selectedFrameTierChoices.length > 0
    ? selectedFrameTierChoices
    : wan2gpImageResolutionChoices
  const selectedWan2gpFrameResolutionValue = resolvedFrameTierChoices.some(
    (choice) => choice.value === selectedWan2gpFrameResolution
  )
    ? selectedWan2gpFrameResolution
    : (resolvedFrameTierChoices[0]?.value || selectedWan2gpFrameResolution)

  // Image provider update helpers
  const updateImageProviders = useCallback((nextProviders: ImageProviderConfig[]) => {
    updateField('image_providers', nextProviders)
  }, [updateField])

  const updateImageProvider = useCallback((providerId: string, patch: Partial<ImageProviderConfig>) => {
    const nextProviders = imageProviders.map((provider) => {
      if (provider.id !== providerId) return provider
      const nextProviderType = (patch.provider_type ?? provider.provider_type) as ImageProviderType
      const nextEnabled = normalizeModelIds(
        patch.enabled_models ?? provider.enabled_models ?? []
      )
      const nextCatalog = normalizeModelIds(
        patch.catalog_models ?? provider.catalog_models ?? nextEnabled
      )
      const finalEnabled = nextCatalog.length > 0
        ? nextEnabled.filter((id) => nextCatalog.includes(id))
        : nextEnabled
      let nextDefaultModel = String(
        patch.default_model
        ?? provider.default_model
        ?? finalEnabled[0]
        ?? ''
      ).trim()
      if (finalEnabled.length === 0) {
        nextDefaultModel = ''
      }
      if (nextDefaultModel && finalEnabled.length > 0 && !finalEnabled.includes(nextDefaultModel)) {
        nextDefaultModel = finalEnabled[0]
      }
      if (!nextDefaultModel && finalEnabled.length > 0) {
        nextDefaultModel = finalEnabled[0]
      }
      const sizeOptions = getImageSizeOptionsByProviderModel(nextProviderType, nextDefaultModel)
      const aspectRatioOptions = getImageAspectRatioOptionsByProviderModel(nextProviderType, nextDefaultModel)
      let nextReferenceSize = String(
        patch.reference_size
        ?? provider.reference_size
        ?? sizeOptions[0]
        ?? '1K'
      ).trim()
      if (!sizeOptions.includes(nextReferenceSize)) {
        nextReferenceSize = sizeOptions[0] || '1K'
      }
      let nextFrameSize = String(
        patch.frame_size
        ?? provider.frame_size
        ?? sizeOptions[0]
        ?? '1K'
      ).trim()
      if (!sizeOptions.includes(nextFrameSize)) {
        nextFrameSize = sizeOptions[0] || '1K'
      }
      let nextReferenceAspectRatio = String(
        patch.reference_aspect_ratio
        ?? provider.reference_aspect_ratio
        ?? aspectRatioOptions[0]
        ?? '1:1'
      ).trim()
      if (!aspectRatioOptions.includes(nextReferenceAspectRatio)) {
        nextReferenceAspectRatio = aspectRatioOptions.includes('1:1')
          ? '1:1'
          : (aspectRatioOptions[0] || '1:1')
      }
      let nextFrameAspectRatio = String(
        patch.frame_aspect_ratio
        ?? provider.frame_aspect_ratio
        ?? aspectRatioOptions[0]
        ?? '9:16'
      ).trim()
      if (!aspectRatioOptions.includes(nextFrameAspectRatio)) {
        nextFrameAspectRatio = aspectRatioOptions.includes('9:16')
          ? '9:16'
          : (aspectRatioOptions[0] || '9:16')
      }
      return {
        ...provider,
        ...patch,
        provider_type: nextProviderType,
        catalog_models: nextCatalog,
        enabled_models: finalEnabled,
        default_model: nextDefaultModel,
        reference_aspect_ratio: nextReferenceAspectRatio,
        reference_size: nextReferenceSize,
        frame_aspect_ratio: nextFrameAspectRatio,
        frame_size: nextFrameSize,
      }
    })
    updateImageProviders(nextProviders)
  }, [imageProviders, updateImageProviders])

  // Image provider adapters
  const imageProviderAdapters = useMemo(() => createImageProviderAdapters({
    imageProviders,
    normalizeModelIds,
    resolveEnabledModelIds,
    updateImageProvider,
    updateField,
    formData,
    settings,
    defaultImageModel: DEFAULT_IMAGE_MODEL,
    defaultCustomImageModels: DEFAULT_CUSTOM_IMAGE_MODELS,
    rawWan2gpEnabledModels,
    wan2gpPresets,
    wan2gpT2iPresets,
    wan2gpI2iPresets,
    wan2gpPresetNameMap,
  }), [
    formData,
    imageProviders,
    rawWan2gpEnabledModels,
    settings,
    updateField,
    updateImageProvider,
    wan2gpI2iPresets,
    wan2gpPresetNameMap,
    wan2gpPresets,
    wan2gpT2iPresets,
  ])

  const imageModelManagerCatalogIds = imageModelManager.catalogIds
  const imageModelManagerAdapter = useMemo(() => {
    const providerId = imageModelManager.providerId
    if (!providerId) return null
    return imageProviderAdapters[providerId] ?? null
  }, [imageModelManager.providerId, imageProviderAdapters])
  const imageModelManagerEnabledIds = useMemo(
    () => imageModelManagerAdapter?.getSelectedIds(imageModelManagerCatalogIds) ?? [],
    [imageModelManagerAdapter, imageModelManagerCatalogIds]
  )
  const canRefreshImageModelManagerCatalog = Boolean(imageModelManagerAdapter?.canRefreshCatalog)
  const imageModelManagerAllSelected = imageModelManagerCatalogIds.length > 0
    && imageModelManagerCatalogIds.every((id) => imageModelManagerEnabledIds.includes(id))

  // Handlers
  const refreshImageProviderModels = useCallback(async (
    providerId: string,
    options?: { silent?: boolean }
  ): Promise<ModelInfo[]> => {
    setIsLoadingImageModels(true)
    try {
      if (providerId === 'wan2gp') {
        const response = await api.settings.fetchWan2gpImagePresets()
        queryClient.setQueryData(queryKeys.settings.wan2gpImagePresets, response)
        const models = normalizeModelIds((response.presets || []).map((item) => item.id))
          .sort((a, b) => a.localeCompare(b))
          .map((id) => ({ id }))
        imageModelManager.setCatalog(models)
        if (!options?.silent) {
          toast.success(`获取到 ${models.length} 个模型`)
        }
        return models
      }

      const provider = imageProviders.find((item) => item.id === providerId)
      if (!provider) {
        imageModelManager.setCatalog([])
        return []
      }

      if (provider.is_builtin) {
        const modelIds = normalizeModelIds(provider.catalog_models ?? [])
        const models = modelIds.map((id) => ({ id }))
        const nextEnabled = normalizeModelIds(provider.enabled_models ?? [])
        imageModelManager.setCatalog(models)
        updateImageProvider(provider.id, {
          catalog_models: modelIds,
          enabled_models: nextEnabled.length > 0 ? nextEnabled : modelIds,
          default_model: provider.default_model || modelIds[0] || '',
        })
        if (!options?.silent) {
          toast.success(`已载入 ${models.length} 个模型`)
        }
        return models
      }

      const models = DEFAULT_CUSTOM_IMAGE_MODELS.map((id) => ({ id }))
      imageModelManager.setCatalog(models)
      updateImageProvider(provider.id, {
        catalog_models: DEFAULT_CUSTOM_IMAGE_MODELS,
        enabled_models: DEFAULT_CUSTOM_IMAGE_MODELS,
        default_model: DEFAULT_IMAGE_MODEL,
      })
      if (!options?.silent) {
        toast.success(`已载入模型（${models.length} 个）`)
      }
      return models
    } catch (error) {
      if (!options?.silent) {
        toast.error(error instanceof Error ? error.message : '获取模型列表失败')
      }
      return []
    } finally {
      setIsLoadingImageModels(false)
    }
  }, [imageModelManager, imageProviders, queryClient, updateImageProvider])

  const handleOpenImageModelManager = useCallback((providerId: string) => {
    const adapter = imageProviderAdapters[providerId]
    if (!adapter) {
      imageModelManager.openManager(providerId, [])
      return
    }
    adapter.ensureCatalogInitialized()
    const modelIds = adapter.getCatalogIds()
    imageModelManager.openManager(providerId, modelIds.map((id) => ({ id })))
  }, [imageModelManager, imageProviderAdapters])

  const handleImageModelEnabledChange = useCallback((modelId: string, checked: boolean) => {
    const providerId = imageModelManager.providerId
    if (!providerId) return
    const adapter = imageProviderAdapters[providerId]
    if (!adapter) return
    const enabled = new Set(adapter.getSelectedIds(imageModelManagerCatalogIds))
    if (checked) enabled.add(modelId)
    else enabled.delete(modelId)
    const nextEnabled = normalizeModelIds(Array.from(enabled))
    adapter.setEnabledIds(nextEnabled)
  }, [
    imageModelManagerCatalogIds,
    imageModelManager.providerId,
    imageProviderAdapters,
  ])

  const handleToggleAllImageModels = useCallback(() => {
    if (!imageModelManagerAdapter) return
    const nextEnabled = imageModelManagerAllSelected ? [] : imageModelManagerCatalogIds
    imageModelManagerAdapter.setEnabledIds(nextEnabled)
  }, [
    imageModelManagerAllSelected,
    imageModelManagerAdapter,
    imageModelManagerCatalogIds,
  ])

  const handleRefreshCurrentImageProviderModels = useCallback(() => {
    if (!imageModelManagerAdapter) return
    void refreshImageProviderModels(imageModelManagerAdapter.providerId)
  }, [imageModelManagerAdapter, refreshImageProviderModels])

  const handleTestImageModel = useCallback(async (modelId: string) => {
    if (!imageModelManagerAdapter) return
    imageModelManager.setModelTesting(modelId)
    const modelLabel = imageModelManagerAdapter.getModelLabel(modelId) || modelId
    try {
      const result = await api.settings.testImageModel(imageModelManagerAdapter.buildTestPayload(modelId))
      if (result.success) {
        const latencyLabel = typeof result.latency_ms === 'number' ? `（${result.latency_ms}ms）` : ''
        imageModelManager.setModelResult(modelId, {
          success: true,
          message: result.message || 'OK',
        })
        toast.success(`模型 ${modelLabel} 检测通过${latencyLabel}`)
        return
      }
      const errorMessage = result.error || result.message || '未知错误'
      imageModelManager.setModelResult(modelId, {
        success: false,
        message: errorMessage,
      })
      toast.error(`模型 ${modelLabel} 检测失败: ${errorMessage}`)
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : '检测失败'
      imageModelManager.setModelResult(modelId, {
        success: false,
        message: errorMessage,
      })
      toast.error(`模型 ${modelLabel} 检测失败: ${errorMessage}`)
    }
  }, [imageModelManager, imageModelManagerAdapter])

  const handleAddCustomImageProvider = useCallback(() => {
    const trimmedName = customImageProviderName.trim()
    if (!trimmedName) {
      toast.error('请输入供应商名称')
      return
    }
    const baseId = normalizeProviderId(trimmedName)
    const usedIds = new Set(imageProviders.map((item) => item.id))
    let nextId = baseId
    let suffix = 2
    while (usedIds.has(nextId)) {
      nextId = `${baseId}_${suffix}`
      suffix += 1
    }
    const nextProvider: ImageProviderConfig = {
      id: nextId,
      name: trimmedName,
      is_builtin: false,
      provider_type: customImageProviderType,
      base_url: '',
      api_key: '',
      catalog_models: DEFAULT_CUSTOM_IMAGE_MODELS,
      enabled_models: DEFAULT_CUSTOM_IMAGE_MODELS,
      default_model: DEFAULT_IMAGE_MODEL,
      reference_aspect_ratio: '1:1',
      reference_size: '1K',
      frame_aspect_ratio: '9:16',
      frame_size: '1K',
    }
    const nextProviders = [...imageProviders, nextProvider]
    updateImageProviders(nextProviders)
    setCustomImageProviderName('')
    setCustomImageProviderType('openai_chat')
    setIsCreatingCustomImageProvider(false)
  }, [
    customImageProviderName,
    customImageProviderType,
    imageProviders,
    updateImageProviders,
  ])

  const handleDeleteCustomImageProvider = useCallback(async (providerId: string) => {
    const target = imageProviders.find((provider) => provider.id === providerId)
    if (!target) return
    if (target.is_builtin) {
      toast.error('内置供应商不支持删除')
      return
    }
    const confirmed = await confirmDialog({
      title: '删除自定义供应商',
      description: `确定删除自定义供应商「${target.name}」吗？`,
      confirmText: '删除',
      cancelText: '取消',
      variant: 'destructive',
    })
    if (!confirmed) return

    const nextProviders = imageProviders.filter((provider) => provider.id !== providerId)
    updateImageProviders(nextProviders)

    if (imageModelManager.providerId === providerId) {
      imageModelManager.onOpenChange(false)
    }

    const currentDefault = String(
      formData.default_image_provider ?? settings?.default_image_provider ?? ''
    ).trim()
    const validDefaultIds = new Set(nextProviders.map((provider) => provider.id))
    if (settings?.wan2gp_available) {
      validDefaultIds.add('wan2gp')
    }
    if (!validDefaultIds.has(currentDefault)) {
      const fallbackDefault = nextProviders[0]?.id || (settings?.wan2gp_available ? 'wan2gp' : '')
      updateField('default_image_provider', fallbackDefault)
    }

    toast.success(`已删除供应商：${target.name}`)
  }, [
    formData.default_image_provider,
    confirmDialog,
    imageModelManager,
    imageProviders,
    settings?.default_image_provider,
    settings?.wan2gp_available,
    updateField,
    updateImageProviders,
  ])

  const handleWan2gpT2iPresetChange = (presetId: string) => {
    setWan2gpReferenceResolutionTierOverride(null)
    setWan2gpFrameResolutionTierOverride(null)
    updateField('image_wan2gp_preset', presetId)
    const preset = effectiveWan2gpT2iCatalog.find((item) => item.id === presetId)
    if (!preset) return

    const options = preset.supported_resolutions?.length
      ? preset.supported_resolutions
      : [preset.default_resolution]
    const currentReferenceResolution =
      formData.image_wan2gp_reference_resolution ?? settings?.image_wan2gp_reference_resolution
    if (!currentReferenceResolution || !options.includes(currentReferenceResolution)) {
      updateField(
        'image_wan2gp_reference_resolution',
        options.find((item) => item === '1024x1024') || preset.default_resolution || options[0]
      )
    }
    const currentFrameResolution =
      formData.image_wan2gp_frame_resolution ?? settings?.image_wan2gp_frame_resolution
    if (!currentFrameResolution || !options.includes(currentFrameResolution)) {
      updateField('image_wan2gp_frame_resolution', preset.default_resolution || options[0])
    }
  }

  const handleWan2gpI2iPresetChange = (presetId: string) => {
    updateField('image_wan2gp_preset_i2i', presetId)
  }

  const handleWan2gpReferenceResolutionTierChange = (tier: string) => {
    setWan2gpReferenceResolutionTierOverride(tier)
    const nextResolution = pickDefaultResolutionForTier(wan2gpImageResolutionChoices, tier)
    if (nextResolution) {
      updateField('image_wan2gp_reference_resolution', nextResolution)
      return
    }
    const fallback = wan2gpImageResolutionChoices.find((choice) => choice.tier === tier)?.value
    if (fallback) {
      updateField('image_wan2gp_reference_resolution', fallback)
    }
  }

  const handleWan2gpFrameResolutionTierChange = (tier: string) => {
    setWan2gpFrameResolutionTierOverride(tier)
    const nextResolution = pickDefaultResolutionForTier(wan2gpImageResolutionChoices, tier)
    if (nextResolution) {
      updateField('image_wan2gp_frame_resolution', nextResolution)
      return
    }
    const fallback = wan2gpImageResolutionChoices.find((choice) => choice.tier === tier)?.value
    if (fallback) {
      updateField('image_wan2gp_frame_resolution', fallback)
    }
  }

  const selectedKlingT2iModelRaw = String(
    formData.image_kling_t2i_model ?? settings?.image_kling_t2i_model ?? ''
  ).trim()
  const selectedKlingI2iModelRaw = String(
    formData.image_kling_i2i_model ?? settings?.image_kling_i2i_model ?? ''
  ).trim()
  const klingEnabledModels = resolveEnabledModelIds(
    formData.image_kling_enabled_models ?? settings?.image_kling_enabled_models,
    KLING_MODEL_OPTIONS
  )
  const selectedKlingModel = klingEnabledModels.includes(selectedKlingT2iModelRaw)
    ? selectedKlingT2iModelRaw
    : klingEnabledModels.includes(selectedKlingI2iModelRaw)
      ? selectedKlingI2iModelRaw
      : (klingEnabledModels[0] || '')
  const klingReferenceAspectRatioOptions = KLING_IMAGE_ASPECT_RATIO_OPTIONS
  const klingFrameAspectRatioOptions = KLING_IMAGE_ASPECT_RATIO_OPTIONS
  const klingReferenceSizeOptions = getKlingImageSizeOptions(selectedKlingModel || 'kling-v3')
  const klingFrameSizeOptions = getKlingImageSizeOptions(selectedKlingModel || 'kling-v3')
  const klingReferenceAspectRatio = klingReferenceAspectRatioOptions.includes(
    String(formData.image_kling_reference_aspect_ratio ?? settings?.image_kling_reference_aspect_ratio ?? '1:1').trim()
  )
    ? String(formData.image_kling_reference_aspect_ratio ?? settings?.image_kling_reference_aspect_ratio ?? '1:1').trim()
    : '1:1'
  const klingFrameAspectRatio = klingFrameAspectRatioOptions.includes(
    String(formData.image_kling_frame_aspect_ratio ?? settings?.image_kling_frame_aspect_ratio ?? '9:16').trim()
  )
    ? String(formData.image_kling_frame_aspect_ratio ?? settings?.image_kling_frame_aspect_ratio ?? '9:16').trim()
    : '9:16'
  const klingReferenceSize = (() => {
    const value = String(formData.image_kling_reference_size ?? settings?.image_kling_reference_size ?? '1K').trim().toUpperCase()
    return klingReferenceSizeOptions.includes(value) ? value : (klingReferenceSizeOptions[0] || '1K')
  })()
  const klingFrameSize = (() => {
    const value = String(formData.image_kling_frame_size ?? settings?.image_kling_frame_size ?? '1K').trim().toUpperCase()
    return klingFrameSizeOptions.includes(value) ? value : (klingFrameSizeOptions[0] || '1K')
  })()

  const handleKlingModelChange = (value: string) => {
    updateField('image_kling_t2i_model', value)
    updateField('image_kling_i2i_model', value)
    const nextSizeOptions = getKlingImageSizeOptions(value)
    const currentReferenceSize = String(
      formData.image_kling_reference_size ?? settings?.image_kling_reference_size ?? '1K'
    ).trim().toUpperCase()
    if (!nextSizeOptions.includes(currentReferenceSize)) {
      updateField('image_kling_reference_size', nextSizeOptions[0] || '1K')
    }
    const currentFrameSize = String(
      formData.image_kling_frame_size ?? settings?.image_kling_frame_size ?? '1K'
    ).trim().toUpperCase()
    if (!nextSizeOptions.includes(currentFrameSize)) {
      updateField('image_kling_frame_size', nextSizeOptions[0] || '1K')
    }
  }

  const selectedViduModelRaw = String(
    formData.image_vidu_t2i_model
    ?? settings?.image_vidu_t2i_model
    ?? formData.image_vidu_i2i_model
    ?? settings?.image_vidu_i2i_model
    ?? 'viduq2'
  ).trim()
  const viduEnabledModels = resolveEnabledModelIds(
    formData.image_vidu_enabled_models ?? settings?.image_vidu_enabled_models,
    VIDU_IMAGE_MODEL_OPTIONS
  )
  const selectedViduModel = viduEnabledModels.includes(selectedViduModelRaw)
    ? selectedViduModelRaw
    : (viduEnabledModels[0] || '')
  const selectedViduReferenceAspectRatioRaw = String(
    formData.image_vidu_reference_aspect_ratio ?? settings?.image_vidu_reference_aspect_ratio ?? '1:1'
  ).trim()
  const selectedViduReferenceAspectRatio = VIDU_IMAGE_ASPECT_RATIO_OPTIONS.includes(selectedViduReferenceAspectRatioRaw)
    ? selectedViduReferenceAspectRatioRaw
    : '1:1'
  const selectedViduFrameAspectRatioRaw = String(
    formData.image_vidu_frame_aspect_ratio ?? settings?.image_vidu_frame_aspect_ratio ?? '9:16'
  ).trim()
  const selectedViduFrameAspectRatio = VIDU_IMAGE_ASPECT_RATIO_OPTIONS.includes(selectedViduFrameAspectRatioRaw)
    ? selectedViduFrameAspectRatioRaw
    : '9:16'
  const selectedViduReferenceSize = normalizeViduImageSize(
    formData.image_vidu_reference_size ?? settings?.image_vidu_reference_size
  )
  const selectedViduFrameSize = normalizeViduImageSize(
    formData.image_vidu_frame_size ?? settings?.image_vidu_frame_size
  )
  const selectedMinimaxModelRaw = String(
    formData.image_minimax_model ?? settings?.image_minimax_model ?? 'image-01'
  ).trim()
  const minimaxEnabledModels = resolveEnabledModelIds(
    formData.image_minimax_enabled_models ?? settings?.image_minimax_enabled_models,
    MINIMAX_IMAGE_MODEL_OPTIONS
  )
  const selectedMinimaxModel = minimaxEnabledModels.includes(selectedMinimaxModelRaw)
    ? selectedMinimaxModelRaw
    : (minimaxEnabledModels[0] || '')
  const selectedMinimaxReferenceAspectRatioRaw = String(
    formData.image_minimax_reference_aspect_ratio ?? settings?.image_minimax_reference_aspect_ratio ?? '1:1'
  ).trim()
  const selectedMinimaxReferenceAspectRatio = MINIMAX_IMAGE_ASPECT_RATIO_OPTIONS.includes(selectedMinimaxReferenceAspectRatioRaw)
    ? selectedMinimaxReferenceAspectRatioRaw
    : '1:1'
  const selectedMinimaxFrameAspectRatioRaw = String(
    formData.image_minimax_frame_aspect_ratio ?? settings?.image_minimax_frame_aspect_ratio ?? '9:16'
  ).trim()
  const selectedMinimaxFrameAspectRatio = MINIMAX_IMAGE_ASPECT_RATIO_OPTIONS.includes(selectedMinimaxFrameAspectRatioRaw)
    ? selectedMinimaxFrameAspectRatioRaw
    : '9:16'
  const selectedMinimaxReferenceSizeRaw = String(
    formData.image_minimax_reference_size ?? settings?.image_minimax_reference_size ?? '2K'
  ).trim().toUpperCase()
  const selectedMinimaxReferenceSize = MINIMAX_IMAGE_SIZE_OPTIONS.includes(selectedMinimaxReferenceSizeRaw)
    ? selectedMinimaxReferenceSizeRaw
    : '2K'
  const selectedMinimaxFrameSizeRaw = String(
    formData.image_minimax_frame_size ?? settings?.image_minimax_frame_size ?? '2K'
  ).trim().toUpperCase()
  const selectedMinimaxFrameSize = MINIMAX_IMAGE_SIZE_OPTIONS.includes(selectedMinimaxFrameSizeRaw)
    ? selectedMinimaxFrameSizeRaw
    : '2K'

  useEffect(() => {
    if (selectedKlingModel && selectedKlingT2iModelRaw !== selectedKlingModel) {
      updateField('image_kling_t2i_model', selectedKlingModel)
    }
    if (selectedKlingModel && selectedKlingI2iModelRaw !== selectedKlingModel) {
      updateField('image_kling_i2i_model', selectedKlingModel)
    }
    if (!klingReferenceAspectRatioOptions.includes(klingReferenceAspectRatio)) {
      updateField('image_kling_reference_aspect_ratio', '1:1')
    }
    if (!klingFrameAspectRatioOptions.includes(klingFrameAspectRatio)) {
      updateField('image_kling_frame_aspect_ratio', '9:16')
    }
    if (!klingReferenceSizeOptions.includes(klingReferenceSize)) {
      updateField('image_kling_reference_size', klingReferenceSizeOptions[0] || '1K')
    }
    if (!klingFrameSizeOptions.includes(klingFrameSize)) {
      updateField('image_kling_frame_size', klingFrameSizeOptions[0] || '1K')
    }
  }, [
    klingFrameAspectRatio,
    klingFrameAspectRatioOptions,
    klingFrameSize,
    klingFrameSizeOptions,
    klingReferenceAspectRatio,
    klingReferenceAspectRatioOptions,
    klingReferenceSize,
    klingReferenceSizeOptions,
    selectedKlingI2iModelRaw,
    selectedKlingModel,
    selectedKlingT2iModelRaw,
    updateField,
  ])
  useEffect(() => {
    if (selectedViduModel && selectedViduModelRaw !== selectedViduModel) {
      updateField('image_vidu_t2i_model', selectedViduModel)
      updateField('image_vidu_i2i_model', selectedViduModel)
    }
  }, [selectedViduModel, selectedViduModelRaw, updateField])
  useEffect(() => {
    if (selectedMinimaxModel && selectedMinimaxModelRaw !== selectedMinimaxModel) {
      updateField('image_minimax_model', selectedMinimaxModel)
    }
  }, [selectedMinimaxModel, selectedMinimaxModelRaw, updateField])
  const deploymentProfile = (formData.deployment_profile ?? settings?.deployment_profile ?? 'cpu').trim().toLowerCase()
  const showWan2gpCard = deploymentProfile !== 'cpu'

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ImageIcon className="h-5 w-5" />
          图像生成
        </CardTitle>
        <CardDescription>用于 AI 图像生成</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="flex flex-col gap-4">
          {orderedImageProviders.map((provider) => {
            const enabledModels = normalizeModelIds(provider.enabled_models ?? [])
            const selectedModel = enabledModels.includes(provider.default_model)
              ? provider.default_model
              : (enabledModels[0] || '')
            const imageSizeOptions = getImageSizeOptionsByProviderModel(
              provider.provider_type,
              selectedModel || provider.default_model || ''
            )
            const imageAspectRatioOptions = getImageAspectRatioOptionsByProviderModel(
              provider.provider_type,
              selectedModel || provider.default_model || ''
            )
            const selectedReferenceAspectRatio = imageAspectRatioOptions.includes(provider.reference_aspect_ratio || '')
              ? (provider.reference_aspect_ratio || '')
              : (imageAspectRatioOptions.includes('1:1') ? '1:1' : (imageAspectRatioOptions[0] || '1:1'))
            const selectedFrameAspectRatio = imageAspectRatioOptions.includes(provider.frame_aspect_ratio || '')
              ? (provider.frame_aspect_ratio || '')
              : (imageAspectRatioOptions.includes('9:16') ? '9:16' : (imageAspectRatioOptions[0] || '9:16'))
            const selectedReferenceSize = imageSizeOptions.includes(provider.reference_size || '')
              ? (provider.reference_size || '')
              : (imageSizeOptions[0] || '1K')
            const selectedFrameSize = imageSizeOptions.includes(provider.frame_size || '')
              ? (provider.frame_size || '')
              : (imageSizeOptions[0] || '1K')
            const visibilityKey = `image_${provider.id}`
            return (
              <div
                key={provider.id}
                className={`border rounded-lg p-4 space-y-4 ${provider.is_builtin ? 'order-1' : 'order-20'}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-2 flex-wrap">
                    <div className="font-medium">
                      {getImageProviderDisplayName(provider)}
                    </div>
                    <Badge variant="outline">{provider.is_builtin ? '内置' : '自定义'}</Badge>
                    {provider.api_key.trim() && (
                      <Badge variant="outline" className="text-green-600">
                        <Check className="h-3 w-3 mr-1" />
                        已配置
                      </Badge>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => handleOpenImageModelManager(provider.id)}
                    >
                      管理模型列表
                    </Button>
                    {!provider.is_builtin && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="text-destructive border-destructive/40 hover:bg-destructive/10 hover:text-destructive"
                        onClick={() => handleDeleteCustomImageProvider(provider.id)}
                      >
                        <Trash2 className="h-4 w-4 mr-1" />
                        删除
                      </Button>
                    )}
                  </div>
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                    <div className="space-y-2">
                      <Label htmlFor={`image_api_key_${provider.id}`}>API Key</Label>
                      <SecretInput
                        id={`image_api_key_${provider.id}`}
                        visible={Boolean(showApiKeys[visibilityKey])}
                        onToggleVisibility={() => onToggleApiKey(visibilityKey)}
                        placeholder="sk-..."
                        value={provider.api_key}
                        onChange={(e) => updateImageProvider(provider.id, { api_key: e.target.value })}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor={`image_base_url_${provider.id}`}>Base URL</Label>
                      <Input
                        id={`image_base_url_${provider.id}`}
                        placeholder="https://api.openai.com/v1"
                        value={provider.base_url}
                        onChange={(e) => updateImageProvider(provider.id, { base_url: e.target.value })}
                      />
                    </div>
                    <div className="space-y-2 md:col-span-2">
                      <Label htmlFor={`image_model_${provider.id}`}>模型</Label>
                      <Select
                        value={selectedModel}
                        onValueChange={(value) => updateImageProvider(provider.id, { default_model: value })}
                      >
                        <SelectTrigger id={`image_model_${provider.id}`}>
                          <SelectValue placeholder="请先勾选模型" />
                        </SelectTrigger>
                        <SelectContent>
                          {enabledModels.length > 0 ? (
                            enabledModels.map((modelId) => (
                              <SelectItem key={modelId} value={modelId}>
                                {modelId}
                              </SelectItem>
                            ))
                          ) : (
                            <div className="px-2 py-1.5 text-sm text-muted-foreground">
                              请在「管理模型列表」中勾选模型
                            </div>
                          )}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor={`image_reference_aspect_ratio_${provider.id}`}>参考图宽高比</Label>
                      <Select
                        value={selectedReferenceAspectRatio}
                        onValueChange={(value) => updateImageProvider(provider.id, { reference_aspect_ratio: value })}
                      >
                        <SelectTrigger id={`image_reference_aspect_ratio_${provider.id}`}>
                          <SelectValue placeholder="选择宽高比" />
                        </SelectTrigger>
                        <SelectContent>
                          {imageAspectRatioOptions.map((item) => (
                            <SelectItem key={item} value={item}>
                              {item}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor={`image_reference_size_${provider.id}`}>参考图分辨率</Label>
                      <Select
                        value={selectedReferenceSize}
                        onValueChange={(value) => updateImageProvider(provider.id, { reference_size: value })}
                      >
                        <SelectTrigger id={`image_reference_size_${provider.id}`}>
                          <SelectValue placeholder="选择分辨率" />
                        </SelectTrigger>
                        <SelectContent>
                          {imageSizeOptions.map((item) => (
                            <SelectItem key={item} value={item}>
                              {formatImageSizeLabel(item)}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor={`image_frame_aspect_ratio_${provider.id}`}>首帧图宽高比</Label>
                      <Select
                        value={selectedFrameAspectRatio}
                        onValueChange={(value) => updateImageProvider(provider.id, { frame_aspect_ratio: value })}
                      >
                        <SelectTrigger id={`image_frame_aspect_ratio_${provider.id}`}>
                          <SelectValue placeholder="选择宽高比" />
                        </SelectTrigger>
                        <SelectContent>
                          {imageAspectRatioOptions.map((item) => (
                            <SelectItem key={item} value={item}>
                              {item}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor={`image_frame_size_${provider.id}`}>首帧图分辨率</Label>
                      <Select
                        value={selectedFrameSize}
                        onValueChange={(value) => updateImageProvider(provider.id, { frame_size: value })}
                      >
                        <SelectTrigger id={`image_frame_size_${provider.id}`}>
                          <SelectValue placeholder="选择分辨率" />
                        </SelectTrigger>
                        <SelectContent>
                          {imageSizeOptions.map((item) => (
                            <SelectItem key={item} value={item}>
                              {formatImageSizeLabel(item)}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                </div>
              </div>
            )
          })}

          <div className="border rounded-lg p-4 space-y-4 order-10">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2 flex-wrap">
                <div className="font-medium">可灵</div>
                <Badge variant="outline">内置</Badge>
                {hasKlingCredentials({
                  kling_access_key: formData.kling_access_key ?? settings?.kling_access_key,
                  kling_secret_key: formData.kling_secret_key ?? settings?.kling_secret_key,
                }) ? (
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
                onClick={() => handleOpenImageModelManager('kling')}
              >
                管理模型列表
              </Button>
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
                  value={formData.kling_base_url ?? settings?.kling_base_url ?? DEFAULT_KLING_BASE_URL}
                  onChange={(e) => updateField('kling_base_url', e.target.value)}
                  placeholder={DEFAULT_KLING_BASE_URL}
                />
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label htmlFor="image_kling_model">图像模型</Label>
                <Select
                  value={selectedKlingModel || undefined}
                  onValueChange={handleKlingModelChange}
                >
                  <SelectTrigger id="image_kling_model">
                    <SelectValue placeholder="选择模型" />
                  </SelectTrigger>
                  <SelectContent>
                    {klingEnabledModels.length > 0 ? (
                      klingEnabledModels.map((modelId) => (
                        <SelectItem key={modelId} value={modelId}>
                          {modelId}
                        </SelectItem>
                      ))
                    ) : (
                      <SelectItem value="__empty__" disabled>
                        请在「管理模型列表」中勾选模型
                      </SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="image_kling_reference_aspect_ratio">参考图宽高比</Label>
                <Select
                  value={klingReferenceAspectRatio}
                  onValueChange={(value) => updateField('image_kling_reference_aspect_ratio', value)}
                >
                  <SelectTrigger id="image_kling_reference_aspect_ratio">
                    <SelectValue placeholder="选择宽高比" />
                  </SelectTrigger>
                  <SelectContent>
                    {klingReferenceAspectRatioOptions.map((ratio) => (
                      <SelectItem key={ratio} value={ratio}>
                        {ratio}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="image_kling_frame_aspect_ratio">首帧图宽高比</Label>
                <Select
                  value={klingFrameAspectRatio}
                  onValueChange={(value) => updateField('image_kling_frame_aspect_ratio', value)}
                >
                  <SelectTrigger id="image_kling_frame_aspect_ratio">
                    <SelectValue placeholder="选择宽高比" />
                  </SelectTrigger>
                  <SelectContent>
                    {klingFrameAspectRatioOptions.map((ratio) => (
                      <SelectItem key={ratio} value={ratio}>
                        {ratio}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="image_kling_reference_size">参考图分辨率</Label>
                <Select
                  value={klingReferenceSize}
                  onValueChange={(value) => updateField('image_kling_reference_size', value)}
                >
                  <SelectTrigger id="image_kling_reference_size">
                    <SelectValue placeholder="选择分辨率" />
                  </SelectTrigger>
                  <SelectContent>
                    {klingReferenceSizeOptions.map((size) => (
                      <SelectItem key={size} value={size}>
                        {formatImageSizeLabel(size)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="image_kling_frame_size">首帧图分辨率</Label>
                <Select
                  value={klingFrameSize}
                  onValueChange={(value) => updateField('image_kling_frame_size', value)}
                >
                  <SelectTrigger id="image_kling_frame_size">
                    <SelectValue placeholder="选择分辨率" />
                  </SelectTrigger>
                  <SelectContent>
                    {klingFrameSizeOptions.map((size) => (
                      <SelectItem key={size} value={size}>
                        {formatImageSizeLabel(size)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>

          <div className="border rounded-lg p-4 space-y-4 order-11">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2 flex-wrap">
                <div className="font-medium">Vidu</div>
                <Badge variant="outline">内置</Badge>
                {(formData.vidu_api_key ?? settings?.vidu_api_key ?? '').trim() ? (
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
                onClick={() => handleOpenImageModelManager('vidu')}
              >
                管理模型列表
              </Button>
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
                  value={formData.vidu_base_url ?? settings?.vidu_base_url ?? DEFAULT_VIDU_BASE_URL}
                  onChange={(e) => updateField('vidu_base_url', e.target.value)}
                  placeholder={DEFAULT_VIDU_BASE_URL}
                />
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label htmlFor="image_vidu_model">模型</Label>
                <Select
                  value={selectedViduModel || undefined}
                  onValueChange={(value) => {
                    updateField('image_vidu_t2i_model', value)
                    updateField('image_vidu_i2i_model', value)
                  }}
                >
                  <SelectTrigger id="image_vidu_model">
                    <SelectValue placeholder="选择模型" />
                  </SelectTrigger>
                  <SelectContent>
                    {viduEnabledModels.length > 0 ? (
                      viduEnabledModels.map((modelId) => (
                        <SelectItem key={modelId} value={modelId}>
                          {modelId}
                        </SelectItem>
                      ))
                    ) : (
                      <SelectItem value="__empty__" disabled>
                        请在「管理模型列表」中勾选模型
                      </SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="image_vidu_reference_aspect_ratio">参考图宽高比</Label>
                <Select
                  value={selectedViduReferenceAspectRatio}
                  onValueChange={(value) => updateField('image_vidu_reference_aspect_ratio', value)}
                >
                  <SelectTrigger id="image_vidu_reference_aspect_ratio">
                    <SelectValue placeholder="选择宽高比" />
                  </SelectTrigger>
                  <SelectContent>
                    {VIDU_IMAGE_ASPECT_RATIO_OPTIONS.map((ratio) => (
                      <SelectItem key={ratio} value={ratio}>
                        {ratio}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="image_vidu_frame_aspect_ratio">首帧图宽高比</Label>
                <Select
                  value={selectedViduFrameAspectRatio}
                  onValueChange={(value) => updateField('image_vidu_frame_aspect_ratio', value)}
                >
                  <SelectTrigger id="image_vidu_frame_aspect_ratio">
                    <SelectValue placeholder="选择宽高比" />
                  </SelectTrigger>
                  <SelectContent>
                    {VIDU_IMAGE_ASPECT_RATIO_OPTIONS.map((ratio) => (
                      <SelectItem key={ratio} value={ratio}>
                        {ratio}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="image_vidu_reference_size">参考图分辨率</Label>
                <Select
                  value={selectedViduReferenceSize}
                  onValueChange={(value) => updateField('image_vidu_reference_size', value)}
                >
                  <SelectTrigger id="image_vidu_reference_size">
                    <SelectValue placeholder="选择分辨率" />
                  </SelectTrigger>
                  <SelectContent>
                    {VIDU_IMAGE_SIZE_OPTIONS.map((size) => (
                      <SelectItem key={size} value={size}>
                        {size}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="image_vidu_frame_size">首帧图分辨率</Label>
                <Select
                  value={selectedViduFrameSize}
                  onValueChange={(value) => updateField('image_vidu_frame_size', value)}
                >
                  <SelectTrigger id="image_vidu_frame_size">
                    <SelectValue placeholder="选择分辨率" />
                  </SelectTrigger>
                  <SelectContent>
                    {VIDU_IMAGE_SIZE_OPTIONS.map((size) => (
                      <SelectItem key={size} value={size}>
                        {size}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>

          <div className="border rounded-lg p-4 space-y-4 order-12">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2 flex-wrap">
                <div className="font-medium">MiniMax</div>
                <Badge variant="outline">内置</Badge>
                {(formData.minimax_api_key ?? settings?.minimax_api_key ?? '').trim() ? (
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
                onClick={() => handleOpenImageModelManager('minimax')}
              >
                管理模型列表
              </Button>
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
                  value={formData.minimax_base_url ?? settings?.minimax_base_url ?? DEFAULT_MINIMAX_BASE_URL}
                  onChange={(e) => updateField('minimax_base_url', e.target.value)}
                  placeholder={DEFAULT_MINIMAX_BASE_URL}
                />
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label htmlFor="image_minimax_model">模型</Label>
                <Select
                  value={selectedMinimaxModel || undefined}
                  onValueChange={(value) => updateField('image_minimax_model', value)}
                >
                  <SelectTrigger id="image_minimax_model">
                    <SelectValue placeholder="选择模型" />
                  </SelectTrigger>
                  <SelectContent>
                    {minimaxEnabledModels.length > 0 ? (
                      minimaxEnabledModels.map((modelId) => (
                        <SelectItem key={modelId} value={modelId}>
                          {modelId}
                        </SelectItem>
                      ))
                    ) : (
                      <SelectItem value="__empty__" disabled>
                        请在「管理模型列表」中勾选模型
                      </SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="image_minimax_reference_aspect_ratio">参考图宽高比</Label>
                <Select
                  value={selectedMinimaxReferenceAspectRatio}
                  onValueChange={(value) => updateField('image_minimax_reference_aspect_ratio', value)}
                >
                  <SelectTrigger id="image_minimax_reference_aspect_ratio">
                    <SelectValue placeholder="选择宽高比" />
                  </SelectTrigger>
                  <SelectContent>
                    {MINIMAX_IMAGE_ASPECT_RATIO_OPTIONS.map((ratio) => (
                      <SelectItem key={ratio} value={ratio}>
                        {ratio}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="image_minimax_frame_aspect_ratio">首帧图宽高比</Label>
                <Select
                  value={selectedMinimaxFrameAspectRatio}
                  onValueChange={(value) => updateField('image_minimax_frame_aspect_ratio', value)}
                >
                  <SelectTrigger id="image_minimax_frame_aspect_ratio">
                    <SelectValue placeholder="选择宽高比" />
                  </SelectTrigger>
                  <SelectContent>
                    {MINIMAX_IMAGE_ASPECT_RATIO_OPTIONS.map((ratio) => (
                      <SelectItem key={ratio} value={ratio}>
                        {ratio}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="image_minimax_reference_size">参考图分辨率</Label>
                <Select
                  value={selectedMinimaxReferenceSize}
                  onValueChange={(value) => updateField('image_minimax_reference_size', value)}
                >
                  <SelectTrigger id="image_minimax_reference_size">
                    <SelectValue placeholder="选择分辨率" />
                  </SelectTrigger>
                  <SelectContent>
                    {MINIMAX_IMAGE_SIZE_OPTIONS.map((size) => (
                      <SelectItem key={size} value={size}>
                        {size}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="image_minimax_frame_size">首帧图分辨率</Label>
                <Select
                  value={selectedMinimaxFrameSize}
                  onValueChange={(value) => updateField('image_minimax_frame_size', value)}
                >
                  <SelectTrigger id="image_minimax_frame_size">
                    <SelectValue placeholder="选择分辨率" />
                  </SelectTrigger>
                  <SelectContent>
                    {MINIMAX_IMAGE_SIZE_OPTIONS.map((size) => (
                      <SelectItem key={size} value={size}>
                        {size}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>

          {showWan2gpCard && (
            <div className="border rounded-lg p-4 space-y-4 order-first">
            <div className="flex items-start justify-between gap-3">
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
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="shrink-0"
                onClick={() => handleOpenImageModelManager('wan2gp')}
              >
                管理模型列表
              </Button>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="image_wan2gp_preset">文生图模型 (t2i)</Label>
                  <Select
                    value={selectedWan2gpT2iPreset || undefined}
                    onValueChange={handleWan2gpT2iPresetChange}
                  >
                    <SelectTrigger id="image_wan2gp_preset">
                      <SelectValue placeholder="选择预设" />
                    </SelectTrigger>
                    <SelectContent>
                      {effectiveWan2gpT2iCatalog.length > 0 ? (
                        effectiveWan2gpT2iCatalog.map((preset) => (
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
                  {selectedWan2gpT2iPresetConfig?.description && (
                    <p className="text-xs text-muted-foreground">
                      {selectedWan2gpT2iPresetConfig.description}
                    </p>
                  )}
                  {selectedWan2gpT2iPresetConfig && (
                    <p className="text-xs text-amber-600">
                      {getWan2gpPromptLanguageHint(
                        '该模型',
                        selectedWan2gpT2iPresetConfig.prompt_language_preference,
                        selectedWan2gpT2iPresetConfig.supports_chinese
                      )}
                    </p>
                  )}
                </div>
                <div className="space-y-2">
                  <Label htmlFor="image_wan2gp_preset_i2i">图生图模型 (i2i)</Label>
                  <Select
                    value={selectedWan2gpI2iPreset || undefined}
                    onValueChange={handleWan2gpI2iPresetChange}
                  >
                    <SelectTrigger id="image_wan2gp_preset_i2i">
                      <SelectValue placeholder="选择预设" />
                    </SelectTrigger>
                    <SelectContent>
                      {effectiveWan2gpI2iCatalog.length > 0 ? (
                        effectiveWan2gpI2iCatalog.map((preset) => (
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
                  {selectedWan2gpI2iPresetConfig?.description && (
                    <p className="text-xs text-muted-foreground">
                      {selectedWan2gpI2iPresetConfig.description}
                    </p>
                  )}
                  {selectedWan2gpI2iPresetConfig && (
                    <p className="text-xs text-amber-600">
                      {getWan2gpPromptLanguageHint(
                        '该模型',
                        selectedWan2gpI2iPresetConfig.prompt_language_preference,
                        selectedWan2gpI2iPresetConfig.supports_chinese
                      )}
                    </p>
                  )}
                  {selectedWan2gpI2iPresetConfig?.id === WAN2GP_DREAMOMNI2_PRESET_ID && (
                    <p className="text-xs text-amber-600">
                      提示：多模态前处理链路，编码较慢。
                    </p>
                  )}
                </div>
                <div className="space-y-2">
                  <Label htmlFor="image_wan2gp_reference_resolution_tier">参考图分辨率档位</Label>
                  <Select
                    value={selectedWan2gpReferenceResolutionTier}
                    onValueChange={handleWan2gpReferenceResolutionTierChange}
                  >
                    <SelectTrigger id="image_wan2gp_reference_resolution_tier">
                      <SelectValue placeholder="选择档位" />
                    </SelectTrigger>
                    <SelectContent>
                      {wan2gpImageResolutionTiers.map((tier) => (
                        <SelectItem key={tier} value={tier}>
                          {tier}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="image_wan2gp_reference_resolution">参考图宽高比</Label>
                  <Select
                    value={selectedWan2gpReferenceResolutionValue}
                    onValueChange={(v) => {
                      updateField('image_wan2gp_reference_resolution', v)
                      const tier = wan2gpImageResolutionChoices.find((choice) => choice.value === v)?.tier
                      if (tier) {
                        setWan2gpReferenceResolutionTierOverride(tier)
                      }
                    }}
                  >
                    <SelectTrigger id="image_wan2gp_reference_resolution">
                      <SelectValue placeholder="选择宽高比" />
                    </SelectTrigger>
                    <SelectContent>
                      {resolvedReferenceTierChoices.map((item) => (
                        <SelectItem key={item.value} value={item.value}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="image_wan2gp_frame_resolution_tier">首帧图分辨率档位</Label>
                  <Select
                    value={selectedWan2gpFrameResolutionTier}
                    onValueChange={handleWan2gpFrameResolutionTierChange}
                  >
                    <SelectTrigger id="image_wan2gp_frame_resolution_tier">
                      <SelectValue placeholder="选择档位" />
                    </SelectTrigger>
                    <SelectContent>
                      {wan2gpImageResolutionTiers.map((tier) => (
                        <SelectItem key={tier} value={tier}>
                          {tier}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="image_wan2gp_frame_resolution">首帧图宽高比</Label>
                  <Select
                    value={selectedWan2gpFrameResolutionValue}
                    onValueChange={(v) => {
                      updateField('image_wan2gp_frame_resolution', v)
                      const tier = wan2gpImageResolutionChoices.find((choice) => choice.value === v)?.tier
                      if (tier) {
                        setWan2gpFrameResolutionTierOverride(tier)
                      }
                    }}
                  >
                    <SelectTrigger id="image_wan2gp_frame_resolution">
                      <SelectValue placeholder="选择宽高比" />
                    </SelectTrigger>
                    <SelectContent>
                      {resolvedFrameTierChoices.map((item) => (
                        <SelectItem key={item.value} value={item.value}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                {!settings?.wan2gp_available && (
                  <p className="text-xs text-muted-foreground md:col-span-2">
                    当前 Wan2GP 未就绪，请先在上方全局配置中设置有效路径。
                  </p>
                )}
            </div>
            </div>
          )}
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => setIsCreatingCustomImageProvider(true)}
        >
          添加自定义供应商
        </Button>
        <ModelManagerDialog
          open={imageModelManager.isOpen}
          onOpenChange={imageModelManager.onOpenChange}
          selectedCount={imageModelManagerEnabledIds.length}
          totalCount={imageModelManagerCatalogIds.length}
          rows={imageModelManagerCatalogIds.map((modelId) => {
            const modelLabel = imageModelManagerAdapter?.getModelLabel(modelId) || modelId
            return {
              id: modelId,
              label: modelLabel,
              tags: imageModelManagerAdapter?.getModelTags(modelId) ?? [],
              checked: imageModelManagerEnabledIds.includes(modelId),
              connectivity: imageModelManager.getModelConnectivity(modelId),
              canTest: Boolean(imageModelManagerAdapter),
              onTest: () => void handleTestImageModel(modelId),
              onCheckedChange: (checked) => handleImageModelEnabledChange(modelId, checked),
            }
          })}
          allSelected={imageModelManagerAllSelected}
          onToggleAll={handleToggleAllImageModels}
          showRefreshButton={canRefreshImageModelManagerCatalog}
          onRefresh={handleRefreshCurrentImageProviderModels}
          isRefreshing={isLoadingImageModels}
          refreshDisabled={!imageModelManagerAdapter}
          emptyText={canRefreshImageModelManagerCatalog
            ? '暂无模型，请检查 API 配置后点击「刷新模型列表」。'
            : '暂无模型。'}
        />
        <Dialog open={isCreatingCustomImageProvider} onOpenChange={setIsCreatingCustomImageProvider}>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>添加自定义供应商</DialogTitle>
              <DialogDescription>创建一个自定义 Image 供应商卡片，默认提供 gemini-3.1-flash-image-preview 与 gemini-3-pro-image-preview。</DialogDescription>
            </DialogHeader>
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="custom_image_name">供应商名称</Label>
                <Input
                  id="custom_image_name"
                  value={customImageProviderName}
                  onChange={(e) => setCustomImageProviderName(e.target.value)}
                  placeholder="例如：Antigravity"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="custom_image_type">供应商类型</Label>
                <Select
                  value={customImageProviderType}
                  onValueChange={(value) => setCustomImageProviderType(value as ImageProviderType)}
                >
                  <SelectTrigger id="custom_image_type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {CUSTOM_IMAGE_PROVIDER_TYPES.map((item) => (
                      <SelectItem key={item.value} value={item.value}>
                        {item.label} ({item.endpoint})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex justify-end">
                <Button type="button" onClick={handleAddCustomImageProvider}>创建</Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  )
}
