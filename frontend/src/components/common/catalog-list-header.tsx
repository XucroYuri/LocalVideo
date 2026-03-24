'use client'

import { CatalogPagination } from '@/components/common/catalog-pagination'

interface CatalogListHeaderProps {
  label: string
  total: number
  page: number
  totalPages: number
  pageSize: number
  isFetching?: boolean
  onPageChange: (page: number) => void
  onPageSizeChange: (size: number) => void
}

export function CatalogListHeader({
  label,
  total,
  page,
  totalPages,
  pageSize,
  isFetching = false,
  onPageChange,
  onPageSizeChange,
}: CatalogListHeaderProps) {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3 text-sm">
      <div className="text-muted-foreground">
        {label}（{total}）
      </div>
      <CatalogPagination
        page={page}
        totalPages={totalPages}
        pageSize={pageSize}
        isFetching={isFetching}
        onPageChange={onPageChange}
        onPageSizeChange={onPageSizeChange}
      />
    </div>
  )
}
