export type TabType = 'script' | 'shots' | 'compose'

export interface RoleAudioConfig {
  audioProvider?: string
  voice?: string
  speed?: number
  audioWan2gpPreset?: string
  audioWan2gpModelMode?: string
  audioWan2gpAltPrompt?: string
  audioWan2gpDurationSeconds?: number
  audioWan2gpTemperature?: number
  audioWan2gpTopK?: number
  audioWan2gpSeed?: number
  audioWan2gpAudioGuide?: string
}

export interface StageConfig {
  scriptMode?: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'
  duoPodcastCameraMode?: 'same_frame' | 'speaker_focus'
  llmProvider?: string
  llmModel?: string
  textTargetLanguage?: 'zh' | 'en'
  textPromptComplexity?: 'minimal' | 'simple' | 'normal' | 'detailed' | 'complex' | 'ultra'
  storyboardShotDensity?: 'low' | 'medium' | 'high'
  style?: string
  targetDuration?: number
  audioProvider?: string
  voice?: string
  speed?: number
  audioMaxConcurrency?: number
  audioWan2gpPreset?: string
  audioWan2gpModelMode?: string
  audioWan2gpAltPrompt?: string
  audioWan2gpDurationSeconds?: number
  audioWan2gpTemperature?: number
  audioWan2gpTopK?: number
  audioWan2gpSeed?: number
  audioWan2gpAudioGuide?: string
  audioRoleConfigs?: Record<string, RoleAudioConfig>
  imageProvider?: string
  imageModel?: string
  frameImageModel?: string
  referenceAspectRatio?: string
  referenceImageSize?: string
  referenceImageResolution?: string
  frameAspectRatio?: string
  frameImageSize?: string
  frameImageResolution?: string
  imageWan2gpPreset?: string
  imageWan2gpPresetI2i?: string
  imageWan2gpInferenceSteps?: number
  imageWan2gpInferenceStepsT2i?: number
  imageWan2gpInferenceStepsI2i?: number
  imageStyle?: string
  videoProvider?: string
  videoModel?: string
  videoModelI2v?: string
  videoAspectRatio?: string
  resolution?: string
  videoWan2gpT2vPreset?: string
  videoWan2gpI2vPreset?: string
  videoWan2gpResolution?: string
  videoWan2gpInferenceSteps?: number
  videoWan2gpSlidingWindowSize?: number
  singleTake?: boolean
  useFirstFrameRef?: boolean
  useReferenceImageRef?: boolean
  videoFitMode?: 'truncate' | 'scale' | 'none'
  composeCanvasStrategy?: 'max_size' | 'most_common' | 'first_shot' | 'fixed'
  composeFixedAspectRatio?: string
  composeFixedResolution?: string
  includeSubtitle?: boolean
  subtitleFontSize?: number
  subtitlePositionPercent?: number
  useReferenceConsistency?: boolean
  maxConcurrency?: number
}

export interface StageStatus {
  [stage: string]: 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | undefined
  content?: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
  storyboard?: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
  audio?: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
  reference?: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
  first_frame_desc?: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
  frame?: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
  video?: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
  compose?: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
  subtitle?: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
  burn_subtitle?: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
  finalize?: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
}
