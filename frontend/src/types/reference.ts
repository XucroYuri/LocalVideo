export interface ReferenceLibraryItem {
  id: number
  name: string
  is_enabled: boolean
  can_speak: boolean
  setting?: string
  appearance_description?: string
  voice_audio_provider?: 'edge_tts' | 'wan2gp' | 'volcengine_tts' | 'kling_tts' | 'vidu_tts' | 'minimax_tts' | 'xiaomi_mimo_tts'
  voice_name?: string
  voice_speed?: number
  voice_wan2gp_preset?: string
  voice_wan2gp_alt_prompt?: string
  voice_wan2gp_audio_guide?: string
  voice_wan2gp_temperature?: number
  voice_wan2gp_top_k?: number
  voice_wan2gp_seed?: number
  image_file_path?: string
  image_updated_at?: number
  source_channel?: 'manual' | 'image_batch' | null
  source_file_name?: string | null
  name_status: 'pending' | 'running' | 'ready' | 'failed' | 'canceled'
  appearance_status: 'pending' | 'running' | 'ready' | 'failed' | 'canceled'
  processing_stage?: string | null
  processing_message?: string | null
  error_message?: string | null
  created_at: string
  updated_at: string
}

export interface ReferenceLibraryListResponse {
  items: ReferenceLibraryItem[]
  total: number
  page?: number | null
  page_size?: number | null
}

export interface ReferenceLibraryImportImageRow {
  index: number
  name?: string | null
  generate_description: boolean
}

export interface ReferenceLibraryImportImagesCreateResponse {
  job_id: string
  job_ids?: string[]
  item_ids: number[]
}

export interface ReferenceLibraryImportTask {
  id: number
  source_file_name: string
  input_name?: string | null
  generate_description: boolean
  status: 'pending' | 'running' | 'completed' | 'failed' | 'canceled'
  stage?: string | null
  stage_message?: string | null
  error_message?: string | null
  cancel_requested?: boolean
  cancel_requested_at?: string | null
  cancel_reason?: string | null
  retry_of_task_id?: number | null
  retry_no?: number
  reference_library_item_id?: number | null
}

export interface ReferenceLibraryImportJob {
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
  tasks: ReferenceLibraryImportTask[]
  created_at: string
  updated_at: string
}

export interface LibraryCancelResponse {
  affected_jobs: number
  affected_tasks: number
}

export interface StageReferenceImportResultItem {
  library_reference_id: number
  library_name?: string | null
  status: 'created' | 'skipped' | 'failed'
  project_reference_id?: string | null
  code: string
  message: string
  warnings: string[]
}

export interface StageReferenceImportResult {
  success: boolean
  summary: {
    requested_count: number
    created_count: number
    skipped_count: number
    failed_count: number
  }
  results: StageReferenceImportResultItem[]
  data: Record<string, unknown>
}
