import { getPublicApiBaseUrl, toApiOrigin } from '@/lib/api-base-url'

function resolveAllowedMediaOrigins(): string[] {
  const origins = new Set<string>()

  try {
    const publicApiUrl = new URL(getPublicApiBaseUrl())
    origins.add(publicApiUrl.origin)

    const { protocol, hostname, port } = publicApiUrl
    if ((hostname === 'localhost' || hostname === '127.0.0.1') && port) {
      origins.add(`${protocol}//localhost:${port}`)
      origins.add(`${protocol}//127.0.0.1:${port}`)
    }
  } catch {
    // Ignore invalid env values.
  }

  return Array.from(origins)
}

const ALLOWED_MEDIA_ORIGINS = resolveAllowedMediaOrigins()

export function isProxyableMediaUrl(rawUrl: string): boolean {
  const value = String(rawUrl || '').trim()
  if (!value) return false
  if (value.startsWith('blob:') || value.startsWith('data:')) return false

  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:'
  } catch {
    return false
  }
}

export function buildMediaProxyUrl(rawUrl: string): string {
  const value = String(rawUrl || '').trim()
  if (!value || typeof window === 'undefined' || !isProxyableMediaUrl(value)) {
    return value
  }

  try {
    const targetUrl = new URL(value)
    if (targetUrl.origin === window.location.origin || ALLOWED_MEDIA_ORIGINS.includes(targetUrl.origin)) {
      return value
    }

    const proxyUrl = new URL('/api/media-proxy', window.location.origin)
    proxyUrl.searchParams.set('url', value)
    return proxyUrl.toString()
  } catch {
    return value
  }
}

export function isAllowedMediaOrigin(rawUrl: string): boolean {
  const value = String(rawUrl || '').trim()
  if (!value) return false

  try {
    const url = new URL(value)
    if (!(url.protocol === 'http:' || url.protocol === 'https:')) return false
    return ALLOWED_MEDIA_ORIGINS.includes(url.origin)
  } catch {
    return false
  }
}

export function rewriteMediaUrlForServer(rawUrl: string): string {
  const value = String(rawUrl || '').trim()
  if (!value) return value

  try {
    const targetUrl = new URL(value)
    const publicOrigin = toApiOrigin(getPublicApiBaseUrl())
    const internalOrigin = toApiOrigin(process.env.INTERNAL_API_URL || getPublicApiBaseUrl())
    if (typeof window === 'undefined' && targetUrl.origin === publicOrigin && internalOrigin) {
      const rewritten = new URL(value)
      const nextOrigin = new URL(internalOrigin)
      rewritten.protocol = nextOrigin.protocol
      rewritten.hostname = nextOrigin.hostname
      rewritten.port = nextOrigin.port
      return rewritten.toString()
    }
    return targetUrl.toString()
  } catch {
    return value
  }
}
