import type { LLMProviderConfig, LLMProviderType } from '@/types/settings'

export interface LlmFetchModelsPayload {
  providerType: LLMProviderType | string
  baseUrl?: string
  apiKey?: string
}

export interface LlmModelTestPayload {
  providerType: LLMProviderType | string
  baseUrl?: string
  apiKey?: string
  model: string
}

export interface LlmProviderAdapter {
  providerId: string
  provider: LLMProviderConfig
  isBuiltin: boolean
  getCatalogIds: () => string[]
  getSelectedIds: () => string[]
  setEnabledIds: (nextEnabled: string[]) => void
  buildFetchModelsPayload: () => LlmFetchModelsPayload
  buildTestPayload: (modelId: string) => LlmModelTestPayload
}

export type LlmProviderAdapters = Record<string, LlmProviderAdapter>

type UpdateLlmProvider = (providerId: string, patch: Partial<LLMProviderConfig>) => void

interface CreateLlmProviderAdaptersParams {
  llmProviders: LLMProviderConfig[]
  normalizeModelIds: (models: string[]) => string[]
  updateLlmProvider: UpdateLlmProvider
}

export function createLlmProviderAdapters(
  params: CreateLlmProviderAdaptersParams
): LlmProviderAdapters {
  const { llmProviders, normalizeModelIds, updateLlmProvider } = params
  const adapters: LlmProviderAdapters = {}
  for (const provider of llmProviders) {
    adapters[provider.id] = {
      providerId: provider.id,
      provider,
      isBuiltin: provider.is_builtin,
      getCatalogIds: () => normalizeModelIds([
        ...(provider.catalog_models ?? []),
        ...(provider.enabled_models ?? []),
      ]),
      getSelectedIds: () => normalizeModelIds(provider.enabled_models ?? []),
      setEnabledIds: (nextEnabled) => {
        updateLlmProvider(provider.id, { enabled_models: normalizeModelIds(nextEnabled) })
      },
      buildFetchModelsPayload: () => ({
        providerType: provider.provider_type,
        baseUrl: provider.base_url,
        apiKey: provider.api_key,
      }),
      buildTestPayload: (modelId) => ({
        providerType: provider.provider_type,
        baseUrl: provider.base_url,
        apiKey: provider.api_key,
        model: modelId,
      }),
    }
  }
  return adapters
}
