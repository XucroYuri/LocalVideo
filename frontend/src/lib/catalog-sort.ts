import type { ReferenceLibraryItem } from '@/types/reference'
import type { VoiceLibraryItem } from '@/types/voice-library'

export function sortReferencesNewestFirst(items: ReferenceLibraryItem[]): ReferenceLibraryItem[] {
  return [...items].sort((left, right) => right.id - left.id)
}

function compareCreatedAtDescThenIdDesc(
  left: Pick<VoiceLibraryItem, 'created_at' | 'id'>,
  right: Pick<VoiceLibraryItem, 'created_at' | 'id'>
): number {
  const leftTime = Date.parse(left.created_at)
  const rightTime = Date.parse(right.created_at)
  if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) {
    return rightTime - leftTime
  }
  return right.id - left.id
}

export function sortVoiceLibraryItems(items: VoiceLibraryItem[]): VoiceLibraryItem[] {
  const customItems: VoiceLibraryItem[] = []
  const builtinItems: VoiceLibraryItem[] = []

  for (const item of items) {
    if (item.is_builtin) {
      builtinItems.push(item)
    } else {
      customItems.push(item)
    }
  }

  customItems.sort(compareCreatedAtDescThenIdDesc)
  return [...customItems, ...builtinItems]
}
