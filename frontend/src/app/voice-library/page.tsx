'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  FileAudio,
  Headphones,
  Link2,
  Loader2,
  Music2,
  Pause,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Trash2,
  Upload,
} from 'lucide-react'
import { toast } from 'sonner'

import { CatalogCreateCard } from '@/components/common/catalog-create-card'
import { CatalogListHeader } from '@/components/common/catalog-list-header'
import { CATALOG_GRID_CARD_CLASS, CATALOG_MAX_WIDTH_CLASS } from '@/components/common/catalog-layout'
import { CatalogQueryState } from '@/components/common/catalog-query-state'
import { CatalogSearchActions } from '@/components/common/catalog-search-actions'
import { useConfirmDialog } from '@/components/common/confirm-dialog-provider'
import { AudioPlayer } from '@/components/ui/audio-player'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useCatalogPagedQuery } from '@/hooks/use-catalog-paged-query'
import { useCatalogRowAction } from '@/hooks/use-catalog-row-action'
import { api } from '@/lib/api-client'
import { LIBRARY_BATCH_MAX_ITEMS } from '@/lib/library-limits'
import { queryKeys } from '@/lib/query-keys'
import { resolveApiResourceUrl } from '@/lib/media-url'
import { sortVoiceLibraryItems } from '@/lib/catalog-sort'
import { cn } from '@/lib/utils'
import type { VoiceLibraryImportAudioRow, VoiceLibraryItem } from '@/types/voice-library'

interface VoiceEditorDraft {
  name: string
  reference_text: string
  audio_file: File | null
  audio_url: string | null
  source_url: string
}

interface AudioImportRow {
  id: string
  file: File
  name: string
  auto_parse_text: boolean
  preview_url: string
}

type ImportMethod = 'audio_with_text' | 'audio_files' | 'video_link'
type VoiceSourceChannel = 'audio_with_text' | 'audio_file' | 'video_link' | 'builtin'

function getNameLength(value: string): number {
  return Array.from(value.trim()).length
}

function createEmptyEditorDraft(): VoiceEditorDraft {
  return {
    name: '',
    reference_text: '',
    audio_file: null,
    audio_url: null,
    source_url: '',
  }
}

function isFieldProcessing(status: VoiceLibraryItem['name_status'] | undefined): boolean {
  return status === 'pending' || status === 'running'
}

function isFieldFailed(status: VoiceLibraryItem['name_status'] | undefined): boolean {
  return status === 'failed'
}

function isFieldCanceled(status: VoiceLibraryItem['name_status'] | undefined): boolean {
  return status === 'canceled'
}

function isItemReady(item: VoiceLibraryItem | null | undefined): boolean {
  if (!item) return false
  return item.name_status === 'ready' && item.reference_text_status === 'ready' && !item.error_message
}

function isItemFailed(item: VoiceLibraryItem): boolean {
  return !!(item.error_message || isFieldFailed(item.name_status) || isFieldFailed(item.reference_text_status))
}

function isItemCanceled(item: VoiceLibraryItem): boolean {
  return isFieldCanceled(item.name_status) || isFieldCanceled(item.reference_text_status)
}

function isItemProcessing(item: VoiceLibraryItem): boolean {
  return isFieldProcessing(item.name_status) || isFieldProcessing(item.reference_text_status)
}

function getCardTagLabel(item: VoiceLibraryItem): string {
  const sourceChannel = (item.source_channel || 'audio_file') as VoiceSourceChannel
  if (item.is_builtin || sourceChannel === 'builtin') return '内置'
  if (sourceChannel === 'video_link') return '解析'
  return '导入'
}

function isBuiltinItem(item: VoiceLibraryItem): boolean {
  const sourceChannel = (item.source_channel || 'audio_file') as VoiceSourceChannel
  return item.is_builtin || sourceChannel === 'builtin'
}

function extractProgressPercent(message: string | null | undefined): number | null {
  const normalized = String(message || '')
  const matched = normalized.match(/(\d{1,3})\s*%/)
  if (!matched) return null
  const value = Number.parseInt(matched[1] || '', 10)
  if (!Number.isFinite(value)) return null
  return Math.max(0, Math.min(100, value))
}

function isJobRunning(status: 'pending' | 'running' | 'completed' | 'failed' | 'canceled' | undefined): boolean {
  return status === 'pending' || status === 'running'
}

function parseTimecode(value: string): number | null {
  const text = value.trim()
  if (!text) return null

  if (/^\d+(\.\d+)?$/.test(text)) {
    const sec = Number(text)
    if (!Number.isFinite(sec) || sec < 0) throw new Error('时间不能为负数')
    return sec
  }

  const parts = text.split(':')
  if (parts.length !== 2 && parts.length !== 3) {
    throw new Error('时间格式需为 HH:MM:SS 或 MM:SS')
  }

  const numbers = parts.map((part) => Number(part))
  if (numbers.some((one) => !Number.isFinite(one) || one < 0)) {
    throw new Error('时间格式不正确')
  }

  if (parts.length === 2) {
    return numbers[0] * 60 + numbers[1]
  }
  return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
}

export default function VoiceLibraryPage() {
  const queryClient = useQueryClient()
  const confirmDialog = useConfirmDialog()

  const editAudioInputRef = useRef<HTMLInputElement | null>(null)
  const methodAudioInputRef = useRef<HTMLInputElement | null>(null)
  const methodAudioTextInputRef = useRef<HTMLInputElement | null>(null)

  const updateEnabledAction = useCatalogRowAction<number>()
  const deletingAction = useCatalogRowAction<number>()
  const retryAction = useCatalogRowAction<number>()

  const [showMethodDialog, setShowMethodDialog] = useState(false)

  const [showAudioWithTextDialog, setShowAudioWithTextDialog] = useState(false)
  const [audioWithTextFile, setAudioWithTextFile] = useState<File | null>(null)
  const [audioWithTextPreviewUrl, setAudioWithTextPreviewUrl] = useState('')
  const [audioWithTextReferenceText, setAudioWithTextReferenceText] = useState('')
  const [audioWithTextSubmitting, setAudioWithTextSubmitting] = useState(false)
  const audioWithTextPreviewObjectUrlRef = useRef<string | null>(null)

  const [showAudioFilesDialog, setShowAudioFilesDialog] = useState(false)
  const [audioImportRows, setAudioImportRows] = useState<AudioImportRow[]>([])
  const [audioImportPlayingRowId, setAudioImportPlayingRowId] = useState<string | null>(null)
  const [audioFilesSubmitting, setAudioFilesSubmitting] = useState(false)

  const [showVideoLinkDialog, setShowVideoLinkDialog] = useState(false)
  const [videoLink, setVideoLink] = useState('')
  const [videoStartTime, setVideoStartTime] = useState('')
  const [videoEndTime, setVideoEndTime] = useState('')
  const [videoLinkSubmitting, setVideoLinkSubmitting] = useState(false)
  const [activeJobIds, setActiveJobIds] = useState<string[]>([])
  const importEventSourceRef = useRef<EventSource | null>(null)

  const [editorOpen, setEditorOpen] = useState(false)
  const [editingItemId, setEditingItemId] = useState<number | null>(null)
  const [editorDraft, setEditorDraft] = useState<VoiceEditorDraft>(createEmptyEditorDraft)
  const [editorSubmitting, setEditorSubmitting] = useState(false)
  const [playingId, setPlayingId] = useState<number | null>(null)
  const audioRefs = useRef<Record<number, HTMLAudioElement | null>>({})

  const clearAudioWithTextPreview = useCallback(() => {
    if (!audioWithTextPreviewObjectUrlRef.current) return
    URL.revokeObjectURL(audioWithTextPreviewObjectUrlRef.current)
    audioWithTextPreviewObjectUrlRef.current = null
  }, [])

  const revokeAudioImportPreviewUrls = useCallback((rows: AudioImportRow[]) => {
    rows.forEach((row) => {
      if (row.preview_url) {
        URL.revokeObjectURL(row.preview_url)
      }
    })
  }, [])

  const resetAudioFilesImportDialog = useCallback(() => {
    setAudioImportPlayingRowId(null)
    setAudioImportRows((prev) => {
      revokeAudioImportPreviewUrls(prev)
      return []
    })
    if (methodAudioInputRef.current) {
      methodAudioInputRef.current.value = ''
    }
  }, [revokeAudioImportPreviewUrls])

  const {
    page,
    pageSize,
    searchText,
    items,
    total,
    totalPages,
    isLoading,
    isFetching,
    error,
    refetch,
    setPage,
    onSearchTextChange,
    onSearch,
    onPageSizeChange,
  } = useCatalogPagedQuery<VoiceLibraryItem>({
    getQueryKey: ({ searchQuery, page, pageSize }) => queryKeys.voiceLibrary.list(searchQuery, page, pageSize),
    queryFn: ({ page, dataPageSize, searchQuery }) =>
      api.voiceLibrary.list({ q: searchQuery, page, pageSize: dataPageSize }),
  })

  const sortedItems = useMemo(() => sortVoiceLibraryItems(items), [items])
  const liveEditingItem = useMemo(() => {
    if (!editingItemId) return null
    return sortedItems.find((item) => item.id === editingItemId) ?? null
  }, [editingItemId, sortedItems])
  const editingReady = isItemReady(liveEditingItem)

  useEffect(() => {
    if (!editorOpen || !liveEditingItem) return
    if (!editingReady) return

    const nextAudioUrl = resolveApiResourceUrl(liveEditingItem.audio_url) || null
    setEditorDraft((prev) => ({
      ...prev,
      name: liveEditingItem.name || prev.name,
      reference_text: liveEditingItem.reference_text || prev.reference_text,
      audio_url: nextAudioUrl,
      source_url: liveEditingItem.source_url || '',
    }))
  }, [editorOpen, liveEditingItem, editingReady])

  const trimmedName = useMemo(() => editorDraft.name.trim(), [editorDraft.name])
  const nameLength = useMemo(() => getNameLength(editorDraft.name), [editorDraft.name])
  const nameError = useMemo(() => {
    if (!trimmedName) return '名称不能为空'
    if (nameLength > 30) return '名称最多30个字符'
    return ''
  }, [nameLength, trimmedName])

  const invalidateVoiceLibrary = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.voiceLibrary.root }),
      queryClient.invalidateQueries({ queryKey: queryKeys.voiceLibrary.active }),
    ])
  }, [queryClient])

  const hasProcessingItems = useMemo(() => sortedItems.some((item) => isItemProcessing(item)), [sortedItems])
  const hasInterruptedItems = useMemo(
    () => sortedItems.some((item) => isItemCanceled(item) || isItemFailed(item)),
    [sortedItems]
  )

  const closeImportStream = useCallback(() => {
    if (!importEventSourceRef.current) return
    importEventSourceRef.current.close()
    importEventSourceRef.current = null
  }, [])

  useEffect(() => {
    if (!hasProcessingItems) return
    const timer = window.setInterval(() => {
      void refetch()
    }, 1800)
    return () => window.clearInterval(timer)
  }, [hasProcessingItems, refetch])

  useEffect(() => {
    if (playingId === null) return
    if (sortedItems.some((item) => item.id === playingId)) return
    setPlayingId(null)
  }, [playingId, sortedItems])

  useEffect(() => {
    if (activeJobIds.length === 0) return
    const timer = window.setInterval(() => {
      void Promise.all(activeJobIds.map((jobId) => api.voiceLibrary.getImportJob(jobId).then((job) => ({ jobId, job }))))
        .then((results) => {
          const finishedIds: string[] = []
          for (const { jobId, job } of results) {
            if (!isJobRunning(job.status)) {
              finishedIds.push(jobId)
              const canceledCount = Number(job.canceled_count || 0)
              if (job.success_count > 0 && job.failed_count === 0 && canceledCount === 0) {
                toast.success(`视频链接导入完成：成功 ${job.success_count}`)
              } else if (job.success_count > 0 && canceledCount > 0) {
                toast.warning(`视频链接导入完成：成功 ${job.success_count}，中断 ${canceledCount}`)
              } else if (job.success_count > 0) {
                toast.warning(`视频链接导入完成：成功 ${job.success_count}，失败 ${job.failed_count}`)
              } else if (canceledCount > 0 && job.failed_count === 0) {
                toast.info(`导入已中断：共 ${canceledCount}`)
              } else {
                toast.error(job.error_message || '视频链接导入失败')
              }
            }
          }
          if (finishedIds.length > 0) {
            setActiveJobIds((prev) => prev.filter((id) => !finishedIds.includes(id)))
            void invalidateVoiceLibrary()
          }
        })
        .catch(() => undefined)
    }, 2000)
    return () => window.clearInterval(timer)
  }, [activeJobIds, invalidateVoiceLibrary])

  useEffect(() => {
    let disposed = false
    let retryTimer: number | null = null
    let retryAttempt = 0

    const connectImportStream = () => {
      if (disposed) return
      closeImportStream()
      const eventSource = new EventSource(api.voiceLibrary.importEventsStreamUrl())
      importEventSourceRef.current = eventSource

      eventSource.onopen = () => {
        retryAttempt = 0
      }

      eventSource.addEventListener('import.update', (event) => {
        try {
          const payload = JSON.parse((event as MessageEvent).data) as {
            active_job_ids?: string[]
          }
          const ids = Array.isArray(payload.active_job_ids) ? payload.active_job_ids : []
          setActiveJobIds(ids)
          void invalidateVoiceLibrary()
        } catch {
          // ignore invalid payload
        }
      })

      eventSource.onerror = () => {
        if (importEventSourceRef.current !== eventSource) return
        eventSource.close()
        importEventSourceRef.current = null
        void invalidateVoiceLibrary()
        if (disposed) return
        const delay = Math.min(1000 * (2 ** retryAttempt), 10000)
        retryAttempt = Math.min(retryAttempt + 1, 4)
        if (retryTimer !== null) {
          window.clearTimeout(retryTimer)
        }
        retryTimer = window.setTimeout(() => {
          retryTimer = null
          connectImportStream()
        }, delay)
      }
    }

    connectImportStream()

    return () => {
      disposed = true
      if (retryTimer !== null) {
        window.clearTimeout(retryTimer)
      }
      closeImportStream()
    }
  }, [closeImportStream, invalidateVoiceLibrary])

  useEffect(() => {
    clearAudioWithTextPreview()
    if (!audioWithTextFile) {
      setAudioWithTextPreviewUrl('')
      return
    }
    const objectUrl = URL.createObjectURL(audioWithTextFile)
    audioWithTextPreviewObjectUrlRef.current = objectUrl
    setAudioWithTextPreviewUrl(objectUrl)
  }, [audioWithTextFile, clearAudioWithTextPreview])

  useEffect(() => {
    return () => {
      clearAudioWithTextPreview()
      revokeAudioImportPreviewUrls(audioImportRows)
      closeImportStream()
    }
  }, [audioImportRows, clearAudioWithTextPreview, closeImportStream, revokeAudioImportPreviewUrls])

  const openImportMethodDialog = () => {
    setShowMethodDialog(true)
  }

  const handleSelectMethod = (method: ImportMethod) => {
    setShowMethodDialog(false)
    if (method === 'audio_with_text') {
      clearAudioWithTextPreview()
      setAudioWithTextFile(null)
      setAudioWithTextReferenceText('')
      setShowAudioWithTextDialog(true)
      return
    }
    if (method === 'audio_files') {
      resetAudioFilesImportDialog()
      setShowAudioFilesDialog(true)
      return
    }
    setVideoLink('')
    setVideoStartTime('')
    setVideoEndTime('')
    setShowVideoLinkDialog(true)
  }

  const handleSubmitAudioWithText = async () => {
    if (!audioWithTextFile) {
      toast.error('请上传音频文件')
      return
    }
    const normalizedText = audioWithTextReferenceText.trim()
    if (!normalizedText) {
      toast.error('请填写参考文本')
      return
    }

    setAudioWithTextSubmitting(true)
    try {
      await api.voiceLibrary.importAudioWithText(audioWithTextFile, normalizedText)
      setShowAudioWithTextDialog(false)
      clearAudioWithTextPreview()
      setAudioWithTextFile(null)
      setAudioWithTextPreviewUrl('')
      setAudioWithTextReferenceText('')
      await invalidateVoiceLibrary()
      toast.success('已创建语音卡片，后台正在命名')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '导入失败')
    } finally {
      setAudioWithTextSubmitting(false)
      if (methodAudioTextInputRef.current) {
        methodAudioTextInputRef.current.value = ''
      }
    }
  }

  const handleSubmitAudioFiles = async () => {
    if (audioImportRows.length === 0) {
      toast.error('请至少选择1个音频文件')
      return
    }
    if (audioImportRows.length > LIBRARY_BATCH_MAX_ITEMS) {
      toast.error(`最多支持${LIBRARY_BATCH_MAX_ITEMS}个音频文件`)
      return
    }

    setAudioFilesSubmitting(true)
    try {
      const files = audioImportRows.map((row) => row.file)
      const rows: VoiceLibraryImportAudioRow[] = audioImportRows.map((row, index) => ({
        index,
        name: row.name.trim() || undefined,
        auto_parse_text: row.auto_parse_text,
      }))
      const result = await api.voiceLibrary.importAudioFiles(files, rows)
      setShowAudioFilesDialog(false)
      resetAudioFilesImportDialog()
      await invalidateVoiceLibrary()
      toast.success(`已创建 ${result.item_ids.length} 张语音卡片`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '导入失败')
    } finally {
      setAudioFilesSubmitting(false)
    }
  }

  const handleSubmitVideoLink = async () => {
    const normalizedUrl = videoLink.trim()
    if (!normalizedUrl) {
      toast.error('请输入视频链接')
      return
    }

    let start: number | null = null
    let end: number | null = null
    try {
      start = parseTimecode(videoStartTime)
      end = parseTimecode(videoEndTime)
      if (start !== null && end !== null && end - start > 60) {
        toast.error('开始-结束时间间隔不能超过1分钟')
        return
      }
      if (start !== null && end !== null && end <= start) {
        toast.error('结束时间必须大于开始时间')
        return
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '时间格式错误')
      return
    }

    setVideoLinkSubmitting(true)
    try {
      const result = await api.voiceLibrary.importVideoLink({
        url: normalizedUrl,
        start_time: videoStartTime.trim() || undefined,
        end_time: videoEndTime.trim() || undefined,
      })
      setShowVideoLinkDialog(false)
      setVideoLink('')
      setVideoStartTime('')
      setVideoEndTime('')
      setActiveJobIds((prev) => {
        const next = new Set(prev)
        const newIds = Array.isArray(result.job_ids) && result.job_ids.length > 0
          ? result.job_ids
          : [result.job_id]
        newIds.forEach((id) => next.add(id))
        return Array.from(next)
      })
      await invalidateVoiceLibrary()
      toast.success(`已创建 ${result.item_ids.length} 张语音卡片`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '导入失败')
    } finally {
      setVideoLinkSubmitting(false)
    }
  }

  const handleToggleEnabled = async (item: VoiceLibraryItem, nextEnabled: boolean) => {
    try {
      await updateEnabledAction.run({
        id: item.id,
        task: () => api.voiceLibrary.update(item.id, { is_enabled: nextEnabled }),
        invalidateQueryKeys: [queryKeys.voiceLibrary.root, queryKeys.voiceLibrary.active],
        errorMessage: (error) => error instanceof Error ? error.message : '更新启用状态失败',
      })
    } catch {
      // toast handled in hook
    }
  }

  const handleDelete = async (item: VoiceLibraryItem) => {
    if (isBuiltinItem(item)) {
      toast.info('内置语音卡片不可删除')
      return
    }
    const confirmed = await confirmDialog({
      title: '删除语音卡片',
      description: `确定删除语音卡片「${item.name}」吗？`,
      confirmText: '删除',
      cancelText: '取消',
      variant: 'destructive',
    })
    if (!confirmed) return

    try {
      await deletingAction.run({
        id: item.id,
        task: () => api.voiceLibrary.delete(item.id),
        invalidateQueryKeys: [queryKeys.voiceLibrary.root, queryKeys.voiceLibrary.active],
        successMessage: '已删除',
        errorMessage: (error) => error instanceof Error ? error.message : '删除失败',
      })
    } catch {
      // toast handled in hook
    }
  }

  const handleCancelAllImports = async () => {
    setActiveJobIds([])
    try {
      const result = await api.voiceLibrary.cancelAllImportJobs()
      if (result.affected_tasks > 0) {
        toast.success(`已中断 ${result.affected_tasks} 个语音任务`)
      } else {
        toast.info('当前没有可中断的语音任务')
      }
      await invalidateVoiceLibrary()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '中断任务失败')
    }
  }

  const handleRestartInterruptedImports = async () => {
    try {
      const result = await api.voiceLibrary.restartInterruptedImportTasks()
      if (result.affected_tasks > 0) {
        toast.success(`已重启 ${result.affected_tasks} 个中断任务`)
      } else {
        toast.info('当前没有可重启的中断任务')
      }
      await invalidateVoiceLibrary()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '重启任务失败')
    }
  }

  const handleInterruptItemTask = async (item: VoiceLibraryItem) => {
    try {
      const result = await api.voiceLibrary.cancelImportTaskByItem(item.id)
      if (result.affected_tasks > 0) {
        toast.success(`已中断语音任务：${item.name}`)
        await invalidateVoiceLibrary()
      } else {
        toast.info('该语音没有可中断的任务')
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '中断任务失败')
    }
  }

  const handleRetry = async (item: VoiceLibraryItem) => {
    try {
      await retryAction.run({
        id: item.id,
        task: () => api.voiceLibrary.retry(item.id),
        invalidateQueryKeys: [queryKeys.voiceLibrary.root, queryKeys.voiceLibrary.active],
        successMessage: '已重新开始任务',
        errorMessage: (error) => error instanceof Error ? error.message : '重试失败',
      })
    } catch {
      // toast handled in hook
    }
  }

  const handleCardPlay = async (item: VoiceLibraryItem) => {
    const itemAudioUrl = resolveApiResourceUrl(item.audio_url)
    if (!itemAudioUrl) {
      toast.error('该语音暂无音频，请稍后再试')
      return
    }
    const target = audioRefs.current[item.id]
    if (!target) return

    if (!target.paused) {
      target.pause()
      return
    }

    for (const [idText, audio] of Object.entries(audioRefs.current)) {
      const id = Number(idText)
      if (id !== item.id && audio && !audio.paused) {
        audio.pause()
      }
    }

    if (target.src !== itemAudioUrl) {
      target.src = itemAudioUrl
      target.load()
    }

    try {
      await target.play()
      setPlayingId(item.id)
    } catch {
      toast.error('播放失败，请重试')
    }
  }

  const openEditor = (item: VoiceLibraryItem) => {
    if (isBuiltinItem(item)) {
      toast.info('内置语音卡片不可编辑')
      return
    }
    if (!isItemReady(item)) {
      toast.info('卡片处理中，暂不可编辑')
      return
    }

    setEditingItemId(item.id)
    setEditorDraft({
      name: item.name || '',
      reference_text: item.reference_text || '',
      audio_file: null,
      audio_url: resolveApiResourceUrl(item.audio_url) || null,
      source_url: item.source_url || '',
    })
    setEditorOpen(true)
  }

  const closeEditor = () => {
    setEditorOpen(false)
    setEditingItemId(null)
    setEditorDraft(createEmptyEditorDraft())
    if (editAudioInputRef.current) {
      editAudioInputRef.current.value = ''
    }
  }

  const handleSubmitEditor = async () => {
    if (!liveEditingItem || !editingReady || editorSubmitting) return
    if (isBuiltinItem(liveEditingItem)) {
      toast.error('内置语音卡片不可编辑')
      return
    }
    if (nameError) {
      toast.error(nameError)
      return
    }

    setEditorSubmitting(true)
    try {
      await api.voiceLibrary.update(liveEditingItem.id, {
        name: trimmedName,
        reference_text: editorDraft.reference_text,
      })
      if (editorDraft.audio_file) {
        await api.voiceLibrary.uploadAudio(liveEditingItem.id, editorDraft.audio_file)
      }
      await invalidateVoiceLibrary()
      closeEditor()
      toast.success('已更新语音卡片')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '更新失败')
    } finally {
      setEditorSubmitting(false)
    }
  }

  return (
    <div className="absolute inset-0 overflow-auto">
      <div className="px-4 py-6 md:px-8 lg:px-12">
        <div className={CATALOG_MAX_WIDTH_CLASS}>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="icon" asChild>
                <Link href="/">
                  <ArrowLeft className="h-4 w-4" />
                </Link>
              </Button>
              <div className="flex items-center gap-2">
                <Headphones className="h-5 w-5 text-foreground" />
                <h1 className="text-xl font-semibold">语音库</h1>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {(activeJobIds.length > 0 || hasProcessingItems) ? (
                <Button variant="destructive" size="sm" onClick={() => void handleCancelAllImports()}>
                  <Pause className="mr-1.5 h-3.5 w-3.5" />
                  停止当前库导入任务
                </Button>
              ) : null}
              {hasInterruptedItems ? (
                <Button variant="outline" size="sm" onClick={() => void handleRestartInterruptedImports()}>
                  <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
                  重启中断任务
                </Button>
              ) : null}
              <CatalogSearchActions
              value={searchText}
              placeholder="搜索语音卡片名称..."
              isRefreshing={isFetching}
              onValueChange={onSearchTextChange}
              onSearch={onSearch}
              onRefresh={() => {
                void refetch()
              }}
            />
            </div>
          </div>

          <CatalogListHeader
            label="语音卡片列表"
            total={total ?? 0}
            page={page}
            totalPages={totalPages}
            pageSize={pageSize}
            isFetching={isFetching}
            onPageChange={setPage}
            onPageSizeChange={onPageSizeChange}
          />

          <CatalogQueryState
            isLoading={isLoading}
            error={error}
            hasData={sortedItems.length > 0}
            onRetry={() => {
              void refetch()
            }}
            loadingFallback={<div className="text-sm text-muted-foreground">加载中...</div>}
          >
            <div className={CATALOG_GRID_CARD_CLASS}>
              <CatalogCreateCard
                title="新增语音预设"
                icon={<Plus className="h-6 w-6 text-primary" />}
                className="h-[252px]"
                onClick={openImportMethodDialog}
              />

              {sortedItems.map((item) => {
                const isUpdatingEnabled = updateEnabledAction.pendingIds.has(item.id)
                const isDeleting = deletingAction.pendingIds.has(item.id)
                const isRetrying = retryAction.pendingIds.has(item.id)
                const failed = isItemFailed(item)
                const canceled = isItemCanceled(item)
                const processing = isItemProcessing(item)
                const recoverable = failed || canceled
                const builtin = isBuiltinItem(item)
                const processingPercent = extractProgressPercent(item.processing_message)
                const itemAudioUrl = resolveApiResourceUrl(item.audio_url)
                const isPlaying = playingId === item.id
                const tagLabel = getCardTagLabel(item)

                return (
                  <Card key={item.id} className="h-[252px] overflow-hidden transition-all hover:-translate-y-0.5 hover:shadow-md">
                    <CardContent className="flex h-full flex-col p-0">
                      <div className="flex items-start justify-between gap-2 px-4 pt-4">
                        <div className="min-w-0 flex-1">
                          <h3 className="truncate text-base font-semibold leading-tight">
                            {item.name?.trim() || (processing ? '处理中...' : '未命名')}
                          </h3>
                          <div className="mt-1 flex items-center gap-1.5 text-xs">
                            <span className="rounded border border-emerald-500/35 bg-emerald-500/10 px-1.5 py-0.5 text-emerald-700">
                              {tagLabel}
                            </span>
                            {failed ? (
                              <span className="rounded border border-destructive/30 bg-destructive/10 px-1.5 py-0.5 text-destructive">
                                失败
                              </span>
                            ) : canceled ? (
                              <span className="rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-amber-700">
                                中断
                              </span>
                            ) : null}
                          </div>
                        </div>
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            role="switch"
                            aria-checked={item.is_enabled}
                            aria-label={item.is_enabled ? '禁用语音卡片' : '启用语音卡片'}
                            disabled={isUpdatingEnabled || isDeleting}
                            onClick={() => {
                              void handleToggleEnabled(item, !item.is_enabled)
                            }}
                            className={cn(
                              'relative h-5 w-10 rounded-full transition-colors',
                              item.is_enabled ? 'bg-zinc-900' : 'bg-zinc-400',
                              (isUpdatingEnabled || isDeleting) && 'opacity-60'
                            )}
                          >
                            <span
                              className={cn(
                                'absolute left-[3px] top-[3px] h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform',
                                item.is_enabled ? 'translate-x-5' : 'translate-x-0'
                              )}
                            />
                          </button>
                          {!builtin ? (
                            <>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8"
                                onClick={() => openEditor(item)}
                                disabled={isDeleting}
                                aria-label="编辑语音卡片"
                              >
                                <Pencil className="h-4 w-4" />
                              </Button>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 text-destructive hover:text-destructive"
                                onClick={() => {
                                  if (processing) {
                                    void handleInterruptItemTask(item)
                                    return
                                  }
                                  void handleDelete(item)
                                }}
                                disabled={isDeleting}
                                aria-label={processing ? '中断任务' : '删除语音卡片'}
                                title={processing ? '中断任务' : '删除语音卡片'}
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                              {recoverable ? (
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="icon"
                                  className="h-8 w-8"
                                  onClick={() => {
                                    void handleRetry(item)
                                  }}
                                  disabled={isDeleting || isRetrying}
                                  aria-label="重试任务"
                                  title="重试任务"
                                >
                                  <RefreshCw className={cn('h-4 w-4', isRetrying && 'animate-spin')} />
                                </Button>
                              ) : null}
                            </>
                          ) : null}
                        </div>
                      </div>

                      <div className="min-h-[92px] px-4 pb-3 pt-2">
                        {isFieldProcessing(item.reference_text_status) ? (
                          <div className="space-y-1 text-xs text-muted-foreground">
                            <div className="flex items-center gap-1.5">
                              <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                              <span>{item.processing_message || '解析中...'}</span>
                            </div>
                            {processingPercent !== null ? (
                              <div className="mt-1.5">
                                <div className="h-1.5 w-full overflow-hidden rounded bg-primary/20">
                                  <div
                                    className="h-full bg-primary transition-all"
                                    style={{ width: `${processingPercent}%` }}
                                  />
                                </div>
                              </div>
                            ) : null}
                          </div>
                        ) : recoverable ? (
                          <p className={cn('line-clamp-3 text-[12px] leading-5', canceled ? 'text-amber-700' : 'text-destructive')}>
                            {item.error_message || (canceled ? '任务已中断' : '处理失败')}
                          </p>
                        ) : (
                          <p className="line-clamp-4 text-[13px] leading-5 text-muted-foreground">
                            {item.reference_text?.trim() || '暂无参考文本'}
                          </p>
                        )}
                      </div>

                      <div className="mt-auto border-t border-dashed bg-muted/35">
                        <button
                          type="button"
                          className="flex w-full items-center justify-center gap-2 px-3 py-3 text-sm"
                          onClick={() => void handleCardPlay(item)}
                        >
                          {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                          <span>
                            {itemAudioUrl ? (isPlaying ? '播放中，点击暂停' : '点击开始播放') : '暂无音频'}
                          </span>
                        </button>
                        <audio
                          ref={(node) => {
                            audioRefs.current[item.id] = node
                          }}
                          preload="none"
                          className="hidden"
                          onPlay={() => setPlayingId(item.id)}
                          onPause={() => {
                            setPlayingId((prev) => (prev === item.id ? null : prev))
                          }}
                          onEnded={() => {
                            setPlayingId((prev) => (prev === item.id ? null : prev))
                          }}
                        />
                      </div>
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          </CatalogQueryState>
        </div>
      </div>

      <Dialog open={showMethodDialog} onOpenChange={setShowMethodDialog}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>新增语音预设</DialogTitle>
            <DialogDescription>请选择导入方式</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <button
              className="rounded-lg border p-4 text-left transition-colors hover:bg-accent"
              onClick={() => handleSelectMethod('audio_with_text')}
            >
              <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                <FileAudio className="h-4 w-4 text-emerald-500" />
                音频+文本
              </div>
              <p className="text-xs text-muted-foreground">上传音频并填写参考文本，提交后自动命名。</p>
            </button>
            <button
              className="rounded-lg border p-4 text-left transition-colors hover:bg-accent"
              onClick={() => handleSelectMethod('audio_files')}
            >
              <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                <Music2 className="h-4 w-4 text-blue-500" />
                音频文件
              </div>
              <p className="text-xs text-muted-foreground">一次最多 {LIBRARY_BATCH_MAX_ITEMS} 个文件，后台自动转写并命名并排队处理。</p>
            </button>
            <button
              className="rounded-lg border p-4 text-left transition-colors hover:bg-accent"
              onClick={() => handleSelectMethod('video_link')}
            >
              <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                <Link2 className="h-4 w-4 text-orange-500" />
                视频链接
              </div>
              <p className="text-xs text-muted-foreground">支持小红书、抖音、快手，可选截取时间。</p>
            </button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={showAudioWithTextDialog} onOpenChange={(open) => {
        if (!open) {
          clearAudioWithTextPreview()
          setAudioWithTextFile(null)
          setAudioWithTextPreviewUrl('')
          if (methodAudioTextInputRef.current) {
            methodAudioTextInputRef.current.value = ''
          }
        }
        setShowAudioWithTextDialog(open)
      }}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>音频文件 + 参考文本</DialogTitle>
          </DialogHeader>

          <div className="space-y-3">
            <div className="space-y-2">
              <Label>音频文件</Label>
              <input
                ref={methodAudioTextInputRef}
                type="file"
                accept="audio/*,.wav,.mp3,.m4a,.flac,.aac,.ogg,.mp4,.webm"
                className="hidden"
                onChange={(event) => {
                  const file = event.target.files?.[0] || null
                  setAudioWithTextFile(file)
                }}
              />
              <div className="space-y-2 rounded-lg border border-dashed bg-muted/35 p-3">
                {audioWithTextPreviewUrl ? (
                  <AudioPlayer src={audioWithTextPreviewUrl} />
                ) : (
                  <div className="flex h-16 items-center justify-center text-sm text-muted-foreground">
                    请上传音频文件（最长1分钟）
                  </div>
                )}
              </div>
              <Button type="button" variant="outline" onClick={() => methodAudioTextInputRef.current?.click()}>
                <Upload className="mr-2 h-4 w-4" />
                {audioWithTextFile ? '重新上传音频' : '上传音频'}
              </Button>
            </div>

            <div className="space-y-2">
              <Label>参考文本</Label>
              <Textarea
                className="min-h-[180px]"
                value={audioWithTextReferenceText}
                onChange={(event) => setAudioWithTextReferenceText(event.target.value)}
                placeholder="请输入参考文本..."
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setShowAudioWithTextDialog(false)} disabled={audioWithTextSubmitting}>
              取消
            </Button>
            <Button onClick={() => void handleSubmitAudioWithText()} disabled={audioWithTextSubmitting}>
              {audioWithTextSubmitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  提交中...
                </>
              ) : '提交'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={showAudioFilesDialog}
        onOpenChange={(open) => {
          if (!open) {
            resetAudioFilesImportDialog()
          }
          setShowAudioFilesDialog(open)
        }}
      >
        <DialogContent className="sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle>音频文件导入</DialogTitle>
            <DialogDescription>最多上传 {LIBRARY_BATCH_MAX_ITEMS} 个文件，每个文件创建一张卡片。</DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <input
              ref={methodAudioInputRef}
              type="file"
              multiple
              accept="audio/*,.wav,.mp3,.m4a,.flac,.aac,.ogg,.mp4,.webm"
              className="hidden"
              onChange={(event) => {
                const files = Array.from(event.target.files || [])
                if (files.length > LIBRARY_BATCH_MAX_ITEMS) {
                  toast.error(`最多支持${LIBRARY_BATCH_MAX_ITEMS}个文件`)
                  return
                }
                setAudioImportPlayingRowId(null)
                setAudioImportRows((prev) => {
                  revokeAudioImportPreviewUrls(prev)
                  return files.map((file, index) => ({
                    id: `${file.name}-${file.size}-${file.lastModified}-${index}`,
                    file,
                    name: '',
                    auto_parse_text: true,
                    preview_url: URL.createObjectURL(file),
                  }))
                })
              }}
            />
            <div className="flex items-center gap-2">
              <Button type="button" variant="outline" onClick={() => methodAudioInputRef.current?.click()}>
                <Upload className="mr-2 h-4 w-4" />
                {audioImportRows.length > 0 ? '重新选择音频' : '选择音频文件'}
              </Button>
              <span className="text-xs text-muted-foreground">默认开启“解析文字”，名称可留空自动生成</span>
            </div>

            {audioImportRows.length === 0 ? (
              <div className="flex h-28 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground">
                请先上传音频文件
              </div>
            ) : (
              <div className="rounded-md border">
                <div className="grid grid-cols-[44px_minmax(0,1fr)_minmax(0,1.3fr)_120px] items-center gap-2 border-b bg-muted/40 px-3 py-2 text-xs font-medium">
                  <span className="text-center">操作</span>
                  <span className="text-center">名称</span>
                  <span className="text-center">播放进度条</span>
                  <span className="text-center">是否解析文字</span>
                </div>
                <div className="max-h-80 overflow-y-auto">
                  {audioImportRows.map((row) => (
                    <div
                      key={row.id}
                      className="grid grid-cols-[44px_minmax(0,1fr)_minmax(0,1.3fr)_120px] items-center gap-2 border-b px-3 py-2 last:border-b-0"
                    >
                      <div className="flex items-center justify-center">
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-destructive hover:text-destructive"
                          onClick={() => {
                            setAudioImportPlayingRowId((prev) => (prev === row.id ? null : prev))
                            setAudioImportRows((prev) => {
                              const target = prev.find((item) => item.id === row.id)
                              if (target?.preview_url) {
                                URL.revokeObjectURL(target.preview_url)
                              }
                              return prev.filter((item) => item.id !== row.id)
                            })
                          }}
                          disabled={audioFilesSubmitting}
                          aria-label="删除导入音频记录"
                          title="删除记录"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                      <Input
                        value={row.name}
                        onChange={(event) => {
                          const value = event.target.value
                          setAudioImportRows((prev) => prev.map((item) => (
                            item.id === row.id ? { ...item, name: value } : item
                          )))
                        }}
                        placeholder="可留空自动命名"
                        disabled={audioFilesSubmitting}
                      />
                      <div className="min-w-0">
                        <AudioPlayer
                          src={row.preview_url}
                          className="w-full"
                          playerKey={row.id}
                          activePlayerKey={audioImportPlayingRowId}
                          onPlayRequest={(key) => setAudioImportPlayingRowId(key)}
                          onPlaybackStateChange={(isPlaying) => {
                            setAudioImportPlayingRowId((prev) => {
                              if (isPlaying) return row.id
                              return prev === row.id ? null : prev
                            })
                          }}
                        />
                      </div>
                      <div className="flex items-center justify-center">
                        <Checkbox
                          checked={row.auto_parse_text}
                          onCheckedChange={(checked) => {
                            const next = checked !== false
                            setAudioImportRows((prev) => prev.map((item) => (
                              item.id === row.id ? { ...item, auto_parse_text: next } : item
                            )))
                          }}
                          disabled={audioFilesSubmitting}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setShowAudioFilesDialog(false)
                resetAudioFilesImportDialog()
              }}
              disabled={audioFilesSubmitting}
            >
              取消
            </Button>
            <Button onClick={() => void handleSubmitAudioFiles()} disabled={audioFilesSubmitting || audioImportRows.length === 0}>
              {audioFilesSubmitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  提交中...
                </>
              ) : '开始导入'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showVideoLinkDialog} onOpenChange={setShowVideoLinkDialog}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>视频链接导入</DialogTitle>
            <DialogDescription>
              支持小红书、抖音、快手单个链接。可选填写开始/结束时间，时间区间最多 1 分钟。
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label>网页链接</Label>
              <Input
                value={videoLink}
                onChange={(event) => setVideoLink(event.target.value)}
                placeholder="请输入单个视频链接"
                disabled={videoLinkSubmitting}
              />
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="space-y-2">
                <Label>开始时间（可选）</Label>
                <Input
                  value={videoStartTime}
                  onChange={(event) => setVideoStartTime(event.target.value)}
                  placeholder="如 00:00:30"
                  disabled={videoLinkSubmitting}
                />
              </div>
              <div className="space-y-2">
                <Label>结束时间（可选）</Label>
                <Input
                  value={videoEndTime}
                  onChange={(event) => setVideoEndTime(event.target.value)}
                  placeholder="如 00:01:00"
                  disabled={videoLinkSubmitting}
                />
              </div>
            </div>

            <p className="text-xs text-muted-foreground">
              规则：不填时间默认从开头截取最多1分钟；只填开始则从开始向后1分钟；只填结束则向前倒推1分钟；同时填写时区间不得超过1分钟。
            </p>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setShowVideoLinkDialog(false)} disabled={videoLinkSubmitting}>
              取消
            </Button>
            <Button onClick={() => void handleSubmitVideoLink()} disabled={videoLinkSubmitting}>
              {videoLinkSubmitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  提交中...
                </>
              ) : '开始导入'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={editorOpen} onOpenChange={(open) => {
        if (!open) {
          closeEditor()
          return
        }
        setEditorOpen(open)
      }}>
        <DialogContent className="max-h-[85vh] overflow-hidden sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>编辑语音卡片</DialogTitle>
          </DialogHeader>

          {!liveEditingItem ? (
            <div className="text-sm text-muted-foreground">未找到卡片</div>
          ) : (
            <div className="max-h-[calc(85vh-9rem)] space-y-4 overflow-y-auto pr-1">
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label>名称</Label>
                  <span className={cn('text-xs', nameLength > 30 ? 'text-destructive' : 'text-muted-foreground')}>
                    {nameLength}/30
                  </span>
                </div>
                <Input
                  value={editorDraft.name}
                  onChange={(event) => {
                    setEditorDraft((prev) => ({ ...prev, name: event.target.value }))
                  }}
                  disabled={!editingReady || editorSubmitting}
                />
                {nameError ? <p className="text-xs text-destructive">{nameError}</p> : null}
              </div>

              <div className="space-y-2">
                <Label>参考文本</Label>
                <Textarea
                  className="min-h-[130px] max-h-[240px] resize-y overflow-y-auto"
                  value={editorDraft.reference_text}
                  onChange={(event) => {
                    setEditorDraft((prev) => ({ ...prev, reference_text: event.target.value }))
                  }}
                  disabled={!editingReady || editorSubmitting}
                />
              </div>

              <div className="space-y-2">
                <Label>音频文件</Label>
                <input
                  ref={editAudioInputRef}
                  type="file"
                  accept="audio/*,.wav,.mp3,.m4a,.flac,.aac,.ogg,.mp4,.webm"
                  className="hidden"
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    if (!file) return
                    const objectUrl = URL.createObjectURL(file)
                    setEditorDraft((prev) => ({
                      ...prev,
                      audio_file: file,
                      audio_url: objectUrl,
                    }))
                  }}
                  disabled={!editingReady || editorSubmitting}
                />
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => editAudioInputRef.current?.click()}
                  disabled={!editingReady || editorSubmitting}
                >
                  <Upload className="mr-2 h-4 w-4" />
                  上传/替换音频
                </Button>
                {editorDraft.audio_url ? (
                  <AudioPlayer src={editorDraft.audio_url} />
                ) : (
                  <p className="text-xs text-muted-foreground">暂无音频</p>
                )}
              </div>

              {liveEditingItem.source_channel === 'video_link' && editorDraft.source_url ? (
                <div className="space-y-2">
                  <Label>原始链接（只读）</Label>
                  <a
                    href={editorDraft.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="line-clamp-2 break-all text-xs text-primary underline-offset-2 hover:underline"
                  >
                    {editorDraft.source_url}
                  </a>
                </div>
              ) : null}
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={closeEditor} disabled={editorSubmitting}>
              取消
            </Button>
            <Button onClick={() => void handleSubmitEditor()} disabled={!editingReady || !!nameError || editorSubmitting}>
              {editorSubmitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  保存中...
                </>
              ) : '保存'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
