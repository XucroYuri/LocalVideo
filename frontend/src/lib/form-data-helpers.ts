export interface VoiceFormFields {
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

export function appendVoiceFields(formData: FormData, data: VoiceFormFields): void {
  if (data.voice_audio_provider) formData.append('voice_audio_provider', data.voice_audio_provider)
  if (data.voice_name) formData.append('voice_name', data.voice_name)
  if (typeof data.voice_speed === 'number') formData.append('voice_speed', String(data.voice_speed))
  if (data.voice_wan2gp_preset !== undefined) formData.append('voice_wan2gp_preset', data.voice_wan2gp_preset)
  if (data.voice_wan2gp_alt_prompt !== undefined) formData.append('voice_wan2gp_alt_prompt', data.voice_wan2gp_alt_prompt)
  if (data.voice_wan2gp_audio_guide !== undefined) formData.append('voice_wan2gp_audio_guide', data.voice_wan2gp_audio_guide)
  if (typeof data.voice_wan2gp_temperature === 'number') {
    formData.append('voice_wan2gp_temperature', String(data.voice_wan2gp_temperature))
  }
  if (typeof data.voice_wan2gp_top_k === 'number') {
    formData.append('voice_wan2gp_top_k', String(data.voice_wan2gp_top_k))
  }
  if (typeof data.voice_wan2gp_seed === 'number') {
    formData.append('voice_wan2gp_seed', String(data.voice_wan2gp_seed))
  }
}
