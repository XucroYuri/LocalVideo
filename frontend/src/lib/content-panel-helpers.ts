// ---------------------------------------------------------------------------
// Interfaces used by helpers AND content-panel.tsx
// ---------------------------------------------------------------------------

export interface Shot {
  id?: number
  shot_id?: string
  shot_index?: number
  order?: number
  voice_content?: string
  speaker_id?: string
  speaker_name?: string
  video_prompt?: string
  first_frame_description?: string
  first_frame_reference_slots?: Array<{ order?: number; id?: string; name?: string }>
  video_reference_slots?: Array<{ order?: number; id?: string; name?: string }>
  audio_url?: string
  video_url?: string
  duration?: number
  width?: number
  height?: number
  first_frame_url?: string
  updated_at?: number
}

export interface ScriptRole {
  id?: string
  name?: string
  description?: string
  seat_side?: 'left' | 'right' | null
  locked?: boolean
}

export interface DialogueLine {
  id?: string
  speaker_id?: string
  speaker_name?: string
  text?: string
  order?: number
}

export interface Reference {
  id: string | number
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
  image_url?: string
}

// ---------------------------------------------------------------------------
// Type alias
// ---------------------------------------------------------------------------

export type ScriptMode = 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const SINGLE_ROLE_ID = 'ref_01'
export const SINGLE_ROLE_NAME = '讲述者'
export const DUO_ROLE_1_ID = 'ref_01'
export const DUO_ROLE_2_ID = 'ref_02'
export const DUO_SCENE_ROLE_ID = 'ref_03'
export const DUO_ROLE_1_NAME = '讲述者1'
export const DUO_ROLE_2_NAME = '讲述者2'
export const DUO_SCENE_ROLE_NAME = '播客场景'
export const DUO_ROLE_1_DESCRIPTION = '冷静理性，擅长先给结论再拆解逻辑与证据；表达克制清晰，像在带着听众做结构化梳理。'
export const DUO_ROLE_2_DESCRIPTION = '好奇敏锐，擅长追问关键细节并把抽象概念翻译成生活化表达；语气亲切有节奏，负责推进讨论。'
export const DUO_SCENE_DESCRIPTION = '双人播客录音间，桌面麦克风对谈，氛围专业但轻松。'
export const DUO_SEAT_LEFT = 'left'
export const DUO_SEAT_RIGHT = 'right'
export const NARRATOR_ROLE_ID = SINGLE_ROLE_ID
export const NARRATOR_ROLE_NAME = '画外音'
const NARRATOR_NAME_ALIASES = new Set(['narrator', '旁白', '画外音', 'vo', 'voiceover', 'voice_over'])
const REF_ID_PATTERN = /^ref_(\d+)$/

// ---------------------------------------------------------------------------
// Helper functions
// ---------------------------------------------------------------------------

export function resolveScriptMode(value: string | undefined, fallback: ScriptMode = 'single'): ScriptMode {
  if (value === 'custom' || value === 'duo_podcast' || value === 'dialogue_script' || value === 'single') return value
  return fallback
}

export function isMultiScriptMode(mode: ScriptMode): boolean {
  return mode === 'custom' || mode === 'single' || mode === 'duo_podcast' || mode === 'dialogue_script'
}

export function countScriptChars(text: string): number {
  return text.replace(/[^\u4e00-\u9fa5a-zA-Z0-9]/g, '').length
}

export function flattenDialogueLines(lines: DialogueLine[]): string {
  return lines.map((line) => String(line.text || '').trim()).filter(Boolean).join('')
}

export function mergeConsecutiveDialogueLines(lines: DialogueLine[]): DialogueLine[] {
  const merged: DialogueLine[] = []
  for (const item of lines) {
    const text = String(item.text || '').trim()
    if (!text) continue

    const speakerId = String(item.speaker_id || '').trim() || SINGLE_ROLE_ID
    const speakerName = String(item.speaker_name || '').trim() || speakerId
    const lineId = String(item.id || '').trim() || `line_${merged.length + 1}`

    if (merged.length > 0 && String(merged[merged.length - 1]?.speaker_id || '').trim() === speakerId) {
      const previousText = String(merged[merged.length - 1]?.text || '').trim()
      merged[merged.length - 1] = {
        ...merged[merged.length - 1],
        text: previousText ? `${previousText}${text}` : text,
      }
      continue
    }

    merged.push({
      ...item,
      id: lineId,
      speaker_id: speakerId,
      speaker_name: speakerName,
      text,
      order: merged.length,
    })
  }

  return merged.map((line, index) => ({
    ...line,
    order: index,
  }))
}

export function normalizeRoleId(value: string | undefined, fallback: string): string {
  const cleaned = String(value || '')
    .trim()
    .replace(/\s+/g, '_')
    .replace(/[^a-zA-Z0-9_-]/g, '')
    .toLowerCase()
  return cleaned || fallback
}

export function isReferenceId(value: string | undefined): boolean {
  return REF_ID_PATTERN.test(String(value || '').trim())
}

export function getNextReferenceId(existingIds: Iterable<string>): string {
  const used = new Set<number>()
  for (const rawId of existingIds) {
    const match = String(rawId || '').trim().match(REF_ID_PATTERN)
    if (!match) continue
    used.add(Number(match[1]))
  }
  let next = 1
  while (used.has(next)) next += 1
  return `ref_${String(next).padStart(2, '0')}`
}

export function isDuoSceneRoleId(roleId: string | undefined): boolean {
  const normalized = String(roleId || '').trim().toLowerCase()
  return normalized === DUO_SCENE_ROLE_ID
}

export function normalizeDuoSeatSide(value: unknown): 'left' | 'right' | null {
  const normalized = String(value || '').trim().toLowerCase()
  if (normalized === DUO_SEAT_LEFT || normalized === '左') return DUO_SEAT_LEFT
  if (normalized === DUO_SEAT_RIGHT || normalized === '右') return DUO_SEAT_RIGHT
  return null
}

export function getOppositeDuoSeatSide(value: 'left' | 'right'): 'left' | 'right' {
  return value === DUO_SEAT_LEFT ? DUO_SEAT_RIGHT : DUO_SEAT_LEFT
}

export function resolveDuoSeatPair(
  role1Seat: 'left' | 'right' | null,
  role2Seat: 'left' | 'right' | null
): ['left' | 'right', 'left' | 'right'] {
  if (role1Seat && role2Seat) {
    if (role1Seat === role2Seat) {
      return [role1Seat, getOppositeDuoSeatSide(role1Seat)]
    }
    return [role1Seat, role2Seat]
  }
  if (role1Seat && !role2Seat) {
    return [role1Seat, getOppositeDuoSeatSide(role1Seat)]
  }
  if (role2Seat && !role1Seat) {
    return [getOppositeDuoSeatSide(role2Seat), role2Seat]
  }
  return [DUO_SEAT_LEFT, DUO_SEAT_RIGHT]
}

export function normalizeRolesForMode(
  mode: ScriptMode,
  roles: ScriptRole[] | undefined,
  maxRoles: number
): ScriptRole[] {
  if (mode === 'single') {
    const role1 = (roles || []).find((role) => String(role.id || '') === SINGLE_ROLE_ID) || roles?.[0] || {}
    return [
      {
        id: SINGLE_ROLE_ID,
        name: String(role1.name || '').trim() || SINGLE_ROLE_NAME,
        description: String(role1.description || '').trim(),
        seat_side: null,
        locked: true,
      },
    ]
  }
  if (mode === 'duo_podcast') {
    const role1 = (roles || []).find((role) => String(role.id || '') === DUO_ROLE_1_ID) || roles?.[0] || {}
    const role2 = (roles || []).find((role) => String(role.id || '') === DUO_ROLE_2_ID) || roles?.[1] || {}
    const scene = (
      (roles || []).find((role) => isDuoSceneRoleId(String(role.id || '')))
      || roles?.[2]
      || {}
    )
    const [role1SeatSide, role2SeatSide] = resolveDuoSeatPair(
      normalizeDuoSeatSide(role1.seat_side),
      normalizeDuoSeatSide(role2.seat_side)
    )
    return [
      {
        id: DUO_ROLE_1_ID,
        name: String(role1.name || '').trim() || DUO_ROLE_1_NAME,
        description: String(role1.description || '').trim() || DUO_ROLE_1_DESCRIPTION,
        seat_side: role1SeatSide,
        locked: true,
      },
      {
        id: DUO_ROLE_2_ID,
        name: String(role2.name || '').trim() || DUO_ROLE_2_NAME,
        description: String(role2.description || '').trim() || DUO_ROLE_2_DESCRIPTION,
        seat_side: role2SeatSide,
        locked: true,
      },
      {
        id: DUO_SCENE_ROLE_ID,
        name: String(scene.name || '').trim() || DUO_SCENE_ROLE_NAME,
        description: String(scene.description || '').trim() || DUO_SCENE_DESCRIPTION,
        seat_side: null,
        locked: true,
      },
    ]
  }

  const result: ScriptRole[] = []
  const seen = new Set<string>()
  const normalizedMaxRoles = Math.max(1, maxRoles)
  const usedIds = new Set<string>()
  for (const role of roles || []) {
    const roleName = String(role.name || '').trim()
    const normalizedNameLower = roleName.toLowerCase()
    let nextId = String(role.id || '').trim()
    if (!isReferenceId(nextId)) {
      nextId = getNextReferenceId(usedIds)
    }
    if (seen.has(nextId)) continue
    seen.add(nextId)
    usedIds.add(nextId)
    const normalizedRole: ScriptRole = {
      id: nextId,
      name: roleName || (NARRATOR_NAME_ALIASES.has(normalizedNameLower) ? NARRATOR_ROLE_NAME : `角色${result.length + 1}`),
      description: String(role.description || '').trim(),
      seat_side: null,
      locked: false,
    }
    if (result.length >= normalizedMaxRoles) continue
    result.push(normalizedRole)
  }
  return result
}

export function buildRolesFromReferences(references: Reference[] | undefined): ScriptRole[] {
  return (references || [])
    .filter((reference) => reference.can_speak !== false)
    .map((reference) => ({
      id: String(reference.id),
      name: String(reference.name || '').trim() || '未命名参考',
      description: String(reference.setting || '').trim(),
      seat_side: null,
      locked: true,
    }))
}

export function buildSpeakerOptionsForMode(
  mode: ScriptMode,
  roles: ScriptRole[],
  references: Reference[] | undefined
): Array<{ id: string; name: string }> {
  const referenceList = references || []
  const speakableReferences = referenceList.filter((reference) => reference.can_speak !== false)
  const referenceNameById = new Map(
    speakableReferences
      .map((reference) => [String(reference.id || '').trim(), String(reference.name || '').trim()])
      .filter((item): item is [string, string] => !!item[0])
  )
  const referenceIdSet = new Set(referenceNameById.keys())

  if (mode === 'dialogue_script') {
    const roleOptions = roles
      .map((role) => ({
        id: String(role.id || '').trim(),
        name: String(role.name || '').trim() || '角色',
      }))
      .filter((item) => !!item.id)
    if (roleOptions.length > 0) return roleOptions
    return speakableReferences
      .map((reference) => ({
        id: String(reference.id || '').trim(),
        name: String(reference.name || '').trim() || '角色',
      }))
      .filter((item) => !!item.id)
  }

  if (mode === 'duo_podcast') {
    return roles
      .filter((role) => {
        const roleId = String(role.id || '').trim()
        return (roleId === DUO_ROLE_1_ID || roleId === DUO_ROLE_2_ID) && referenceIdSet.has(roleId)
      })
      .map((role) => {
        const roleId = String(role.id || '').trim()
        return {
          id: roleId,
          name: referenceNameById.get(roleId) || String(role.name || '').trim() || '角色',
        }
      })
      .filter((item) => !!item.id)
  }

  return roles
    .map((role) => ({
      id: String(role.id || '').trim(),
      name: String(role.name || '').trim() || '角色',
    }))
    .filter((item) => !!item.id)
}

export function getRoleName(roleId: string | undefined, roles: ScriptRole[]): string {
  if (!roleId) return SINGLE_ROLE_NAME
  const matched = roles.find((role) => String(role.id || '') === roleId)
  return String(matched?.name || '').trim() || roleId
}

export function normalizeDialogueLinesForMode(
  mode: ScriptMode,
  lines: DialogueLine[] | undefined,
  roles: ScriptRole[],
  fallbackContent: string
): DialogueLine[] {
  const dialogueRoles = mode === 'duo_podcast'
    ? roles.filter((role) => {
        const roleId = String(role.id || '').trim()
        return roleId === DUO_ROLE_1_ID || roleId === DUO_ROLE_2_ID
      })
    : roles
  const allowedSpeakerIds = new Set<string>()
  for (const role of dialogueRoles) {
    const id = String(role.id || '').trim()
    if (id) allowedSpeakerIds.add(id)
  }

  const defaultSpeakerId = (mode === 'dialogue_script' || mode === 'custom')
    ? (String(dialogueRoles[0]?.id || '').trim() || SINGLE_ROLE_ID)
    : (String(dialogueRoles[0]?.id || SINGLE_ROLE_ID))

  const normalized: DialogueLine[] = []
  for (const [index, rawLine] of (lines || []).entries()) {
    const text = String(rawLine.text || '').trim()
    if (!text) continue
    const requestedSpeakerId = String(rawLine.speaker_id || '').trim()
    const requestedSpeakerName = String(rawLine.speaker_name || '').trim()
    const shouldKeepLooseSpeaker = mode === 'custom' || mode === 'dialogue_script'
    const speakerId = allowedSpeakerIds.has(requestedSpeakerId)
      ? requestedSpeakerId
      : (
          shouldKeepLooseSpeaker
            ? (requestedSpeakerId || requestedSpeakerName || defaultSpeakerId)
            : defaultSpeakerId
        )
    const speakerName = (
      shouldKeepLooseSpeaker
      && !allowedSpeakerIds.has(requestedSpeakerId)
      && requestedSpeakerName
    )
      ? requestedSpeakerName
      : getRoleName(speakerId, roles)
    normalized.push({
      id: String(rawLine.id || '').trim() || `line_${index + 1}`,
      speaker_id: speakerId,
      speaker_name: speakerName,
      text,
      order: normalized.length,
    })
  }

  if (normalized.length === 0 && String(fallbackContent || '').trim()) {
    normalized.push({
      id: 'line_1',
      speaker_id: defaultSpeakerId,
      speaker_name: getRoleName(defaultSpeakerId, roles),
      text: String(fallbackContent || '').trim(),
      order: 0,
    })
  }

  if (mode === 'single') {
    if (normalized.length === 0) return []
    const singleSpeakerId = String(roles[0]?.id || SINGLE_ROLE_ID)
    return normalized.map((line, index) => ({
      ...line,
      speaker_id: singleSpeakerId,
      speaker_name: getRoleName(singleSpeakerId, roles),
      order: index,
    }))
  }

  return normalized
}

export function formatRuntimeProgressText(message: string, progressValue: number): string {
  const trimmed = message.trim()
  const isModelDownload = /^模型下载中/.test(trimmed)
  const base = isModelDownload
    ? trimmed
    : message.replace(/\s*[（(]\d+%\s*[）)]\s*/g, ' ').trim()
  const hasPercentInMessage = /\d+\s*%/.test(base)
  if (/生成中|执行中/.test(base) && !hasPercentInMessage) {
    return `${base} ${progressValue}%`
  }
  return base
}

export function resolveShotGeneratingState(params: {
  isStageRunning: boolean
  isSingleShotRun: boolean
  isTargetShot: boolean
  hasShotState: boolean
  hasGeneratingShot: boolean
}): { isGenerating: boolean; isStarting: boolean } {
  const { isStageRunning, isSingleShotRun, isTargetShot, hasShotState, hasGeneratingShot } = params
  if (!isStageRunning) {
    return { isGenerating: false, isStarting: false }
  }
  if (isSingleShotRun) {
    const isGenerating = isTargetShot
    return { isGenerating, isStarting: isGenerating && !hasShotState }
  }
  const isStarting = !hasGeneratingShot
  const isGenerating = hasShotState || isStarting
  return { isGenerating, isStarting }
}

export function isStageRunningWithFallback(params: {
  runningStage?: string
  runningAction?: string
  targetStage: string
  requiredAction?: string
  fallbackStageStatus?: string
  hasGeneratingShot: boolean
  fallbackRequiresGeneratingShot?: boolean
}): boolean {
  const {
    runningStage,
    runningAction,
    targetStage,
    requiredAction,
    fallbackStageStatus,
    hasGeneratingShot,
    fallbackRequiresGeneratingShot = false,
  } = params
  if (runningStage === targetStage) {
    return !requiredAction || runningAction === requiredAction
  }
  if (!runningStage && fallbackStageStatus === 'running') {
    return !fallbackRequiresGeneratingShot || hasGeneratingShot
  }
  return false
}

export function resolveCurrentItemGenerationState(params: {
  isStageRunning: boolean
  isSingleItemRun: boolean
  isTargetItem: boolean
  hasItemState: boolean
  hasGeneratingItem: boolean
  batchMode?: 'active_only'
  singleRunUseItemState?: boolean
}): { isGenerating: boolean; isStarting: boolean } {
  const {
    isStageRunning,
    isSingleItemRun,
    isTargetItem,
    hasItemState,
    hasGeneratingItem,
    batchMode = 'active_only',
    singleRunUseItemState = false,
  } = params
  if (!isStageRunning) {
    return { isGenerating: false, isStarting: false }
  }
  if (isSingleItemRun) {
    const isGenerating = singleRunUseItemState ? (isTargetItem || hasItemState) : isTargetItem
    return { isGenerating, isStarting: isGenerating && !hasItemState }
  }
  if (batchMode === 'active_only') {
    return { isGenerating: hasItemState, isStarting: false }
  }
  return { isGenerating: hasItemState || hasGeneratingItem, isStarting: false }
}

export function resolveRuntimeDisplay(params: {
  isGenerating: boolean
  isStarting: boolean
  shotProgress?: number
  stageProgress?: number
  progressMessage?: string
}): {
  progress: number
  runtimeMessage: string
  progressText: string
  isModelDownloading: boolean
} {
  const { isGenerating, isStarting, shotProgress, stageProgress, progressMessage } = params
  const progress = Math.max(
    0,
    Math.min(
      100,
      Math.round(
        typeof shotProgress === 'number'
          ? shotProgress
          : (isGenerating ? (stageProgress ?? 0) : 0)
      )
    )
  )
  const runtimeMessage = (progressMessage || '').trim() || (isStarting ? '准备中...' : '生成中...')
  return {
    progress,
    runtimeMessage,
    progressText: formatRuntimeProgressText(runtimeMessage, progress),
    isModelDownloading: runtimeMessage.startsWith('模型下载中'),
  }
}
