'use client'

import { useState, useCallback, useRef, useEffect, useMemo, type ReactNode, type SyntheticEvent } from 'react'
import {
  FileText, ImageIcon, Video, Play, Volume2,
  X, Trash2, RefreshCw, Upload, Plus, Wand2, ArrowUp, ArrowDown, LayoutGrid, MoreHorizontal, CircleHelp, ChevronDown,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { AudioPlayer } from '@/components/ui/audio-player'
import { VideoPreviewPlayerClient } from '@/components/ui/video-preview-player-client'
import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type { Shot, Reference, ScriptRole } from '@/lib/content-panel-helpers'
import {
  countScriptChars,
  resolveScriptMode, resolveShotGeneratingState, isStageRunningWithFallback,
  resolveCurrentItemGenerationState, resolveRuntimeDisplay,
  buildSpeakerOptionsForMode, normalizeRolesForMode, getRoleName, NARRATOR_ROLE_ID,
} from '@/lib/content-panel-helpers'

interface ShotsTabContentProps {
  stageData?: {
    content?: {
      script_mode?: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'
      roles?: ScriptRole[]
    }
    storyboard?: {
      shots?: Shot[]
      references?: Reference[]
    }
    audio?: {
      shots?: Shot[]
    }
    reference?: {
      references?: Reference[]
    }
    frame?: {
      shots?: Array<{
        first_frame_url?: string
        first_frame_description?: string
        updated_at?: number
      }>
    }
    video?: {
      shots?: Shot[]
    }
  }
  generatingShots?: Record<string, { status: string; progress: number }>
  runningStage?: string
  progress?: number
  progressMessage?: string
  frameStageStatus?: string
  videoStageStatus?: string
  runningShotIndex?: number
  configuredScriptMode?: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'
  useReferenceImageRef?: boolean
  singleTakeEnabled?: boolean
  useFirstFrameRef?: boolean
  useReferenceConsistency?: boolean
  onSaveFrameDescription?: (shotIndex: number, description: string) => Promise<void>
  onGenerateFrameDescription?: (shotIndex: number) => Promise<void>
  onSaveFrameReferences?: (shotIndex: number, referenceIds: string[]) => Promise<void>
  onRegenerateFrameImage?: (shotIndex: number) => Promise<void>
  onReuseFirstFrameToOthers?: () => Promise<void>
  onUploadFrameImage?: (shotIndex: number, file: File) => Promise<void>
  onDeleteFrameImage?: (shotIndex: number) => Promise<void>
  onClearAllAudio?: () => Promise<void>
  onClearAllFrameImages?: () => Promise<void>
  onGenerateVideoDescription?: (shotIndex: number) => Promise<void>
  onRegenerateVideo?: (shotIndex: number) => Promise<void>
  onSaveVideoDescription?: (shotIndex: number, description: string) => Promise<void>
  onSaveVideoReferences?: (shotIndex: number, referenceIds: string[]) => Promise<void>
  onDeleteVideo?: (shotIndex: number) => Promise<void>
  onClearAllVideos?: () => Promise<void>
  onClearAllShotContent?: () => Promise<void>
  onSmartMergeShots?: () => Promise<void>
  onInsertShots?: (anchorIndex: number, direction: 'before' | 'after', count: number) => Promise<void>
  onMoveShot?: (shotId: string, direction: 'up' | 'down', step?: number) => Promise<void>
  onDeleteShot?: (shotId: string) => Promise<void>
  onUpdateShot?: (
    shotId: string,
    data: {
      voice_content?: string
      speaker_id?: string
      speaker_name?: string
    }
  ) => Promise<void>
  onRegenerateAudio?: (shotIndex: number) => Promise<void>
}

const EMPTY_SHOTS: Shot[] = []
const EMPTY_REFERENCES: Reference[] = []
const SHOT_EDITOR_TEXTAREA_CLASS = 'min-h-[100px] max-h-[140px] overflow-y-auto resize-none text-sm leading-5'

interface LazyMountProps {
  placeholder: ReactNode
  children: ReactNode
  className?: string
  rootMargin?: string
}

function LazyMount({
  placeholder,
  children,
  className,
  rootMargin = '320px 0px',
}: LazyMountProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [isVisible, setIsVisible] = useState(false)

  useEffect(() => {
    if (isVisible) return
    const node = containerRef.current
    if (!node || typeof IntersectionObserver === 'undefined') {
      const timer = window.setTimeout(() => setIsVisible(true), 0)
      return () => window.clearTimeout(timer)
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setIsVisible(true)
          observer.disconnect()
        }
      },
      { rootMargin }
    )

    observer.observe(node)
    return () => observer.disconnect()
  }, [isVisible, rootMargin])

  return (
    <div ref={containerRef} className={className}>
      {isVisible ? children : placeholder}
    </div>
  )
}

interface DeferredVideoPreviewProps {
  videoUrl: string
  initialDuration?: number
  activated: boolean
  onActivate: () => void
  className?: string
  videoClassName?: string
  posterClassName?: string
  onLoadedMetadata?: (event: SyntheticEvent<HTMLVideoElement>) => void
}

function DeferredVideoPreview({
  videoUrl,
  initialDuration,
  activated,
  onActivate,
  className,
  videoClassName,
  posterClassName,
  onLoadedMetadata,
}: DeferredVideoPreviewProps) {
  return (
    <VideoPreviewPlayerClient
      key={videoUrl}
      src={videoUrl}
      initialDuration={initialDuration}
      activated={activated}
      onActivate={onActivate}
      className={className}
      videoClassName={videoClassName}
      posterClassName={posterClassName}
      onLoadedMetadata={onLoadedMetadata}
      autoPlayOnActivate
    />
  )
}

function formatStatsDuration(rawSeconds: number): string {
  const safeSeconds = Number.isFinite(rawSeconds) ? Math.max(0, rawSeconds) : 0
  const whole = Math.floor(safeSeconds)
  const hours = Math.floor(whole / 3600)
  const minutes = Math.floor((whole % 3600) / 60)
  const seconds = whole % 60
  return `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

export function ShotsTabContent({
  stageData,
  generatingShots,
  runningStage,
  progress,
  progressMessage,
  frameStageStatus,
  videoStageStatus,
  runningShotIndex,
  configuredScriptMode,
  useReferenceImageRef,
  singleTakeEnabled = false,
  useFirstFrameRef = false,
  useReferenceConsistency = false,
  onSaveFrameDescription,
  onGenerateFrameDescription,
  onSaveFrameReferences,
  onRegenerateFrameImage,
  onReuseFirstFrameToOthers,
  onUploadFrameImage,
  onDeleteFrameImage,
  onClearAllAudio,
  onClearAllFrameImages,
  onGenerateVideoDescription,
  onRegenerateVideo,
  onSaveVideoDescription,
  onSaveVideoReferences,
  onDeleteVideo,
  onClearAllVideos,
  onClearAllShotContent,
  onSmartMergeShots,
  onInsertShots,
  onMoveShot,
  onDeleteShot,
  onUpdateShot,
  onRegenerateAudio,
}: ShotsTabContentProps) {
  const frameFileInputRef = useRef<HTMLInputElement>(null)

  // Frame description editing states
  const [frameDescDrafts, setFrameDescDrafts] = useState<Record<number, string>>({})
  const [isGeneratingFrameDesc, setIsGeneratingFrameDesc] = useState(false)
  const [isSavingFrameReferences, setIsSavingFrameReferences] = useState(false)
  const [regeneratingFrameShotIndex, setRegeneratingFrameShotIndex] = useState<number | null>(null)
  const [isReusingFirstFrame, setIsReusingFirstFrame] = useState(false)
  const [isUploadingFrame, setIsUploadingFrame] = useState(false)
  const [frameUploadShotIndex, setFrameUploadShotIndex] = useState<number | null>(null)
  const [deletingFrameShotIndex, setDeletingFrameShotIndex] = useState<number | null>(null)
  const [brokenFrameImageByShot, setBrokenFrameImageByShot] = useState<Record<number, string>>({})

  // Video description editing states
  const [videoDescDrafts, setVideoDescDrafts] = useState<Record<number, string>>({})
  const [isGeneratingVideoDesc, setIsGeneratingVideoDesc] = useState(false)
  const [isSavingVideoReferences, setIsSavingVideoReferences] = useState(false)

  // Delete states
  const [deletingVideoShotIndex, setDeletingVideoShotIndex] = useState<number | null>(null)
  const [isClearingAllAudio, setIsClearingAllAudio] = useState(false)
  const [isClearingAllFrameImages, setIsClearingAllFrameImages] = useState(false)
  const [isClearingAllVideos, setIsClearingAllVideos] = useState(false)
  const [isClearingAllShotContent, setIsClearingAllShotContent] = useState(false)
  const [isSmartMergingShots, setIsSmartMergingShots] = useState(false)
  const [shotDrafts, setShotDrafts] = useState<Record<string, {
    voiceContent: string
    speakerId: string
    speakerName: string
  }>>({})
  const [insertingAnchorKey, setInsertingAnchorKey] = useState<string | null>(null)
  const [movingShotId, setMovingShotId] = useState<string | null>(null)
  const [deletingShotId, setDeletingShotId] = useState<string | null>(null)
  const [insertCountByShot, setInsertCountByShot] = useState<Record<string, number>>({})
  const [compactMode, setCompactMode] = useState(false)
  const [videoAspectByShot, setVideoAspectByShot] = useState<Record<string, number>>({})
  const [activatedVideoByShot, setActivatedVideoByShot] = useState<Record<string, boolean>>({})
  const shotAutoSaveTimersRef = useRef<Record<string, number>>({})
  const frameDescAutoSaveTimersRef = useRef<Record<number, number>>({})
  const videoDescAutoSaveTimersRef = useRef<Record<number, number>>({})
  const lastSubmittedShotSignatureRef = useRef<Record<string, string>>({})
  const lastSubmittedFrameDescRef = useRef<Record<number, string>>({})
  const lastSubmittedVideoDescRef = useRef<Record<number, string>>({})

  const resolvedConfiguredScriptMode = resolveScriptMode(configuredScriptMode)
  const hasAnyGeneratingShot = !!generatingShots && Object.keys(generatingShots).length > 0
  const isFrameReferenceEffective = !!useReferenceConsistency
  const isVideoReferenceEffective = !!useReferenceImageRef
  const references = stageData?.reference?.references ?? stageData?.storyboard?.references ?? EMPTY_REFERENCES
  const shots = stageData?.storyboard?.shots ?? EMPTY_SHOTS
  const audioShots = stageData?.audio?.shots ?? EMPTY_SHOTS
  const frameShots = stageData?.frame?.shots ?? EMPTY_SHOTS
  const videoShots = stageData?.video?.shots ?? EMPTY_SHOTS
  const shotsScriptMode = resolveScriptMode(
    configuredScriptMode || stageData?.content?.script_mode,
    resolvedConfiguredScriptMode
  )
  const normalizedContentRoles = useMemo(
    () => normalizeRolesForMode(
      shotsScriptMode,
      stageData?.content?.roles,
      Math.max(1, stageData?.content?.roles?.length || references.length || 1)
    ),
    [references.length, shotsScriptMode, stageData?.content?.roles]
  )
  const shotSpeakerOptionsBase = useMemo(() => {
    const optionMap = new Map<string, string>()
    buildSpeakerOptionsForMode(shotsScriptMode, normalizedContentRoles, references).forEach((option) => {
      const id = String(option.id || '').trim()
      const name = String(option.name || '').trim()
      if (!id) return
      optionMap.set(id, name || getRoleName(id, normalizedContentRoles))
    })
    shots.forEach((shot) => {
      const speakerId = String(shot?.speaker_id || '').trim()
      if (!speakerId || optionMap.has(speakerId)) return
      const speakerName = String(shot?.speaker_name || '').trim() || getRoleName(speakerId, normalizedContentRoles)
      optionMap.set(speakerId, speakerName || speakerId)
    })
    if (optionMap.size === 0) {
      optionMap.set(NARRATOR_ROLE_ID, '讲述者')
    }
    return Array.from(optionMap.entries()).map(([id, name]) => ({ id, name }))
  }, [normalizedContentRoles, references, shots, shotsScriptMode])
  const shotSpeakerNameById = useMemo(
    () => new Map(shotSpeakerOptionsBase.map((option) => [option.id, option.name])),
    [shotSpeakerOptionsBase]
  )
  const frameDescSavedSignature = useMemo(
    () => Array.from({ length: Math.max(shots.length, frameShots.length) })
      .map((_, shotIndex) => `${shotIndex}:${String(
        shots[shotIndex]?.first_frame_description
        || frameShots[shotIndex]?.first_frame_description
        || ''
      )}`)
      .join('\u0001'),
    [frameShots, shots]
  )
  const videoDescSavedSignature = useMemo(
    () => shots
      .map((shot, shotIndex) => `${shotIndex}:${String(shot?.video_prompt || '')}`)
      .join('\u0001'),
    [shots]
  )

  useEffect(() => {
    if (typeof window === 'undefined') return
    const saved = window.localStorage.getItem('localvideo_shots_compact_mode')
    setCompactMode(saved === '1')
  }, [])

  const handleSaveFrameDesc = useCallback(async (shotIndex: number, description: string) => {
    if (!onSaveFrameDescription) return
    if (lastSubmittedFrameDescRef.current[shotIndex] === description) return
    try {
      await onSaveFrameDescription(shotIndex, description)
      lastSubmittedFrameDescRef.current = {
        ...lastSubmittedFrameDescRef.current,
        [shotIndex]: description,
      }
    } catch (error) {
      console.error('Failed to save frame description:', error)
      toast.error('首帧描述保存失败')
    }
  }, [onSaveFrameDescription])

  const flushAutoSaveFrameDesc = useCallback(async (shotIndex: number) => {
    const draft = String(frameDescDrafts[shotIndex] || '')
    const timerId = frameDescAutoSaveTimersRef.current[shotIndex]
    if (timerId) {
      window.clearTimeout(timerId)
      delete frameDescAutoSaveTimersRef.current[shotIndex]
    }
    await handleSaveFrameDesc(shotIndex, draft)
  }, [frameDescDrafts, handleSaveFrameDesc])

  const handleGenerateFrameDesc = async (shotIndex: number) => {
    if (!onGenerateFrameDescription) return
    const shots = stageData?.storyboard?.shots || []
    const shot = shots[shotIndex]
    const videoPrompt = String(shot?.video_prompt || '').trim()
    if (!videoPrompt) {
      toast.info('请先生成视频描述')
      return
    }
    setIsGeneratingFrameDesc(true)
    try {
      await onGenerateFrameDescription(shotIndex)
    } catch (error) {
      console.error('Failed to generate frame description:', error)
    } finally {
      setIsGeneratingFrameDesc(false)
    }
  }

  const handleSaveFrameReferences = async (shotIndex: number, referenceIds: string[]) => {
    if (!onSaveFrameReferences) return
    setIsSavingFrameReferences(true)
    try {
      await onSaveFrameReferences(shotIndex, referenceIds)
    } catch (error) {
      console.error('Failed to save frame references:', error)
    } finally {
      setIsSavingFrameReferences(false)
    }
  }

  const handleRegenerateFrameImage = async (shotIndex: number) => {
    if (!onRegenerateFrameImage) return
    setRegeneratingFrameShotIndex(shotIndex)
    try {
      await onRegenerateFrameImage(shotIndex)
    } catch (error) {
      console.error('Failed to regenerate frame image:', error)
    } finally {
      setRegeneratingFrameShotIndex(null)
    }
  }

  const handleReuseFirstFrameToOthers = async () => {
    if (!onReuseFirstFrameToOthers) return
    setIsReusingFirstFrame(true)
    try {
      await onReuseFirstFrameToOthers()
    } catch (error) {
      console.error('Failed to reuse first frame image to other shots:', error)
    } finally {
      setIsReusingFirstFrame(false)
    }
  }

  const handleFrameImageClick = (shotIndex: number) => {
    if (!onUploadFrameImage || isUploadingFrame || regeneratingFrameShotIndex !== null) return
    setFrameUploadShotIndex(shotIndex)
    frameFileInputRef.current?.click()
  }

  const handleFrameFileChange = async (e: React.ChangeEvent<HTMLInputElement>, shotIndex: number) => {
    const file = e.target.files?.[0]
    if (!file || !onUploadFrameImage) {
      setFrameUploadShotIndex(null)
      if (frameFileInputRef.current) {
        frameFileInputRef.current.value = ''
      }
      return
    }

    setIsUploadingFrame(true)
    try {
      await onUploadFrameImage(shotIndex, file)
    } catch (error) {
      console.error('Failed to upload frame image:', error)
    } finally {
      setIsUploadingFrame(false)
      setFrameUploadShotIndex(null)
      if (frameFileInputRef.current) {
        frameFileInputRef.current.value = ''
      }
    }
  }

  const handleRegenerateVideo = async (shotIndex: number) => {
    if (!onRegenerateVideo) return
    try {
      await onRegenerateVideo(shotIndex)
    } catch (error) {
      console.error('Failed to regenerate video:', error)
    } finally {
    }
  }

  const handleSaveVideoDesc = useCallback(async (shotIndex: number, description: string) => {
    if (!onSaveVideoDescription) return
    if (lastSubmittedVideoDescRef.current[shotIndex] === description) return
    try {
      await onSaveVideoDescription(shotIndex, description)
      lastSubmittedVideoDescRef.current = {
        ...lastSubmittedVideoDescRef.current,
        [shotIndex]: description,
      }
    } catch (error) {
      console.error('Failed to save video description:', error)
      toast.error('视频描述保存失败')
    }
  }, [onSaveVideoDescription])

  const flushAutoSaveVideoDesc = useCallback(async (shotIndex: number) => {
    const draft = String(videoDescDrafts[shotIndex] || '')
    const timerId = videoDescAutoSaveTimersRef.current[shotIndex]
    if (timerId) {
      window.clearTimeout(timerId)
      delete videoDescAutoSaveTimersRef.current[shotIndex]
    }
    await handleSaveVideoDesc(shotIndex, draft)
  }, [handleSaveVideoDesc, videoDescDrafts])

  const handleSaveVideoReferences = async (shotIndex: number, referenceIds: string[]) => {
    if (!onSaveVideoReferences) return
    setIsSavingVideoReferences(true)
    try {
      await onSaveVideoReferences(shotIndex, referenceIds)
    } catch (error) {
      console.error('Failed to save video references:', error)
    } finally {
      setIsSavingVideoReferences(false)
    }
  }

  const handleGenerateVideoDesc = async (shotIndex: number) => {
    if (!onGenerateVideoDescription) return
    setIsGeneratingVideoDesc(true)
    try {
      await onGenerateVideoDescription(shotIndex)
    } catch (error) {
      console.error('Failed to generate video description:', error)
    } finally {
      setIsGeneratingVideoDesc(false)
    }
  }

  const handleDeleteFrameImage = async (shotIndex: number) => {
    if (!onDeleteFrameImage) return
    setDeletingFrameShotIndex(shotIndex)
    try {
      await onDeleteFrameImage(shotIndex)
    } catch (error) {
      console.error('Failed to delete frame image:', error)
    } finally {
      setDeletingFrameShotIndex(null)
    }
  }

  const handleDeleteVideo = async (shotIndex: number) => {
    if (!onDeleteVideo) return
    setDeletingVideoShotIndex(shotIndex)
    try {
      await onDeleteVideo(shotIndex)
    } catch (error) {
      console.error('Failed to delete video:', error)
    } finally {
      setDeletingVideoShotIndex(null)
    }
  }

  const handleClearAllFrameImages = async () => {
    if (!onClearAllFrameImages) return
    setIsClearingAllFrameImages(true)
    try {
      await onClearAllFrameImages()
    } finally {
      setIsClearingAllFrameImages(false)
    }
  }

  const handleClearAllAudio = async () => {
    if (!onClearAllAudio) return
    setIsClearingAllAudio(true)
    try {
      await onClearAllAudio()
    } finally {
      setIsClearingAllAudio(false)
    }
  }

  const handleClearAllVideos = async () => {
    if (!onClearAllVideos) return
    setIsClearingAllVideos(true)
    try {
      await onClearAllVideos()
    } finally {
      setIsClearingAllVideos(false)
    }
  }

  const handleClearAllShotContent = async () => {
    if (!onClearAllShotContent) return
    setIsClearingAllShotContent(true)
    try {
      await onClearAllShotContent()
    } finally {
      setIsClearingAllShotContent(false)
    }
  }

  const handleSmartMergeShots = async () => {
    if (!onSmartMergeShots) return
    setIsSmartMergingShots(true)
    try {
      await onSmartMergeShots()
    } catch (error) {
      console.error('Failed to smart merge shots:', error)
    } finally {
      setIsSmartMergingShots(false)
    }
  }

  const handleToggleCompactMode = () => {
    const next = !compactMode
    setCompactMode(next)
    if (typeof window !== 'undefined') {
      window.localStorage.setItem('localvideo_shots_compact_mode', next ? '1' : '0')
    }
  }

  const handleActivateVideoPreview = useCallback((shotId: string) => {
    const normalized = String(shotId || '').trim()
    if (!normalized) return
    setActivatedVideoByShot((prev) => {
      if (prev[normalized]) return prev
      return { ...prev, [normalized]: true }
    })
  }, [])

  const resolveShotId = useCallback((shot: Shot | undefined, fallbackShotIndex?: number) => {
    const normalized = String(shot?.shot_id || '').trim()
    if (normalized) return normalized
    if (typeof fallbackShotIndex === 'number' && Number.isFinite(fallbackShotIndex) && fallbackShotIndex >= 0) {
      return `shot_${Math.floor(fallbackShotIndex) + 1}`
    }
    return ''
  }, [])

  const buildShotSignature = useCallback((draft: {
    voiceContent: string
    speakerId: string
    speakerName: string
  }) => JSON.stringify({
    voiceContent: String(draft.voiceContent || ''),
    speakerId: String(draft.speakerId || ''),
    speakerName: String(draft.speakerName || ''),
  }), [])

  const updateShotDraft = useCallback((shotId: string, draft: {
    voiceContent: string
    speakerId: string
    speakerName: string
  }) => {
    setShotDrafts((prev) => ({
      ...prev,
      [shotId]: draft,
    }))
  }, [])

  const handleSaveShot = useCallback(async (shotId: string, draft: {
    voiceContent: string
    speakerId: string
    speakerName: string
  }) => {
    if (!onUpdateShot || !shotId) return
    const signature = buildShotSignature(draft)
    if (lastSubmittedShotSignatureRef.current[shotId] === signature) return
    try {
      await onUpdateShot(shotId, {
        voice_content: draft.voiceContent,
        speaker_id: draft.speakerId,
        speaker_name: draft.speakerName,
      })
      lastSubmittedShotSignatureRef.current = {
        ...lastSubmittedShotSignatureRef.current,
        [shotId]: signature,
      }
    } catch (error) {
      console.error('Failed to save shot:', error)
      toast.error('保存失败')
    }
  }, [buildShotSignature, onUpdateShot])

  const flushAutoSaveShot = useCallback(async (shotId: string) => {
    const draft = shotDrafts[shotId]
    if (!draft) return
    if (shotAutoSaveTimersRef.current[shotId]) {
      window.clearTimeout(shotAutoSaveTimersRef.current[shotId])
      delete shotAutoSaveTimersRef.current[shotId]
    }
    await handleSaveShot(shotId, draft)
  }, [handleSaveShot, shotDrafts])

  const handleInsertShots = async (
    anchorIndex: number,
    direction: 'before' | 'after',
    key: string,
    defaultCount = 1
  ) => {
    if (!onInsertShots) return
    const currentCount = Math.max(1, Math.floor(insertCountByShot[key] ?? defaultCount))
    setInsertingAnchorKey(key)
    try {
      await onInsertShots(anchorIndex, direction, currentCount)
    } catch (error) {
      console.error('Failed to insert shots:', error)
    } finally {
      setInsertingAnchorKey(null)
    }
  }

  const handleMoveShot = async (shotId: string, direction: 'up' | 'down') => {
    if (!onMoveShot) return
    setMovingShotId(shotId)
    try {
      await onMoveShot(shotId, direction, 1)
    } catch (error) {
      console.error('Failed to move shot:', error)
    } finally {
      setMovingShotId(null)
    }
  }

  const handleDeleteShotAction = async (shotId: string) => {
    if (!onDeleteShot) return
    setDeletingShotId(shotId)
    try {
      await onDeleteShot(shotId)
    } catch (error) {
      console.error('Failed to delete shot:', error)
    } finally {
      setDeletingShotId(null)
    }
  }

  useEffect(() => {
    setShotDrafts((prev) => {
      const next: typeof prev = {}
      shots.forEach((shot, shotIndex) => {
        const shotId = resolveShotId(shot, shotIndex)
        if (!shotId) return
        const speakerId = String(shot?.speaker_id || '').trim() || NARRATOR_ROLE_ID
        next[shotId] = {
          voiceContent: String(shot?.voice_content || ''),
          speakerId,
          speakerName: String(shot?.speaker_name || '').trim()
            || shotSpeakerNameById.get(speakerId)
            || getRoleName(speakerId, normalizedContentRoles)
            || '讲述者',
        }
      })
      const prevKeys = Object.keys(prev)
      const nextKeys = Object.keys(next)
      if (
        prevKeys.length === nextKeys.length
        && nextKeys.every((key) => {
          const prevDraft = prev[key]
          const nextDraft = next[key]
          return prevDraft
            && nextDraft
            && prevDraft.voiceContent === nextDraft.voiceContent
            && prevDraft.speakerId === nextDraft.speakerId
            && prevDraft.speakerName === nextDraft.speakerName
        })
      ) {
        return prev
      }
      return next
    })
  }, [normalizedContentRoles, resolveShotId, shotSpeakerNameById, shots])

  useEffect(() => {
    setFrameDescDrafts((prev) => {
      const next: Record<number, string> = {}
      for (let shotIndex = 0; shotIndex < Math.max(shots.length, frameShots.length); shotIndex += 1) {
        next[shotIndex] = String(
          shots[shotIndex]?.first_frame_description
          || frameShots[shotIndex]?.first_frame_description
          || ''
        )
      }
      const prevKeys = Object.keys(prev)
      const nextKeys = Object.keys(next)
      if (
        prevKeys.length === nextKeys.length
        && nextKeys.every((key) => prev[Number(key)] === next[Number(key)])
      ) {
        return prev
      }
      return next
    })
    const nextSubmitted: Record<number, string> = {}
    for (let shotIndex = 0; shotIndex < Math.max(shots.length, frameShots.length); shotIndex += 1) {
      nextSubmitted[shotIndex] = String(
        shots[shotIndex]?.first_frame_description
        || frameShots[shotIndex]?.first_frame_description
        || ''
      )
    }
    lastSubmittedFrameDescRef.current = nextSubmitted
  }, [frameDescSavedSignature, frameShots, shots])

  useEffect(() => {
    setVideoDescDrafts((prev) => {
      const next: Record<number, string> = {}
      for (let shotIndex = 0; shotIndex < shots.length; shotIndex += 1) {
        next[shotIndex] = String(shots[shotIndex]?.video_prompt || '')
      }
      const prevKeys = Object.keys(prev)
      const nextKeys = Object.keys(next)
      if (
        prevKeys.length === nextKeys.length
        && nextKeys.every((key) => prev[Number(key)] === next[Number(key)])
      ) {
        return prev
      }
      return next
    })
    const nextSubmitted: Record<number, string> = {}
    for (let shotIndex = 0; shotIndex < shots.length; shotIndex += 1) {
      nextSubmitted[shotIndex] = String(shots[shotIndex]?.video_prompt || '')
    }
    lastSubmittedVideoDescRef.current = nextSubmitted
  }, [shots, videoDescSavedSignature])

  useEffect(() => () => {
    Object.values(shotAutoSaveTimersRef.current).forEach((timerId) => {
      window.clearTimeout(timerId)
    })
    Object.values(frameDescAutoSaveTimersRef.current).forEach((timerId) => {
      window.clearTimeout(timerId)
    })
    Object.values(videoDescAutoSaveTimersRef.current).forEach((timerId) => {
      window.clearTimeout(timerId)
    })
  }, [])
  const hasGeneratingShot = hasAnyGeneratingShot
  const isSingleShotRun = runningShotIndex !== undefined

  const isAudioStageRunning = runningStage === 'audio'
  const isShotScopedAudioRun = isSingleShotRun
  const isFrameStageRunning = isStageRunningWithFallback({
    runningStage,
    targetStage: 'frame',
    fallbackStageStatus: frameStageStatus,
    hasGeneratingShot: hasGeneratingShot,
  })
  const isOtherStageRunningForFrame = !!runningStage && runningStage !== 'frame'
  const isScriptStageRunning = runningStage === 'storyboard'
  const isOtherStageRunningForVideoDesc = !!runningStage && runningStage !== 'storyboard'
  const isFirstFrameDescStageRunning = runningStage === 'first_frame_desc'
  const isOtherStageRunningForFirstFrameDesc = !!runningStage && runningStage !== 'first_frame_desc'
  const isVideoStageRunning = isStageRunningWithFallback({
    runningStage,
    targetStage: 'video',
    fallbackStageStatus: videoStageStatus,
    hasGeneratingShot: hasGeneratingShot,
  })
  const isOtherStageRunningForVideo = !!runningStage && !isVideoStageRunning
  const shotCount = Math.max(
    shots.length,
    audioShots.length,
    frameShots.length,
    videoShots.length
  )
  const hasAnyFrameImage = frameShots.some((shot) => !!String(shot?.first_frame_url || '').trim())
  const hasAnyAudio = audioShots.some((shot) => !!String(shot?.audio_url || '').trim())
  const hasAnyVideo = videoShots.some((shot) => !!String(shot?.video_url || '').trim())
  const hasAnyShotContent =
    shots.some((shot) => {
      const voiceContent = String(shot?.voice_content || '').trim()
      const videoPrompt = String(shot?.video_prompt || '').trim()
      const firstFrameDesc = String(shot?.first_frame_description || '').trim()
      return !!voiceContent || !!videoPrompt || !!firstFrameDesc
    })
    || audioShots.some((shot) => !!String(shot?.audio_url || '').trim())
    || frameShots.some((shot) => {
      const frameUrl = String(shot?.first_frame_url || '').trim()
      const frameDesc = String(shot?.first_frame_description || '').trim()
      return !!frameUrl || !!frameDesc
    })
    || videoShots.some((shot) => !!String(shot?.video_url || '').trim())
  const isAnyClearActionRunning =
    isClearingAllAudio || isClearingAllFrameImages || isClearingAllVideos || isClearingAllShotContent || isSmartMergingShots
  const disableBulkActions = !!runningStage || isAnyClearActionRunning
  const smartMergeReady =
    shotCount >= 2
    && shots.length >= 2
    && shots.every((shot) => !!String(shot?.voice_content || '').trim())
    && shots.every((shot) => !!String(shot?.video_prompt || '').trim())
    && audioShots.length >= shots.length
    && shots.every((_, shotIndex) => {
      const audioShot = audioShots[shotIndex]
      return (
        !!String(audioShot?.audio_url || '').trim()
        && typeof audioShot?.duration === 'number'
        && Number.isFinite(audioShot.duration)
        && audioShot.duration > 0
      )
    })
  const totalScriptChars = useMemo(() => {
    const storyboardText = shots
      .map((shot) => String(shot?.voice_content || '').trim())
      .filter(Boolean)
      .join('')
    return countScriptChars(storyboardText)
  }, [shots])
  const totalAudioDurationSeconds = useMemo(() => {
    return audioShots.reduce((sum, shot) => {
      const audioUrl = String(shot?.audio_url || '').trim()
      const duration = Number(shot?.duration)
      if (!audioUrl || !Number.isFinite(duration) || duration <= 0) {
        return sum
      }
      return sum + duration
    }, 0)
  }, [audioShots])
  const isDuoPodcastMode = shotsScriptMode === 'duo_podcast'
  const defaultCompactAspectRatio = 9 / 16
  const dominantCompactAspectRatio = useMemo(() => {
    const compactShotCount = Math.max(shots.length, videoShots.length)
    const ratioFrequency = new Map<string, { count: number; ratio: number }>()

    for (let shotIndex = 0; shotIndex < compactShotCount; shotIndex += 1) {
      const videoUrl = String(videoShots[shotIndex]?.video_url || '').trim()
      if (!videoUrl) continue
      const shotId = resolveShotId(shots[shotIndex], shotIndex)
      const ratio = videoAspectByShot[shotId]
      if (!(Number.isFinite(ratio) && ratio > 0)) continue

      const roundedRatio = Math.round(ratio * 100) / 100
      const bucket = roundedRatio.toFixed(2)
      const current = ratioFrequency.get(bucket)
      if (current) {
        current.count += 1
      } else {
        ratioFrequency.set(bucket, { count: 1, ratio: roundedRatio })
      }
    }

    let mostCommonRatio = defaultCompactAspectRatio
    let maxCount = 0
    ratioFrequency.forEach((item) => {
      if (item.count > maxCount) {
        maxCount = item.count
        mostCommonRatio = item.ratio
      }
    })
    return mostCommonRatio
  }, [defaultCompactAspectRatio, resolveShotId, shots, videoAspectByShot, videoShots])

  const handleVideoMetadataLoaded = useCallback(
    (shotId: string, event: React.SyntheticEvent<HTMLVideoElement>) => {
      const { videoWidth, videoHeight } = event.currentTarget
      if (!(videoWidth > 0 && videoHeight > 0)) return
      const ratio = videoWidth / videoHeight
      if (!(Number.isFinite(ratio) && ratio > 0)) return
      setVideoAspectByShot((prev) => {
        const current = prev[shotId]
        if (Number.isFinite(current) && Math.abs((current || 0) - ratio) < 0.01) {
          return prev
        }
        return {
          ...prev,
          [shotId]: ratio,
        }
      })
    },
    []
  )

  const renderCompactMode = () => {
    const compactShotCount = Math.max(shots.length, videoShots.length)
    if (compactShotCount <= 0) {
      return (
        <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
          暂无分镜，先执行「生成分镜」
        </div>
      )
    }

    return (
      <div className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-3">
        {Array.from({ length: compactShotCount }).map((_, shotIndex) => {
          const currentShot = shots[shotIndex]
          const currentVideo = videoShots[shotIndex]
          const shotId = resolveShotId(currentShot, shotIndex)
          const compactSpeakerId = String(currentShot?.speaker_id || '').trim() || NARRATOR_ROLE_ID
          const compactSpeakerName = String(currentShot?.speaker_name || '').trim()
            || shotSpeakerNameById.get(compactSpeakerId)
            || getRoleName(compactSpeakerId, normalizedContentRoles)
            || '讲述者'
          const voiceContent = String(currentShot?.voice_content || '').trim()
          const videoUrl = String(currentVideo?.video_url || '').trim()
          const isVideoActivated = !!activatedVideoByShot[shotId]
          const videoAspectRatio = (
            typeof currentVideo?.width === 'number'
            && typeof currentVideo?.height === 'number'
            && currentVideo.width > 0
            && currentVideo.height > 0
          )
            ? currentVideo.width / currentVideo.height
            : undefined
          const selfRatio = videoAspectByShot[shotId]
          const cardAspectRatio = Number.isFinite(selfRatio) && (selfRatio || 0) > 0
            ? Number(selfRatio)
            : (videoAspectRatio && videoAspectRatio > 0
              ? videoAspectRatio
              : dominantCompactAspectRatio
            )

          return (
            <Card key={`compact_${shotId}_${shotIndex}`} className="py-0">
              <CardContent className="p-3 space-y-3">
                <div className="flex items-center justify-between">
                  <Badge variant="outline">分镜 {shotIndex + 1}</Badge>
                  <span className="text-xs text-muted-foreground line-clamp-1">
                    {compactSpeakerName}
                  </span>
                </div>
                <div className="rounded-md border bg-muted/20 p-2">
                  <div
                    className={cn(
                      'w-full overflow-hidden rounded',
                      videoUrl
                        ? 'bg-black/5'
                        : 'border border-dashed text-xs text-muted-foreground'
                    )}
                    style={{ aspectRatio: cardAspectRatio }}
                  >
                    {videoUrl ? (
                      <LazyMount
                        className="h-full w-full"
                        placeholder={
                          <div className="flex h-full w-full items-center justify-center text-xs text-muted-foreground">
                            滚动到可视区域后显示封面
                          </div>
                        }
                      >
                        <DeferredVideoPreview
                          videoUrl={videoUrl}
                          activated={isVideoActivated}
                          onActivate={() => handleActivateVideoPreview(shotId)}
                          className="h-full w-full"
                          videoClassName="h-full w-full rounded object-contain bg-black"
                          posterClassName="h-full w-full"
                          onLoadedMetadata={(event) => handleVideoMetadataLoaded(shotId, event)}
                        />
                      </LazyMount>
                    ) : (
                      <div className="flex h-full w-full items-center justify-center">
                        暂无视频
                      </div>
                    )}
                  </div>
                </div>
                <p className="min-h-[56px] whitespace-pre-wrap rounded-md bg-muted/40 p-2 text-xs leading-5">
                  {voiceContent || '空白分镜'}
                </p>
              </CardContent>
            </Card>
          )
        })}
      </div>
    )
  }

  const renderFrameCard = (params: {
    shotIndex: number
    hasScript: boolean
    hasVideoPrompt: boolean
    hasFrameDesc: boolean
    firstFrameDescriptionDraft: string
    selectedFrameReferenceIds: string[]
    selectedFrameReferences: Reference[]
    hasFrameImage: boolean
    frameImageUrl?: string
    isCurrentFirstFrameDescGenerating: boolean
    isCurrentFrameGenerating: boolean
    isLocalFrameDeleting: boolean
    isLocalFrameRegenerating: boolean
    isLocalFrameUploading: boolean
    currentFrameProgress: number
    frameProgressText: string
    isFrameModelDownloading: boolean
    isDuoFirstShot: boolean
    isDuoNonFirstShot: boolean
    isDuoFirstShotWithImage: boolean
    className?: string
  }) => (
    <Card className={cn("py-0", params.className)}>
      <CardContent className="p-4 space-y-4">
        <div className="flex items-center justify-between gap-3">
          <h4 className="text-sm font-medium flex items-center gap-2">
            <ImageIcon className="h-4 w-4" />
            首帧图
          </h4>
          {params.isDuoFirstShotWithImage && onReuseFirstFrameToOthers && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 px-2"
              onClick={handleReuseFirstFrameToOthers}
              disabled={
                isReusingFirstFrame
                || params.isLocalFrameRegenerating
                || params.isCurrentFrameGenerating
                || isOtherStageRunningForFrame
              }
            >
              <Wand2 className={cn("h-3 w-3 mr-1", isReusingFirstFrame && "animate-spin")} />
              {isReusingFirstFrame ? '复用中...' : '复用到其他分镜'}
            </Button>
          )}
        </div>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 xl:items-start">
          {!params.isDuoNonFirstShot ? (
            <div className="space-y-4">
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <h5 className="text-xs font-medium text-muted-foreground">描述</h5>
                  <div className="flex items-center gap-1">
                    {onGenerateFrameDescription && params.hasScript && (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 px-2"
                        onClick={() => handleGenerateFrameDesc(params.shotIndex)}
                        disabled={
                          isGeneratingFrameDesc
                          || params.isCurrentFirstFrameDescGenerating
                          || isOtherStageRunningForFirstFrameDesc
                        }
                      >
                        <RefreshCw
                          className={cn(
                            "h-3 w-3 mr-1",
                            (isGeneratingFrameDesc || params.isCurrentFirstFrameDescGenerating) && "animate-spin"
                          )}
                        />
                        {(isGeneratingFrameDesc || params.isCurrentFirstFrameDescGenerating)
                          ? '生成中...'
                          : (params.hasFrameDesc ? '重新生成' : '生成')}
                      </Button>
                    )}
                  </div>
                </div>
                <Textarea
                  value={params.firstFrameDescriptionDraft}
                  onChange={(event) => {
                    const nextValue = event.target.value
                    setFrameDescDrafts((prev) => ({ ...prev, [params.shotIndex]: nextValue }))
                    const timerId = frameDescAutoSaveTimersRef.current[params.shotIndex]
                    if (timerId) {
                      window.clearTimeout(timerId)
                    }
                    frameDescAutoSaveTimersRef.current[params.shotIndex] = window.setTimeout(() => {
                      void handleSaveFrameDesc(params.shotIndex, nextValue)
                    }, 800)
                  }}
                  onBlur={() => void flushAutoSaveFrameDesc(params.shotIndex)}
                  placeholder={
                    params.hasVideoPrompt
                      ? '输入首帧图描述，或点击右上角生成'
                      : '请先生成视频描述，再填写或生成首帧图描述'
                  }
                  className={SHOT_EDITOR_TEXTAREA_CLASS}
                />
                {params.isDuoFirstShot && (
                  <p className="text-xs text-amber-600">
                    首帧描述由系统按固定模板生成；如需调整画面，请修改首帧参考图或对应外观描述。
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <h5 className="text-xs font-medium text-muted-foreground">参考</h5>
                  {onSaveFrameReferences && (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 px-2"
                          disabled={isSavingFrameReferences || references.length === 0}
                        >
                          <Plus className="h-3 w-3 mr-1" />
                          添加参考
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-52">
                        {references.length === 0 ? (
                          <DropdownMenuItem disabled>暂无可添加参考</DropdownMenuItem>
                        ) : (
                          references.map((reference) => {
                            const referenceId = String(reference.id)
                            const exists = params.selectedFrameReferenceIds.includes(referenceId)
                            return (
                              <DropdownMenuItem
                                key={referenceId}
                                disabled={exists || isSavingFrameReferences}
                                onSelect={(event) => {
                                  event.preventDefault()
                                  if (exists || isSavingFrameReferences) return
                                  void handleSaveFrameReferences(params.shotIndex, [
                                    ...params.selectedFrameReferenceIds,
                                    referenceId,
                                  ])
                                }}
                              >
                                <span>{reference.name}</span>
                                {exists && (
                                  <span className="ml-auto text-xs text-muted-foreground">已添加</span>
                                )}
                              </DropdownMenuItem>
                            )
                          })
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  )}
                </div>
                {params.selectedFrameReferences.length > 0 ? (
                  <div className="space-y-2">
                    <div className={cn(
                      "relative rounded-lg p-2 transition",
                      !isFrameReferenceEffective && "overflow-hidden border border-dashed border-amber-400/60 bg-amber-50/40 dark:bg-amber-500/10"
                    )}>
                      <div className={cn(
                        "flex flex-wrap gap-2 transition",
                        !isFrameReferenceEffective && "grayscale opacity-60"
                      )}>
                        {params.selectedFrameReferences.map((reference) => {
                          const referenceId = String(reference.id)
                          return (
                            <div
                              key={referenceId}
                              className="group relative inline-flex items-center rounded-full border bg-muted px-3 py-1 text-xs"
                            >
                              <span>{reference.name}</span>
                              {onSaveFrameReferences && (
                                <button
                                  type="button"
                                  className={cn(
                                    "absolute -right-1 -top-1 hidden h-4 w-4 items-center justify-center rounded-full border bg-background text-muted-foreground transition-colors",
                                    "group-hover:flex hover:text-destructive"
                                  )}
                                  onClick={() => {
                                    if (isSavingFrameReferences) return
                                    void handleSaveFrameReferences(
                                      params.shotIndex,
                                      params.selectedFrameReferenceIds.filter((id) => id !== referenceId)
                                    )
                                  }}
                                  aria-label={`删除参考 ${reference.name}`}
                                  title={`删除参考 ${reference.name}`}
                                >
                                  <X className="h-3 w-3" />
                                </button>
                              )}
                            </div>
                          )
                        })}
                      </div>
                      {!isFrameReferenceEffective && (
                        <>
                          <div className="pointer-events-none absolute inset-0 bg-[repeating-linear-gradient(-45deg,rgba(245,158,11,0.14),rgba(245,158,11,0.14)_8px,transparent_8px,transparent_16px)]" />
                          <div className="absolute right-2 top-2">
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Badge variant="secondary" className="cursor-default border border-amber-300/70 bg-amber-100 text-amber-800">
                                  未生效
                                </Badge>
                              </TooltipTrigger>
                              <TooltipContent side="top">
                                <p className="text-xs">当前仅用于预览，不参与首帧图生成</p>
                              </TooltipContent>
                            </Tooltip>
                          </div>
                        </>
                      )}
                    </div>
                    {!isFrameReferenceEffective && (
                      <p className="text-xs text-amber-600">
                        开启「保持参考一致性」后生效
                      </p>
                    )}
                  </div>
                ) : (
                  <div className="bg-muted/30 p-3 rounded-lg border-2 border-dashed border-muted-foreground/20">
                    <p className="text-sm text-muted-foreground text-center">未关联参考</p>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <h5 className="text-xs font-medium text-muted-foreground">描述</h5>
                </div>
                <div className="rounded-lg border-2 border-dashed border-muted-foreground/20 bg-muted/30 p-3">
                  <p className="text-sm text-muted-foreground text-center">
                    双人播客一镜到底下，后续分镜首帧图优先复用首个分镜或截取上一个分镜尾帧。
                  </p>
                </div>
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <h5 className="text-xs font-medium text-muted-foreground">参考</h5>
                </div>
                <div className="rounded-lg border-2 border-dashed border-muted-foreground/20 bg-muted/30 p-3">
                  <p className="text-sm text-muted-foreground text-center">
                    当前分镜不单独维护首帧描述与参考，等待复用结果即可。
                  </p>
                </div>
              </div>
            </div>
          )}

          <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h5 className="text-xs font-medium text-muted-foreground">图片</h5>
            <div className="flex items-center gap-1">
              {onDeleteFrameImage && params.hasFrameImage && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2 hover:text-destructive hover:bg-destructive/10"
                  onClick={() => handleDeleteFrameImage(params.shotIndex)}
                  disabled={params.isLocalFrameDeleting || params.isLocalFrameRegenerating || isUploadingFrame}
                >
                  <Trash2 className="h-3 w-3 mr-1" />
                  删除
                </Button>
              )}
              {onRegenerateFrameImage && params.hasFrameDesc && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2"
                  onClick={() => handleRegenerateFrameImage(params.shotIndex)}
                  disabled={params.isLocalFrameRegenerating || params.isCurrentFrameGenerating || isOtherStageRunningForFrame}
                >
                  <RefreshCw className={cn("h-3 w-3 mr-1", (params.isLocalFrameRegenerating || params.isCurrentFrameGenerating) && "animate-spin")} />
                  {(params.isLocalFrameRegenerating || params.isCurrentFrameGenerating) ? '生成中...' : (params.hasFrameImage ? '重新生成' : '生成')}
                </Button>
              )}
              {onUploadFrameImage && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2"
                  onClick={() => handleFrameImageClick(params.shotIndex)}
                  disabled={isUploadingFrame}
                >
                  <Upload className="h-3 w-3 mr-1" />
                  上传
                </Button>
              )}
            </div>
          </div>
          <div className="rounded-lg border border-muted-foreground/20 bg-muted/20 p-3">
            {params.hasFrameImage ? (
              <div
                className={cn(
                  "flex justify-center relative group",
                  onUploadFrameImage && "cursor-pointer"
                )}
                onClick={() => handleFrameImageClick(params.shotIndex)}
              >
                <LazyMount
                  placeholder={
                    <div className="flex h-64 w-full items-center justify-center rounded-lg bg-muted/40 text-sm text-muted-foreground">
                      滚动到可视区域后加载图片
                    </div>
                  }
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={params.frameImageUrl}
                    alt="首帧图"
                    loading="lazy"
                    decoding="async"
                    className="max-h-64 w-auto max-w-full rounded-lg object-contain"
                    onLoad={() => {
                      setBrokenFrameImageByShot((prev) => {
                        if (prev[params.shotIndex] === undefined) return prev
                        const next = { ...prev }
                        delete next[params.shotIndex]
                        return next
                      })
                    }}
                    onError={() => {
                      const failedRaw = String(frameShots[params.shotIndex]?.first_frame_url || '').trim()
                      if (!failedRaw) return
                      setBrokenFrameImageByShot((prev) => {
                        if (prev[params.shotIndex] === failedRaw) return prev
                        return { ...prev, [params.shotIndex]: failedRaw }
                      })
                    }}
                  />
                </LazyMount>
                {onUploadFrameImage && !isUploadingFrame && !params.isLocalFrameRegenerating && !params.isLocalFrameDeleting && (
                  <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-black/30 rounded-lg">
                    <div className="text-white text-sm flex items-center gap-2">
                      <Upload className="h-5 w-5" />
                      点击上传新图片
                    </div>
                  </div>
                )}
                {(params.isLocalFrameUploading || params.isLocalFrameRegenerating || params.isLocalFrameDeleting || params.isCurrentFrameGenerating) && (
                  <div className="absolute inset-0 flex items-center justify-center bg-black/50 rounded-lg">
                    <div className="text-white text-sm flex flex-col items-center gap-2">
                      <div className="flex items-center gap-2">
                        <RefreshCw className="h-5 w-5 animate-spin" />
                        {params.isLocalFrameUploading ? '上传中...' : params.isLocalFrameDeleting ? '删除中...' : params.frameProgressText}
                      </div>
                      {!params.isLocalFrameUploading && !params.isLocalFrameDeleting && (
                        <>
                          <div className="w-32 h-2 bg-white/20 rounded-full overflow-hidden">
                            <div
                              className="h-full bg-white transition-all duration-300"
                              style={{ width: `${params.currentFrameProgress}%` }}
                            />
                          </div>
                          <div className="text-xs text-white/80">{params.currentFrameProgress}%</div>
                        </>
                      )}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div
                className={cn(
                  "aspect-video bg-muted/30 rounded-lg border-2 border-dashed border-muted-foreground/20 flex items-center justify-center",
                  onUploadFrameImage && "cursor-pointer hover:bg-muted/50 transition-colors"
                )}
                onClick={() => handleFrameImageClick(params.shotIndex)}
              >
                {params.isCurrentFrameGenerating ? (
                  <div className="text-center space-y-3">
                    <RefreshCw
                      className={cn(
                        "text-primary mx-auto animate-spin",
                        params.isFrameModelDownloading ? "h-6 w-6" : "h-8 w-8"
                      )}
                    />
                    <p className="text-sm text-muted-foreground">{params.frameProgressText}</p>
                    <div className="w-32 h-2 bg-muted rounded-full overflow-hidden mx-auto">
                      <div
                        className="h-full bg-primary transition-all duration-300"
                        style={{ width: `${params.currentFrameProgress}%` }}
                      />
                    </div>
                  </div>
                ) : params.isLocalFrameUploading ? (
                  <div className="text-center">
                    <RefreshCw className="h-8 w-8 text-muted-foreground mx-auto mb-2 animate-spin" />
                    <p className="text-sm text-muted-foreground">上传中...</p>
                  </div>
                ) : (
                  <div className="text-center">
                    <ImageIcon className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
                    <p className="text-sm text-muted-foreground">
                      {params.isDuoNonFirstShot
                        ? '等待截取上一个分镜尾帧或使用「生成并复用首帧图」生成图片'
                        : (onUploadFrameImage ? '点击上传或使用「生成首帧图」生成图片' : '点击「生成首帧图」生成图片')}
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )

  return (
    <div className="h-full flex flex-col">
      <div className="shrink-0 border-b bg-background/95 px-6 py-3 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <div className="flex items-center justify-between gap-4">
          <div className="flex min-w-0 flex-wrap items-center gap-2.5">
            <div className="flex min-w-[156px] items-center justify-between gap-4 rounded-xl border border-border/60 bg-muted/30 px-3 py-1.5 shadow-sm">
              <div className="text-[12px] font-medium text-muted-foreground">
                分镜总数量
              </div>
              <div className="text-base font-semibold tabular-nums text-foreground">
                {shotCount}
              </div>
            </div>
            <div className="flex min-w-[156px] items-center justify-between gap-4 rounded-xl border border-border/60 bg-muted/30 px-3 py-1.5 shadow-sm">
              <div className="text-[12px] font-medium text-muted-foreground">
                文案总字数
              </div>
              <div className="text-base font-semibold tabular-nums text-foreground">
                {totalScriptChars}
              </div>
            </div>
            <div className="flex min-w-[156px] items-center justify-between gap-4 rounded-xl border border-border/60 bg-muted/30 px-3 py-1.5 shadow-sm">
              <div className="text-[12px] font-medium text-muted-foreground">
                音频总时长
              </div>
              <div className="text-base font-semibold tabular-nums text-foreground">
                {formatStatsDuration(totalAudioDurationSeconds)}
              </div>
            </div>
          </div>
          <div className="flex items-center justify-end gap-2">
          {onSmartMergeShots && (
            <div className="flex items-center gap-1">
              <Button
                variant="outline"
                size="sm"
                className="h-8"
                onClick={() => void handleSmartMergeShots()}
                disabled={disableBulkActions || !smartMergeReady}
              >
                <Wand2 className="h-3.5 w-3.5 mr-1.5" />
                {isSmartMergingShots ? '合并中...' : '智能合并分镜'}
              </Button>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-input bg-background text-muted-foreground transition-colors hover:text-foreground disabled:pointer-events-none"
                    disabled={disableBulkActions}
                    aria-label="智能合并分镜说明"
                  >
                    <CircleHelp className="h-4 w-4" />
                  </button>
                </TooltipTrigger>
                <TooltipContent side="bottom" align="end" className="max-w-xs text-xs leading-5">
                  会基于当前文案、音频时长、视频描述、参考和当前视频模型单次时长上限，智能重构为更少分镜。目的是减少视频生成调用次数并提升一致性。执行后会清空现有分镜音频、首帧描述、首帧图和视频内容。
                </TooltipContent>
              </Tooltip>
            </div>
          )}
          {onClearAllAudio && (
            <Button
              variant="outline"
              size="sm"
              className="h-8"
              onClick={() => void handleClearAllAudio()}
              disabled={disableBulkActions || !hasAnyAudio}
            >
              <Trash2 className="h-3.5 w-3.5 mr-1.5" />
              {isClearingAllAudio ? '清空中...' : '清空音频'}
            </Button>
          )}
          {onClearAllFrameImages && (
            <Button
              variant="outline"
              size="sm"
              className="h-8"
              onClick={() => void handleClearAllFrameImages()}
              disabled={disableBulkActions || !hasAnyFrameImage}
            >
              <Trash2 className="h-3.5 w-3.5 mr-1.5" />
              {isClearingAllFrameImages ? '清空中...' : '清空首帧图'}
            </Button>
          )}
          {onClearAllVideos && (
            <Button
              variant="outline"
              size="sm"
              className="h-8"
              onClick={() => void handleClearAllVideos()}
              disabled={disableBulkActions || !hasAnyVideo}
            >
              <Trash2 className="h-3.5 w-3.5 mr-1.5" />
              {isClearingAllVideos ? '清空中...' : '清空视频'}
            </Button>
          )}
          {onClearAllShotContent && (
            <Button
              variant="outline"
              size="sm"
              className="h-8 text-destructive hover:text-destructive"
              onClick={() => void handleClearAllShotContent()}
              disabled={disableBulkActions || !hasAnyShotContent}
            >
              <Trash2 className="h-3.5 w-3.5 mr-1.5" />
              {isClearingAllShotContent ? '清空中...' : '清空所有'}
            </Button>
          )}
          <Button
            variant={compactMode ? 'default' : 'outline'}
            size="sm"
            className="h-8"
            onClick={handleToggleCompactMode}
          >
            <LayoutGrid className="h-3.5 w-3.5 mr-1.5" />
            {compactMode ? '紧凑模式已开启' : '紧凑模式'}
          </Button>
          </div>
        </div>
      </div>

      <input
        ref={frameFileInputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="hidden"
        onChange={(e) => {
          if (frameUploadShotIndex === null) {
            if (frameFileInputRef.current) frameFileInputRef.current.value = ''
            return
          }
          void handleFrameFileChange(e, frameUploadShotIndex)
        }}
      />

      <div className="flex-1 overflow-auto p-6 space-y-4">

        {compactMode ? renderCompactMode() : (
          shotCount <= 0 ? (
            <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
              暂无分镜，先执行「生成分镜」
            </div>
          ) : Array.from({ length: shotCount }).map((_, shotIndex) => {
          const currentShot = shots[shotIndex]
          const currentAudio = audioShots[shotIndex]
          const currentAudioUrl = String(currentAudio?.audio_url || '').trim()
          const currentFrame = frameShots[shotIndex]
          const currentVideo = videoShots[shotIndex]

          const voiceContent = currentShot?.voice_content || ''
          const firstFrameDescription =
            currentShot?.first_frame_description
            || currentFrame?.first_frame_description
            || ''
          const videoPrompt = currentShot?.video_prompt || ''
          const hasVideoPrompt = !!videoPrompt.trim()

          const hasScript = !!voiceContent
          const hasAudio = !!currentAudioUrl
          const hasFrameDesc = !!firstFrameDescription
          const frameImageUrlRaw = currentFrame?.first_frame_url
          const failedFrameUrl = brokenFrameImageByShot[shotIndex]
          const hasFrameImage = !!frameImageUrlRaw && failedFrameUrl !== frameImageUrlRaw
          const frameImageUrl = frameImageUrlRaw || undefined

          const currentShotKey = String(shotIndex)
          const currentShotGeneratingProgress = generatingShots?.[currentShotKey]?.progress
          const isTargetShot = isSingleShotRun ? runningShotIndex === shotIndex : true

          const audioGenerationState = isShotScopedAudioRun
            ? resolveShotGeneratingState({
                isStageRunning: isAudioStageRunning,
                isSingleShotRun: isSingleShotRun,
                isTargetShot: isTargetShot,
                hasShotState: currentShotGeneratingProgress !== undefined,
                hasGeneratingShot: hasGeneratingShot,
              })
            : { isGenerating: false, isStarting: false }
          const isCurrentAudioGenerating = audioGenerationState.isGenerating
          const {
            progress: currentAudioProgress,
            progressText: audioProgressText,
          } = resolveRuntimeDisplay({
            isGenerating: isCurrentAudioGenerating,
            isStarting: audioGenerationState.isStarting,
            shotProgress: currentShotGeneratingProgress,
            stageProgress: progress,
            progressMessage: isAudioStageRunning ? progressMessage : undefined,
          })

          const isDuoFrameBatchFallbackGenerating =
            isDuoPodcastMode
            && isFrameStageRunning
            && !isSingleShotRun
            && !hasGeneratingShot
          const frameHasShotState =
            currentShotGeneratingProgress !== undefined || isDuoFrameBatchFallbackGenerating
          const frameGenerationState = resolveCurrentItemGenerationState({
            isStageRunning: isFrameStageRunning,
            isSingleItemRun: isSingleShotRun,
            isTargetItem: isTargetShot,
            hasItemState: frameHasShotState,
            hasGeneratingItem: hasGeneratingShot,
            batchMode: 'active_only',
          })
          const isCurrentFrameGenerating = frameGenerationState.isGenerating
          const isCurrentSingleTakeFrameExtracting =
            isVideoStageRunning
            && singleTakeEnabled
            && useFirstFrameRef
            && shotIndex > 0
            && !hasFrameImage
            && (
              isSingleShotRun
                ? isTargetShot
                : currentShotGeneratingProgress !== undefined
            )
          const displayFrameGenerating = isCurrentFrameGenerating || isCurrentSingleTakeFrameExtracting
          const {
            progress: currentFrameProgress,
            progressText: frameProgressText,
            isModelDownloading: isFrameModelDownloading,
          } = resolveRuntimeDisplay({
            isGenerating: displayFrameGenerating,
            isStarting: frameGenerationState.isStarting,
            shotProgress: currentShotGeneratingProgress,
            stageProgress: progress,
            progressMessage: isFrameStageRunning ? progressMessage : undefined,
          })
          const displayFrameProgressText = isCurrentSingleTakeFrameExtracting
            ? '截取中...'
            : frameProgressText
          const displayFrameProgress = isCurrentSingleTakeFrameExtracting
            ? Math.max(
                currentShotGeneratingProgress ?? progress ?? 0,
                3
              )
            : currentFrameProgress
          const displayIsFrameModelDownloading = isCurrentSingleTakeFrameExtracting
            ? false
            : isFrameModelDownloading

          const currentShotId = resolveShotId(currentShot, shotIndex)
          const hasVideo = !!currentVideo?.video_url
          const isVideoActivated = !!activatedVideoByShot[currentShotId]
          const videoAspectRatio = (
            typeof currentVideo?.width === 'number'
            && typeof currentVideo?.height === 'number'
            && currentVideo.width > 0
            && currentVideo.height > 0
          )
            ? currentVideo.width / currentVideo.height
            : undefined
          const measuredVideoAspectRatio = videoAspectByShot[currentShotId]
          const resolvedVideoAspectRatio = Number.isFinite(measuredVideoAspectRatio) && measuredVideoAspectRatio > 0
            ? measuredVideoAspectRatio
            : videoAspectRatio
          const previewAspectRatio = resolvedVideoAspectRatio && resolvedVideoAspectRatio > 0
            ? resolvedVideoAspectRatio
            : (9 / 16)
          const normalPreviewMaxWidth = resolvedVideoAspectRatio && resolvedVideoAspectRatio > 0
            ? Math.max(96, Math.round(resolvedVideoAspectRatio * 256))
            : 144
          const selectedFrameReferenceIds = Array.from(
            new Set(
              (Array.isArray(currentShot?.first_frame_reference_slots)
                ? currentShot.first_frame_reference_slots
                : []
              )
                .map((referenceItem) => String(referenceItem?.id || '').trim())
                .filter((id) => !!id)
            )
          )
          const selectedFrameReferences = selectedFrameReferenceIds
            .map((id) => references.find((c) => String(c.id) === id))
            .filter((c): c is Reference => !!c)
          const selectedVideoReferenceIds = Array.from(
            new Set(
              (Array.isArray(currentShot?.video_reference_slots)
                ? currentShot.video_reference_slots
                : []
              )
                .map((referenceItem) => String(referenceItem?.id || '').trim())
                .filter((id) => !!id)
            )
          )
          const selectedVideoReferences = selectedVideoReferenceIds
            .map((id) => references.find((c) => String(c.id) === id))
            .filter((c): c is Reference => !!c)
          const isCurrentVideoDescGenerating = isScriptStageRunning && (isSingleShotRun ? isTargetShot : true)
          const isCurrentFirstFrameDescGenerating =
            isFirstFrameDescStageRunning && (isSingleShotRun ? isTargetShot : true)
          const videoHasShotState = currentShotGeneratingProgress !== undefined
          const videoGenerationState = resolveCurrentItemGenerationState({
            isStageRunning: isVideoStageRunning,
            isSingleItemRun: isSingleShotRun,
            isTargetItem: isTargetShot,
            hasItemState: videoHasShotState,
            hasGeneratingItem: hasGeneratingShot,
            batchMode: 'active_only',
          })
          const isCurrentVideoGenerating = videoGenerationState.isGenerating
          const {
            progress: displayVideoProgress,
            runtimeMessage: videoRuntimeMessage,
            progressText: videoProgressText,
          } = resolveRuntimeDisplay({
            isGenerating: isCurrentVideoGenerating,
            isStarting: videoGenerationState.isStarting,
            shotProgress: currentShotGeneratingProgress,
            stageProgress: progress,
            progressMessage: isVideoStageRunning ? progressMessage : undefined,
          })

          const isLocalFrameRegenerating = regeneratingFrameShotIndex === shotIndex
          const isLocalFrameDeleting = deletingFrameShotIndex === shotIndex
          const isLocalFrameUploading = isUploadingFrame && frameUploadShotIndex === shotIndex
          const isLocalVideoDeleting = deletingVideoShotIndex === shotIndex
          const shotSpeakerId = String(currentShot?.speaker_id || '').trim() || NARRATOR_ROLE_ID
          const shotSpeakerName = String(currentShot?.speaker_name || '').trim()
            || shotSpeakerNameById.get(shotSpeakerId)
            || getRoleName(shotSpeakerId, normalizedContentRoles)
            || '讲述者'
          const shotDraft = currentShotId
            ? (shotDrafts[currentShotId] || {
              voiceContent: String(currentShot?.voice_content || ''),
              speakerId: shotSpeakerId,
              speakerName: shotSpeakerName || '讲述者',
            })
            : {
              voiceContent: String(currentShot?.voice_content || ''),
              speakerId: shotSpeakerId,
              speakerName: shotSpeakerName || '讲述者',
            }
          const effectiveShotSpeakerOptions = shotSpeakerNameById.has(shotDraft.speakerId)
            ? shotSpeakerOptionsBase
            : [
                ...shotSpeakerOptionsBase,
                {
                  id: shotDraft.speakerId,
                  name: shotDraft.speakerName || getRoleName(shotDraft.speakerId, normalizedContentRoles) || shotDraft.speakerId,
                },
              ]
          const effectiveShotSpeakerName = shotSpeakerNameById.get(shotDraft.speakerId)
            || shotDraft.speakerName
            || getRoleName(shotDraft.speakerId, normalizedContentRoles)
            || '讲述者'
          const canMoveUp = shotIndex > 0
          const canMoveDown = shotIndex < shotCount - 1
          const menuBeforeKey = `menu-before-${currentShotId}`
          const menuAfterKey = `menu-after-${currentShotId}`
          const menuBeforeCount = Math.max(1, Math.floor(insertCountByShot[menuBeforeKey] ?? 1))
          const menuAfterCount = Math.max(1, Math.floor(insertCountByShot[menuAfterKey] ?? 1))

          return (
            <div key={currentShotId || String(currentShot?.id || shotIndex)} className="space-y-3">
              <div className="group/shot relative rounded-xl border-2 border-border/70 bg-card/70 p-4 shadow-sm">
                <div className="absolute right-3 top-3 z-20 opacity-0 transition-opacity duration-150 group-hover/shot:opacity-100 group-focus-within/shot:opacity-100">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="outline" size="icon" className="h-8 w-8" aria-label="分镜操作菜单">
                        <MoreHorizontal className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-[280px] p-2">
                      <div className="space-y-2">
                        <div className="flex items-center gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-9 flex-1 justify-start"
                            onClick={() => void handleInsertShots(shotIndex, 'before', menuBeforeKey)}
                            disabled={!onInsertShots || !!runningStage || insertingAnchorKey === menuBeforeKey}
                          >
                            {insertingAnchorKey === menuBeforeKey ? '插入中...' : '向上插入'}
                          </Button>
                          <Input
                            value={String(menuBeforeCount)}
                            onChange={(event) => {
                              const parsed = Number.parseInt(event.target.value, 10)
                              const nextCount = Number.isFinite(parsed) ? Math.max(1, Math.min(20, parsed)) : 1
                              setInsertCountByShot((prev) => ({ ...prev, [menuBeforeKey]: nextCount }))
                            }}
                            type="number"
                            min={1}
                            max={20}
                            className="h-9 w-20"
                          />
                        </div>
                        <div className="flex items-center gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-9 flex-1 justify-start"
                            onClick={() => void handleInsertShots(shotIndex, 'after', menuAfterKey)}
                            disabled={!onInsertShots || !!runningStage || insertingAnchorKey === menuAfterKey}
                          >
                            {insertingAnchorKey === menuAfterKey ? '插入中...' : '向下插入'}
                          </Button>
                          <Input
                            value={String(menuAfterCount)}
                            onChange={(event) => {
                              const parsed = Number.parseInt(event.target.value, 10)
                              const nextCount = Number.isFinite(parsed) ? Math.max(1, Math.min(20, parsed)) : 1
                              setInsertCountByShot((prev) => ({ ...prev, [menuAfterKey]: nextCount }))
                            }}
                            type="number"
                            min={1}
                            max={20}
                            className="h-9 w-20"
                          />
                        </div>
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-9 w-full justify-start"
                          onClick={() => void handleMoveShot(currentShotId, 'up')}
                          disabled={!canMoveUp || movingShotId === currentShotId || !!runningStage || !onMoveShot}
                        >
                          <ArrowUp className="h-3.5 w-3.5 mr-1" />
                          上移
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-9 w-full justify-start"
                          onClick={() => void handleMoveShot(currentShotId, 'down')}
                          disabled={!canMoveDown || movingShotId === currentShotId || !!runningStage || !onMoveShot}
                        >
                          <ArrowDown className="h-3.5 w-3.5 mr-1" />
                          下移
                        </Button>
                        <Button
                          variant="destructive"
                          size="sm"
                          className="h-9 w-full justify-start"
                          onClick={() => void handleDeleteShotAction(currentShotId)}
                          disabled={deletingShotId === currentShotId || !!runningStage || !onDeleteShot}
                        >
                          <Trash2 className="h-3.5 w-3.5 mr-1" />
                          删除
                        </Button>
                      </div>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
                <div className="mb-3 flex items-center gap-2">
                  <Badge variant="outline">分镜 {shotIndex + 1}</Badge>
                </div>
                <div className={cn(
                  "grid grid-cols-1 gap-4",
                  "xl:grid-cols-5"
                )}>
                {/* 卡片1：口播（文案 + 音频） */}
                <Card className="py-0 xl:col-span-1">
                  <CardContent className="p-4 space-y-4">
                    <h4 className="text-sm font-medium flex items-center gap-2">
                      <FileText className="h-4 w-4" />
                      口播
                    </h4>

                    <div className="space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <h5 className="text-xs font-medium text-muted-foreground">文案</h5>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <button
                              type="button"
                              className="inline-flex h-7 items-center gap-1 rounded-full border bg-background px-3 text-[11px] font-medium text-foreground shadow-sm transition-colors hover:bg-muted"
                            >
                              <span>{effectiveShotSpeakerName}</span>
                              <ChevronDown className="h-3 w-3 text-muted-foreground" />
                            </button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="min-w-[120px]">
                            {effectiveShotSpeakerOptions.map((speaker) => (
                              <DropdownMenuItem
                                key={speaker.id}
                                onSelect={() => {
                                  const nextDraft = {
                                    ...shotDraft,
                                    speakerId: speaker.id,
                                    speakerName: String(speaker.name || getRoleName(speaker.id, normalizedContentRoles) || speaker.id),
                                  }
                                  updateShotDraft(currentShotId, nextDraft)
                                  if (shotAutoSaveTimersRef.current[currentShotId]) {
                                    window.clearTimeout(shotAutoSaveTimersRef.current[currentShotId])
                                  }
                                  shotAutoSaveTimersRef.current[currentShotId] = window.setTimeout(() => {
                                    void handleSaveShot(currentShotId, nextDraft)
                                  }, 800)
                                }}
                              >
                                {speaker.name}
                              </DropdownMenuItem>
                            ))}
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                      <div>
                        <Textarea
                          value={shotDraft.voiceContent}
                          onChange={(event) => {
                            const nextDraft = {
                              ...shotDraft,
                              voiceContent: event.target.value,
                            }
                            updateShotDraft(currentShotId, nextDraft)
                            if (shotAutoSaveTimersRef.current[currentShotId]) {
                              window.clearTimeout(shotAutoSaveTimersRef.current[currentShotId])
                            }
                            shotAutoSaveTimersRef.current[currentShotId] = window.setTimeout(() => {
                              void handleSaveShot(currentShotId, nextDraft)
                            }, 800)
                          }}
                          onBlur={() => void flushAutoSaveShot(currentShotId)}
                          placeholder="输入分镜文案..."
                          className={SHOT_EDITOR_TEXTAREA_CLASS}
                        />
                      </div>
                    </div>

                    <div className="space-y-2">
                      <h5 className="text-xs font-medium text-muted-foreground">音频</h5>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs text-muted-foreground">配音</span>
                        {onRegenerateAudio && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 px-2"
                            onClick={() => void onRegenerateAudio(shotIndex)}
                            disabled={isAudioStageRunning}
                          >
                            <RefreshCw className={cn('h-3 w-3 mr-1', isCurrentAudioGenerating && 'animate-spin')} />
                            {isCurrentAudioGenerating ? '生成中...' : (hasAudio ? '重新生成' : '生成')}
                          </Button>
                        )}
                      </div>
                      {hasAudio ? (
                        <div className="p-3 bg-muted rounded-lg space-y-2">
                          <AudioPlayer
                            src={currentAudioUrl}
                            initialDuration={typeof currentAudio?.duration === 'number' ? currentAudio.duration : 0}
                            preload="none"
                          />
                          {isCurrentAudioGenerating && (
                            <div className="space-y-1">
                              <p className="text-xs text-muted-foreground">{audioProgressText}</p>
                              <div className="w-32 h-2 bg-muted-foreground/20 rounded-full overflow-hidden">
                                <div
                                  className="h-full bg-primary transition-all duration-300"
                                  style={{ width: `${currentAudioProgress}%` }}
                                />
                              </div>
                            </div>
                          )}
                        </div>
                      ) : (
                        <div className="bg-muted/30 p-3 rounded-lg border-2 border-dashed border-muted-foreground/20 flex items-center justify-center gap-2">
                          {isCurrentAudioGenerating ? (
                            <div className="text-center space-y-3">
                              <RefreshCw className="h-6 w-6 text-primary mx-auto animate-spin" />
                              <p className="text-xs text-muted-foreground">{audioProgressText}</p>
                              <div className="w-32 h-2 bg-muted rounded-full overflow-hidden mx-auto">
                                <div
                                  className="h-full bg-primary transition-all duration-300"
                                  style={{ width: `${currentAudioProgress}%` }}
                                />
                              </div>
                            </div>
                          ) : (
                            <>
                              <Volume2 className="h-4 w-4 text-muted-foreground" />
                              <p className="text-sm text-muted-foreground">请先生成分镜，再在当前页面逐镜生成音频</p>
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  </CardContent>
                </Card>

                {renderFrameCard({
                  shotIndex,
                  hasScript,
                  hasVideoPrompt,
                  hasFrameDesc,
                  firstFrameDescriptionDraft: frameDescDrafts[shotIndex] ?? firstFrameDescription,
                  selectedFrameReferenceIds,
                  selectedFrameReferences,
                  hasFrameImage,
                  frameImageUrl,
                  isCurrentFirstFrameDescGenerating,
                  isCurrentFrameGenerating: displayFrameGenerating,
                  isLocalFrameDeleting,
                  isLocalFrameRegenerating,
                  isLocalFrameUploading,
                  currentFrameProgress: displayFrameProgress,
                  frameProgressText: displayFrameProgressText,
                  isFrameModelDownloading: displayIsFrameModelDownloading,
                  isDuoFirstShot: isDuoPodcastMode && shotIndex === 0,
                  isDuoNonFirstShot: isDuoPodcastMode && shotIndex > 0,
                  isDuoFirstShotWithImage: isDuoPodcastMode && shotIndex === 0 && hasFrameImage,
                  className: "xl:col-span-2",
                })}

                {/* 卡片3：分镜视频（描述 + 视频） */}
                <Card className="py-0 xl:col-span-2">
                  <CardContent className="p-4 space-y-4">
                    <h4 className="text-sm font-medium flex items-center gap-2">
                      <Video className="h-4 w-4" />
                      分镜视频
                    </h4>

                    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 md:items-start">
                      <div className="space-y-4 min-w-0">
                        <div className="space-y-2">
                          <div className="flex items-center justify-between">
                            <h5 className="text-xs font-medium text-muted-foreground">描述</h5>
                            <div className="flex items-center gap-1">
                              {onGenerateVideoDescription && hasScript && (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-6 px-2"
                                  onClick={() => handleGenerateVideoDesc(shotIndex)}
                                  disabled={
                                    isGeneratingVideoDesc
                                    || isCurrentVideoDescGenerating
                                    || isOtherStageRunningForVideoDesc
                                  }
                                >
                                  <RefreshCw
                                    className={cn(
                                      "h-3 w-3 mr-1",
                                      (isGeneratingVideoDesc || isCurrentVideoDescGenerating) && "animate-spin"
                                    )}
                                  />
                                  {(isGeneratingVideoDesc || isCurrentVideoDescGenerating)
                                    ? '生成中...'
                                    : (videoPrompt ? '重新生成' : '生成')}
                                </Button>
                              )}
                            </div>
                          </div>
                          <Textarea
                            value={videoDescDrafts[shotIndex] ?? videoPrompt}
                            onChange={(event) => {
                              const nextValue = event.target.value
                              setVideoDescDrafts((prev) => ({ ...prev, [shotIndex]: nextValue }))
                              const timerId = videoDescAutoSaveTimersRef.current[shotIndex]
                              if (timerId) {
                                window.clearTimeout(timerId)
                              }
                              videoDescAutoSaveTimersRef.current[shotIndex] = window.setTimeout(() => {
                                void handleSaveVideoDesc(shotIndex, nextValue)
                              }, 800)
                            }}
                            onBlur={() => void flushAutoSaveVideoDesc(shotIndex)}
                            placeholder="输入视频描述，或点击右上角生成"
                            className={SHOT_EDITOR_TEXTAREA_CLASS}
                          />
                        </div>

                        <div className="space-y-2">
                          <div className="flex items-center justify-between">
                            <h5 className="text-xs font-medium text-muted-foreground">参考</h5>
                            {onSaveVideoReferences && (
                              <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-6 px-2"
                                    disabled={isSavingVideoReferences || references.length === 0}
                                  >
                                    <Plus className="h-3 w-3 mr-1" />
                                    添加参考
                                  </Button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="end" className="w-52">
                                  {references.length === 0 ? (
                                    <DropdownMenuItem disabled>暂无可添加参考</DropdownMenuItem>
                                  ) : (
                                    references.map((reference) => {
                                      const referenceId = String(reference.id)
                                      const exists = selectedVideoReferenceIds.includes(referenceId)
                                      return (
                                        <DropdownMenuItem
                                          key={referenceId}
                                          disabled={exists || isSavingVideoReferences}
                                          onSelect={(event) => {
                                            event.preventDefault()
                                            if (exists || isSavingVideoReferences) return
                                            void handleSaveVideoReferences(shotIndex, [
                                              ...selectedVideoReferenceIds,
                                              referenceId,
                                            ])
                                          }}
                                        >
                                          <span>{reference.name}</span>
                                          {exists && (
                                            <span className="ml-auto text-xs text-muted-foreground">已添加</span>
                                          )}
                                        </DropdownMenuItem>
                                      )
                                    })
                                  )}
                                </DropdownMenuContent>
                              </DropdownMenu>
                            )}
                          </div>
                          {selectedVideoReferences.length > 0 ? (
                            <div className="space-y-2">
                              <div className={cn(
                                "relative rounded-lg p-2 transition",
                                !isVideoReferenceEffective && "overflow-hidden border border-dashed border-amber-400/60 bg-amber-50/40 dark:bg-amber-500/10"
                              )}>
                                <div className={cn(
                                  "flex flex-wrap gap-2 transition",
                                  !isVideoReferenceEffective && "grayscale opacity-60"
                                )}>
                                  {selectedVideoReferences.map((reference) => {
                                    const referenceId = String(reference.id)
                                    return (
                                      <div
                                        key={referenceId}
                                        className="group relative inline-flex items-center rounded-full border bg-muted px-3 py-1 text-xs"
                                      >
                                        <span>{reference.name}</span>
                                        {onSaveVideoReferences && (
                                          <button
                                            type="button"
                                            className={cn(
                                              "absolute -right-1 -top-1 hidden h-4 w-4 items-center justify-center rounded-full border bg-background text-muted-foreground transition-colors",
                                              "group-hover:flex hover:text-destructive"
                                            )}
                                            onClick={() => {
                                              if (isSavingVideoReferences) return
                                              void handleSaveVideoReferences(
                                                shotIndex,
                                                selectedVideoReferenceIds.filter((id) => id !== referenceId)
                                              )
                                            }}
                                            aria-label={`删除参考 ${reference.name}`}
                                            title={`删除参考 ${reference.name}`}
                                          >
                                            <X className="h-3 w-3" />
                                          </button>
                                        )}
                                      </div>
                                    )
                                  })}
                                </div>
                                {!isVideoReferenceEffective && (
                                  <>
                                    <div className="pointer-events-none absolute inset-0 bg-[repeating-linear-gradient(-45deg,rgba(245,158,11,0.14),rgba(245,158,11,0.14)_8px,transparent_8px,transparent_16px)]" />
                                    <div className="absolute right-2 top-2">
                                      <Tooltip>
                                        <TooltipTrigger asChild>
                                          <Badge variant="secondary" className="cursor-default border border-amber-300/70 bg-amber-100 text-amber-800">
                                            未生效
                                          </Badge>
                                        </TooltipTrigger>
                                        <TooltipContent side="top">
                                          <p className="text-xs">当前仅用于预览，不参与视频生成</p>
                                        </TooltipContent>
                                      </Tooltip>
                                    </div>
                                  </>
                                )}
                              </div>
                              {!isVideoReferenceEffective && (
                                <p className="text-xs text-amber-600">
                                  开启「借鉴参考图」后生效
                                </p>
                              )}
                            </div>
                          ) : (
                            <div className="bg-muted/30 p-3 rounded-lg border-2 border-dashed border-muted-foreground/20">
                              <p className="text-sm text-muted-foreground text-center">未关联参考</p>
                            </div>
                          )}
                        </div>
                      </div>

                      <div className="space-y-2 min-w-0">
                        <div className="flex items-center justify-between">
                          <h5 className="text-xs font-medium text-muted-foreground">视频</h5>
                          <div className="flex items-center gap-1">
                            {onDeleteVideo && hasVideo && (
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-6 px-2 hover:text-destructive hover:bg-destructive/10"
                                onClick={() => handleDeleteVideo(shotIndex)}
                                disabled={isLocalVideoDeleting || isVideoStageRunning}
                              >
                                <Trash2 className="h-3 w-3 mr-1" />
                                删除
                              </Button>
                            )}
                            {onRegenerateVideo && videoPrompt && (
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-6 px-2"
                                onClick={() => handleRegenerateVideo(shotIndex)}
                                disabled={isVideoStageRunning || isOtherStageRunningForVideo}
                              >
                                <RefreshCw className={cn("h-3 w-3 mr-1", isCurrentVideoGenerating && "animate-spin")} />
                                {isCurrentVideoGenerating ? '生成中...' : (hasVideo ? '重新生成' : '生成')}
                              </Button>
                            )}
                          </div>
                        </div>
                        <div className="rounded-lg border border-muted-foreground/20 bg-muted/20 p-3">
                          {hasVideo ? (
                            <div className="flex justify-center relative group/video-card">
                              <LazyMount
                                placeholder={
                                  <div className="flex h-64 w-full items-center justify-center rounded-lg bg-muted/40 text-sm text-muted-foreground">
                                    滚动到可视区域后显示封面
                                  </div>
                                }
                                className="block w-full"
                              >
                                <div
                                  className="mx-auto h-full max-w-full"
                                  style={
                                    {
                                      width: `min(100%, ${normalPreviewMaxWidth}px)`,
                                      aspectRatio: String(previewAspectRatio),
                                    }
                                  }
                                >
                                  <DeferredVideoPreview
                                    videoUrl={currentVideo.video_url || ''}
                                    initialDuration={currentVideo.duration}
                                    activated={isVideoActivated}
                                    onActivate={() => handleActivateVideoPreview(currentShotId)}
                                    className="h-full w-full max-w-full"
                                    videoClassName="rounded-lg object-contain"
                                    posterClassName="h-full w-full object-contain"
                                    onLoadedMetadata={(event) => handleVideoMetadataLoaded(currentShotId, event)}
                                  />
                              </div>
                              </LazyMount>
                              {(isCurrentVideoGenerating || isLocalVideoDeleting) && (
                                <div className="absolute inset-0 flex items-center justify-center bg-black/50 rounded-lg">
                                  <div className="text-white text-sm flex flex-col items-center gap-2">
                                    <div className="flex items-center gap-2">
                                      <RefreshCw className="h-5 w-5 animate-spin" />
                                      {isLocalVideoDeleting ? '删除中...' : videoRuntimeMessage}
                                    </div>
                                    {!isLocalVideoDeleting && isCurrentVideoGenerating && (
                                      <div className="w-32 h-2 bg-white/20 rounded-full overflow-hidden">
                                        <div
                                          className="h-full bg-white transition-all duration-300"
                                          style={{ width: `${displayVideoProgress}%` }}
                                        />
                                      </div>
                                    )}
                                    {!isLocalVideoDeleting && isCurrentVideoGenerating && (
                                      <div className="text-xs text-white/80">{displayVideoProgress}%</div>
                                    )}
                                  </div>
                                </div>
                              )}
                            </div>
                          ) : (
                            <div className="aspect-video bg-muted/30 rounded-lg border-2 border-dashed border-muted-foreground/20 flex items-center justify-center">
                              {isCurrentVideoGenerating ? (
                                <div className="text-center space-y-3">
                                  <RefreshCw className="h-8 w-8 text-primary mx-auto animate-spin" />
                                  <p className="text-sm text-muted-foreground">{videoProgressText}</p>
                                  <div className="w-32 h-2 bg-muted rounded-full overflow-hidden mx-auto">
                                    <div
                                      className="h-full bg-primary transition-all duration-300"
                                      style={{ width: `${displayVideoProgress}%` }}
                                    />
                                  </div>
                                </div>
                              ) : (
                                <div className="text-center">
                                  <Play className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
                                  <p className="text-sm text-muted-foreground">
                                    {onRegenerateVideo && videoPrompt ? '点击上方「生成」按钮生成视频' : '点击「生成视频」生成分镜视频'}
                                  </p>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
                </div>
              </div>
            </div>
          )
          })
        )}
      </div>
    </div>
  )
}
