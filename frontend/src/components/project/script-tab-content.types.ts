import type { ReferenceLibraryItem, StageReferenceImportResult } from '@/types/reference'
import type { Shot, ScriptRole, DialogueLine, Reference } from '@/lib/content-panel-helpers'

export interface ScriptTabContentProps {
  stageData?: {
    content?: {
      title?: string
      content?: string
      char_count?: number
      shots_locked?: boolean
      script_mode?: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'
      roles?: ScriptRole[]
      dialogue_lines?: DialogueLine[]
    }
    storyboard?: {
      title?: string
      shots?: Shot[]
      references?: Reference[]
    }
    audio?: {
      shots?: Shot[]
    }
    reference?: {
      references?: Reference[]
      reference_images?: Array<{
        id: string
        name: string
        setting?: string
        appearance_description?: string
        can_speak?: boolean
        voice_audio_provider?: 'edge_tts' | 'wan2gp' | 'volcengine_tts' | 'kling_tts' | 'vidu_tts' | 'minimax_tts' | 'xiaomi_mimo_tts'
        voice_name?: string
        voice_speed?: number
        voice_wan2gp_preset?: string
        voice_wan2gp_alt_prompt?: string
        voice_wan2gp_audio_guide?: string
        voice_wan2gp_temperature?: number
        voice_wan2gp_top_k?: number
        voice_wan2gp_seed?: number
        file_path?: string
        generated?: boolean
      }>
    }
  }
  generatingShots?: Record<string, { status: string; progress: number }>
  runningStage?: string
  runningAction?: string
  runningReferenceId?: string | number
  progress?: number
  progressMessage?: string
  referenceStageStatus?: string
  configuredScriptMode?: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'
  narratorStyle?: string
  dialogueScriptMaxRoles?: number
  onSaveContent?: (data: {
    title?: string
    content?: string
    script_mode?: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'
    roles?: ScriptRole[]
    dialogue_lines?: DialogueLine[]
  }) => Promise<void>
  onDeleteContent?: () => Promise<void>
  onUnlockContentByClearingShots?: () => Promise<void>
  onImportDialogue?: (
    file: File,
    scriptMode: 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'
  ) => Promise<void>
  onSaveReference?: (
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
  ) => Promise<void>
  onDeleteReference?: (referenceId: string | number) => Promise<void>
  onRegenerateReferenceImage?: (referenceId: string | number) => Promise<void>
  onUploadReferenceImage?: (referenceId: string | number, file: File) => Promise<void>
  onCreateReference?: (
    data: {
      name?: string
      setting?: string
      appearance_description?: string
      can_speak?: boolean
      voice_audio_provider?: 'edge_tts' | 'wan2gp' | 'volcengine_tts' | 'kling_tts' | 'vidu_tts' | 'minimax_tts' | 'xiaomi_mimo_tts'
      voice_name?: string
      voice_speed?: number
      voice_wan2gp_preset?: string
      voice_wan2gp_alt_prompt?: string
      voice_wan2gp_audio_guide?: string
      voice_wan2gp_temperature?: number
      voice_wan2gp_top_k?: number
      voice_wan2gp_seed?: number
      file?: File
    }
  ) => Promise<void>
  onGenerateDescriptionFromImage?: (referenceId: string | number) => Promise<void>
  onDeleteReferenceImage?: (referenceId: string | number) => Promise<void>
  libraryReferences?: ReferenceLibraryItem[]
  onImportReferencesFromLibrary?: (data: {
    library_reference_ids: number[]
    start_reference_index?: number
    import_setting: boolean
    import_appearance_description: boolean
    import_image: boolean
    import_voice: boolean
  }) => Promise<StageReferenceImportResult>
  showReferencePanel?: boolean
}
