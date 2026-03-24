'use client'

import {
  Wand2,
  RefreshCw,
  Upload,
  Trash2,
  ImageIcon,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { getReferenceVoiceProviderLabel } from '@/lib/reference-voice'
import { cn } from '@/lib/utils'
import type { UseScriptReferencePanelReturn } from '@/hooks/use-script-reference-panel'

interface ScriptReferenceCardViewProps {
  fileInputRef: UseScriptReferencePanelReturn['fileInputRef']
  onFileChange: UseScriptReferencePanelReturn['handleFileChange']
  currentReference: UseScriptReferencePanelReturn['currentReference']
  isCurrentReferenceCanSpeak: UseScriptReferencePanelReturn['isCurrentReferenceCanSpeak']
  isCurrentReferenceSpeakInactive: UseScriptReferencePanelReturn['isCurrentReferenceSpeakInactive']
  isCurrentLockedNarratorReference: UseScriptReferencePanelReturn['isCurrentLockedNarratorReference']
  scriptMode: UseScriptReferencePanelReturn['scriptMode']
  safeCurrentReferenceIndex: UseScriptReferencePanelReturn['safeCurrentReferenceIndex']
  isCurrentNarratorSettingLocked: UseScriptReferencePanelReturn['isCurrentNarratorSettingLocked']
  currentReferenceSetting: UseScriptReferencePanelReturn['currentReferenceSetting']
  currentReferenceAppearanceDesc: UseScriptReferencePanelReturn['currentReferenceAppearanceDesc']
  voiceMeta: UseScriptReferencePanelReturn['voiceMeta']
  voiceLibraryNameByAudioPath: UseScriptReferencePanelReturn['voiceLibraryNameByAudioPath']
  speakInactiveHintText: UseScriptReferencePanelReturn['speakInactiveHintText']
  onGenerateDescriptionFromImage: UseScriptReferencePanelReturn['onGenerateDescriptionFromImage']
  handleGenerateDescriptionFromImage: UseScriptReferencePanelReturn['handleGenerateDescriptionFromImage']
  isCurrentReferenceGeneratingDescription: UseScriptReferencePanelReturn['isCurrentReferenceGeneratingDescription']
  onRegenerateReferenceImage: UseScriptReferencePanelReturn['onRegenerateReferenceImage']
  handleRegenerateImage: UseScriptReferencePanelReturn['handleRegenerateImage']
  showReferenceGenerating: UseScriptReferencePanelReturn['showReferenceGenerating']
  onUploadReferenceImage: UseScriptReferencePanelReturn['onUploadReferenceImage']
  handleImageClick: UseScriptReferencePanelReturn['handleImageClick']
  isUploading: UseScriptReferencePanelReturn['isUploading']
  onDeleteReferenceImage: UseScriptReferencePanelReturn['onDeleteReferenceImage']
  handleDeleteReferenceImage: UseScriptReferencePanelReturn['handleDeleteReferenceImage']
  isDeletingReferenceImage: UseScriptReferencePanelReturn['isDeletingReferenceImage']
  referenceProgressText: UseScriptReferencePanelReturn['referenceProgressText']
  isReferenceImageStageRunning: UseScriptReferencePanelReturn['isReferenceImageStageRunning']
  referenceProgress: UseScriptReferencePanelReturn['referenceProgress']
  isReferenceModelDownloading: UseScriptReferencePanelReturn['isReferenceModelDownloading']
}

export function ScriptReferenceCardView({
  fileInputRef,
  onFileChange,
  currentReference,
  isCurrentReferenceCanSpeak,
  isCurrentReferenceSpeakInactive,
  isCurrentLockedNarratorReference,
  scriptMode,
  safeCurrentReferenceIndex,
  isCurrentNarratorSettingLocked,
  currentReferenceSetting,
  currentReferenceAppearanceDesc,
  voiceMeta,
  voiceLibraryNameByAudioPath,
  speakInactiveHintText,
  onGenerateDescriptionFromImage,
  handleGenerateDescriptionFromImage,
  isCurrentReferenceGeneratingDescription,
  onRegenerateReferenceImage,
  handleRegenerateImage,
  showReferenceGenerating,
  onUploadReferenceImage,
  handleImageClick,
  isUploading,
  onDeleteReferenceImage,
  handleDeleteReferenceImage,
  isDeletingReferenceImage,
  referenceProgressText,
  isReferenceImageStageRunning,
  referenceProgress,
  isReferenceModelDownloading,
}: ScriptReferenceCardViewProps) {
  const currentReferenceId = currentReference?.id
  const normalizedVoice = voiceMeta.normalizeConfig({
    voice_audio_provider: currentReference?.voice_audio_provider,
    voice_name: currentReference?.voice_name,
    voice_speed: currentReference?.voice_speed,
    voice_wan2gp_preset: currentReference?.voice_wan2gp_preset,
    voice_wan2gp_alt_prompt: currentReference?.voice_wan2gp_alt_prompt,
    voice_wan2gp_audio_guide: currentReference?.voice_wan2gp_audio_guide,
  })
  const speedLabel = `${(normalizedVoice.voice_speed ?? 1.0).toFixed(1)}x`
  const wan2gpPreset = normalizedVoice.voice_audio_provider === 'wan2gp'
    ? voiceMeta.getWan2gpPreset(normalizedVoice.voice_wan2gp_preset)
    : undefined
  const wan2gpModelName = wan2gpPreset?.display_name
    || normalizedVoice.voice_wan2gp_preset
    || '未设置'

  const canOperateReference = currentReferenceId !== undefined && currentReferenceId !== null

  return (
    <div className="space-y-4">
      <input
        ref={fileInputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="hidden"
        onChange={(e) => {
          if (!canOperateReference) return
          void onFileChange(e, currentReferenceId)
        }}
      />
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_360px] gap-4 items-start">
        <div className="space-y-4 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">参考名：</span>
            <span className="text-sm font-medium">{currentReference?.name}</span>
            <Badge variant={isCurrentReferenceCanSpeak ? (isCurrentReferenceSpeakInactive ? 'secondary' : 'default') : 'secondary'}>
              {isCurrentReferenceCanSpeak
                ? (isCurrentReferenceSpeakInactive ? '可说台词（未生效）' : '可说台词')
                : '不可说台词'}
            </Badge>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h5 className="text-xs font-medium text-muted-foreground">
                {isCurrentLockedNarratorReference
                  ? (
                    scriptMode === 'duo_podcast'
                      ? `讲述者${safeCurrentReferenceIndex + 1}设定`
                      : '讲述者设定'
                  )
                  : '参考设定'}
              </h5>
            </div>
            {isCurrentNarratorSettingLocked && (
              <p className="text-xs text-amber-600">
                当前为预设讲述者风格，设定随风格自动同步。
              </p>
            )}
            {currentReferenceSetting ? (
              <p className="text-sm bg-muted/50 p-3 rounded-lg whitespace-pre-wrap">{currentReferenceSetting}</p>
            ) : (
              <div className="bg-muted/30 p-3 rounded-lg border-2 border-dashed border-muted-foreground/20">
                <p className="text-sm text-muted-foreground text-center">未填写参考设定</p>
              </div>
            )}
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h5 className="text-xs font-medium text-muted-foreground">参考外观描述</h5>
              <div className="flex items-center gap-1">
                {onGenerateDescriptionFromImage && currentReference?.image_url && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 px-2"
                    onClick={() => {
                      if (!canOperateReference) return
                      void handleGenerateDescriptionFromImage(currentReferenceId)
                    }}
                    disabled={isCurrentReferenceGeneratingDescription}
                    title="根据图片生成外观描述"
                  >
                    <Wand2 className={cn('h-3 w-3 mr-1', isCurrentReferenceGeneratingDescription && 'animate-pulse')} />
                    {isCurrentReferenceGeneratingDescription ? '生成中...' : '从图生成描述'}
                  </Button>
                )}
              </div>
            </div>
            {currentReferenceAppearanceDesc ? (
              <p className="text-sm bg-muted/50 p-3 rounded-lg whitespace-pre-wrap">
                {currentReferenceAppearanceDesc}
              </p>
            ) : (
              <div className="bg-muted/30 p-3 rounded-lg border-2 border-dashed border-muted-foreground/20">
                <p className="text-sm text-muted-foreground text-center">
                  {currentReference?.image_url ? '点击「从图生成描述」自动生成外观描述' : '请先编辑填写外观描述'}
                </p>
              </div>
            )}
          </div>

          {isCurrentReferenceCanSpeak && (
            <div className="space-y-2">
              <h5 className="text-xs font-medium text-muted-foreground">声音</h5>
              <div
                className={cn(
                  'relative rounded-lg border bg-muted/30 p-3 text-sm space-y-1',
                  isCurrentReferenceSpeakInactive
                    && 'overflow-hidden border-dashed border-amber-400/60 bg-amber-50/40 dark:bg-amber-500/10'
                )}
              >
                <div className={cn(isCurrentReferenceSpeakInactive && 'relative z-10')}>
                  <div>Provider：{getReferenceVoiceProviderLabel(normalizedVoice.voice_audio_provider)}</div>
                  {normalizedVoice.voice_audio_provider !== 'wan2gp' ? (
                    <>
                      <div>
                        音色：{voiceMeta.resolveVoiceLabel(
                          normalizedVoice.voice_audio_provider,
                          normalizedVoice.voice_name,
                          normalizedVoice.voice_wan2gp_preset
                        )}
                      </div>
                      <div>语速：{speedLabel}</div>
                    </>
                  ) : (
                    <>
                      <div>模型：{wan2gpModelName}</div>
                      {normalizedVoice.voice_wan2gp_preset === 'qwen3_tts_customvoice' && (
                        <>
                          <div>
                            音色：{voiceMeta.resolveVoiceLabel(
                              normalizedVoice.voice_audio_provider,
                              normalizedVoice.voice_name,
                              normalizedVoice.voice_wan2gp_preset
                            )}
                          </div>
                          <div>风格指令：{normalizedVoice.voice_wan2gp_alt_prompt || '未设置'}</div>
                        </>
                      )}
                      {normalizedVoice.voice_wan2gp_preset === 'qwen3_tts_base' && (
                        <>
                          <div>
                            语言：{voiceMeta.resolveVoiceLabel(
                              normalizedVoice.voice_audio_provider,
                              normalizedVoice.voice_name,
                              normalizedVoice.voice_wan2gp_preset
                            )}
                          </div>
                          <div>
                            语音库预设：
                            {voiceLibraryNameByAudioPath.get(
                              String(normalizedVoice.voice_wan2gp_audio_guide || '').trim()
                            ) || '未设置'}
                          </div>
                        </>
                      )}
                      {normalizedVoice.voice_wan2gp_preset === 'qwen3_tts_voicedesign' && (
                        <div>音色指令：{normalizedVoice.voice_wan2gp_alt_prompt || '未设置'}</div>
                      )}
                      {normalizedVoice.voice_wan2gp_preset !== 'qwen3_tts_customvoice'
                        && normalizedVoice.voice_wan2gp_preset !== 'qwen3_tts_base'
                        && normalizedVoice.voice_wan2gp_preset !== 'qwen3_tts_voicedesign' && (
                        <div>
                          音色：{voiceMeta.resolveVoiceLabel(
                            normalizedVoice.voice_audio_provider,
                            normalizedVoice.voice_name,
                            normalizedVoice.voice_wan2gp_preset
                          )}
                        </div>
                      )}
                      <div>语速：{speedLabel}</div>
                    </>
                  )}
                </div>
                {isCurrentReferenceSpeakInactive && (
                  <>
                    <div className="pointer-events-none absolute inset-0 bg-[repeating-linear-gradient(-45deg,rgba(245,158,11,0.14),rgba(245,158,11,0.14)_8px,transparent_8px,transparent_16px)]" />
                    <div className="absolute right-2 top-2">
                      <Badge
                        variant="secondary"
                        className="cursor-default border border-amber-300/70 bg-amber-100 text-amber-800"
                      >
                        未生效
                      </Badge>
                    </div>
                  </>
                )}
              </div>
              {isCurrentReferenceSpeakInactive && (
                <p className="text-xs text-amber-600">{speakInactiveHintText}</p>
              )}
            </div>
          )}
        </div>

        <div className="space-y-2 xl:sticky xl:top-2 xl:pt-8">
          <div className="flex items-center justify-between">
            <h5 className="text-xs font-medium text-muted-foreground">图片</h5>
            <div className="flex items-center gap-1">
              {onRegenerateReferenceImage && !!currentReferenceAppearanceDesc && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2"
                  onClick={() => {
                    if (!canOperateReference) return
                    void handleRegenerateImage(currentReferenceId)
                  }}
                  disabled={showReferenceGenerating}
                  title="生成参考图片"
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
                  title="删除参考图片"
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
                  <p className="text-sm text-muted-foreground">
                    {referenceProgressText}
                  </p>
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
        </div>
      </div>
    </div>
  )
}
