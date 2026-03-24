const FALLBACK_PUBLIC_API_BASE_URL = 'http://localhost:8000/api/v1'

export function getPublicApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_URL || FALLBACK_PUBLIC_API_BASE_URL
}

export function getInternalApiBaseUrl(): string {
  if (typeof window === 'undefined') {
    return process.env.INTERNAL_API_URL || getPublicApiBaseUrl()
  }
  return getPublicApiBaseUrl()
}

export function toApiOrigin(apiBaseUrl: string): string {
  return apiBaseUrl.replace(/\/api\/v1\/?$/, '')
}

