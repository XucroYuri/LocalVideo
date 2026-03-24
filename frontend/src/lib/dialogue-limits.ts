export const MIN_DIALOGUE_SCRIPT_MAX_ROLES = 1
export const MAX_DIALOGUE_SCRIPT_MAX_ROLES = 20
export const DEFAULT_DIALOGUE_SCRIPT_MAX_ROLES = MAX_DIALOGUE_SCRIPT_MAX_ROLES

export function normalizeDialogueScriptMaxRoles(
  value: unknown,
  fallback = DEFAULT_DIALOGUE_SCRIPT_MAX_ROLES
): number {
  const parsed = Number(value)
  const normalized = Number.isFinite(parsed) ? Math.trunc(parsed) : fallback
  return Math.max(MIN_DIALOGUE_SCRIPT_MAX_ROLES, Math.min(MAX_DIALOGUE_SCRIPT_MAX_ROLES, normalized))
}
