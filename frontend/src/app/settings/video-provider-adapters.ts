import type { Settings, SettingsUpdate, Wan2gpVideoPreset } from '@/types/settings'

export type VideoProviderId = 'volcengine_seedance' | 'wan2gp'

export interface VideoModelTestPayload {
  providerId: VideoProviderId
  model: string
  apiKey?: string
  baseUrl?: string
  wan2gpPath?: string
}

interface VideoProviderAdapter {
  getCatalogIds: () => string[]
  getSelectedIds: (catalogIds: string[]) => string[]
  setEnabledIds: (nextEnabled: string[]) => void
  getModelLabel: (modelId: string) => string
  getModelTags: (modelId: string) => string[]
  buildTestPayload: (modelId: string) => VideoModelTestPayload
}

export type VideoProviderAdapters = Record<VideoProviderId, VideoProviderAdapter>

type UpdateField = <K extends keyof SettingsUpdate>(key: K, value: SettingsUpdate[K]) => void

interface CreateVideoProviderAdaptersParams {
  normalizeModelIds: (models: string[]) => string[]
  resolveEnabledModelIds: (rawEnabled: string[] | null | undefined, catalog: string[]) => string[]
  updateField: UpdateField
  formData: SettingsUpdate
  settings?: Settings
  rawVideoSeedanceEnabledModels: string[] | null | undefined
  rawVideoWan2gpEnabledModels: string[] | null | undefined
  seedanceModelIds: string[]
  seedanceModelNameMap: Map<string, string>
  seedanceModelTagMap: Map<string, string[]>
  wan2gpVideoT2vPresets: Wan2gpVideoPreset[]
  wan2gpVideoI2vPresets: Wan2gpVideoPreset[]
  wan2gpVideoPresetNameMap: Map<string, string>
  currentVideoSeedanceModel: string
  currentVideoWan2gpT2vPreset: string
  currentVideoWan2gpI2vPreset: string
  setWan2gpVideoResolutionTierOverride: (value: string | null) => void
  seedanceDefaultBaseUrl: string
}

export function createVideoProviderAdapters(
  params: CreateVideoProviderAdaptersParams
): VideoProviderAdapters {
  const {
    normalizeModelIds,
    resolveEnabledModelIds,
    updateField,
    formData,
    settings,
    rawVideoSeedanceEnabledModels,
    rawVideoWan2gpEnabledModels,
    seedanceModelIds,
    seedanceModelNameMap,
    seedanceModelTagMap,
    wan2gpVideoT2vPresets,
    wan2gpVideoI2vPresets,
    wan2gpVideoPresetNameMap,
    currentVideoSeedanceModel,
    currentVideoWan2gpT2vPreset,
    currentVideoWan2gpI2vPreset,
    setWan2gpVideoResolutionTierOverride,
    seedanceDefaultBaseUrl,
  } = params

  return {
    volcengine_seedance: {
      getCatalogIds: () => normalizeModelIds([
        ...seedanceModelIds,
        currentVideoSeedanceModel,
      ]),
      getSelectedIds: (catalogIds) => resolveEnabledModelIds(rawVideoSeedanceEnabledModels, catalogIds),
      setEnabledIds: (nextEnabled) => {
        updateField('video_seedance_enabled_models', nextEnabled)
        const current = formData.video_seedance_model ?? settings?.video_seedance_model ?? ''
        if (!nextEnabled.includes(current)) {
          updateField('video_seedance_model', nextEnabled[0] ?? '')
        }
      },
      getModelLabel: (modelId) => seedanceModelNameMap.get(modelId) || modelId,
      getModelTags: (modelId) => seedanceModelTagMap.get(modelId) ?? [],
      buildTestPayload: (modelId) => ({
        providerId: 'volcengine_seedance',
        model: modelId,
        apiKey: formData.video_seedance_api_key ?? settings?.video_seedance_api_key ?? '',
        baseUrl: formData.video_seedance_base_url ?? settings?.video_seedance_base_url ?? seedanceDefaultBaseUrl,
      }),
    },
    wan2gp: {
      getCatalogIds: () => normalizeModelIds([
        ...wan2gpVideoT2vPresets.map((item) => item.id),
        ...wan2gpVideoI2vPresets.map((item) => item.id),
        currentVideoWan2gpT2vPreset,
        currentVideoWan2gpI2vPreset,
      ]),
      getSelectedIds: (catalogIds) => resolveEnabledModelIds(rawVideoWan2gpEnabledModels, catalogIds),
      setEnabledIds: (nextEnabled) => {
        updateField('video_wan2gp_enabled_models', nextEnabled)
        const nextEnabledSet = new Set(nextEnabled)
        const nextT2vCatalog = wan2gpVideoT2vPresets.filter((preset) => nextEnabledSet.has(preset.id))
        const nextI2vCatalog = wan2gpVideoI2vPresets.filter((preset) => nextEnabledSet.has(preset.id))

        const currentT2v = formData.video_wan2gp_t2v_preset ?? settings?.video_wan2gp_t2v_preset ?? ''
        if (!nextT2vCatalog.some((item) => item.id === currentT2v)) {
          const nextT2v = nextT2vCatalog[0]?.id ?? ''
          setWan2gpVideoResolutionTierOverride(null)
          updateField('video_wan2gp_t2v_preset', nextT2v)
          const preset = nextT2vCatalog[0]
          if (preset) {
            const options = preset.supported_resolutions?.length
              ? preset.supported_resolutions
              : [preset.default_resolution]
            const currentResolution = formData.video_wan2gp_resolution ?? settings?.video_wan2gp_resolution
            if (!currentResolution || !options.includes(currentResolution)) {
              updateField('video_wan2gp_resolution', preset.default_resolution || options[0])
            }
          }
        }

        const currentI2v = formData.video_wan2gp_i2v_preset ?? settings?.video_wan2gp_i2v_preset ?? ''
        if (!nextI2vCatalog.some((item) => item.id === currentI2v)) {
          updateField('video_wan2gp_i2v_preset', nextI2vCatalog[0]?.id ?? '')
        }
      },
      getModelLabel: (modelId) => wan2gpVideoPresetNameMap.get(modelId) || modelId,
      getModelTags: (modelId) => {
        const tags: string[] = []
        if (wan2gpVideoT2vPresets.some((preset) => preset.id === modelId)) {
          tags.push('t2v')
        }
        if (wan2gpVideoI2vPresets.some((preset) => preset.id === modelId)) {
          tags.push('i2v')
        }
        return tags
      },
      buildTestPayload: (modelId) => ({
        providerId: 'wan2gp',
        model: modelId,
        wan2gpPath: formData.wan2gp_path ?? settings?.wan2gp_path ?? '',
      }),
    },
  }
}

export function isVideoProviderId(value: string | null | undefined): value is VideoProviderId {
  return value === 'volcengine_seedance' || value === 'wan2gp'
}
