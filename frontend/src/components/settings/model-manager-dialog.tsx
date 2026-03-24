import { Loader2, RefreshCw } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { ModelConnectivityEntry } from '@/hooks/use-model-manager'

export interface ModelManagerDialogRow {
  id: string
  label: string
  tags?: string[]
  checked: boolean
  connectivity?: ModelConnectivityEntry
  canTest?: boolean
  onTest: () => void
  onCheckedChange: (checked: boolean) => void
}

interface ModelManagerDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  selectedCount: number
  totalCount: number
  rows: ModelManagerDialogRow[]
  allSelected: boolean
  onToggleAll: () => void
  showRefreshButton?: boolean
  onRefresh?: () => void
  isRefreshing?: boolean
  refreshDisabled?: boolean
  title?: string
  description?: string
  showToggleAllButton?: boolean
  emptyText: string
}

export function ModelManagerDialog({
  open,
  onOpenChange,
  selectedCount,
  totalCount,
  rows,
  allSelected,
  onToggleAll,
  showRefreshButton = false,
  onRefresh,
  isRefreshing = false,
  refreshDisabled = false,
  title = '管理模型列表',
  description = '只有勾选模型才会出现在下拉列表中。',
  showToggleAllButton = true,
  emptyText,
}: ModelManagerDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[90vw] sm:max-w-[66rem]">
        <DialogHeader className="space-y-2">
          <div className="flex items-start justify-between gap-4 pr-10">
            <div className="space-y-1.5">
              <DialogTitle>{title}</DialogTitle>
              {description ? <DialogDescription>{description}</DialogDescription> : null}
            </div>
            <div className="flex items-center gap-3 shrink-0">
              {showToggleAllButton ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={onToggleAll}
                  disabled={totalCount === 0}
                >
                  {allSelected ? '全部取消' : '一键全选'}
                </Button>
              ) : null}
              {showRefreshButton ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={onRefresh}
                  disabled={isRefreshing || refreshDisabled}
                >
                  {isRefreshing ? (
                    <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  ) : (
                    <RefreshCw className="h-4 w-4 mr-2" />
                  )}
                  刷新模型列表
                </Button>
              ) : null}
            </div>
          </div>
        </DialogHeader>
        <div className="text-xs text-muted-foreground">
          已勾选 {selectedCount} / {totalCount}
        </div>
        <ScrollArea className="h-[30rem] rounded-md border">
          {rows.length > 0 ? (
            <div className="divide-y">
              {rows.map((row) => {
                const connectivity = row.connectivity
                const isTestingConnectivity = connectivity?.status === 'testing'
                const testLabel = isTestingConnectivity
                  ? '检测中'
                  : (connectivity?.status === 'success'
                    ? '可用'
                    : (connectivity?.status === 'failed' ? '失败' : '检测'))
                const testButtonStatusClass = connectivity?.status === 'success'
                  ? 'border-green-500 text-green-600 hover:bg-green-50 hover:text-green-700 dark:border-green-500/70 dark:text-green-400 dark:hover:bg-green-950/40'
                  : (connectivity?.status === 'failed'
                    ? 'border-red-500 text-red-600 hover:bg-red-50 hover:text-red-700 dark:border-red-500/70 dark:text-red-400 dark:hover:bg-red-950/40'
                    : '')
                const tags = row.tags ?? []
                return (
                  <div key={row.id} className="grid grid-cols-[minmax(0,1fr)_auto_auto_auto] items-center gap-3 px-3 py-2 text-sm">
                    <span className="truncate">{row.label}</span>
                    <div className="flex items-center gap-1">
                      {tags.map((tag) => (
                        <Badge key={`${row.id}-${tag}`} variant="outline" className="h-7 px-2 text-sm font-medium">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className={`h-7 px-2 ${testButtonStatusClass}`}
                      onClick={row.onTest}
                      disabled={isTestingConnectivity || !row.canTest}
                      title={connectivity?.message || ''}
                    >
                      {isTestingConnectivity ? (
                        <>
                          <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
                          检测中
                        </>
                      ) : testLabel}
                    </Button>
                    <Checkbox
                      checked={row.checked}
                      onCheckedChange={(checked) => row.onCheckedChange(checked === true)}
                      aria-label={`启用模型 ${row.label}`}
                    />
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="px-3 py-6 text-sm text-muted-foreground">
              {emptyText}
            </div>
          )}
        </ScrollArea>
      </DialogContent>
    </Dialog>
  )
}
