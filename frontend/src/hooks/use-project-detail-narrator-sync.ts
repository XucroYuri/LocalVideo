import { useCallback, useEffect, useRef } from 'react'

import { api } from '@/lib/api-client'
import { resolveApiResourceUrl } from '@/lib/media-url'
import type { ContentSyncSnapshot, NarratorSyncTarget } from '@/hooks/use-project-detail.types'
import {
  isNarratorPresetAppearanceTextByMode,
  isNarratorPresetNameTextByMode,
  isNarratorPresetSettingTextByMode,
  resolveNarratorCustomNameByMode,
  resolveNarratorPresetAppearanceByMode,
  resolveNarratorPresetImageAssetByMode,
  resolveNarratorPresetNameByMode,
  resolveNarratorPresetSettingByMode,
  resolveNarratorPresetVoiceByMode,
} from '@/lib/narrator-style'
import type { Project } from '@/types/project'
import type { BackendStageType, Stage } from '@/types/stage'
import { toast } from 'sonner'

interface UseProjectDetailNarratorSyncParams {
  projectId: number
  contentGenerationEnabled: boolean
  effectiveScriptMode: string
  lockedNarratorReferences: NarratorSyncTarget[]
  snapshotCurrentContent: () => ContentSyncSnapshot
  notifyIfContentSyncedByReferenceChange: (before: ContentSyncSnapshot) => Promise<void>
  refetchStageScope: (stage: BackendStageType) => void
  project: Project | undefined
  referenceStage: Stage | null | undefined
  stageConfigStyle: string
  stageConfigHydratedProjectIdRef: React.RefObject<number | null>
}

export function useProjectDetailNarratorSync({
  projectId,
  contentGenerationEnabled,
  effectiveScriptMode,
  lockedNarratorReferences,
  snapshotCurrentContent,
  notifyIfContentSyncedByReferenceChange,
  refetchStageScope,
  project,
  referenceStage,
  stageConfigStyle,
  stageConfigHydratedProjectIdRef,
}: UseProjectDetailNarratorSyncParams) {
  const narratorStyleSyncQueueRef = useRef<Promise<void>>(Promise.resolve())
  const narratorStyleAutoSyncAttemptedKeyRef = useRef<string>('')

  const handleNarratorStylePresetSync = useCallback(async (styleValue: string) => {
    if (!contentGenerationEnabled) return
    if (effectiveScriptMode !== 'single' && effectiveScriptMode !== 'duo_podcast') return

    const fallbackNarratorReferences: NarratorSyncTarget[] = lockedNarratorReferences.map((item) => ({
      referenceId: item.referenceId,
      narratorIndex: item.narratorIndex,
      reference: {
        name: item.reference.name,
        setting: item.reference.setting,
        appearance_description: item.reference.appearance_description,
        can_speak: item.reference.can_speak,
        voice_audio_provider: item.reference.voice_audio_provider,
        voice_name: item.reference.voice_name,
        voice_speed: item.reference.voice_speed,
        voice_wan2gp_preset: item.reference.voice_wan2gp_preset,
        voice_wan2gp_alt_prompt: item.reference.voice_wan2gp_alt_prompt,
        voice_wan2gp_audio_guide: item.reference.voice_wan2gp_audio_guide,
        voice_wan2gp_temperature: item.reference.voice_wan2gp_temperature,
        voice_wan2gp_top_k: item.reference.voice_wan2gp_top_k,
        voice_wan2gp_seed: item.reference.voice_wan2gp_seed,
        image_url: item.reference.image_url,
      },
    }))

    let narratorReferencesForSync = fallbackNarratorReferences
    try {
      const latestReferenceStage = await api.stages.get(projectId, 'reference')
      const latestOutput = (latestReferenceStage?.output_data || {}) as {
        references?: Array<{
          id?: string
          name?: string
          setting?: string
          appearance_description?: string
          can_speak?: boolean
          voice_audio_provider?: 'edge_tts' | 'wan2gp' | 'volcengine_tts' | 'kling_tts' | 'vidu_tts' | 'minimax_tts' | 'xiaomi_mimo_tts'
          voice_name?: string
          voice_speed?: number
          voice_wan2gp_preset?: string
          voice_wan2gp_alt_prompt?: string
          voice_wan2gp_audio_guide?: string
          voice_wan2gp_temperature?: number
          voice_wan2gp_top_k?: number
          voice_wan2gp_seed?: number
        }>
        reference_images?: Array<{ id?: string; file_path?: string }>
      }
      const latestReferences = Array.isArray(latestOutput.references) ? latestOutput.references : []
      if (latestReferences.length > 0) {
        const latestImageIds = new Set(
          (Array.isArray(latestOutput.reference_images) ? latestOutput.reference_images : [])
            .map((image) => String(image?.id || '').trim())
            .filter((id) => !!id)
        )
        const narratorCountLimit = effectiveScriptMode === 'single' ? 1 : 2
        narratorReferencesForSync = latestReferences
          .slice(0, narratorCountLimit)
          .map((reference, narratorIndex) => {
            const referenceId = String(reference?.id || '').trim()
            return {
              referenceId,
              narratorIndex,
              reference: {
                ...reference,
                image_url: latestImageIds.has(referenceId) ? '__has_image__' : '',
              },
            }
          })
          .filter((item) => !!item.referenceId)
      }
    } catch {
      narratorReferencesForSync = fallbackNarratorReferences
    }

    if (narratorReferencesForSync.length === 0) return

    const contentSnapshotBefore = snapshotCurrentContent()
    const updates: Array<{
      referenceId: string
      presetImageAssetPath: string
      shouldClearImage: boolean
      hasExistingImage: boolean
      payload: {
        name: string
        setting: string
        appearance_description: string
        can_speak: boolean
        voice_audio_provider?: 'edge_tts' | 'wan2gp' | 'volcengine_tts' | 'kling_tts' | 'vidu_tts' | 'minimax_tts' | 'xiaomi_mimo_tts'
        voice_name?: string
        voice_speed?: number
        voice_wan2gp_preset?: string
        voice_wan2gp_alt_prompt?: string
        voice_wan2gp_audio_guide?: string
        voice_wan2gp_temperature?: number
        voice_wan2gp_top_k?: number
        voice_wan2gp_seed?: number
      }
    }> = []
    narratorReferencesForSync.forEach(({ referenceId, reference: narratorReference, narratorIndex }) => {
      const presetSetting = resolveNarratorPresetSettingByMode(
        effectiveScriptMode,
        styleValue,
        narratorIndex
      )
      const presetName = resolveNarratorPresetNameByMode(
        effectiveScriptMode,
        styleValue,
        narratorIndex
      )
      const presetVoice = resolveNarratorPresetVoiceByMode(
        effectiveScriptMode,
        styleValue,
        narratorIndex
      )
      const presetAppearance = resolveNarratorPresetAppearanceByMode(
        effectiveScriptMode,
        styleValue,
        narratorIndex
      )
      const presetImageAssetPath = resolveNarratorPresetImageAssetByMode(
        effectiveScriptMode,
        styleValue,
        narratorIndex
      )
      const defaultCustomName = resolveNarratorCustomNameByMode(
        effectiveScriptMode,
        narratorIndex
      )
      const currentName = String(narratorReference.name || '').trim()
      const currentSetting = String(narratorReference.setting || '').trim()
      const currentAppearance = String(
        narratorReference.appearance_description || ''
      ).trim()
      const targetName = presetName || (
        isNarratorPresetNameTextByMode(effectiveScriptMode, currentName)
          ? defaultCustomName
          : (currentName || defaultCustomName)
      )
      const targetSetting = presetSetting || (
        isNarratorPresetSettingTextByMode(effectiveScriptMode, currentSetting) ? '' : currentSetting
      )
      const targetAppearance = presetAppearance || (
        isNarratorPresetAppearanceTextByMode(effectiveScriptMode, currentAppearance)
          ? ''
          : currentAppearance
      )
      const targetVoiceAudioProvider = presetVoice?.voice_audio_provider ?? narratorReference.voice_audio_provider
      const targetVoiceName = presetVoice?.voice_name ?? narratorReference.voice_name
      const targetVoiceSpeed = presetVoice?.voice_speed ?? narratorReference.voice_speed
      const targetWan2gpPreset = presetVoice?.voice_wan2gp_preset ?? narratorReference.voice_wan2gp_preset
      const targetWan2gpAltPrompt = (
        presetVoice?.voice_wan2gp_alt_prompt ?? narratorReference.voice_wan2gp_alt_prompt
      )
      const targetWan2gpAudioGuide = (
        presetVoice?.voice_wan2gp_audio_guide ?? narratorReference.voice_wan2gp_audio_guide
      )
      const targetWan2gpTemperature = (
        presetVoice?.voice_wan2gp_temperature ?? narratorReference.voice_wan2gp_temperature
      )
      const targetWan2gpTopK = presetVoice?.voice_wan2gp_top_k ?? narratorReference.voice_wan2gp_top_k
      const targetWan2gpSeed = presetVoice?.voice_wan2gp_seed ?? narratorReference.voice_wan2gp_seed
      const currentImageUrl = String(narratorReference.image_url || '').trim()
      const hasExistingImage = !!currentImageUrl
      const shouldClearImage = !presetImageAssetPath && !!currentImageUrl
      const currentCanSpeak = narratorReference.can_speak !== false
      if (
        currentName === targetName
        && currentSetting === targetSetting
        && currentAppearance === targetAppearance
        && currentCanSpeak
        && narratorReference.voice_audio_provider === targetVoiceAudioProvider
        && narratorReference.voice_name === targetVoiceName
        && narratorReference.voice_speed === targetVoiceSpeed
        && narratorReference.voice_wan2gp_preset === targetWan2gpPreset
        && narratorReference.voice_wan2gp_alt_prompt === targetWan2gpAltPrompt
        && narratorReference.voice_wan2gp_audio_guide === targetWan2gpAudioGuide
        && narratorReference.voice_wan2gp_temperature === targetWan2gpTemperature
        && narratorReference.voice_wan2gp_top_k === targetWan2gpTopK
        && narratorReference.voice_wan2gp_seed === targetWan2gpSeed
        && !shouldClearImage
      ) {
        return
      }

      updates.push({
        referenceId,
        presetImageAssetPath,
        shouldClearImage,
        hasExistingImage,
        payload: {
          name: targetName,
          setting: targetSetting,
          appearance_description: targetAppearance,
          can_speak: true,
          voice_audio_provider: targetVoiceAudioProvider,
          voice_name: targetVoiceName,
          voice_speed: targetVoiceSpeed,
          voice_wan2gp_preset: targetWan2gpPreset,
          voice_wan2gp_alt_prompt: targetWan2gpAltPrompt,
          voice_wan2gp_audio_guide: targetWan2gpAudioGuide,
          voice_wan2gp_temperature: targetWan2gpTemperature,
          voice_wan2gp_top_k: targetWan2gpTopK,
          voice_wan2gp_seed: targetWan2gpSeed,
        },
      })
    })

    if (updates.length === 0) return
    try {
      const imageUploadFailures: string[] = []
      const imageClearFailures: string[] = []
      for (const item of updates) {
        await api.stages.updateReference(projectId, item.referenceId, item.payload)
        if (item.presetImageAssetPath) {
          try {
            const presetAssetUrl = resolveApiResourceUrl(item.presetImageAssetPath)
            const imageResponse = await fetch(presetAssetUrl)
            if (!imageResponse.ok) {
              // 预设声明了图片但静态资源不可用时，清空旧图，避免保留上一个预设图片。
              if (item.hasExistingImage) {
                try {
                  await api.stages.deleteReferenceImage(projectId, item.referenceId)
                } catch {
                  imageClearFailures.push(item.referenceId)
                }
              }
              imageUploadFailures.push(item.presetImageAssetPath)
              continue
            }
            const blob = await imageResponse.blob()
            const fileName = item.presetImageAssetPath.split('/').pop() || `${item.referenceId}.png`
            const file = new File([blob], fileName, {
              type: blob.type || 'image/png',
            })
            await api.stages.uploadReferenceImage(projectId, item.referenceId, file)
          } catch {
            if (item.hasExistingImage) {
              try {
                await api.stages.deleteReferenceImage(projectId, item.referenceId)
              } catch {
                imageClearFailures.push(item.referenceId)
              }
            }
            imageUploadFailures.push(item.presetImageAssetPath)
          }
        } else if (item.shouldClearImage) {
          try {
            await api.stages.deleteReferenceImage(projectId, item.referenceId)
          } catch {
            imageClearFailures.push(item.referenceId)
          }
        }
      }
      refetchStageScope('reference')
      await notifyIfContentSyncedByReferenceChange(contentSnapshotBefore)
      if (imageUploadFailures.length > 0 || imageClearFailures.length > 0) {
        const warnings: string[] = []
        if (imageUploadFailures.length > 0) {
          warnings.push(`预设图片同步失败 ${imageUploadFailures.length} 项（请先执行批量生成脚本）`)
        }
        if (imageClearFailures.length > 0) {
          warnings.push(`参考图片清空失败 ${imageClearFailures.length} 项`)
        }
        toast.warning(warnings.join('；'))
      }
    } catch (error) {
      console.error('Failed to sync narrator preset settings:', error)
      toast.error('同步讲述者预设失败')
    }
  }, [
    contentGenerationEnabled,
    effectiveScriptMode,
    lockedNarratorReferences,
    notifyIfContentSyncedByReferenceChange,
    projectId,
    refetchStageScope,
    snapshotCurrentContent,
  ])

  const handleNarratorStyleChange = useCallback(async (nextStyle: string, prevStyle: string) => {
    if (!contentGenerationEnabled) return
    if (effectiveScriptMode !== 'single' && effectiveScriptMode !== 'duo_podcast') return
    if (lockedNarratorReferences.length === 0) return
    if (nextStyle === prevStyle) return
    narratorStyleSyncQueueRef.current = narratorStyleSyncQueueRef.current
      .catch(() => {})
      .then(() => handleNarratorStylePresetSync(nextStyle))
    await narratorStyleSyncQueueRef.current
  }, [
    contentGenerationEnabled,
    effectiveScriptMode,
    handleNarratorStylePresetSync,
    lockedNarratorReferences.length,
  ])

  useEffect(() => {
    if (!contentGenerationEnabled) return
    if (effectiveScriptMode !== 'single' && effectiveScriptMode !== 'duo_podcast') return
    if (!project) return
    if (stageConfigHydratedProjectIdRef.current !== project.id) return
    // Wait until REFERENCE stage query settles (object or null).
    // Avoid syncing against transient SCRIPT fallback references during initial loading.
    if (referenceStage === undefined) return
    const normalizedStyle = String(stageConfigStyle || '').trim()
    if (!normalizedStyle || normalizedStyle === '__default__') return
    const normalizedProjectStyle = String(project.style || '').trim()
    // Prevent running with any pre-hydration fallback style.
    if (normalizedStyle !== normalizedProjectStyle) return
    if (lockedNarratorReferences.length === 0) return
    const referenceKey = lockedNarratorReferences.map((item) => item.referenceId).join(',')
    if (!referenceKey) return
    const autoSyncKey = `${projectId}:${effectiveScriptMode}:${normalizedStyle}:${referenceKey}`
    if (narratorStyleAutoSyncAttemptedKeyRef.current === autoSyncKey) return
    narratorStyleAutoSyncAttemptedKeyRef.current = autoSyncKey

    narratorStyleSyncQueueRef.current = narratorStyleSyncQueueRef.current
      .catch(() => {})
      .then(() => handleNarratorStylePresetSync(normalizedStyle))
      .catch((error) => {
        console.error('Failed to auto sync narrator style preset:', error)
        if (narratorStyleAutoSyncAttemptedKeyRef.current === autoSyncKey) {
          narratorStyleAutoSyncAttemptedKeyRef.current = ''
        }
      })
  }, [
    contentGenerationEnabled,
    effectiveScriptMode,
    handleNarratorStylePresetSync,
    lockedNarratorReferences,
    project,
    projectId,
    referenceStage,
    stageConfigHydratedProjectIdRef,
    stageConfigStyle,
  ])

  return { handleNarratorStyleChange }
}
