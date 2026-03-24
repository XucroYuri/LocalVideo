'use client'

import {
  RefreshCw,
  Upload,
  Trash2,
  ImageIcon,
} from 'lucide-react'

import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ReferenceVoiceFields } from '@/components/audio/reference-voice-fields'
import { SpeakInactiveNotice } from '@/components/project/script-reference-card-new'
import type { UseScriptReferencePanelReturn } from '@/hooks/use-script-reference-panel'
import { cn } from '@/lib/utils'

interface ScriptReferenceCardEditProps {
  hook: UseScriptReferencePanelReturn
}

export function ScriptReferenceCardEdit({ hook }: ScriptReferenceCardEditProps) {
  const {
    currentReference,
    fileInputRef,
    handleFileChange,
    editedReferenceName,
    setEditedReferenceName,
    flushAutoSaveReference,
    editedReferenceSetting,
    setEditedReferenceSetting,
    isCurrentNarratorSettingLocked,
    editedReferenceAppearanceDesc,
    setEditedReferenceAppearanceDesc,
    editedReferenceCanSpeak,
    setEditedReferenceCanSpeak,
    setEditedReferenceVoice,
    voiceMeta,
    isCurrentLockedNarratorReference,
    isEditedReferenceSpeakInactive,
    speakInactiveHintText,
    normalizedEditedReferenceVoice,
    onRegenerateReferenceImage,
    handleRegenerateImage,
    showReferenceGenerating,
    onUploadReferenceImage,
    handleImageClick,
    isUploading,
    onDeleteReferenceImage,
    handleDeleteReferenceImage,
    isDeletingReferenceImage,
    isReferenceImageStageRunning,
    referenceProgressText,
    referenceProgress,
    isReferenceModelDownloading,
  } = hook

  const currentReferenceId = currentReference?.id
  const canOperateReference = currentReferenceId !== undefined && currentReferenceId !== null
  const settingPlaceholder = '参考设定写角色身份、性格、语气等人设信息，不写外观细节。'
  const appearancePlaceholder = '参考外观描述只写镜头可见外形（发型、服饰、材质、配色、配饰等），不写性格设定。'

  return (
    <div className="space-y-4">
      <input
        ref={fileInputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="hidden"
        onChange={(e) => {
          if (!canOperateReference) return
          void handleFileChange(e, currentReferenceId)
        }}
      />
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_360px] gap-4 items-start">
        <div className="space-y-4 min-w-0">
          <div className="space-y-2">
            <Label htmlFor="edit-reference-name">参考名称</Label>
            <Input
              id="edit-reference-name"
              value={editedReferenceName}
              onChange={(e) => setEditedReferenceName(e.target.value)}
              onBlur={() => void flushAutoSaveReference()}
              placeholder="输入参考名称..."
            />
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="space-y-2 min-w-0">
              <Label htmlFor="edit-reference-setting">参考设定（可选）</Label>
              <Textarea
                id="edit-reference-setting"
                value={editedReferenceSetting}
                onChange={(e) => setEditedReferenceSetting(e.target.value)}
                onBlur={() => void flushAutoSaveReference()}
                placeholder={settingPlaceholder}
                className="h-[160px] max-h-[160px] overflow-y-auto resize-none"
                disabled={isCurrentNarratorSettingLocked}
              />
              {isCurrentNarratorSettingLocked && (
                <p className="text-xs text-amber-600">
                  当前为预设讲述者风格，参考设定由风格自动同步，不能手动编辑。
                </p>
              )}
            </div>
            <div className="space-y-2 min-w-0">
              <Label htmlFor="edit-reference-appearance">参考外观描述（可选）</Label>
              <Textarea
                id="edit-reference-appearance"
                value={editedReferenceAppearanceDesc}
                onChange={(e) => setEditedReferenceAppearanceDesc(e.target.value)}
                onBlur={() => void flushAutoSaveReference()}
                placeholder={appearancePlaceholder}
                className="h-[160px] max-h-[160px] overflow-y-auto resize-none"
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="edit-reference-can-speak">是否可说台词</Label>
            <Select
              value={editedReferenceCanSpeak ? 'true' : 'false'}
              onValueChange={(value) => {
                const canSpeak = value !== 'false'
                setEditedReferenceCanSpeak(canSpeak)
                if (canSpeak) {
                  setEditedReferenceVoice((prev) => voiceMeta.normalizeConfig(prev))
                }
                void flushAutoSaveReference()
              }}
              disabled={isCurrentLockedNarratorReference}
            >
              <SelectTrigger id="edit-reference-can-speak">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="true">可说台词</SelectItem>
                <SelectItem value="false">不可说台词（如场景）</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {isEditedReferenceSpeakInactive && speakInactiveHintText && (
            <SpeakInactiveNotice hintText={speakInactiveHintText} />
          )}
          {editedReferenceCanSpeak && (
            <ReferenceVoiceFields
              value={normalizedEditedReferenceVoice}
              onChange={(nextValue) => {
                setEditedReferenceVoice(nextValue)
              }}
              meta={voiceMeta}
            />
          )}
        </div>

        <div className="space-y-2 xl:sticky xl:top-2 xl:pt-8">
          <div className="flex items-center justify-between">
            <h5 className="text-xs font-medium text-muted-foreground">图片</h5>
            <div className="flex items-center gap-1">
              {onRegenerateReferenceImage && !!editedReferenceAppearanceDesc.trim() && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2"
                  onClick={() => {
                    if (!canOperateReference) return
                    void handleRegenerateImage(currentReferenceId)
                  }}
                  disabled={showReferenceGenerating}
                >
                  <RefreshCw className={cn('h-3 w-3 mr-1', showReferenceGenerating && 'animate-spin')} />
                  {showReferenceGenerating ? '生成中...' : (currentReference?.image_url ? '重新生成' : '生成')}
                </Button>
              )}
              {onUploadReferenceImage && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2"
                  onClick={handleImageClick}
                  disabled={isUploading || showReferenceGenerating}
                >
                  <Upload className="h-3 w-3 mr-1" />
                  上传
                </Button>
              )}
              {onDeleteReferenceImage && currentReference?.image_url && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2 hover:text-destructive hover:bg-destructive/10"
                  onClick={() => {
                    if (!canOperateReference) return
                    void handleDeleteReferenceImage(currentReferenceId)
                  }}
                  disabled={isDeletingReferenceImage || showReferenceGenerating || isUploading}
                >
                  <Trash2 className="h-3 w-3 mr-1" />
                  删除
                </Button>
              )}
            </div>
          </div>

          {currentReference?.image_url ? (
            <div className="relative group flex justify-center rounded-lg border bg-muted/20 p-3 min-h-[300px]">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={currentReference.image_url}
                alt={currentReference.name}
                className={cn(
                  'w-full max-h-[520px] rounded-lg object-contain',
                  onUploadReferenceImage && 'cursor-pointer'
                )}
                onClick={() => {
                  if (!showReferenceGenerating) handleImageClick()
                }}
              />
              {onUploadReferenceImage && !isUploading && !showReferenceGenerating && !isDeletingReferenceImage && (
                <div
                  className="absolute inset-3 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-black/30 rounded-lg cursor-pointer"
                  onClick={handleImageClick}
                >
                  <div className="text-white text-sm flex items-center gap-2">
                    <Upload className="h-5 w-5" />
                    点击上传新图片
                  </div>
                </div>
              )}
              {(isUploading || showReferenceGenerating || isDeletingReferenceImage) && (
                <div className="absolute inset-3 flex items-center justify-center bg-black/50 rounded-lg">
                  <div className="text-white text-sm flex flex-col items-center gap-2">
                    <div className="flex items-center gap-2">
                      <RefreshCw className="h-5 w-5 animate-spin" />
                      {isUploading ? '上传中...' : isDeletingReferenceImage ? '删除中...' : referenceProgressText}
                    </div>
                    {isReferenceImageStageRunning && (
                      <div className="w-44 h-2 bg-white/25 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-white transition-all duration-300"
                          style={{ width: `${referenceProgress}%` }}
                        />
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div
              className={cn(
                'min-h-[300px] bg-muted/30 rounded-lg border-2 border-dashed border-muted-foreground/20 flex items-center justify-center px-4',
                onUploadReferenceImage && 'cursor-pointer hover:bg-muted/50 transition-colors'
              )}
              onClick={handleImageClick}
            >
              {isUploading ? (
                <div className="text-center">
                  <RefreshCw className="h-8 w-8 text-muted-foreground mx-auto mb-2 animate-spin" />
                  <p className="text-sm text-muted-foreground">上传中...</p>
                </div>
              ) : showReferenceGenerating ? (
                <div className="text-center w-full px-6">
                  <RefreshCw
                    className={cn(
                      'text-muted-foreground mx-auto mb-2 animate-spin',
                      isReferenceModelDownloading ? 'h-6 w-6' : 'h-8 w-8'
                    )}
                  />
                  <p className="text-sm text-muted-foreground">{referenceProgressText}</p>
                  {isReferenceImageStageRunning && (
                    <div className="mt-2 h-2 w-full max-w-xs mx-auto bg-muted rounded-full overflow-hidden">
                      <div
                        className="h-full bg-primary transition-all duration-300"
                        style={{ width: `${referenceProgress}%` }}
                      />
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-center">
                  <ImageIcon className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
                  <p className="text-sm text-muted-foreground">
                    {onUploadReferenceImage ? '点击上传或使用「生成」按钮生成图片' : '请先添加参考外观描述'}
                  </p>
                </div>
              )}
            </div>
          )}
          {isEditedReferenceSpeakInactive && (
            <div className="flex justify-end">
              <Badge variant="secondary" className="cursor-default border border-amber-300/70 bg-amber-100 text-amber-800">
                未生效
              </Badge>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
