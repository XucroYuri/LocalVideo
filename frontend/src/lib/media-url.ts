import { getPublicApiBaseUrl, toApiOrigin } from '@/lib/api-base-url'

export function getApiOrigin(): string {
  return toApiOrigin(getPublicApiBaseUrl())
}

export function resolveApiResourceUrl(url: string | null | undefined): string {
  const trimmed = String(url || '').trim()
  if (!trimmed) return ''
  if (/^[a-z][a-z\d+\-.]*:/i.test(trimmed)) return trimmed
  const apiOrigin = getApiOrigin()
  if (trimmed.startsWith('/')) return `${apiOrigin}${trimmed}`
  return `${apiOrigin}/${trimmed}`
}

export function resolveStorageFileUrl(filePath: string | null | undefined): string | undefined {
  const normalized = String(filePath || '').trim().replace(/\\/g, '/')
  if (!normalized) return undefined
  if (/^[a-z][a-z\d+\-.]*:/i.test(normalized)) return normalized

  let relativePath = normalized
  if (normalized.includes('/storage/')) {
    relativePath = normalized.split('/storage/').pop() || normalized
  } else if (normalized.startsWith('./storage/')) {
    relativePath = normalized.slice('./storage/'.length)
  } else if (normalized.startsWith('storage/')) {
    relativePath = normalized.slice('storage/'.length)
  } else if (normalized.startsWith('/storage/')) {
    relativePath = normalized.slice('/storage/'.length)
  }

  return encodeURI(`${getApiOrigin()}/storage/${relativePath}`)
}
