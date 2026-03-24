interface KlingCredentialSource {
  kling_access_key?: string | null
  kling_secret_key?: string | null
}

function normalizeValue(value: string | null | undefined): string {
  return String(value || '').trim()
}

export function resolveKlingAccessKey(source: KlingCredentialSource | undefined): string {
  return normalizeValue(source?.kling_access_key)
}

export function resolveKlingSecretKey(source: KlingCredentialSource | undefined): string {
  return normalizeValue(source?.kling_secret_key)
}

export function hasKlingCredentials(source: KlingCredentialSource | undefined): boolean {
  const accessKey = resolveKlingAccessKey(source)
  const secretKey = resolveKlingSecretKey(source)
  return Boolean(accessKey && secretKey)
}
