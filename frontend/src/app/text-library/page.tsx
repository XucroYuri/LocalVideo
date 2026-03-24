'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'
import { useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  Clapperboard,
  Clipboard,
  FileText,
  Globe,
  Link2,
  Loader2,
  Music2,
  NotebookPen,
  Pause,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'

import { CatalogCreateCard } from '@/components/common/catalog-create-card'
import { CatalogListHeader } from '@/components/common/catalog-list-header'
import { CATALOG_GRID_CARD_CLASS, CATALOG_MAX_WIDTH_CLASS } from '@/components/common/catalog-layout'
import { CatalogQueryState } from '@/components/common/catalog-query-state'
import { CatalogSearchActions } from '@/components/common/catalog-search-actions'
import { useConfirmDialog } from '@/components/common/confirm-dialog-provider'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useCatalogPagedQuery } from '@/hooks/use-catalog-paged-query'
import { useCatalogRowAction } from '@/hooks/use-catalog-row-action'
import { api } from '@/lib/api-client'
import { LIBRARY_BATCH_MAX_ITEMS } from '@/lib/library-limits'
import { queryKeys } from '@/lib/query-keys'
import { cn } from '@/lib/utils'
import type {
  TextImportJobStatus,
  TextItemFieldStatus,
  TextLibraryItem,
  TextSourceChannel,
} from '@/types/text-library'

interface TextEditorDraft {
  name: string
  content: string
  is_enabled: boolean
}

type ImportMethod = 'copy' | 'files' | 'links'

const CHANNEL_META: Record<TextSourceChannel, { label: string; icon: typeof Clipboard; className: string }> = {
  copy: { label: '复制', icon: Clipboard, className: 'text-emerald-500' },
  file: { label: '文件', icon: FileText, className: 'text-blue-500' },
  web: { label: '网页', icon: Globe, className: 'text-sky-500' },
  xiaohongshu: { label: '小红书', icon: NotebookPen, className: 'text-rose-500' },
  douyin: { label: '抖音', icon: Music2, className: 'text-zinc-700' },
  kuaishou: { label: '快手', icon: Clapperboard, className: 'text-orange-500' },
}
const EDITOR_PLACEHOLDER_NAMES = new Set(['', '生成中', '解析中', '处理中', '处理中...'])

function createEmptyEditorDraft(): TextEditorDraft {
  return {
    name: '',
    content: '',
    is_enabled: true,
  }
}

function getNameLength(value: string): number {
  return Array.from(value.trim()).length
}

function isLinkChannel(channel: TextSourceChannel): boolean {
  return channel === 'web' || channel === 'xiaohongshu' || channel === 'douyin' || channel === 'kuaishou'
}

function isFieldProcessing(status: TextItemFieldStatus | undefined): boolean {
  return status === 'pending' || status === 'running'
}

function isFieldFailed(status: TextItemFieldStatus | undefined): boolean {
  return status === 'failed'
}

function isFieldCanceled(status: TextItemFieldStatus | undefined): boolean {
  return status === 'canceled'
}

function isItemReady(item: TextLibraryItem | null | undefined): boolean {
  if (!item) return false
  return item.title_status === 'ready' && item.content_status === 'ready' && !item.error_message
}

function isItemFailed(item: TextLibraryItem): boolean {
  return !!(item.error_message || isFieldFailed(item.title_status) || isFieldFailed(item.content_status))
}

function isItemCanceled(item: TextLibraryItem): boolean {
  return isFieldCanceled(item.title_status) || isFieldCanceled(item.content_status)
}

function isItemProcessing(item: TextLibraryItem): boolean {
  return isFieldProcessing(item.title_status) || isFieldProcessing(item.content_status)
}

function getInterruptedStatusLabel(item: TextLibraryItem): string | null {
  if (isItemCanceled(item)) return '已中断'
  if (isItemFailed(item)) return '失败'
  return null
}

function interruptedStatusClassName(item: TextLibraryItem): string {
  if (isItemCanceled(item)) {
    return 'bg-amber-500/10 text-amber-700 border-amber-500/30'
  }
  if (isItemFailed(item)) {
    return 'bg-destructive/10 text-destructive border-destructive/30'
  }
  return ''
}

function extractProgressPercent(message: string | null | undefined): number | null {
  const normalized = String(message || '')
  const matched = normalized.match(/(\d{1,3})\s*%/)
  if (!matched) return null
  const value = Number.parseInt(matched[1] || '', 10)
  if (!Number.isFinite(value)) return null
  return Math.max(0, Math.min(100, value))
}

function isJobRunning(status: TextImportJobStatus | undefined): boolean {
  return status === 'pending' || status === 'running'
}

export default function TextLibraryPage() {
  const queryClient = useQueryClient()
  const confirmDialog = useConfirmDialog()
  const fileImportRef = useRef<HTMLInputElement | null>(null)
  const importEventSourceRef = useRef<EventSource | null>(null)
  const updateEnabledAction = useCatalogRowAction<number>()
  const deletingAction = useCatalogRowAction<number>()
  const retryAction = useCatalogRowAction<number>()

  const [showMethodDialog, setShowMethodDialog] = useState(false)
  const [showCopyDialog, setShowCopyDialog] = useState(false)
  const [copyText, setCopyText] = useState('')
  const [copySubmitting, setCopySubmitting] = useState(false)

  const [showLinksDialog, setShowLinksDialog] = useState(false)
  const [linksText, setLinksText] = useState('')
  const [linksSubmitting, setLinksSubmitting] = useState(false)
  const [activeJobIds, setActiveJobIds] = useState<string[]>([])

  const [editorOpen, setEditorOpen] = useState(false)
  const [editingItemId, setEditingItemId] = useState<number | null>(null)
  const [editorDraft, setEditorDraft] = useState<TextEditorDraft>(createEmptyEditorDraft)
  const [editorSubmitting, setEditorSubmitting] = useState(false)

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
  } = useCatalogPagedQuery<TextLibraryItem>({
    getQueryKey: ({ searchQuery, page, pageSize }) => queryKeys.textLibrary.list(searchQuery, page, pageSize),
    queryFn: ({ page, dataPageSize, searchQuery }) =>
      api.textLibrary.list({ q: searchQuery, page, pageSize: dataPageSize }),
  })

  const sortedItems = useMemo(
    () => [...items].sort((left, right) => right.id - left.id),
    [items]
  )

  const liveEditingItem = useMemo(() => {
    if (!editingItemId) return null
    return sortedItems.find((item) => item.id === editingItemId) ?? null
  }, [editingItemId, sortedItems])

  const editingReady = isItemReady(liveEditingItem)

  useEffect(() => {
    if (!editorOpen || !liveEditingItem) return
    setEditorDraft((prev) => {
      if (!editingReady) {
        return {
          name: liveEditingItem.name,
          content: liveEditingItem.content,
          is_enabled: liveEditingItem.is_enabled,
        }
      }

      const prevName = prev.name.trim()
      if (!EDITOR_PLACEHOLDER_NAMES.has(prevName)) {
        return prev
      }
      return {
        name: liveEditingItem.name,
        content: liveEditingItem.content,
        is_enabled: liveEditingItem.is_enabled,
      }
    })
  }, [editorOpen, liveEditingItem, editingReady])

  const nameLength = useMemo(() => getNameLength(editorDraft.name), [editorDraft.name])
  const trimmedName = useMemo(() => editorDraft.name.trim(), [editorDraft.name])
  const trimmedContent = useMemo(() => editorDraft.content.trim(), [editorDraft.content])

  const nameError = useMemo(() => {
    if (!trimmedName) return '名称不能为空'
    if (nameLength > 30) return '名称最多30个字符'
    return ''
  }, [nameLength, trimmedName])

  const contentError = useMemo(() => (!trimmedContent ? '内容不能为空' : ''), [trimmedContent])
  const canSubmitEditor = editingReady && !editorSubmitting && !nameError && !contentError

  const invalidateTextLibrary = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.textLibrary.root })
  }, [queryClient])

  const closeImportStream = useCallback(() => {
    if (!importEventSourceRef.current) return
    importEventSourceRef.current.close()
    importEventSourceRef.current = null
  }, [])

  const hasProcessingItems = useMemo(() => {
    return sortedItems.some((item) => isItemProcessing(item))
  }, [sortedItems])
  const hasInterruptedItems = useMemo(() => {
    return sortedItems.some((item) => isItemCanceled(item) || isItemFailed(item))
  }, [sortedItems])

  const processingPollIntervalMs = useMemo(() => {
    if (editorOpen && liveEditingItem && !editingReady) return 600
    return 2000
  }, [editorOpen, liveEditingItem, editingReady])

  useEffect(() => {
    return () => {
      closeImportStream()
    }
  }, [closeImportStream])

  useEffect(() => {
    if (!hasProcessingItems) return
    const timer = window.setInterval(() => {
      void refetch()
    }, processingPollIntervalMs)
    return () => window.clearInterval(timer)
  }, [hasProcessingItems, processingPollIntervalMs, refetch])

  useEffect(() => {
    if (activeJobIds.length === 0) return
    const timer = window.setInterval(() => {
      void Promise.all(activeJobIds.map((jobId) => api.textLibrary.getImportJob(jobId).then((job) => ({ jobId, job }))))
        .then((results) => {
          const finishedIds: string[] = []
          for (const { jobId, job } of results) {
            if (!isJobRunning(job.status)) {
              finishedIds.push(jobId)
              const canceledCount = Number(job.canceled_count || 0)
              if (job.success_count > 0 && job.failed_count === 0 && canceledCount === 0) {
                toast.success(`链接导入完成：成功 ${job.success_count}`)
              } else if (job.success_count > 0 && canceledCount > 0) {
                toast.warning(`链接导入完成：成功 ${job.success_count}，中断 ${canceledCount}`)
              } else if (job.success_count > 0) {
                toast.warning(`链接导入完成：成功 ${job.success_count}，失败 ${job.failed_count}`)
              } else if (canceledCount > 0 && job.failed_count === 0) {
                toast.info(`链接导入已中断：共 ${canceledCount}`)
              } else {
                toast.error(job.error_message || '链接导入失败')
              }
            }
          }
          if (finishedIds.length > 0) {
            setActiveJobIds((prev) => prev.filter((id) => !finishedIds.includes(id)))
            void invalidateTextLibrary()
          }
        })
        .catch(() => undefined)
    }, 2000)
    return () => window.clearInterval(timer)
  }, [activeJobIds, invalidateTextLibrary])

  useEffect(() => {
    let disposed = false
    let retryTimer: number | null = null
    let retryAttempt = 0

    const connectImportStream = () => {
      if (disposed) return
      closeImportStream()
      const eventSource = new EventSource(api.textLibrary.importEventsStreamUrl())
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
          void invalidateTextLibrary()
        } catch {
          // ignore bad payload
        }
      })

      eventSource.onerror = () => {
        if (importEventSourceRef.current !== eventSource) return
        eventSource.close()
        importEventSourceRef.current = null
        void invalidateTextLibrary()
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
  }, [closeImportStream, invalidateTextLibrary])

  const openImportMethodDialog = () => {
    setShowMethodDialog(true)
  }

  const handleSelectMethod = (method: ImportMethod) => {
    setShowMethodDialog(false)
    if (method === 'copy') {
      setCopyText('')
      setShowCopyDialog(true)
      return
    }
    if (method === 'files') {
      fileImportRef.current?.click()
      return
    }
    setLinksText('')
    setShowLinksDialog(true)
  }

  const handleCopySubmit = async () => {
    const content = copyText.trim()
    if (!content) {
      toast.error('请输入文本内容')
      return
    }
    setShowCopyDialog(false)
    setCopyText('')
    setCopySubmitting(true)
    try {
      await api.textLibrary.importCopy(content)
      await invalidateTextLibrary()
      toast.success('导入任务已创建')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '导入失败')
    } finally {
      setCopySubmitting(false)
    }
  }

  const handleImportFiles = async (files: FileList | null) => {
    if (!files) return
    const selected = Array.from(files)
    if (selected.length === 0) return
    if (selected.length > LIBRARY_BATCH_MAX_ITEMS) {
      toast.error(`最多支持 ${LIBRARY_BATCH_MAX_ITEMS} 个文件`)
      return
    }
    const unsupported = selected.filter((file) => {
      const name = file.name.toLowerCase()
      return !(name.endsWith('.txt') || name.endsWith('.md') || name.endsWith('.markdown'))
    })
    if (unsupported.length > 0) {
      toast.error('仅支持 txt 和 markdown 文件')
      return
    }

    try {
      const created = await api.textLibrary.importFiles(selected)
      await invalidateTextLibrary()
      toast.success(`已创建 ${created.length} 个导入任务`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '文件导入失败')
    } finally {
      if (fileImportRef.current) {
        fileImportRef.current.value = ''
      }
    }
  }

  const handleSubmitLinksImport = async () => {
    const normalized = linksText.trim()
    if (!normalized) {
      toast.error('请输入链接')
      return
    }
    const linkCount = normalized.split(/\s+/).filter(Boolean).length
    if (linkCount > LIBRARY_BATCH_MAX_ITEMS) {
      toast.error(`最多支持 ${LIBRARY_BATCH_MAX_ITEMS} 个链接`)
      return
    }
    setShowLinksDialog(false)
    setLinksText('')
    setLinksSubmitting(true)
    try {
      const result = await api.textLibrary.importLinks(normalized)
      setActiveJobIds((prev) => {
        const next = new Set(prev)
        const newIds = Array.isArray(result.job_ids) && result.job_ids.length > 0
          ? result.job_ids
          : [result.job_id]
        newIds.forEach((id) => next.add(id))
        return Array.from(next)
      })
      await invalidateTextLibrary()
      toast.success(`已创建 ${result.item_ids.length} 个链接导入任务`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '提交失败')
    } finally {
      setLinksSubmitting(false)
    }
  }

  const handleToggleEnabled = async (item: TextLibraryItem, nextEnabled: boolean) => {
    try {
      await updateEnabledAction.run({
        id: item.id,
        task: () => api.textLibrary.update(item.id, { is_enabled: nextEnabled }),
        invalidateQueryKeys: [queryKeys.textLibrary.root],
        errorMessage: (error) => error instanceof Error ? error.message : '更新启用状态失败',
      })
    } catch {
      // toast handled in hook
    }
  }

  const handleCancelAllImports = async () => {
    setActiveJobIds([])
    try {
      const result = await api.textLibrary.cancelAllImportJobs()
      if (result.affected_tasks > 0) {
        toast.success(`已中断 ${result.affected_tasks} 个文本导入任务`)
      } else {
        toast.info('当前没有可中断的文本导入任务')
      }
      await invalidateTextLibrary()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '中断任务失败')
    }
  }

  const handleRestartInterruptedImports = async () => {
    try {
      const result = await api.textLibrary.restartInterruptedImportTasks()
      if (result.affected_tasks > 0) {
        toast.success(`已重启 ${result.affected_tasks} 个中断任务`)
      } else {
        toast.info('当前没有可重启的中断任务')
      }
      await invalidateTextLibrary()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '重启任务失败')
    }
  }

  const handleInterruptItemTask = async (item: TextLibraryItem) => {
    try {
      const result = await api.textLibrary.cancelImportTaskByItem(item.id)
      if (result.affected_tasks > 0) {
        toast.success(`已中断文本任务：${item.name}`)
        await invalidateTextLibrary()
      } else {
        toast.info('该文本没有进行中的导入任务')
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '中断任务失败')
    }
  }

  const handleRetry = async (item: TextLibraryItem) => {
    try {
      await retryAction.run({
        id: item.id,
        task: () => api.textLibrary.retry(item.id),
        invalidateQueryKeys: [queryKeys.textLibrary.root],
        successMessage: '已重新开始任务',
        errorMessage: (error) => error instanceof Error ? error.message : '重试失败',
      })
    } catch {
      // toast handled in hook
    }
  }

  const handleDelete = async (item: TextLibraryItem) => {
    const confirmed = await confirmDialog({
      title: '删除文本卡片',
      description: `确定删除文本卡片「${item.name}」吗？`,
      confirmText: '删除',
      cancelText: '取消',
      variant: 'destructive',
    })
    if (!confirmed) return
    try {
      await deletingAction.run({
        id: item.id,
        task: () => api.textLibrary.delete(item.id),
        invalidateQueryKeys: [queryKeys.textLibrary.root],
        successMessage: '已删除',
        errorMessage: (error) => error instanceof Error ? error.message : '删除失败',
      })
    } catch {
      // toast handled in hook
    }
  }

  const openEditor = (item: TextLibraryItem) => {
    setEditingItemId(item.id)
    setEditorDraft({
      name: item.name,
      content: item.content,
      is_enabled: item.is_enabled,
    })
    setEditorOpen(true)
  }

  const closeEditor = () => {
    setEditorOpen(false)
    setEditingItemId(null)
    setEditorDraft(createEmptyEditorDraft())
  }

  const handleSubmitEditor = async () => {
    if (!liveEditingItem || !canSubmitEditor) return
    setEditorSubmitting(true)
    try {
      await api.textLibrary.update(liveEditingItem.id, {
        name: trimmedName,
        content: trimmedContent,
        is_enabled: editorDraft.is_enabled,
      })
      await invalidateTextLibrary()
      closeEditor()
      toast.success('已更新文本卡片')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : '更新失败')
    } finally {
      setEditorSubmitting(false)
    }
  }

  return (
    <div className="absolute inset-0 overflow-auto">
      <input
        ref={fileImportRef}
        type="file"
        accept=".txt,.md,.markdown,text/plain,text/markdown"
        className="hidden"
        multiple
        onChange={(event) => {
          void handleImportFiles(event.target.files)
        }}
      />

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
                <FileText className="h-5 w-5 text-foreground" />
                <h1 className="text-xl font-semibold">文本库</h1>
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
                placeholder="搜索文本卡片名称..."
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
            label="文本卡片列表"
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
                title="新增文本预设"
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
                const processingPercent = extractProgressPercent(item.processing_message)
                const sourceMeta = CHANNEL_META[item.source_channel]
                const SourceIcon = sourceMeta.icon
                const interruptedStatusLabel = getInterruptedStatusLabel(item)
                const primaryRecoverableMessage = item.error_message || (canceled ? '任务已中断' : '解析失败')
                const secondaryMessage = String(item.processing_message || '').trim()
                return (
                  <Card key={item.id} className="h-[252px] overflow-hidden transition-all hover:-translate-y-0.5 hover:shadow-md">
                    <CardContent className="flex h-full flex-col p-0">
                      <div className="flex items-start justify-between gap-2 px-4 pt-4">
                        <div className="min-w-0 flex-1">
                          <h3 className="truncate text-base font-semibold leading-tight">
                            {item.name?.trim() || (processing ? '处理中...' : '未命名')}
                          </h3>
                          <div className="mt-1 flex items-center gap-1.5 text-xs">
                            {interruptedStatusLabel ? (
                              <span className={cn('rounded border px-1.5 py-0.5', interruptedStatusClassName(item))}>
                                {interruptedStatusLabel}
                              </span>
                            ) : null}
                          </div>
                        </div>
                        <div className="flex items-center gap-1">
                          <button
                            type="button"
                            role="switch"
                            aria-checked={item.is_enabled}
                            aria-label={item.is_enabled ? '禁用文本卡片' : '启用文本卡片'}
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
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            onClick={() => openEditor(item)}
                            disabled={isDeleting}
                            aria-label="编辑文本卡片"
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
                            aria-label={processing ? '中断任务' : '删除文本卡片'}
                            title={processing ? '中断任务' : '删除文本卡片'}
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
                        </div>
                      </div>

                      <div className="min-h-[92px] px-4 pb-3 pt-2">
                        {isFieldProcessing(item.content_status) ? (
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
                          <p className={cn('line-clamp-4 text-[12px] leading-5', canceled ? 'text-amber-700' : 'text-destructive')}>
                            {primaryRecoverableMessage}
                          </p>
                        ) : (
                          <p className="line-clamp-4 text-[13px] leading-5 text-muted-foreground">
                            {item.content?.trim() || '暂无内容'}
                          </p>
                        )}
                        {secondaryMessage
                          && !isFieldProcessing(item.content_status)
                          && secondaryMessage !== String(primaryRecoverableMessage || '').trim() ? (
                          <p className="mt-1 line-clamp-1 text-[11px] text-muted-foreground">{item.processing_message}</p>
                        ) : null}
                      </div>

                      <div className="mt-auto border-t border-dashed bg-muted/35 px-3 py-3">
                        <div className="flex items-center justify-center gap-2">
                          <div
                            title={sourceMeta.label}
                            className={cn(
                              'flex h-7 w-7 items-center justify-center rounded border border-primary/40 bg-primary/10',
                              sourceMeta.className
                            )}
                          >
                            <SourceIcon className="h-3.5 w-3.5" />
                          </div>
                        </div>
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
            <DialogTitle>新增文本预设</DialogTitle>
            <DialogDescription>请选择导入方式</DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <button
              className="rounded-lg border p-4 text-left transition-colors hover:bg-accent"
              onClick={() => handleSelectMethod('copy')}
            >
              <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                <Clipboard className="h-4 w-4 text-emerald-500" />
                复制文字
              </div>
              <p className="text-xs text-muted-foreground">直接输入文本。</p>
            </button>
            <button
              className="rounded-lg border p-4 text-left transition-colors hover:bg-accent"
              onClick={() => handleSelectMethod('files')}
            >
              <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                <FileText className="h-4 w-4 text-blue-500" />
                上传文件
              </div>
              <p className="text-xs text-muted-foreground">支持 txt / markdown 格式，1 次最多 {LIBRARY_BATCH_MAX_ITEMS} 个文件。</p>
            </button>
            <button
              className="rounded-lg border p-4 text-left transition-colors hover:bg-accent"
              onClick={() => handleSelectMethod('links')}
            >
              <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                <Link2 className="h-4 w-4 text-sky-500" />
                链接导入
              </div>
              <p className="text-xs text-muted-foreground">支持网页、小红书、抖音、快手链接，1 次最多 {LIBRARY_BATCH_MAX_ITEMS} 个链接。</p>
            </button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={showCopyDialog} onOpenChange={setShowCopyDialog}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>复制文字导入</DialogTitle>
          </DialogHeader>
          <Textarea
            className="min-h-[220px]"
            placeholder="请输入文本内容..."
            value={copyText}
            onChange={(event) => setCopyText(event.target.value)}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowCopyDialog(false)} disabled={copySubmitting}>
              取消
            </Button>
            <Button onClick={() => void handleCopySubmit()} disabled={copySubmitting}>
              {copySubmitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  提交中...
                </>
              ) : '提交'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showLinksDialog} onOpenChange={setShowLinksDialog}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>链接导入</DialogTitle>
            <DialogDescription>
              如要添加多个网址，请用空格或换行符分隔，最多支持 {LIBRARY_BATCH_MAX_ITEMS} 个链接。导入后会立即生成占位卡片，并在后台持续排队解析。
            </DialogDescription>
          </DialogHeader>
          <Textarea
            className="min-h-[180px]"
            placeholder="请输入一个或多个链接..."
            value={linksText}
            onChange={(event) => setLinksText(event.target.value)}
            disabled={linksSubmitting}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowLinksDialog(false)} disabled={linksSubmitting}>
              取消
            </Button>
            <Button onClick={() => void handleSubmitLinksImport()} disabled={linksSubmitting}>
              {linksSubmitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  提交中...
                </>
              ) : '开始导入'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={editorOpen} onOpenChange={(open) => { if (!open) closeEditor() }}>
        <DialogContent className="sm:max-w-xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>编辑文本卡片</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            {liveEditingItem && !editingReady ? (
              <div className={cn(
                'rounded-md border px-3 py-2 text-sm',
                liveEditingItem.error_message
                  || isFieldFailed(liveEditingItem.title_status)
                  || isFieldFailed(liveEditingItem.content_status)
                  || isFieldCanceled(liveEditingItem.title_status)
                  || isFieldCanceled(liveEditingItem.content_status)
                  ? 'border-destructive/30 bg-destructive/5 text-destructive'
                  : 'border-primary/30 bg-primary/5 text-primary'
              )}>
                <div className="flex items-center gap-2">
                  {liveEditingItem.error_message
                    || isFieldFailed(liveEditingItem.title_status)
                    || isFieldFailed(liveEditingItem.content_status)
                    || isFieldCanceled(liveEditingItem.title_status)
                    || isFieldCanceled(liveEditingItem.content_status) ? null : (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  )}
                  <span>{liveEditingItem.processing_message || '任务处理中...'}</span>
                </div>
                {extractProgressPercent(liveEditingItem.processing_message) !== null ? (
                  <div className="mt-2 h-1.5 w-full overflow-hidden rounded bg-primary/20">
                    <div
                      className="h-full bg-primary transition-all"
                      style={{ width: `${extractProgressPercent(liveEditingItem.processing_message) ?? 0}%` }}
                    />
                  </div>
                ) : null}
                {liveEditingItem.error_message ? (
                  <p className="mt-1 whitespace-pre-wrap break-words text-xs">{liveEditingItem.error_message}</p>
                ) : null}
              </div>
            ) : null}

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="text-card-name">名称</Label>
                <span className={cn('text-xs', nameLength > 30 ? 'text-destructive' : 'text-muted-foreground')}>
                  {nameLength}/30
                </span>
              </div>
              <Input
                id="text-card-name"
                value={editorDraft.name}
                onChange={(event) => {
                  setEditorDraft((prev) => ({ ...prev, name: event.target.value }))
                }}
                placeholder="请输入名称"
                disabled={!editingReady || editorSubmitting}
              />
              {nameError ? <p className="text-xs text-destructive">{nameError}</p> : null}
            </div>

            {liveEditingItem && isLinkChannel(liveEditingItem.source_channel) && liveEditingItem.source_url ? (
              <div className="space-y-1">
                <Label>原始链接</Label>
                <a
                  href={liveEditingItem.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="block break-all rounded-md border bg-muted/40 px-3 py-2 text-sm text-primary underline"
                >
                  {liveEditingItem.source_url}
                </a>
                {liveEditingItem.source_post_id ? (
                  <p className="text-xs text-muted-foreground">帖子 ID：{liveEditingItem.source_post_id}</p>
                ) : null}
              </div>
            ) : null}

            <div className="space-y-2">
              <Label htmlFor="text-card-content">内容</Label>
              <Textarea
                id="text-card-content"
                className="min-h-[220px] max-h-[60vh] overflow-y-auto field-sizing-fixed"
                value={editorDraft.content}
                onChange={(event) => {
                  setEditorDraft((prev) => ({ ...prev, content: event.target.value }))
                }}
                placeholder="请输入内容"
                disabled={!editingReady || editorSubmitting}
              />
              {contentError ? <p className="text-xs text-destructive">{contentError}</p> : null}
            </div>

            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={editorDraft.is_enabled}
                disabled={!editingReady || editorSubmitting}
                onChange={(event) => {
                  setEditorDraft((prev) => ({ ...prev, is_enabled: event.target.checked }))
                }}
              />
              启用该卡片
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={closeEditor} disabled={editorSubmitting}>
              取消
            </Button>
            <Button onClick={() => void handleSubmitEditor()} disabled={!canSubmitEditor}>
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
