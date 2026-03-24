'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { Plus, Upload, Trash2, Users, ArrowLeft, Volume2, Wand2, Pencil, Loader2, Pause, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'

import { api } from '@/lib/api-client'
import { CatalogCreateCard } from '@/components/common/catalog-create-card'
import { useConfirmDialog } from '@/components/common/confirm-dialog-provider'
import { CatalogListHeader } from '@/components/common/catalog-list-header'
import { CATALOG_GRID_CARD_CLASS, CATALOG_MAX_WIDTH_FLEX_COLUMN_CLASS } from '@/components/common/catalog-layout'
import { CatalogQueryState } from '@/components/common/catalog-query-state'
import { CatalogSearchActions } from '@/components/common/catalog-search-actions'
import { ReferenceVoiceFields } from '@/components/audio/reference-voice-fields'
import { useCatalogRowAction } from '@/hooks/use-catalog-row-action'
import { useCatalogPagedQuery } from '@/hooks/use-catalog-paged-query'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { AudioPlayer } from '@/components/ui/audio-player'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { ReferenceLibraryImportImageRow, ReferenceLibraryItem } from '@/types/reference'
import type { ReferenceVoiceConfig } from '@/hooks/use-reference-voice-meta'
import { speedToRate, useReferenceVoiceMeta } from '@/hooks/use-reference-voice-meta'
import { resolveApiResourceUrl, resolveStorageFileUrl } from '@/lib/media-url'
import { sortReferencesNewestFirst } from '@/lib/catalog-sort'
import { queryKeys } from '@/lib/query-keys'
import { LIBRARY_BATCH_MAX_ITEMS } from '@/lib/library-limits'

interface EditableReference {
  name: string
  can_speak: boolean
  setting: string
  appearance_description: string
  voice: Partial<ReferenceVoiceConfig>
}

interface BatchImportRow {
  id: string
  file: File
  name: string
  generate_description: boolean
}

function getNameLength(value: string): number {
  return Array.from(value.trim()).length
}

function isFieldProcessing(status: ReferenceLibraryItem['name_status'] | undefined): boolean {
  return status === 'pending' || status === 'running'
}

function isFieldFailed(status: ReferenceLibraryItem['name_status'] | undefined): boolean {
  return status === 'failed'
}

function isFieldCanceled(status: ReferenceLibraryItem['name_status'] | undefined): boolean {
  return status === 'canceled'
}

function isItemProcessing(item: ReferenceLibraryItem): boolean {
  return isFieldProcessing(item.name_status) || isFieldProcessing(item.appearance_status)
}

function isItemFailed(item: ReferenceLibraryItem): boolean {
  return !!(item.error_message || isFieldFailed(item.name_status) || isFieldFailed(item.appearance_status))
}

function isItemCanceled(item: ReferenceLibraryItem): boolean {
  return isFieldCanceled(item.name_status) || isFieldCanceled(item.appearance_status)
}

function isJobRunning(status: 'pending' | 'running' | 'completed' | 'failed' | 'canceled' | undefined): boolean {
  return status === 'pending' || status === 'running'
}

function isSameVoiceConfig(
  left: Partial<ReferenceVoiceConfig> | undefined,
  right: Partial<ReferenceVoiceConfig> | undefined
): boolean {
  return (
    left?.voice_audio_provider === right?.voice_audio_provider
    && left?.voice_name === right?.voice_name
    && left?.voice_speed === right?.voice_speed
    && left?.voice_wan2gp_preset === right?.voice_wan2gp_preset
    && left?.voice_wan2gp_alt_prompt === right?.voice_wan2gp_alt_prompt
    && left?.voice_wan2gp_audio_guide === right?.voice_wan2gp_audio_guide
    && left?.voice_wan2gp_temperature === right?.voice_wan2gp_temperature
    && left?.voice_wan2gp_top_k === right?.voice_wan2gp_top_k
    && left?.voice_wan2gp_seed === right?.voice_wan2gp_seed
  )
}

export default function ReferenceLibraryPage() {
  const queryClient = useQueryClient()
  const confirmDialog = useConfirmDialog()
  const uploadInputRef = useRef<HTMLInputElement>(null)
  const createUploadInputRef = useRef<HTMLInputElement>(null)
  const previewEventSourceRef = useRef<EventSource | null>(null)
  const importEventSourceRef = useRef<EventSource | null>(null)
  const lastSyncedSelectionRef = useRef<string>('')

  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [editable, setEditable] = useState<EditableReference | null>(null)
  const [isEditingDetail, setIsEditingDetail] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const [isDeletingImage, setIsDeletingImage] = useState(false)
  const togglingSpeakAction = useCatalogRowAction<number>()
  const deletingAction = useCatalogRowAction<number>()
  const retryAction = useCatalogRowAction<number>()
  const generateDescriptionAction = useCatalogRowAction<number>()
  const [isCreateGeneratingDescription, setIsCreateGeneratingDescription] = useState(false)
  const [isStreamingDescription, setIsStreamingDescription] = useState(false)
  const descriptionStreamVersionRef = useRef(0)
  const batchImportInputRef = useRef<HTMLInputElement>(null)

  const [createDraft, setCreateDraft] = useState<EditableReference | null>(null)
  const [isCreating, setIsCreating] = useState(false)
  const [createFile, setCreateFile] = useState<File | null>(null)
  const [showMethodDialog, setShowMethodDialog] = useState(false)
  const [showBatchDialog, setShowBatchDialog] = useState(false)
  const [batchRows, setBatchRows] = useState<BatchImportRow[]>([])
  const [batchSubmitting, setBatchSubmitting] = useState(false)
  const [activeJobIds, setActiveJobIds] = useState<string[]>([])
  const [isPreviewing, setIsPreviewing] = useState(false)
  const [previewStatus, setPreviewStatus] = useState('')
  const [previewAudioUrl, setPreviewAudioUrl] = useState('')
  const [returnHref, setReturnHref] = useState('/')
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
  } = useCatalogPagedQuery<ReferenceLibraryItem>({
    getQueryKey: ({ searchQuery, page, pageSize }) => queryKeys.references.list(searchQuery, page, pageSize),
    queryFn: ({ page, dataPageSize, searchQuery }) =>
      api.references.list({ q: searchQuery, page, pageSize: dataPageSize }),
  })
  const voiceMeta = useReferenceVoiceMeta()
  const normalizeVoiceConfig = voiceMeta.normalizeConfig
  const toVoicePayload = voiceMeta.toPayload
  const defaultVoiceProvider = voiceMeta.defaultAudioProvider
  const buildEditableFromItem = useCallback((item: ReferenceLibraryItem): EditableReference => {
    const canSpeak = item.can_speak !== false
    return {
      name: item.name || '',
      can_speak: canSpeak,
      setting: item.setting || '',
      appearance_description: item.appearance_description || '',
      voice: normalizeVoiceConfig({
        voice_audio_provider: item.voice_audio_provider,
        voice_name: item.voice_name,
        voice_speed: item.voice_speed,
        voice_wan2gp_preset: item.voice_wan2gp_preset,
        voice_wan2gp_alt_prompt: item.voice_wan2gp_alt_prompt,
        voice_wan2gp_audio_guide: item.voice_wan2gp_audio_guide,
        voice_wan2gp_temperature: item.voice_wan2gp_temperature,
        voice_wan2gp_top_k: item.voice_wan2gp_top_k,
        voice_wan2gp_seed: item.voice_wan2gp_seed,
      }),
    }
  }, [normalizeVoiceConfig])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const from = (params.get('from') || '').trim().toLowerCase()
    const projectIdParam = (params.get('projectId') || '').trim()
    if (from === 'project' && /^\d+$/.test(projectIdParam)) {
      setReturnHref(`/projects/${projectIdParam}`)
      return
    }
    setReturnHref('/')
  }, [])

  const sortedItems = useMemo(() => sortReferencesNewestFirst(items), [items])
  const isCreateMode = createDraft !== null
  const activeForm = createDraft || editable
  const activeName = activeForm?.name || ''
  const activeTrimmedName = activeName.trim()
  const activeNameLength = useMemo(() => getNameLength(activeName), [activeName])
  const activeNameError = useMemo(() => {
    if (!activeForm) return ''
    if (!activeTrimmedName) return '名称不能为空'
    if (activeNameLength > 12) return '名称最多12个字符'
    return ''
  }, [activeForm, activeNameLength, activeTrimmedName])

  useEffect(() => {
    if (isCreateMode) {
      setSelectedId(null)
      setEditable(null)
      return
    }
    if (items.length === 0) {
      setSelectedId(null)
      setEditable(null)
      setIsEditingDetail(false)
      return
    }
    if (!selectedId || !items.some((item) => item.id === selectedId)) {
      setSelectedId(items[0].id)
    }
  }, [isCreateMode, items, selectedId])

  const selected = useMemo(() => items.find((item) => item.id === selectedId) || null, [items, selectedId])

  useEffect(() => {
    if (isCreateMode) {
      lastSyncedSelectionRef.current = ''
      setEditable(null)
      return
    }
    if (!selected) {
      lastSyncedSelectionRef.current = ''
      setEditable(null)
      return
    }

    const syncKey = `${selected.id}:${selected.updated_at}`
    if (lastSyncedSelectionRef.current === syncKey) {
      return
    }
    lastSyncedSelectionRef.current = syncKey

    const nextEditable = buildEditableFromItem(selected)
    setEditable((prev) => {
      if (!prev) return nextEditable
      const same = (
        prev.name === nextEditable.name
        && prev.can_speak === nextEditable.can_speak
        && prev.setting === nextEditable.setting
        && prev.appearance_description === nextEditable.appearance_description
        && isSameVoiceConfig(prev.voice, nextEditable.voice)
      )
      return same ? prev : nextEditable
    })
  }, [buildEditableFromItem, isCreateMode, selected])

  const normalizedEditableVoice = useMemo(
    () => editable
      ? normalizeVoiceConfig(editable.voice)
      : null,
    [editable, normalizeVoiceConfig]
  )
  const normalizedCreateVoice = useMemo(
    () => createDraft
      ? normalizeVoiceConfig(createDraft.voice)
      : null,
    [createDraft, normalizeVoiceConfig]
  )
  const createImageUrl = useMemo(() => {
    if (!createFile) return undefined
    return URL.createObjectURL(createFile)
  }, [createFile])

  const selectedImageUrl = useMemo(() => {
    if (!selected?.image_file_path) return undefined
    const baseUrl = resolveStorageFileUrl(selected.image_file_path)
    if (!baseUrl) return undefined
    return `${baseUrl}?t=${selected.image_updated_at || 0}`
  }, [selected])
  const activeImageUrl = isCreateMode ? createImageUrl : selectedImageUrl
  const hasActiveImage = Boolean(activeImageUrl)

  const runRefresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.references.root })
    await refetch()
  }, [queryClient, refetch])

  const hasProcessingItems = useMemo(
    () => sortedItems.some((item) => isItemProcessing(item)),
    [sortedItems]
  )
  const hasInterruptedItems = useMemo(
    () => sortedItems.some((item) => isItemCanceled(item) || isItemFailed(item)),
    [sortedItems]
  )

  const closePreviewStream = useCallback(() => {
    if (!previewEventSourceRef.current) return
    previewEventSourceRef.current.close()
    previewEventSourceRef.current = null
  }, [])

  const closeImportStream = useCallback(() => {
    if (!importEventSourceRef.current) return
    importEventSourceRef.current.close()
    importEventSourceRef.current = null
  }, [])

  useEffect(() => {
    return () => {
      if (createImageUrl) {
        URL.revokeObjectURL(createImageUrl)
      }
    }
  }, [createImageUrl])

  useEffect(() => {
    return () => {
      closePreviewStream()
      closeImportStream()
    }
  }, [closeImportStream, closePreviewStream])

  useEffect(() => {
    closePreviewStream()
    setIsPreviewing(false)
    setPreviewStatus('')
    setPreviewAudioUrl('')
  }, [closePreviewStream, isCreateMode, selectedId])

  useEffect(() => {
    if (!hasProcessingItems) return
    const timer = window.setInterval(() => {
      void refetch()
    }, 1800)
    return () => window.clearInterval(timer)
  }, [hasProcessingItems, refetch])

  useEffect(() => {
    if (activeJobIds.length === 0) return
    const timer = window.setInterval(() => {
      void Promise.all(activeJobIds.map((jobId) => api.references.getImportJob(jobId).then((job) => ({ jobId, job }))))
        .then((results) => {
          const finishedIds: string[] = []
          for (const { jobId, job } of results) {
            if (!isJobRunning(job.status)) {
              finishedIds.push(jobId)
              const canceledCount = Number(job.canceled_count || 0)
              if (job.success_count > 0 && job.failed_count === 0 && canceledCount === 0) {
                toast.success(`图片导入完成：成功 ${job.success_count}`)
              } else if (job.success_count > 0 && canceledCount > 0) {
                toast.warning(`图片导入完成：成功 ${job.success_count}，中断 ${canceledCount}`)
              } else if (job.success_count > 0) {
                toast.warning(`图片导入完成：成功 ${job.success_count}，失败 ${job.failed_count}`)
              } else if (canceledCount > 0 && job.failed_count === 0) {
                toast.info(`图片导入已中断：共 ${canceledCount}`)
              } else {
                toast.error(job.error_message || '图片导入失败')
              }
            }
          }
          if (finishedIds.length > 0) {
            setActiveJobIds((prev) => prev.filter((id) => !finishedIds.includes(id)))
            void runRefresh()
          }
        })
        .catch(() => undefined)
    }, 2000)
    return () => window.clearInterval(timer)
  }, [activeJobIds, runRefresh])

  useEffect(() => {
    let disposed = false
    let retryTimer: number | null = null
    let retryAttempt = 0

    const connectImportStream = () => {
      if (disposed) return
      closeImportStream()
      const eventSource = new EventSource(api.references.importEventsStreamUrl())
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
          void runRefresh()
        } catch {
          // ignore bad payload
        }
      })

      eventSource.onerror = () => {
        if (importEventSourceRef.current !== eventSource) return
        eventSource.close()
        importEventSourceRef.current = null
        void runRefresh()
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
  }, [closeImportStream, runRefresh])

  const handlePreview = useCallback(() => {
    if (!activeForm) return
    if (!activeForm.can_speak) {
      toast.info('当前参考未配置声音')
      return
    }
    const voicePayload = normalizeVoiceConfig(activeForm.voice)

    closePreviewStream()
    setIsPreviewing(true)
    setPreviewStatus('准备中...')
    setPreviewAudioUrl('')

    const previewText = `大家好，我是${activeForm.name || '参考角色'}，欢迎使用影流`
    const provider = voicePayload.voice_audio_provider
    const inputData = provider === 'wan2gp'
      ? {
          audio_wan2gp_preset: voicePayload.voice_wan2gp_preset,
          audio_wan2gp_model_mode: voicePayload.voice_name,
          audio_wan2gp_alt_prompt: voicePayload.voice_wan2gp_alt_prompt,
          audio_wan2gp_audio_guide: voicePayload.voice_wan2gp_audio_guide,
          audio_wan2gp_temperature: voicePayload.voice_wan2gp_temperature,
          audio_wan2gp_top_k: voicePayload.voice_wan2gp_top_k,
          audio_wan2gp_seed: voicePayload.voice_wan2gp_seed,
          audio_wan2gp_speed: voicePayload.voice_speed,
          preview_text: previewText,
        }
      : {
          edge_tts_voice: voicePayload.voice_name,
          edge_tts_rate: speedToRate(voicePayload.voice_speed ?? 1.0),
          preview_text: previewText,
        }
    const streamUrl = api.settings.audioPreviewStreamUrl(provider, inputData)
    const eventSource = new EventSource(streamUrl)
    previewEventSourceRef.current = eventSource

    eventSource.onmessage = (event) => {
      if (previewEventSourceRef.current !== eventSource) return
      if (event.data === '[DONE]') {
        closePreviewStream()
        setIsPreviewing(false)
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
        setPreviewStatus(String(payload.message || '生成中...'))
        return
      }
      if (eventType === 'result') {
        const audioUrl = resolveApiResourceUrl(String(payload.audio_url || ''))
        setPreviewStatus(String(payload.message || '生成完成'))
        setPreviewAudioUrl(audioUrl ? `${audioUrl}?t=${Date.now()}` : '')
        setIsPreviewing(false)
        closePreviewStream()
        return
      }
      if (eventType === 'error') {
        const message = String(payload.message || '试听失败')
        setPreviewStatus(message)
        setIsPreviewing(false)
        closePreviewStream()
        toast.error(message)
      }
    }

    eventSource.onerror = () => {
      if (previewEventSourceRef.current !== eventSource) return
      closePreviewStream()
      setIsPreviewing(false)
      setPreviewStatus('连接中断')
    }
  }, [activeForm, closePreviewStream, normalizeVoiceConfig])

  const handleSave = async () => {
    if (!selected || !editable) return
    const trimmedName = editable.name.trim()
    const nameLength = getNameLength(editable.name)
    if (!trimmedName) {
      toast.error('名称不能为空')
      return
    }
    if (nameLength > 12) {
      toast.error('名称最多12个字符')
      return
    }

    setIsSaving(true)
    try {
      const voicePayload = toVoicePayload(editable.can_speak, editable.voice)
      await api.references.update(selected.id, {
        name: trimmedName,
        can_speak: editable.can_speak,
        setting: editable.setting,
        appearance_description: editable.appearance_description,
        ...voicePayload,
      })
      toast.success('参考已保存')
      setIsEditingDetail(false)
      await runRefresh()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '保存失败')
    } finally {
      setIsSaving(false)
    }
  }

  const handleDeleteItem = async (item: ReferenceLibraryItem) => {
    const confirmed = await confirmDialog({
      title: '删除参考',
      description: `确定删除参考「${item.name}」吗？`,
      confirmText: '删除',
      cancelText: '取消',
      variant: 'destructive',
    })
    if (!confirmed) return

    try {
      await deletingAction.run({
        id: item.id,
        task: () => api.references.delete(item.id),
        successMessage: '参考已删除',
        errorMessage: (error) => error instanceof Error ? error.message : '删除失败',
        onSuccess: async () => {
          if (selectedId === item.id) {
            setSelectedId(null)
            setEditable(null)
            setIsEditingDetail(false)
          }
          await runRefresh()
        },
      })
    } catch { /* toast handled in hook */ }
  }

  const handleCancelAllImports = async () => {
    setActiveJobIds([])
    try {
      const result = await api.references.cancelAllImportJobs()
      if (result.affected_tasks > 0) {
        toast.success(`已中断 ${result.affected_tasks} 个参考导入任务`)
      } else {
        toast.info('当前没有可中断的参考导入任务')
      }
      await runRefresh()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '中断任务失败')
    }
  }

  const handleRestartInterruptedImports = async () => {
    try {
      const result = await api.references.restartInterruptedImportTasks()
      if (result.affected_tasks > 0) {
        toast.success(`已重启 ${result.affected_tasks} 个中断任务`)
      } else {
        toast.info('当前没有可重启的中断任务')
      }
      await runRefresh()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '重启任务失败')
    }
  }

  const handleInterruptItemTask = async (item: ReferenceLibraryItem) => {
    try {
      const result = await api.references.cancelImportTaskByItem(item.id)
      if (result.affected_tasks > 0) {
        toast.success(`已中断参考任务：${item.name}`)
        await runRefresh()
      } else {
        toast.info('该参考没有进行中的导入任务')
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '中断任务失败')
    }
  }

  const handleRetryItem = async (item: ReferenceLibraryItem) => {
    try {
      await retryAction.run({
        id: item.id,
        task: () => api.references.retry(item.id),
        successMessage: '已重新开始任务',
        errorMessage: (error) => error instanceof Error ? error.message : '重试失败',
        onSuccess: async () => {
          await runRefresh()
        },
      })
    } catch {
      // toast handled in hook
    }
  }

  const handleToggleEnabled = async (item: ReferenceLibraryItem, nextEnabled: boolean) => {
    try {
      await togglingSpeakAction.run({
        id: item.id,
        task: () => api.references.update(item.id, { is_enabled: nextEnabled }),
        errorMessage: (error) => error instanceof Error ? error.message : '更新状态失败',
        onSuccess: async () => {
          await runRefresh()
        },
      })
    } catch { /* toast handled in hook */ }
  }

  const handleUploadImage = async (file: File) => {
    if (!selected) return
    setIsUploading(true)
    try {
      await api.references.uploadImage(selected.id, file)
      toast.success('图片已上传')
      await runRefresh()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '上传失败')
    } finally {
      setIsUploading(false)
      if (uploadInputRef.current) {
        uploadInputRef.current.value = ''
      }
    }
  }

  const handleDeleteImage = async () => {
    if (!selected) return
    setIsDeletingImage(true)
    try {
      await api.references.deleteImage(selected.id)
      toast.success('图片已删除')
      await runRefresh()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '删除失败')
    } finally {
      setIsDeletingImage(false)
    }
  }

  const handleGenerateDescriptionFromImage = async () => {
    if (!hasActiveImage) {
      toast.info('请先上传参考图片')
      return
    }

    if (isCreateMode) {
      if (!createFile) {
        toast.info('请先上传参考图片')
        return
      }
      setIsCreateGeneratingDescription(true)
      try {
        const result = await api.references.describeFromUpload(createFile)
        const description = String(result.appearance_description || '')
        const streamVersion = descriptionStreamVersionRef.current + 1
        descriptionStreamVersionRef.current = streamVersion
        setIsStreamingDescription(true)
        setCreateDraft((prev) => (prev ? { ...prev, appearance_description: '' } : prev))
        let cursor = 0
        while (cursor < description.length) {
          if (descriptionStreamVersionRef.current !== streamVersion) return
          const remain = description.length - cursor
          const step = remain > 160 ? 8 : remain > 64 ? 4 : 2
          cursor = Math.min(description.length, cursor + step)
          const partial = description.slice(0, cursor)
          setCreateDraft((prev) => (prev ? { ...prev, appearance_description: partial } : prev))
          await new Promise((resolve) => window.setTimeout(resolve, 18))
        }
        toast.success('外观描述已生成')
      } catch (error) {
        toast.error(error instanceof Error ? error.message : '生成描述失败')
      } finally {
        setIsStreamingDescription(false)
        setIsCreateGeneratingDescription(false)
      }
      return
    }

    if (!selected) return
    if (!selected.image_file_path) {
      toast.info('请先上传参考图片')
      return
    }

    const targetId = selected.id
    try {
      await generateDescriptionAction.run({
        id: targetId,
        task: () => api.references.describeFromImage(targetId),
        successMessage: '外观描述已生成',
        errorMessage: (error) => error instanceof Error ? error.message : '生成描述失败',
        onSuccess: async (result) => {
          const description = String(result.appearance_description || '')
          const streamVersion = descriptionStreamVersionRef.current + 1
          descriptionStreamVersionRef.current = streamVersion
          setIsStreamingDescription(true)
          setEditable((prev) => (prev ? { ...prev, appearance_description: '' } : prev))
          let cursor = 0
          while (cursor < description.length) {
            if (descriptionStreamVersionRef.current !== streamVersion) return
            const remain = description.length - cursor
            const step = remain > 160 ? 8 : remain > 64 ? 4 : 2
            cursor = Math.min(description.length, cursor + step)
            const partial = description.slice(0, cursor)
            setEditable((prev) => (prev ? { ...prev, appearance_description: partial } : prev))
            await new Promise((resolve) => window.setTimeout(resolve, 18))
          }
          await runRefresh()
        },
      })
    } catch { /* toast handled in hook */ }
    finally {
      setIsStreamingDescription(false)
    }
  }
  const isSelectedGeneratingDescription = selected
    ? generateDescriptionAction.pendingIds.has(selected.id)
    : false
  const isGeneratingDescription = isCreateMode ? isCreateGeneratingDescription : isSelectedGeneratingDescription
  const isDescriptionBusy = isGeneratingDescription || isStreamingDescription

  const buildCreateDraft = useCallback((): EditableReference => ({
    name: '',
    can_speak: false,
    setting: '',
    appearance_description: '',
    voice: normalizeVoiceConfig({ voice_audio_provider: defaultVoiceProvider }),
  }), [defaultVoiceProvider, normalizeVoiceConfig])

  const startManualCreate = useCallback(() => {
    setCreateDraft(buildCreateDraft())
    setCreateFile(null)
    setShowMethodDialog(false)
    setShowBatchDialog(false)
    setBatchRows([])
    setIsEditingDetail(true)
    setSelectedId(null)
    closePreviewStream()
    setIsPreviewing(false)
    setPreviewStatus('')
    setPreviewAudioUrl('')
    if (createUploadInputRef.current) {
      createUploadInputRef.current.value = ''
    }
  }, [buildCreateDraft, closePreviewStream])

  const handleOpenCreateMethod = useCallback(() => {
    setShowMethodDialog(true)
  }, [])

  const handleSelectCreateMethod = useCallback((method: 'manual' | 'batch') => {
    if (method === 'manual') {
      startManualCreate()
      return
    }
    setShowMethodDialog(false)
    setBatchRows([])
    setShowBatchDialog(true)
    if (batchImportInputRef.current) {
      batchImportInputRef.current.value = ''
    }
  }, [startManualCreate])

  const handleCancelCreate = useCallback(() => {
    descriptionStreamVersionRef.current += 1
    setIsStreamingDescription(false)
    setCreateDraft(null)
    setCreateFile(null)
    setIsEditingDetail(false)
    closePreviewStream()
    setIsPreviewing(false)
    setPreviewStatus('')
    setPreviewAudioUrl('')
    if (createUploadInputRef.current) {
      createUploadInputRef.current.value = ''
    }
  }, [closePreviewStream])

  const handlePickBatchFiles = useCallback((files: FileList | null) => {
    if (!files) return
    const selectedFiles = Array.from(files)
    if (selectedFiles.length === 0) return
    if (selectedFiles.length > LIBRARY_BATCH_MAX_ITEMS) {
      toast.error(`最多支持上传 ${LIBRARY_BATCH_MAX_ITEMS} 张图片`)
      return
    }
    const mappedRows = selectedFiles.map((file, index) => ({
      id: `${file.name}-${file.size}-${file.lastModified}-${index}`,
      file,
      name: '',
      generate_description: true,
    }))
    setBatchRows(mappedRows)
  }, [])

  const handleSubmitBatchImport = async () => {
    if (batchRows.length === 0) {
      toast.error('请先上传图片')
      return
    }
    setBatchSubmitting(true)
    try {
      const files = batchRows.map((row) => row.file)
      const rows: ReferenceLibraryImportImageRow[] = batchRows.map((row, index) => ({
        index,
        name: row.name.trim() || undefined,
        generate_description: row.generate_description,
      }))
      const result = await api.references.importImages(files, rows)
      setShowBatchDialog(false)
      setBatchRows([])
      setActiveJobIds((prev) => {
        const next = new Set(prev)
        const newIds = Array.isArray(result.job_ids) && result.job_ids.length > 0
          ? result.job_ids
          : [result.job_id]
        newIds.forEach((id) => next.add(id))
        return Array.from(next)
      })
      await runRefresh()
      toast.success(`已创建 ${result.item_ids.length} 张参考卡片`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '批量导入失败')
    } finally {
      setBatchSubmitting(false)
    }
  }

  const handleStartEditItem = useCallback((item: ReferenceLibraryItem) => {
    setCreateDraft(null)
    setCreateFile(null)
    setSelectedId(item.id)
    setEditable(buildEditableFromItem(item))
    setIsEditingDetail(true)
  }, [buildEditableFromItem])

  const handleCancelEdit = useCallback(() => {
    descriptionStreamVersionRef.current += 1
    setIsStreamingDescription(false)
    if (selected) {
      setEditable(buildEditableFromItem(selected))
    }
    setIsEditingDetail(false)
    closePreviewStream()
    setIsPreviewing(false)
    setPreviewStatus('')
    setPreviewAudioUrl('')
  }, [buildEditableFromItem, closePreviewStream, selected])

  const updateActiveForm = useCallback((updater: (prev: EditableReference) => EditableReference) => {
    if (isCreateMode) {
      setCreateDraft((prev) => prev ? updater(prev) : prev)
      return
    }
    setEditable((prev) => prev ? updater(prev) : prev)
  }, [isCreateMode])

  useEffect(() => () => {
    descriptionStreamVersionRef.current += 1
  }, [])

  const handleCreate = async () => {
    if (!createDraft) return
    const trimmedName = createDraft.name.trim()
    const nameLength = getNameLength(createDraft.name)
    if (!trimmedName) {
      toast.error('名称不能为空')
      return
    }
    if (nameLength > 12) {
      toast.error('名称最多12个字符')
      return
    }

    setIsCreating(true)
    try {
      const voicePayload = toVoicePayload(createDraft.can_speak, createDraft.voice)
      const item = await api.references.create({
        name: trimmedName,
        is_enabled: true,
        can_speak: createDraft.can_speak,
        setting: createDraft.setting,
        appearance_description: createDraft.appearance_description,
        ...voicePayload,
        file: createFile || undefined,
      })
      toast.success('参考已创建')
      setCreateDraft(null)
      setCreateFile(null)
      setIsEditingDetail(false)
      await runRefresh()
      setSelectedId(item.id)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '创建失败')
    } finally {
      setIsCreating(false)
    }
  }

  return (
    <div className="absolute inset-0 overflow-hidden">
      <div className="flex h-full min-h-0 flex-col px-4 py-6 md:px-8 lg:px-12">
        <div className={CATALOG_MAX_WIDTH_FLEX_COLUMN_CLASS}>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="icon" asChild>
              <Link href={returnHref} aria-label="返回" title="返回">
                <ArrowLeft className="h-4 w-4" />
              </Link>
            </Button>
            <div className="flex items-center gap-2">
              <Users className="h-5 w-5" />
              <h1 className="text-xl font-semibold">参考库</h1>
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
            placeholder="搜索参考名称..."
            isRefreshing={isFetching}
            onValueChange={onSearchTextChange}
            onSearch={onSearch}
            onRefresh={() => {
              void runRefresh()
            }}
          />
          </div>
        </div>

        <CatalogListHeader
          label="参考列表"
          total={total ?? 0}
          page={page}
          totalPages={totalPages}
          pageSize={pageSize}
          isFetching={isFetching}
          onPageChange={setPage}
          onPageSizeChange={onPageSizeChange}
        />

        <div className="min-h-0 flex-1">
          <div className="h-full overflow-y-auto pr-1">
            <CatalogQueryState
              isLoading={isLoading}
              error={error}
              hasData={sortedItems.length > 0}
              onRetry={() => {
                void runRefresh()
              }}
              loadingFallback={<div className="p-4 text-sm text-muted-foreground">加载中...</div>}
            >
              <div className={CATALOG_GRID_CARD_CLASS}>
                <CatalogCreateCard
                  title="新建参考"
                  icon={<Plus className="h-6 w-6 text-primary" />}
                  className="h-[252px]"
                  onClick={handleOpenCreateMethod}
                />

                {sortedItems.map((item) => {
                  const imageBase = resolveStorageFileUrl(item.image_file_path)
                  const imageUrl = imageBase ? `${imageBase}?t=${item.image_updated_at || 0}` : ''
                  const isTogglingSpeak = togglingSpeakAction.pendingIds.has(item.id)
                  const isDeleting = deletingAction.pendingIds.has(item.id)
                  const isRetrying = retryAction.pendingIds.has(item.id)
                  const processing = isItemProcessing(item)
                  const failed = isItemFailed(item)
                  const canceled = isItemCanceled(item)
                  const recoverable = failed || canceled
                  return (
                    <Card key={item.id} className="h-[252px] overflow-hidden transition-all hover:-translate-y-0.5 hover:shadow-md">
                      <CardContent className="flex h-full flex-col p-0">
                        <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2 px-4 pt-4">
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-col items-start gap-1">
                              <h3 className="max-w-full truncate text-base font-semibold leading-tight">{item.name}</h3>
                              <div className="flex items-center gap-1.5">
                                <Badge variant={item.can_speak ? 'default' : 'secondary'}>
                                  {item.can_speak ? '可说台词' : '不可说台词'}
                                </Badge>
                                {failed ? (
                                  <span className="rounded border border-destructive/30 bg-destructive/10 px-1.5 py-0.5 text-xs text-destructive">
                                    失败
                                  </span>
                                ) : canceled ? (
                                  <span className="rounded border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-xs text-amber-700">
                                    已中断
                                  </span>
                                ) : null}
                              </div>
                            </div>
                          </div>
                          <div className="flex items-center gap-1 justify-self-end">
                            <button
                              type="button"
                              role="switch"
                              aria-checked={item.is_enabled}
                              aria-label={item.is_enabled ? '禁用角色' : '启用角色'}
                              disabled={isTogglingSpeak || isDeleting}
                              onClick={() => {
                                void handleToggleEnabled(item, !item.is_enabled)
                              }}
                              className={`relative h-5 w-10 rounded-full transition-colors ${
                                item.is_enabled ? 'bg-zinc-900' : 'bg-zinc-400'
                              } ${(isTogglingSpeak || isDeleting) ? 'opacity-60' : ''}`}
                            >
                              <span
                                className={`absolute left-[3px] top-[3px] h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform ${
                                  item.is_enabled ? 'translate-x-5' : 'translate-x-0'
                                }`}
                              />
                            </button>
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8"
                              onClick={() => handleStartEditItem(item)}
                              disabled={isDeleting}
                              aria-label="编辑角色"
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
                                void handleDeleteItem(item)
                              }}
                              disabled={isDeleting}
                              aria-label={processing ? '中断任务' : '删除角色'}
                              title={processing ? '中断任务' : '删除角色'}
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
                                  void handleRetryItem(item)
                                }}
                                disabled={isDeleting || isRetrying}
                                aria-label="重试任务"
                                title="重试任务"
                              >
                                <RefreshCw className={`h-4 w-4 ${isRetrying ? 'animate-spin' : ''}`} />
                              </Button>
                            ) : null}
                          </div>
                        </div>

                        <div className="mt-3 flex h-40 items-center justify-center overflow-hidden border-y bg-muted/35 px-4">
                          {imageUrl ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                              src={imageUrl}
                              alt={item.name || '角色图片'}
                              loading="lazy"
                              className="h-full w-auto max-w-full object-contain"
                            />
                          ) : (
                            <div className="text-sm text-muted-foreground">暂无图片</div>
                          )}
                        </div>

                        <div className="px-4 py-3">
                          <p className="line-clamp-3 text-sm text-muted-foreground">
                            {String(item.setting || '').trim() || '未填写参考设定'}
                          </p>
                          {(processing || failed || canceled) && (item.processing_message || item.error_message) ? (
                            <div className={`mt-1 flex items-start gap-1 text-xs ${failed ? 'text-destructive' : canceled ? 'text-amber-700' : 'text-primary'}`}>
                              {(failed || canceled) ? null : <Loader2 className="mt-0.5 h-3 w-3 shrink-0 animate-spin" />}
                              <span className="line-clamp-2">
                                {item.error_message || item.processing_message || (canceled ? '任务已中断' : '')}
                              </span>
                            </div>
                          ) : null}
                        </div>
                      </CardContent>
                    </Card>
                  )
                })}
              </div>
            </CatalogQueryState>
          </div>
        </div>
        </div>

        <Dialog open={showMethodDialog} onOpenChange={setShowMethodDialog}>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>新增参考</DialogTitle>
            </DialogHeader>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <button
                className="rounded-lg border p-4 text-left transition-colors hover:bg-accent"
                onClick={() => handleSelectCreateMethod('manual')}
              >
                <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                  <Pencil className="h-4 w-4 text-emerald-500" />
                  手动单个编辑
                </div>
                <p className="text-xs text-muted-foreground">
                  前往编辑窗口填写名称、设定并上传图片。
                </p>
              </button>
              <button
                className="rounded-lg border p-4 text-left transition-colors hover:bg-accent"
                onClick={() => handleSelectCreateMethod('batch')}
              >
                <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                  <Upload className="h-4 w-4 text-blue-500" />
                  批量上传图片
                </div>
                <p className="text-xs text-muted-foreground">
                  一次上传最多 {LIBRARY_BATCH_MAX_ITEMS} 张图片，后台自动命名/生成描述并排队处理。
                </p>
              </button>
            </div>
          </DialogContent>
        </Dialog>

        <Dialog
          open={showBatchDialog}
          onOpenChange={(open) => {
            if (!open && batchSubmitting) {
              return
            }
            if (!open) {
              setShowBatchDialog(false)
              setBatchRows([])
              if (batchImportInputRef.current) {
                batchImportInputRef.current.value = ''
              }
              return
            }
            setShowBatchDialog(open)
          }}
        >
          <DialogContent
            className="sm:max-w-3xl"
            onEscapeKeyDown={(event) => {
              if (batchSubmitting) {
                event.preventDefault()
              }
            }}
            onPointerDownOutside={(event) => {
              if (batchSubmitting) {
                event.preventDefault()
              }
            }}
          >
            <DialogHeader>
              <DialogTitle>批量上传图片</DialogTitle>
            </DialogHeader>
            <div className="space-y-3">
              <input
                ref={batchImportInputRef}
                type="file"
                multiple
                accept="image/png,image/jpeg,image/webp"
                className="hidden"
                onChange={(event) => handlePickBatchFiles(event.target.files)}
              />
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => batchImportInputRef.current?.click()}
                  disabled={batchSubmitting}
                >
                  <Upload className="mr-2 h-4 w-4" />
                  {batchRows.length > 0 ? '重新选择图片' : '上传图片'}
                </Button>
                <span className="text-xs text-muted-foreground">最多 {LIBRARY_BATCH_MAX_ITEMS} 张</span>
              </div>

              {batchRows.length === 0 ? (
                <div className="flex h-28 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground">
                  请先上传图片
                </div>
              ) : (
                <div className="rounded-md border">
                  <div className="grid grid-cols-[44px_minmax(0,1fr)_minmax(0,1.4fr)_130px] items-center gap-2 border-b bg-muted/40 px-3 py-2 text-xs font-medium">
                    <span className="text-center">操作</span>
                    <span className="text-center">名称</span>
                    <span className="text-center">文件路径</span>
                    <span className="text-center">生成图片描述</span>
                  </div>
                  <div className="max-h-72 overflow-y-auto">
                    {batchRows.map((row) => (
                      <div
                        key={row.id}
                        className="grid grid-cols-[44px_minmax(0,1fr)_minmax(0,1.4fr)_130px] items-center gap-2 border-b px-3 py-2 last:border-b-0"
                      >
                        <div className="flex items-center justify-center">
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-destructive hover:text-destructive"
                            onClick={() => {
                              setBatchRows((prev) => prev.filter((item) => item.id !== row.id))
                            }}
                            disabled={batchSubmitting}
                            aria-label="删除上传图片记录"
                            title="删除记录"
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                        <Input
                          value={row.name}
                          onChange={(event) => {
                            const value = event.target.value
                            setBatchRows((prev) => prev.map((item) => (
                              item.id === row.id ? { ...item, name: value } : item
                            )))
                          }}
                          placeholder="可留空自动命名"
                          disabled={batchSubmitting}
                        />
                        <div className="truncate text-xs text-muted-foreground" title={row.file.name}>
                          {row.file.name}
                        </div>
                        <div className="flex items-center justify-center">
                          <Checkbox
                            checked={row.generate_description}
                            onCheckedChange={(checked) => {
                              const next = checked !== false
                              setBatchRows((prev) => prev.map((item) => (
                                item.id === row.id ? { ...item, generate_description: next } : item
                              )))
                            }}
                            disabled={batchSubmitting}
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
                  setShowBatchDialog(false)
                  setBatchRows([])
                  if (batchImportInputRef.current) {
                    batchImportInputRef.current.value = ''
                  }
                }}
                disabled={batchSubmitting}
              >
                取消
              </Button>
              <Button onClick={() => void handleSubmitBatchImport()} disabled={batchSubmitting || batchRows.length === 0}>
                {batchSubmitting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    创建中...
                  </>
                ) : '创建'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <Dialog
          open={isEditingDetail || isCreateMode}
          onOpenChange={(open) => {
            if (!open) {
              if (isCreateMode) {
                handleCancelCreate()
              } else {
                handleCancelEdit()
              }
              return
            }
            setIsEditingDetail(true)
          }}
        >
          <DialogContent className="max-h-[85vh] overflow-hidden sm:max-w-2xl">
            <DialogHeader>
              <DialogTitle>{isCreateMode ? '创建参考' : '编辑参考'}</DialogTitle>
            </DialogHeader>
            <div className="max-h-[calc(85vh-9rem)] space-y-4 overflow-y-auto pr-1">
              {!activeForm ? (
                <div className="text-sm text-muted-foreground">请选择一个参考进行编辑</div>
              ) : (
                <>
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <Label>参考名称</Label>
                      <span className={`text-xs ${activeNameLength > 12 ? 'text-destructive' : 'text-muted-foreground'}`}>
                        {activeNameLength}/12
                      </span>
                    </div>
                    <Input
                      value={activeForm.name}
                      onChange={(e) => updateActiveForm((prev) => ({ ...prev, name: e.target.value }))}
                    />
                    {activeNameError ? (
                      <p className="text-xs text-destructive">{activeNameError}</p>
                    ) : null}
                  </div>

                  <div className="space-y-2">
                    <Label>是否可说台词</Label>
                    <Select
                      value={activeForm.can_speak ? 'true' : 'false'}
                      onValueChange={(v) => updateActiveForm((prev) => {
                        const canSpeak = v !== 'false'
                        if (!canSpeak) {
                          return { ...prev, can_speak: false }
                        }
                        return {
                          ...prev,
                          can_speak: true,
                          voice: normalizeVoiceConfig(prev.voice),
                        }
                      })}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="true">可说台词</SelectItem>
                        <SelectItem value="false">不可说台词（如场景）</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  {activeForm.can_speak && (
                    <div className="space-y-2">
                      <ReferenceVoiceFields
                        value={(isCreateMode ? normalizedCreateVoice : normalizedEditableVoice) || activeForm.voice}
                        onChange={(next) => updateActiveForm((prev) => ({ ...prev, voice: next }))}
                        meta={voiceMeta}
                      />
                      <div className="flex items-center gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handlePreview()}
                          disabled={isPreviewing}
                        >
                          <Volume2 className="h-4 w-4 mr-1" />
                          {isPreviewing ? '试听中...' : '试听'}
                        </Button>
                        {previewStatus && (
                          <span className="text-xs text-muted-foreground">{previewStatus}</span>
                        )}
                      </div>
                      {previewAudioUrl && (
                        <AudioPlayer src={previewAudioUrl} className="w-full" />
                      )}
                    </div>
                  )}

                  <div className="space-y-2">
                    <Label>参考设定（可选）</Label>
                    <Textarea
                      className="min-h-[110px] max-h-[220px] overflow-y-auto resize-y"
                      value={activeForm.setting}
                      onChange={(e) => updateActiveForm((prev) => ({ ...prev, setting: e.target.value }))}
                    />
                    <p className="text-xs text-muted-foreground">
                      参考设定用于描述角色人设（身份、性格、语气等），不用于描述视觉外观。
                    </p>
                  </div>

                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <Label>参考外观描述（可选）</Label>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2"
                        onClick={() => void handleGenerateDescriptionFromImage()}
                        disabled={isDescriptionBusy || !hasActiveImage}
                        title={hasActiveImage ? '根据参考图片生成外观描述' : '请先上传参考图片'}
                      >
                        <Wand2 className={`h-3.5 w-3.5 mr-1 ${isDescriptionBusy ? 'animate-pulse' : ''}`} />
                        {isDescriptionBusy ? '生成中...' : '从图生成描述'}
                      </Button>
                    </div>
                    <Textarea
                      className="min-h-[130px] max-h-[260px] overflow-y-auto resize-y"
                      value={activeForm.appearance_description}
                      onChange={(e) => updateActiveForm((prev) => ({ ...prev, appearance_description: e.target.value }))}
                      disabled={isDescriptionBusy}
                    />
                    <p className="text-xs text-muted-foreground">
                      参考外观描述仅用于视觉生成（外形、服装、材质、镜头细节），不写性格与背景设定。
                    </p>
                    {!hasActiveImage && (
                      <p className="text-xs text-muted-foreground">上传参考图片后，可使用「从图生成描述」自动填写。</p>
                    )}
                  </div>

                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <Label>图片（可选）</Label>
                      <div className="flex items-center gap-2">
                        {isCreateMode ? (
                          <>
                            <input
                              ref={createUploadInputRef}
                              type="file"
                              accept="image/png,image/jpeg,image/webp"
                              className="hidden"
                              onChange={(e) => setCreateFile(e.target.files?.[0] || null)}
                            />
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => createUploadInputRef.current?.click()}
                            >
                              <Upload className="h-4 w-4 mr-1" />
                              {createFile ? '重新选择' : '选择图片'}
                            </Button>
                            {createFile && (
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => {
                                  setCreateFile(null)
                                  if (createUploadInputRef.current) {
                                    createUploadInputRef.current.value = ''
                                  }
                                }}
                              >
                                <Trash2 className="h-4 w-4 mr-1" />
                                清空
                              </Button>
                            )}
                          </>
                        ) : (
                          <>
                            <input
                              ref={uploadInputRef}
                              type="file"
                              accept="image/png,image/jpeg,image/webp"
                              className="hidden"
                              onChange={(e) => {
                                const file = e.target.files?.[0]
                                if (file) {
                                  void handleUploadImage(file)
                                }
                              }}
                            />
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-6 px-2"
                              onClick={() => uploadInputRef.current?.click()}
                              disabled={isUploading || isDeletingImage}
                            >
                              <Upload className="h-3 w-3 mr-1" />
                              {isUploading ? '上传中...' : (selectedImageUrl ? '重新上传' : '上传')}
                            </Button>
                            {selectedImageUrl && (
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-6 px-2 hover:text-destructive hover:bg-destructive/10"
                                onClick={() => void handleDeleteImage()}
                                disabled={isDeletingImage || isUploading}
                              >
                                <Trash2 className="h-3 w-3 mr-1" />
                                {isDeletingImage ? '删除中...' : '删除'}
                              </Button>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                    {activeImageUrl ? (
                      <div className="flex justify-center">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={activeImageUrl}
                          alt={selected?.name || activeForm.name || '参考图片'}
                          className="mx-auto max-h-72 w-auto rounded-lg border"
                        />
                      </div>
                    ) : (
                      <div className="h-44 border-2 border-dashed rounded-lg flex items-center justify-center text-sm text-muted-foreground">
                        暂无图片
                      </div>
                    )}
                  </div>

                  <DialogFooter className="gap-2 pt-2">
                    {isCreateMode ? (
                      <>
                        <Button variant="outline" onClick={() => handleCancelCreate()} disabled={isCreating}>
                          取消
                        </Button>
                        <Button onClick={() => void handleCreate()} disabled={isCreating || Boolean(activeNameError)}>
                          {isCreating ? '创建中...' : '创建参考'}
                        </Button>
                      </>
                    ) : (
                      <>
                        <Button variant="outline" onClick={() => handleCancelEdit()} disabled={isSaving}>
                          取消
                        </Button>
                        <Button onClick={() => void handleSave()} disabled={isSaving || Boolean(activeNameError)}>
                          {isSaving ? '保存中...' : '保存'}
                        </Button>
                      </>
                    )}
                  </DialogFooter>
                </>
              )}
            </div>
          </DialogContent>
        </Dialog>
      </div>
    </div>
  )
}
