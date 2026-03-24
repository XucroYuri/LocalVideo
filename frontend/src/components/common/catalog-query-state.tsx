'use client'

import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'

interface CatalogQueryStateProps {
  isLoading: boolean
  error: unknown
  hasData?: boolean
  onRetry: () => void
  loadingFallback: ReactNode
  children: ReactNode
}

export function CatalogQueryState({
  isLoading,
  error,
  hasData = false,
  onRetry,
  loadingFallback,
  children,
}: CatalogQueryStateProps) {
  if (isLoading && !hasData) {
    return <>{loadingFallback}</>
  }

  if (error && !hasData) {
    const message = error instanceof Error ? error.message : '加载失败'
    return (
      <Card className="mx-auto max-w-md border-destructive">
        <CardContent className="flex flex-col items-center justify-center py-16">
          <p className="mb-4 text-destructive">{message}</p>
          <Button onClick={onRetry}>重试</Button>
        </CardContent>
      </Card>
    )
  }

  return <>{children}</>
}
