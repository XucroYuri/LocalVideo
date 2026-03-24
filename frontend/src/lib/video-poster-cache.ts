'use client'

const VIDEO_POSTER_DB_NAME = 'localvideo-video-poster-cache'
const VIDEO_POSTER_DB_VERSION = 1
const VIDEO_POSTER_STORE_NAME = 'video_posters'
const VIDEO_POSTER_UPDATED_AT_INDEX = 'updated_at'
const VIDEO_POSTER_CACHE_LIMIT = 120
const VIDEO_POSTER_SESSION_LIMIT = 24
const VIDEO_POSTER_SESSION_PREFIX = 'localvideo_video_poster:'
const VIDEO_POSTER_SESSION_INDEX_KEY = 'localvideo_video_poster:index'

interface VideoPosterRecord {
  src: string
  data_url: string
  updated_at: number
}

let dbPromise: Promise<IDBDatabase | null> | null = null
const inMemoryPosterCache = new Map<string, string>()

function requestToPromise<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

function normalizeCacheKey(src: string): string {
  const value = String(src || '').trim()
  if (!value) return ''

  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = ((hash << 5) - hash + value.charCodeAt(index)) | 0
  }

  return `v1_${Math.abs(hash).toString(36)}_${value.length.toString(36)}`
}

function readSessionIndex(): string[] {
  if (typeof window === 'undefined') return []

  try {
    const raw = window.sessionStorage.getItem(VIDEO_POSTER_SESSION_INDEX_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.filter((item) => typeof item === 'string' && item) : []
  } catch {
    return []
  }
}

function writeSessionIndex(keys: string[]) {
  if (typeof window === 'undefined') return
  try {
    window.sessionStorage.setItem(VIDEO_POSTER_SESSION_INDEX_KEY, JSON.stringify(keys))
  } catch {
    // Ignore storage quota failures.
  }
}

function writeSessionPoster(src: string, dataUrl: string) {
  if (typeof window === 'undefined') return

  const normalizedSrc = String(src || '').trim()
  const normalizedDataUrl = String(dataUrl || '').trim()
  const cacheKey = normalizeCacheKey(normalizedSrc)
  if (!normalizedSrc || !normalizedDataUrl || !cacheKey) return

  try {
    window.sessionStorage.setItem(`${VIDEO_POSTER_SESSION_PREFIX}${cacheKey}`, normalizedDataUrl)
    const previousIndex = readSessionIndex()
    const nextIndex = [
      cacheKey,
      ...previousIndex.filter((item) => item !== cacheKey),
    ]
    writeSessionIndex(nextIndex.slice(0, VIDEO_POSTER_SESSION_LIMIT))

    const staleKeys = nextIndex
      .filter((item, index) => index >= VIDEO_POSTER_SESSION_LIMIT)
    staleKeys.forEach((item) => {
      window.sessionStorage.removeItem(`${VIDEO_POSTER_SESSION_PREFIX}${item}`)
    })
  } catch {
    // Ignore storage quota failures.
  }
}

function readSessionPoster(src: string): string | null {
  if (typeof window === 'undefined') return null

  const normalizedSrc = String(src || '').trim()
  const cacheKey = normalizeCacheKey(normalizedSrc)
  if (!normalizedSrc || !cacheKey) return null

  try {
    const cached = window.sessionStorage.getItem(`${VIDEO_POSTER_SESSION_PREFIX}${cacheKey}`)
    const normalizedDataUrl = String(cached || '').trim()
    if (!normalizedDataUrl) return null

    const nextIndex = [
      cacheKey,
      ...readSessionIndex().filter((item) => item !== cacheKey),
    ]
    writeSessionIndex(nextIndex.slice(0, VIDEO_POSTER_SESSION_LIMIT))
    return normalizedDataUrl
  } catch {
    return null
  }
}

function writeSyncCaches(src: string, dataUrl: string) {
  const normalizedSrc = String(src || '').trim()
  const normalizedDataUrl = String(dataUrl || '').trim()
  if (!normalizedSrc || !normalizedDataUrl) return

  inMemoryPosterCache.set(normalizedSrc, normalizedDataUrl)
  writeSessionPoster(normalizedSrc, normalizedDataUrl)
}

export function getCachedVideoPosterSync(src: string): string | null {
  const normalizedSrc = String(src || '').trim()
  if (!normalizedSrc) return null

  const inMemory = inMemoryPosterCache.get(normalizedSrc)
  if (inMemory) return inMemory

  const inSession = readSessionPoster(normalizedSrc)
  if (inSession) {
    inMemoryPosterCache.set(normalizedSrc, inSession)
    return inSession
  }

  return null
}

function openVideoPosterDatabase(): Promise<IDBDatabase | null> {
  if (typeof window === 'undefined' || typeof window.indexedDB === 'undefined') {
    return Promise.resolve(null)
  }
  if (dbPromise) return dbPromise

  dbPromise = new Promise((resolve) => {
    const request = window.indexedDB.open(VIDEO_POSTER_DB_NAME, VIDEO_POSTER_DB_VERSION)

    request.onupgradeneeded = () => {
      const database = request.result
      const store = database.objectStoreNames.contains(VIDEO_POSTER_STORE_NAME)
        ? request.transaction?.objectStore(VIDEO_POSTER_STORE_NAME)
        : database.createObjectStore(VIDEO_POSTER_STORE_NAME, { keyPath: 'src' })

      if (store && !store.indexNames.contains(VIDEO_POSTER_UPDATED_AT_INDEX)) {
        store.createIndex(VIDEO_POSTER_UPDATED_AT_INDEX, VIDEO_POSTER_UPDATED_AT_INDEX)
      }
    }

    request.onsuccess = () => {
      const database = request.result
      database.onclose = () => {
        dbPromise = null
      }
      resolve(database)
    }

    request.onerror = () => {
      resolve(null)
    }

    request.onblocked = () => {
      resolve(null)
    }
  })

  return dbPromise
}

async function pruneVideoPosterCache(database: IDBDatabase): Promise<void> {
  const transaction = database.transaction(VIDEO_POSTER_STORE_NAME, 'readwrite')
  const store = transaction.objectStore(VIDEO_POSTER_STORE_NAME)
  const count = await requestToPromise(store.count())
  const overflow = count - VIDEO_POSTER_CACHE_LIMIT
  if (overflow <= 0) {
    await new Promise<void>((resolve) => {
      transaction.oncomplete = () => resolve()
      transaction.onabort = () => resolve()
      transaction.onerror = () => resolve()
    })
    return
  }

  const index = store.index(VIDEO_POSTER_UPDATED_AT_INDEX)
  let deleted = 0

  await new Promise<void>((resolve) => {
    const cursorRequest = index.openCursor()

    cursorRequest.onsuccess = () => {
      const cursor = cursorRequest.result
      if (!cursor || deleted >= overflow) {
        resolve()
        return
      }

      cursor.delete()
      deleted += 1
      cursor.continue()
    }

    cursorRequest.onerror = () => resolve()
  })

  await new Promise<void>((resolve) => {
    transaction.oncomplete = () => resolve()
    transaction.onabort = () => resolve()
    transaction.onerror = () => resolve()
  })
}

export async function getCachedVideoPoster(src: string): Promise<string | null> {
  const normalizedSrc = String(src || '').trim()
  if (!normalizedSrc) return null

  const syncCached = getCachedVideoPosterSync(normalizedSrc)
  if (syncCached) return syncCached

  try {
    const database = await openVideoPosterDatabase()
    if (!database) return null

    const transaction = database.transaction(VIDEO_POSTER_STORE_NAME, 'readonly')
    const store = transaction.objectStore(VIDEO_POSTER_STORE_NAME)
    const record = await requestToPromise(store.get(normalizedSrc)) as VideoPosterRecord | undefined
    const normalizedDataUrl = String(record?.data_url || '').trim() || null
    if (normalizedDataUrl) {
      writeSyncCaches(normalizedSrc, normalizedDataUrl)
    }
    return normalizedDataUrl
  } catch {
    return null
  }
}

export async function setCachedVideoPoster(src: string, dataUrl: string): Promise<void> {
  const normalizedSrc = String(src || '').trim()
  const normalizedDataUrl = String(dataUrl || '').trim()
  if (!normalizedSrc || !normalizedDataUrl) return

  writeSyncCaches(normalizedSrc, normalizedDataUrl)

  try {
    const database = await openVideoPosterDatabase()
    if (!database) return

    await new Promise<void>((resolve) => {
      const transaction = database.transaction(VIDEO_POSTER_STORE_NAME, 'readwrite')
      const store = transaction.objectStore(VIDEO_POSTER_STORE_NAME)
      store.put({
        src: normalizedSrc,
        data_url: normalizedDataUrl,
        updated_at: Date.now(),
      } satisfies VideoPosterRecord)
      transaction.oncomplete = () => resolve()
      transaction.onabort = () => resolve()
      transaction.onerror = () => resolve()
    })

    await pruneVideoPosterCache(database)
  } catch {
    // Ignore storage failures and fall back to sync caches only.
  }
}
