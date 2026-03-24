'use client'

import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

export const DEFAULT_PAGE_SIZE_OPTIONS = [20, 30, 40, 50] as const

export function resolveDataPageSize(cardPageSize: number, includeCreateCard = true): number {
  const safe = Number.isFinite(cardPageSize) ? Math.max(1, Math.floor(cardPageSize)) : 20
  return includeCreateCard ? Math.max(1, safe - 1) : safe
}

export function resolveTotalPages(total: number, cardPageSize: number, includeCreateCard = true): number {
  const safeTotal = Number.isFinite(total) ? Math.max(0, Math.floor(total)) : 0
  const dataPageSize = resolveDataPageSize(cardPageSize, includeCreateCard)
  return Math.max(1, Math.ceil(safeTotal / dataPageSize))
}

interface CatalogPaginationProps {
  page: number
  totalPages: number
  pageSize: number
  isFetching?: boolean
  pageSizeOptions?: readonly number[]
  onPageChange: (page: number) => void
  onPageSizeChange: (size: number) => void
}

export function CatalogPagination({
  page,
  totalPages,
  pageSize,
  isFetching = false,
  pageSizeOptions = DEFAULT_PAGE_SIZE_OPTIONS,
  onPageChange,
  onPageSizeChange,
}: CatalogPaginationProps) {
  const safePage = Math.max(1, page)
  const safeTotalPages = Math.max(1, totalPages)

  return (
    <div className="flex items-center gap-2">
      <span className="text-muted-foreground">每页</span>
      <Select
        value={String(pageSize)}
        onValueChange={(value) => {
          const next = Number(value)
          if (!Number.isFinite(next)) return
          onPageSizeChange(next)
        }}
      >
        <SelectTrigger className="w-[92px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {pageSizeOptions.map((one) => (
            <SelectItem key={one} value={String(one)}>{one}</SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button
        variant="outline"
        size="sm"
        onClick={() => onPageChange(Math.max(1, safePage - 1))}
        disabled={isFetching || safePage <= 1}
      >
        上一页
      </Button>
      <span className="min-w-[140px] text-center text-muted-foreground">
        第 {safePage} / {safeTotalPages} 页
      </span>
      <Button
        variant="outline"
        size="sm"
        onClick={() => onPageChange(Math.min(safeTotalPages, safePage + 1))}
        disabled={isFetching || safePage >= safeTotalPages}
      >
        下一页
      </Button>
    </div>
  )
}
