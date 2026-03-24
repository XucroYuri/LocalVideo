'use client'

import { useEffect, useRef, useState } from 'react'
import { Pause, Play } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Slider } from '@/components/ui/slider'
import { cn } from '@/lib/utils'

interface AudioPlayerProps {
  src: string
  className?: string
  playerKey?: string
  activePlayerKey?: string | null
  onPlayRequest?: (key: string) => void
  onPlaybackStateChange?: (isPlaying: boolean) => void
  initialDuration?: number
  preload?: 'none' | 'metadata' | 'auto'
}

function formatClock(rawSeconds: number): string {
  const safeSeconds = Number.isFinite(rawSeconds) ? Math.max(0, rawSeconds) : 0
  const whole = Math.floor(safeSeconds)
  const hours = Math.floor(whole / 3600)
  const minutes = Math.floor((whole % 3600) / 60)
  const seconds = whole % 60
  return `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

export function AudioPlayer(props: AudioPlayerProps) {
  return <AudioPlayerInner key={`${props.src}:${props.initialDuration || 0}:${props.preload || 'metadata'}`} {...props} />
}

function AudioPlayerInner({
  src,
  className,
  playerKey,
  activePlayerKey = null,
  onPlayRequest,
  onPlaybackStateChange,
  initialDuration = 0,
  preload = 'metadata',
}: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [isSeeking, setIsSeeking] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(Math.max(0, initialDuration))
  const [isMetadataReady, setIsMetadataReady] = useState(preload !== 'none' && initialDuration <= 0)

  const resolveDuration = (value: number): number => {
    if (!Number.isFinite(value)) return 0
    return Math.max(0, value)
  }
  const canSeek = isMetadataReady && duration > 0

  useEffect(() => {
    if (!playerKey || !activePlayerKey || activePlayerKey === playerKey) return
    const media = audioRef.current
    if (!media || media.paused) return
    media.pause()
  }, [activePlayerKey, playerKey])

  const togglePlay = async () => {
    const media = audioRef.current
    if (!media) return
    if (media.paused) {
      if (playerKey && onPlayRequest) {
        onPlayRequest(playerKey)
      }
      try {
        await media.play()
      } catch {
        setIsPlaying(false)
        onPlaybackStateChange?.(false)
      }
      return
    }
    media.pause()
  }

  return (
    <div
      className={cn(
        'w-full rounded-xl border border-border/60 bg-gradient-to-b from-background to-muted/20 px-2.5 py-2 shadow-sm',
        className
      )}
    >
      <audio
        key={src}
        ref={audioRef}
        src={src}
        preload={preload}
        className="hidden"
        onLoadStart={() => {
          setIsPlaying(false)
          setIsSeeking(false)
          setCurrentTime(0)
          setDuration(Math.max(0, initialDuration))
          setIsMetadataReady(false)
        }}
        onLoadedMetadata={(event) => {
          const media = event.currentTarget
          setCurrentTime(media.currentTime || 0)
          setDuration(resolveDuration(media.duration || 0))
          setIsMetadataReady(true)
        }}
        onDurationChange={(event) => {
          setDuration(resolveDuration(event.currentTarget.duration || 0))
          setIsMetadataReady(true)
        }}
        onTimeUpdate={(event) => {
          if (isSeeking) return
          setCurrentTime(event.currentTarget.currentTime || 0)
        }}
        onPlay={() => {
          setIsPlaying(true)
          onPlaybackStateChange?.(true)
        }}
        onPause={() => {
          setIsPlaying(false)
          onPlaybackStateChange?.(false)
        }}
        onEnded={() => {
          setIsPlaying(false)
          const media = audioRef.current
          setCurrentTime(resolveDuration(media?.duration || 0))
          onPlaybackStateChange?.(false)
        }}
      />

      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="icon-xs"
          className="shrink-0 rounded-full border-primary/30 text-primary hover:border-primary/60 hover:bg-primary/10"
          onClick={() => void togglePlay()}
          disabled={!src}
          aria-label={isPlaying ? '暂停' : '播放'}
        >
          {isPlaying ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5 translate-x-[0.5px]" />}
        </Button>

        <div className="min-w-0 flex-1">
          <Slider
            min={0}
            max={canSeek ? duration : 0}
            step={0.05}
            value={[Math.min(currentTime, canSeek ? duration : 0)]}
            disabled={!canSeek}
            onValueChange={(value) => {
              const nextTime = value[0] ?? 0
              setIsSeeking(true)
              setCurrentTime(nextTime)
            }}
            onValueCommit={(value) => {
              const nextTime = value[0] ?? 0
              const media = audioRef.current
              if (media) media.currentTime = nextTime
              setCurrentTime(nextTime)
              setIsSeeking(false)
            }}
            className="w-full"
          />
        </div>

        <span className="w-[112px] text-right text-[11px] font-medium tabular-nums text-muted-foreground">
          {formatClock(currentTime)} / {formatClock(duration)}
        </span>
      </div>
    </div>
  )
}
