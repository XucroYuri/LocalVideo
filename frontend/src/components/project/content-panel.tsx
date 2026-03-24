'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Loader2, Trash2, Video } from 'lucide-react'
import type { ScriptRole, DialogueLine, Reference } from '@/lib/content-panel-helpers'
import type { ReferenceLibraryItem, StageReferenceImportResult } from '@/types/reference'
import { useConfirmDialog } from '@/components/common/confirm-dialog-provider'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { VideoPreviewPlayerClient } from '@/components/ui/video-preview-player-client'
import type { TabType } from '@/types/stage-panel'
import { ScriptTabContent } from './script-tab-content'
import { ShotsTabContent } from './shots-tab-content'

export interface ContentPanelProps {
  activeTab: TabType
  stageData?: {
    content?: {
      title?: string
      content?: string
      char_count?: number
      shots_locked?: boolean
      script_mode?: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'
      chat_history?: Array<{
        role?: 'user' | 'assistant'
        text?: string
      }>
      chat_summary?: string
      last_user_message?: string
      roles?: ScriptRole[]
      dialogue_lines?: DialogueLine[]
    }
    storyboard?: {
      title?: string
      shots?: import('@/lib/content-panel-helpers').Shot[]
      references?: Reference[]
    }
    audio?: {
      shots?: import('@/lib/content-panel-helpers').Shot[]
    }
    reference?: {
      references?: Reference[]
      reference_images?: Array<{
        id: string
        name: string
        setting?: string
        appearance_description?: string
        can_speak?: boolean
        voice_audio_provider?: 'edge_tts' | 'wan2gp' | 'volcengine_tts' | 'kling_tts' | 'vidu_tts' | 'minimax_tts' | 'xiaomi_mimo_tts'
        voice_name?: string
        voice_speed?: number
        voice_wan2gp_preset?: string
        voice_wan2gp_alt_prompt?: string
        voice_wan2gp_audio_guide?: string
        voice_wan2gp_temperature?: number
        voice_wan2gp_top_k?: number
        voice_wan2gp_seed?: number
        file_path?: string
        generated?: boolean
      }>
    }
    video?: {
      shots?: import('@/lib/content-panel-helpers').Shot[]
    }
    frame?: {
      shots?: Array<{
        first_frame_url?: string
        first_frame_description?: string
        updated_at?: number
      }>
    }
    compose?: {
      video_url?: string
      poster_url?: string
      width?: number
      height?: number
      duration?: number
    }
    subtitle?: {
      subtitle_url?: string
      duration?: number
      line_count?: number
    }
    burn_subtitle?: {
      video_url?: string
      duration?: number
      width?: number
      height?: number
    }
    finalize?: {
      video_url?: string
      poster_url?: string
      width?: number
      height?: number
      duration?: number
      has_subtitle?: boolean
      source_stage?: string
    }
  }
  // Progress tracking for generating items
  generatingShots?: Record<string, { status: string; progress: number }>
  runningStage?: string  // Which stage is currently running
  runningAction?: string
  runningReferenceId?: string | number
  progress?: number
  progressMessage?: string
  referenceStageStatus?: string
  frameStageStatus?: string
  videoStageStatus?: string
  runningShotIndex?: number
  configuredScriptMode?: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'
  narratorStyle?: string
  dialogueScriptMaxRoles?: number
  useReferenceImageRef?: boolean
  singleTakeEnabled?: boolean
  useFirstFrameRef?: boolean
  useReferenceConsistency?: boolean
  includeSubtitle?: boolean
  onSaveContent?: (data: {
    title?: string
    content?: string
    script_mode?: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'
    roles?: ScriptRole[]
    dialogue_lines?: DialogueLine[]
  }) => Promise<void>
  onDeleteContent?: () => Promise<void>
  onUnlockContentByClearingShots?: () => Promise<void>
  onContentChatSend?: (message: string) => Promise<void>
  onContentChatReset?: () => Promise<void>
  isContentChatRunning?: boolean
  onImportDialogue?: (
    file: File,
    scriptMode: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'
  ) => Promise<void>
  onSaveReference?: (
    referenceId: string | number,
    data: {
      name: string
      setting?: string
      appearance_description?: string
      can_speak: boolean
      voice_audio_provider?: 'edge_tts' | 'wan2gp' | 'volcengine_tts' | 'kling_tts' | 'vidu_tts' | 'minimax_tts' | 'xiaomi_mimo_tts'
      voice_name?: string
      voice_speed?: number
      voice_wan2gp_preset?: string
      voice_wan2gp_alt_prompt?: string
      voice_wan2gp_audio_guide?: string
      voice_wan2gp_temperature?: number
      voice_wan2gp_top_k?: number
      voice_wan2gp_seed?: number
    }
  ) => Promise<void>
  onDeleteReference?: (referenceId: string | number) => Promise<void>
  onRegenerateReferenceImage?: (referenceId: string | number) => Promise<void>
  onUploadReferenceImage?: (referenceId: string | number, file: File) => Promise<void>
  onCreateReference?: (
    data: {
      name?: string
      setting?: string
      appearance_description?: string
      can_speak?: boolean
      voice_audio_provider?: 'edge_tts' | 'wan2gp' | 'volcengine_tts' | 'kling_tts' | 'vidu_tts' | 'minimax_tts' | 'xiaomi_mimo_tts'
      voice_name?: string
      voice_speed?: number
      voice_wan2gp_preset?: string
      voice_wan2gp_alt_prompt?: string
      voice_wan2gp_audio_guide?: string
      voice_wan2gp_temperature?: number
      voice_wan2gp_top_k?: number
      voice_wan2gp_seed?: number
      file?: File
    }
  ) => Promise<void>
  onGenerateDescriptionFromImage?: (referenceId: string | number) => Promise<void>
  // Frame editing handlers
  onSaveFrameDescription?: (shotIndex: number, description: string) => Promise<void>
  onGenerateFrameDescription?: (shotIndex: number) => Promise<void>
  onSaveFrameReferences?: (shotIndex: number, referenceIds: string[]) => Promise<void>
  onRegenerateFrameImage?: (shotIndex: number) => Promise<void>
  onReuseFirstFrameToOthers?: () => Promise<void>
  onUploadFrameImage?: (shotIndex: number, file: File) => Promise<void>
  onDeleteFrameImage?: (shotIndex: number) => Promise<void>
  onClearAllAudio?: () => Promise<void>
  onClearAllFrameImages?: () => Promise<void>
  // Video editing handlers
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
    data: { voice_content?: string; speaker_id?: string; speaker_name?: string }
  ) => Promise<void>
  onRegenerateAudio?: (shotIndex: number) => Promise<void>
  onDeleteComposeVideo?: () => Promise<void>
  // Reference image delete handler
  onDeleteReferenceImage?: (referenceId: string | number) => Promise<void>
  libraryReferences?: ReferenceLibraryItem[]
  onImportReferencesFromLibrary?: (data: {
    library_reference_ids: number[]
    start_reference_index?: number
    import_setting: boolean
    import_appearance_description: boolean
    import_image: boolean
    import_voice: boolean
  }) => Promise<StageReferenceImportResult>
  showScriptReferencePanel?: boolean
}

export function ContentPanel({
  activeTab,
  stageData,
  showScriptReferencePanel = true,
  ...rest
}: ContentPanelProps) {
  const confirmDialog = useConfirmDialog()
  const [isDeletingComposeVideo, setIsDeletingComposeVideo] = useState(false)
  const [contentChatMessage, setContentChatMessage] = useState('')
  const [isSendingContentChat, setIsSendingContentChat] = useState(false)
  const [isResettingContentChat, setIsResettingContentChat] = useState(false)
  const contentChatTextareaRef = useRef<HTMLTextAreaElement | null>(null)

  const adjustContentChatTextareaHeight = useCallback(() => {
    const textarea = contentChatTextareaRef.current
    if (!textarea) return
    const maxHeightPx = 160
    textarea.style.height = 'auto'
    const nextHeight = Math.min(textarea.scrollHeight, maxHeightPx)
    textarea.style.height = `${nextHeight}px`
    textarea.style.overflowY = textarea.scrollHeight > maxHeightPx ? 'auto' : 'hidden'
  }, [])

  useEffect(() => {
    adjustContentChatTextareaHeight()
  }, [contentChatMessage, adjustContentChatTextareaHeight])

  const handleDeleteComposeVideo = async () => {
    if (!rest.onDeleteComposeVideo || isDeletingComposeVideo) return
    try {
      setIsDeletingComposeVideo(true)
      await rest.onDeleteComposeVideo()
    } finally {
      setIsDeletingComposeVideo(false)
    }
  }

  const renderContent = () => {
    switch (activeTab) {
      case 'script':
        return <ScriptTabContent stageData={stageData} showReferencePanel={showScriptReferencePanel} {...rest} />
      case 'shots':
        return <ShotsTabContent stageData={stageData} {...rest} />
      case 'compose':
        return renderComposeTab()
      default:
        return null
    }
  }

  const renderComposeTab = () => {
    const includeSubtitle = rest.includeSubtitle !== false
    const finalVideoData = includeSubtitle
      ? (
          stageData?.finalize
          || (stageData?.burn_subtitle?.video_url
            ? {
                video_url: stageData.burn_subtitle.video_url,
                poster_url: stageData?.compose?.poster_url,
                width: stageData.burn_subtitle.width,
                height: stageData.burn_subtitle.height,
                duration: stageData.burn_subtitle.duration,
              }
            : undefined)
        )
      : (stageData?.finalize || stageData?.compose)
    const composeVideoUrl = finalVideoData?.video_url
    const composeAspectRatio = (
      typeof finalVideoData?.width === 'number'
      && typeof finalVideoData?.height === 'number'
      && finalVideoData.width > 0
      && finalVideoData.height > 0
    )
      ? finalVideoData.width / finalVideoData.height
      : undefined
    const hasComposeVideo = !!String(composeVideoUrl || '').trim()

    return (
      <div className="h-full p-6">
        <div className="h-full rounded-lg border border-muted-foreground/20 bg-muted/20 p-3 flex flex-col">
          <div className="mb-3 flex items-center justify-between">
            <h5 className="text-xs font-medium text-muted-foreground">视频</h5>
            {rest.onDeleteComposeVideo && hasComposeVideo && (
              <Button
                variant="ghost"
                size="sm"
                className="h-6 px-2 hover:text-destructive hover:bg-destructive/10"
                onClick={() => void handleDeleteComposeVideo()}
                disabled={isDeletingComposeVideo}
              >
                {isDeletingComposeVideo ? (
                  <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                ) : (
                  <Trash2 className="h-3 w-3 mr-1" />
                )}
                {isDeletingComposeVideo ? '删除中...' : '删除'}
              </Button>
            )}
          </div>

          {hasComposeVideo ? (
            <div className="flex-1 min-h-0 flex items-center justify-center">
              <div
                className="h-full max-w-full"
                style={
                  composeAspectRatio && composeAspectRatio > 0
                    ? { aspectRatio: composeAspectRatio }
                    : undefined
                }
              >
                <VideoPreviewPlayerClient
                  key={composeVideoUrl || ''}
                  src={composeVideoUrl || ''}
                  initialDuration={finalVideoData?.duration}
                  posterCaptureMaxEdge={0}
                  cacheCapturedPoster={false}
                  className="h-full w-full"
                  videoClassName="h-full w-full rounded-lg object-contain"
                  posterClassName="h-full w-full rounded-lg object-contain"
                  autoPlayOnActivate
                />
              </div>
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground">
              <Video className="h-12 w-12 mb-4 opacity-50" />
              <p>点击「生成成片」按钮生成最终视频</p>
            </div>
          )}
        </div>
      </div>
    )
  }

  const showContentChatComposer = activeTab === 'script' && (
    !!rest.onContentChatSend || !!rest.onContentChatReset
  )
  const hasStoryboardShots = (stageData?.storyboard?.shots?.length || 0) > 0
  const areShotsLocked = !!stageData?.content?.shots_locked || hasStoryboardShots
  const currentScriptMode = String(
    rest.configuredScriptMode || stageData?.content?.script_mode || 'single'
  ).trim()
  const isPresetRoleLockedMode = currentScriptMode === 'single' || currentScriptMode === 'duo_podcast'
  const contentChatPlaceholder = areShotsLocked
    ? '文案已与分镜绑定，请前往分镜页编辑'
    : '输入你想要的台词需求或修改指令...'

  const handleContentChatSend = async () => {
    if (
      !rest.onContentChatSend
      || isSendingContentChat
      || isResettingContentChat
      || rest.isContentChatRunning
      || areShotsLocked
    ) {
      return
    }
    const message = contentChatMessage.trim()
    if (!message) return
    try {
      setIsSendingContentChat(true)
      await rest.onContentChatSend(message)
      setContentChatMessage('')
    } finally {
      setIsSendingContentChat(false)
    }
  }

  const handleContentChatReset = async () => {
    if (
      !rest.onContentChatReset
      || isSendingContentChat
      || isResettingContentChat
      || rest.isContentChatRunning
      || areShotsLocked
    ) {
      return
    }
    const confirmed = await confirmDialog({
      title: '重置确认',
      description: isPresetRoleLockedMode
        ? '重置会清空当前文案和对话记录，不会清空参考区内容，是否继续？'
        : '重置会清空当前文案、对话记录和参考区内容，是否继续？',
      confirmText: '确认重置',
      cancelText: '取消',
      variant: 'destructive',
    })
    if (!confirmed) return
    try {
      setIsResettingContentChat(true)
      await rest.onContentChatReset()
      setContentChatMessage('')
    } finally {
      setIsResettingContentChat(false)
    }
  }

  return (
    <div className="h-full flex flex-col bg-muted/30">
      <div className="min-h-0 flex-1">
        {renderContent()}
      </div>
      {showContentChatComposer && (
        <div className="border-t bg-background/95 px-6 py-4">
          <div className="w-full rounded-2xl border border-border/70 bg-muted/35 p-3 shadow-sm">
            <Textarea
              ref={contentChatTextareaRef}
              value={contentChatMessage}
              placeholder={contentChatPlaceholder}
              onChange={(event) => setContentChatMessage(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== 'Enter') return
                if (event.shiftKey) return
                event.preventDefault()
                void handleContentChatSend()
              }}
              rows={1}
              className="min-h-[44px] max-h-[160px] resize-none border-0 bg-transparent px-0 shadow-none focus-visible:ring-0"
              disabled={isSendingContentChat || isResettingContentChat || rest.isContentChatRunning || areShotsLocked}
            />
            <div className="mt-3 flex items-center justify-end gap-2 border-t border-border/60 pt-3">
              <Button
                size="sm"
                variant="outline"
                onClick={() => void handleContentChatReset()}
                disabled={
                  isSendingContentChat
                  || isResettingContentChat
                  || rest.isContentChatRunning
                  || areShotsLocked
                  || !rest.onContentChatReset
                }
              >
                {isResettingContentChat ? '重置中...' : '重置'}
              </Button>
              <Button
                size="sm"
                onClick={() => void handleContentChatSend()}
                disabled={
                  !contentChatMessage.trim()
                  || isSendingContentChat
                  || isResettingContentChat
                  || rest.isContentChatRunning
                  || areShotsLocked
                  || !rest.onContentChatSend
                }
              >
                {isSendingContentChat || rest.isContentChatRunning ? '发送中...' : '发送'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
