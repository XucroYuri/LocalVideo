'use client'

import { Check, Clock3, XCircle } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import type { RuntimeValidationStatus } from '@/types/settings'

const RUNTIME_VALIDATION_STATUS_LABELS: Record<RuntimeValidationStatus, string> = {
  not_ready: '未就绪',
  pending: '待校验',
  failed: '校验失败',
  ready: '已就绪',
}

function normalizeRuntimeValidationStatus(status: string | undefined): RuntimeValidationStatus {
  if (status === 'ready' || status === 'failed' || status === 'pending' || status === 'not_ready') {
    return status
  }
  return 'not_ready'
}

export function RuntimeValidationBadge({ status }: { status: string | undefined }) {
  const normalized = normalizeRuntimeValidationStatus(status)
  if (normalized === 'ready') {
    return (
      <Badge variant="outline" className="text-green-600">
        <Check className="h-3 w-3 mr-1" />
        {RUNTIME_VALIDATION_STATUS_LABELS[normalized]}
      </Badge>
    )
  }
  if (normalized === 'pending') {
    return (
      <Badge variant="outline" className="text-amber-600">
        <Clock3 className="h-3 w-3 mr-1" />
        {RUNTIME_VALIDATION_STATUS_LABELS[normalized]}
      </Badge>
    )
  }
  if (normalized === 'failed') {
    return (
      <Badge variant="outline" className="text-red-600">
        <XCircle className="h-3 w-3 mr-1" />
        {RUNTIME_VALIDATION_STATUS_LABELS[normalized]}
      </Badge>
    )
  }
  return <Badge variant="outline">{RUNTIME_VALIDATION_STATUS_LABELS[normalized]}</Badge>
}
