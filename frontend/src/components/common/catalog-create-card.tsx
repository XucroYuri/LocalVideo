'use client'

import type { ReactNode } from 'react'
import { Loader2, Plus } from 'lucide-react'

import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'

interface CatalogCreateCardProps {
  title: string
  onClick: () => void
  icon?: ReactNode
  loading?: boolean
  disabled?: boolean
  className?: string
  contentClassName?: string
}

export function CatalogCreateCard({
  title,
  onClick,
  icon,
  loading = false,
  disabled = false,
  className,
  contentClassName,
}: CatalogCreateCardProps) {
  const isDisabled = disabled || loading

  return (
    <Card
      className={cn(
        'cursor-pointer border-dashed transition-all hover:border-primary hover:bg-accent/50',
        isDisabled && 'cursor-not-allowed opacity-60',
        className
      )}
      onClick={() => {
        if (!isDisabled) onClick()
      }}
    >
      <CardContent
        className={cn(
          'flex h-full flex-col items-center justify-center p-6',
          contentClassName
        )}
      >
        {loading ? (
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        ) : (
          <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
            {icon ?? <Plus className="h-6 w-6 text-primary" />}
          </div>
        )}
        <h3 className="font-medium">{title}</h3>
      </CardContent>
    </Card>
  )
}
