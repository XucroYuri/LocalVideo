export type SourceType = 'search' | 'deep_research' | 'text'

export interface Source {
  id: number
  project_id: number
  type: SourceType
  title: string
  content: string
  selected: boolean
  created_at: string
  updated_at: string
}

export interface SourceCreate {
  type: SourceType
  title: string
  content: string
  selected?: boolean
}

export interface SourceUpdate {
  title?: string
  content?: string
  selected?: boolean
}

export interface SourceListResponse {
  items: Source[]
  total: number
}

export interface SourceBatchUpdate {
  source_ids: number[]
  selected: boolean
}
