import { useCallback, useEffect, useState } from 'react'

import { api } from '@/lib/api-client'
import type { VoiceInfo } from '@/types/settings'
import { loadCachedVoices, saveCachedVoices } from '@/app/settings/settings-audio-preview-helpers'

const FALLBACK_VOICES: VoiceInfo[] = [
  { id: 'zh-CN-YunjianNeural', name: '云健 (男声)', locale: 'zh-CN' },
  { id: 'zh-CN-YunxiNeural', name: '云希 (男声)', locale: 'zh-CN' },
  { id: 'zh-CN-XiaoxiaoNeural', name: '晓晓 (女声)', locale: 'zh-CN' },
  { id: 'zh-CN-XiaoyiNeural', name: '晓伊 (女声)', locale: 'zh-CN' },
]

export function useSettingsEdgeVoices() {
  const [availableVoices, setAvailableVoices] = useState<VoiceInfo[]>([])
  const [isLoadingVoices, setIsLoadingVoices] = useState(false)
  const [voicesInitialized, setVoicesInitialized] = useState(false)

  const fetchVoices = useCallback(async () => {
    setIsLoadingVoices(true)
    try {
      const response = await api.settings.fetchVoices('edge_tts')
      if (response.voices.length > 0) {
        setAvailableVoices(response.voices)
        saveCachedVoices(response.voices, 'edge_tts')
      }
    } catch {
      setAvailableVoices(FALLBACK_VOICES)
    } finally {
      setIsLoadingVoices(false)
    }
  }, [])

  useEffect(() => {
    if (voicesInitialized) return
    const cached = loadCachedVoices('edge_tts')
    if (cached.length > 0) {
      setAvailableVoices(cached)
    } else {
      void fetchVoices()
    }
    setVoicesInitialized(true)
  }, [fetchVoices, voicesInitialized])

  return {
    availableVoices,
    isLoadingVoices,
    fetchVoices,
  }
}
