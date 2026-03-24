'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Search, Plus, FileText, Globe, ChevronLeft, Loader2, Trash2, Brain, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import ReactMarkdown from 'react-markdown'
import remarkBreaks from 'remark-breaks'
import remarkGfm from 'remark-gfm'
import { cn } from '@/lib/utils'
import type { Source } from '@/types/source'
import type { SourceImportFromTextLibraryResponse, TextLibraryItem } from '@/types/text-library'

interface SourcePanelProps {
  projectId: number
  sources: Source[]
  onSearch: (keywords: string, searchType: 'web' | 'deep') => Promise<void>
  onAddText: (text: string) => void
  textLibraryItems: TextLibraryItem[]
  onImportFromTextLibrary: (textLibraryIds: number[]) => Promise<SourceImportFromTextLibraryResponse>
  onToggleSelected: (sourceId: number, selected: boolean) => Promise<void>
  onDeleteSource: (sourceId: number) => Promise<void>
  isSearching: boolean
}

const SOURCE_TYPE_META = {
  search: {
    icon: Globe,
    color: 'text-blue-500',
  },
  deep_research: {
    icon: Brain,
    color: 'text-violet-500',
  },
  text: {
    icon: FileText,
    color: 'text-green-500',
  },
} as const

export function SourcePanel({
  sources,
  onSearch,
  onAddText,
  textLibraryItems,
  onImportFromTextLibrary,
  onToggleSelected,
  onDeleteSource,
  isSearching,
}: SourcePanelProps) {
  const [keywords, setKeywords] = useState('')
  const [showTextInput, setShowTextInput] = useState(false)
  const [textInput, setTextInput] = useState('')
  const [searchType, setSearchType] = useState<'web' | 'deep'>('web')
  const [viewingSourceId, setViewingSourceId] = useState<number | null>(null)
  const keywordTextareaRef = useRef<HTMLTextAreaElement | null>(null)
  const [showImportDialog, setShowImportDialog] = useState(false)
  const [selectedTextLibraryIds, setSelectedTextLibraryIds] = useState<number[]>([])
  const [isImporting, setIsImporting] = useState(false)
  const [importResult, setImportResult] = useState<SourceImportFromTextLibraryResponse | null>(null)

  // Delete confirmation dialog state
  const [showDeleteDialog, setShowDeleteDialog] = useState(false)
  const [sourceToDelete, setSourceToDelete] = useState<Source | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)

  const handleSearch = async () => {
    if (!keywords.trim() || isSearching) return
    await onSearch(keywords, searchType)
  }

  const adjustKeywordTextareaHeight = useCallback(() => {
    const textarea = keywordTextareaRef.current
    if (!textarea) return
    if (!textarea.value.trim()) {
      textarea.style.height = '40px'
      textarea.style.overflowY = 'hidden'
      return
    }
    const maxHeightPx = 160
    textarea.style.height = 'auto'
    const nextHeight = Math.min(textarea.scrollHeight, maxHeightPx)
    textarea.style.height = `${nextHeight}px`
    textarea.style.overflowY = textarea.scrollHeight > maxHeightPx ? 'auto' : 'hidden'
  }, [])

  useEffect(() => {
    adjustKeywordTextareaHeight()
  }, [keywords, adjustKeywordTextareaHeight])

  const handleAddText = () => {
    if (!textInput.trim()) return
    onAddText(textInput)
    setTextInput('')
    setShowTextInput(false)
  }

  const handleOpenImportDialog = () => {
    setSelectedTextLibraryIds([])
    setImportResult(null)
    setShowImportDialog(true)
  }

  const handleToggleTextLibrarySelection = (itemId: number, checked: boolean) => {
    setSelectedTextLibraryIds((prev) => {
      if (checked) {
        if (prev.includes(itemId)) return prev
        return [...prev, itemId]
      }
      return prev.filter((id) => id !== itemId)
    })
  }

  const handleConfirmImportFromTextLibrary = async () => {
    if (selectedTextLibraryIds.length === 0) return
    setIsImporting(true)
    try {
      const result = await onImportFromTextLibrary(selectedTextLibraryIds)
      setImportResult(result)
      setSelectedTextLibraryIds([])
    } finally {
      setIsImporting(false)
    }
  }

  const handleToggleSelected = async (e: React.MouseEvent, source: Source) => {
    e.stopPropagation()
    await onToggleSelected(source.id, !source.selected)
  }

  const handleDeleteClick = (e: React.MouseEvent, source: Source) => {
    e.stopPropagation()
    setSourceToDelete(source)
    setShowDeleteDialog(true)
  }

  const handleConfirmDelete = async () => {
    if (!sourceToDelete) return
    setIsDeleting(true)
    try {
      await onDeleteSource(sourceToDelete.id)
      setShowDeleteDialog(false)
      setSourceToDelete(null)
      // 如果正在查看被删除的来源，返回列表
      if (viewingSourceId === sourceToDelete.id) {
        setViewingSourceId(null)
      }
    } finally {
      setIsDeleting(false)
    }
  }

  const handleCancelDelete = () => {
    setShowDeleteDialog(false)
    setSourceToDelete(null)
  }

  const viewingSource = viewingSourceId
    ? sources.find(s => s.id === viewingSourceId)
    : null

  const selectedSearchIcon = searchType === 'deep' ? Brain : Globe
  const searchPlaceholder =
    searchType === 'deep'
      ? '输入研究问题或主题（可包含背景与约束）...'
      : '搜索关键词，用空格分隔...'

  if (viewingSource) {
    const ViewingIcon = SOURCE_TYPE_META[viewingSource.type].icon
    const viewingIconColor = SOURCE_TYPE_META[viewingSource.type].color
    return (
      <div className="h-full flex flex-col bg-background overflow-hidden">
        <div className="flex-shrink-0 p-4 border-b">
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setViewingSourceId(null)}
              className="gap-1"
            >
              <ChevronLeft className="h-4 w-4" />
              返回
            </Button>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <ViewingIcon className={cn('h-4 w-4 flex-shrink-0', viewingIconColor)} />
                <span className="font-medium truncate">{viewingSource.title}</span>
              </div>
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
              onClick={(e) => handleDeleteClick(e, viewingSource)}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </div>
        <ScrollArea className="flex-1 min-h-0">
          <div className="p-4 min-w-0">
            <div
              className="w-full min-w-0 overflow-x-auto break-words [overflow-wrap:anywhere] [word-break:break-word] text-sm bg-muted p-4 rounded-lg font-sans"
            >
              <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkBreaks]}
                components={{
                  h1: ({ children, ...props }) => <h1 className="mt-4 mb-2 text-base font-semibold" {...props}>{children}</h1>,
                  h2: ({ children, ...props }) => <h2 className="mt-4 mb-2 text-sm font-semibold" {...props}>{children}</h2>,
                  h3: ({ children, ...props }) => <h3 className="mt-3 mb-1 text-sm font-medium" {...props}>{children}</h3>,
                  p: ({ children, ...props }) => <p className="mb-3 leading-7" {...props}>{children}</p>,
                  ul: ({ children, ...props }) => <ul className="mb-3 list-disc pl-5" {...props}>{children}</ul>,
                  ol: ({ children, ...props }) => <ol className="mb-3 list-decimal pl-5" {...props}>{children}</ol>,
                  li: ({ children, ...props }) => <li className="mb-1" {...props}>{children}</li>,
                  blockquote: ({ children, ...props }) => (
                    <blockquote className="mb-3 border-l-2 border-muted-foreground/30 pl-3 text-muted-foreground" {...props}>
                      {children}
                    </blockquote>
                  ),
                  a: ({ children, ...props }) => (
                    <a className="text-primary underline break-all" target="_blank" rel="noreferrer" {...props}>
                      {children}
                    </a>
                  ),
                  code: ({ children, className, ...props }) => {
                    const isBlock = Boolean(className)
                    if (!isBlock) {
                      return (
                        <code className="rounded bg-background px-1 py-0.5 text-[0.85em]" {...props}>
                          {children}
                        </code>
                      )
                    }
                    return (
                      <code
                        className="mb-3 block overflow-x-auto rounded-md bg-background p-3 text-xs leading-6"
                        {...props}
                      >
                        {children}
                      </code>
                    )
                  },
                }}
              >
                {viewingSource.content}
              </ReactMarkdown>
            </div>
          </div>
        </ScrollArea>

        {/* Delete Confirmation Dialog */}
        <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>确认删除来源</DialogTitle>
              <DialogDescription>
                确定要删除来源「{sourceToDelete?.title}」吗？此操作不可撤销，该来源将从数据库中永久删除。
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={handleCancelDelete} disabled={isDeleting}>
                取消
              </Button>
              <Button variant="destructive" onClick={handleConfirmDelete} disabled={isDeleting}>
                {isDeleting ? '删除中...' : '确认删除'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col bg-background overflow-hidden">
      <div className="flex-shrink-0 p-4 border-b">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">来源</h2>
        </div>

        <div className="space-y-3">
          <div className="rounded-lg border bg-card p-3 space-y-3">
            <div className="relative">
              <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
              <Textarea
                ref={keywordTextareaRef}
                placeholder={searchPlaceholder}
                rows={1}
                className="pl-9 min-h-[40px] max-h-[160px] resize-none field-sizing-fixed"
                value={keywords}
                onChange={(e) => setKeywords(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key !== 'Enter') return
                  if (e.shiftKey) return
                  e.preventDefault()
                  void handleSearch()
                }}
              />
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <div className="flex-1 min-w-[180px]">
                <Select
                  value={searchType}
                onValueChange={(v) => {
                  const nextType = v as 'web' | 'deep'
                  setSearchType(nextType)
                }}
              >
                  <SelectTrigger className="w-full">
                    {selectedSearchIcon === Brain ? (
                      <Brain className="h-4 w-4 mr-2 flex-shrink-0 text-violet-500" />
                    ) : (
                      <Globe className="h-4 w-4 mr-2 flex-shrink-0 text-blue-500" />
                    )}
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="web">Web Search</SelectItem>
                    <SelectItem value="deep">Deep Research</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <Button
                onClick={handleSearch}
                disabled={!keywords.trim() || isSearching}
                className="flex-shrink-0 max-w-full"
              >
                {isSearching ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                ) : (
                  <Search className="h-4 w-4 mr-2" />
                )}
                开始搜索
              </Button>
            </div>
          </div>

          <div className="flex gap-2">
            <Button
              variant="outline"
              className="flex-1 justify-start"
              onClick={() => setShowTextInput(!showTextInput)}
            >
              <Plus className="h-4 w-4 mr-2" />
              直接添加文本
            </Button>

            <Button
              variant="outline"
              className="flex-1 justify-start"
              onClick={handleOpenImportDialog}
            >
              <Upload className="h-4 w-4 mr-2" />
              从文本库导入
            </Button>
          </div>

          {showTextInput && (
            <div className="space-y-2 p-3 bg-muted/50 rounded-lg max-h-48 overflow-hidden flex flex-col">
              <Textarea
                placeholder="直接输入文本内容..."
                className="flex-1 min-h-[80px] max-h-[120px] resize-none"
                value={textInput}
                onChange={(e) => setTextInput(e.target.value)}
              />
              <div className="flex gap-2 justify-end flex-shrink-0">
                <Button variant="ghost" size="sm" onClick={() => setShowTextInput(false)}>
                  取消
                </Button>
                <Button size="sm" onClick={handleAddText} disabled={!textInput.trim()}>
                  添加
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>

      <ScrollArea className="flex-1 min-h-0">
        <div className="p-2">
          {sources.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <FileText className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p className="text-sm">已保存的来源将显示在此处</p>
              <p className="text-xs mt-1">搜索关键词或直接添加文本</p>
            </div>
          ) : (
            <div className="space-y-1">
              {sources.map((source) => {
                const SourceIcon = SOURCE_TYPE_META[source.type].icon
                const sourceIconColor = SOURCE_TYPE_META[source.type].color

                return (
                  <div
                    key={source.id}
                    className={cn(
                      'w-full flex items-center gap-2 p-3 rounded-lg text-left transition-colors',
                      'hover:bg-accent cursor-pointer',
                      !source.selected && 'opacity-50'
                    )}
                  >
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-5 w-5 min-h-5 text-muted-foreground hover:text-destructive hover:bg-destructive/10 flex-shrink-0"
                      onClick={(e) => handleDeleteClick(e, source)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                    <div
                      className="flex-shrink-0 mt-1.5"
                      onClick={(e) => handleToggleSelected(e, source)}
                    >
                      <Checkbox
                        checked={source.selected}
                        className="cursor-pointer"
                      />
                    </div>
                    <button
                      onClick={() => setViewingSourceId(source.id)}
                      className="flex-1 flex items-center gap-2 min-w-0 text-left"
                    >
                      <SourceIcon className={cn('h-4 w-4 flex-shrink-0', sourceIconColor)} />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{source.title}</p>
                        <p className="text-xs text-muted-foreground truncate">{source.content.slice(0, 50)}...</p>
                      </div>
                    </button>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </ScrollArea>

      {/* Delete Confirmation Dialog */}
      <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认删除来源</DialogTitle>
            <DialogDescription>
              确定要删除来源「{sourceToDelete?.title}」吗？此操作不可撤销，该来源将从数据库中永久删除。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={handleCancelDelete} disabled={isDeleting}>
              取消
            </Button>
            <Button variant="destructive" onClick={handleConfirmDelete} disabled={isDeleting}>
              {isDeleting ? '删除中...' : '确认删除'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showImportDialog} onOpenChange={(open) => {
        if (!open && isImporting) return
        setShowImportDialog(open)
      }}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>从文本库导入</DialogTitle>
            <DialogDescription>
              可多选文本库卡片，导入后将作为项目来源加入左侧列表。
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <div className="flex items-center justify-between text-sm">
              <span>已选 {selectedTextLibraryIds.length} / {textLibraryItems.length}</span>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setSelectedTextLibraryIds(textLibraryItems.map((item) => item.id))}
                >
                  全选
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setSelectedTextLibraryIds([])}
                >
                  清空
                </Button>
              </div>
            </div>

            <div className="max-h-64 overflow-y-auto rounded-md border">
              {textLibraryItems.length === 0 ? (
                <div className="p-3 text-sm text-muted-foreground">文本库暂无可导入卡片</div>
              ) : (
                <div className="divide-y">
                  {textLibraryItems.map((item) => {
                    const checked = selectedTextLibraryIds.includes(item.id)
                    return (
                      <label key={item.id} className="flex cursor-pointer items-start gap-3 p-3 hover:bg-accent/40">
                        <Checkbox
                          checked={checked}
                          onCheckedChange={(next) => {
                            handleToggleTextLibrarySelection(item.id, next !== false)
                          }}
                        />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="truncate text-sm font-medium">{item.name}</span>
                            {item.is_enabled ? null : <span className="text-xs text-muted-foreground">已禁用</span>}
                          </div>
                          <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                            {item.content}
                          </p>
                        </div>
                      </label>
                    )
                  })}
                </div>
              )}
            </div>

            {importResult ? (
              <div className="space-y-2 rounded-md border p-3">
                <p className="text-sm font-medium">
                  导入结果：成功 {importResult.summary.created_count}，跳过 {importResult.summary.skipped_count}，失败 {importResult.summary.failed_count}
                </p>
                <div className="max-h-40 space-y-1 overflow-y-auto text-xs text-muted-foreground">
                  {importResult.results.map((item) => (
                    <p key={`${item.text_library_id}-${item.status}`}>
                      [{item.status}] #{item.text_library_id} {item.message}
                    </p>
                  ))}
                </div>
              </div>
            ) : null}
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowImportDialog(false)}
              disabled={isImporting}
            >
              关闭
            </Button>
            <Button
              onClick={() => void handleConfirmImportFromTextLibrary()}
              disabled={isImporting || selectedTextLibraryIds.length === 0}
            >
              {isImporting ? '导入中...' : '开始导入'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
