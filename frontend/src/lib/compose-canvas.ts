export type ComposeCanvasStrategy = 'max_size' | 'most_common' | 'first_shot' | 'fixed'

export interface ComposeCanvasPreset {
  value: string
  width: number
  height: number
  label: string
}

export interface VideoShotDimension {
  width?: number
  height?: number
}

export interface ComposeCanvasEstimate {
  width: number
  height: number
  strategy: ComposeCanvasStrategy
  sourceLabel: string
}

export const COMPOSE_CANVAS_STRATEGY_OPTIONS: Array<{
  value: ComposeCanvasStrategy
  label: string
  description: string
}> = [
  {
    value: 'max_size',
    label: '取最大尺寸',
    description: '取当前分镜里像素面积最大的尺寸作为统一画布，尽量保留清晰度，其他分镜会等比缩放并补边。',
  },
  {
    value: 'most_common',
    label: '按最常见尺寸统一',
    description: '优先按当前分镜里出现次数最多的尺寸统一，适合大多数分镜本来就一致、只有少量离群尺寸的情况。',
  },
  {
    value: 'first_shot',
    label: '按首个分镜尺寸统一',
    description: '直接以第一个有效分镜的尺寸作为最终画布，适合你已经手动确认首个分镜就是目标尺寸的情况。',
  },
  {
    value: 'fixed',
    label: '按固定目标分辨率统一',
    description: '手动指定统一画布尺寸，所有分镜都会适配到这个固定输出分辨率。',
  },
]

export const COMPOSE_FIXED_ASPECT_RATIO_OPTIONS = ['9:16', '16:9', '1:1', '3:4', '4:3', '21:9'] as const

export const COMPOSE_FIXED_RESOLUTION_PRESETS: Record<string, ComposeCanvasPreset[]> = {
  '9:16': [
    { value: '540x960', width: 540, height: 960, label: '540x960' },
    { value: '720x1280', width: 720, height: 1280, label: '720x1280' },
    { value: '1080x1920', width: 1080, height: 1920, label: '1080x1920' },
  ],
  '16:9': [
    { value: '960x540', width: 960, height: 540, label: '960x540' },
    { value: '1280x720', width: 1280, height: 720, label: '1280x720' },
    { value: '1920x1080', width: 1920, height: 1080, label: '1920x1080' },
  ],
  '1:1': [
    { value: '720x720', width: 720, height: 720, label: '720x720' },
    { value: '1080x1080', width: 1080, height: 1080, label: '1080x1080' },
  ],
  '3:4': [
    { value: '720x960', width: 720, height: 960, label: '720x960' },
    { value: '1080x1440', width: 1080, height: 1440, label: '1080x1440' },
  ],
  '4:3': [
    { value: '960x720', width: 960, height: 720, label: '960x720' },
    { value: '1440x1080', width: 1440, height: 1080, label: '1440x1080' },
  ],
  '21:9': [
    { value: '1280x544', width: 1280, height: 544, label: '1280x544' },
    { value: '1920x816', width: 1920, height: 816, label: '1920x816' },
  ],
}

export function getComposeFixedResolutionOptions(aspectRatio: string | undefined): ComposeCanvasPreset[] {
  return COMPOSE_FIXED_RESOLUTION_PRESETS[String(aspectRatio || '').trim()] || COMPOSE_FIXED_RESOLUTION_PRESETS['9:16']
}

export function parseComposeResolution(value: string | undefined): { width: number; height: number } | null {
  const match = String(value || '').trim().match(/^(\d+)\s*x\s*(\d+)$/i)
  if (!match) return null
  const width = Number(match[1])
  const height = Number(match[2])
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return null
  }
  return { width, height }
}

export function formatAspectRatio(width: number, height: number): string {
  const safeWidth = Math.max(1, Math.round(width))
  const safeHeight = Math.max(1, Math.round(height))
  const divisor = gcd(safeWidth, safeHeight)
  return `${safeWidth / divisor}:${safeHeight / divisor}`
}

function gcd(a: number, b: number): number {
  let x = Math.abs(a)
  let y = Math.abs(b)
  while (y !== 0) {
    const next = x % y
    x = y
    y = next
  }
  return x || 1
}

function normalizeEvenDimensions(width: number, height: number): { width: number; height: number } {
  const safeWidth = width % 2 === 0 ? width : width - 1
  const safeHeight = height % 2 === 0 ? height : height - 1
  return {
    width: Math.max(safeWidth, 2),
    height: Math.max(safeHeight, 2),
  }
}

function getValidDimensions(videoItems: VideoShotDimension[]): Array<{ width: number; height: number; index: number }> {
  return videoItems.flatMap((videoItem, index) => {
    const width = Number(videoItem.width)
    const height = Number(videoItem.height)
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
      return []
    }
    const normalized = normalizeEvenDimensions(Math.round(width), Math.round(height))
    return [{ ...normalized, index }]
  })
}

export function estimateComposeCanvas(params: {
  strategy: ComposeCanvasStrategy
  videoItems: VideoShotDimension[]
  fixedResolution?: string
}): ComposeCanvasEstimate | null {
  const { strategy, videoItems, fixedResolution } = params
  if (strategy === 'fixed') {
    const parsed = parseComposeResolution(fixedResolution)
    if (!parsed) return null
    const normalized = normalizeEvenDimensions(parsed.width, parsed.height)
    return {
      ...normalized,
      strategy,
      sourceLabel: '固定目标分辨率',
    }
  }

  const dimensions = getValidDimensions(videoItems)
  if (dimensions.length === 0) return null

  if (strategy === 'first_shot') {
    const first = dimensions[0]
    return {
      width: first.width,
      height: first.height,
      strategy,
      sourceLabel: '首个分镜尺寸',
    }
  }

  if (strategy === 'most_common') {
    const counts = new Map<string, { width: number; height: number; count: number; firstIndex: number }>()
    dimensions.forEach((item) => {
      const key = `${item.width}x${item.height}`
      const existing = counts.get(key)
      if (existing) {
        existing.count += 1
      } else {
        counts.set(key, {
          width: item.width,
          height: item.height,
          count: 1,
          firstIndex: item.index,
        })
      }
    })
    const selected = Array.from(counts.values()).sort((a, b) => {
      if (b.count !== a.count) return b.count - a.count
      const areaDiff = (b.width * b.height) - (a.width * a.height)
      if (areaDiff !== 0) return areaDiff
      return a.firstIndex - b.firstIndex
    })[0]
    return {
      width: selected.width,
      height: selected.height,
      strategy,
      sourceLabel: `最常见尺寸（出现 ${selected.count} 次）`,
    }
  }

  const largest = dimensions.sort((a, b) => {
    const areaDiff = (b.width * b.height) - (a.width * a.height)
    if (areaDiff !== 0) return areaDiff
    return a.index - b.index
  })[0]
  return {
    width: largest.width,
    height: largest.height,
    strategy,
    sourceLabel: '当前最大尺寸',
  }
}
