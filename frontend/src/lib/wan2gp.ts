export interface Wan2gpResolutionChoice {
  value: string
  tier: string
  label: string
  isDefault: boolean
}

export type Wan2gpPromptLanguagePreference = 'zh' | 'balanced' | 'en' | string

export function getWan2gpPromptLanguageHint(
  subject: string,
  preference: Wan2gpPromptLanguagePreference,
  supportsChinese?: boolean
): string {
  switch (preference) {
    case 'zh':
      return `${subject}更适合中文 prompt，建议优先使用中文描述。`
    case 'en':
      return `${subject}更适合英文 prompt，建议优先使用英文描述。`
    case 'balanced':
      return `${subject}中英文 prompt 均可，可按习惯选择。`
    default:
      return supportsChinese
        ? `${subject}支持中文 prompt，也可使用英文描述。`
        : `${subject}不支持中文 prompt，请使用英文描述。`
  }
}

interface ResolutionPreset {
  value: string
  ratio: string
  isDefault?: boolean
}

interface ResolutionTierPreset {
  tier: string
  items: ResolutionPreset[]
}

const WAN2GP_RESOLUTION_PRESETS: ResolutionTierPreset[] = [
  {
    tier: '1080p',
    items: [
      { value: '1920x1088', ratio: '16:9' },
      { value: '1088x1920', ratio: '9:16', isDefault: true },
      { value: '1920x832', ratio: '21:9' },
      { value: '832x1920', ratio: '9:21' },
    ],
  },
  {
    tier: '720p',
    items: [
      { value: '1024x1024', ratio: '1:1' },
      { value: '1280x720', ratio: '16:9' },
      { value: '720x1280', ratio: '9:16', isDefault: true },
      { value: '1280x544', ratio: '21:9' },
      { value: '544x1280', ratio: '9:21' },
      { value: '1104x832', ratio: '4:3' },
      { value: '832x1104', ratio: '3:4' },
      { value: '960x960', ratio: '1:1' },
    ],
  },
  {
    tier: '540p',
    items: [
      { value: '960x544', ratio: '16:9' },
      { value: '544x960', ratio: '9:16', isDefault: true },
    ],
  },
  {
    tier: '480p',
    items: [
      { value: '832x624', ratio: '4:3' },
      { value: '624x832', ratio: '3:4' },
      { value: '720x720', ratio: '1:1' },
      { value: '832x480', ratio: '16:9' },
      { value: '480x832', ratio: '9:16', isDefault: true },
      { value: '512x512', ratio: '1:1' },
    ],
  },
]

const TIER_ORDER = WAN2GP_RESOLUTION_PRESETS.map((item) => item.tier)

const PRESET_LOOKUP = new Map<string, Wan2gpResolutionChoice>()
const PRESET_POSITION = new Map<string, number>()

let globalIndex = 0
for (const tierPreset of WAN2GP_RESOLUTION_PRESETS) {
  for (const item of tierPreset.items) {
    PRESET_LOOKUP.set(item.value, {
      value: item.value,
      tier: tierPreset.tier,
      label: `${item.value} (${item.ratio})`,
      isDefault: !!item.isDefault,
    })
    PRESET_POSITION.set(item.value, globalIndex)
    globalIndex += 1
  }
}

function parseResolution(value: string): { width: number; height: number } | null {
  const match = /^(\d+)x(\d+)$/.exec(value)
  if (!match) return null
  return {
    width: Number(match[1]),
    height: Number(match[2]),
  }
}

function gcd(a: number, b: number): number {
  let x = Math.abs(a)
  let y = Math.abs(b)
  while (y !== 0) {
    const t = x % y
    x = y
    y = t
  }
  return x || 1
}

function formatRatio(value: string): string {
  const parsed = parseResolution(value)
  if (!parsed || parsed.width <= 0 || parsed.height <= 0) {
    return value
  }
  const divisor = gcd(parsed.width, parsed.height)
  return `${parsed.width / divisor}:${parsed.height / divisor}`
}

function inferTier(value: string): string {
  const parsed = parseResolution(value)
  if (!parsed) return 'other'
  const shortSide = Math.min(parsed.width, parsed.height)
  if (shortSide >= 1000) return '1080p'
  if (shortSide >= 700) return '720p'
  if (shortSide >= 540) return '540p'
  if (shortSide >= 480) return '480p'
  return 'other'
}

export function getWan2gpResolutionChoice(value: string): Wan2gpResolutionChoice {
  const preset = PRESET_LOOKUP.get(value)
  if (preset) return preset
  return {
    value,
    tier: inferTier(value),
    label: `${value} (${formatRatio(value)})`,
    isDefault: false,
  }
}

export function getWan2gpResolutionChoices(supportedResolutions: string[]): Wan2gpResolutionChoice[] {
  const uniqueResolutions = Array.from(
    new Set((supportedResolutions || []).filter((item) => typeof item === 'string' && item.length > 0))
  )

  const choices = uniqueResolutions.map((value) => getWan2gpResolutionChoice(value))
  choices.sort((a, b) => {
    const tierA = TIER_ORDER.indexOf(a.tier)
    const tierB = TIER_ORDER.indexOf(b.tier)
    if (tierA !== tierB) {
      if (tierA === -1) return 1
      if (tierB === -1) return -1
      return tierA - tierB
    }
    const posA = PRESET_POSITION.get(a.value)
    const posB = PRESET_POSITION.get(b.value)
    if (posA !== undefined && posB !== undefined && posA !== posB) {
      return posA - posB
    }
    return a.value.localeCompare(b.value)
  })
  return choices
}

export function getWan2gpResolutionTiers(choices: Wan2gpResolutionChoice[]): string[] {
  const tiers = Array.from(new Set(choices.map((item) => item.tier)))
  return tiers.sort((a, b) => {
    const idxA = TIER_ORDER.indexOf(a)
    const idxB = TIER_ORDER.indexOf(b)
    if (idxA !== idxB) {
      if (idxA === -1) return 1
      if (idxB === -1) return -1
      return idxA - idxB
    }
    return a.localeCompare(b)
  })
}

export function pickDefaultResolutionForTier(
  choices: Wan2gpResolutionChoice[],
  tier: string
): string | undefined {
  const tierChoices = choices.filter((item) => item.tier === tier)
  if (tierChoices.length === 0) return undefined
  return tierChoices.find((item) => item.isDefault)?.value || tierChoices[0].value
}
