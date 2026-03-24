'use client'

import { use } from 'react'
import Link from 'next/link'
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { SourcePanel } from '@/components/project/source-panel'
import { ContentPanel } from '@/components/project/content-panel'
import { StagePanel } from '@/components/project/stage-panel'
import useProjectDetail from '@/hooks/use-project-detail'
import { normalizeDialogueScriptMaxRoles } from '@/lib/dialogue-limits'
import type { ReferenceLibraryItem } from '@/types/reference'

interface PageProps {
  params: Promise<{ id: string }>
}

export default function ProjectDetailPage({ params }: PageProps) {
  const { id } = use(params)
  const projectId = parseInt(id, 10)

  const {
    projectLoading,
    project,
    activeTab,
    setActiveTab,
    isRunning,
    runningStage,
    runningAction,
    progress,
    progressMessage,
    completedItems,
    totalItems,
    skippedItems,
    generatingShots,
    runningShotIndex,
    runningReferenceId,
    isSearching,
    stageConfig,
    handleStageConfigChange,
    sources,
    stageData,
    stageStatus,
    stageCompletion,
    settings,
    stageStatusFromList,
    isSingleTakeEnabled,
    effectiveUseFirstFrameRef,
    hasReferenceData,
    referenceStageStatus,
    frameStageStatus,
    videoStageStatus,
    libraryReferences,
    textLibraryItems,
    cancelIsPending,
    composeVideoUrl,
    contentScriptMode,
    handleSearch,
    handleAddText,
    handleImportFromTextLibrary,
    handleToggleSelected,
    handleDeleteSource,
    handleSaveContent,
    handleContentChatSend,
    handleContentChatReset,
    handleDeleteContent,
    handleUnlockContentByClearingShots,
    handleImportDialogue,
    handleSaveReference,
    handleDeleteReference,
    handleRegenerateReferenceImage,
    handleUploadReferenceImage,
    handleCreateReference,
    handleGenerateDescriptionFromImage,
    handleSaveFrameDescription,
    handleGenerateFrameDescription,
    handleSaveFrameReferences,
    handleRegenerateFrameImage,
    handleReuseFirstFrameToOthers,
    handleUploadFrameImage,
    handleDeleteFrameImage,
    handleClearAllAudio,
    handleClearAllFrameImages,
    handleRegenerateVideo,
    handleGenerateVideoDescription,
    handleSaveVideoDescription,
    handleSaveVideoReferences,
    handleDeleteVideo,
    handleClearAllVideos,
    handleClearAllShotContent,
    handleSmartMergeShots,
    handleInsertShots,
    handleMoveShot,
    handleDeleteShot,
    handleUpdateShot,
    handleRegenerateAudio,
    handleDeleteReferenceImage,
    handleDeleteComposeVideo,
    handleImportReferencesFromLibrary,
    handleCancelAllRunningTasks,
    handleRunStageWithStoryboardConfirm,
    handleSingleTakeModeTransition,
    handleNarratorStyleChange,
  } = useProjectDetail(projectId)

  const referenceStage = { status: referenceStageStatus }
  const frameStage = { status: frameStageStatus }
  const videoStage = { status: videoStageStatus }
  const referenceLibraryData = { items: libraryReferences }
  const cancelRunningTasksMutation = { isPending: cancelIsPending }

  if (projectLoading || !settings) {
    return (
      <div className="h-full flex">
        <Skeleton className="w-80 h-full" />
        <Skeleton className="flex-1 h-full" />
        <Skeleton className="w-80 h-full" />
      </div>
    )
  }

  if (!project) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <p className="text-muted-foreground mb-4">项目不存在</p>
          <Button asChild>
            <Link href="/">返回首页</Link>
          </Button>
        </div>
      </div>
    )
  }

  const showSourcePanel = activeTab === 'script'
  const stagePanelDefaultSize = 20
  const contentPanelDefaultSize = showSourcePanel ? 48 : 70
  return (
    <div className="absolute inset-0 overflow-hidden">
      <ResizablePanelGroup orientation="horizontal" className="h-full">
        {showSourcePanel && (
          <>
            <ResizablePanel defaultSize="22%" minSize="15%" maxSize="35%" id="left-script-panel">
              <SourcePanel
                projectId={projectId}
                sources={sources}
                onSearch={handleSearch}
                onAddText={handleAddText}
                textLibraryItems={textLibraryItems}
                onImportFromTextLibrary={handleImportFromTextLibrary}
                onToggleSelected={handleToggleSelected}
                onDeleteSource={handleDeleteSource}
                isSearching={isSearching}
              />
            </ResizablePanel>
            <ResizableHandle withHandle />
          </>
        )}

        <ResizablePanel defaultSize={`${contentPanelDefaultSize}%`} minSize="25%" id="content-panel">
          <ContentPanel
            activeTab={activeTab}
            stageData={stageData}
            showScriptReferencePanel={activeTab === 'script'}
            generatingShots={generatingShots}
            runningStage={runningStage}
            runningAction={runningAction}
            runningReferenceId={runningReferenceId}
            progress={progress}
            progressMessage={progressMessage}
            referenceStageStatus={referenceStage?.status || stageStatusFromList.reference}
            frameStageStatus={frameStage?.status || stageStatusFromList.frame}
            videoStageStatus={videoStage?.status || stageStatusFromList.video}
            runningShotIndex={runningShotIndex}
            configuredScriptMode={stageConfig.scriptMode}
            narratorStyle={stageConfig.style}
            dialogueScriptMaxRoles={normalizeDialogueScriptMaxRoles(settings?.dialogue_script_max_roles)}
            includeSubtitle={stageConfig.includeSubtitle ?? true}
            useReferenceImageRef={stageConfig.useReferenceImageRef ?? false}
            singleTakeEnabled={isSingleTakeEnabled}
            useFirstFrameRef={effectiveUseFirstFrameRef}
            useReferenceConsistency={stageConfig.useReferenceConsistency ?? false}
            onSaveContent={handleSaveContent}
            onContentChatSend={handleContentChatSend}
            onContentChatReset={handleContentChatReset}
            isContentChatRunning={runningStage === 'content'}
            onDeleteContent={handleDeleteContent}
            onUnlockContentByClearingShots={handleUnlockContentByClearingShots}
            onImportDialogue={handleImportDialogue}
            onSaveReference={handleSaveReference}
            onDeleteReference={handleDeleteReference}
            onRegenerateReferenceImage={handleRegenerateReferenceImage}
            onUploadReferenceImage={handleUploadReferenceImage}
            onCreateReference={handleCreateReference}
            onGenerateDescriptionFromImage={handleGenerateDescriptionFromImage}
            onSaveFrameDescription={handleSaveFrameDescription}
            onGenerateFrameDescription={handleGenerateFrameDescription}
            onSaveFrameReferences={handleSaveFrameReferences}
            onRegenerateFrameImage={handleRegenerateFrameImage}
            onReuseFirstFrameToOthers={handleReuseFirstFrameToOthers}
            onUploadFrameImage={handleUploadFrameImage}
            onDeleteFrameImage={handleDeleteFrameImage}
            onClearAllAudio={handleClearAllAudio}
            onClearAllFrameImages={handleClearAllFrameImages}
            onRegenerateVideo={handleRegenerateVideo}
            onGenerateVideoDescription={handleGenerateVideoDescription}
            onSaveVideoDescription={handleSaveVideoDescription}
            onSaveVideoReferences={handleSaveVideoReferences}
            onDeleteVideo={handleDeleteVideo}
            onClearAllVideos={handleClearAllVideos}
            onClearAllShotContent={handleClearAllShotContent}
            onSmartMergeShots={handleSmartMergeShots}
            onInsertShots={handleInsertShots}
            onMoveShot={handleMoveShot}
            onDeleteShot={handleDeleteShot}
            onUpdateShot={handleUpdateShot}
            onRegenerateAudio={handleRegenerateAudio}
            onDeleteReferenceImage={handleDeleteReferenceImage}
            onDeleteComposeVideo={handleDeleteComposeVideo}
            libraryReferences={(referenceLibraryData?.items || []) as ReferenceLibraryItem[]}
            onImportReferencesFromLibrary={handleImportReferencesFromLibrary}
          />
        </ResizablePanel>

        <ResizableHandle withHandle />

        <ResizablePanel defaultSize={`${stagePanelDefaultSize}%`} minSize="18%" maxSize="40%" id="stage-panel">
          <StagePanel
            activeTab={activeTab}
            onTabChange={setActiveTab}
            stageStatus={stageStatus}
            isRunning={isRunning}
            runningStage={runningStage}
            runningAction={runningAction}
            progress={progress}
            progressMessage={progressMessage}
            completedItems={completedItems}
            totalItems={totalItems}
            skippedItems={skippedItems}
            isCancelling={cancelRunningTasksMutation.isPending}
            onCancelAllRunningTasks={handleCancelAllRunningTasks}
            onRunStage={handleRunStageWithStoryboardConfirm}
            config={stageConfig}
            onConfigChange={handleStageConfigChange}
            hasReferenceData={hasReferenceData}
            isReferenceImageComplete={stageCompletion.referenceImageReady}
            hasVideoPromptReady={stageCompletion.storyboardReady}
            projectTitle={project.title}
            composeVideoUrl={composeVideoUrl}
            composeVideoShots={stageData?.video?.shots || []}
            contentScriptMode={contentScriptMode}
            onSingleTakeModeTransition={handleSingleTakeModeTransition}
            onNarratorStyleChange={handleNarratorStyleChange}
          />
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  )
}
