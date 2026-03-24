import { useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { useConfirmDialog } from '@/components/common/confirm-dialog-provider'
import { api } from '@/lib/api-client'
import { queryKeys } from '@/lib/query-keys'
import { getScopedWan2gpInferenceSteps } from '@/lib/stage-input-builder'
import { resolveVideoProvider } from '@/lib/stage-runtime'
import type { StageConfig } from '@/types/stage-panel'
import type { BackendStageType, Stage } from '@/types/stage'
import type { StageReferenceImportResult } from '@/types/reference'
import type { ReferenceVoiceProvider } from '@/lib/project-detail-helpers'
import type { Settings } from '@/types/settings'

interface LockedNarratorReference {
  referenceId: string
}

interface ProjectDetailStageData {
  storyboard?: {
    shots?: Array<{ shot_id?: string }>
  }
  audio?: {
    shots?: Array<{ audio_url?: string }>
  }
  frame?: {
    shots?: Array<{ first_frame_url?: string }>
  }
  video?: {
    shots?: Array<{ video_url?: string }>
  }
}

interface UseProjectDetailStageActionsParams {
  projectId: number
  effectiveScriptMode: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'
  lockedDuoSceneReferenceId: string
  lockedNarratorReferences: LockedNarratorReference[]
  runReferenceMutationWithContentSync: <T>(mutation: () => Promise<T>) => Promise<T>
  stageConfig: StageConfig
  refetchStageScope: (stage: BackendStageType) => void
  referenceNameById: Map<string, string>
  stageData: ProjectDetailStageData | undefined
  refetchFrameStage: () => Promise<unknown>
  refetchStages: () => Promise<unknown>
  refetchVideoStage: () => Promise<unknown>
  refetchComposeStage: () => Promise<unknown>
  refetchSubtitleStage: () => Promise<unknown>
  refetchBurnSubtitleStage: () => Promise<unknown>
  refetchFinalizeStage: () => Promise<unknown>
  refetchStoryboardStage: () => Promise<unknown>
  refetchAudioStage: () => Promise<unknown>
  settings: Settings | undefined
  runStage: (stage: BackendStageType, config: StageConfig, inputData?: Record<string, unknown>) => Promise<void>
  isSingleTakeEnabled: boolean
  effectiveUseFirstFrameRef: boolean
  hasStoryboardClearableOutputs: boolean
}

export function useProjectDetailStageActions(params: UseProjectDetailStageActionsParams) {
  const {
    projectId,
    effectiveScriptMode,
    lockedDuoSceneReferenceId,
    lockedNarratorReferences,
    runReferenceMutationWithContentSync,
    stageConfig,
    refetchStageScope,
    referenceNameById,
    stageData,
    refetchFrameStage,
    refetchStages,
    refetchVideoStage,
    refetchComposeStage,
    refetchSubtitleStage,
    refetchBurnSubtitleStage,
    refetchFinalizeStage,
    refetchStoryboardStage,
    refetchAudioStage,
    settings,
    runStage,
    isSingleTakeEnabled,
    effectiveUseFirstFrameRef,
    hasStoryboardClearableOutputs,
  } = params
  const confirmDialog = useConfirmDialog()
  const queryClient = useQueryClient()

  const syncClearedShotsToCache = useCallback(() => {
    queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'content'), (current) => {
      if (!current) return current
      const output = {
        ...((current.output_data || {}) as Record<string, unknown>),
        shots_locked: false,
      }
      return { ...current, output_data: output }
    })
    queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'storyboard'), (current) => {
      if (!current) return current
      const output = {
        ...((current.output_data || {}) as Record<string, unknown>),
        shots: [],
        shot_count: 0,
      }
      return { ...current, output_data: output }
    })
    queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'audio'), (current) => {
      if (!current) return current
      return {
        ...current,
        output_data: {
          audio_assets: [],
          shot_count: 0,
          total_duration: 0,
          generating_shots: {},
        },
      }
    })
    queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'frame'), (current) => {
      if (!current) return current
      return {
        ...current,
        output_data: {
          frame_images: [],
          frame_count: 0,
          success_count: 0,
        },
      }
    })
    queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'video'), (current) => {
      if (!current) return current
      return {
        ...current,
        output_data: {
          video_assets: [],
          video_count: 0,
        },
      }
    })
    queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'compose'), (current) => {
      if (!current) return current
      return { ...current, output_data: {} }
    })
    queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'subtitle'), (current) => {
      if (!current) return current
      return { ...current, output_data: {} }
    })
    queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'burn_subtitle'), (current) => {
      if (!current) return current
      return { ...current, output_data: {} }
    })
    queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'finalize'), (current) => {
      if (!current) return current
      return { ...current, output_data: {} }
    })
  }, [projectId, queryClient])

  const syncSmartMergePendingToCache = useCallback(() => {
    queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'storyboard'), (current) => {
      if (!current) return current
      const output = {
        ...((current.output_data || {}) as Record<string, unknown>),
        shots: [],
        shot_count: 0,
      }
      return { ...current, output_data: output }
    })
    queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'content'), (current) => {
      if (!current) return current
      const output = {
        ...((current.output_data || {}) as Record<string, unknown>),
        shots_locked: true,
      }
      return { ...current, output_data: output }
    })
    queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'first_frame_desc'), (current) => {
      if (!current) return current
      return { ...current, output_data: {} }
    })
    queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'audio'), (current) => {
      if (!current) return current
      return {
        ...current,
        output_data: {
          audio_assets: [],
          shot_count: 0,
          total_duration: 0,
          generating_shots: {},
        },
      }
    })
    queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'frame'), (current) => {
      if (!current) return current
      return {
        ...current,
        output_data: {
          frame_images: [],
          frame_count: 0,
          success_count: 0,
        },
      }
    })
    queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'video'), (current) => {
      if (!current) return current
      return {
        ...current,
        output_data: {
          video_assets: [],
          video_count: 0,
        },
      }
    })
    queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'compose'), (current) => {
      if (!current) return current
      return { ...current, output_data: {} }
    })
    queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'subtitle'), (current) => {
      if (!current) return current
      return { ...current, output_data: {} }
    })
    queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'burn_subtitle'), (current) => {
      if (!current) return current
      return { ...current, output_data: {} }
    })
    queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'finalize'), (current) => {
      if (!current) return current
      return { ...current, output_data: {} }
    })
  }, [projectId, queryClient])

  const syncDeletedComposeVideoToCache = useCallback(() => {
    queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'compose'), (current) => {
      if (!current) return current
      return { ...current, output_data: {} }
    })
    queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'subtitle'), (current) => {
      if (!current) return current
      return { ...current, output_data: {} }
    })
    queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'burn_subtitle'), (current) => {
      if (!current) return current
      return { ...current, output_data: {} }
    })
    queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'finalize'), (current) => {
      if (!current) return current
      return { ...current, output_data: {} }
    })
  }, [projectId, queryClient])

  const clearAllShotContentWithoutConfirm = useCallback(async () => {
    try {
      await api.stages.clearAllShotContent(projectId)
      syncClearedShotsToCache()
      await queryClient.invalidateQueries({ queryKey: queryKeys.projects.listBase })
      await Promise.all([
        refetchStages(),
        refetchStoryboardStage(),
        refetchAudioStage(),
        refetchFrameStage(),
        refetchVideoStage(),
        refetchComposeStage(),
      ])
    } catch (error) {
      console.error('Failed to clear all shot content:', error)
      toast.error('清空分镜内容失败')
      throw error
    }
  }, [
    projectId,
    queryClient,
    refetchAudioStage,
    refetchComposeStage,
    refetchFrameStage,
    refetchStoryboardStage,
    refetchStages,
    refetchVideoStage,
    syncClearedShotsToCache,
  ])

  const handleDeleteContent = useCallback(async () => {
    try {
      await api.stages.updateContent(projectId, {
        title: '',
        content: '',
        dialogue_lines: [],
      })
      refetchStageScope('content')
      toast.success('文案已删除')
    } catch (error) {
      console.error('Failed to delete content:', error)
      toast.error('删除失败')
      throw error
    }
  }, [projectId, refetchStageScope])

  const handleImportDialogue = useCallback(async (
    file: File,
    scriptMode: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'
  ) => {
    try {
      const response = await api.stages.importContentDialogue(projectId, file, scriptMode)
      const createdReferences = response.auto_created_references || []
      if (createdReferences.length > 0) {
        await confirmDialog({
          title: '导入完成',
          description: `检测到 ${createdReferences.length} 个角色在参考区不存在，已自动新建名称参考：${createdReferences.join('、')}`,
          confirmText: '我知道了',
          hideCancel: true,
        })
      }
      refetchStageScope('content')
      refetchStageScope('reference')
      toast.success('对话脚本已导入')
    } catch (error) {
      const message = error instanceof Error ? error.message : '导入失败'
      toast.error(message)
      throw error
    }
  }, [confirmDialog, projectId, refetchStageScope])

  const handleSaveReference = useCallback(async (
    referenceId: string | number,
    data: {
      name: string
      setting?: string
      appearance_description?: string
      can_speak: boolean
      voice_audio_provider?: ReferenceVoiceProvider
      voice_name?: string
      voice_speed?: number
      voice_wan2gp_preset?: string
      voice_wan2gp_alt_prompt?: string
      voice_wan2gp_audio_guide?: string
      voice_wan2gp_temperature?: number
      voice_wan2gp_top_k?: number
      voice_wan2gp_seed?: number
    }
  ) => {
    try {
      await runReferenceMutationWithContentSync(() => api.stages.updateReference(projectId, referenceId, data))
    } catch (error) {
      console.error('Failed to save reference:', error)
      toast.error('保存失败')
      throw error
    }
  }, [projectId, runReferenceMutationWithContentSync])

  const handleDeleteReference = useCallback(async (referenceId: string | number) => {
    const normalizedId = String(referenceId).trim()
    if (effectiveScriptMode === 'duo_podcast' && lockedDuoSceneReferenceId && normalizedId === lockedDuoSceneReferenceId) {
      toast.info('双人播客模式下，播客场景参考固定，不能删除')
      return
    }
    if (lockedNarratorReferences.some((item) => item.referenceId === normalizedId)) {
      if (effectiveScriptMode === 'single') {
        toast.info('单人叙述模式下，首个参考固定为讲述者，不能删除')
      } else if (effectiveScriptMode === 'duo_podcast') {
        toast.info('双人播客模式下，前2个参考固定为讲述者，不能删除')
      }
      return
    }
    try {
      await runReferenceMutationWithContentSync(() => api.stages.deleteReference(projectId, referenceId))
      toast.success('参考已删除')
    } catch (error) {
      console.error('Failed to delete reference:', error)
      toast.error('删除失败')
      throw error
    }
  }, [
    effectiveScriptMode,
    lockedDuoSceneReferenceId,
    lockedNarratorReferences,
    projectId,
    runReferenceMutationWithContentSync,
  ])

  const handleUploadReferenceImage = useCallback(async (referenceId: string | number, file: File) => {
    try {
      await api.stages.uploadReferenceImage(projectId, referenceId, file)
      refetchStageScope('reference')
      toast.success('参考图片已上传')
    } catch (error) {
      console.error('Failed to upload reference image:', error)
      toast.error('上传失败')
      throw error
    }
  }, [projectId, refetchStageScope])

  const handleCreateReference = useCallback(async (
    data: {
      name?: string
      setting?: string
      appearance_description?: string
      can_speak?: boolean
      voice_audio_provider?: ReferenceVoiceProvider
      voice_name?: string
      voice_speed?: number
      voice_wan2gp_preset?: string
      voice_wan2gp_alt_prompt?: string
      voice_wan2gp_audio_guide?: string
      voice_wan2gp_temperature?: number
      voice_wan2gp_top_k?: number
      voice_wan2gp_seed?: number
      file?: File
    }
  ) => {
    try {
      await runReferenceMutationWithContentSync(() => api.stages.createReference(projectId, data))
      toast.success('参考已创建')
    } catch (error) {
      console.error('Failed to create reference:', error)
      toast.error('创建失败')
      throw error
    }
  }, [projectId, runReferenceMutationWithContentSync])

  const handleGenerateDescriptionFromImage = useCallback(async (referenceId: string | number) => {
    try {
      await api.stages.generateDescriptionFromImage(projectId, referenceId, {
        target_language: stageConfig.textTargetLanguage || 'zh',
        prompt_complexity: stageConfig.textPromptComplexity || 'normal',
        llm_provider: stageConfig.llmProvider || undefined,
        llm_model: stageConfig.llmModel || undefined,
      })
      refetchStageScope('reference')
    } catch (error) {
      console.error('Failed to generate description from image:', error)
      toast.error('生成描述失败')
      throw error
    }
  }, [projectId, refetchStageScope, stageConfig])

  const handleSaveFrameDescription = useCallback(async (shotIndex: number, description: string) => {
    try {
      await api.stages.updateFrameDescription(projectId, shotIndex, { description })
      refetchStageScope('frame')
    } catch (error) {
      console.error('Failed to save frame description:', error)
      toast.error('保存失败')
      throw error
    }
  }, [projectId, refetchStageScope])

  const handleSaveFrameReferences = useCallback(async (shotIndex: number, referenceIds: string[]) => {
    try {
      const normalizedIds = Array.from(new Set(referenceIds.map((id) => String(id || '').trim()).filter((id) => !!id)))
      const referenceSlotItems = normalizedIds.map((id, index) => {
        const name = referenceNameById.get(id)
        return { order: index + 1, id, ...(name ? { name } : {}) }
      })
      await api.stages.updateFrameDescription(projectId, shotIndex, {
        first_frame_reference_slots: referenceSlotItems,
      })
      refetchStageScope('frame')
      toast.success('首帧参考图已更新')
    } catch (error) {
      console.error('Failed to save frame references:', error)
      toast.error('更新失败')
      throw error
    }
  }, [projectId, referenceNameById, refetchStageScope])

  const handleSaveVideoDescription = useCallback(async (shotIndex: number, description: string) => {
    try {
      await api.stages.updateVideoDescription(projectId, shotIndex, { description })
      refetchStageScope('storyboard')
    } catch (error) {
      console.error('Failed to save video description:', error)
      toast.error('保存失败')
      throw error
    }
  }, [projectId, refetchStageScope])

  const handleSaveVideoReferences = useCallback(async (shotIndex: number, referenceIds: string[]) => {
    try {
      const normalizedIds = Array.from(new Set(referenceIds.map((id) => String(id || '').trim()).filter((id) => !!id)))
      const referenceSlotItems = normalizedIds.map((id, index) => {
        const name = referenceNameById.get(id)
        return { order: index + 1, id, ...(name ? { name } : {}) }
      })
      await api.stages.updateVideoDescription(projectId, shotIndex, {
        video_reference_slots: referenceSlotItems,
      })
      refetchStageScope('storyboard')
      toast.success('视频参考图已更新')
    } catch (error) {
      console.error('Failed to save video references:', error)
      toast.error('更新失败')
      throw error
    }
  }, [projectId, referenceNameById, refetchStageScope])

  const handleUploadFrameImage = useCallback(async (shotIndex: number, file: File) => {
    try {
      await api.stages.uploadFrameImage(projectId, shotIndex, file)
      refetchStageScope('frame')
      toast.success('首帧图已上传')
    } catch (error) {
      console.error('Failed to upload frame image:', error)
      toast.error('上传失败')
      throw error
    }
  }, [projectId, refetchStageScope])

  const handleDeleteFrameImage = useCallback(async (shotIndex: number) => {
    try {
      await api.stages.deleteFrameImage(projectId, shotIndex)
      refetchStageScope('frame')
      toast.success('首帧图已删除')
    } catch (error) {
      console.error('Failed to delete frame image:', error)
      toast.error('删除失败')
      throw error
    }
  }, [projectId, refetchStageScope])

  const handleSingleTakeModeTransition = useCallback(async (
    params: { nextEnabled: boolean; reason: 'toggle' | 'duo_mode' }
  ): Promise<boolean> => {
    void params
    return true
  }, [])

  const handleDeleteVideo = useCallback(async (shotIndex: number) => {
    try {
      await api.stages.deleteVideo(projectId, shotIndex)
      await queryClient.invalidateQueries({ queryKey: queryKeys.projects.listBase })
      refetchStageScope('video')
      toast.success('视频已删除')
    } catch (error) {
      console.error('Failed to delete video:', error)
      toast.error('删除失败')
      throw error
    }
  }, [projectId, queryClient, refetchStageScope])

  const handleClearAllFrameImages = useCallback(async () => {
    const frameShots = stageData?.frame?.shots || []
    const targetShotIndices = frameShots
      .map((shot, index) => (String(shot?.first_frame_url || '').trim() ? index : -1))
      .filter((index) => index >= 0)
    if (targetShotIndices.length === 0) {
      toast.info('当前没有可清空的首帧图')
      return
    }

    const confirmed = await confirmDialog({
      title: '清空首帧图确认',
      description: `将清空 ${targetShotIndices.length} 个分镜的首帧图，是否继续？`,
      confirmText: '确认清空',
      cancelText: '取消',
      variant: 'destructive',
    })
    if (!confirmed) return

    try {
      const result = await api.stages.bulkDeleteFrameImages(projectId, targetShotIndices)
      const failedCount = Array.isArray(result.missing_shot_indices) ? result.missing_shot_indices.length : 0
      await refetchFrameStage()
      await refetchStages()

      if (failedCount > 0) {
        toast.warning(`清空完成：成功 ${targetShotIndices.length - failedCount}，失败 ${failedCount}`)
      } else {
        toast.success(`已清空 ${targetShotIndices.length} 个分镜首帧图`)
      }
    } catch (error) {
      console.error('Failed to clear all frame images:', error)
      toast.error('清空首帧图失败')
      throw error
    }
  }, [confirmDialog, projectId, refetchFrameStage, refetchStages, stageData?.frame?.shots])

  const handleClearAllAudio = useCallback(async () => {
    const audioShots = stageData?.audio?.shots || []
    const targetShotIndices = audioShots
      .map((shot, index) => (String(shot?.audio_url || '').trim() ? index : -1))
      .filter((index) => index >= 0)
    if (targetShotIndices.length === 0) {
      toast.info('当前没有可清空的音频')
      return
    }

    const confirmed = await confirmDialog({
      title: '清空音频确认',
      description: `将清空 ${targetShotIndices.length} 个分镜的音频，是否继续？`,
      confirmText: '确认清空',
      cancelText: '取消',
      variant: 'destructive',
    })
    if (!confirmed) return

    try {
      const result = await api.stages.bulkDeleteAudios(projectId, targetShotIndices)
      const failedCount = Array.isArray(result.missing_shot_indices) ? result.missing_shot_indices.length : 0
      await refetchAudioStage()
      await refetchStages()

      if (failedCount > 0) {
        toast.warning(`清空完成：成功 ${targetShotIndices.length - failedCount}，失败 ${failedCount}`)
      } else {
        toast.success(`已清空 ${targetShotIndices.length} 个分镜音频`)
      }
    } catch (error) {
      console.error('Failed to clear all audio:', error)
      toast.error('清空音频失败')
      throw error
    }
  }, [confirmDialog, projectId, refetchAudioStage, refetchStages, stageData?.audio?.shots])

  const handleClearAllVideos = useCallback(async () => {
    const videoShots = stageData?.video?.shots || []
    const targetShotIndices = videoShots
      .map((shot, index) => (String(shot?.video_url || '').trim() ? index : -1))
      .filter((index) => index >= 0)
    if (targetShotIndices.length === 0) {
      toast.info('当前没有可清空的视频')
      return
    }

    const confirmed = await confirmDialog({
      title: '清空视频确认',
      description: `将清空 ${targetShotIndices.length} 个分镜的视频，是否继续？`,
      confirmText: '确认清空',
      cancelText: '取消',
      variant: 'destructive',
    })
    if (!confirmed) return

    try {
      const result = await api.stages.bulkDeleteVideos(projectId, targetShotIndices)
      const failedCount = Array.isArray(result.missing_shot_indices) ? result.missing_shot_indices.length : 0
      await queryClient.invalidateQueries({ queryKey: queryKeys.projects.listBase })
      await Promise.all([refetchVideoStage(), refetchComposeStage(), refetchStages()])

      if (failedCount > 0) {
        toast.warning(`清空完成：成功 ${targetShotIndices.length - failedCount}，失败 ${failedCount}`)
      } else {
        toast.success(`已清空 ${targetShotIndices.length} 个分镜视频`)
      }
    } catch (error) {
      console.error('Failed to clear all videos:', error)
      toast.error('清空视频失败')
      throw error
    }
  }, [confirmDialog, projectId, queryClient, refetchComposeStage, refetchStages, refetchVideoStage, stageData?.video?.shots])

  const handleClearAllShotContent = useCallback(async () => {
    const confirmed = await confirmDialog({
      title: '清空所有分镜内容',
      description: '清空后将移除所有分镜文案、分镜音频、首帧描述、首帧图、视频描述和视频，是否继续？',
      confirmText: '确认清空',
      cancelText: '取消',
      variant: 'destructive',
    })
    if (!confirmed) return

    await clearAllShotContentWithoutConfirm()
    toast.success('已清空所有分镜内容')
  }, [
    clearAllShotContentWithoutConfirm,
    confirmDialog,
  ])

  const handleDeleteComposeVideo = useCallback(async () => {
    try {
      await api.stages.deleteComposeVideo(projectId)
      syncDeletedComposeVideoToCache()
      await queryClient.invalidateQueries({ queryKey: queryKeys.projects.listBase })
      await Promise.all([
        refetchStages(),
        refetchComposeStage(),
        refetchSubtitleStage(),
        refetchBurnSubtitleStage(),
        refetchFinalizeStage(),
      ])
      toast.success('最终视频已删除')
    } catch (error) {
      console.error('Failed to delete composed video:', error)
      toast.error('删除失败')
      throw error
    }
  }, [
    projectId,
    queryClient,
    refetchBurnSubtitleStage,
    refetchComposeStage,
    refetchFinalizeStage,
    refetchStages,
    refetchSubtitleStage,
    syncDeletedComposeVideoToCache,
  ])

  const refetchShotScopes = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.projects.listBase })
    await Promise.all([
      refetchStages(),
      refetchStoryboardStage(),
      refetchAudioStage(),
      refetchFrameStage(),
      refetchVideoStage(),
      refetchComposeStage(),
    ])
  }, [
    refetchAudioStage,
    refetchComposeStage,
    refetchFrameStage,
    refetchStoryboardStage,
    refetchStages,
    refetchVideoStage,
    queryClient,
  ])

  const handleInsertShots = useCallback(async (
    anchorIndex: number,
    direction: 'before' | 'after',
    count: number
  ) => {
    try {
      await api.stages.insertShots(projectId, {
        anchor_index: anchorIndex,
        direction,
        count,
      })
      await refetchShotScopes()
      toast.success(`已插入 ${count} 个分镜`)
    } catch (error) {
      console.error('Failed to insert shots:', error)
      toast.error('插入分镜失败')
      throw error
    }
  }, [projectId, refetchShotScopes])

  const handleMoveShot = useCallback(async (
    shotId: string,
    direction: 'up' | 'down',
    step = 1
  ) => {
    try {
      await api.stages.moveShot(projectId, {
        shot_id: shotId,
        direction,
        step,
      })
      await refetchShotScopes()
      toast.success(direction === 'up' ? '分镜已上移' : '分镜已下移')
    } catch (error) {
      console.error('Failed to move shot:', error)
      toast.error('移动分镜失败')
      throw error
    }
  }, [projectId, refetchShotScopes])

  const handleDeleteShot = useCallback(async (shotId: string) => {
    const confirmed = await confirmDialog({
      title: '删除分镜',
      description: '删除后将同步清理该分镜相关生成内容，是否继续？',
      confirmText: '确认删除',
      cancelText: '取消',
      variant: 'destructive',
    })
    if (!confirmed) return
    try {
      await api.stages.deleteShot(projectId, shotId)
      await refetchShotScopes()
      toast.success('分镜已删除')
    } catch (error) {
      console.error('Failed to delete shot:', error)
      toast.error('删除分镜失败')
      throw error
    }
  }, [confirmDialog, projectId, refetchShotScopes])

  const handleUpdateShot = useCallback(async (
    shotId: string,
    data: {
      voice_content?: string
      speaker_id?: string
      speaker_name?: string
    }
  ) => {
    try {
      await api.stages.updateShot(projectId, shotId, data)
      await refetchShotScopes()
    } catch (error) {
      console.error('Failed to update shot:', error)
      toast.error('更新分镜失败')
      throw error
    }
  }, [projectId, refetchShotScopes])

  const handleUnlockContentByClearingShots = useCallback(async () => {
    const confirmed = await confirmDialog({
      title: '清空分镜并解锁文案',
      description: '将清空全部分镜及相关生成内容，恢复文案区可编辑状态，是否继续？',
      confirmText: '确认清空',
      cancelText: '取消',
      variant: 'destructive',
    })
    if (!confirmed) return

    try {
      await api.stages.unlockContentByClearingShots(projectId)
      syncClearedShotsToCache()
      await refetchShotScopes()
      toast.success('已清空分镜并恢复文案编辑')
    } catch (error) {
      console.error('Failed to unlock content by clearing shots:', error)
      toast.error('操作失败')
      throw error
    }
  }, [confirmDialog, projectId, refetchShotScopes, syncClearedShotsToCache])

  const handleDeleteReferenceImage = useCallback(async (referenceId: string | number) => {
    try {
      await api.stages.deleteReferenceImage(projectId, referenceId)
      refetchStageScope('reference')
      toast.success('参考图片已删除')
    } catch (error) {
      console.error('Failed to delete reference image:', error)
      toast.error('删除失败')
      throw error
    }
  }, [projectId, refetchStageScope])

  const handleImportReferencesFromLibrary = useCallback(async (
    data: {
      library_reference_ids: number[]
      start_reference_index?: number
      import_setting: boolean
      import_appearance_description: boolean
      import_image: boolean
      import_voice: boolean
    }
  ): Promise<StageReferenceImportResult> => {
    try {
      const result = await runReferenceMutationWithContentSync(
        () => api.stages.importReferencesFromLibrary(projectId, data)
      )
      const { created_count, skipped_count, failed_count } = result.summary
      if (failed_count > 0) {
        toast.warning(`导入完成：成功 ${created_count}，跳过 ${skipped_count}，失败 ${failed_count}`)
      } else {
        toast.success(`导入完成：成功 ${created_count}，跳过 ${skipped_count}`)
      }
      return result
    } catch (error) {
      const message = error instanceof Error ? error.message : '导入失败'
      toast.error(message)
      throw error
    }
  }, [projectId, runReferenceMutationWithContentSync])

  const handleRegenerateReferenceImage = useCallback(async (referenceId: string | number) => {
    const imageProvider = stageConfig.imageProvider || settings?.default_image_provider
    const referenceWan2gpInferenceSteps = getScopedWan2gpInferenceSteps(stageConfig, 't2i')
    try {
      await runStage('reference', stageConfig, {
        action: 'generate_images',
        only_reference_id: String(referenceId),
        force_regenerate: true,
        image_provider: imageProvider,
        ...(imageProvider === 'wan2gp'
          ? {
              image_wan2gp_preset: stageConfig.imageWan2gpPreset || settings?.image_wan2gp_preset,
              image_resolution: stageConfig.referenceImageResolution || settings?.image_wan2gp_reference_resolution,
              image_wan2gp_inference_steps: referenceWan2gpInferenceSteps,
            }
          : {
              image_model: stageConfig.imageModel || undefined,
              image_aspect_ratio: stageConfig.referenceAspectRatio,
              image_size: stageConfig.referenceImageSize,
            }),
        ...(stageConfig.imageStyle?.trim() ? { image_style: stageConfig.imageStyle.trim() } : {}),
      })
    } catch (error) {
      console.error('Failed to regenerate reference image:', error)
      toast.error('重新生成失败')
      throw error
    }
  }, [runStage, stageConfig, settings])

  const handleGenerateFrameDescription = useCallback(async (shotIndex: number) => {
    try {
      await runStage('first_frame_desc', stageConfig, {
        only_shot_index: shotIndex,
        single_take: isSingleTakeEnabled,
        use_reference_consistency: stageConfig.useReferenceConsistency,
      })
    } catch (error) {
      console.error('Failed to generate frame description:', error)
      toast.error('生成失败')
      throw error
    }
  }, [isSingleTakeEnabled, runStage, stageConfig])

  const handleGenerateVideoDescription = useCallback(async (shotIndex: number) => {
    try {
      await runStage('storyboard', stageConfig, {
        only_shot_index: shotIndex,
        single_take: isSingleTakeEnabled,
        use_first_frame_ref: effectiveUseFirstFrameRef,
        use_reference_image_ref: stageConfig.useReferenceImageRef,
      })
    } catch (error) {
      console.error('Failed to generate video description:', error)
      toast.error('生成失败')
      throw error
    }
  }, [effectiveUseFirstFrameRef, isSingleTakeEnabled, runStage, stageConfig])

  const handleRegenerateFrameImage = useCallback(async (shotIndex: number) => {
    try {
      await runStage('frame', stageConfig, {
        only_shot_index: shotIndex,
        single_take: isSingleTakeEnabled,
        force_regenerate: true,
      })
    } catch (error) {
      console.error('Failed to regenerate frame image:', error)
      toast.error('重新生成失败')
      throw error
    }
  }, [isSingleTakeEnabled, runStage, stageConfig])

  const handleReuseFirstFrameToOthers = useCallback(async () => {
    try {
      await api.stages.reuseFirstFrameToOthers(projectId)
      refetchStageScope('frame')
      toast.success('已复用到其他分镜')
    } catch (error) {
      console.error('Failed to reuse first frame image:', error)
      toast.error('复用失败')
      throw error
    }
  }, [projectId, refetchStageScope])

  const handleRegenerateAudio = useCallback(async (shotIndex: number) => {
    try {
      await runStage('audio', stageConfig, {
        only_shot_index: shotIndex,
        force_regenerate: true,
      })
    } catch (error) {
      console.error('Failed to regenerate audio:', error)
      toast.error('重新生成失败')
      throw error
    }
  }, [runStage, stageConfig])

  const handleRegenerateVideo = useCallback(async (shotIndex: number) => {
    try {
      const videoProvider = resolveVideoProvider(stageConfig.videoProvider, settings)
      await runStage('video', stageConfig, {
        only_shot_index: shotIndex,
        force_regenerate: true,
        single_take: isSingleTakeEnabled,
        video_provider: videoProvider,
        ...(videoProvider === 'wan2gp'
          ? {
              video_wan2gp_t2v_preset: stageConfig.videoWan2gpT2vPreset || settings?.video_wan2gp_t2v_preset,
              video_wan2gp_i2v_preset: stageConfig.videoWan2gpI2vPreset || settings?.video_wan2gp_i2v_preset,
              video_wan2gp_resolution: stageConfig.videoWan2gpResolution || settings?.video_wan2gp_resolution,
              video_wan2gp_inference_steps: stageConfig.videoWan2gpInferenceSteps,
              video_wan2gp_sliding_window_size: stageConfig.videoWan2gpSlidingWindowSize,
              max_concurrency: 1,
            }
          : {
              video_model: effectiveUseFirstFrameRef
                ? (stageConfig.videoModelI2v || stageConfig.videoModel)
                : stageConfig.videoModel,
              video_aspect_ratio: stageConfig.videoAspectRatio,
              resolution: stageConfig.resolution,
              ...(typeof stageConfig.maxConcurrency === 'number'
                && Number.isFinite(stageConfig.maxConcurrency)
                && stageConfig.maxConcurrency > 0
                ? { max_concurrency: Math.max(1, Math.floor(stageConfig.maxConcurrency)) }
                : {}),
            }),
        use_first_frame_ref: effectiveUseFirstFrameRef,
        use_reference_image_ref: stageConfig.useReferenceImageRef,
      })
    } catch (error) {
      console.error('Failed to regenerate video:', error)
      toast.error('重新生成失败')
      throw error
    }
  }, [effectiveUseFirstFrameRef, isSingleTakeEnabled, runStage, settings, stageConfig])

  const originalStoryboardShotCount = Array.isArray(stageData?.storyboard?.shots)
    ? stageData.storyboard.shots.length
    : 0

  const handleSmartMergeShots = useCallback(async () => {
    const confirmed = await confirmDialog({
      title: '智能合并分镜确认',
      description: '将清空当前分镜及已生成的分镜音频、首帧描述、首帧图和视频内容，然后重新生成合并后的分镜，是否继续？',
      confirmText: '继续',
      cancelText: '取消',
      variant: 'destructive',
    })
    if (!confirmed) return

    try {
      syncSmartMergePendingToCache()
      await runStage('storyboard', stageConfig, {
        action: 'smart_merge',
        original_shot_count: originalStoryboardShotCount,
      })
    } catch (error) {
      console.error('Failed to smart merge shots:', error)
      toast.error(error instanceof Error ? error.message : '智能合并分镜失败')
      throw error
    }
  }, [
    confirmDialog,
    originalStoryboardShotCount,
    runStage,
    stageConfig,
    syncSmartMergePendingToCache,
  ])

  const handleRunStageWithStoryboardConfirm = useCallback((
    stage: BackendStageType,
    config: StageConfig,
    inputData?: Record<string, unknown>
  ) => {
    const run = async () => {
      if (stage === 'storyboard' && hasStoryboardClearableOutputs) {
        const confirmed = await confirmDialog({
          title: '重新生成分镜确认',
          description: '重新生成分镜会清空已生成的分镜文案、分镜音频、视频描述、首帧图描述、首帧图和视频内容，是否继续？',
          confirmText: '继续',
          cancelText: '取消',
          variant: 'destructive',
        })
        if (!confirmed) return
        await clearAllShotContentWithoutConfirm()
      }
      await runStage(stage, config, inputData)
    }
    void run()
  }, [clearAllShotContentWithoutConfirm, confirmDialog, hasStoryboardClearableOutputs, runStage])

  return {
    handleDeleteContent,
    handleImportDialogue,
    handleSaveReference,
    handleDeleteReference,
    handleUploadReferenceImage,
    handleCreateReference,
    handleGenerateDescriptionFromImage,
    handleSaveFrameDescription,
    handleSaveFrameReferences,
    handleSaveVideoDescription,
    handleSaveVideoReferences,
    handleUploadFrameImage,
    handleDeleteFrameImage,
    handleSingleTakeModeTransition,
    handleDeleteVideo,
    handleClearAllAudio,
    handleClearAllFrameImages,
    handleClearAllVideos,
    handleClearAllShotContent,
    handleDeleteComposeVideo,
    handleInsertShots,
    handleMoveShot,
    handleDeleteShot,
    handleUpdateShot,
    handleUnlockContentByClearingShots,
    handleDeleteReferenceImage,
    handleImportReferencesFromLibrary,
    handleRegenerateReferenceImage,
    handleGenerateFrameDescription,
    handleGenerateVideoDescription,
    handleRegenerateFrameImage,
    handleReuseFirstFrameToOthers,
    handleRegenerateAudio,
    handleRegenerateVideo,
    handleSmartMergeShots,
    handleRunStageWithStoryboardConfirm,
  }
}
