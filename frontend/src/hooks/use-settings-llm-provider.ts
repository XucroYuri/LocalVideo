import { useCallback, useMemo, useState } from 'react'
import { toast } from 'sonner'

import { api } from '@/lib/api-client'
import { createLlmProviderAdapters } from '@/app/settings/llm-provider-adapters'
import { useConfirmDialog } from '@/components/common/confirm-dialog-provider'
import { useModelManager } from '@/hooks/use-model-manager'
import { normalizeModelIds, normalizeProviderId } from '@/lib/provider-config'
import type { LLMProviderConfig, LLMProviderType, SettingsUpdate } from '@/types/settings'

interface ModelInfo {
  id: string
  object?: string
  created?: number
  owned_by?: string
}

interface UseSettingsLlmProviderParams {
  llmProviders: LLMProviderConfig[]
  llmModelManager: ReturnType<typeof useModelManager>
  updateField: <K extends keyof SettingsUpdate>(key: K, value: SettingsUpdate[K]) => void
  currentDefaultProviderId: string
}

export function useSettingsLlmProvider(params: UseSettingsLlmProviderParams) {
  const {
    llmProviders,
    llmModelManager,
    updateField,
    currentDefaultProviderId,
  } = params
  const confirmDialog = useConfirmDialog()
  const [isLoadingModels, setIsLoadingModels] = useState(false)
  const [isCreatingCustomProvider, setIsCreatingCustomProvider] = useState(false)
  const [customProviderName, setCustomProviderName] = useState('')
  const [customProviderType, setCustomProviderType] = useState<LLMProviderType>('openai_chat')
  const [llmProviderFetchedCatalogMap, setLlmProviderFetchedCatalogMap] = useState<Record<string, string[]>>({})

  const updateLlmProviders = useCallback((nextProviders: LLMProviderConfig[]) => {
    updateField('llm_providers', nextProviders)
  }, [updateField])

  const updateLlmProvider = useCallback((providerId: string, patch: Partial<LLMProviderConfig>) => {
    const nextProviders = llmProviders.map((provider) => {
      if (provider.id !== providerId) return provider
      const nextEnabled = normalizeModelIds(
        patch.enabled_models ?? provider.enabled_models ?? []
      )
      const baseCatalog = normalizeModelIds(
        patch.catalog_models ?? provider.catalog_models ?? nextEnabled
      )
      const nextCatalog = normalizeModelIds([
        ...baseCatalog,
        ...nextEnabled,
      ])
      const finalEnabled = nextEnabled
      let nextDefaultModel = String(
        patch.default_model
        ?? provider.default_model
        ?? finalEnabled[0]
        ?? ''
      ).trim()
      if (finalEnabled.length === 0) {
        nextDefaultModel = ''
      }
      if (nextDefaultModel && finalEnabled.length > 0 && !finalEnabled.includes(nextDefaultModel)) {
        nextDefaultModel = finalEnabled[0]
      }
      if (!nextDefaultModel && finalEnabled.length > 0) {
        nextDefaultModel = finalEnabled[0]
      }
      return {
        ...provider,
        ...patch,
        catalog_models: nextCatalog,
        enabled_models: finalEnabled,
        default_model: nextDefaultModel,
      }
    })
    updateLlmProviders(nextProviders)
  }, [llmProviders, updateLlmProviders])

  const llmProviderAdapters = useMemo(() => createLlmProviderAdapters({
    llmProviders,
    normalizeModelIds,
    updateLlmProvider,
  }), [llmProviders, updateLlmProvider])

  const llmModelManagerCatalogIds = llmModelManager.catalogIds
  const llmModelManagerAdapter = useMemo(() => {
    const providerId = llmModelManager.providerId
    if (!providerId) return null
    return llmProviderAdapters[providerId] ?? null
  }, [llmModelManager.providerId, llmProviderAdapters])

  const llmModelManagerEnabledIds = useMemo(
    () => llmModelManagerAdapter?.getSelectedIds() ?? [],
    [llmModelManagerAdapter]
  )

  const canRefreshLlmModelManagerCatalog = Boolean(llmModelManagerAdapter && !llmModelManagerAdapter.isBuiltin)
  const llmModelManagerAllSelected = llmModelManagerCatalogIds.length > 0
    && llmModelManagerCatalogIds.every((id) => llmModelManagerEnabledIds.includes(id))

  const refreshProviderModels = useCallback(async (
    providerId: string,
    options?: { silent?: boolean }
  ): Promise<ModelInfo[]> => {
    const adapter = llmProviderAdapters[providerId]
    if (!adapter) {
      llmModelManager.setCatalog([])
      return []
    }
    setIsLoadingModels(true)
    try {
      if (adapter.isBuiltin) {
        const modelIds = adapter.getCatalogIds()
        const models = modelIds.map((id) => ({ id }))
        llmModelManager.setCatalog(models)
        setLlmProviderFetchedCatalogMap((prev) => ({ ...prev, [providerId]: modelIds }))
        if (!options?.silent) {
          toast.success(`已载入 ${models.length} 个模型`)
        }
        return models
      }

      const fetchPayload = adapter.buildFetchModelsPayload()
      if (!String(fetchPayload.apiKey || '').trim()) {
        if (!options?.silent) {
          toast.error('请先填写 API Key')
        }
        llmModelManager.setCatalog(
          adapter.getCatalogIds().map((id) => ({ id }))
        )
        return []
      }

      const response = await api.settings.fetchModels(fetchPayload)
      const fetchedModelIds = normalizeModelIds(response.models.map((item) => item.id))
        .sort((a, b) => a.localeCompare(b))
      const preservedEnabledIds = adapter.getSelectedIds().filter(
        (id) => !fetchedModelIds.includes(id)
      )
      const mergedCatalogModelIds = normalizeModelIds([
        ...fetchedModelIds,
        ...preservedEnabledIds,
      ])
      const models = mergedCatalogModelIds
        .map((id) => ({ id }))
      llmModelManager.setCatalog(models)
      setLlmProviderFetchedCatalogMap((prev) => ({ ...prev, [providerId]: fetchedModelIds }))
      updateLlmProvider(providerId, {
        catalog_models: mergedCatalogModelIds,
      })
      if (!options?.silent) {
        toast.success(`获取到 ${fetchedModelIds.length} 个模型`)
      }
      return models
    } catch (error) {
      if (!options?.silent) {
        toast.error(error instanceof Error ? error.message : '获取模型列表失败')
      }
      return []
    } finally {
      setIsLoadingModels(false)
    }
  }, [llmModelManager, llmProviderAdapters, updateLlmProvider])

  const handleOpenModelManager = useCallback((providerId: string) => {
    const adapter = llmProviderAdapters[providerId]
    if (!adapter) return
    llmModelManager.openManager(
      providerId,
      adapter.getCatalogIds().map((id) => ({ id }))
    )
    if (!adapter.isBuiltin) {
      void refreshProviderModels(providerId, { silent: true })
    }
  }, [llmModelManager, llmProviderAdapters, refreshProviderModels])

  const handleLlmModelEnabledChange = useCallback((modelId: string, checked: boolean) => {
    const providerId = llmModelManager.providerId
    if (!providerId) return
    const adapter = llmProviderAdapters[providerId]
    if (!adapter) return
    const enabled = new Set(adapter.getSelectedIds())
    if (checked) enabled.add(modelId)
    else enabled.delete(modelId)
    adapter.setEnabledIds(Array.from(enabled))
  }, [llmModelManager.providerId, llmProviderAdapters])

  const handleToggleAllLlmModels = useCallback(() => {
    if (!llmModelManagerAdapter) return
    const nextEnabled = llmModelManagerAllSelected ? [] : llmModelManagerCatalogIds
    llmModelManagerAdapter.setEnabledIds(nextEnabled)
  }, [
    llmModelManagerAllSelected,
    llmModelManagerAdapter,
    llmModelManagerCatalogIds,
  ])

  const handleRefreshCurrentProviderModels = useCallback(() => {
    if (!llmModelManagerAdapter) return
    void refreshProviderModels(llmModelManagerAdapter.providerId)
  }, [llmModelManagerAdapter, refreshProviderModels])

  const handleTestLlmModel = useCallback(async (modelId: string) => {
    if (!llmModelManagerAdapter) return
    llmModelManager.setModelTesting(modelId)
    try {
      const result = await api.settings.testModel(llmModelManagerAdapter.buildTestPayload(modelId))
      if (result.success) {
        const latencyLabel = typeof result.latency_ms === 'number' ? `（${result.latency_ms}ms）` : ''
        llmModelManager.setModelResult(modelId, {
          success: true,
          message: result.message || 'OK',
        })
        toast.success(`模型 ${modelId} 检测通过${latencyLabel}`)
        return
      }
      const errorMessage = result.error || result.message || '未知错误'
      llmModelManager.setModelResult(modelId, {
        success: false,
        message: errorMessage,
      })
      toast.error(`模型 ${modelId} 检测失败: ${errorMessage}`)
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : '检测失败'
      llmModelManager.setModelResult(modelId, {
        success: false,
        message: errorMessage,
      })
      toast.error(`模型 ${modelId} 检测失败: ${errorMessage}`)
    }
  }, [llmModelManager, llmModelManagerAdapter])

  const handleAddCustomProvider = useCallback(() => {
    const trimmedName = customProviderName.trim()
    if (!trimmedName) {
      toast.error('请输入供应商名称')
      return
    }
    const baseId = normalizeProviderId(trimmedName)
    const usedIds = new Set(llmProviders.map((item) => item.id))
    let nextId = baseId
    let suffix = 2
    while (usedIds.has(nextId)) {
      nextId = `${baseId}_${suffix}`
      suffix += 1
    }
    const nextProvider: LLMProviderConfig = {
      id: nextId,
      name: trimmedName,
      is_builtin: false,
      provider_type: customProviderType,
      base_url: '',
      api_key: '',
      catalog_models: [],
      enabled_models: [],
      default_model: '',
      supports_vision: true,
    }
    const nextProviders = [...llmProviders, nextProvider]
    updateLlmProviders(nextProviders)
    setCustomProviderName('')
    setCustomProviderType('openai_chat')
    setIsCreatingCustomProvider(false)
  }, [
    customProviderName,
    customProviderType,
    llmProviders,
    updateLlmProviders,
  ])

  const handleDeleteCustomProvider = useCallback(async (providerId: string) => {
    const target = llmProviders.find((provider) => provider.id === providerId)
    if (!target) return
    if (target.is_builtin) {
      toast.error('内置供应商不支持删除')
      return
    }
    const confirmed = await confirmDialog({
      title: '删除自定义供应商',
      description: `确定删除自定义供应商「${target.name}」吗？`,
      confirmText: '删除',
      cancelText: '取消',
      variant: 'destructive',
    })
    if (!confirmed) return

    const nextProviders = llmProviders.filter((provider) => provider.id !== providerId)
    updateLlmProviders(nextProviders)
    setLlmProviderFetchedCatalogMap((prev) => {
      if (!(providerId in prev)) return prev
      const next = { ...prev }
      delete next[providerId]
      return next
    })

    if (llmModelManager.providerId === providerId) {
      llmModelManager.onOpenChange(false)
    }

    const stillValid = nextProviders.some((provider) => provider.id === currentDefaultProviderId)
    if (!stillValid) {
      updateField('default_llm_provider', nextProviders[0]?.id || 'builtin_openai')
    }

    toast.success(`已删除供应商：${target.name}`)
  }, [
    currentDefaultProviderId,
    confirmDialog,
    llmModelManager,
    llmProviders,
    updateField,
    updateLlmProviders,
  ])

  return {
    isLoadingModels,
    isCreatingCustomProvider,
    setIsCreatingCustomProvider,
    customProviderName,
    setCustomProviderName,
    customProviderType,
    setCustomProviderType,
    llmProviderFetchedCatalogMap,
    updateLlmProvider,
    llmModelManagerCatalogIds,
    llmModelManagerEnabledIds,
    llmModelManagerAdapter,
    llmModelManagerAllSelected,
    canRefreshLlmModelManagerCatalog,
    handleOpenModelManager,
    handleLlmModelEnabledChange,
    handleToggleAllLlmModels,
    handleRefreshCurrentProviderModels,
    handleTestLlmModel,
    handleAddCustomProvider,
    handleDeleteCustomProvider,
  }
}
