'use client'

import { useCallback } from 'react'
import type { QueryKey } from '@tanstack/react-query'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { useRowPendingState } from '@/hooks/use-row-pending-state'

interface RunCatalogRowActionOptions<TId extends string | number, TResult> {
  id: TId
  task: () => Promise<TResult>
  successMessage?: string | ((result: TResult) => string | undefined)
  errorMessage?: string | ((error: unknown) => string)
  invalidateQueryKeys?: QueryKey[]
  onSuccess?: (result: TResult) => void | Promise<void>
}

export function useCatalogRowAction<TId extends string | number = number>() {
  const queryClient = useQueryClient()
  const pendingState = useRowPendingState<TId>()

  const run = useCallback(async <TResult>(
    options: RunCatalogRowActionOptions<TId, TResult>
  ): Promise<TResult> => {
    const {
      id,
      task,
      successMessage,
      errorMessage,
      invalidateQueryKeys = [],
      onSuccess,
    } = options

    try {
      const result = await pendingState.withPending(id, task)
      if (invalidateQueryKeys.length > 0) {
        await Promise.all(
          invalidateQueryKeys.map((queryKey) => queryClient.invalidateQueries({ queryKey }))
        )
      }
      if (onSuccess) {
        await onSuccess(result)
      }
      const successText = typeof successMessage === 'function'
        ? successMessage(result)
        : successMessage
      if (successText) {
        toast.success(successText)
      }
      return result
    } catch (error) {
      const fallbackMessage = error instanceof Error ? error.message : '操作失败'
      const errorText = typeof errorMessage === 'function'
        ? errorMessage(error)
        : (errorMessage || fallbackMessage)
      toast.error(errorText)
      throw error
    }
  }, [pendingState, queryClient])

  return {
    pendingIds: pendingState.pendingIds,
    run,
  }
}
