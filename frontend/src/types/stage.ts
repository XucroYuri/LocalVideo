export type BackendStageType =
  | 'research'
  | 'content'
  | 'storyboard'
  | 'audio'
  | 'subtitle'
  | 'burn_subtitle'
  | 'finalize'
  | 'reference'
  | 'first_frame_desc'
  | 'frame'
  | 'video'
  | 'compose'

export type StageType = BackendStageType

export type StageStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped'

// 完整的阶段执行记录
export interface Stage {
  id: number
  project_id: number
  stage_type: StageType
  stage_number: number
  status: StageStatus
  progress: number
  total_items?: number
  completed_items?: number
  skipped_items?: number
  last_item_complete?: number
  input_data?: Record<string, unknown>
  output_data?: Record<string, unknown>
  error_message?: string
  created_at: string
  updated_at: string
}

// 阶段列表项（GET /projects/{id}/stages 返回）
export interface StageListItem {
  stage_type: StageType
  stage_number: number
  status: StageStatus
  progress: number
  is_applicable: boolean
  is_optional: boolean
  error_message?: string
}

// 阶段列表响应
export interface StageListResponse {
  items: StageListItem[]
  current_stage?: number
}

// SSE 进度事件
export interface StageProgressEvent {
  stage_type: StageType
  progress: number
  message?: string
  status?: StageStatus
  data?: Record<string, unknown>
  item_complete?: number
  total_items?: number    // Total number of items to generate
  completed_items?: number // Number of completed items
  skipped_items?: number   // Number of skipped items (already generated)
  generating_shots?: Record<string, { status: string; progress: number }>
}

// 阶段执行请求
export interface StageRunRequest {
  force?: boolean
  input_data?: Record<string, unknown>
}

// Pipeline 执行请求
export interface PipelineRunRequest {
  from_stage?: StageType
  to_stage?: StageType
}

// 阶段元信息 (静态 fallback，优先使用 useStageManifest hook 获取后端数据)
export const STAGE_META: Record<string, { name: string; icon: string; description: string }> = {
  research: { name: '信息搜集', icon: '🔍', description: '根据关键词搜索网络信息' },
  content: { name: '文案生成', icon: '✍️', description: 'LLM 生成完整口播文案' },
  storyboard: { name: '分镜生成', icon: '📝', description: 'LLM 规划分镜并生成视频描述' },
  audio: { name: '音频生成', icon: '🔊', description: 'TTS 语音合成' },
  subtitle: { name: '字幕生成', icon: '💬', description: '基于母版视频生成完整字幕' },
  burn_subtitle: { name: '字幕烧录', icon: '📝', description: '将字幕烧录到母版视频' },
  finalize: { name: '最终成片', icon: '✅', description: '统一选择最终交付视频' },
  reference: { name: '参考图生成', icon: '👤', description: '生成参考图 (I2V)' },
  first_frame_desc: { name: '首帧描述', icon: '🧾', description: '逐分镜生成首帧提示词' },
  frame: { name: '首帧生成', icon: '🖼️', description: '生成首帧图像 (I2V)' },
  video: { name: '视频生成', icon: '🎬', description: 'AI 生成分镜视频' },
  compose: { name: '母版合成', icon: '🎥', description: 'FFmpeg 合成无字幕母版视频' },
}
