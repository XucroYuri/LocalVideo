export const DEFAULT_SINGLE_TARGET_DURATION = 60
export const DEFAULT_DUO_TARGET_DURATION = 300

export const TEXT_TARGET_LANGUAGES = [
  { value: 'zh', label: '中文' },
  { value: 'en', label: '英文' },
] as const

export const TEXT_PROMPT_COMPLEXITIES = [
  { value: 'minimal', label: '极简（20字以内）' },
  { value: 'simple', label: '简单（20-50字）' },
  { value: 'normal', label: '正常（50-150字）' },
  { value: 'detailed', label: '细节（150-300字）' },
  { value: 'complex', label: '复杂（300-600字）' },
  { value: 'ultra', label: '极繁（600-1000字）' },
] as const

export const STORYBOARD_SHOT_DENSITIES = [
  { value: 'low', label: '低密度', hint: '少切镜，单镜头更长' },
  { value: 'medium', label: '中密度', hint: '常规短视频节奏' },
  { value: 'high', label: '高密度', hint: '快切，镜头更碎' },
] as const

export const IMAGE_STYLES = [
  { value: '__none__', label: '无预设' },
  { value: 'semi_realistic_anime', label: '半写实动漫' },
  { value: 'anime', label: '日系动漫' },
  { value: 'realistic', label: '写实风格' },
  { value: 'cartoon', label: '卡通风格' },
  { value: 'watercolor', label: '水彩风格' },
  { value: 'oil_painting', label: '油画风格' },
  { value: 'pixel_art', label: '像素风格' },
  { value: 'cyberpunk', label: '赛博朋克' },
] as const
