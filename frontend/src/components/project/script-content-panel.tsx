'use client'

import {
  useEffect,
  useRef,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react'
import {
  CircleHelp,
  FileText,
  Trash2,
  Upload,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { SpeakerLineEditor } from '@/components/project/speaker-line-editor'
import { cn } from '@/lib/utils'
import { useScriptContentPanel, type UseScriptContentPanelParams } from '@/hooks/use-script-content-panel'

export type ScriptContentPanelProps = UseScriptContentPanelParams

export function ScriptContentPanel(props: ScriptContentPanelProps) {
  const {
    dialogueImportInputRef,
    editedTitle,
    setEditedTitle,
    editedDialogueLines,
    isSavingContent,
    isAutoSavingContent,
    isDeletingContent,
    isImportingDialogue,
    contentConstraintHintText,
    canImportDialogue,
    dialogueImportSample,
    isContentStageRunning,
    isOtherStageRunningForContent,
    isShotsLocked,
    editedSpeakerOptions,
    hasEditableSpeakers,
    editingTextForCount,
    handleUpdateDialogueLine,
    handleOpenDialogueImport,
    handleDialogueImportFileChange,
    handleDeleteContent,
    flushAutoSaveContent,
    onDeleteContent,
    onUnlockContentByClearingShots,
    handleUnlockContentByClearingShots,
    ensureAtLeastOneDialogueLine,
    insertDialogueLineAfter,
    updateDialogueLineSpeaker,
    removeDialogueLineWithFocus,
    countScriptChars,
  } = useScriptContentPanel(props)

  const lineTextareaRefs = useRef<Record<string, HTMLTextAreaElement | null>>({})
  const pendingFocusRef = useRef<{ lineId: string; caret: 'start' | 'end' } | null>(null)
  const compositionStateRef = useRef<Record<string, boolean>>({})

  useEffect(() => {
    if (editedDialogueLines.length === 0 && hasEditableSpeakers && !isShotsLocked) {
      void ensureAtLeastOneDialogueLine()
    }
  }, [editedDialogueLines.length, ensureAtLeastOneDialogueLine, hasEditableSpeakers, isShotsLocked])

  useEffect(() => {
    const pendingFocus = pendingFocusRef.current
    if (!pendingFocus) return
    const target = lineTextareaRefs.current[pendingFocus.lineId]
    if (!target) return
    pendingFocusRef.current = null
    requestAnimationFrame(() => {
      target.focus()
      const caretPosition = pendingFocus.caret === 'end'
        ? target.value.length
        : 0
      target.setSelectionRange(caretPosition, caretPosition)
    })
  }, [editedDialogueLines])

  const getSpeakerName = (
    speakerId: string | undefined,
    fallbackSpeakerName?: string
  ) => {
    const normalizedSpeakerId = String(speakerId || '').trim()
    const matched = editedSpeakerOptions.find((speaker) => speaker.id === normalizedSpeakerId)
    return matched?.name || String(fallbackSpeakerName || '').trim() || '角色'
  }

  const handleInsertNextLine = (lineId: string) => {
    const nextLineId = insertDialogueLineAfter(lineId)
    if (nextLineId) {
      pendingFocusRef.current = { lineId: nextLineId, caret: 'start' }
    }
  }

  const handleRemoveLine = (lineId: string, direction: 'auto' | 'previous' = 'auto') => {
    const nextFocus = removeDialogueLineWithFocus(lineId, direction)
    if (nextFocus?.lineId) {
      pendingFocusRef.current = nextFocus
    }
  }

  const handleLineKeyDown = (
    event: ReactKeyboardEvent<HTMLTextAreaElement>,
    lineId: string
  ) => {
    const textarea = event.currentTarget
    const isComposing = !!compositionStateRef.current[lineId]

    if (event.key === 'Enter' && !event.shiftKey && !isComposing) {
      event.preventDefault()
      handleInsertNextLine(lineId)
      return
    }

    if (
      event.key === 'Backspace'
      && textarea.value.length === 0
      && textarea.selectionStart === 0
      && textarea.selectionEnd === 0
    ) {
      event.preventDefault()
      handleRemoveLine(lineId, 'previous')
    }
  }

  return (
    <Card className="py-0">
      <CardContent className="p-4 space-y-3">
        <input
          ref={dialogueImportInputRef}
          type="file"
          accept=".json,application/json,text/plain"
          className="hidden"
          onChange={handleDialogueImportFileChange}
        />

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h4 className="text-sm font-medium flex items-center gap-2">
              <FileText className="h-4 w-4" />
              文案
            </h4>
            {contentConstraintHintText && (
              <Badge variant="outline" className="h-6 rounded-full border-amber-200 bg-amber-50 px-2.5 text-[11px] font-medium text-amber-700">
                {contentConstraintHintText}
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-2">
            {canImportDialogue && (
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2"
                  onClick={handleOpenDialogueImport}
                  disabled={isImportingDialogue || isSavingContent}
                >
                  <Upload className="h-3 w-3 mr-1" />
                  {isImportingDialogue ? '导入中...' : '上传'}
                </Button>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      className="inline-flex h-4 w-4 items-center justify-center rounded-full border text-[10px] text-muted-foreground hover:text-foreground"
                      aria-label="上传样例说明"
                    >
                      ?
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="bottom" align="end" className="max-w-[420px]">
                    <div className="space-y-1">
                      <p className="text-xs">上传 JSON 样例（title/roles 可选）：</p>
                      <pre className="text-[11px] leading-4 whitespace-pre-wrap">{dialogueImportSample}</pre>
                    </div>
                  </TooltipContent>
                </Tooltip>
              </div>
            )}
            {!isShotsLocked && (isSavingContent || isAutoSavingContent) && (
              <span className="text-xs text-muted-foreground">
                自动保存中...
              </span>
            )}
          </div>
        </div>

        {isShotsLocked && (
          <div className="rounded-lg border border-amber-300 bg-amber-50/60 px-3 py-2 text-xs text-amber-800">
            <div className="flex items-center justify-between gap-2">
              <span>当前文案已与分镜区绑定，请到分镜页编辑。若要恢复文案直接编辑，请先清空分镜区。</span>
              {onUnlockContentByClearingShots && (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 shrink-0"
                  onClick={handleUnlockContentByClearingShots}
                >
                  清空分镜并解锁
                </Button>
              )}
            </div>
          </div>
        )}

        <div className="space-y-2.5">
          <div className="flex items-center gap-3">
            <p className="shrink-0 text-sm font-medium">标题</p>
            <Input
              id="edit-title"
              value={editedTitle}
              onChange={(e) => setEditedTitle(e.target.value)}
              onBlur={() => void flushAutoSaveContent()}
              placeholder="输入标题..."
              className="h-11 border border-transparent bg-muted/25 px-3 text-sm font-normal shadow-none transition-colors hover:bg-muted/35 focus-visible:border-border focus-visible:ring-2 focus-visible:ring-ring/20"
              disabled={isShotsLocked}
            />
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <p className="text-sm font-medium">台词</p>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      type="button"
                      className="inline-flex h-4 w-4 items-center justify-center rounded-full border text-[10px] text-muted-foreground hover:text-foreground"
                      aria-label="台词编辑说明"
                    >
                      <CircleHelp className="h-3 w-3" />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="bottom" align="start" className="max-w-[320px] text-xs">
                    点击人物标签更换角色，按 Enter 新增下一行，Shift+Enter 行内换行。
                  </TooltipContent>
                </Tooltip>
              </div>
              <div className="flex items-center gap-3">
                <p className="text-xs text-muted-foreground">共 {countScriptChars(editingTextForCount)} 字</p>
                {onDeleteContent && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 px-2 hover:text-destructive hover:bg-destructive/10"
                    onClick={handleDeleteContent}
                    disabled={isDeletingContent || isContentStageRunning || isOtherStageRunningForContent}
                  >
                    <Trash2 className="h-3 w-3 mr-1" />
                    {isDeletingContent ? '删除中...' : '清空'}
                  </Button>
                )}
              </div>
            </div>

            {!hasEditableSpeakers ? (
              <div className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground text-center">
                当前参考区没有可用角色，请先在参考区创建角色参考
              </div>
            ) : (
              <div className="rounded-xl border bg-background px-3 py-1">
                <div className="space-y-0">
                  {editedDialogueLines.map((line, lineIndex) => {
                    const lineId = String(line.id || `line_${lineIndex + 1}`)
                    const speakerId = String(line.speaker_id || '').trim() || editedSpeakerOptions[0]?.id || ''
                    const speakerName = getSpeakerName(speakerId, String(line.speaker_name || ''))
                    return (
                      <SpeakerLineEditor
                        key={lineId}
                        speakerId={speakerId}
                        speakerName={speakerName}
                        speakerOptions={editedSpeakerOptions}
                        text={String(line.text || '')}
                        onSpeakerChange={(nextSpeakerId) => {
                          updateDialogueLineSpeaker(lineId, nextSpeakerId)
                          pendingFocusRef.current = { lineId, caret: 'end' }
                        }}
                        onDelete={() => handleRemoveLine(lineId, 'auto')}
                        onTextChange={(value) => handleUpdateDialogueLine(lineId, { text: value })}
                        onKeyDown={(event) => handleLineKeyDown(event, lineId)}
                        onCompositionStart={() => {
                          compositionStateRef.current[lineId] = true
                        }}
                        onCompositionEnd={() => {
                          compositionStateRef.current[lineId] = false
                        }}
                        onBlur={() => void flushAutoSaveContent()}
                        placeholder="输入台词内容..."
                        textareaRef={(node) => {
                          lineTextareaRefs.current[lineId] = node
                        }}
                        disabled={isShotsLocked}
                        showDeleteAction={!isShotsLocked}
                        rowClassName={cn(
                          lineIndex > 0 && 'border-t border-border/20'
                        )}
                      />
                    )
                  })}
                </div>
              </div>
            )}

          </div>
        </div>
      </CardContent>
    </Card>
  )
}
