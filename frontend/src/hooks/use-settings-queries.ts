'use client'

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api-client'
import { sortVoiceLibraryItems } from '@/lib/catalog-sort'
import { queryKeys } from '@/lib/query-keys'

interface UseSettingsBundleOptions {
  includeWan2gpVideoPresets?: boolean
  includeWan2gpAudioPresets?: boolean
  includeActiveVoiceLibrary?: boolean
}

export function useSettingsQuery() {
  return useQuery({
    queryKey: queryKeys.settings.root,
    queryFn: () => api.settings.get(),
    staleTime: 30_000,
  })
}

export function useSettingsProvidersQuery() {
  return useQuery({
    queryKey: queryKeys.settings.providers,
    queryFn: () => api.settings.fetchProviders(),
  })
}

export function useSettingsEdgeVoicesQuery() {
  return useSettingsVoicesQuery('edge_tts')
}

export function useSettingsVoicesQuery(
  provider: string,
  enabled = true,
  options?: { modelName?: string }
) {
  const modelName = options?.modelName
  return useQuery({
    queryKey: queryKeys.settings.voices(provider, modelName),
    queryFn: () => api.settings.fetchVoices(provider, { modelName }),
    enabled,
  })
}

export function useWan2gpImagePresetsQuery() {
  return useQuery({
    queryKey: queryKeys.settings.wan2gpImagePresets,
    queryFn: () => api.settings.fetchWan2gpImagePresets(),
    staleTime: 5 * 60 * 1000,
  })
}

export function useWan2gpVideoPresetsQuery(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.settings.wan2gpVideoPresets,
    queryFn: () => api.settings.fetchWan2gpVideoPresets(),
    staleTime: 5 * 60 * 1000,
    enabled,
  })
}

export function useWan2gpAudioPresetsQuery(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.settings.wan2gpAudioPresets,
    queryFn: () => api.settings.fetchWan2gpAudioPresets(),
    staleTime: 5 * 60 * 1000,
    enabled,
  })
}

export function useActiveVoiceLibraryQuery(enabled = true) {
  return useQuery({
    queryKey: queryKeys.voiceLibrary.active,
    queryFn: () => api.voiceLibrary.list({ enabledOnly: true, withAudioOnly: true }),
    staleTime: 60 * 1000,
    enabled,
  })
}

export function useVoiceLibraryQuery() {
  return useQuery({
    queryKey: queryKeys.voiceLibrary.root,
    queryFn: () => api.voiceLibrary.list(),
    staleTime: 60 * 1000,
  })
}

export function useSettingsBundle(options?: UseSettingsBundleOptions) {
  const {
    includeWan2gpVideoPresets = false,
    includeWan2gpAudioPresets = false,
    includeActiveVoiceLibrary = false,
  } = options || {}

  const settingsQuery = useSettingsQuery()
  const wan2gpImagePresetQuery = useWan2gpImagePresetsQuery()
  const wan2gpVideoPresetQuery = useWan2gpVideoPresetsQuery(
    includeWan2gpVideoPresets
  )
  const wan2gpAudioPresetQuery = useWan2gpAudioPresetsQuery(
    includeWan2gpAudioPresets
  )
  const activeVoiceLibraryQuery = useActiveVoiceLibraryQuery(includeActiveVoiceLibrary)

  const activeVoiceLibraryItems = useMemo(() => {
    if (!includeActiveVoiceLibrary) return []
    return sortVoiceLibraryItems(activeVoiceLibraryQuery.data?.items ?? [])
  }, [activeVoiceLibraryQuery.data?.items, includeActiveVoiceLibrary])

  return {
    settingsQuery,
    wan2gpImagePresetQuery,
    wan2gpVideoPresetQuery,
    wan2gpAudioPresetQuery,
    activeVoiceLibraryQuery,
    settings: settingsQuery.data,
    isSettingsLoading: settingsQuery.isPending,
    wan2gpImagePresets: wan2gpImagePresetQuery.data?.presets ?? [],
    wan2gpVideoPresetData: wan2gpVideoPresetQuery.data,
    wan2gpAudioPresets: wan2gpAudioPresetQuery.data?.presets ?? [],
    activeVoiceLibraryItems,
  }
}
