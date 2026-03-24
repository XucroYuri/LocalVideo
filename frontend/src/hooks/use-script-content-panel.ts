'use client'

import { useState, useCallback, useRef, useEffect, useMemo } from 'react'
import { toast } from 'sonner'

import { useConfirmDialog } from '@/components/common/confirm-dialog-provider'
import type { ScriptRole, DialogueLine, Reference, ScriptMode } from '@/lib/content-panel-helpers'
import {
  NARRATOR_ROLE_ID,
  resolveScriptMode,
  isMultiScriptMode,
  countScriptChars,
  flattenDialogueLines,
  mergeConsecutiveDialogueLines,
  normalizeRolesForMode,
  buildRolesFromReferences,
  buildSpeakerOptionsForMode,
  getRoleName,
  normalizeDialogueLinesForMode,
} from '@/lib/content-panel-helpers'
import {
  DEFAULT_DIALOGUE_SCRIPT_MAX_ROLES,
  normalizeDialogueScriptMaxRoles,
} from '@/lib/dialogue-limits'

// ---------------------------------------------------------------------------
// Params interface
// ---------------------------------------------------------------------------

export interface UseScriptContentPanelParams {
  stageData?: {
    content?: {
      title?: string
      content?: string
      char_count?: number
      shots_locked?: boolean
      script_mode?: ScriptMode
      roles?: ScriptRole[]
      dialogue_lines?: DialogueLine[]
    }
    storyboard?: {
      shots?: Array<{ shot_id?: string }>
      references?: Reference[]
    }
    reference?: {
      references?: Reference[]
    }
  }
  runningStage?: string
  progress?: number
  progressMessage?: string
  configuredScriptMode?: ScriptMode
  dialogueScriptMaxRoles?: number
  onSaveContent?: (data: {
    title?: string
    content?: string
    script_mode?: ScriptMode
    roles?: ScriptRole[]
    dialogue_lines?: DialogueLine[]
  }) => Promise<void>
  onDeleteContent?: () => Promise<void>
  onUnlockContentByClearingShots?: () => Promise<void>
  onImportDialogue?: (file: File, scriptMode: ScriptMode) => Promise<void>
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useScriptContentPanel(params: UseScriptContentPanelParams) {
  const {
    stageData,
    runningStage,
    configuredScriptMode,
    dialogueScriptMaxRoles = DEFAULT_DIALOGUE_SCRIPT_MAX_ROLES,
    onSaveContent,
    onDeleteContent,
    onUnlockContentByClearingShots,
    onImportDialogue,
  } = params
  const confirmDialog = useConfirmDialog()

  // ---- State ----
  const [isEditingContent, setIsEditingContent] = useState(false)
  const [editedTitle, setEditedTitle] = useState('')
  const [editedContent, setEditedContent] = useState('')
  const [editedScriptMode, setEditedScriptMode] = useState<ScriptMode>('single')
  const [editedRoles, setEditedRoles] = useState<ScriptRole[]>([])
  const [editedDialogueLines, setEditedDialogueLines] = useState<DialogueLine[]>([])
  const [isSavingContent, setIsSavingContent] = useState(false)
  const [isDeletingContent, setIsDeletingContent] = useState(false)
  const [isImportingDialogue, setIsImportingDialogue] = useState(false)
  const [isAutoSavingContent, setIsAutoSavingContent] = useState(false)
  const dialogueImportInputRef = useRef<HTMLInputElement>(null)
  const contentAutoSaveTimerRef = useRef<number | null>(null)
  const lastSubmittedContentSignatureRef = useRef<string>('')
  const dialogueLineIdCounterRef = useRef<number>(1)

  // ---- Derived values ----
  const resolvedConfiguredScriptMode = resolveScriptMode(configuredScriptMode)
  const maxDialogueRoleCount = normalizeDialogueScriptMaxRoles(dialogueScriptMaxRoles)
  const references = stageData?.reference?.references || stageData?.storyboard?.references || []

  const scriptMode = resolveScriptMode(
    configuredScriptMode || stageData?.content?.script_mode,
    resolvedConfiguredScriptMode
  )
  const isMultiMode = isMultiScriptMode(scriptMode)
  const contentRoles = normalizeRolesForMode(
    scriptMode,
    stageData?.content?.roles,
    maxDialogueRoleCount
  )
  const referenceRoles = normalizeRolesForMode(
    'dialogue_script',
    buildRolesFromReferences(references),
    maxDialogueRoleCount
  )
  const viewRoles = scriptMode === 'dialogue_script'
    ? (contentRoles.length > 0 ? contentRoles : referenceRoles)
    : contentRoles
  const viewDialogueLines = normalizeDialogueLinesForMode(
    scriptMode,
    stageData?.content?.dialogue_lines,
    viewRoles,
    stageData?.content?.content || ''
  )

  const hasSavedTitle = !!String(stageData?.content?.title || '').trim()
  const hasSavedRoles = (stageData?.content?.roles?.length || 0) > 0
  const hasSavedDialogue = (stageData?.content?.dialogue_lines?.length || 0) > 0
  const hasSavedPlainContent = !!String(stageData?.content?.content || '').trim()
  const hasScriptBody = viewDialogueLines.length > 0 || hasSavedPlainContent
  const hasContent = isMultiMode
    ? viewRoles.length > 0
      || viewDialogueLines.length > 0
      || hasSavedPlainContent
      || hasSavedTitle
      || hasSavedRoles
      || hasSavedDialogue
    : hasSavedPlainContent || hasSavedTitle || hasSavedRoles

  const contentTextForCount = isMultiMode
    ? flattenDialogueLines(viewDialogueLines)
    : String(stageData?.content?.content || '')
  const displayCharCount = stageData?.content?.char_count ?? countScriptChars(contentTextForCount)

  const displayMode = isEditingContent
    ? resolveScriptMode(editedScriptMode, scriptMode)
    : scriptMode

  const getModeConstraintHintText = useCallback((
    mode: ScriptMode
  ): string => {
    if (mode === 'single') return '单人口播约束已开启'
    if (mode === 'duo_podcast') return '双人播客约束已开启'
    if (mode === 'dialogue_script') return '剧情化约束已开启'
    return ''
  }, [])
  const viewConstraintHintText = getModeConstraintHintText(scriptMode)
  const editConstraintHintText = getModeConstraintHintText(displayMode)
  const contentConstraintHintText = isEditingContent ? editConstraintHintText : viewConstraintHintText

  const hasStoryboardShots = (stageData?.storyboard?.shots?.length || 0) > 0
  const areShotsLocked = !!stageData?.content?.shots_locked || hasStoryboardShots
  const canImportDialogue = !!onImportDialogue && isMultiScriptMode(displayMode) && !areShotsLocked
  const dialogueImportSample = `{
  "title": "标题",
  "roles": [
    { "name": "x", "description": "x设定" },
    { "name": "y", "description": "y设定" },
    { "name": "z", "description": "z设定" }
  ],
  "dialogue_lines": [
    { "speaker_name": "x", "text": "x台词1" },
    { "speaker_name": "y", "text": "y台词1" },
    { "speaker_name": "x", "text": "x台词2" },
    { "speaker_name": "y", "text": "y台词2" },
    ...
  ]
}`

  const isContentStageRunning = runningStage === 'content'
  const isOtherStageRunningForContent = !!runningStage && runningStage !== 'content'
  const editedSpeakerOptions = buildSpeakerOptionsForMode(displayMode, editedRoles, references)
  const editedSpeakerIdSet = new Set(editedSpeakerOptions.map((item) => item.id))
  const hasEditableSpeakers = editedSpeakerOptions.length > 0
  const editingTextForCount = flattenDialogueLines(editedDialogueLines)

  const buildDialogueLineId = useCallback(() => {
    dialogueLineIdCounterRef.current += 1
    return `line_${Date.now()}_${dialogueLineIdCounterRef.current}`
  }, [])

  const getDefaultSpeaker = useCallback((speakerOptions: Array<{ id: string; name: string }>) => {
    const fallbackSpeakerId = String(speakerOptions[0]?.id || '').trim() || NARRATOR_ROLE_ID
    return {
      id: fallbackSpeakerId,
      name: String(speakerOptions[0]?.name || '').trim() || getRoleName(fallbackSpeakerId, editedRoles),
    }
  }, [editedRoles])

  const buildEmptyDialogueLine = useCallback((params?: {
    speakerId?: string
    speakerName?: string
    order?: number
  }): DialogueLine => {
    const refs = stageData?.reference?.references || stageData?.storyboard?.references || []
    const speakerOptions = buildSpeakerOptionsForMode(editedScriptMode, editedRoles, refs)
    const fallbackSpeaker = getDefaultSpeaker(speakerOptions)
    const speakerId = String(params?.speakerId || '').trim() || fallbackSpeaker.id
    return {
      id: buildDialogueLineId(),
      speaker_id: speakerId,
      speaker_name: String(params?.speakerName || '').trim() || getRoleName(speakerId, editedRoles) || fallbackSpeaker.name,
      text: '',
      order: typeof params?.order === 'number' ? params.order : editedDialogueLines.length,
    }
  }, [
    buildDialogueLineId,
    editedDialogueLines.length,
    editedRoles,
    editedScriptMode,
    getDefaultSpeaker,
    stageData?.reference?.references,
    stageData?.storyboard?.references,
  ])

  const buildEditableContentSnapshot = useCallback(() => {
    const refs = stageData?.reference?.references || stageData?.storyboard?.references || []
    const mode = resolveScriptMode(
      configuredScriptMode || stageData?.content?.script_mode,
      resolvedConfiguredScriptMode
    )
    const normalizedRoles = mode === 'dialogue_script'
      ? (() => {
          const contentDerivedRoles = normalizeRolesForMode(
            'dialogue_script',
            stageData?.content?.roles,
            maxDialogueRoleCount
          )
          if (contentDerivedRoles.length > 0) return contentDerivedRoles
          return normalizeRolesForMode(
            'dialogue_script',
            buildRolesFromReferences(refs),
            maxDialogueRoleCount
          )
        })()
      : normalizeRolesForMode(
        mode,
        stageData?.content?.roles,
        maxDialogueRoleCount
      )
    const normalizedLines = normalizeDialogueLinesForMode(
      mode,
      stageData?.content?.dialogue_lines,
      normalizedRoles,
      stageData?.content?.content || ''
    )
    const nextLines = areShotsLocked
      ? mergeConsecutiveDialogueLines(normalizedLines)
      : normalizedLines
    return {
      title: stageData?.content?.title || '',
      mode,
      roles: normalizedRoles,
      lines: nextLines,
      content: mode === 'single'
        ? String(stageData?.content?.content || '')
        : flattenDialogueLines(nextLines),
    }
  }, [
    areShotsLocked,
    configuredScriptMode,
    maxDialogueRoleCount,
    resolvedConfiguredScriptMode,
    stageData?.content?.content,
    stageData?.content?.dialogue_lines,
    stageData?.content?.roles,
    stageData?.content?.script_mode,
    stageData?.content?.title,
    stageData?.reference?.references,
    stageData?.storyboard?.references,
  ])

  const editableContentSnapshot = useMemo(
    () => buildEditableContentSnapshot(),
    [buildEditableContentSnapshot]
  )

  const buildContentSignature = useCallback((input: {
    title: string
    mode: ScriptMode
    content: string
    roles: ScriptRole[]
    lines: DialogueLine[]
  }) => JSON.stringify({
    title: String(input.title || ''),
    mode: resolveScriptMode(input.mode, resolvedConfiguredScriptMode),
    content: String(input.content || ''),
    roles: (input.roles || []).map((role) => ({
      id: String(role.id || ''),
      name: String(role.name || ''),
      description: String(role.description || ''),
    })),
    lines: (input.lines || []).map((line, index) => ({
      id: String(line.id || ''),
      speaker_id: String(line.speaker_id || ''),
      speaker_name: String(line.speaker_name || ''),
      text: String(line.text || ''),
      order: typeof line.order === 'number' ? line.order : index,
    })),
  }), [resolvedConfiguredScriptMode])

  const getPersistableDialogueLines = useCallback((lines: DialogueLine[]) => (
    lines
      .map((line, index) => ({
        ...line,
        id: String(line.id || '').trim() || `line_${index + 1}`,
        speaker_id: String(line.speaker_id || '').trim(),
        speaker_name: String(line.speaker_name || '').trim(),
        text: String(line.text || '').trim(),
      }))
      .filter((line) => line.text)
      .map((line, index) => ({
        ...line,
        order: index,
      }))
  ), [])

  const buildDialogueLineComparableKey = useCallback((lines: DialogueLine[]) => JSON.stringify(
    getPersistableDialogueLines(lines).map((line) => ({
      id: String(line.id || ''),
      speaker_id: String(line.speaker_id || ''),
      speaker_name: String(line.speaker_name || ''),
      text: String(line.text || ''),
      order: typeof line.order === 'number' ? line.order : 0,
    }))
  ), [getPersistableDialogueLines])

  const savedContentSignature = useMemo(() => buildContentSignature({
    title: editableContentSnapshot.title,
    mode: editableContentSnapshot.mode,
    content: editableContentSnapshot.content,
    roles: editableContentSnapshot.roles,
    lines: getPersistableDialogueLines(editableContentSnapshot.lines),
  }), [buildContentSignature, editableContentSnapshot, getPersistableDialogueLines])

  const currentContentSignature = useMemo(() => buildContentSignature({
    title: editedTitle,
    mode: editedScriptMode,
    content: flattenDialogueLines(getPersistableDialogueLines(editedDialogueLines)),
    roles: editedRoles,
    lines: getPersistableDialogueLines(editedDialogueLines),
  }), [buildContentSignature, editedDialogueLines, editedRoles, editedScriptMode, editedTitle, getPersistableDialogueLines])

  // ---- Handlers ----

  const handleStartEditContent = useCallback(() => {
    if (areShotsLocked) {
      toast.info('文案已与分镜绑定，请到分镜页编辑，或先清空分镜内容后再编辑文案')
      return
    }
    const refs = stageData?.reference?.references || stageData?.storyboard?.references || []
    const mode = resolveScriptMode(
      configuredScriptMode || stageData?.content?.script_mode,
      resolvedConfiguredScriptMode
    )
    const normalizedRoles = mode === 'dialogue_script'
      ? (() => {
          const contentDerivedRoles = normalizeRolesForMode(
            'dialogue_script',
            stageData?.content?.roles,
            maxDialogueRoleCount
          )
          if (contentDerivedRoles.length > 0) return contentDerivedRoles
          return normalizeRolesForMode(
            'dialogue_script',
            buildRolesFromReferences(refs),
            maxDialogueRoleCount
          )
        })()
      : normalizeRolesForMode(
        mode,
        stageData?.content?.roles,
        maxDialogueRoleCount
      )
    const normalizedLines = normalizeDialogueLinesForMode(
      mode,
      stageData?.content?.dialogue_lines,
      normalizedRoles,
      stageData?.content?.content || ''
    )

    setEditedTitle(stageData?.content?.title || '')
    setEditedContent(flattenDialogueLines(normalizedLines))
    setEditedScriptMode(mode)
    setEditedRoles(normalizedRoles)
    setEditedDialogueLines(normalizedLines)
    setIsEditingContent(true)
  }, [
    configuredScriptMode,
    maxDialogueRoleCount,
    resolvedConfiguredScriptMode,
    stageData?.reference?.references,
    stageData?.storyboard?.references,
    stageData?.content?.content,
    stageData?.content?.dialogue_lines,
    stageData?.content?.roles,
    stageData?.content?.script_mode,
    stageData?.content?.title,
    areShotsLocked,
  ])

  const handleCancelEditContent = () => {
    setIsEditingContent(false)
    setEditedTitle('')
    setEditedContent('')
    setEditedScriptMode(
      resolveScriptMode(configuredScriptMode || stageData?.content?.script_mode, resolvedConfiguredScriptMode)
    )
    setEditedRoles([])
    setEditedDialogueLines([])
  }

  useEffect(() => {
    setEditedTitle(editableContentSnapshot.title)
    setEditedContent(editableContentSnapshot.content)
    setEditedScriptMode(editableContentSnapshot.mode)
    setEditedRoles(editableContentSnapshot.roles)
    setEditedDialogueLines((prev) => {
      const nextLines = editableContentSnapshot.lines
      const prevComparable = buildDialogueLineComparableKey(prev)
      const nextComparable = buildDialogueLineComparableKey(nextLines)
      if (prevComparable === nextComparable && prev.length >= nextLines.length) {
        return prev.map((line, index) => ({ ...line, order: index }))
      }
      return nextLines
    })
  }, [buildDialogueLineComparableKey, editableContentSnapshot])

  // Sync roles when editing in dialogue_script mode and references change
  useEffect(() => {
    if (!isEditingContent || editedScriptMode !== 'dialogue_script') return
    const refs = stageData?.reference?.references || stageData?.storyboard?.references || []
    const nextRoles = (() => {
      const contentDerivedRoles = normalizeRolesForMode(
        'dialogue_script',
        stageData?.content?.roles,
        maxDialogueRoleCount
      )
      if (contentDerivedRoles.length > 0) return contentDerivedRoles
      return normalizeRolesForMode(
        'dialogue_script',
        buildRolesFromReferences(refs),
        maxDialogueRoleCount
      )
    })()
    setEditedRoles(nextRoles)
    setEditedDialogueLines((prev) =>
      normalizeDialogueLinesForMode('dialogue_script', prev, nextRoles, editedContent)
    )
  }, [
    editedContent,
    editedScriptMode,
    isEditingContent,
    maxDialogueRoleCount,
    stageData?.content?.roles,
    stageData?.reference?.references,
    stageData?.storyboard?.references,
  ])

  const ensureAtLeastOneDialogueLine = useCallback(() => {
    const refs = stageData?.reference?.references || stageData?.storyboard?.references || []
    const speakerOptions = buildSpeakerOptionsForMode(editedScriptMode, editedRoles, refs)
    if (speakerOptions.length === 0) {
      return null
    }
    const emptyLine = buildEmptyDialogueLine({
      speakerId: speakerOptions[0]?.id,
      speakerName: speakerOptions[0]?.name,
      order: 0,
    })
    setEditedDialogueLines((prev) => {
      if (prev.length > 0) return prev
      return [emptyLine]
    })
    return emptyLine.id || null
  }, [
    buildEmptyDialogueLine,
    editedRoles,
    editedScriptMode,
    stageData?.reference?.references,
    stageData?.storyboard?.references,
  ])

  const handleAddDialogueLine = useCallback(() => {
    const ensuredId = ensureAtLeastOneDialogueLine()
    if (ensuredId) return ensuredId
    const refs = stageData?.reference?.references || stageData?.storyboard?.references || []
    const speakerOptions = buildSpeakerOptionsForMode(editedScriptMode, editedRoles, refs)
    if (speakerOptions.length === 0) {
      toast.info('请先在参考区创建可用角色参考')
      return null
    }
    const emptyLine = buildEmptyDialogueLine({
      speakerId: speakerOptions[0]?.id,
      speakerName: speakerOptions[0]?.name,
    })
    setEditedDialogueLines((prev) => (
      [...prev, { ...emptyLine, order: prev.length }]
    ))
    return emptyLine.id || null
  }, [
    buildEmptyDialogueLine,
    editedRoles,
    editedScriptMode,
    ensureAtLeastOneDialogueLine,
    stageData?.reference?.references,
    stageData?.storyboard?.references,
  ])

  const insertDialogueLineAfter = useCallback((lineId: string) => {
    const currentLine = editedDialogueLines.find((line) => String(line.id || '') === lineId)
    const emptyLine = buildEmptyDialogueLine({
      speakerId: String(currentLine?.speaker_id || '').trim(),
      speakerName: String(currentLine?.speaker_name || '').trim(),
    })
    setEditedDialogueLines((prev) => {
      const targetIndex = prev.findIndex((line) => String(line.id || '') === lineId)
      const insertIndex = targetIndex >= 0 ? targetIndex + 1 : prev.length
      const next = [...prev]
      next.splice(insertIndex, 0, { ...emptyLine, order: insertIndex })
      return next.map((line, index) => ({ ...line, order: index }))
    })
    return emptyLine.id || null
  }, [buildEmptyDialogueLine, editedDialogueLines])

  const updateDialogueLineText = useCallback((lineId: string, text: string) => {
    setEditedDialogueLines((prev) => prev.map((line) => {
      if (String(line.id || '') !== lineId) return line
      return {
        ...line,
        text,
      }
    }))
  }, [])

  const updateDialogueLineSpeaker = useCallback((lineId: string, speakerId: string) => {
    setEditedDialogueLines((prev) => prev.map((line) => {
      if (String(line.id || '') !== lineId) return line
      const nextSpeakerId = String(speakerId || '').trim()
      return {
        ...line,
        speaker_id: nextSpeakerId,
        speaker_name: getRoleName(nextSpeakerId, editedRoles),
      }
    }))
  }, [editedRoles])

  const handleUpdateDialogueLine = useCallback((lineId: string, updates: Partial<DialogueLine>) => {
    if (updates.text !== undefined) {
      updateDialogueLineText(lineId, String(updates.text || ''))
    }
    if (updates.speaker_id !== undefined) {
      updateDialogueLineSpeaker(lineId, String(updates.speaker_id || ''))
    }
  }, [updateDialogueLineSpeaker, updateDialogueLineText])

  const removeDialogueLineWithFocus = useCallback((
    lineId: string,
    direction: 'auto' | 'previous' = 'auto'
  ) => {
    const currentIndex = editedDialogueLines.findIndex((line) => String(line.id || '') === lineId)
    if (currentIndex < 0) return null
    const nextLine = editedDialogueLines[currentIndex + 1]
    const prevLine = editedDialogueLines[currentIndex - 1]
    const remainingLines = editedDialogueLines.filter((line) => String(line.id || '') !== lineId)

    if (remainingLines.length === 0) {
      const fallbackLine = buildEmptyDialogueLine({ order: 0 })
      setEditedDialogueLines([{ ...fallbackLine, order: 0 }])
      return {
        lineId: String(fallbackLine.id || ''),
        caret: 'start' as const,
      }
    }

    setEditedDialogueLines(remainingLines.map((line, index) => ({ ...line, order: index })))

    if (direction === 'previous' || !nextLine) {
      return prevLine
        ? {
            lineId: String(prevLine.id || ''),
            caret: 'end' as const,
          }
        : {
            lineId: String(remainingLines[0]?.id || ''),
            caret: 'start' as const,
          }
    }

    return {
      lineId: String(nextLine.id || ''),
      caret: 'start' as const,
    }
  }, [buildEmptyDialogueLine, editedDialogueLines])

  const handleRemoveDialogueLine = useCallback((lineId: string) => {
    return removeDialogueLineWithFocus(lineId, 'auto')
  }, [removeDialogueLineWithFocus])

  const handleOpenDialogueImport = useCallback(() => {
    if (!onImportDialogue) return
    dialogueImportInputRef.current?.click()
  }, [onImportDialogue])

  const handleDialogueImportFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !onImportDialogue) return
    const hasExistingContent =
      !!String(stageData?.content?.title || '').trim()
      || !!String(stageData?.content?.content || '').trim()
      || (Array.isArray(stageData?.content?.roles) && stageData.content.roles.length > 0)
      || (Array.isArray(stageData?.content?.dialogue_lines) && stageData.content.dialogue_lines.length > 0)
    if (hasExistingContent) {
      const confirmed = await confirmDialog({
        title: '导入覆盖确认',
        description: '导入会清空当前文案与角色，并用上传内容覆盖。是否继续？',
        confirmText: '继续导入',
        cancelText: '取消',
        variant: 'destructive',
      })
      if (!confirmed) {
        if (dialogueImportInputRef.current) dialogueImportInputRef.current.value = ''
        return
      }
    }
    const mode = resolveScriptMode(
      isEditingContent ? editedScriptMode : (configuredScriptMode || stageData?.content?.script_mode),
      resolvedConfiguredScriptMode
    )

    setIsImportingDialogue(true)
    try {
      await onImportDialogue(file, mode)
      setIsEditingContent(false)
    } catch (error) {
      console.error('Failed to import dialogue:', error)
    } finally {
      setIsImportingDialogue(false)
      if (dialogueImportInputRef.current) dialogueImportInputRef.current.value = ''
    }
  }

  useEffect(() => {
    if (areShotsLocked) return
    if (!hasEditableSpeakers) return
    if (editedDialogueLines.length > 0) return
    void ensureAtLeastOneDialogueLine()
  }, [
    areShotsLocked,
    editedDialogueLines.length,
    ensureAtLeastOneDialogueLine,
    hasEditableSpeakers,
  ])

  const handleSaveContent = useCallback(async () => {
    if (!onSaveContent) return
    setIsSavingContent(true)
    setIsAutoSavingContent(true)
    try {
      const mode = resolveScriptMode(editedScriptMode, resolvedConfiguredScriptMode)
      const normalizedRoles = normalizeRolesForMode(mode, editedRoles, maxDialogueRoleCount)
      const refs = stageData?.reference?.references || stageData?.storyboard?.references || []
      const speakerOptions = buildSpeakerOptionsForMode(mode, normalizedRoles, refs)
      const allowedSpeakerIds = new Set(speakerOptions.map((item) => item.id))
      const fallbackSpeakerId = String(speakerOptions[0]?.id || '').trim()

      if (mode !== 'single' && speakerOptions.length === 0) {
        toast.error('当前参考区没有可用角色，请先创建角色参考')
        return
      }
      const normalizedLines = normalizeDialogueLinesForMode(
        mode,
        editedDialogueLines,
        normalizedRoles,
        flattenDialogueLines(editedDialogueLines) || editedContent
      )
      const payloadLines = normalizedLines.map((line, index) => {
        const requestedSpeakerId = String(line.speaker_id || '').trim()
        const speakerId = allowedSpeakerIds.has(requestedSpeakerId)
          ? requestedSpeakerId
          : fallbackSpeakerId
        return {
          id: String(line.id || '').trim() || `line_${index + 1}`,
          speaker_id: speakerId,
          speaker_name: getRoleName(speakerId, normalizedRoles),
          text: String(line.text || '').trim(),
          order: index,
        }
      }).filter((line) => line.text)
      await onSaveContent({
        title: editedTitle,
        content: flattenDialogueLines(payloadLines),
        script_mode: mode,
        roles: normalizedRoles,
        dialogue_lines: payloadLines,
      })
      lastSubmittedContentSignatureRef.current = buildContentSignature({
        title: editedTitle,
        mode,
        content: flattenDialogueLines(payloadLines),
        roles: normalizedRoles,
        lines: payloadLines,
      })
    } catch (error) {
      console.error('Failed to save content:', error)
    } finally {
      setIsSavingContent(false)
      setIsAutoSavingContent(false)
    }
  }, [
    buildContentSignature,
    editedContent,
    editedDialogueLines,
    editedRoles,
    editedScriptMode,
    editedTitle,
    maxDialogueRoleCount,
    onSaveContent,
    resolvedConfiguredScriptMode,
    stageData?.reference?.references,
    stageData?.storyboard?.references,
  ])

  const handleDeleteContent = async () => {
    if (!onDeleteContent) return
    setIsDeletingContent(true)
    try {
      await onDeleteContent()
      setIsEditingContent(false)
    } catch (error) {
      console.error('Failed to delete content:', error)
    } finally {
      setIsDeletingContent(false)
    }
  }

  const handleUnlockContentByClearingShots = async () => {
    if (!onUnlockContentByClearingShots) return
    try {
      await onUnlockContentByClearingShots()
      setIsEditingContent(false)
    } catch (error) {
      console.error('Failed to unlock content by clearing shots:', error)
    }
  }

  useEffect(() => {
    if (!onSaveContent || areShotsLocked) return
    if (!hasEditableSpeakers && editedScriptMode !== 'single') return
    if (currentContentSignature === savedContentSignature) {
      lastSubmittedContentSignatureRef.current = ''
      return
    }
    if (currentContentSignature === lastSubmittedContentSignatureRef.current) return

    if (contentAutoSaveTimerRef.current !== null) {
      window.clearTimeout(contentAutoSaveTimerRef.current)
    }

    contentAutoSaveTimerRef.current = window.setTimeout(() => {
      void handleSaveContent()
    }, 800)

    return () => {
      if (contentAutoSaveTimerRef.current !== null) {
        window.clearTimeout(contentAutoSaveTimerRef.current)
        contentAutoSaveTimerRef.current = null
      }
    }
  }, [
    areShotsLocked,
    currentContentSignature,
    editedScriptMode,
    handleSaveContent,
    hasEditableSpeakers,
    onSaveContent,
    savedContentSignature,
  ])

  const flushAutoSaveContent = useCallback(async () => {
    if (!onSaveContent || areShotsLocked) return
    if (currentContentSignature === savedContentSignature) return
    if (currentContentSignature === lastSubmittedContentSignatureRef.current) return
    if (contentAutoSaveTimerRef.current !== null) {
      window.clearTimeout(contentAutoSaveTimerRef.current)
      contentAutoSaveTimerRef.current = null
    }
    await handleSaveContent()
  }, [
    areShotsLocked,
    currentContentSignature,
    handleSaveContent,
    onSaveContent,
    savedContentSignature,
  ])

  return {
    // Refs
    dialogueImportInputRef,
    // State
    isEditingContent,
    editedTitle,
    setEditedTitle,
    editedContent,
    setEditedContent,
    editedDialogueLines,
    isSavingContent,
    isAutoSavingContent,
    isDeletingContent,
    isImportingDialogue,
    // Derived
    displayMode,
    contentConstraintHintText,
    canImportDialogue,
    dialogueImportSample,
    hasContent,
    hasScriptBody,
    displayCharCount,
    isContentStageRunning,
    isOtherStageRunningForContent,
    isShotsLocked: areShotsLocked,
    editedSpeakerOptions,
    editedSpeakerIdSet,
    hasEditableSpeakers,
    editingTextForCount,
    viewRoles,
    viewDialogueLines,
    // Handlers
    handleStartEditContent,
    handleCancelEditContent,
    ensureAtLeastOneDialogueLine,
    handleAddDialogueLine,
    insertDialogueLineAfter,
    updateDialogueLineText,
    updateDialogueLineSpeaker,
    removeDialogueLineWithFocus,
    handleUpdateDialogueLine,
    handleRemoveDialogueLine,
    handleOpenDialogueImport,
    handleDialogueImportFileChange,
    handleSaveContent,
    flushAutoSaveContent,
    handleDeleteContent,
    handleUnlockContentByClearingShots,
    // Pass-through callbacks for conditional rendering
    onSaveContent,
    onDeleteContent,
    onUnlockContentByClearingShots,
    // Helpers re-exported for the component
    countScriptChars,
    getRoleName,
    stageTitle: stageData?.content?.title || '',
  }
}
