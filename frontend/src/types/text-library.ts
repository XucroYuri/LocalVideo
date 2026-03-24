export type TextSourceChannel = 'copy' | 'file' | 'web' | 'xiaohongshu' | 'douyin' | 'kuaishou'
export type TextImportJobStatus = 'pending' | 'running' | 'completed' | 'failed' | 'canceled'
export type TextImportTaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'canceled'
export type TextItemFieldStatus = 'pending' | 'running' | 'ready' | 'failed' | 'canceled'

export interface TextLibraryItem {
  id: number
  name: string
  content: string
  source_channel: TextSourceChannel
  title_status: TextItemFieldStatus
  content_status: TextItemFieldStatus
  processing_stage?: string | null
  processing_message?: string | null
  error_message?: string | null
  source_url?: string | null
  source_file_name?: string | null
  source_post_id?: string | null
  source_post_updated_at?: string | null
  is_enabled: boolean
  created_at: string
  updated_at: string
}

export interface TextLibraryListResponse {
  items: TextLibraryItem[]
  total: number
  page?: number | null
  page_size?: number | null
}

export interface TextLibraryImportTask {
  id: number
  source_url: string
  source_channel: TextSourceChannel
  status: TextImportTaskStatus
  stage?: string | null
  stage_message?: string | null
  cache_hit?: boolean
  error_message?: string | null
  cancel_requested?: boolean
  cancel_requested_at?: string | null
  cancel_reason?: string | null
  retry_of_task_id?: number | null
  retry_no?: number
  text_library_item_id?: number | null
  source_post_id?: string | null
  source_post_updated_at?: string | null
}

export interface TextLibraryImportJob {
  id: string
  status: TextImportJobStatus
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
  tasks: TextLibraryImportTask[]
  created_at: string
  updated_at: string
}

export interface TextLibraryImportLinksCreateResponse {
  job_id: string
  job_ids?: string[]
  item_ids: number[]
}

export interface SourceImportFromTextLibraryResultItem {
  text_library_id: number
  status: 'created' | 'skipped' | 'failed'
  source_id?: number | null
  message: string
}

export interface SourceImportFromTextLibraryResponse {
  success: boolean
  summary: {
    requested_count: number
    created_count: number
    skipped_count: number
    failed_count: number
  }
  results: SourceImportFromTextLibraryResultItem[]
}

export interface TextLibraryCancelResponse {
  affected_jobs: number
  affected_tasks: number
}
