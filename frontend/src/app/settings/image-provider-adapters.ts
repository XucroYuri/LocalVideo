import type {
  ImageProviderConfig,
  Settings,
  SettingsUpdate,
  Wan2gpImagePreset,
} from '@/types/settings'

export interface ImageModelTestPayload {
  providerId: string
  model: string
}

export interface ImageProviderAdapter {
  providerId: string
  canRefreshCatalog: boolean
  getCatalogIds: () => string[]
  getSelectedIds: (catalogIds: string[]) => string[]
  setEnabledIds: (nextEnabled: string[]) => void
  ensureCatalogInitialized: () => void
  getModelLabel: (modelId: string) => string
  getModelTags: (modelId: string) => string[]
  buildTestPayload: (modelId: string) => ImageModelTestPayload
}

export type ImageProviderAdapters = Record<string, ImageProviderAdapter>

type UpdateImageProvider = (providerId: string, patch: Partial<ImageProviderConfig>) => void
type UpdateField = <K extends keyof SettingsUpdate>(key: K, value: SettingsUpdate[K]) => void

interface CreateImageProviderAdaptersParams {
  imageProviders: ImageProviderConfig[]
  normalizeModelIds: (models: string[]) => string[]
  resolveEnabledModelIds: (rawEnabled: string[] | null | undefined, catalog: string[]) => string[]
  updateImageProvider: UpdateImageProvider
  updateField: UpdateField
  formData: SettingsUpdate
  settings?: Settings
  defaultImageModel: string
  defaultCustomImageModels: string[]
  rawWan2gpEnabledModels: string[] | null | undefined
  wan2gpPresets: Wan2gpImagePreset[]
  wan2gpT2iPresets: Wan2gpImagePreset[]
  wan2gpI2iPresets: Wan2gpImagePreset[]
  wan2gpPresetNameMap: Map<string, string>
}

function supportsI2iForOnlineImageModel(modelId: string): boolean {
  const normalized = modelId.trim().toLowerCase()
  if (!normalized) return false
  if (normalized === 'doubao-seedream-5.0') return true
  if (normalized === 'doubao-seedream-4.5') return true
  if (normalized === 'doubao-seedream-4.0') return true
  if (normalized.startsWith('gemini-') && normalized.endsWith('-image-preview')) return true
  return false
}

const KLING_IMAGE_MODEL_OPTIONS = ['kling-v3', 'kling-v3-omni']
const VIDU_IMAGE_MODEL_OPTIONS = ['viduq2']
const MINIMAX_IMAGE_MODEL_OPTIONS = ['image-01', 'image-01-live']

export function createImageProviderAdapters(
  params: CreateImageProviderAdaptersParams
): ImageProviderAdapters {
  const {
    imageProviders,
    normalizeModelIds,
    resolveEnabledModelIds,
    updateImageProvider,
    updateField,
    formData,
    settings,
    defaultImageModel,
    defaultCustomImageModels,
    rawWan2gpEnabledModels,
    wan2gpPresets,
    wan2gpT2iPresets,
    wan2gpI2iPresets,
    wan2gpPresetNameMap,
  } = params

  const adapters: ImageProviderAdapters = {
    wan2gp: {
      providerId: 'wan2gp',
      canRefreshCatalog: false,
      getCatalogIds: () => normalizeModelIds(wan2gpPresets.map((item) => item.id)),
      getSelectedIds: (catalogIds) => resolveEnabledModelIds(rawWan2gpEnabledModels, catalogIds),
      setEnabledIds: (nextEnabled) => {
        updateField('image_wan2gp_enabled_models', nextEnabled)
        const nextEnabledSet = new Set(nextEnabled)
        const nextT2iCatalog = wan2gpT2iPresets.filter((preset) => nextEnabledSet.has(preset.id))
        const nextI2iCatalog = wan2gpI2iPresets.filter((preset) => nextEnabledSet.has(preset.id))
        const currentT2i = formData.image_wan2gp_preset ?? settings?.image_wan2gp_preset ?? ''
        if (!nextT2iCatalog.some((item) => item.id === currentT2i)) {
          updateField('image_wan2gp_preset', nextT2iCatalog[0]?.id ?? '')
        }
        const currentI2i = formData.image_wan2gp_preset_i2i ?? settings?.image_wan2gp_preset_i2i ?? ''
        if (!nextI2iCatalog.some((item) => item.id === currentI2i)) {
          updateField('image_wan2gp_preset_i2i', nextI2iCatalog[0]?.id ?? '')
        }
      },
      ensureCatalogInitialized: () => { /* no-op */ },
      getModelLabel: (modelId) => wan2gpPresetNameMap.get(modelId) || modelId,
      getModelTags: (modelId) => {
        const tags: string[] = []
        if (wan2gpT2iPresets.some((preset) => preset.id === modelId)) {
          tags.push('t2i')
        }
        if (wan2gpI2iPresets.some((preset) => preset.id === modelId)) {
          tags.push('i2i')
        }
        return tags
      },
      buildTestPayload: (modelId) => ({
        providerId: 'wan2gp',
        model: modelId,
      }),
    },
    kling: {
      providerId: 'kling',
      canRefreshCatalog: false,
      getCatalogIds: () => normalizeModelIds([
        ...KLING_IMAGE_MODEL_OPTIONS,
        formData.image_kling_t2i_model ?? settings?.image_kling_t2i_model ?? 'kling-v3',
        formData.image_kling_i2i_model ?? settings?.image_kling_i2i_model ?? 'kling-v3',
      ]),
      getSelectedIds: (catalogIds) => resolveEnabledModelIds(
        formData.image_kling_enabled_models ?? settings?.image_kling_enabled_models,
        catalogIds
      ),
      setEnabledIds: (nextEnabled) => {
        updateField('image_kling_enabled_models', nextEnabled)
        const currentT2i = String(
          formData.image_kling_t2i_model ?? settings?.image_kling_t2i_model ?? 'kling-v3'
        ).trim() || 'kling-v3'
        const currentI2i = String(
          formData.image_kling_i2i_model ?? settings?.image_kling_i2i_model ?? 'kling-v3'
        ).trim() || 'kling-v3'
        if (!nextEnabled.includes(currentT2i)) {
          updateField('image_kling_t2i_model', nextEnabled[0] ?? 'kling-v3')
        }
        if (!nextEnabled.includes(currentI2i)) {
          updateField('image_kling_i2i_model', nextEnabled[0] ?? 'kling-v3')
        }
      },
      ensureCatalogInitialized: () => { /* no-op */ },
      getModelLabel: (modelId) => modelId,
      getModelTags: () => ['t2i', 'i2i'],
      buildTestPayload: (modelId) => ({
        providerId: 'kling',
        model: modelId,
      }),
    },
    vidu: {
      providerId: 'vidu',
      canRefreshCatalog: false,
      getCatalogIds: () => normalizeModelIds([
        ...VIDU_IMAGE_MODEL_OPTIONS,
        formData.image_vidu_t2i_model ?? settings?.image_vidu_t2i_model ?? 'viduq2',
        formData.image_vidu_i2i_model ?? settings?.image_vidu_i2i_model ?? 'viduq2',
      ]),
      getSelectedIds: (catalogIds) => resolveEnabledModelIds(
        formData.image_vidu_enabled_models ?? settings?.image_vidu_enabled_models,
        catalogIds
      ),
      setEnabledIds: (nextEnabled) => {
        updateField('image_vidu_enabled_models', nextEnabled)
        const currentT2i = String(
          formData.image_vidu_t2i_model ?? settings?.image_vidu_t2i_model ?? 'viduq2'
        ).trim() || 'viduq2'
        const currentI2i = String(
          formData.image_vidu_i2i_model ?? settings?.image_vidu_i2i_model ?? 'viduq2'
        ).trim() || 'viduq2'
        if (!nextEnabled.includes(currentT2i)) {
          updateField('image_vidu_t2i_model', nextEnabled[0] ?? 'viduq2')
        }
        if (!nextEnabled.includes(currentI2i)) {
          updateField('image_vidu_i2i_model', nextEnabled[0] ?? 'viduq2')
        }
      },
      ensureCatalogInitialized: () => { /* no-op */ },
      getModelLabel: (modelId) => modelId,
      getModelTags: () => ['t2i', 'i2i'],
      buildTestPayload: (modelId) => ({
        providerId: 'vidu',
        model: modelId,
      }),
    },
    minimax: {
      providerId: 'minimax',
      canRefreshCatalog: false,
      getCatalogIds: () => normalizeModelIds([
        ...MINIMAX_IMAGE_MODEL_OPTIONS,
        formData.image_minimax_model ?? settings?.image_minimax_model ?? 'image-01',
      ]),
      getSelectedIds: (catalogIds) => resolveEnabledModelIds(
        formData.image_minimax_enabled_models ?? settings?.image_minimax_enabled_models,
        catalogIds
      ),
      setEnabledIds: (nextEnabled) => {
        updateField('image_minimax_enabled_models', nextEnabled)
        const current = String(
          formData.image_minimax_model ?? settings?.image_minimax_model ?? 'image-01'
        ).trim() || 'image-01'
        if (!nextEnabled.includes(current)) {
          updateField('image_minimax_model', nextEnabled[0] ?? 'image-01')
        }
      },
      ensureCatalogInitialized: () => { /* no-op */ },
      getModelLabel: (modelId) => modelId,
      getModelTags: () => ['t2i', 'i2i'],
      buildTestPayload: (modelId) => ({
        providerId: 'minimax',
        model: modelId,
      }),
    },
  }

  for (const provider of imageProviders) {
    adapters[provider.id] = {
      providerId: provider.id,
      canRefreshCatalog: false,
      getCatalogIds: () => {
        if (provider.is_builtin) {
          return normalizeModelIds(provider.catalog_models ?? [])
        }
        const existingCatalog = normalizeModelIds(provider.catalog_models ?? [])
        return existingCatalog.length > 0
          ? existingCatalog
          : normalizeModelIds(defaultCustomImageModels)
      },
      getSelectedIds: (catalogIds) => resolveEnabledModelIds(provider.enabled_models, catalogIds),
      setEnabledIds: (nextEnabled) => {
        updateImageProvider(provider.id, { enabled_models: normalizeModelIds(nextEnabled) })
      },
      ensureCatalogInitialized: () => {
        if (provider.is_builtin) return
        const catalogModels = normalizeModelIds(
          (provider.catalog_models ?? []).length > 0
            ? (provider.catalog_models ?? [])
            : defaultCustomImageModels
        )
        const enabledModels = resolveEnabledModelIds(provider.enabled_models, catalogModels)
        const nextEnabledModels = enabledModels.length > 0
          ? enabledModels
          : catalogModels
        const defaultModel = nextEnabledModels.includes(provider.default_model)
          ? provider.default_model
          : (nextEnabledModels[0] || defaultImageModel)
        updateImageProvider(provider.id, {
          catalog_models: catalogModels,
          enabled_models: nextEnabledModels,
          default_model: defaultModel,
        })
      },
      getModelLabel: (modelId) => modelId,
      getModelTags: (modelId) => (supportsI2iForOnlineImageModel(modelId) ? ['t2i', 'i2i'] : ['t2i']),
      buildTestPayload: (modelId) => ({
        providerId: provider.id,
        model: modelId,
      }),
    }
  }

  return adapters
}
