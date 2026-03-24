import type { Project, ProjectCreate, ProjectListResponse } from '@/types/project'
import type { Stage, StageListResponse, StageRunRequest } from '@/types/stage'
import type {
  Settings,
  SettingsUpdate,
  VoiceInfo,
  AvailableProviders,
  Capabilities,
  JinaReaderUsage,
  TavilyUsage,
  ImageProviderType,
  LLMProviderType,
  Wan2gpAudioPreset,
  Wan2gpImagePreset,
  Wan2gpVideoPreset,
} from '@/types/settings'
import type { Source, SourceCreate, SourceUpdate, SourceListResponse, SourceBatchUpdate } from '@/types/source'
import type { VoiceFormFields } from '@/lib/form-data-helpers'
import { appendVoiceFields } from '@/lib/form-data-helpers'
import type {
  LibraryCancelResponse,
  ReferenceLibraryImportImageRow,
  ReferenceLibraryImportImagesCreateResponse,
  ReferenceLibraryImportJob,
  ReferenceLibraryItem,
  ReferenceLibraryListResponse,
  StageReferenceImportResult,
} from '@/types/reference'
import type {
  VoiceLibraryCancelResponse,
  VoiceLibraryImportAudioRow,
  VoiceLibraryImportAudioFilesResponse,
  VoiceLibraryImportJob,
  VoiceLibraryImportVideoLinkCreateResponse,
  VoiceLibraryItem,
  VoiceLibraryListResponse,
} from '@/types/voice-library'
import type {
  TextLibraryCancelResponse,
  SourceImportFromTextLibraryResponse,
  TextLibraryImportJob,
  TextLibraryImportLinksCreateResponse,
  TextLibraryItem,
  TextLibraryListResponse,
} from '@/types/text-library'
import { getInternalApiBaseUrl, getPublicApiBaseUrl } from '@/lib/api-base-url'

type ImageScene = 'reference' | 'frame'

async function fetchAPI<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const headers = new Headers(options.headers)
  const hasBody = options.body !== undefined && options.body !== null
  const isFormDataBody = typeof FormData !== 'undefined' && options.body instanceof FormData

  if (hasBody && !isFormDataBody && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(`${getInternalApiBaseUrl()}${endpoint}`, {
    ...options,
    cache: options.cache ?? 'no-store',
    headers,
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(error.detail || `API Error: ${response.status}`)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return response.json()
}

async function uploadFile<T>(
  endpoint: string,
  file: File
): Promise<T> {
  const formData = new FormData()
  formData.append('file', file)

  const response = await fetch(`${getInternalApiBaseUrl()}${endpoint}`, {
    method: 'POST',
    body: formData,
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(error.detail || `API Error: ${response.status}`)
  }

  return response.json()
}

export const api = {
  projects: {
    list: (page = 1, pageSize = 20, q = '') => {
      const query = new URLSearchParams()
      query.set('page', String(page))
      query.set('page_size', String(pageSize))
      if (q.trim()) query.set('q', q.trim())
      return fetchAPI<ProjectListResponse>(`/projects?${query.toString()}`)
    },
    get: (id: number) =>
      fetchAPI<Project>(`/projects/${id}`),
    create: (data: ProjectCreate) =>
      fetchAPI<Project>('/projects', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    update: (id: number, data: Partial<ProjectCreate>) =>
      fetchAPI<Project>(`/projects/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    duplicate: (id: number) =>
      fetchAPI<Project>(`/projects/${id}/duplicate`, {
        method: 'POST',
      }),
    regenerateCover: (id: number) =>
      fetchAPI<Project>(`/projects/${id}/cover/regenerate`, {
        method: 'POST',
      }),
    delete: (id: number) =>
      fetchAPI<void>(`/projects/${id}`, { method: 'DELETE' }),
  },
  stages: {
    manifest: () =>
      fetchAPI<{ stages: Array<{ type: string; number: number; name: string; icon: string; description: string; is_optional: boolean }> }>('/stages/manifest'),
    list: (projectId: number) =>
      fetchAPI<StageListResponse>(`/projects/${projectId}/stages`),
    get: (projectId: number, stageType: string) =>
      fetchAPI<Stage>(`/projects/${projectId}/stages/${stageType}`),
    run: (projectId: number, stageType: string, request: StageRunRequest = {}) =>
      fetchAPI<Stage>(`/projects/${projectId}/stages/${stageType}`, {
        method: 'POST',
        body: JSON.stringify(request),
      }),
    streamUrl: (projectId: number, stageType: string, force = false, inputData?: Record<string, unknown>) => {
      const params = new URLSearchParams({ force: String(force) })
      if (inputData) {
        params.set('input_data', JSON.stringify(inputData))
      }
      return `${getPublicApiBaseUrl()}/projects/${projectId}/stages/${stageType}/stream?${params.toString()}`
    },
    pipelineStreamUrl: (projectId: number) =>
      `${getPublicApiBaseUrl()}/projects/${projectId}/stages/pipeline/run`,
    cancelRunningTasks: (projectId: number) =>
      fetchAPI<{
        success: boolean
        cancelled_stage_tasks: number
        cancelled_pipeline_tasks: number
        recovered_running_stages: number
      }>(`/projects/${projectId}/stages/tasks/cancel`, {
        method: 'POST',
      }),
    // Content update
    updateContent: (
      projectId: number,
      data: {
        title?: string
        content?: string
        script_mode?: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'
        roles?: Array<{
          id?: string
          name?: string
          description?: string
          seat_side?: 'left' | 'right' | null
          locked?: boolean
        }>
        dialogue_lines?: Array<{
          id?: string
          speaker_id?: string
          speaker_name?: string
          text?: string
          order?: number
        }>
      }
    ) =>
      fetchAPI<{ success: boolean; data: Record<string, unknown> }>(`/projects/${projectId}/stages/content/data`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    importContentDialogue: (
      projectId: number,
      file: File,
      scriptMode?: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'
    ) => {
      const formData = new FormData()
      formData.append('file', file)
      if (scriptMode) formData.append('script_mode', scriptMode)
      return fetch(`${getInternalApiBaseUrl()}/projects/${projectId}/stages/content/dialogue/import`, {
        method: 'POST',
        body: formData,
      }).then(async (response) => {
        if (!response.ok) {
          const error = await response.json().catch(() => ({}))
          throw new Error(error.detail || `API Error: ${response.status}`)
        }
        return response.json() as Promise<{
          success: boolean
          data: Record<string, unknown>
          auto_created_references?: string[]
        }>
      })
    },
    // Reference update
    updateReference: (
      projectId: number,
      referenceId: string | number,
      data: {
        name: string
        setting?: string
        appearance_description?: string
        can_speak: boolean
        voice_audio_provider?: 'edge_tts' | 'wan2gp' | 'volcengine_tts' | 'kling_tts' | 'vidu_tts' | 'minimax_tts' | 'xiaomi_mimo_tts'
        voice_name?: string
        voice_speed?: number
        voice_wan2gp_preset?: string
        voice_wan2gp_alt_prompt?: string
        voice_wan2gp_audio_guide?: string
        voice_wan2gp_temperature?: number
        voice_wan2gp_top_k?: number
        voice_wan2gp_seed?: number
      }
    ) =>
      fetchAPI<{ success: boolean; data: Record<string, unknown> }>(`/projects/${projectId}/stages/reference/items/${referenceId}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    // Reference delete
    deleteReference: (projectId: number, referenceId: string | number) =>
      fetchAPI<{ success: boolean; data: Record<string, unknown> }>(`/projects/${projectId}/stages/reference/items/${referenceId}`, {
        method: 'DELETE',
      }),
    regenerateImage: (
      projectId: number,
      scene: ImageScene,
      itemId: string | number,
      options?: {
        image_provider?: string
        image_aspect_ratio?: string
        image_size?: string
        image_resolution?: string
        image_wan2gp_preset?: string
        image_wan2gp_inference_steps?: number
        image_wan2gp_guidance_scale?: number
        image_style?: string
        use_reference_consistency?: boolean
      }
    ) =>
      fetchAPI<{ success: boolean; data: Record<string, unknown> }>(
        `/projects/${projectId}/stages/image/${scene}/items/${itemId}/regenerate`,
        {
          method: 'POST',
          body: JSON.stringify(options || {}),
        }
      ),
    uploadImage: (projectId: number, scene: ImageScene, itemId: string | number, file: File) =>
      uploadFile<{ success: boolean; data: Record<string, unknown> }>(
        `/projects/${projectId}/stages/image/${scene}/items/${itemId}/upload`,
        file
      ),
    deleteImage: (projectId: number, scene: ImageScene, itemId: string | number) =>
      fetchAPI<{ success: boolean }>(
        `/projects/${projectId}/stages/image/${scene}/items/${itemId}/asset`,
        { method: 'DELETE' }
      ),
    // Reference image regenerate
    regenerateReferenceImage: (
      projectId: number,
      referenceId: string | number,
      options?: {
        image_provider?: string
        image_aspect_ratio?: string
        image_size?: string
        image_resolution?: string
        image_wan2gp_preset?: string
        image_wan2gp_inference_steps?: number
        image_wan2gp_guidance_scale?: number
        image_style?: string
      }
    ) => api.stages.regenerateImage(projectId, 'reference', referenceId, options),
    // Reference image upload
    uploadReferenceImage: (projectId: number, referenceId: string | number, file: File) =>
      api.stages.uploadImage(projectId, 'reference', referenceId, file),
    // Create new reference with optional image
    createReference: (
      projectId: number,
      data: {
        name?: string
        setting?: string
        appearance_description?: string
        can_speak?: boolean
        file?: File
      } & VoiceFormFields
    ) => {
      const formData = new FormData()
      if (data.name) formData.append('name', data.name)
      if (data.setting) formData.append('setting', data.setting)
      if (data.appearance_description) {
        formData.append('appearance_description', data.appearance_description)
      }
      formData.append('can_speak', String(data.can_speak ?? true))
      appendVoiceFields(formData, data)
      if (data.file) formData.append('file', data.file)

      return fetch(`${getInternalApiBaseUrl()}/projects/${projectId}/stages/reference/items`, {
        method: 'POST',
        body: formData,
      }).then(async (response) => {
        if (!response.ok) {
          const error = await response.json().catch(() => ({}))
          throw new Error(error.detail || `API Error: ${response.status}`)
        }
        return response.json() as Promise<{ success: boolean; data: Record<string, unknown>; reference_id: string }>
      })
    },
    // Generate reference description from image using Vision API
    generateDescriptionFromImage: (
      projectId: number,
      referenceId: string | number,
      options?: {
        target_language?: 'zh' | 'en'
        prompt_complexity?: 'minimal' | 'simple' | 'normal' | 'detailed' | 'complex' | 'ultra'
        llm_provider?: string
        llm_model?: string
      }
    ) =>
      fetchAPI<{ success: boolean; appearance_description: string; data: Record<string, unknown> }>(
        `/projects/${projectId}/stages/reference/items/${referenceId}/describe-from-image`,
        {
          method: 'POST',
          body: JSON.stringify(options || {}),
        }
      ),
    importReferencesFromLibrary: (
      projectId: number,
      data: {
        library_reference_ids: number[]
        start_reference_index?: number
        import_setting: boolean
        import_appearance_description: boolean
        import_image: boolean
        import_voice: boolean
      }
    ) =>
      fetchAPI<StageReferenceImportResult>(
        `/projects/${projectId}/stages/reference/import-from-library`,
        {
          method: 'POST',
          body: JSON.stringify(data),
        }
      ),
    // Frame description update
    updateFrameDescription: (
      projectId: number,
      shotIndex: number,
      data: {
        description?: string
        first_frame_reference_slots?: Array<{ order?: number; id: string; name?: string }>
      }
    ) =>
      fetchAPI<{ success: boolean; data: Record<string, unknown> }>(
        `/projects/${projectId}/stages/frame/shots/${shotIndex}`,
        {
          method: 'PATCH',
          body: JSON.stringify(data),
        }
      ),
    // Frame image regenerate
    regenerateFrameImage: (
      projectId: number,
      shotIndex: number,
      options?: {
        image_provider?: string
        image_aspect_ratio?: string
        image_size?: string
        image_resolution?: string
        image_wan2gp_preset?: string
        image_wan2gp_inference_steps?: number
        image_wan2gp_guidance_scale?: number
        image_style?: string
        use_reference_consistency?: boolean
      }
    ) => api.stages.regenerateImage(projectId, 'frame', shotIndex, options),
    // Frame image upload
    uploadFrameImage: (projectId: number, shotIndex: number, file: File) =>
      api.stages.uploadImage(projectId, 'frame', shotIndex, file),
    // Reuse first frame image to all shots
    reuseFirstFrameToOthers: (projectId: number) =>
      fetchAPI<{ success: boolean; data: Record<string, unknown> }>(
        `/projects/${projectId}/stages/frame/frames/reuse-first`,
        { method: 'POST' }
      ),
    // Video regenerate
    regenerateVideo: (
      projectId: number,
      shotIndex: number,
      options?: {
        video_provider?: string
        video_model?: string
        aspect_ratio?: string
        resolution?: string
        use_first_frame_ref?: boolean
        video_wan2gp_t2v_preset?: string
        video_wan2gp_i2v_preset?: string
        video_wan2gp_resolution?: string
        video_wan2gp_inference_steps?: number
        video_wan2gp_sliding_window_size?: number
      }
    ) =>
      fetchAPI<{ success: boolean; data: Record<string, unknown> }>(
        `/projects/${projectId}/stages/video/shots/${shotIndex}/regenerate`,
        {
          method: 'POST',
          body: JSON.stringify(options || {}),
        }
      ),
    // Audio regenerate
    regenerateAudio: (
      projectId: number,
      shotIndex: number,
      options?: {
        audio_provider?: string
        voice?: string
        speed?: number
        audio_wan2gp_preset?: string
        audio_wan2gp_model_mode?: string
        audio_wan2gp_alt_prompt?: string
        audio_wan2gp_duration_seconds?: number
        audio_wan2gp_temperature?: number
        audio_wan2gp_top_k?: number
        audio_wan2gp_seed?: number
        audio_wan2gp_audio_guide?: string
        audio_wan2gp_split_strategy?: 'sentence_punct' | 'anchor_tail'
      }
    ) =>
      fetchAPI<{ success: boolean; data: Record<string, unknown> }>(
        `/projects/${projectId}/stages/audio/shots/${shotIndex}/regenerate`,
        {
          method: 'POST',
          body: JSON.stringify(options || {}),
        }
      ),
    // Video description update
    updateVideoDescription: (
      projectId: number,
      shotIndex: number,
      data: {
        description?: string
        video_reference_slots?: Array<{ order?: number; id: string; name?: string }>
      }
    ) =>
      fetchAPI<{ success: boolean; data: Record<string, unknown> }>(
        `/projects/${projectId}/stages/video/shots/${shotIndex}`,
        {
          method: 'PATCH',
          body: JSON.stringify(data),
        }
      ),
    // Delete frame image
    deleteFrameImage: (projectId: number, shotIndex: number) =>
      api.stages.deleteImage(projectId, 'frame', shotIndex),
    bulkDeleteFrameImages: (projectId: number, shotIndices: number[]) =>
      fetchAPI<{ success: boolean; deleted_count: number; missing_shot_indices: number[] }>(
        `/projects/${projectId}/stages/image/frame/assets/bulk-delete`,
        {
          method: 'POST',
          body: JSON.stringify({ shot_indices: shotIndices }),
        }
      ),
    // Delete video
    deleteVideo: (projectId: number, shotIndex: number) =>
      fetchAPI<{ success: boolean }>(
        `/projects/${projectId}/stages/video/shots/${shotIndex}`,
        { method: 'DELETE' }
      ),
    bulkDeleteVideos: (projectId: number, shotIndices: number[]) =>
      fetchAPI<{ success: boolean; deleted_count: number; missing_shot_indices: number[] }>(
        `/projects/${projectId}/stages/video/shots/bulk-delete`,
        {
          method: 'POST',
          body: JSON.stringify({ shot_indices: shotIndices }),
        }
      ),
    bulkDeleteAudios: (projectId: number, shotIndices: number[]) =>
      fetchAPI<{ success: boolean; deleted_count: number; missing_shot_indices: number[] }>(
        `/projects/${projectId}/stages/audio/shots/bulk-delete`,
        {
          method: 'POST',
          body: JSON.stringify({ shot_indices: shotIndices }),
        }
      ),
    // Delete composed final video
    deleteComposeVideo: (projectId: number) =>
      fetchAPI<{ success: boolean }>(
        `/projects/${projectId}/stages/compose/video`,
        { method: 'DELETE' }
      ),
    // Clear all shot-level generated content
    clearAllShotContent: (projectId: number) =>
      fetchAPI<{ success: boolean }>(
        `/projects/${projectId}/stages/shots/clear-all`,
        { method: 'POST' }
      ),
    // Shot list & editing
    listShots: (projectId: number) =>
      fetchAPI<{
        success: boolean
        data: {
          shots: Array<{
            shot_id: string
            order: number
            voice_content?: string
            speaker_id?: string
            speaker_name?: string
            line_id?: string
            video_prompt?: string
            first_frame_description?: string
          }>
          shot_count: number
          shots_locked: boolean
        }
      }>(`/projects/${projectId}/stages/shots`),
    insertShots: (
      projectId: number,
      data: { anchor_index: number; direction: 'before' | 'after'; count: number }
    ) =>
      fetchAPI<{
        success: boolean
        data: {
          shots: Array<Record<string, unknown>>
          shot_count: number
          shots_locked: boolean
        }
      }>(`/projects/${projectId}/stages/shots/insert`, {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    updateShot: (
      projectId: number,
      shotId: string,
      data: {
        voice_content?: string
        speaker_id?: string
        speaker_name?: string
      }
    ) =>
      fetchAPI<{
        success: boolean
        data: {
          shots: Array<Record<string, unknown>>
          shot_count: number
          shots_locked: boolean
        }
      }>(`/projects/${projectId}/stages/shots/${shotId}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    deleteShot: (projectId: number, shotId: string) =>
      fetchAPI<{
        success: boolean
        data: {
          shots: Array<Record<string, unknown>>
          shot_count: number
          shots_locked: boolean
        }
      }>(`/projects/${projectId}/stages/shots/${shotId}`, {
        method: 'DELETE',
      }),
    reorderShots: (
      projectId: number,
      data: { ordered_shot_ids: string[] }
    ) =>
      fetchAPI<{
        success: boolean
        data: {
          shots: Array<Record<string, unknown>>
          shot_count: number
          shots_locked: boolean
        }
      }>(`/projects/${projectId}/stages/shots/reorder`, {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    moveShot: (
      projectId: number,
      data: { shot_id: string; direction: 'up' | 'down'; step: number }
    ) =>
      fetchAPI<{
        success: boolean
        data: {
          shots: Array<Record<string, unknown>>
          shot_count: number
          shots_locked: boolean
        }
      }>(`/projects/${projectId}/stages/shots/move`, {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    unlockContentByClearingShots: (projectId: number) =>
      fetchAPI<{ success: boolean }>(
        `/projects/${projectId}/stages/shots/unlock-content`,
        { method: 'POST' }
      ),
    // Delete reference image (not the reference)
    deleteReferenceImage: (projectId: number, referenceId: string | number) =>
      api.stages.deleteImage(projectId, 'reference', referenceId),
  },
  references: {
    list: (params?: { q?: string; enabledOnly?: boolean; page?: number; pageSize?: number }) => {
      const query = new URLSearchParams()
      if (params?.q?.trim()) query.set('q', params.q.trim())
      if (params?.enabledOnly) query.set('enabled_only', 'true')
      if (typeof params?.page === 'number' && Number.isFinite(params.page) && params.page > 0) {
        query.set('page', String(Math.floor(params.page)))
      }
      if (typeof params?.pageSize === 'number' && Number.isFinite(params.pageSize) && params.pageSize > 0) {
        query.set('page_size', String(Math.floor(params.pageSize)))
      }
      const suffix = query.size > 0 ? `?${query.toString()}` : ''
      return fetchAPI<ReferenceLibraryListResponse>(`/references${suffix}`)
    },
    create: (data: {
      name: string
      is_enabled?: boolean
      can_speak?: boolean
      setting?: string
      appearance_description?: string
      file?: File
    } & VoiceFormFields) => {
      const formData = new FormData()
      formData.append('name', data.name)
      formData.append('is_enabled', String(data.is_enabled ?? true))
      formData.append('can_speak', String(data.can_speak ?? false))
      if (data.setting) formData.append('setting', data.setting)
      if (data.appearance_description) {
        formData.append('appearance_description', data.appearance_description)
      }
      appendVoiceFields(formData, data)
      if (data.file) formData.append('file', data.file)

      return fetch(`${getInternalApiBaseUrl()}/references`, {
        method: 'POST',
        body: formData,
      }).then(async (response) => {
        if (!response.ok) {
          const error = await response.json().catch(() => ({}))
          throw new Error(error.detail || `API Error: ${response.status}`)
        }
        return response.json() as Promise<ReferenceLibraryItem>
      })
    },
    update: (
      itemId: number,
      data: {
        name?: string
        is_enabled?: boolean
        can_speak?: boolean
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
      }
    ) =>
      fetchAPI<ReferenceLibraryItem>(`/references/${itemId}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    delete: (itemId: number) => fetchAPI<void>(`/references/${itemId}`, { method: 'DELETE' }),
    uploadImage: (itemId: number, file: File) =>
      uploadFile<ReferenceLibraryItem>(`/references/${itemId}/image/upload`, file),
    deleteImage: (itemId: number) =>
      fetchAPI<ReferenceLibraryItem>(`/references/${itemId}/image`, { method: 'DELETE' }),
    describeFromImage: (
      itemId: number,
      options?: {
        target_language?: 'zh' | 'en'
        prompt_complexity?: 'minimal' | 'simple' | 'normal' | 'detailed' | 'complex' | 'ultra'
        llm_provider?: string
        llm_model?: string
      }
    ) =>
      fetchAPI<{ success: boolean; appearance_description: string; data: Record<string, unknown> }>(
        `/references/${itemId}/describe-from-image`,
        {
          method: 'POST',
          body: JSON.stringify(options || {}),
        }
      ),
    describeFromUpload: (
      file: File,
      options?: {
        target_language?: 'zh' | 'en'
        prompt_complexity?: 'minimal' | 'simple' | 'normal' | 'detailed' | 'complex' | 'ultra'
        llm_provider?: string
        llm_model?: string
      }
    ) => {
      const formData = new FormData()
      formData.append('file', file)
      if (options?.target_language) formData.append('target_language', options.target_language)
      if (options?.prompt_complexity) formData.append('prompt_complexity', options.prompt_complexity)
      if (options?.llm_provider) formData.append('llm_provider', options.llm_provider)
      if (options?.llm_model) formData.append('llm_model', options.llm_model)

      return fetch(`${getInternalApiBaseUrl()}/references/describe-from-upload`, {
        method: 'POST',
        body: formData,
      }).then(async (response) => {
        if (!response.ok) {
          const error = await response.json().catch(() => ({}))
          throw new Error(error.detail || `API Error: ${response.status}`)
        }
        return response.json() as Promise<{ success: boolean; appearance_description: string; data: Record<string, unknown> }>
      })
    },
    importImages: (files: File[], rows: ReferenceLibraryImportImageRow[]) => {
      const formData = new FormData()
      files.forEach((file) => {
        formData.append('files', file)
      })
      formData.append('rows_json', JSON.stringify(rows))

      return fetch(`${getInternalApiBaseUrl()}/references/import/images`, {
        method: 'POST',
        body: formData,
      }).then(async (response) => {
        if (!response.ok) {
          const error = await response.json().catch(() => ({}))
          throw new Error(error.detail || `API Error: ${response.status}`)
        }
        return response.json() as Promise<ReferenceLibraryImportImagesCreateResponse>
      })
    },
    getImportJob: (jobId: string) =>
      fetchAPI<ReferenceLibraryImportJob>(`/references/import-jobs/${jobId}`),
    cancelAllImportJobs: () =>
      fetchAPI<LibraryCancelResponse>('/references/import-jobs/cancel-all', {
        method: 'POST',
      }),
    cancelImportJob: (jobId: string) =>
      fetchAPI<LibraryCancelResponse>(`/references/import-jobs/${jobId}/cancel`, {
        method: 'POST',
      }),
    cancelImportTask: (taskId: number) =>
      fetchAPI<LibraryCancelResponse>(`/references/import-tasks/${taskId}/cancel`, {
        method: 'POST',
      }),
    cancelImportTaskByItem: (itemId: number) =>
      fetchAPI<LibraryCancelResponse>(`/references/import-tasks/by-item/${itemId}/cancel`, {
        method: 'POST',
      }),
    retryImportTask: (taskId: number) =>
      fetchAPI<ReferenceLibraryImportImagesCreateResponse>(`/references/import-tasks/${taskId}/retry`, {
        method: 'POST',
      }),
    restartInterruptedImportTasks: () =>
      fetchAPI<LibraryCancelResponse>('/references/import-jobs/restart-interrupted', {
        method: 'POST',
      }),
    importEventsStreamUrl: () => `${getPublicApiBaseUrl()}/references/import-events/stream`,
    retry: (itemId: number) =>
      fetchAPI<ReferenceLibraryItem>(`/references/${itemId}/retry`, {
        method: 'POST',
      }),
  },
  voiceLibrary: {
    list: (params?: { q?: string; enabledOnly?: boolean; withAudioOnly?: boolean; page?: number; pageSize?: number }) => {
      const query = new URLSearchParams()
      if (params?.q?.trim()) query.set('q', params.q.trim())
      if (params?.enabledOnly) query.set('enabled_only', 'true')
      if (params?.withAudioOnly) query.set('with_audio_only', 'true')
      if (typeof params?.page === 'number' && Number.isFinite(params.page) && params.page > 0) {
        query.set('page', String(Math.floor(params.page)))
      }
      if (typeof params?.pageSize === 'number' && Number.isFinite(params.pageSize) && params.pageSize > 0) {
        query.set('page_size', String(Math.floor(params.pageSize)))
      }
      const suffix = query.size > 0 ? `?${query.toString()}` : ''
      return fetchAPI<VoiceLibraryListResponse>(`/voice-library${suffix}`)
    },
    create: (data: {
      name: string
      reference_text?: string
      audio_file_path?: string
      is_enabled?: boolean
    }) =>
      fetchAPI<VoiceLibraryItem>('/voice-library', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    update: (itemId: number, data: {
      name?: string
      reference_text?: string
      audio_file_path?: string
      is_enabled?: boolean
    }) =>
      fetchAPI<VoiceLibraryItem>(`/voice-library/${itemId}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    delete: (itemId: number) =>
      fetchAPI<void>(`/voice-library/${itemId}`, { method: 'DELETE' }),
    uploadAudio: (itemId: number, file: File) =>
      uploadFile<VoiceLibraryItem>(`/voice-library/${itemId}/audio/upload`, file),
    deleteAudio: (itemId: number) =>
      fetchAPI<VoiceLibraryItem>(`/voice-library/${itemId}/audio`, { method: 'DELETE' }),
    importAudioWithText: (file: File, referenceText: string) => {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('reference_text', referenceText)
      return fetch(`${getInternalApiBaseUrl()}/voice-library/import/audio-with-text`, {
        method: 'POST',
        body: formData,
      }).then(async (response) => {
        if (!response.ok) {
          const error = await response.json().catch(() => ({}))
          throw new Error(error.detail || `API Error: ${response.status}`)
        }
        return response.json() as Promise<VoiceLibraryItem>
      })
    },
    importAudioFiles: (files: File[], rows: VoiceLibraryImportAudioRow[]) => {
      const formData = new FormData()
      files.forEach((file) => {
        formData.append('files', file)
      })
      formData.append('rows_json', JSON.stringify(rows))
      return fetch(`${getInternalApiBaseUrl()}/voice-library/import/audio-files`, {
        method: 'POST',
        body: formData,
      }).then(async (response) => {
        if (!response.ok) {
          const error = await response.json().catch(() => ({}))
          throw new Error(error.detail || `API Error: ${response.status}`)
        }
        return response.json() as Promise<VoiceLibraryImportAudioFilesResponse>
      })
    },
    importVideoLink: (data: {
      url: string
      start_time?: string
      end_time?: string
    }) =>
      fetchAPI<VoiceLibraryImportVideoLinkCreateResponse>('/voice-library/import/video-link', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    getImportJob: (jobId: string) =>
      fetchAPI<VoiceLibraryImportJob>(`/voice-library/import-jobs/${jobId}`),
    cancelAllImportJobs: () =>
      fetchAPI<VoiceLibraryCancelResponse>('/voice-library/import-jobs/cancel-all', {
        method: 'POST',
      }),
    cancelImportJob: (jobId: string) =>
      fetchAPI<VoiceLibraryCancelResponse>(`/voice-library/import-jobs/${jobId}/cancel`, {
        method: 'POST',
      }),
    cancelImportTask: (taskId: number) =>
      fetchAPI<VoiceLibraryCancelResponse>(`/voice-library/import-tasks/${taskId}/cancel`, {
        method: 'POST',
      }),
    cancelImportTaskByItem: (itemId: number) =>
      fetchAPI<VoiceLibraryCancelResponse>(`/voice-library/import-tasks/by-item/${itemId}/cancel`, {
        method: 'POST',
      }),
    retryImportTask: (taskId: number) =>
      fetchAPI<VoiceLibraryImportVideoLinkCreateResponse>(`/voice-library/import-tasks/${taskId}/retry`, {
        method: 'POST',
      }),
    restartInterruptedImportTasks: () =>
      fetchAPI<VoiceLibraryCancelResponse>('/voice-library/import-jobs/restart-interrupted', {
        method: 'POST',
      }),
    importEventsStreamUrl: () => `${getPublicApiBaseUrl()}/voice-library/import-events/stream`,
    retry: (itemId: number) =>
      fetchAPI<VoiceLibraryItem>(`/voice-library/${itemId}/retry`, {
        method: 'POST',
      }),
  },
  textLibrary: {
    list: (params?: { q?: string; enabledOnly?: boolean; page?: number; pageSize?: number }) => {
      const query = new URLSearchParams()
      if (params?.q?.trim()) query.set('q', params.q.trim())
      if (params?.enabledOnly) query.set('enabled_only', 'true')
      if (typeof params?.page === 'number' && Number.isFinite(params.page) && params.page > 0) {
        query.set('page', String(Math.floor(params.page)))
      }
      if (typeof params?.pageSize === 'number' && Number.isFinite(params.pageSize) && params.pageSize > 0) {
        query.set('page_size', String(Math.floor(params.pageSize)))
      }
      const suffix = query.size > 0 ? `?${query.toString()}` : ''
      return fetchAPI<TextLibraryListResponse>(`/text-library${suffix}`)
    },
    importCopy: (content: string) =>
      fetchAPI<TextLibraryItem>('/text-library/import/copy', {
        method: 'POST',
        body: JSON.stringify({ content }),
      }),
    importFiles: (files: File[]) => {
      const formData = new FormData()
      files.forEach((file) => {
        formData.append('files', file)
      })
      return fetch(`${getInternalApiBaseUrl()}/text-library/import/files`, {
        method: 'POST',
        body: formData,
      }).then(async (response) => {
        if (!response.ok) {
          const error = await response.json().catch(() => ({}))
          throw new Error(error.detail || `API Error: ${response.status}`)
        }
        return response.json() as Promise<TextLibraryItem[]>
      })
    },
    importLinks: (urlsText: string) =>
      fetchAPI<TextLibraryImportLinksCreateResponse>('/text-library/import/links', {
        method: 'POST',
        body: JSON.stringify({ urls_text: urlsText }),
      }),
    getImportJob: (jobId: string) =>
      fetchAPI<TextLibraryImportJob>(`/text-library/import-jobs/${jobId}`),
    cancelAllImportJobs: () =>
      fetchAPI<TextLibraryCancelResponse>('/text-library/import-jobs/cancel-all', {
        method: 'POST',
      }),
    cancelImportJob: (jobId: string) =>
      fetchAPI<TextLibraryCancelResponse>(`/text-library/import-jobs/${jobId}/cancel`, {
        method: 'POST',
      }),
    cancelImportTask: (taskId: number) =>
      fetchAPI<TextLibraryCancelResponse>(`/text-library/import-tasks/${taskId}/cancel`, {
        method: 'POST',
      }),
    cancelImportTaskByItem: (itemId: number) =>
      fetchAPI<TextLibraryCancelResponse>(`/text-library/import-tasks/by-item/${itemId}/cancel`, {
        method: 'POST',
      }),
    retryImportTask: (taskId: number) =>
      fetchAPI<TextLibraryImportLinksCreateResponse>(`/text-library/import-tasks/${taskId}/retry`, {
        method: 'POST',
      }),
    restartInterruptedImportTasks: () =>
      fetchAPI<TextLibraryCancelResponse>('/text-library/import-jobs/restart-interrupted', {
        method: 'POST',
      }),
    importEventsStreamUrl: () => `${getPublicApiBaseUrl()}/text-library/import-events/stream`,
    retry: (itemId: number) =>
      fetchAPI<TextLibraryItem>(`/text-library/${itemId}/retry`, {
        method: 'POST',
      }),
    update: (itemId: number, data: { name?: string; content?: string; is_enabled?: boolean }) =>
      fetchAPI<TextLibraryItem>(`/text-library/${itemId}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    delete: (itemId: number) =>
      fetchAPI<void>(`/text-library/${itemId}`, { method: 'DELETE' }),
  },
  settings: {
    get: () => fetchAPI<Settings>('/settings'),
    update: (data: SettingsUpdate) =>
      fetchAPI<Settings>('/settings', {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    uploadGoogleCredentials: (file: File) =>
      uploadFile<Settings>('/settings/google-credentials/upload', file),
    deleteGoogleCredentials: () =>
      fetchAPI<Settings>('/settings/google-credentials', {
        method: 'DELETE',
      }),
    fetchModels: (params: { providerType: LLMProviderType | ImageProviderType | string; baseUrl?: string; apiKey?: string }) => {
      const searchParams = new URLSearchParams()
      searchParams.set('provider_type', params.providerType)
      if (params.baseUrl) searchParams.set('base_url', params.baseUrl)
      if (params.apiKey) searchParams.set('api_key', params.apiKey)
      return fetchAPI<{ models: Array<{ id: string; object?: string; created?: number; owned_by?: string }> }>(`/settings/models?${searchParams.toString()}`)
    },
    testModel: (params: { providerType: LLMProviderType | ImageProviderType | string; baseUrl?: string; apiKey?: string; model: string }) =>
      fetchAPI<{ success: boolean; model: string; latency_ms?: number; message?: string; error?: string }>(
        '/settings/models/test',
        {
          method: 'POST',
          body: JSON.stringify({
            provider_type: params.providerType,
            base_url: params.baseUrl,
            api_key: params.apiKey,
            model: params.model,
          }),
        }
      ),
    testImageModel: (params: { providerId: string; model: string }) =>
      fetchAPI<{ success: boolean; model: string; latency_ms?: number; message?: string; error?: string }>(
        '/settings/image/models/test',
        {
          method: 'POST',
          body: JSON.stringify({
            provider_id: params.providerId,
            model: params.model,
          }),
        }
      ),
    testVideoModel: (params: {
      providerId: string
      model: string
      apiKey?: string
      accessKey?: string
      secretKey?: string
      baseUrl?: string
      projectId?: string
      location?: string
      wan2gpPath?: string
    }) =>
      fetchAPI<{ success: boolean; model: string; latency_ms?: number; message?: string; error?: string }>(
        '/settings/video/models/test',
        {
          method: 'POST',
          body: JSON.stringify({
            provider_id: params.providerId,
            model: params.model,
            api_key: params.apiKey,
            access_key: params.accessKey,
            secret_key: params.secretKey,
            base_url: params.baseUrl,
            project_id: params.projectId,
            location: params.location,
            wan2gp_path: params.wan2gpPath,
          }),
        }
      ),
    testSeedanceConnectivity: (params: { apiKey?: string; baseUrl?: string; model: string }) =>
      fetchAPI<{ success: boolean; model: string; latency_ms?: number; message?: string; error?: string }>(
        '/settings/video/volcengine_seedance/test',
        {
          method: 'POST',
          body: JSON.stringify({
            api_key: params.apiKey,
            base_url: params.baseUrl,
            model: params.model,
          }),
        }
      ),
    fetchVoices: (
      provider: string = 'edge_tts',
      options?: { forceRefresh?: boolean; modelName?: string }
    ) => {
      const params = new URLSearchParams({ provider })
      if (options?.forceRefresh) params.set('force_refresh', 'true')
      if (options?.modelName) params.set('model_name', options.modelName)
      return fetchAPI<{ voices: VoiceInfo[] }>(`/settings/voices?${params.toString()}`)
    },
    fetchProviders: () =>
      fetchAPI<AvailableProviders>('/settings/providers'),
    fetchWan2gpImagePresets: () =>
      fetchAPI<{ presets: Wan2gpImagePreset[] }>('/settings/image/wan2gp/presets'),
    fetchWan2gpVideoPresets: () =>
      fetchAPI<{ t2v_presets: Wan2gpVideoPreset[]; i2v_presets: Wan2gpVideoPreset[] }>('/settings/video/wan2gp/presets'),
    fetchWan2gpAudioPresets: () =>
      fetchAPI<{ presets: Wan2gpAudioPreset[] }>('/settings/audio/wan2gp/presets'),
    validateWan2gp: (data: { wan2gp_path?: string; local_model_python_path?: string }) =>
      fetchAPI<{ valid: boolean; wan2gp_path: string; python_path: string; torch_version: string }>(
        '/settings/wan2gp/validate',
        {
          method: 'POST',
          body: JSON.stringify(data),
        }
      ),
    validateFasterWhisper: (data: { model?: string }) =>
      fetchAPI<{
        valid: boolean
        model: string
        device: string
        compute_type: string
        elapsed_ms: number
        utterance_count: number
        word_count: number
        preview_text: string
      }>('/settings/faster-whisper/validate', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    testVolcengineSpeechRecognition: (data: {
      app_key?: string
      access_key?: string
      resource_id?: string
      language?: string
    }) =>
      fetchAPI<{
        valid: boolean
        app_key_masked: string
        resource_id: string
        language: string | null
        elapsed_ms: number
        utterance_count: number
        word_count: number
        preview_text: string
      }>('/settings/speech/volcengine_asr/test', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    validateCrawl4ai: () =>
      fetchAPI<{
        valid: boolean
        command_path: string
        command: string
        output_preview: string
      }>('/settings/crawl4ai/validate', {
        method: 'POST',
        body: JSON.stringify({}),
      }),
    validateXhsDownloader: (data: { xhs_downloader_path?: string }) =>
      fetchAPI<{
        valid: boolean
        xhs_downloader_path: string
        uv_path: string
        entry: string
      }>('/settings/xhs-downloader/validate', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    validateTiktokDownloader: (data: { tiktok_downloader_path?: string }) =>
      fetchAPI<{
        valid: boolean
        tiktok_downloader_path: string
        uv_path: string
        entry: string
      }>('/settings/tiktok-downloader/validate', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    validateKsDownloader: (data: { ks_downloader_path?: string }) =>
      fetchAPI<{
        valid: boolean
        ks_downloader_path: string
        uv_path: string
        entry: string
      }>('/settings/ks-downloader/validate', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    getJinaReaderUsage: (data: { jina_reader_api_key?: string }) =>
      fetchAPI<JinaReaderUsage>('/settings/jina-reader/usage', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    audioPreviewStreamUrl: (
      provider: 'edge_tts' | 'wan2gp' | 'volcengine_tts' | 'kling_tts' | 'vidu_tts' | 'minimax_tts' | 'xiaomi_mimo_tts',
      inputData?: Record<string, unknown>
    ) => {
      const params = new URLSearchParams({ provider })
      if (inputData) {
        params.set('input_data', JSON.stringify(inputData))
      }
      return `${getPublicApiBaseUrl()}/settings/audio/preview/stream?${params.toString()}`
    },
    getTavilyUsage: () =>
      fetchAPI<TavilyUsage>(`/settings/tavily/usage?ts=${Date.now()}`, {
        cache: 'no-store',
      }),
  },
  capabilities: {
    get: () => fetchAPI<Capabilities>('/capabilities'),
  },
  sources: {
    list: (projectId: number, selectedOnly = false) =>
      fetchAPI<SourceListResponse>(`/projects/${projectId}/sources?selected_only=${selectedOnly}`),
    get: (projectId: number, sourceId: number) =>
      fetchAPI<Source>(`/projects/${projectId}/sources/${sourceId}`),
    create: (projectId: number, data: SourceCreate) =>
      fetchAPI<Source>(`/projects/${projectId}/sources`, {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    update: (projectId: number, sourceId: number, data: SourceUpdate) =>
      fetchAPI<Source>(`/projects/${projectId}/sources/${sourceId}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      }),
    delete: (projectId: number, sourceId: number) =>
      fetchAPI<void>(`/projects/${projectId}/sources/${sourceId}`, { method: 'DELETE' }),
    batchUpdate: (projectId: number, data: SourceBatchUpdate) =>
      fetchAPI<{ updated_count: number }>(`/projects/${projectId}/sources/batch-update`, {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    importFromTextLibrary: (projectId: number, textLibraryIds: number[]) =>
      fetchAPI<SourceImportFromTextLibraryResponse>(`/projects/${projectId}/sources/import-from-text-library`, {
        method: 'POST',
        body: JSON.stringify({ text_library_ids: textLibraryIds }),
      }),
  },
}
