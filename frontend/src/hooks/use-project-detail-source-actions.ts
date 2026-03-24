import type { MutableRefObject } from 'react'
import { toast } from 'sonner'

import { api } from '@/lib/api-client'
import type { StageConfig } from '@/types/stage-panel'
import type { BackendStageType, StageProgressEvent } from '@/types/stage'
import type { Source } from '@/types/source'
import type { SourceImportFromTextLibraryResponse } from '@/types/text-library'

interface CreateSourceMutation {
  mutateAsync: (data: { type: 'search' | 'deep_research' | 'text'; title: string; content: string }) => Promise<Source>
}

interface UpdateSourceMutation {
  mutate: (params: { sourceId: number; data: { content?: string; selected?: boolean } }) => void
  mutateAsync: (params: { sourceId: number; data: { content?: string; selected?: boolean } }) => Promise<unknown>
}

interface DeleteSourceMutation {
  mutateAsync: (sourceId: number) => Promise<unknown>
}

interface ImportFromTextLibraryMutation {
  mutateAsync: (textLibraryIds: number[]) => Promise<SourceImportFromTextLibraryResponse>
}

interface CancelRunningTasksMutation {
  mutateAsync: () => Promise<{ cancelled_stage_tasks: number; cancelled_pipeline_tasks: number }>
}

interface CreateProjectDetailSourceActionsParams {
  projectId: number
  isRunning: boolean
  isSearching: boolean
  runningStage?: BackendStageType
  stageConfig: StageConfig
  activeSearchEventSourceRef: MutableRefObject<EventSource | null>
  manualCancelSuppressUntilRef: MutableRefObject<number>
  createSourceMutation: CreateSourceMutation
  updateSourceMutation: UpdateSourceMutation
  deleteSourceMutation: DeleteSourceMutation
  importFromTextLibraryMutation: ImportFromTextLibraryMutation
  cancelRunningTasksMutation: CancelRunningTasksMutation
  stopActiveStageStream: () => void
  refetchStages: () => void
  refetchProject: () => void
  refetchSingleStageDetail: (stage: BackendStageType) => void
  setIsSearching: (value: boolean) => void
  setIsRunning: (value: boolean) => void
  setRunningStage: (value: BackendStageType | undefined) => void
  setRunningAction: (value: string | undefined) => void
  setRunningShotIndex: (value: number | undefined) => void
  setRunningReferenceId: (value: string | number | undefined) => void
  setGeneratingShots: (value: Record<string, { status: string; progress: number }> | undefined) => void
  setCompletedItems: (value: number | undefined) => void
  setTotalItems: (value: number | undefined) => void
  setSkippedItems: (value: number | undefined) => void
  setProgress: (value: number) => void
  setProgressMessage: (value: string | undefined) => void
  stageStreamDebugEnabled: boolean
  formatResearchDisplayContent: (raw: string) => string
}

export function useProjectDetailSourceActions(params: CreateProjectDetailSourceActionsParams) {
  const {
    projectId,
    isRunning,
    isSearching,
    runningStage,
    stageConfig,
    activeSearchEventSourceRef,
    manualCancelSuppressUntilRef,
    createSourceMutation,
    updateSourceMutation,
    deleteSourceMutation,
    importFromTextLibraryMutation,
    cancelRunningTasksMutation,
    stopActiveStageStream,
    refetchStages,
    refetchProject,
    refetchSingleStageDetail,
    setIsSearching,
    setIsRunning,
    setRunningStage,
    setRunningAction,
    setRunningShotIndex,
    setRunningReferenceId,
    setGeneratingShots,
    setCompletedItems,
    setTotalItems,
    setSkippedItems,
    setProgress,
    setProgressMessage,
    stageStreamDebugEnabled,
    formatResearchDisplayContent,
  } = params

  const handleSearch = async (keywords: string, searchType: 'web' | 'deep') => {
    if (isRunning && !isSearching && runningStage !== 'research') {
      toast.info('当前有生成任务进行中，请先中断或等待完成')
      return
    }

    if (activeSearchEventSourceRef.current) {
      activeSearchEventSourceRef.current.close()
      activeSearchEventSourceRef.current = null
    }

    setIsSearching(true)
    setIsRunning(true)
    setRunningStage('research')
    setRunningAction(undefined)
    setRunningShotIndex(undefined)
    setRunningReferenceId(undefined)
    setGeneratingShots(undefined)
    setCompletedItems(undefined)
    setTotalItems(undefined)
    setSkippedItems(undefined)
    setProgress(0)
    setProgressMessage('正在检索网页信息...')

    const modeLabel = searchType === 'deep' ? 'Deep Research' : 'Web Search'
    const selectedLlmProvider = String(stageConfig.llmProvider || '').trim()
    const selectedLlmModel = String(stageConfig.llmModel || '').trim()
    const llmInputOverrides = {
      ...(selectedLlmProvider ? { llm_provider: selectedLlmProvider } : {}),
      ...(selectedLlmModel ? { llm_model: selectedLlmModel } : {}),
    }

    const searchInputData = searchType === 'deep'
      ? {
          search_mode: 'deep',
          research_stream: true,
          research_model: 'auto',
          poll_interval_seconds: 6,
          poll_timeout_seconds: 900,
          stream_idle_timeout_seconds: 45,
          stream_timeout_seconds: 600,
          ...llmInputOverrides,
        }
      : {
          search_mode: 'web',
          llm_stream: true,
          ...llmInputOverrides,
        }

    try {
      await api.projects.update(projectId, { keywords })

      const tempSource = await createSourceMutation.mutateAsync({
        type: searchType === 'deep' ? 'deep_research' : 'search',
        title: `搜索: ${keywords}`,
        content: `正在通过 ${modeLabel} 搜索关键词: ${keywords}...`,
      })

      const streamUrl = api.stages.streamUrl(projectId, 'research', true, searchInputData)
      const eventSource = new EventSource(streamUrl)
      activeSearchEventSourceRef.current = eventSource
      let finalized = false
      let finalStageHandled = false
      let lastSourceMessage = ''
      let sourceFlushTimer: ReturnType<typeof setTimeout> | null = null
      let fallbackPollTimer: ReturnType<typeof setTimeout> | null = null
      let queuedSourceMessage: string | null = null
      let lastSourceFlushAt = 0
      const sourceFlushIntervalMs = 2000
      const terminalStatuses = new Set(['completed', 'failed', 'skipped'])

      const flushSourceMessage = () => {
        if (!queuedSourceMessage || !tempSource.id) return
        const nextMessage = queuedSourceMessage
        queuedSourceMessage = null
        lastSourceFlushAt = Date.now()
        updateSourceMutation.mutate({
          sourceId: tempSource.id,
          data: { content: nextMessage },
        })
      }

      const queueSourceMessage = (nextMessage: string) => {
        queuedSourceMessage = nextMessage
        const elapsed = Date.now() - lastSourceFlushAt
        if (elapsed >= sourceFlushIntervalMs) {
          if (sourceFlushTimer) {
            clearTimeout(sourceFlushTimer)
            sourceFlushTimer = null
          }
          flushSourceMessage()
          return
        }
        if (!sourceFlushTimer) {
          sourceFlushTimer = setTimeout(() => {
            sourceFlushTimer = null
            flushSourceMessage()
          }, sourceFlushIntervalMs - elapsed)
        }
      }

      const cleanupSearchRuntime = () => {
        if (sourceFlushTimer) {
          clearTimeout(sourceFlushTimer)
          sourceFlushTimer = null
        }
        if (fallbackPollTimer) {
          clearTimeout(fallbackPollTimer)
          fallbackPollTimer = null
        }
      }

      const finalizeSearch = () => {
        if (finalized) return false
        finalized = true
        eventSource.close()
        if (activeSearchEventSourceRef.current === eventSource) {
          activeSearchEventSourceRef.current = null
        }
        cleanupSearchRuntime()
        flushSourceMessage()
        setIsSearching(false)
        setIsRunning(false)
        setRunningStage(undefined)
        setRunningAction(undefined)
        refetchStages()
        refetchProject()
        return true
      }

      const applyFinalStageResult = (
        stageStatus: string,
        stageError: string,
        stageReport: string,
        fallbackMessage: string
      ) => {
        if (finalStageHandled) return
        finalStageHandled = true

        if (stageStatus === 'completed') {
          const nextContent = formatResearchDisplayContent(stageReport || fallbackMessage)
          if (nextContent && tempSource.id) {
            updateSourceMutation.mutate({
              sourceId: tempSource.id,
              data: { content: nextContent },
            })
          }
          toast.success(`${modeLabel} 完成`)
          return
        }

        if (stageStatus === 'failed') {
          const err = stageError || fallbackMessage || '未知错误'
          if (tempSource.id) {
            updateSourceMutation.mutate({
              sourceId: tempSource.id,
              data: { content: `${modeLabel} 失败: ${err}` },
            })
          }
          toast.error(`${modeLabel} 失败: ${err}`)
          return
        }

        if (stageStatus === 'skipped') {
          if (fallbackMessage && tempSource.id) {
            updateSourceMutation.mutate({
              sourceId: tempSource.id,
              data: { content: fallbackMessage },
            })
          }
          toast.info(`${modeLabel} 已跳过`)
        }
      }

      const syncFinalStage = (fallbackStatus?: string, fallbackMessage?: string) => {
        void api.stages.get(projectId, 'research')
          .then((stage) => {
            const output = (stage.output_data ?? {}) as Record<string, unknown>
            const stageReport = typeof output.report === 'string' ? output.report : ''
            const progressMessage = typeof output.progress_message === 'string' ? output.progress_message : ''
            const partialReport = typeof output.partial_report === 'string' ? output.partial_report : ''
            if (typeof stage.progress === 'number') setProgress(stage.progress)
            if (progressMessage) setProgressMessage(progressMessage)
            applyFinalStageResult(
              String(stage.status || '').toLowerCase(),
              stage.error_message || '',
              stageReport,
              fallbackMessage || partialReport || progressMessage || ''
            )
          })
          .catch(() => {
            const fallback = String(fallbackStatus || '').toLowerCase()
            applyFinalStageResult(
              fallback,
              fallbackMessage || '',
              '',
              fallbackMessage || ''
            )
          })
      }

      const scheduleFallbackPoll = () => {
        if (finalized) return
        if (fallbackPollTimer) clearTimeout(fallbackPollTimer)
        fallbackPollTimer = setTimeout(() => {
          if (finalized) return
          void api.stages.get(projectId, 'research')
            .then((stage) => {
              const stageStatus = String(stage.status || '').toLowerCase()
              const output = (stage.output_data ?? {}) as Record<string, unknown>
              const progressMessage = typeof output.progress_message === 'string' ? output.progress_message : ''
              const partialReport = typeof output.partial_report === 'string' ? output.partial_report : ''
              const nextContent = formatResearchDisplayContent(partialReport || progressMessage)
              if (typeof stage.progress === 'number') setProgress(stage.progress)
              if (progressMessage) setProgressMessage(progressMessage)

              if (nextContent && nextContent !== lastSourceMessage) {
                lastSourceMessage = nextContent
                queueSourceMessage(nextContent)
              }

              if (terminalStatuses.has(stageStatus)) {
                if (finalizeSearch()) {
                  const stageReport = typeof output.report === 'string' ? output.report : ''
                  applyFinalStageResult(
                    stageStatus,
                    stage.error_message || '',
                    stageReport,
                    partialReport || progressMessage || lastSourceMessage
                  )
                }
                return
              }

              scheduleFallbackPoll()
            })
            .catch(() => {
              scheduleFallbackPoll()
            })
        }, 3000)
      }

      scheduleFallbackPoll()

      eventSource.onmessage = (event) => {
        if (event.data === '[DONE]') {
          if (!finalizeSearch()) return
          syncFinalStage(undefined, lastSourceMessage)
          return
        }

        try {
          const data = JSON.parse(event.data) as StageProgressEvent
          const payload = data.data as { partial_report?: string } | undefined
          const partialReport = typeof payload?.partial_report === 'string'
            ? payload.partial_report
            : ''
          const nextContent = formatResearchDisplayContent(partialReport || data.message || '')
          if (typeof data.progress === 'number') setProgress(data.progress)
          if (data.message) setProgressMessage(data.message)
          if (nextContent && tempSource.id && nextContent !== lastSourceMessage) {
            lastSourceMessage = nextContent
            queueSourceMessage(nextContent)
          }
          const stageStatus = String(data.status || '').toLowerCase()
          if (terminalStatuses.has(stageStatus)) {
            if (!finalizeSearch()) return
            syncFinalStage(stageStatus, nextContent || lastSourceMessage)
          }
        } catch (error) {
          console.error('Failed to parse SSE message:', error)
        }
      }

      eventSource.onerror = () => {
        if (!finalizeSearch()) return
        syncFinalStage(undefined, lastSourceMessage)
      }
    } catch (error) {
      console.error('Search failed:', error)
      if (activeSearchEventSourceRef.current) {
        activeSearchEventSourceRef.current.close()
        activeSearchEventSourceRef.current = null
      }
      toast.error(`${modeLabel} 失败`)
      setIsSearching(false)
      setIsRunning(false)
      setRunningStage(undefined)
      setRunningAction(undefined)
    }
  }

  const handleAddText = async (text: string) => {
    try {
      await createSourceMutation.mutateAsync({
        type: 'text',
        title: text.slice(0, 30) + (text.length > 30 ? '...' : ''),
        content: text,
      })
      toast.success('文本已添加')
    } catch {
      toast.error('添加文本失败')
    }
  }

  const handleToggleSelected = async (sourceId: number, selected: boolean) => {
    try {
      await updateSourceMutation.mutateAsync({
        sourceId,
        data: { selected },
      })
    } catch {
      toast.error('更新失败')
    }
  }

  const handleDeleteSource = async (sourceId: number) => {
    await deleteSourceMutation.mutateAsync(sourceId)
  }

  const handleImportFromTextLibrary = async (textLibraryIds: number[]) => {
    const result = await importFromTextLibraryMutation.mutateAsync(textLibraryIds)
    const { created_count, skipped_count, failed_count } = result.summary
    if (failed_count > 0) {
      toast.warning(`导入完成：成功 ${created_count}，跳过 ${skipped_count}，失败 ${failed_count}`)
    } else {
      toast.success(`导入完成：成功 ${created_count}，跳过 ${skipped_count}`)
    }
    return result
  }

  const handleCancelAllRunningTasks = async () => {
    if (!isRunning && !isSearching) return
    manualCancelSuppressUntilRef.current = Date.now() + 15_000
    if (activeSearchEventSourceRef.current) {
      activeSearchEventSourceRef.current.close()
      activeSearchEventSourceRef.current = null
    }
    stopActiveStageStream()
    const stageToRefresh = runningStage ?? (isSearching ? 'research' as BackendStageType : undefined)
    try {
      const result = await cancelRunningTasksMutation.mutateAsync()
      setIsRunning(false)
      setIsSearching(false)
      setRunningStage(undefined)
      setRunningAction(undefined)
      setRunningShotIndex(undefined)
      setRunningReferenceId(undefined)
      setGeneratingShots(undefined)
      setProgressMessage('任务已手动中断')
      await Promise.all([
        Promise.resolve().then(() => refetchStages()),
        stageToRefresh
          ? Promise.resolve().then(() => refetchSingleStageDetail(stageToRefresh))
          : Promise.resolve(),
        Promise.resolve().then(() => refetchProject()),
      ])
      toast.success(`已中断任务（阶段任务 ${result.cancelled_stage_tasks}，流水线任务 ${result.cancelled_pipeline_tasks}）`)
    } catch (error) {
      manualCancelSuppressUntilRef.current = 0
      if (stageStreamDebugEnabled) {
        console.warn('[Cancel Running Tasks][ERROR]', error)
      }
      toast.error('中断任务失败')
    }
  }

  return {
    handleSearch,
    handleAddText,
    handleToggleSelected,
    handleDeleteSource,
    handleImportFromTextLibrary,
    handleCancelAllRunningTasks,
  }
}
