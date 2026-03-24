'use client'

import { useCallback, useState } from 'react'

export function useRowPendingState<TId extends string | number = number>() {
  const [pendingIds, setPendingIds] = useState<Set<TId>>(() => new Set())

  const markPending = useCallback((id: TId) => {
    setPendingIds((prev) => {
      const next = new Set(prev)
      next.add(id)
      return next
    })
  }, [])

  const clearPending = useCallback((id: TId) => {
    setPendingIds((prev) => {
      if (!prev.has(id)) return prev
      const next = new Set(prev)
      next.delete(id)
      return next
    })
  }, [])

  const withPending = useCallback(async <T>(id: TId, task: () => Promise<T>): Promise<T> => {
    markPending(id)
    try {
      return await task()
    } finally {
      clearPending(id)
    }
  }, [clearPending, markPending])

  return {
    pendingIds,
    markPending,
    clearPending,
    withPending,
  }
}
