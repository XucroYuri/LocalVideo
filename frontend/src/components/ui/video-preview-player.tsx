'use client'

import { useCallback, useEffect, useRef, useState, type SyntheticEvent } from 'react'
import { Pause, Play } from 'lucide-react'

import { buildMediaProxyUrl } from '@/lib/media-proxy'
import { getCachedVideoPoster, getCachedVideoPosterSync, setCachedVideoPoster } from '@/lib/video-poster-cache'
import { cn } from '@/lib/utils'

export interface VideoPreviewPlayerProps {
  src: string
  initialDuration?: number
  posterUrl?: string
  posterAlt?: string
  posterCaptureMaxEdge?: number
  cacheCapturedPoster?: boolean
  activated?: boolean
  onActivate?: () => void
  className?: string
  videoClassName?: string
  posterClassName?: string
  onLoadedMetadata?: (event: SyntheticEvent<HTMLVideoElement>) => void
  autoPlayOnActivate?: boolean
}

const PREVIEW_SEEK_EPSILON = 0.05
const PREVIEW_SEEK_SECONDS = 0.001
const VIDEO_POSTER_MAX_EDGE = 480
const VIDEO_POSTER_MIN_BRIGHTNESS = 18
const loadedPosterCache = new Set<string>()

function formatClock(rawSeconds: number): string {
  const safeSeconds = Number.isFinite(rawSeconds) ? Math.max(0, rawSeconds) : 0
  const whole = Math.floor(safeSeconds)
  const hours = Math.floor(whole / 3600)
  const minutes = Math.floor((whole % 3600) / 60)
  const seconds = whole % 60
  return `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function isCanvasFrameTooDark(context: CanvasRenderingContext2D, width: number, height: number) {
  const sampleSize = Math.max(4, Math.min(width, height, 24))
  const offsetX = Math.max(0, Math.floor((width - sampleSize) / 2))
  const offsetY = Math.max(0, Math.floor((height - sampleSize) / 2))

  try {
    const imageData = context.getImageData(offsetX, offsetY, sampleSize, sampleSize)
    const { data } = imageData
    if (!data.length) return false

    let total = 0
    for (let index = 0; index < data.length; index += 16) {
      total += (data[index] || 0) + (data[index + 1] || 0) + (data[index + 2] || 0)
    }

    const samples = Math.max(1, Math.ceil(data.length / 16))
    const average = total / (samples * 3)
    return average < VIDEO_POSTER_MIN_BRIGHTNESS
  } catch {
    return false
  }
}

function capturePosterDataUrl(media: HTMLVideoElement, maxEdge: number): string | null {
  const width = media.videoWidth
  const height = media.videoHeight
  if (!(width > 0 && height > 0)) return null

  const normalizedMaxEdge = Number.isFinite(maxEdge) && maxEdge > 0 ? maxEdge : Math.max(width, height)
  const scale = Math.min(1, normalizedMaxEdge / Math.max(width, height))
  const targetWidth = Math.max(1, Math.round(width * scale))
  const targetHeight = Math.max(1, Math.round(height * scale))
  const canvas = document.createElement('canvas')
  canvas.width = targetWidth
  canvas.height = targetHeight

  try {
    const context = canvas.getContext('2d')
    if (!context) return null
    context.drawImage(media, 0, 0, targetWidth, targetHeight)
    if (isCanvasFrameTooDark(context, targetWidth, targetHeight)) {
      return null
    }
    return canvas.toDataURL('image/jpeg', 0.82) || null
  } catch {
    return null
  }
}

export function VideoPreviewPlayer({
  src,
  initialDuration = 0,
  posterUrl,
  posterAlt = '视频封面',
  posterCaptureMaxEdge = VIDEO_POSTER_MAX_EDGE,
  cacheCapturedPoster = true,
  activated,
  onActivate,
  className,
  videoClassName,
  posterClassName,
  onLoadedMetadata,
  autoPlayOnActivate = true,
}: VideoPreviewPlayerProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [internalActivated, setInternalActivated] = useState(false)
  const isActivated = activated ?? internalActivated
  const [isPlaying, setIsPlaying] = useState(false)
  const [isVideoReady, setIsVideoReady] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(Math.max(0, initialDuration))
  const previousActivatedRef = useRef(isActivated)
  const [isSeeking, setIsSeeking] = useState(false)
  const isSeekingRef = useRef(false)
  const previewPreparedRef = useRef(false)
  const metadataNotifiedRef = useRef(false)
  const renderedFrameCallbackIdRef = useRef<number | null>(null)
  const renderedFrameFallbackTimerRef = useRef<number | null>(null)
  const normalizedPosterUrl = String(posterUrl || '').trim()
  const normalizedSrc = String(src || '').trim()
  const normalizedPosterCaptureMaxEdge = Number.isFinite(posterCaptureMaxEdge) && posterCaptureMaxEdge > 0
    ? Math.round(posterCaptureMaxEdge)
    : 0
  const posterCacheKey = normalizedPosterUrl
    ? ''
    : `${normalizedSrc}::poster:${normalizedPosterCaptureMaxEdge > 0 ? normalizedPosterCaptureMaxEdge : 'full'}`
  const effectiveVideoSrc = buildMediaProxyUrl(normalizedSrc)
  const [loadedPosterUrl, setLoadedPosterUrl] = useState(
    () => (normalizedPosterUrl && loadedPosterCache.has(normalizedPosterUrl) ? normalizedPosterUrl : '')
  )
  const [cachedVideoPosterState, setCachedVideoPosterState] = useState<{ src: string; dataUrl: string }>({
    src: posterCacheKey,
    dataUrl: normalizedPosterUrl ? '' : (getCachedVideoPosterSync(posterCacheKey) || ''),
  })
  const syncCachedVideoPosterUrl = normalizedPosterUrl ? '' : (getCachedVideoPosterSync(posterCacheKey) || '')
  const cachedVideoPosterUrl = cachedVideoPosterState.src === posterCacheKey && cachedVideoPosterState.dataUrl
    ? cachedVideoPosterState.dataUrl
    : syncCachedVideoPosterUrl
  const resolvedPosterUrl = normalizedPosterUrl || cachedVideoPosterUrl
  const [isWaitingForRenderedFrame, setIsWaitingForRenderedFrame] = useState(false)
  const shouldLoadVideoSource = isActivated || !resolvedPosterUrl || !!onLoadedMetadata
  const activeVideoSrc = shouldLoadVideoSource ? effectiveVideoSrc : undefined

  const resolveDuration = (value: number): number => {
    if (!Number.isFinite(value)) return 0
    return Math.max(0, value)
  }

  const cancelRenderedFrameWait = useCallback((media?: HTMLVideoElement | null) => {
    if (
      renderedFrameCallbackIdRef.current !== null
      && media
      && typeof media.cancelVideoFrameCallback === 'function'
    ) {
      media.cancelVideoFrameCallback(renderedFrameCallbackIdRef.current)
    }
    if (renderedFrameFallbackTimerRef.current !== null) {
      window.clearTimeout(renderedFrameFallbackTimerRef.current)
    }
    renderedFrameCallbackIdRef.current = null
    renderedFrameFallbackTimerRef.current = null
    setIsWaitingForRenderedFrame(false)
  }, [])

  const beginRenderedFrameWait = useCallback((media: HTMLVideoElement) => {
    if (!resolvedPosterUrl) return

    cancelRenderedFrameWait(media)
    setIsWaitingForRenderedFrame(true)

    if (typeof media.requestVideoFrameCallback === 'function') {
      renderedFrameCallbackIdRef.current = media.requestVideoFrameCallback(() => {
        renderedFrameCallbackIdRef.current = null
        setIsWaitingForRenderedFrame(false)
      })
      return
    }

    renderedFrameFallbackTimerRef.current = window.setTimeout(() => {
      renderedFrameFallbackTimerRef.current = null
      setIsWaitingForRenderedFrame(false)
    }, 34)
  }, [cancelRenderedFrameWait, resolvedPosterUrl])

  useEffect(() => {
    isSeekingRef.current = isSeeking
  }, [isSeeking])

  useEffect(() => {
    const media = videoRef.current
    return () => {
      if (
        renderedFrameCallbackIdRef.current !== null
        && media
        && typeof media.cancelVideoFrameCallback === 'function'
      ) {
        media.cancelVideoFrameCallback(renderedFrameCallbackIdRef.current)
      }
      if (renderedFrameFallbackTimerRef.current !== null) {
        window.clearTimeout(renderedFrameFallbackTimerRef.current)
      }
    }
  }, [])

  useEffect(() => {
    if (!normalizedPosterUrl || loadedPosterCache.has(normalizedPosterUrl)) return

    let cancelled = false
    const image = new Image()
    const markLoaded = () => {
      if (cancelled) return
      loadedPosterCache.add(normalizedPosterUrl)
      setLoadedPosterUrl(normalizedPosterUrl)
    }
    const markFailed = () => {}

    image.onload = markLoaded
    image.onerror = markFailed
    image.src = normalizedPosterUrl
    if (image.complete) {
      markLoaded()
    }

    return () => {
      cancelled = true
      image.onload = null
      image.onerror = null
    }
  }, [normalizedPosterUrl])

  useEffect(() => {
    if (!posterCacheKey || normalizedPosterUrl) return

    let cancelled = false
    void getCachedVideoPoster(posterCacheKey).then((cachedPosterUrl) => {
      if (cancelled) return
      setCachedVideoPosterState((current) => {
        if (current.src === posterCacheKey && current.dataUrl) {
          return current
        }
        return {
          src: posterCacheKey,
          dataUrl: cachedPosterUrl || '',
        }
      })
    })

    return () => {
      cancelled = true
    }
  }, [normalizedPosterUrl, posterCacheKey])

  const primePreviewFrame = useCallback((media: HTMLVideoElement) => {
    if (isActivated || previewPreparedRef.current) return
    previewPreparedRef.current = true
    if (media.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
      setIsVideoReady(true)
      return
    }

    const safeDuration = resolveDuration(media.duration || duration)
    const targetTime = Math.min(
      PREVIEW_SEEK_SECONDS,
      Math.max(safeDuration - PREVIEW_SEEK_SECONDS, 0)
    )
    if (targetTime <= 0) {
      setIsVideoReady(media.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA)
      return
    }

    const handleSeeked = () => {
      setIsVideoReady(true)
      media.removeEventListener('seeked', handleSeeked)
      media.removeEventListener('error', handleError)
    }
    const handleError = () => {
      setIsVideoReady(media.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA)
      media.removeEventListener('seeked', handleSeeked)
      media.removeEventListener('error', handleError)
    }

    media.addEventListener('seeked', handleSeeked)
    media.addEventListener('error', handleError)
    try {
      media.currentTime = targetTime
    } catch {
      handleError()
    }
  }, [duration, isActivated])

  useEffect(() => {
    if (!shouldLoadVideoSource) return
    const media = videoRef.current
    if (!media) return
    let settled = false

    metadataNotifiedRef.current = false

    const notifyLoadedMetadata = () => {
      if (metadataNotifiedRef.current) return
      if (!(media.videoWidth > 0 && media.videoHeight > 0)) return
      metadataNotifiedRef.current = true
      onLoadedMetadata?.({ currentTarget: media } as SyntheticEvent<HTMLVideoElement>)
    }

    const syncReadyState = () => {
      setCurrentTime(media.currentTime || 0)
      setDuration(resolveDuration(media.duration || initialDuration))
      notifyLoadedMetadata()
      if (media.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
        setIsVideoReady(true)
        if (!normalizedPosterUrl && !getCachedVideoPosterSync(posterCacheKey)) {
          const capturedPosterUrl = capturePosterDataUrl(media, normalizedPosterCaptureMaxEdge)
          if (capturedPosterUrl) {
            setCachedVideoPosterState({
              src: posterCacheKey,
              dataUrl: capturedPosterUrl,
            })
            if (cacheCapturedPoster) {
              void setCachedVideoPoster(posterCacheKey, capturedPosterUrl)
            }
            settled = true
          }
        }
        if (normalizedPosterUrl || getCachedVideoPosterSync(posterCacheKey)) {
          settled = true
        }
      }
    }

    const handleLoadedMetadata = () => {
      setCurrentTime(media.currentTime || 0)
      setDuration(resolveDuration(media.duration || 0))
      primePreviewFrame(media)
      notifyLoadedMetadata()
    }
    const handleLoadedData = () => {
      setIsVideoReady(true)
      if (!normalizedPosterUrl && !getCachedVideoPosterSync(posterCacheKey)) {
        const capturedPosterUrl = capturePosterDataUrl(media, normalizedPosterCaptureMaxEdge)
        if (capturedPosterUrl) {
          setCachedVideoPosterState({
            src: posterCacheKey,
            dataUrl: capturedPosterUrl,
          })
          if (cacheCapturedPoster) {
            void setCachedVideoPoster(posterCacheKey, capturedPosterUrl)
          }
        }
      }
      setCurrentTime(media.currentTime || 0)
    }
    const handleDurationChange = () => {
      setDuration(resolveDuration(media.duration || 0))
    }
    const handleTimeUpdate = () => {
      if (isSeekingRef.current) return
      setCurrentTime(media.currentTime || 0)
    }
    const handlePlay = () => {
      setIsPlaying(true)
      setIsVideoReady(true)
    }
    const handlePause = () => {
      setIsPlaying(false)
    }
    const handleEnded = () => {
      setIsPlaying(false)
      setCurrentTime(resolveDuration(media.duration || 0))
      cancelRenderedFrameWait(media)
    }

    media.addEventListener('loadedmetadata', handleLoadedMetadata)
    media.addEventListener('loadeddata', handleLoadedData)
    media.addEventListener('durationchange', handleDurationChange)
    media.addEventListener('timeupdate', handleTimeUpdate)
    media.addEventListener('play', handlePlay)
    media.addEventListener('pause', handlePause)
    media.addEventListener('ended', handleEnded)

    const timer = window.setTimeout(syncReadyState, 0)
    const intervalId = window.setInterval(() => {
      if (settled) {
        window.clearInterval(intervalId)
        return
      }
      syncReadyState()
    }, 800)

    return () => {
      window.clearTimeout(timer)
      window.clearInterval(intervalId)
      media.removeEventListener('loadedmetadata', handleLoadedMetadata)
      media.removeEventListener('loadeddata', handleLoadedData)
      media.removeEventListener('durationchange', handleDurationChange)
      media.removeEventListener('timeupdate', handleTimeUpdate)
      media.removeEventListener('play', handlePlay)
      media.removeEventListener('pause', handlePause)
      media.removeEventListener('ended', handleEnded)
    }
  }, [
    cancelRenderedFrameWait,
    cacheCapturedPoster,
    initialDuration,
    normalizedPosterCaptureMaxEdge,
    normalizedPosterUrl,
    onLoadedMetadata,
    posterCacheKey,
    primePreviewFrame,
    shouldLoadVideoSource,
  ])

  useEffect(() => {
    const wasActivated = previousActivatedRef.current
    previousActivatedRef.current = isActivated
    if (!isActivated || !autoPlayOnActivate || wasActivated) return
    const video = videoRef.current
    if (!video) return
    const timer = window.setTimeout(() => {
      if (video.currentTime > PREVIEW_SEEK_EPSILON) {
        try {
          video.currentTime = 0
        } catch {
          // Ignore browsers that reject the reset before enough data is buffered.
        }
      }
      beginRenderedFrameWait(video)
      void video.play().catch(() => {
        cancelRenderedFrameWait(video)
        setIsPlaying(false)
      })
    }, 0)
    return () => window.clearTimeout(timer)
  }, [isActivated, autoPlayOnActivate, beginRenderedFrameWait, cancelRenderedFrameWait])

  const activate = () => {
    if (activated === undefined) {
      setInternalActivated(true)
    }
    onActivate?.()
  }

  const commitSeek = (value: number) => {
    const media = videoRef.current
    if (!media) return
    const safeDuration = resolveDuration(media.duration || duration)
    const nextTime = Math.min(Math.max(0, value), safeDuration)
    media.currentTime = nextTime
    setCurrentTime(nextTime)
  }

  const handleSeekChange = (value: string) => {
    const nextTime = Number(value)
    if (!Number.isFinite(nextTime)) return
    setCurrentTime(nextTime)
  }

  const togglePlay = async () => {
    const media = videoRef.current
    if (!media) {
      activate()
      return
    }
    if (media.paused) {
      const safeDuration = resolveDuration(media.duration || duration)
      const isNearEnd = safeDuration > 0
        && media.currentTime >= Math.max(safeDuration - PREVIEW_SEEK_EPSILON, PREVIEW_SEEK_SECONDS)

      if (isNearEnd) {
        try {
          media.currentTime = PREVIEW_SEEK_SECONDS
          setCurrentTime(PREVIEW_SEEK_SECONDS)
        } catch {
          setCurrentTime(0)
        }
      }

      beginRenderedFrameWait(media)
      try {
        await media.play()
      } catch {
        cancelRenderedFrameWait(media)
        setIsPlaying(false)
      }
      return
    }
    media.pause()
  }

  const progressMax = Math.max(duration, currentTime, 0.01)
  const progressPercent = progressMax > 0 ? (currentTime / progressMax) * 100 : 0
  const isPosterLoaded = normalizedPosterUrl
    ? (
        loadedPosterCache.has(normalizedPosterUrl)
        || loadedPosterUrl === normalizedPosterUrl
      )
    : !!cachedVideoPosterUrl
  const shouldPinPoster = !!resolvedPosterUrl && !isActivated
  const shouldShowPoster = shouldPinPoster || (!!resolvedPosterUrl && (!isVideoReady || isWaitingForRenderedFrame))
  const shouldShowVideo = isVideoReady && !shouldPinPoster

  return (
    <div className={cn('inline-block h-full w-full', className)}>
      <div className="group/video-preview relative inline-block h-full w-full overflow-hidden rounded-lg bg-black/90">
        <video
          ref={videoRef}
          src={activeVideoSrc}
          crossOrigin="anonymous"
          preload={shouldLoadVideoSource ? 'metadata' : 'none'}
          muted={!isActivated}
          playsInline
          className={cn(
            'h-full w-full object-contain',
            shouldShowVideo ? 'opacity-100' : 'opacity-0',
            isActivated ? videoClassName : posterClassName || videoClassName
          )}
        />

        {shouldShowPoster && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={resolvedPosterUrl}
            alt={posterAlt}
            className={cn(
              'pointer-events-none absolute inset-0 h-full w-full transition-opacity duration-150',
              posterClassName || videoClassName,
              isPosterLoaded ? 'opacity-100' : 'opacity-0'
            )}
          />
        )}

        {!isVideoReady && !isPosterLoaded && (
          <div className="absolute inset-0 bg-black/90" />
        )}

        {!isActivated ? (
          <button
            type="button"
            onClick={activate}
            className="absolute inset-0 flex items-center justify-center bg-transparent"
            aria-label="播放视频"
          >
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-black/60 text-white shadow-lg">
              <Play className="ml-0.5 h-4 w-4 fill-current" />
            </div>
            <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 via-black/35 to-transparent px-3 pb-3 pt-8">
              <div className="flex justify-end">
                <span className="w-[96px] text-right text-[11px] font-medium tabular-nums text-white/90">
                  {formatClock(0)} / {formatClock(duration)}
                </span>
              </div>
            </div>
          </button>
        ) : (
          <>
            {!isPlaying ? (
              <button
                type="button"
                onClick={() => void togglePlay()}
                className="absolute inset-0 flex items-center justify-center bg-transparent"
                aria-label="播放视频"
              >
                <div className="flex h-12 w-12 items-center justify-center rounded-full bg-black/60 text-white shadow-lg">
                  <Play className="ml-0.5 h-4 w-4 fill-current" />
                </div>
              </button>
            ) : (
              <button
                type="button"
                onClick={() => void togglePlay()}
                className="absolute inset-0 flex items-center justify-center bg-transparent opacity-0 transition-opacity group-hover/video-preview:opacity-100"
                aria-label="暂停视频"
              >
                <div className="flex h-12 w-12 items-center justify-center rounded-full bg-black/60 text-white shadow-lg">
                  <Pause className="h-4 w-4" />
                </div>
              </button>
            )}
            <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 via-black/45 to-transparent px-3 pb-3 pt-8">
              <div className="mb-2 flex justify-end">
                <span className="rounded-md bg-black/35 px-2 py-1 text-right text-[11px] font-medium tabular-nums text-white/95">
                  {formatClock(currentTime)} / {formatClock(duration)}
                </span>
              </div>
              <div className="pointer-events-auto relative h-5 w-full">
                <div className="pointer-events-none absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-white/25" />
                <div
                  className="pointer-events-none absolute left-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-white"
                  style={{ width: `${Math.min(Math.max(progressPercent, 0), 100)}%` }}
                />
                <input
                  type="range"
                  min={0}
                  max={progressMax}
                  step={0.01}
                  value={Math.min(currentTime, progressMax)}
                  onMouseDown={() => setIsSeeking(true)}
                  onMouseUp={(event) => {
                    setIsSeeking(false)
                    commitSeek(Number(event.currentTarget.value))
                  }}
                  onTouchStart={() => setIsSeeking(true)}
                  onTouchEnd={(event) => {
                    setIsSeeking(false)
                    commitSeek(Number(event.currentTarget.value))
                  }}
                  onChange={(event) => handleSeekChange(event.currentTarget.value)}
                  onInput={(event) => handleSeekChange((event.target as HTMLInputElement).value)}
                  className="absolute inset-0 z-10 h-full w-full cursor-pointer appearance-none bg-transparent [&::-webkit-slider-runnable-track]:h-5 [&::-webkit-slider-runnable-track]:bg-transparent [&::-webkit-slider-thumb]:mt-1 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:shadow [&::-moz-range-track]:h-5 [&::-moz-range-track]:bg-transparent [&::-moz-range-thumb]:h-3 [&::-moz-range-thumb]:w-3 [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-white [&::-moz-range-thumb]:shadow"
                  aria-label="视频播放进度"
                />
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
