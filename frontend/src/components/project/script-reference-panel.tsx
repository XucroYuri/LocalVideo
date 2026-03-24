'use client'

import {
  ChevronLeft,
  ChevronRight,
  User,
  RefreshCw,
  Upload,
  Plus,
  Trash2,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { ScriptReferenceImportDialog } from '@/components/project/script-reference-import-dialog'
import { ScriptReferenceDeleteDialog } from '@/components/project/script-reference-delete-dialog'
import { ScriptReferenceCardNew } from '@/components/project/script-reference-card-new'
import { ScriptReferenceCardEdit } from '@/components/project/script-reference-card-edit'
import { ScriptReferenceCardView } from '@/components/project/script-reference-card-view'
import { useScriptReferencePanel } from '@/hooks/use-script-reference-panel'
import type { ScriptTabContentProps } from '@/components/project/script-tab-content.types'

type ScriptReferencePanelProps = Pick<ScriptTabContentProps,
  | 'stageData'
  | 'generatingShots'
  | 'runningStage'
  | 'runningAction'
  | 'runningReferenceId'
  | 'progress'
  | 'progressMessage'
  | 'referenceStageStatus'
  | 'configuredScriptMode'
  | 'narratorStyle'
  | 'onSaveReference'
  | 'onDeleteReference'
  | 'onRegenerateReferenceImage'
  | 'onUploadReferenceImage'
  | 'onCreateReference'
  | 'onGenerateDescriptionFromImage'
  | 'onDeleteReferenceImage'
  | 'libraryReferences'
  | 'onImportReferencesFromLibrary'
> & {
  activeScriptModeForConstraint: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'
}

export function ScriptReferencePanel({
  libraryReferences = [],
  ...rest
}: ScriptReferencePanelProps) {
  const hook = useScriptReferencePanel({ ...rest, libraryReferences })
  const {
    hasReferences,
    onImportReferencesFromLibrary,
    showNewReferenceCard,
    handleOpenImportDialog,
    safeCurrentReferenceIndex,
    isCurrentLockedNarratorReference,
    scriptMode,
    isCurrentLockedDuoSceneReference,
    currentReference,
    onDeleteReference,
    isCurrentFixedReference,
    handleDeleteClick,
    referenceConstraintHintText,
    newReferenceName,
    setNewReferenceName,
    isPendingLockedNarratorReference,
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
    handleCreateReferenceWithoutImage,
    fileInputRef,
    handleFileChange,
    isCurrentReferenceCanSpeak,
    isCurrentReferenceSpeakInactive,
    isCurrentNarratorSettingLocked,
    currentReferenceSetting,
    currentReferenceAppearanceDesc,
    voiceLibraryNameByAudioPath,
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
    handlePrevReference,
    references,
    setShowNewReferenceCard,
    setCurrentReferenceIndex,
    onCreateReference,
    handleNewReferenceClick,
    handleNextReference,
    newReferenceFileInputRef,
    handleNewReferenceFileChange,
    isCreatingReference,
    handleOpenNewReferenceFilePicker,
    showImportDialog,
    setShowImportDialog,
    importSettingChecked,
    setImportSettingChecked,
    importAppearanceChecked,
    setImportAppearanceChecked,
    importImageChecked,
    setImportImageChecked,
    importVoiceChecked,
    setImportVoiceChecked,
    selectedImportCount,
    handleImportAllSelection,
    importStartReferenceIndex,
    overwriteReferencePreview,
    appendCountPreview,
    importSelectionOrder,
    handleToggleImportSelection,
    importResult,
    isImportingReferences,
    handleConfirmImportFromLibrary,
    showDeleteDialog,
    setShowDeleteDialog,
    referenceToDelete,
    isDeleting,
    handleCancelDelete,
    handleConfirmDelete,
  } = hook

  const handleDeleteCurrentReference = () => {
    if (!currentReference) return
    handleDeleteClick(currentReference)
  }

  const newCardProps = {
    newReferenceFileInputRef,
    handleNewReferenceFileChange,
    onOpenNewReferenceFilePicker: handleOpenNewReferenceFilePicker,
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
  }

  const viewCardProps = {
    fileInputRef,
    onFileChange: handleFileChange,
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
  }

  return (
    <>
      {hasReferences ? (
        <div className="space-y-3">
          <Card className="py-0">
            <CardContent className="p-4 space-y-4">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-medium flex items-center gap-2">
                  <User className="h-4 w-4" />
                  参考
                </h4>
                <div className="flex items-center gap-1">
                  {onImportReferencesFromLibrary && !showNewReferenceCard && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 px-2 text-foreground hover:text-foreground"
                      onClick={() => handleOpenImportDialog(safeCurrentReferenceIndex)}
                    >
                      <Upload className="h-3 w-3 mr-1" />
                      从已有参考导入
                    </Button>
                  )}
                  {isCurrentLockedNarratorReference && !showNewReferenceCard && (
                    <Badge variant="secondary">
                      {scriptMode === 'duo_podcast'
                        ? `讲述者${safeCurrentReferenceIndex + 1}（固定）`
                        : '讲述者（固定）'}
                    </Badge>
                  )}
                  {isCurrentLockedDuoSceneReference && !showNewReferenceCard && (
                    <Badge variant="secondary">播客场景（固定）</Badge>
                  )}
                  {onDeleteReference && !showNewReferenceCard && !isCurrentFixedReference && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 px-2 text-foreground hover:text-foreground"
                      onClick={handleDeleteCurrentReference}
                    >
                      <Trash2 className="h-3 w-3 mr-1" />
                      删除
                    </Button>
                  )}
                </div>
              </div>
              {referenceConstraintHintText && <p className="text-xs text-amber-600">{referenceConstraintHintText}</p>}

              {showNewReferenceCard ? (
                <ScriptReferenceCardNew
                  variant="has-references"
                  {...newCardProps}
                />
              ) : currentReference ? (
                <ScriptReferenceCardEdit hook={hook} />
              ) : (
                <ScriptReferenceCardView {...viewCardProps} />
              )}
            </CardContent>
          </Card>
          <div className="flex items-center justify-center gap-4">
            <Button variant="ghost" size="icon" onClick={handlePrevReference} disabled={references.length <= 1}>
              <ChevronLeft className="h-5 w-5" />
            </Button>
            <div className="flex items-center gap-2">
              {references.map((_, idx) => (
                <button
                  key={idx}
                  onClick={() => {
                    setShowNewReferenceCard(false)
                    setCurrentReferenceIndex(idx)
                  }}
                  className={cn(
                    'w-2 h-2 rounded-full transition-colors',
                    idx === safeCurrentReferenceIndex && !showNewReferenceCard ? 'bg-primary' : 'bg-muted-foreground/30'
                  )}
                />
              ))}
              {onCreateReference && (
                <button
                  onClick={handleNewReferenceClick}
                  className={cn(
                    'w-5 h-5 rounded-full transition-colors flex items-center justify-center border-2 border-dashed',
                    showNewReferenceCard ? 'border-primary bg-primary/10' : 'border-muted-foreground/30 hover:border-primary/50'
                  )}
                  title="添加新参考"
                >
                  <Plus className="h-3 w-3 text-muted-foreground" />
                </button>
              )}
            </div>
            <span className="text-sm text-muted-foreground min-w-[60px] text-center">
              {showNewReferenceCard ? '新增' : `${safeCurrentReferenceIndex + 1} / ${references.length}`}
            </span>
            <Button variant="ghost" size="icon" onClick={handleNextReference} disabled={references.length <= 1}>
              <ChevronRight className="h-5 w-5" />
            </Button>
          </div>
        </div>
      ) : (
        <Card className="py-0">
          <CardContent className="p-4 space-y-4">
            <div className="flex items-center justify-between">
                <h4 className="text-sm font-medium flex items-center gap-2">
                  <User className="h-4 w-4" />
                  参考
                </h4>
                <div className="flex items-center gap-1">
                {onImportReferencesFromLibrary && (
                  <Button variant="ghost" size="sm" className="h-6 px-2" onClick={() => handleOpenImportDialog(0)}>
                    <Upload className="h-3 w-3 mr-1" />
                    从已有参考导入
                  </Button>
                )}
                {onCreateReference && !showNewReferenceCard && (
                  <Button variant="ghost" size="sm" className="h-6 px-2" onClick={handleNewReferenceClick}>
                    <Plus className="h-3 w-3 mr-1" />
                    新增参考
                  </Button>
                )}
              </div>
            </div>
            {referenceConstraintHintText && <p className="text-xs text-amber-600">{referenceConstraintHintText}</p>}
            <input
              ref={newReferenceFileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              onChange={handleNewReferenceFileChange}
            />
            <div
              className={cn(
                'h-40 w-full rounded-lg border-2 border-dashed flex items-center justify-center',
                isCreatingReference || !onCreateReference ? 'bg-muted/30' : 'bg-muted/30 cursor-pointer hover:bg-muted/50 transition-colors'
              )}
              onClick={handleOpenNewReferenceFilePicker}
            >
              {isCreatingReference ? (
                <div className="text-center">
                  <RefreshCw className="h-10 w-10 text-muted-foreground mx-auto mb-2 animate-spin" />
                  <p className="text-sm text-muted-foreground">创建中...</p>
                </div>
              ) : onCreateReference ? (
                <div className="text-center">
                  <Upload className="h-10 w-10 text-muted-foreground mx-auto mb-2" />
                  <p className="text-sm text-muted-foreground">直接上传图片创建参考</p>
                  <p className="text-xs text-muted-foreground/70 mt-1">或点击「推断并新增参考信息」按钮自动生成</p>
                </div>
              ) : (
                <div className="text-center">
                  <User className="h-10 w-10 text-muted-foreground mx-auto mb-2 opacity-50" />
                  <p className="text-sm text-muted-foreground">点击「推断并新增参考信息」按钮生成参考内容</p>
                </div>
              )}
            </div>
            {onCreateReference && showNewReferenceCard && (
              <ScriptReferenceCardNew
                variant="empty-state"
                {...newCardProps}
              />
            )}
          </CardContent>
        </Card>
      )}

      <ScriptReferenceImportDialog
        open={showImportDialog}
        onOpenChange={setShowImportDialog}
        importSettingChecked={importSettingChecked}
        onImportSettingCheckedChange={setImportSettingChecked}
        importAppearanceChecked={importAppearanceChecked}
        onImportAppearanceCheckedChange={setImportAppearanceChecked}
        importImageChecked={importImageChecked}
        onImportImageCheckedChange={setImportImageChecked}
        importVoiceChecked={importVoiceChecked}
        onImportVoiceCheckedChange={setImportVoiceChecked}
        selectedImportCount={selectedImportCount}
        libraryReferences={libraryReferences}
        onSelectAll={() => handleImportAllSelection(true)}
        onClearAll={() => handleImportAllSelection(false)}
        importStartReferenceIndex={importStartReferenceIndex}
        overwriteReferencePreview={overwriteReferencePreview}
        appendCountPreview={appendCountPreview}
        importSelectionOrder={importSelectionOrder}
        onToggleImportSelection={handleToggleImportSelection}
        importResult={importResult}
        isImportingReferences={isImportingReferences}
        onConfirm={() => void handleConfirmImportFromLibrary()}
      />

      <ScriptReferenceDeleteDialog
        open={showDeleteDialog}
        onOpenChange={setShowDeleteDialog}
        referenceName={referenceToDelete?.name || ''}
        isDeleting={isDeleting}
        onCancel={handleCancelDelete}
        onConfirm={handleConfirmDelete}
      />
    </>
  )
}
