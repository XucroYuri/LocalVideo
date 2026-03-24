import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { normalizeModelIds } from '@/lib/provider-config'

export interface ModelManagerCatalogItem {
  id: string
}

export type ModelConnectivityStatus = 'idle' | 'testing' | 'success' | 'failed'

export interface ModelConnectivityEntry {
  status: ModelConnectivityStatus
  message?: string
}

interface UseModelManagerOptions {
  resetDelayMs?: number
}

function buildModelKey(providerId: string | null, modelId: string): string | null {
  if (!providerId) return null
  const normalizedModelId = String(modelId || '').trim()
  if (!normalizedModelId) return null
  return `${providerId}::${normalizedModelId}`
}

export function useModelManager(options?: UseModelManagerOptions) {
  const resetDelayMs = options?.resetDelayMs ?? 3000
  const [isOpen, setIsOpen] = useState(false)
  const [providerId, setProviderId] = useState<string | null>(null)
  const [catalog, setCatalog] = useState<ModelManagerCatalogItem[]>([])
  const [connectivityStatus, setConnectivityStatus] = useState<Record<string, ModelConnectivityEntry>>({})
  const resetTimersRef = useRef<Record<string, number>>({})

  const clearResetTimerByKey = useCallback((modelKey: string) => {
    const timer = resetTimersRef.current[modelKey]
    if (!timer) return
    window.clearTimeout(timer)
    delete resetTimersRef.current[modelKey]
  }, [])

  const scheduleStatusResetByKey = useCallback((modelKey: string, delay: number) => {
    clearResetTimerByKey(modelKey)
    resetTimersRef.current[modelKey] = window.setTimeout(() => {
      setConnectivityStatus((prev) => {
        if (!prev[modelKey] || prev[modelKey]?.status === 'testing') return prev
        const next = { ...prev }
        delete next[modelKey]
        return next
      })
      delete resetTimersRef.current[modelKey]
    }, delay)
  }, [clearResetTimerByKey])

  const openManager = useCallback((nextProviderId: string, nextCatalog: ModelManagerCatalogItem[]) => {
    setProviderId(nextProviderId)
    setCatalog(nextCatalog)
    setIsOpen(true)
  }, [])

  const onOpenChange = useCallback((open: boolean) => {
    setIsOpen(open)
    if (!open) {
      setProviderId(null)
      setCatalog([])
    }
  }, [])

  const catalogIds = useMemo(
    () => normalizeModelIds(catalog.map((item) => item.id)),
    [catalog]
  )

  const setModelTesting = useCallback((modelId: string) => {
    const modelKey = buildModelKey(providerId, modelId)
    if (!modelKey) return
    clearResetTimerByKey(modelKey)
    setConnectivityStatus((prev) => ({
      ...prev,
      [modelKey]: { status: 'testing' },
    }))
  }, [clearResetTimerByKey, providerId])

  const setModelResult = useCallback((
    modelId: string,
    result: { success: boolean; message?: string; delayMs?: number }
  ) => {
    const modelKey = buildModelKey(providerId, modelId)
    if (!modelKey) return
    const status: ModelConnectivityStatus = result.success ? 'success' : 'failed'
    setConnectivityStatus((prev) => ({
      ...prev,
      [modelKey]: { status, message: result.message },
    }))
    scheduleStatusResetByKey(modelKey, result.delayMs ?? resetDelayMs)
  }, [providerId, resetDelayMs, scheduleStatusResetByKey])

  const getModelConnectivity = useCallback((modelId: string): ModelConnectivityEntry | undefined => {
    const modelKey = buildModelKey(providerId, modelId)
    if (!modelKey) return undefined
    return connectivityStatus[modelKey]
  }, [connectivityStatus, providerId])

  useEffect(() => () => {
    Object.values(resetTimersRef.current).forEach((timer) => window.clearTimeout(timer))
    resetTimersRef.current = {}
  }, [])

  return {
    isOpen,
    providerId,
    catalog,
    catalogIds,
    connectivityStatus,
    setCatalog,
    openManager,
    onOpenChange,
    setModelTesting,
    setModelResult,
    getModelConnectivity,
  }
}
