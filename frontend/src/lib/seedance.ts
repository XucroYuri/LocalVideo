import type { SeedanceModelPreset as ApiSeedanceModelPreset } from '@/types/settings'

export interface SeedanceModelPreset {
  id: string
  label: string
  description: string
  supportsT2v: boolean
  supportsI2v: boolean
  supportsLastFrame: boolean
  supportsReferenceImage: boolean
  referenceRestrictions?: string[]
}

/** Convert backend capabilities response to frontend format. */
export function fromApiSeedancePresets(presets: ApiSeedanceModelPreset[]): SeedanceModelPreset[] {
  return presets.map((p) => ({
    id: p.id,
    label: p.label,
    description: p.description,
    supportsT2v: p.supports_t2v,
    supportsI2v: p.supports_i2v,
    supportsLastFrame: p.supports_last_frame,
    supportsReferenceImage: p.supports_reference_image,
    referenceRestrictions: p.reference_restrictions.length > 0 ? p.reference_restrictions : undefined,
  }))
}

/** Hardcoded fallback — used when capabilities API is not yet loaded. */
export const SEEDANCE_MODEL_PRESETS: SeedanceModelPreset[] = [
  {
    id: 'seedance-2-0',
    label: 'Seedance 2.0',
    description: '支持文生视频、图生视频与多模态参考视频',
    supportsT2v: true,
    supportsI2v: true,
    supportsLastFrame: true,
    supportsReferenceImage: true,
    referenceRestrictions: ['参考图模式支持 1~9 张图片'],
  },
  {
    id: 'seedance-2-0-fast',
    label: 'Seedance 2.0 fast',
    description: '更快的 Seedance 2.0，支持文生视频、图生视频与多模态参考视频',
    supportsT2v: true,
    supportsI2v: true,
    supportsLastFrame: true,
    supportsReferenceImage: true,
    referenceRestrictions: ['参考图模式支持 1~9 张图片'],
  },
]

export const SEEDANCE_ASPECT_RATIOS = ['adaptive', '16:9', '4:3', '1:1', '3:4', '9:16', '21:9']
export const SEEDANCE_RESOLUTIONS = ['480p', '720p']

export function resolveSeedancePreset(
  modelId: string | undefined,
  presets?: SeedanceModelPreset[]
): SeedanceModelPreset | undefined {
  if (!modelId) return undefined
  return (presets ?? SEEDANCE_MODEL_PRESETS).find((item) => item.id === modelId)
}
