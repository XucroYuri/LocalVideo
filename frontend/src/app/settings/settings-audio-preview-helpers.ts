import type { VoiceInfo } from '@/types/settings'

export type AudioPreviewProvider =
  | 'wan2gp'
  | 'edge_tts'
  | 'volcengine_tts'
  | 'kling_tts'
  | 'vidu_tts'
  | 'minimax_tts'
  | 'xiaomi_mimo_tts'

export interface AudioPreviewState {
  isRunning: boolean
  status: string
  audioUrl: string
  error: string | null
}

export type AudioPreviewLocale =
  | 'zh-CN'
  | 'zh-TW'
  | 'zh-HK'
  | 'en-US'
  | 'en-GB'
  | 'ja-JP'
  | 'es-ES'
  | 'es-MX'
  | 'id-ID'

const VOICES_CACHE_KEY = 'localvideo_available_voices'

export const AUDIO_PREVIEW_TEXT_BY_LOCALE: Record<AudioPreviewLocale, string> = {
  'zh-CN': '您好，欢迎使用影流，祝您创作愉快。',
  'zh-TW': '哈囉，歡迎使用影流，祝你創作順利。',
  'zh-HK': '你好，歡迎使用影流，祝你創作順利。',
  'en-US': 'Hello, welcome to LocalVideo. Wishing you an inspiring creative session.',
  'en-GB': 'Hello, welcome to LocalVideo. Wishing you a smooth and inspiring creative session.',
  'ja-JP': 'こんにちは、LocalVideoへようこそ。創作を楽しんでください。',
  'es-ES': 'Hola, bienvenido a LocalVideo. Que disfrutes creando.',
  'es-MX': 'Hola, bienvenido a LocalVideo. Que disfrutes mucho creando.',
  'id-ID': 'Halo, selamat datang di LocalVideo. Semoga proses kreatifmu lancar.',
}
export const AUDIO_PREVIEW_TEXT = AUDIO_PREVIEW_TEXT_BY_LOCALE['zh-CN']
export const AUDIO_PREVIEW_STEPS_BY_PROVIDER: Record<AudioPreviewProvider, string[]> = {
  wan2gp: ['准备中...', '模型下载中...', '模型加载中...', '生成中...'],
  edge_tts: ['生成中...'],
  volcengine_tts: ['生成中...'],
  kling_tts: ['生成中...'],
  vidu_tts: ['生成中...'],
  minimax_tts: ['生成中...'],
  xiaomi_mimo_tts: ['生成中...'],
}

export type CachedVoiceProvider = string

export function normalizeAudioPreviewLocale(locale: string | undefined | null): AudioPreviewLocale {
  const rawLocale = String(locale || '').trim()
  if (!rawLocale) return 'zh-CN'

  const candidates = rawLocale
    .replace(/,/g, '/')
    .split('/')
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean)

  const values = candidates.length > 0 ? candidates : [rawLocale.toLowerCase()]
  for (const candidate of values) {
    if (candidate.startsWith('zh-hk') || candidate.startsWith('yue')) return 'zh-HK'
    if (candidate.startsWith('zh-tw')) return 'zh-TW'
    if (candidate.startsWith('zh')) return 'zh-CN'
    if (candidate.startsWith('en-gb')) return 'en-GB'
    if (candidate.startsWith('en')) return 'en-US'
    if (candidate.startsWith('ja')) return 'ja-JP'
    if (candidate.startsWith('es-mx')) return 'es-MX'
    if (candidate.startsWith('es')) return 'es-ES'
    if (candidate.startsWith('id')) return 'id-ID'
  }
  return 'zh-CN'
}

export function resolveAudioPreviewText(locale: string | undefined | null): string {
  return AUDIO_PREVIEW_TEXT_BY_LOCALE[normalizeAudioPreviewLocale(locale)] || AUDIO_PREVIEW_TEXT
}

function getVoiceCacheKey(provider: CachedVoiceProvider): string {
  return `${VOICES_CACHE_KEY}_${provider}`
}

export function loadCachedVoices(provider: CachedVoiceProvider = 'edge_tts'): VoiceInfo[] {
  if (typeof window === 'undefined') return []
  try {
    const cached = localStorage.getItem(getVoiceCacheKey(provider))
    return cached ? JSON.parse(cached) : []
  } catch {
    return []
  }
}

export function saveCachedVoices(
  voices: VoiceInfo[],
  provider: CachedVoiceProvider = 'edge_tts'
) {
  if (typeof window === 'undefined') return
  try {
    localStorage.setItem(getVoiceCacheKey(provider), JSON.stringify(voices))
  } catch {
    // ignore write errors on unsupported environments
  }
}
