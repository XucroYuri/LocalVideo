export type ProjectStatus = 'draft' | 'running' | 'paused' | 'completed' | 'failed'
export type ProjectVideoMode = 'oral_script_driven' | 'audio_visual_driven'
export type ProjectVideoType = 'custom' | 'single_narration' | 'duo_podcast' | 'dialogue_script'

export interface Project {
  id: number
  title: string
  keywords?: string
  input_text?: string
  style: string
  target_duration: number
  video_mode: ProjectVideoMode
  video_type: ProjectVideoType
  config?: Record<string, unknown>
  status: ProjectStatus
  current_stage?: number
  error_message?: string
  output_dir?: string
  cover_emoji?: string
  dialogue_preview?: string
  first_video_url?: string
  created_at: string
  updated_at: string
}

export interface ProjectCreate {
  title: string
  keywords?: string
  input_text?: string
  style?: string
  target_duration?: number
  video_mode?: ProjectVideoMode
  video_type?: ProjectVideoType
  config?: Record<string, unknown>
}

export interface ProjectListResponse {
  items: Project[]
  total: number
  page: number
  page_size: number
}
