export type ContentSyncSnapshot = {
  roles: Array<{ id: string; name: string }>
  dialogue_lines: Array<{ speaker_id: string; speaker_name: string; text: string }>
  content: string
}

export type NarratorSyncTarget = {
  referenceId: string
  narratorIndex: number
  reference: {
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
    image_url?: string
  }
}
