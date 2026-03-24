import type { ImageProviderConfig, LLMProviderConfig } from '@/types/settings'

export function formatCredits(value: number | null | undefined): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '-'
  return Number.isInteger(value) ? String(value) : value.toFixed(2)
}

export function normalizeModelIds(models: Array<string | null | undefined>): string[] {
  const seen = new Set<string>()
  const normalized: string[] = []
  for (const item of models) {
    const id = String(item || '').trim()
    if (!id || seen.has(id)) continue
    seen.add(id)
    normalized.push(id)
  }
  return normalized
}

export function resolveEnabledModelIds(
  rawEnabled: string[] | null | undefined,
  catalog: string[]
): string[] {
  const normalizedCatalog = normalizeModelIds(catalog)
  if (rawEnabled == null) return normalizedCatalog
  const configured = normalizeModelIds(rawEnabled)
  const catalogSet = new Set(normalizedCatalog)
  return configured.filter((id) => catalogSet.has(id))
}

export function normalizeProviderId(rawName: string): string {
  const base = rawName
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, '_')
    .replace(/^_+|_+$/g, '')
  const stem = base || 'custom_provider'
  return `custom_${stem}`
}

export function getLlmProviderDisplayName(provider: Pick<LLMProviderConfig, 'name'>): string {
  const normalized = String(provider.name || '').trim().toLowerCase()
  if (normalized === 'minimax') return 'MiniMax'
  return provider.name
}

export function getImageProviderDisplayName(
  provider: Pick<ImageProviderConfig, 'name' | 'provider_type'>
): string {
  if (provider.provider_type === 'gemini_api') return 'Gemini'
  if (provider.provider_type === 'volcengine_seedream') return '火山引擎'
  return provider.name
}
