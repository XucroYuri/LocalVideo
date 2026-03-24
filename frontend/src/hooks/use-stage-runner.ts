'use client'

import { useCallback, useRef } from 'react'
import type { MutableRefObject } from 'react'
import type { QueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api } from '@/lib/api-client'
import { queryKeys } from '@/lib/query-keys'
import { buildStageInputData } from '@/lib/stage-input-builder'
import {
  buildProviderHintInput,
  normalizeRunningMessage,
  runningFallbackMessage,
} from '@/lib/stage-runtime'
import type { StageConfig } from '@/types/stage-panel'
import type { Settings } from '@/types/settings'
import type { BackendStageType, Stage, StageProgressEvent } from '@/types/stage'

const CONTENT_CHAR_FILTER_REGEX = /[，。！？；：,.!?;:、'"()（）【】\[\]《》<>～~…—\-\s]/g
const DEFAULT_UNNAMED_PROJECT_TITLE_REGEX = /^未命名项目_\d{8}_\d{6}$/

function countContentChars(text: string): number {
  return text.replace(CONTENT_CHAR_FILTER_REGEX, '').length
}

interface UseStageRunnerOptions {
  projectId: number
  queryClient: QueryClient
  settings?: Settings
  stageDataForInput?: {
    content?: {
      roles?: Array<{
        id?: string
      }>
    }
    storyboard?: {
      shots?: Array<{
        speaker_id?: string
      }>
    }
    reference?: {
      references?: Array<{
        id?: string | number
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
    }
  }
  isRunning: boolean
  runningStage?: BackendStageType
  stageStreamDebugEnabled: boolean
  activeStageEventSourceRef: MutableRefObject<EventSource | null>
  activeFallbackPollingStopRef: MutableRefObject<(() => void) | null>
  lastCompletedItemsRef: MutableRefObject<number | undefined>
  lastItemCompleteRef: MutableRefObject<number | undefined>
  refetchStages: () => void
  refetchProject: () => void
  refetchSingleStageDetail: (stage: BackendStageType) => void
  setIsRunning: (value: boolean) => void
  setRunningStage: (value: BackendStageType | undefined) => void
  setRunningAction: (value: string | undefined) => void
  setProgress: (value: number) => void
  setProgressMessage: (value: string | undefined) => void
  setCompletedItems: (value: number | undefined) => void
  setTotalItems: (value: number | undefined) => void
  setSkippedItems: (value: number | undefined) => void
  setGeneratingShots: (
    value: Record<string, { status: string; progress: number }> | undefined
  ) => void
  setRunningShotIndex: (value: number | undefined) => void
  setRunningReferenceId: (value: string | undefined) => void
}

export function useStageRunner(options: UseStageRunnerOptions) {
  const {
    projectId,
    queryClient,
    settings,
    stageDataForInput,
    isRunning,
    runningStage,
    stageStreamDebugEnabled,
    activeStageEventSourceRef,
    activeFallbackPollingStopRef,
    lastCompletedItemsRef,
    lastItemCompleteRef,
    refetchStages,
    refetchProject,
    refetchSingleStageDetail,
    setIsRunning,
    setRunningStage,
    setRunningAction,
    setProgress,
    setProgressMessage,
    setCompletedItems,
    setTotalItems,
    setSkippedItems,
    setGeneratingShots,
    setRunningShotIndex,
    setRunningReferenceId,
  } = options
  const lastLiveFrameRefetchAtRef = useRef(0)
  const lastStageWarningsFingerprintRef = useRef<string | null>(null)
  const smartMergeOptimisticActiveRef = useRef(false)

  const emitStageWarnings = useCallback((
    stageType: BackendStageType,
    payload?: Record<string, unknown> | null,
  ) => {
    if (!payload) return
    const warnings = Array.isArray(payload.warnings)
      ? payload.warnings
        .map((item) => String(item || '').trim())
        .filter(Boolean)
      : []
    if (warnings.length <= 0) return

    const fingerprint = `${stageType}:${warnings.join('\n')}`
    if (lastStageWarningsFingerprintRef.current === fingerprint) {
      return
    }
    lastStageWarningsFingerprintRef.current = fingerprint
    toast.warning(warnings.join('；'))
  }, [])

  const buildReferenceActionSummaryMessage = useCallback((
    stageType: BackendStageType,
    stageData: Stage,
    status: 'completed' | 'failed' | 'skipped'
  ): string | null => {
    if (stageType === 'storyboard') {
      const inputData = (stageData.input_data || {}) as Record<string, unknown>
      const action = String(inputData.action || '').trim().toLowerCase()
      if (action === 'smart_merge' && status === 'completed') {
        const originalShotCountRaw = Number(inputData.original_shot_count)
        const originalShotCount = Number.isFinite(originalShotCountRaw)
          ? Math.max(0, Math.floor(originalShotCountRaw))
          : 0
        const outputData = (stageData.output_data || {}) as Record<string, unknown>
        const mergedShotCountRaw = Number(
          outputData.shot_count
          ?? (Array.isArray(outputData.shots) ? outputData.shots.length : 0)
        )
        const mergedShotCount = Number.isFinite(mergedShotCountRaw)
          ? Math.max(0, Math.floor(mergedShotCountRaw))
          : 0
        if (originalShotCount > 0 || mergedShotCount > 0) {
          return `智能合并完成：从 ${originalShotCount} 个镜头变成 ${mergedShotCount} 个镜头`
        }
        return '智能合并完成'
      }
      return null
    }

    if (stageType !== 'reference') return null
    const inputData = (stageData.input_data || {}) as Record<string, unknown>
    const action = String(inputData.action || 'generate_info').trim().toLowerCase()
    if (!action) return null

    if (action === 'generate_info' && status === 'completed') {
      const outputData = (stageData.output_data || {}) as Record<string, unknown>
      const parsedCount = Number(outputData.new_reference_count)
      const newReferenceCount = Number.isFinite(parsedCount) ? Math.max(0, Math.floor(parsedCount)) : 0
      let newReferenceNames = Array.isArray(outputData.new_reference_names)
        ? outputData.new_reference_names
          .map((item) => String(item || '').trim())
          .filter(Boolean)
        : []
      if (newReferenceNames.length === 0 && newReferenceCount > 0 && Array.isArray(outputData.references)) {
        const references = outputData.references
          .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
          .map((item) => String(item.name || '').trim())
          .filter(Boolean)
        if (references.length >= newReferenceCount) {
          newReferenceNames = references.slice(-newReferenceCount)
        }
      }
      if (newReferenceCount <= 0) {
        return '参考信息推断完成：新增 0 个'
      }
      const displayNames = newReferenceNames.slice(0, 8)
      const remain = Math.max(0, newReferenceNames.length - displayNames.length)
      const namesPart = displayNames.length > 0
        ? `（${displayNames.join('、')}${remain > 0 ? ` 等 ${newReferenceNames.length} 个` : ''}）`
        : ''
      return `参考信息推断完成：新增 ${newReferenceCount} 个${namesPart}`
    }

    if (action !== 'generate_images') return null

    const outputData = (stageData.output_data || {}) as Record<string, unknown>
    const toSafeInt = (value: unknown, fallback = 0) => {
      const parsed = Number(value)
      return Number.isFinite(parsed) ? Math.max(0, Math.floor(parsed)) : fallback
    }
    const totalItems = toSafeInt(stageData.total_items)
    const completedItems = toSafeInt(stageData.completed_items)
    const skippedItems = toSafeInt(stageData.skipped_items)
    const imageExistsSkipped = toSafeInt(outputData.image_exists_skipped_count)
    const missingDescriptionSkipped = toSafeInt(outputData.missing_description_skipped_count)
    const failedItems = Math.max(0, totalItems - completedItems)
    const targetCount = toSafeInt(outputData.target_count, totalItems + skippedItems)
    const prefix = status === 'completed'
      ? '参考图执行完成'
      : status === 'failed'
        ? '参考图执行失败'
        : '参考图已跳过'

    return `${prefix}：目标 ${targetCount}，完成 ${completedItems}，有图跳过 ${imageExistsSkipped}，无描述跳过 ${missingDescriptionSkipped}，失败 ${failedItems}`
  }, [])

  const syncProjectTitleFromGeneratedContent = useCallback(async (stageData: Stage) => {
    if (stageData.stage_type !== 'content') return

    const output = (stageData.output_data || {}) as Record<string, unknown>
    const generatedTitle = String(output.title || '').trim()
    if (!generatedTitle) return

    const currentProject = queryClient.getQueryData<{ title?: string }>(queryKeys.projects.detail(projectId))
    const currentTitle = String(currentProject?.title || '').trim()
    if (!DEFAULT_UNNAMED_PROJECT_TITLE_REGEX.test(currentTitle)) return
    if (currentTitle === generatedTitle) return

    try {
      const updatedProject = await api.projects.update(projectId, { title: generatedTitle })
      queryClient.setQueryData(queryKeys.projects.detail(projectId), updatedProject)
      await queryClient.invalidateQueries({ queryKey: queryKeys.projects.listBase })
    } catch (error) {
      console.error('Failed to sync project title from generated content:', error)
    }
  }, [projectId, queryClient])

  const applyStreamPartialToCache = useCallback((stage: BackendStageType, payload?: Record<string, unknown>) => {
    if (!payload) return

    if (stage === 'content') {
      queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'content'), (current) => {
        if (!current) return current
        const output = { ...((current.output_data || {}) as Record<string, unknown>) }
        const partialTitle = payload.partial_title
        const partialDialogueLines = payload.partial_dialogue_lines
        const partialContent = payload.partial_content
        let hasChanged = false

        if (typeof partialTitle === 'string' && partialTitle.trim()) {
          const nextTitle = partialTitle
          if (String(output.title || '') !== nextTitle) {
            output.title = nextTitle
            hasChanged = true
          }
        }
        if (Array.isArray(partialDialogueLines)) {
          const prevLines = Array.isArray(output.dialogue_lines) ? output.dialogue_lines : []
          const nextLinesSerialized = JSON.stringify(partialDialogueLines)
          const prevLinesSerialized = JSON.stringify(prevLines)
          if (nextLinesSerialized !== prevLinesSerialized) {
            output.dialogue_lines = partialDialogueLines
            hasChanged = true
          }
        }
        if (typeof partialContent === 'string' && partialContent.trim()) {
          if (String(output.content || '') !== partialContent) {
            output.content = partialContent
            hasChanged = true
          }
          const existingCharCount = Number(output.char_count)
          if (!Number.isFinite(existingCharCount)) {
            output.char_count = countContentChars(partialContent)
            hasChanged = true
          }
        }
        if (!hasChanged) return current
        return { ...current, output_data: output }
      })
      return
    }

    if (stage === 'storyboard') {
      const partialStoryboardShots = payload.partial_storyboard_shots
      if (!Array.isArray(partialStoryboardShots)) return
      queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'storyboard'), (current) => {
        if (!current) return current
        const output = { ...((current.output_data || {}) as Record<string, unknown>) }
        const currentShots = Array.isArray(output.shots)
          ? (output.shots as Record<string, unknown>[])
          : []
        const shots: Record<string, unknown>[] = [...currentShots]
        partialStoryboardShots.forEach((item) => {
          if (!item || typeof item !== 'object') return
          const shot = item as Record<string, unknown>
          const shotIndex = Number(shot.shot_index)
          if (!Number.isInteger(shotIndex) || shotIndex < 0) return
          while (shotIndex >= shots.length) {
            shots.push({})
          }
          const existing = shots[shotIndex] || {}
          const nextShot: Record<string, unknown> = {
            ...existing,
            shot_index: shotIndex,
          }
          const voiceContent = String(shot.voice_content || '').trim()
          if (voiceContent) nextShot.voice_content = voiceContent
          const speakerId = String(shot.speaker_id || '').trim()
          if (speakerId) nextShot.speaker_id = speakerId
          const speakerName = String(shot.speaker_name || '').trim()
          if (speakerName) nextShot.speaker_name = speakerName
          const videoPrompt = String(shot.video_prompt || '').trim()
          if (videoPrompt) nextShot.video_prompt = videoPrompt
          if (Array.isArray(shot.video_reference_slots)) {
            nextShot.video_reference_slots = shot.video_reference_slots
          }
          shots[shotIndex] = {
            ...nextShot,
          }
        })
        output.shots = shots
        return { ...current, output_data: output }
      })
      return
    }

    if (stage === 'first_frame_desc') {
      const partialFirstFrameShots = payload.partial_first_frame_shots
      if (!Array.isArray(partialFirstFrameShots)) return
      queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'storyboard'), (current) => {
        if (!current) return current
        const output = { ...((current.output_data || {}) as Record<string, unknown>) }
        const currentShots = Array.isArray(output.shots)
          ? (output.shots as Record<string, unknown>[])
          : []
        const shots: Record<string, unknown>[] = [...currentShots]
        partialFirstFrameShots.forEach((item) => {
          if (!item || typeof item !== 'object') return
          const shot = item as Record<string, unknown>
          const shotIndex = Number(shot.shot_index)
          const firstFrameDescription = String(shot.first_frame_description || '').trim()
          if (!Number.isInteger(shotIndex) || shotIndex < 0) return
          const hasReferenceSlots = Array.isArray(shot.first_frame_reference_slots)
          if (!firstFrameDescription && !hasReferenceSlots) return
          while (shotIndex >= shots.length) {
            shots.push({})
          }
          const existing = shots[shotIndex] || {}
          const nextShot: Record<string, unknown> = {
            ...existing,
            shot_index: shotIndex,
          }
          if (firstFrameDescription) {
            nextShot.first_frame_description = firstFrameDescription
          }
          if (hasReferenceSlots) {
            nextShot.first_frame_reference_slots = shot.first_frame_reference_slots
          }
          shots[shotIndex] = nextShot
        })
        output.shots = shots
        return { ...current, output_data: output }
      })
      return
    }

    if (stage === 'reference') {
      const partialReferences = payload.partial_references
      const partialReferenceId = typeof payload.partial_reference_id === 'string'
        ? payload.partial_reference_id.trim()
        : ''
      const partialReferenceDescription = typeof payload.partial_reference_description === 'string'
        ? payload.partial_reference_description.trim()
        : ''
      if (!Array.isArray(partialReferences) && (!partialReferenceId || !partialReferenceDescription)) return

      queryClient.setQueryData<Stage | null>(queryKeys.projectResources.stageDetail(projectId, 'reference'), (current) => {
        if (!current) return current
        const output = { ...((current.output_data || {}) as Record<string, unknown>) }
        let nextReferences: Record<string, unknown>[] = Array.isArray(output.references)
          ? (output.references as Record<string, unknown>[])
          : []

        if (Array.isArray(partialReferences)) {
          nextReferences = partialReferences
            .filter((item) => !!item && typeof item === 'object')
            .map((item) => ({ ...(item as Record<string, unknown>) }))
        }

        if (partialReferenceId && partialReferenceDescription) {
          nextReferences = nextReferences.map((item) => {
            const id = String(item.id || '').trim()
            if (id !== partialReferenceId) return item
            return {
              ...item,
              appearance_description: partialReferenceDescription,
              description: partialReferenceDescription,
            }
          })
        }

        output.references = nextReferences
        return { ...current, output_data: output }
      })
    }
  }, [projectId, queryClient])

  const stopActiveStageStream = useCallback(() => {
    if (activeStageEventSourceRef.current) {
      activeStageEventSourceRef.current.close()
      activeStageEventSourceRef.current = null
    }
    if (activeFallbackPollingStopRef.current) {
      activeFallbackPollingStopRef.current()
      activeFallbackPollingStopRef.current = null
    }
  }, [activeFallbackPollingStopRef, activeStageEventSourceRef])

  const clearRunningState = useCallback(() => {
    smartMergeOptimisticActiveRef.current = false
    setIsRunning(false)
    setRunningStage(undefined)
    setRunningAction(undefined)
    setRunningShotIndex(undefined)
    setRunningReferenceId(undefined)
    lastStageWarningsFingerprintRef.current = null
    lastCompletedItemsRef.current = undefined
    lastItemCompleteRef.current = undefined
    lastLiveFrameRefetchAtRef.current = 0
  }, [
    lastStageWarningsFingerprintRef,
    lastLiveFrameRefetchAtRef,
    lastCompletedItemsRef,
    lastItemCompleteRef,
    setIsRunning,
    setRunningAction,
    setRunningReferenceId,
    setRunningStage,
    setRunningShotIndex,
  ])

  const applyRunningStateFromStage = useCallback((stage: BackendStageType, stageData: Stage) => {
    queryClient.setQueryData<Stage>(
      queryKeys.projectResources.stageDetail(projectId, stage),
      (current) => {
        if (
          smartMergeOptimisticActiveRef.current
          && stage === 'storyboard'
          && current
        ) {
          const currentOutput = ((current.output_data || {}) as Record<string, unknown>)
          const nextOutput = ((stageData.output_data || {}) as Record<string, unknown>)
          return {
            ...stageData,
            output_data: {
              ...nextOutput,
              shots: Array.isArray(currentOutput.shots) ? currentOutput.shots : [],
              shot_count: typeof currentOutput.shot_count === 'number'
                ? currentOutput.shot_count
                : Array.isArray(currentOutput.shots)
                  ? currentOutput.shots.length
                  : 0,
            },
          }
        }
        return stageData
      }
    )
    setIsRunning(true)
    setRunningStage(stage)
    setProgress(stageData.progress ?? 0)
    setCompletedItems(stageData.completed_items)
    setTotalItems(stageData.total_items)
    setSkippedItems(stageData.skipped_items)

    const currentInput = stageData.input_data as
      | { action?: string; only_shot_index?: number; only_reference_id?: string | number }
      | undefined
    setRunningAction(currentInput?.action)
    setRunningShotIndex(
      typeof currentInput?.only_shot_index === 'number'
        ? currentInput.only_shot_index
        : undefined
    )
    setRunningReferenceId(
      stage === 'reference' && currentInput?.only_reference_id !== undefined
        ? String(currentInput.only_reference_id)
        : undefined
    )

    const output = stageData.output_data as
      | {
          generating_shots?: Record<string, { status: string; progress: number }>
          progress_message?: string
        }
      | undefined
    emitStageWarnings(stage, (output as Record<string, unknown> | undefined) ?? undefined)
    setGeneratingShots(output?.generating_shots)
    setProgressMessage(
      normalizeRunningMessage({
        stage,
        message: output?.progress_message,
        progress: stageData.progress ?? 0,
        inputData: (stageData.input_data as Record<string, unknown> | undefined) ?? undefined,
        outputData: (output as Record<string, unknown> | undefined) ?? undefined,
      })
    )
  }, [
    emitStageWarnings,
    projectId,
    queryClient,
    setCompletedItems,
    setGeneratingShots,
    setIsRunning,
    setProgress,
    setProgressMessage,
    setRunningAction,
    setRunningReferenceId,
    setRunningStage,
    setRunningShotIndex,
    setSkippedItems,
    setTotalItems,
  ])

  const startFallbackPolling = useCallback((stage: BackendStageType) => {
    const refetchRelatedStageDetails = (force = false) => {
      if (!force && smartMergeOptimisticActiveRef.current && stage === 'storyboard') {
        return
      }
      if (stage === 'video') {
        refetchSingleStageDetail('video')
        refetchSingleStageDetail('frame')
        return
      }
      if (stage === 'finalize') {
        refetchSingleStageDetail('compose')
        refetchSingleStageDetail('subtitle')
        refetchSingleStageDetail('burn_subtitle')
        refetchSingleStageDetail('finalize')
        return
      }
      refetchSingleStageDetail(stage)
    }

    let delay = 1000
    let elapsed = 0
    const maxDelay = 5000
    const maxElapsed = 15 * 60 * 1000
    let timeoutId: ReturnType<typeof setTimeout> | null = null
    let stopped = false

    const stopPolling = () => {
      stopped = true
      if (timeoutId) {
        clearTimeout(timeoutId)
        timeoutId = null
      }
      if (activeFallbackPollingStopRef.current === stopPolling) {
        activeFallbackPollingStopRef.current = null
      }
    }

    const pollOnce = async () => {
      if (stopped) return
      try {
        if (stage === 'finalize') {
          const stageTypes: BackendStageType[] = ['compose', 'subtitle', 'burn_subtitle', 'finalize']
          const stageRows = await Promise.all(stageTypes.map((stageType) => api.stages.get(projectId, stageType)))
          const runningRow = stageRows.find((item) => item.status === 'running')
          if (runningRow) {
            applyRunningStateFromStage(runningRow.stage_type as BackendStageType, runningRow)
          } else {
            const finalizeRow = stageRows.find((item) => item.stage_type === 'finalize')
            if (finalizeRow?.status === 'completed') {
              stopPolling()
              clearRunningState()
              setGeneratingShots(undefined)
              refetchStages()
              refetchRelatedStageDetails(true)
              emitStageWarnings('finalize', (finalizeRow.output_data as Record<string, unknown> | undefined) ?? undefined)
              refetchProject()
              toast.success('执行完成')
              return
            }
            if (finalizeRow?.status === 'failed') {
              stopPolling()
              clearRunningState()
              setGeneratingShots(undefined)
              refetchStages()
              refetchRelatedStageDetails(true)
              refetchProject()
              toast.error(`执行失败: ${finalizeRow.error_message || '未知错误'}`)
              return
            }
            if (finalizeRow?.status === 'skipped') {
              stopPolling()
              clearRunningState()
              setGeneratingShots(undefined)
              refetchStages()
              refetchRelatedStageDetails(true)
              refetchProject()
              toast.info('执行已跳过')
              return
            }
          }
        } else {
          const currentStage = await api.stages.get(projectId, stage)
          const status = currentStage.status
          if (status === 'running') {
            applyRunningStateFromStage(stage, currentStage)
          } else if (status === 'pending') {
          // Keep polling while queued, but do not force UI back into running state.
        } else if (status === 'completed') {
          stopPolling()
          clearRunningState()
          setGeneratingShots(undefined)
          refetchStages()
          refetchRelatedStageDetails(true)
          await syncProjectTitleFromGeneratedContent(currentStage)
          emitStageWarnings(stage, (currentStage.output_data as Record<string, unknown> | undefined) ?? undefined)
          refetchProject()
          const summary = buildReferenceActionSummaryMessage(stage, currentStage, 'completed')
          toast.success(summary || '执行完成')
          return
        } else if (status === 'failed') {
          stopPolling()
          clearRunningState()
          setGeneratingShots(undefined)
          refetchStages()
          refetchRelatedStageDetails(true)
          refetchProject()
          const summary = buildReferenceActionSummaryMessage(stage, currentStage, 'failed')
          if (summary) {
            const reason = currentStage.error_message ? `，原因：${currentStage.error_message}` : ''
            toast.error(`${summary}${reason}`)
          } else {
            toast.error(`执行失败: ${currentStage.error_message || '未知错误'}`)
          }
          return
        } else if (status === 'skipped') {
          stopPolling()
          clearRunningState()
          setGeneratingShots(undefined)
          refetchStages()
          refetchRelatedStageDetails(true)
          refetchProject()
          const summary = buildReferenceActionSummaryMessage(stage, currentStage, 'skipped')
            toast.info(summary || '执行已跳过')
            return
          }
        }
      } catch (pollError) {
        console.error('Fallback polling error:', pollError)
      }

      elapsed += delay
      if (elapsed >= maxElapsed) {
        stopPolling()
        clearRunningState()
        setGeneratingShots(undefined)
        return
      }
      delay = Math.min(maxDelay, delay + 1000)
      timeoutId = setTimeout(pollOnce, delay)
    }

    timeoutId = setTimeout(pollOnce, delay)
    return stopPolling
  }, [
    activeFallbackPollingStopRef,
    applyRunningStateFromStage,
    emitStageWarnings,
    clearRunningState,
    syncProjectTitleFromGeneratedContent,
    projectId,
    refetchProject,
    refetchSingleStageDetail,
    refetchStages,
    setGeneratingShots,
    buildReferenceActionSummaryMessage,
  ])

  const runStage = useCallback(
    async (stage: BackendStageType, config?: StageConfig, inputData?: Record<string, unknown>) => {
      const relatedStages: BackendStageType[] = (() => {
        if (stage === 'video') return ['video', 'frame']
        if (stage === 'storyboard') {
          return ['storyboard', 'audio', 'frame', 'video', 'compose', 'subtitle', 'burn_subtitle', 'finalize']
        }
        if (stage === 'finalize') return ['compose', 'subtitle', 'burn_subtitle', 'finalize']
        return [stage]
      })()

      const refetchRelatedStageDetails = (force = false) => {
        if (!force && smartMergeOptimisticActiveRef.current && stage === 'storyboard') {
          return
        }
        relatedStages.forEach((stageType) => refetchSingleStageDetail(stageType))
      }

      if (isRunning) {
        const stageNames: Partial<Record<BackendStageType, string>> = {
          content: '生成文案',
          storyboard: '生成分镜',
          audio: '生成音频',
          reference: '生成参考',
          first_frame_desc: '生成首帧描述',
          frame: '生成首帧图',
          video: '生成视频',
          compose: '母版合成',
          subtitle: '生成字幕',
          burn_subtitle: '烧录字幕',
          finalize: '生成成片',
        }
        const runningName = runningStage ? stageNames[runningStage] || runningStage : '任务'
        toast.info(`当前正在${runningName}，请等待完成后再试`)
        return
      }

      stopActiveStageStream()

      setIsRunning(true)
      setRunningStage(stage)
      setRunningAction(inputData?.action as string | undefined)
    setRunningShotIndex(
        typeof inputData?.only_shot_index === 'number' ? inputData.only_shot_index : undefined
      )
      setRunningReferenceId(
        stage === 'reference' && inputData?.only_reference_id !== undefined
          ? String(inputData.only_reference_id)
          : undefined
      )
      setProgress(0)
      const initialProviderHint = buildProviderHintInput({
        stage,
        inputData: inputData ? ({ ...inputData } as Record<string, unknown>) : undefined,
        config,
        settings,
      })
      setProgressMessage(
        runningFallbackMessage({
          stage,
          progress: 0,
          inputData: initialProviderHint,
        })
      )
      setCompletedItems(undefined)
      setTotalItems(undefined)
      setSkippedItems(undefined)
      setGeneratingShots(undefined)
      lastStageWarningsFingerprintRef.current = null
      lastCompletedItemsRef.current = undefined
      lastItemCompleteRef.current = undefined
      lastLiveFrameRefetchAtRef.current = 0

      try {
        if (stage === 'content' && config) {
          const updateData: Record<string, unknown> = {}
          if (config.style !== undefined) updateData.style = config.style
          if (config.targetDuration) updateData.target_duration = config.targetDuration
          if (Object.keys(updateData).length > 0) {
            await api.projects.update(projectId, updateData)
          }
        }

        const mergedInputData = buildStageInputData({
          stage,
          config,
          settings,
          inputData,
          stageData: stageDataForInput,
        })
        smartMergeOptimisticActiveRef.current = (
          stage === 'storyboard'
          && String(mergedInputData.action || '').trim().toLowerCase() === 'smart_merge'
        )
        if (stage === 'video') {
          const rawProvider = String(
            config?.videoProvider
            || settings?.default_video_provider
            || ''
          ).trim()
          const rawModel = String(
            (mergedInputData.use_first_frame_ref
              ? (config?.videoModelI2v || config?.videoModel)
              : config?.videoModel)
            || ''
          ).trim()
          const mergedProvider = String(mergedInputData.video_provider || '').trim()
          const mergedModel = String(mergedInputData.video_model || '').trim()
          const mergedT2vPreset = String(mergedInputData.video_wan2gp_t2v_preset || '').trim()
          const mergedI2vPreset = String(mergedInputData.video_wan2gp_i2v_preset || '').trim()
          const resolvedMergedModel = mergedModel || mergedI2vPreset || mergedT2vPreset
          const modelAdjusted = Boolean(rawModel && resolvedMergedModel && rawModel !== resolvedMergedModel)
          console.info('[StageInput][VideoModelResolve]', {
            stage,
            single_take: Boolean(mergedInputData.single_take),
            use_first_frame_ref: Boolean(mergedInputData.use_first_frame_ref),
            ui_provider: rawProvider || undefined,
            ui_model: rawModel || undefined,
            request_provider: mergedProvider || undefined,
            request_model: resolvedMergedModel || undefined,
            adjusted: modelAdjusted,
            request_payload: {
              video_model: mergedModel || undefined,
              video_wan2gp_t2v_preset: mergedT2vPreset || undefined,
              video_wan2gp_i2v_preset: mergedI2vPreset || undefined,
            },
          })
        }

        const streamUrl = api.stages.streamUrl(projectId, stage, true, mergedInputData)
        const eventSource = new EventSource(streamUrl)
        activeStageEventSourceRef.current = eventSource
        let terminalHandled = false

        const closeEventSource = () => {
          eventSource.close()
          if (activeStageEventSourceRef.current === eventSource) {
            activeStageEventSourceRef.current = null
          }
        }

        const finalizeStageFromBackend = async (statusHint?: string, terminalMessage?: string) => {
          if (terminalHandled) return
          terminalHandled = true
          closeEventSource()
          const hintedStatus = String(statusHint || '').toLowerCase()
          try {
            const stageData = await api.stages.get(projectId, stage)
            queryClient.setQueryData<Stage | null>(
              queryKeys.projectResources.stageDetail(projectId, stage),
              stageData
            )
            const stageStatus = String(stageData.status || '').toLowerCase()
            if (stageStreamDebugEnabled) {
              console.log('[Stage SSE][FINAL STATUS]', {
                stage,
                status: stageData.status,
                progress: stageData.progress,
                total_items: stageData.total_items,
                completed_items: stageData.completed_items,
                skipped_items: stageData.skipped_items,
                status_hint: statusHint,
              })
            }
            refetchStages()
            refetchRelatedStageDetails(true)
            await syncProjectTitleFromGeneratedContent(stageData)
            emitStageWarnings(stage, (stageData.output_data as Record<string, unknown> | undefined) ?? undefined)
            refetchProject()
            const effectiveStatus = (
              stageStatus === 'completed'
              || stageStatus === 'failed'
              || stageStatus === 'skipped'
            )
              ? stageStatus
              : (
                  hintedStatus === 'completed'
                  || hintedStatus === 'failed'
                  || hintedStatus === 'skipped'
                )
                ? hintedStatus
                : ''
            if (effectiveStatus === 'completed') {
              clearRunningState()
              setGeneratingShots(undefined)
              const summary = buildReferenceActionSummaryMessage(stage, stageData, 'completed')
              toast.success(summary || '执行完成')
              return
            }
            if (effectiveStatus === 'failed') {
              clearRunningState()
              setGeneratingShots(undefined)
              const summary = buildReferenceActionSummaryMessage(stage, stageData, 'failed')
              const reasonText = String(stageData.error_message || terminalMessage || '').trim()
              if (summary) {
                const reason = reasonText ? `，原因：${reasonText}` : ''
                toast.error(`${summary}${reason}`)
              } else {
                toast.error(`执行失败: ${reasonText || '未知错误'}`)
              }
              return
            }
            if (effectiveStatus === 'skipped') {
              clearRunningState()
              setGeneratingShots(undefined)
              const summary = buildReferenceActionSummaryMessage(stage, stageData, 'skipped')
              toast.info(summary || '执行已跳过')
              return
            }
            const stopPolling = startFallbackPolling(stage)
            activeFallbackPollingStopRef.current = stopPolling
          } catch (e) {
            console.error('Failed to check stage status:', e)
            if (
              hintedStatus === 'completed'
              || hintedStatus === 'failed'
              || hintedStatus === 'skipped'
            ) {
              clearRunningState()
              setGeneratingShots(undefined)
              if (hintedStatus === 'completed') {
                toast.success('执行完成')
              } else if (hintedStatus === 'skipped') {
                toast.info('执行已跳过')
              } else {
                const reasonText = String(terminalMessage || '').trim()
                toast.error(`执行失败: ${reasonText || '未知错误'}`)
              }
              return
            }
            const stopPolling = startFallbackPolling(stage)
            activeFallbackPollingStopRef.current = stopPolling
          }
        }

        eventSource.onmessage = (event) => {
          if (event.data === '[DONE]') {
            if (stageStreamDebugEnabled) {
              console.log('[Stage SSE][DONE]', { stage, projectId })
            }
            void finalizeStageFromBackend()
            return
          }

          try {
            const data: StageProgressEvent = JSON.parse(event.data)
            const currentEventStage = (data.stage_type || stage) as BackendStageType
            const streamPayload = data.data as Record<string, unknown> | undefined
            let shouldRefetchProgress = false
            applyStreamPartialToCache(currentEventStage, streamPayload)
            emitStageWarnings(currentEventStage, streamPayload)
            if (stageStreamDebugEnabled) {
              console.log('[Stage SSE][MSG]', {
                stage,
                event_stage: currentEventStage,
                progress: data.progress,
                message: data.message,
                data: streamPayload,
                item_complete: data.item_complete,
                total_items: data.total_items,
                completed_items: data.completed_items,
                skipped_items: data.skipped_items,
                generating_shots: data.generating_shots,
              })
            }
            setRunningStage(currentEventStage)
            setProgress(data.progress)
            if (data.message) {
              setProgressMessage(
                normalizeRunningMessage({
                  stage: currentEventStage,
                  message: data.message,
                  progress: data.progress ?? 0,
                  inputData: mergedInputData as Record<string, unknown>,
                })
              )
            }
            const hasCompletedItemsSignal = data.completed_items !== undefined
            if (hasCompletedItemsSignal) {
              const prevCompleted = lastCompletedItemsRef.current
              setCompletedItems(data.completed_items)
              lastCompletedItemsRef.current = data.completed_items
              if (prevCompleted === undefined || data.completed_items !== prevCompleted) {
                shouldRefetchProgress = true
              }
            }
            if (data.total_items !== undefined) {
              setTotalItems(data.total_items)
            }
            if (data.skipped_items !== undefined) {
              setSkippedItems(data.skipped_items)
            }
            if (data.generating_shots !== undefined) {
              setGeneratingShots(data.generating_shots || undefined)
            }
            if (currentEventStage === 'video') {
              const now = Date.now()
              if (now - lastLiveFrameRefetchAtRef.current >= 1200) {
                lastLiveFrameRefetchAtRef.current = now
                refetchSingleStageDetail('frame')
              }
            }
            if (
              data.item_complete !== undefined
              && data.item_complete !== null
              && data.item_complete >= 0
              && data.item_complete !== lastItemCompleteRef.current
            ) {
              lastItemCompleteRef.current = data.item_complete
              if (!hasCompletedItemsSignal) {
                shouldRefetchProgress = true
              }
            }
            if (shouldRefetchProgress) {
              refetchStages()
              refetchRelatedStageDetails()
            }
            const stageStatus = String(data.status || '').toLowerCase()
            if (
              stage === 'finalize'
              && currentEventStage !== 'finalize'
              && (stageStatus === 'completed' || stageStatus === 'failed' || stageStatus === 'skipped')
            ) {
              refetchSingleStageDetail(currentEventStage)
              return
            }
            if (stageStatus === 'completed' || stageStatus === 'failed' || stageStatus === 'skipped') {
              void finalizeStageFromBackend(stageStatus, data.message)
              return
            }
          } catch (e) {
            console.error('Failed to parse SSE message:', e)
          }
        }

        eventSource.onerror = async () => {
          if (terminalHandled) return
          if (stageStreamDebugEnabled) {
            console.warn('[Stage SSE][ERROR]', { stage, projectId })
          }
          closeEventSource()
          try {
            const stageData = await api.stages.get(projectId, stage)
            if (stageData.status === 'running') {
              applyRunningStateFromStage(stage, stageData)
              const stopPolling = startFallbackPolling(stage)
              activeFallbackPollingStopRef.current = stopPolling
              return
            } else if (stageData.status === 'pending') {
              const stopPolling = startFallbackPolling(stage)
              activeFallbackPollingStopRef.current = stopPolling
              return
            } else if (stageData.status === 'completed') {
              await syncProjectTitleFromGeneratedContent(stageData)
              emitStageWarnings(stage, (stageData.output_data as Record<string, unknown> | undefined) ?? undefined)
              const summary = buildReferenceActionSummaryMessage(stage, stageData, 'completed')
              toast.success(summary || '执行完成')
            } else if (stageData.status === 'failed') {
              const summary = buildReferenceActionSummaryMessage(stage, stageData, 'failed')
              if (summary) {
                const reason = stageData.error_message ? `，原因：${stageData.error_message}` : ''
                toast.error(`${summary}${reason}`)
              } else {
                toast.error(`执行失败: ${stageData.error_message || '未知错误'}`)
              }
            } else if (stageData.status === 'skipped') {
              const summary = buildReferenceActionSummaryMessage(stage, stageData, 'skipped')
              toast.info(summary || '执行已跳过')
            }
          } catch (e) {
            console.error('Failed to check stage status:', e)
            const stopPolling = startFallbackPolling(stage)
            activeFallbackPollingStopRef.current = stopPolling
            return
          }
          clearRunningState()
          setGeneratingShots(undefined)
          refetchStages()
          refetchRelatedStageDetails(true)
          refetchProject()
        }
      } catch (error) {
        console.error('Failed to start stage:', error)
        if (activeStageEventSourceRef.current) {
          activeStageEventSourceRef.current.close()
          activeStageEventSourceRef.current = null
        }
        smartMergeOptimisticActiveRef.current = false
        clearRunningState()
        toast.error('执行失败')
      }
    },
    [
      activeFallbackPollingStopRef,
      activeStageEventSourceRef,
      applyStreamPartialToCache,
      applyRunningStateFromStage,
      clearRunningState,
      isRunning,
      lastCompletedItemsRef,
      lastLiveFrameRefetchAtRef,
      lastItemCompleteRef,
      projectId,
      queryClient,
      refetchProject,
      refetchSingleStageDetail,
      refetchStages,
      runningStage,
      setCompletedItems,
      setGeneratingShots,
      setIsRunning,
      setProgress,
      setProgressMessage,
      setRunningAction,
      setRunningReferenceId,
      setRunningStage,
      setRunningShotIndex,
      setSkippedItems,
      setTotalItems,
      settings,
      stageDataForInput,
      stageStreamDebugEnabled,
      buildReferenceActionSummaryMessage,
      emitStageWarnings,
      startFallbackPolling,
      syncProjectTitleFromGeneratedContent,
      stopActiveStageStream,
    ]
  )

  return {
    stopActiveStageStream,
    clearRunningState,
    applyRunningStateFromStage,
    startFallbackPolling,
    runStage,
  }
}
