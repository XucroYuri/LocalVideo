import { Play, Loader2, RotateCcw, Check, Download } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import {
  getImageDefaults,
  getWan2gpDefaults,
  getScopedWan2gpInferenceSteps,
} from '@/lib/stage-panel-helpers'
import type { Wan2gpImagePreset, Settings } from '@/types/settings'
import type { StageConfig, StageStatus, TabType } from '@/types/stage-panel'
import type { BackendStageType } from '@/types/stage'

interface StagePanelActionButtonsProps {
  activeTab: TabType
  stageStatus: StageStatus
  isRunning: boolean
  runningStage?: BackendStageType
  runningAction?: string
  onRunStage: (stage: BackendStageType, config: StageConfig, inputData?: Record<string, unknown>) => void
  config: StageConfig
  effectiveScriptMode: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'
  isSingleTakeEnabled: boolean
  effectiveUseFirstFrameRef: boolean
  hasReferenceData: boolean
  isReferenceImageComplete: boolean
  hasVideoPromptReady: boolean
  settings: Settings | undefined
  getConfiguredImageProviders: () => string[]
  resolveEffectiveImageProvider: (providers: string[]) => string
  resolveWan2gpPreset: (
    presetId: string,
    presetType: 't2i' | 'i2i'
  ) => Wan2gpImagePreset | undefined
  composeVideoUrl?: string
  isExportingVideo: boolean
  onExportVideo: () => void
}

export function StagePanelActionButtons({
  activeTab,
  stageStatus,
  isRunning,
  runningStage,
  runningAction,
  onRunStage,
  config,
  effectiveScriptMode,
  isSingleTakeEnabled,
  effectiveUseFirstFrameRef,
  hasReferenceData,
  isReferenceImageComplete,
  hasVideoPromptReady,
  settings,
  getConfiguredImageProviders,
  resolveEffectiveImageProvider,
  resolveWan2gpPreset,
  composeVideoUrl,
  isExportingVideo,
  onExportVideo,
}: StagePanelActionButtonsProps) {
  const renderStageButton = (
    stage: BackendStageType,
    label: string,
    variant: 'default' | 'outline' | 'secondary' = 'outline'
  ) => {
    const status = stageStatus[stage]
    const isThisRunning = isRunning && (
      stage === 'finalize'
        ? runningStage === 'compose'
          || runningStage === 'subtitle'
          || runningStage === 'burn_subtitle'
          || runningStage === 'finalize'
        : runningStage === stage
    )
    const isCompleted = status === 'completed' || status === 'skipped'
    const isFailed = status === 'failed'

    return (
      <Button
        variant={variant}
        size="sm"
        className={cn(
          'flex-1',
          isCompleted && 'border-green-500 text-green-600',
          isFailed && 'border-red-500 text-red-600'
        )}
        onClick={() => onRunStage(stage, config)}
        disabled={isRunning}
      >
        {isThisRunning ? (
          <Loader2 className="h-4 w-4 animate-spin mr-1" />
        ) : isCompleted ? (
          <Check className="h-4 w-4 mr-1" />
        ) : isFailed ? (
          <RotateCcw className="h-4 w-4 mr-1" />
        ) : (
          <Play className="h-4 w-4 mr-1" />
        )}
        {label}
      </Button>
    )
  }

  const renderReferenceInfoButton = () => {
    const status = stageStatus.reference
    const isThisRunning = isRunning && runningStage === 'reference' && runningAction === 'generate_info'
    const isCompleted = hasReferenceData
    const isFailed = status === 'failed' && !hasReferenceData

    return (
      <Button
        variant="outline"
        size="sm"
        className={cn(
          'flex-1',
          isCompleted && 'border-green-500 text-green-600',
          isFailed && 'border-red-500 text-red-600'
        )}
        onClick={() => onRunStage('reference', config, { action: 'generate_info' })}
        disabled={isRunning}
      >
        {isThisRunning ? (
          <Loader2 className="h-4 w-4 animate-spin mr-1" />
        ) : isCompleted ? (
          <Check className="h-4 w-4 mr-1" />
        ) : isFailed ? (
          <RotateCcw className="h-4 w-4 mr-1" />
        ) : (
          <Play className="h-4 w-4 mr-1" />
        )}
        推断并新增参考信息
      </Button>
    )
  }

  const renderReferenceImageButton = () => {
    const status = stageStatus.reference
    const isThisRunning = isRunning && runningStage === 'reference' && runningAction === 'generate_images'
    const hasImages = isReferenceImageComplete
    const isFailed = status === 'failed' && !hasImages
    const imageProviders = getConfiguredImageProviders()
    const effectiveImageProvider = resolveEffectiveImageProvider(imageProviders)
    const onlineDefaults = getImageDefaults(effectiveImageProvider, settings, 'reference')
    const wan2gpDefaults = getWan2gpDefaults(settings)
    const selectedWan2gpPreset = resolveWan2gpPreset(
      config.imageWan2gpPreset || wan2gpDefaults.preset,
      't2i'
    )
    const referenceWan2gpSteps =
      getScopedWan2gpInferenceSteps(config, 't2i')
      || selectedWan2gpPreset?.inference_steps
      || wan2gpDefaults.inferenceSteps
      || 20

    return (
      <Button
        variant="outline"
        size="sm"
        className={cn(
          'flex-1',
          hasImages && 'border-green-500 text-green-600',
          isFailed && 'border-red-500 text-red-600'
        )}
        onClick={() => onRunStage('reference', config, {
          action: 'generate_images',
          image_provider: effectiveImageProvider,
          ...(effectiveImageProvider === 'wan2gp'
            ? {
                image_wan2gp_preset: config.imageWan2gpPreset || wan2gpDefaults.preset,
                image_resolution: config.referenceImageResolution || wan2gpDefaults.referenceResolution,
                image_wan2gp_inference_steps: referenceWan2gpSteps,
              }
            : {
                image_aspect_ratio: config.referenceAspectRatio || onlineDefaults.aspectRatio,
                image_size: config.referenceImageSize || onlineDefaults.size,
              }),
          ...(config.imageStyle?.trim() ? { image_style: config.imageStyle.trim() } : {}),
          max_concurrency: effectiveImageProvider === 'wan2gp' ? 1 : (config.maxConcurrency || 4),
        })}
        disabled={isRunning || !hasReferenceData}
        title={!hasReferenceData ? '请先推断并新增参考信息' : undefined}
      >
        {isThisRunning ? (
          <Loader2 className="h-4 w-4 animate-spin mr-1" />
        ) : hasImages ? (
          <Check className="h-4 w-4 mr-1" />
        ) : isFailed ? (
          <RotateCcw className="h-4 w-4 mr-1" />
        ) : (
          <Play className="h-4 w-4 mr-1" />
        )}
        生成参考图
      </Button>
    )
  }

  const renderVideoPromptButton = () => {
    const status = stageStatus.storyboard
    const isThisRunning = isRunning && runningStage === 'storyboard'
    const isCompleted = status === 'completed'
    const isFailed = status === 'failed'

    return (
      <Button
        variant="outline"
        size="sm"
        className={cn(
          'flex-1',
          isCompleted && 'border-green-500 text-green-600',
          isFailed && 'border-red-500 text-red-600'
        )}
        onClick={() => onRunStage('storyboard', config, {
          use_first_frame_ref: effectiveUseFirstFrameRef,
          use_reference_image_ref: config.useReferenceImageRef ?? false,
          single_take: isSingleTakeEnabled,
        })}
        disabled={isRunning}
      >
        {isThisRunning ? (
          <Loader2 className="h-4 w-4 animate-spin mr-1" />
        ) : isCompleted ? (
          <Check className="h-4 w-4 mr-1" />
        ) : isFailed ? (
          <RotateCcw className="h-4 w-4 mr-1" />
        ) : (
          <Play className="h-4 w-4 mr-1" />
        )}
        生成分镜
      </Button>
    )
  }

  const renderFirstFrameDescButton = () => {
    const status = stageStatus.first_frame_desc
    const isThisRunning = isRunning && runningStage === 'first_frame_desc'
    const isCompleted = status === 'completed'
    const isFailed = status === 'failed'

    return (
      <Button
        variant="outline"
        size="sm"
        className={cn(
          'flex-1',
          isCompleted && 'border-green-500 text-green-600',
          isFailed && 'border-red-500 text-red-600'
        )}
        onClick={() => {
          if (!hasVideoPromptReady) {
            toast.info('请先生成分镜')
            return
          }
          onRunStage('first_frame_desc', config, {
            single_take: isSingleTakeEnabled,
            ...(effectiveScriptMode === 'duo_podcast' ? { only_shot_index: 0 } : {}),
          })
        }}
        disabled={isRunning}
      >
        {isThisRunning ? (
          <Loader2 className="h-4 w-4 animate-spin mr-1" />
        ) : isCompleted ? (
          <Check className="h-4 w-4 mr-1" />
        ) : isFailed ? (
          <RotateCcw className="h-4 w-4 mr-1" />
        ) : (
          <Play className="h-4 w-4 mr-1" />
        )}
        生成首帧描述
      </Button>
    )
  }

  switch (activeTab) {
    case 'script':
      return (
        <div className="space-y-2">
          <div className="flex gap-2">
            {effectiveScriptMode !== 'custom' && renderStageButton('content', '一键生成文案')}
          </div>
          <div className="flex gap-2">
            {renderReferenceInfoButton()}
            {renderReferenceImageButton()}
          </div>
        </div>
      )
    case 'shots':
      return (
        <div className="space-y-2">
          <div className="flex gap-2">
            {renderVideoPromptButton()}
            {renderStageButton('audio', '生成音频')}
          </div>
          <div className="flex gap-2">
            {renderFirstFrameDescButton()}
            {renderStageButton(
              'frame',
              effectiveScriptMode === 'duo_podcast' ? '生成并复用首帧图' : '生成首帧图'
            )}
          </div>
          <div className="flex gap-2">
            {renderStageButton('video', '生成视频')}
          </div>
        </div>
      )
    case 'compose':
      return (
        <div className="flex gap-2">
          {renderStageButton('finalize', '生成成片', 'outline')}
          <Button
            variant="default"
            size="sm"
            className="flex-1"
            onClick={onExportVideo}
            disabled={!composeVideoUrl || isExportingVideo}
          >
            {isExportingVideo ? (
              <Loader2 className="h-4 w-4 animate-spin mr-1" />
            ) : (
              <Download className="h-4 w-4 mr-1" />
            )}
            {isExportingVideo ? '导出中...' : '视频导出'}
          </Button>
        </div>
      )
    default:
      return null
  }
}
