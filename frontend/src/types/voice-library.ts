export interface VoiceLibraryItem {
  id: number
  name: string
  reference_text?: string | null
  audio_file_path?: string | null
  audio_url?: string | null
  has_audio: boolean
  is_enabled: boolean
  is_builtin: boolean
  source_channel?: 'audio_with_text' | 'audio_file' | 'video_link' | 'builtin' | null
  auto_parse_text: boolean
  source_url?: string | null
  source_file_name?: string | null
  source_post_id?: string | null
  source_post_updated_at?: string | null
  clip_start_requested_sec?: number | null
  clip_end_requested_sec?: number | null
  clip_start_actual_sec?: number | null
  clip_end_actual_sec?: number | null
  name_status: 'pending' | 'running' | 'ready' | 'failed' | 'canceled'
  reference_text_status: 'pending' | 'running' | 'ready' | 'failed' | 'canceled'
  processing_stage?: string | null
  processing_message?: string | null
  error_message?: string | null
  created_at: string
  updated_at: string
}

export interface VoiceLibraryListResponse {
  items: VoiceLibraryItem[]
  total: number
  page?: number | null
  page_size?: number | null
}

export interface VoiceLibraryImportAudioFilesResponse {
  item_ids: number[]
}

export interface VoiceLibraryImportAudioRow {
  index: number
  name?: string | null
  auto_parse_text: boolean
}

export interface VoiceLibraryImportTask {
  id: number
  source_channel: 'audio_with_text' | 'audio_file' | 'video_link' | 'builtin'
  source_url?: string | null
  source_file_name?: string | null
  auto_parse_text: boolean
  clip_start_requested_sec?: number | null
  clip_end_requested_sec?: number | null
  clip_start_actual_sec?: number | null
  clip_end_actual_sec?: number | null
  status: 'pending' | 'running' | 'completed' | 'failed' | 'canceled'
  stage?: string | null
  stage_message?: string | null
  error_message?: string | null
  cancel_requested?: boolean
  cancel_requested_at?: string | null
  cancel_reason?: string | null
  retry_of_task_id?: number | null
  retry_no?: number
  voice_library_item_id?: number | null
  source_post_id?: string | null
  source_post_updated_at?: string | null
}

export interface VoiceLibraryImportJob {
  id: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'canceled'
  total_count: number
  completed_count: number
  success_count: number
  failed_count: number
  canceled_count?: number
  cancel_requested?: boolean
  cancel_requested_at?: string | null
  cancel_requested_by?: string | null
  terminal_at?: string | null
  error_message?: string | null
  tasks: VoiceLibraryImportTask[]
  created_at: string
  updated_at: string
}

export interface VoiceLibraryImportVideoLinkCreateResponse {
  job_id: string
  job_ids?: string[]
  item_ids: number[]
}

export interface VoiceLibraryCancelResponse {
  affected_jobs: number
  affected_tasks: number
}
