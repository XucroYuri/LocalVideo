'use client'

import { RefreshCw, Search } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface CatalogSearchActionsProps {
  value: string
  placeholder: string
  isRefreshing?: boolean
  widthClassName?: string
  onValueChange: (value: string) => void
  onSearch: () => void
  onRefresh: () => void
}

export function CatalogSearchActions({
  value,
  placeholder,
  isRefreshing = false,
  widthClassName = 'w-56',
  onValueChange,
  onSearch,
  onRefresh,
}: CatalogSearchActionsProps) {
  return (
    <div className="flex items-center gap-2">
      <div className={`relative ${widthClassName}`}>
        <Input
          className="pr-14"
          placeholder={placeholder}
          value={value}
          onChange={(event) => onValueChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') onSearch()
          }}
        />
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="absolute right-1 top-1/2 h-7 -translate-y-1/2 px-2"
          onClick={onSearch}
          aria-label="搜索"
        >
          <Search className="h-3.5 w-3.5" />
        </Button>
      </div>
      <Button type="button" variant="outline" size="icon" className="h-9 w-9" onClick={onRefresh} aria-label="刷新">
        <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />
      </Button>
    </div>
  )
}
