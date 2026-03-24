'use client'

import {
  X,
  Plus,
  RefreshCw,
  Upload,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { ReferenceVoiceFields } from '@/components/audio/reference-voice-fields'
import type { UseScriptReferencePanelReturn } from '@/hooks/use-script-reference-panel'

interface ScriptReferenceCardNewProps {
  variant: 'has-references' | 'empty-state'
  newReferenceFileInputRef: UseScriptReferencePanelReturn['newReferenceFileInputRef']
  handleNewReferenceFileChange: UseScriptReferencePanelReturn['handleNewReferenceFileChange']
  onOpenNewReferenceFilePicker: UseScriptReferencePanelReturn['handleOpenNewReferenceFilePicker']
  isCreatingReference: UseScriptReferencePanelReturn['isCreatingReference']
  newReferenceName: UseScriptReferencePanelReturn['newReferenceName']
  setNewReferenceName: UseScriptReferencePanelReturn['setNewReferenceName']
  isPendingLockedNarratorReference: UseScriptReferencePanelReturn['isPendingLockedNarratorReference']
  scriptMode: UseScriptReferencePanelReturn['scriptMode']
  pendingLockedNarratorIndex: UseScriptReferencePanelReturn['pendingLockedNarratorIndex']
  newReferenceSetting: UseScriptReferencePanelReturn['newReferenceSetting']
  setNewReferenceSetting: UseScriptReferencePanelReturn['setNewReferenceSetting']
  isPendingNarratorSettingLocked: UseScriptReferencePanelReturn['isPendingNarratorSettingLocked']
  newReferenceAppearanceDesc: UseScriptReferencePanelReturn['newReferenceAppearanceDesc']
  setNewReferenceAppearanceDesc: UseScriptReferencePanelReturn['setNewReferenceAppearanceDesc']
  newReferenceCanSpeak: UseScriptReferencePanelReturn['newReferenceCanSpeak']
  setNewReferenceCanSpeak: UseScriptReferencePanelReturn['setNewReferenceCanSpeak']
  setNewReferenceVoice: UseScriptReferencePanelReturn['setNewReferenceVoice']
  voiceMeta: UseScriptReferencePanelReturn['voiceMeta']
  isNewReferenceSpeakInactive: UseScriptReferencePanelReturn['isNewReferenceSpeakInactive']
  speakInactiveHintText: UseScriptReferencePanelReturn['speakInactiveHintText']
  normalizedNewReferenceVoice: UseScriptReferencePanelReturn['normalizedNewReferenceVoice']
  setShowNewReferenceCard: UseScriptReferencePanelReturn['setShowNewReferenceCard']
  handleCreateReferenceWithoutImage: UseScriptReferencePanelReturn['handleCreateReferenceWithoutImage']
}

export function ScriptReferenceCardNew({
  variant,
  newReferenceFileInputRef,
  handleNewReferenceFileChange,
  onOpenNewReferenceFilePicker,
  isCreatingReference,
  newReferenceName,
  setNewReferenceName,
  isPendingLockedNarratorReference,
  scriptMode,
  pendingLockedNarratorIndex,
  newReferenceSetting,
  setNewReferenceSetting,
  isPendingNarratorSettingLocked,
  newReferenceAppearanceDesc,
  setNewReferenceAppearanceDesc,
  newReferenceCanSpeak,
  setNewReferenceCanSpeak,
  setNewReferenceVoice,
  voiceMeta,
  isNewReferenceSpeakInactive,
  speakInactiveHintText,
  normalizedNewReferenceVoice,
  setShowNewReferenceCard,
  handleCreateReferenceWithoutImage,
}: ScriptReferenceCardNewProps) {
  const isInline = variant === 'has-references'

  return (
    <div className="space-y-4">
      {isInline && (
        <>
          <input
            ref={newReferenceFileInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            onChange={handleNewReferenceFileChange}
          />
          <div
            className={cn(
              'h-60 w-full rounded-lg border-2 border-dashed flex items-center justify-center',
              isCreatingReference ? 'bg-muted/50' : 'bg-muted/30 cursor-pointer hover:bg-muted/50 transition-colors'
            )}
            onClick={onOpenNewReferenceFilePicker}
          >
            {isCreatingReference ? (
              <div className="text-center">
                <RefreshCw className="h-10 w-10 text-muted-foreground mx-auto mb-2 animate-spin" />
                <p className="text-sm text-muted-foreground">创建中...</p>
              </div>
            ) : (
              <div className="text-center">
                <Upload className="h-10 w-10 text-muted-foreground mx-auto mb-2" />
                <p className="text-sm text-muted-foreground">点击上传参考图片</p>
                <p className="text-xs text-muted-foreground/70 mt-1">或先填写信息后点击下方按钮创建</p>
              </div>
            )}
          </div>
        </>
      )}
      <div className="space-y-2">
        <Label htmlFor={isInline ? 'new-reference-name' : 'empty-reference-name'} className={isInline ? undefined : 'text-muted-foreground'}>
          参考名称
        </Label>
        <Input
          id={isInline ? 'new-reference-name' : 'empty-reference-name'}
          value={newReferenceName}
          onChange={(e) => setNewReferenceName(e.target.value)}
          placeholder={isInline ? '输入参考名称...' : '新参考'}
          disabled={isCreatingReference || isPendingLockedNarratorReference}
        />
        {isPendingLockedNarratorReference && (
          <p className="text-xs text-muted-foreground">
            {scriptMode === 'duo_podcast'
              ? `双人播客模式下，前2个参考固定为讲述者（当前为讲述者${pendingLockedNarratorIndex + 1}）。`
              : '单人叙述模式下，首个参考固定为讲述者。'}
          </p>
        )}
      </div>
      <div className="space-y-2">
        <Label htmlFor={isInline ? 'new-reference-setting' : 'empty-reference-setting'} className={isInline ? undefined : 'text-muted-foreground'}>
          参考设定（可选）
        </Label>
        <Textarea
          id={isInline ? 'new-reference-setting' : 'empty-reference-setting'}
          value={newReferenceSetting}
          onChange={(e) => setNewReferenceSetting(e.target.value)}
          className={cn('resize-y', isInline ? 'min-h-[80px]' : 'min-h-[60px]')}
          disabled={isCreatingReference || isPendingNarratorSettingLocked}
        />
        <p className="text-xs text-muted-foreground">
          参考设定写角色身份、性格、语气等人设信息，不写外观细节。
        </p>
        {isPendingNarratorSettingLocked && (
          <p className="text-xs text-amber-600">
            当前为预设讲述者风格，设定由风格自动同步，不能手动编辑。
          </p>
        )}
      </div>
      <div className="space-y-2">
        <Label htmlFor={isInline ? 'new-reference-appearance' : 'empty-reference-appearance'} className={isInline ? undefined : 'text-muted-foreground'}>
          参考外观描述（可选）
        </Label>
        <Textarea
          id={isInline ? 'new-reference-appearance' : 'empty-reference-appearance'}
          value={newReferenceAppearanceDesc}
          onChange={(e) => setNewReferenceAppearanceDesc(e.target.value)}
          className={cn('resize-y', isInline ? 'min-h-[80px]' : 'min-h-[60px]')}
          disabled={isCreatingReference}
        />
        <p className="text-xs text-muted-foreground">
          参考外观描述只写镜头可见外形（发型、服饰、材质、配色、配饰等），不写性格设定。
        </p>
      </div>
      <div className="space-y-2">
        <Label htmlFor={isInline ? 'new-reference-can-speak' : 'empty-reference-can-speak'} className={isInline ? undefined : 'text-muted-foreground'}>
          是否可说台词
        </Label>
        <Select
          value={newReferenceCanSpeak ? 'true' : 'false'}
          onValueChange={(value) => {
            const canSpeak = value !== 'false'
            setNewReferenceCanSpeak(canSpeak)
            if (canSpeak) {
              setNewReferenceVoice((prev) => voiceMeta.normalizeConfig(prev))
            }
          }}
          disabled={isCreatingReference || isPendingLockedNarratorReference}
        >
          <SelectTrigger id={isInline ? 'new-reference-can-speak' : 'empty-reference-can-speak'}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="true">可说台词</SelectItem>
            <SelectItem value="false">不可说台词（如场景）</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {isNewReferenceSpeakInactive && speakInactiveHintText && (
        <SpeakInactiveNotice hintText={speakInactiveHintText} />
      )}
      {newReferenceCanSpeak && (
        <ReferenceVoiceFields
          value={normalizedNewReferenceVoice}
          onChange={setNewReferenceVoice}
          meta={voiceMeta}
          disabled={isCreatingReference}
        />
      )}
      <div className={cn('flex gap-2', isInline ? 'justify-end' : 'justify-end')}>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setShowNewReferenceCard(false)}
          disabled={isCreatingReference}
        >
          <X className="h-4 w-4 mr-1" />
          取消
        </Button>
        <Button
          size="sm"
          variant={isInline ? 'default' : 'outline'}
          onClick={handleCreateReferenceWithoutImage}
          disabled={isCreatingReference || !newReferenceName.trim()}
        >
          <Plus className="h-4 w-4 mr-1" />
          {isCreatingReference ? '创建中...' : '创建参考（无图片）'}
        </Button>
      </div>
    </div>
  )
}

export function SpeakInactiveNotice({ hintText }: { hintText: string }) {
  return (
    <div className="relative overflow-hidden rounded-lg border border-dashed border-amber-400/60 bg-amber-50/40 p-3 dark:bg-amber-500/10">
      <div className="pointer-events-none absolute inset-0 bg-[repeating-linear-gradient(-45deg,rgba(245,158,11,0.14),rgba(245,158,11,0.14)_8px,transparent_8px,transparent_16px)]" />
      <div className="relative flex items-start justify-between gap-2">
        <p className="text-xs text-amber-600">{hintText}</p>
        <Badge
          variant="secondary"
          className="cursor-default border border-amber-300/70 bg-amber-100 text-amber-800"
        >
          未生效
        </Badge>
      </div>
    </div>
  )
}
