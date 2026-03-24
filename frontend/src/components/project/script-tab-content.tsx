'use client'

import { ScriptContentPanel } from '@/components/project/script-content-panel'
import { ScriptReferencePanel } from '@/components/project/script-reference-panel'
import type { ScriptTabContentProps } from '@/components/project/script-tab-content.types'
import { resolveScriptMode } from '@/lib/content-panel-helpers'
import { DEFAULT_DIALOGUE_SCRIPT_MAX_ROLES } from '@/lib/dialogue-limits'

export function ScriptTabContent({
  stageData,
  generatingShots,
  runningStage,
  runningAction,
  runningReferenceId,
  progress,
  progressMessage,
  referenceStageStatus,
  configuredScriptMode,
  narratorStyle,
  dialogueScriptMaxRoles = DEFAULT_DIALOGUE_SCRIPT_MAX_ROLES,
  onSaveContent,
  onDeleteContent,
  onUnlockContentByClearingShots,
  onImportDialogue,
  onSaveReference,
  onDeleteReference,
  onRegenerateReferenceImage,
  onUploadReferenceImage,
  onCreateReference,
  onGenerateDescriptionFromImage,
  onDeleteReferenceImage,
  libraryReferences = [],
  onImportReferencesFromLibrary,
  showReferencePanel = true,
}: ScriptTabContentProps) {
  const scriptMode = resolveScriptMode(
    configuredScriptMode || stageData?.content?.script_mode
  )

  return (
    <div className="h-full flex flex-col">
      <div className="min-h-0 flex-1 overflow-auto p-6">
        <div className="space-y-4 pr-1">
          <ScriptContentPanel
            stageData={stageData}
            runningStage={runningStage}
            progress={progress}
            progressMessage={progressMessage}
            configuredScriptMode={configuredScriptMode}
            dialogueScriptMaxRoles={dialogueScriptMaxRoles}
            onSaveContent={onSaveContent}
            onDeleteContent={onDeleteContent}
            onUnlockContentByClearingShots={onUnlockContentByClearingShots}
            onImportDialogue={onImportDialogue}
          />

          {showReferencePanel && (
            <ScriptReferencePanel
              stageData={stageData}
              generatingShots={generatingShots}
              runningStage={runningStage}
              runningAction={runningAction}
              runningReferenceId={runningReferenceId}
              progress={progress}
              progressMessage={progressMessage}
              referenceStageStatus={referenceStageStatus}
              configuredScriptMode={configuredScriptMode}
              narratorStyle={narratorStyle}
              onSaveReference={onSaveReference}
              onDeleteReference={onDeleteReference}
              onRegenerateReferenceImage={onRegenerateReferenceImage}
              onUploadReferenceImage={onUploadReferenceImage}
              onCreateReference={onCreateReference}
              onGenerateDescriptionFromImage={onGenerateDescriptionFromImage}
              onDeleteReferenceImage={onDeleteReferenceImage}
              libraryReferences={libraryReferences}
              onImportReferencesFromLibrary={onImportReferencesFromLibrary}
              activeScriptModeForConstraint={scriptMode}
            />
          )}
        </div>
      </div>
    </div>
  )
}
