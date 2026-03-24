export type VideoMode = 'oral_script_driven' | 'audio_visual_driven'
export type VideoType = 'custom' | 'single_narration' | 'duo_podcast' | 'dialogue_script'
export type ScriptMode = 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'

export const VIDEO_MODE_LABELS: Record<VideoMode, string> = {
  oral_script_driven: '口播文案驱动',
  audio_visual_driven: '声画驱动',
}

export const VIDEO_TYPE_LABELS: Record<VideoType, string> = {
  custom: '自定义',
  single_narration: '单人叙述',
  duo_podcast: '双人播客',
  dialogue_script: '台词剧本',
}

export function resolveVideoMode(value: unknown): VideoMode {
  const normalized = String(value || '').trim()
  if (normalized === 'audio_visual_driven') return 'audio_visual_driven'
  return 'oral_script_driven'
}

export function resolveVideoType(value: unknown): VideoType {
  const normalized = String(value || '').trim()
  if (normalized === 'custom') return 'custom'
  if (normalized === 'single_narration') return 'single_narration'
  if (normalized === 'duo_podcast') return 'duo_podcast'
  if (normalized === 'dialogue_script') return 'dialogue_script'
  return 'custom'
}

export function resolveScriptModeFromVideoType(value: unknown): ScriptMode {
  const type = resolveVideoType(value)
  if (type === 'duo_podcast') return 'duo_podcast'
  if (type === 'dialogue_script') return 'dialogue_script'
  if (type === 'custom') return 'custom'
  return 'single'
}

export function buildProjectModeLabel(modeValue: unknown, typeValue: unknown): string {
  const mode = resolveVideoMode(modeValue)
  const type = resolveVideoType(typeValue)
  return `${VIDEO_MODE_LABELS[mode]}-${VIDEO_TYPE_LABELS[type]}`
}
