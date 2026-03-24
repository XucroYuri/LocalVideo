import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { api } from '@/lib/api-client'
import { resolveApiResourceUrl } from '@/lib/media-url'
import {
  AUDIO_PREVIEW_STEPS_BY_PROVIDER,
  type AudioPreviewProvider,
  type AudioPreviewState,
} from '@/app/settings/settings-audio-preview-helpers'

interface UseSettingsAudioPreviewParams {
  buildAudioPreviewInput: (provider: AudioPreviewProvider) => Record<string, unknown>
}

export function useSettingsAudioPreview(params: UseSettingsAudioPreviewParams) {
  const { buildAudioPreviewInput } = params
  const [audioPreviewState, setAudioPreviewState] = useState<Record<AudioPreviewProvider, AudioPreviewState>>({
    wan2gp: { isRunning: false, status: '待开始', audioUrl: '', error: null },
    edge_tts: { isRunning: false, status: '待开始', audioUrl: '', error: null },
    volcengine_tts: { isRunning: false, status: '待开始', audioUrl: '', error: null },
    kling_tts: { isRunning: false, status: '待开始', audioUrl: '', error: null },
    vidu_tts: { isRunning: false, status: '待开始', audioUrl: '', error: null },
    minimax_tts: { isRunning: false, status: '待开始', audioUrl: '', error: null },
    xiaomi_mimo_tts: { isRunning: false, status: '待开始', audioUrl: '', error: null },
  })
  const audioPreviewEventSourceRef = useRef<Record<AudioPreviewProvider, EventSource | null>>({
    wan2gp: null,
    edge_tts: null,
    volcengine_tts: null,
    kling_tts: null,
    vidu_tts: null,
    minimax_tts: null,
    xiaomi_mimo_tts: null,
  })

  const updateAudioPreviewState = useCallback(
    (provider: AudioPreviewProvider, patch: Partial<AudioPreviewState>) => {
      setAudioPreviewState((prev) => ({
        ...prev,
        [provider]: {
          ...prev[provider],
          ...patch,
        },
      }))
    },
    []
  )

  const closeAudioPreviewStream = useCallback((provider: AudioPreviewProvider) => {
    const current = audioPreviewEventSourceRef.current[provider]
    if (!current) return
    current.close()
    audioPreviewEventSourceRef.current[provider] = null
  }, [])

  useEffect(() => {
    return () => {
      closeAudioPreviewStream('wan2gp')
      closeAudioPreviewStream('edge_tts')
      closeAudioPreviewStream('volcengine_tts')
      closeAudioPreviewStream('kling_tts')
      closeAudioPreviewStream('vidu_tts')
      closeAudioPreviewStream('minimax_tts')
      closeAudioPreviewStream('xiaomi_mimo_tts')
    }
  }, [closeAudioPreviewStream])

  const startAudioPreview = useCallback((provider: AudioPreviewProvider) => {
    const providerSteps = AUDIO_PREVIEW_STEPS_BY_PROVIDER[provider]
    closeAudioPreviewStream(provider)
    updateAudioPreviewState(provider, {
      isRunning: true,
      status: providerSteps[0] || '生成中...',
      audioUrl: '',
      error: null,
    })

    const streamUrl = api.settings.audioPreviewStreamUrl(provider, buildAudioPreviewInput(provider))
    const eventSource = new EventSource(streamUrl)
    audioPreviewEventSourceRef.current[provider] = eventSource

    eventSource.onmessage = (event) => {
      if (audioPreviewEventSourceRef.current[provider] !== eventSource) return
      if (event.data === '[DONE]') {
        closeAudioPreviewStream(provider)
        updateAudioPreviewState(provider, { isRunning: false })
        return
      }

      let payload: Record<string, unknown>
      try {
        payload = JSON.parse(event.data) as Record<string, unknown>
      } catch {
        return
      }
      const eventType = String(payload.type || '')

      if (eventType === 'status') {
        updateAudioPreviewState(provider, {
          status: String(payload.message || providerSteps[0] || '生成中...'),
          error: null,
        })
        return
      }

      if (eventType === 'result') {
        const audioUrl = resolveApiResourceUrl(String(payload.audio_url || '').trim())
        updateAudioPreviewState(provider, {
          isRunning: false,
          status: String(payload.message || '生成完成'),
          audioUrl: audioUrl ? `${audioUrl}?t=${Date.now()}` : '',
          error: null,
        })
        toast.success('试用音频生成完成')
        closeAudioPreviewStream(provider)
        return
      }

      if (eventType === 'error') {
        const message = String(payload.message || '试用失败')
        updateAudioPreviewState(provider, {
          isRunning: false,
          status: '生成失败',
          error: message,
        })
        toast.error(`试用失败: ${message}`)
        closeAudioPreviewStream(provider)
      }
    }

    eventSource.onerror = () => {
      if (audioPreviewEventSourceRef.current[provider] !== eventSource) return
      closeAudioPreviewStream(provider)
      updateAudioPreviewState(provider, {
        isRunning: false,
        status: '连接中断',
      })
    }
  }, [buildAudioPreviewInput, closeAudioPreviewStream, updateAudioPreviewState])

  return {
    audioPreviewState,
    startAudioPreview,
  }
}
