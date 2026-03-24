'use client'

import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { toast } from 'sonner'

import { useConfirmDialog } from '@/components/common/confirm-dialog-provider'
import { useVoiceLibraryQuery } from '@/hooks/use-settings-queries'
import {
  resolveNarratorCustomNameByMode,
  resolveNarratorPresetNameByMode,
  resolveNarratorPresetVoiceByMode,
  isNarratorPresetSettingTextByMode,
  resolveNarratorPresetSettingByMode,
} from '@/lib/narrator-style'
import {
  EDGE_TTS_DEFAULT_VOICE,
  EDGE_TTS_DUO_ROLE_1_VOICE,
  EDGE_TTS_DUO_ROLE_2_VOICE,
} from '@/lib/reference-voice'
import type { ReferenceVoiceConfig } from '@/hooks/use-reference-voice-meta'
import { useReferenceVoiceMeta } from '@/hooks/use-reference-voice-meta'
import type { Reference } from '@/lib/content-panel-helpers'
import type { ScriptTabContentProps } from '@/components/project/script-tab-content.types'
import {
  DUO_ROLE_1_NAME,
  DUO_ROLE_2_NAME,
  SINGLE_ROLE_NAME,
  resolveScriptMode,
  isStageRunningWithFallback,
  resolveCurrentItemGenerationState,
  resolveRuntimeDisplay,
} from '@/lib/content-panel-helpers'

type ScriptMode = 'custom' | 'single' | 'duo_podcast' | 'dialogue_script'

export interface UseScriptReferencePanelParams {
  stageData?: ScriptTabContentProps['stageData']
  generatingShots?: ScriptTabContentProps['generatingShots']
  runningStage?: ScriptTabContentProps['runningStage']
  runningAction?: ScriptTabContentProps['runningAction']
  runningReferenceId?: ScriptTabContentProps['runningReferenceId']
  progress?: ScriptTabContentProps['progress']
  progressMessage?: ScriptTabContentProps['progressMessage']
  referenceStageStatus?: ScriptTabContentProps['referenceStageStatus']
  configuredScriptMode?: ScriptTabContentProps['configuredScriptMode']
  narratorStyle?: ScriptTabContentProps['narratorStyle']
  onSaveReference?: ScriptTabContentProps['onSaveReference']
  onDeleteReference?: ScriptTabContentProps['onDeleteReference']
  onRegenerateReferenceImage?: ScriptTabContentProps['onRegenerateReferenceImage']
  onUploadReferenceImage?: ScriptTabContentProps['onUploadReferenceImage']
  onCreateReference?: ScriptTabContentProps['onCreateReference']
  onGenerateDescriptionFromImage?: ScriptTabContentProps['onGenerateDescriptionFromImage']
  onDeleteReferenceImage?: ScriptTabContentProps['onDeleteReferenceImage']
  libraryReferences: NonNullable<ScriptTabContentProps['libraryReferences']>
  onImportReferencesFromLibrary?: ScriptTabContentProps['onImportReferencesFromLibrary']
  activeScriptModeForConstraint: ScriptMode
}

export function useScriptReferencePanel({
  stageData,
  generatingShots,
  runningStage,
  runningAction,
  runningReferenceId,
  progress,
  progressMessage,
  referenceStageStatus,
  configuredScriptMode,
  narratorStyle,
  onSaveReference,
  onDeleteReference,
  onRegenerateReferenceImage,
  onUploadReferenceImage,
  onCreateReference,
  onGenerateDescriptionFromImage,
  onDeleteReferenceImage,
  libraryReferences,
  onImportReferencesFromLibrary,
  activeScriptModeForConstraint,
}: UseScriptReferencePanelParams) {
  const confirmDialog = useConfirmDialog()
  // ── State ──────────────────────────────────────────────────────────────
  const [currentReferenceIndex, setCurrentReferenceIndex] = useState(0)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const newReferenceFileInputRef = useRef<HTMLInputElement>(null)

  const [isEditingReference, setIsEditingReference] = useState(false)
  const [editedReferenceName, setEditedReferenceName] = useState('')
  const [editedReferenceSetting, setEditedReferenceSetting] = useState('')
  const [editedReferenceAppearanceDesc, setEditedReferenceAppearanceDesc] = useState('')
  const [editedReferenceCanSpeak, setEditedReferenceCanSpeak] = useState(true)
  const [editedReferenceVoice, setEditedReferenceVoice] = useState<Partial<ReferenceVoiceConfig>>({
    voice_audio_provider: 'edge_tts',
  })
  const [isSavingReference, setIsSavingReference] = useState(false)
  const [isAutoSavingReference, setIsAutoSavingReference] = useState(false)
  const referenceAutoSaveTimerRef = useRef<number | null>(null)
  const lastSubmittedReferenceSignatureRef = useRef<string>('')

  const [showDeleteDialog, setShowDeleteDialog] = useState(false)
  const [referenceToDelete, setReferenceToDelete] = useState<Reference | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)

  const [regeneratingReferenceId, setRegeneratingReferenceId] = useState<string | number | null>(null)
  const [isUploading, setIsUploading] = useState(false)

  const [isCreatingReference, setIsCreatingReference] = useState(false)
  const [newReferenceName, setNewReferenceName] = useState('新参考')
  const [newReferenceSetting, setNewReferenceSetting] = useState('')
  const [newReferenceAppearanceDesc, setNewReferenceAppearanceDesc] = useState('')
  const [newReferenceCanSpeak, setNewReferenceCanSpeak] = useState(false)
  const [newReferenceVoice, setNewReferenceVoice] = useState<Partial<ReferenceVoiceConfig>>({
    voice_audio_provider: 'edge_tts',
  })
  const [showNewReferenceCard, setShowNewReferenceCard] = useState(false)
  const [showImportDialog, setShowImportDialog] = useState(false)
  const [importStartReferenceIndex, setImportStartReferenceIndex] = useState(0)
  const [importSelectionOrder, setImportSelectionOrder] = useState<number[]>([])
  const [importSettingChecked, setImportSettingChecked] = useState(true)
  const [importAppearanceChecked, setImportAppearanceChecked] = useState(true)
  const [importImageChecked, setImportImageChecked] = useState(true)
  const [importVoiceChecked, setImportVoiceChecked] = useState(true)
  const [isImportingReferences, setIsImportingReferences] = useState(false)
  const [importResult, setImportResult] = useState<Awaited<ReturnType<NonNullable<ScriptTabContentProps['onImportReferencesFromLibrary']>>> | null>(null)

  const [generatingDescriptionReferenceIds, setGeneratingDescriptionReferenceIds] = useState<Set<string>>(new Set())
  const [isDeletingReferenceImage, setIsDeletingReferenceImage] = useState(false)

  // ── Voice meta & derived ───────────────────────────────────────────────
  const { data: voiceLibraryData } = useVoiceLibraryQuery()
  const voiceLibraryNameByAudioPath = useMemo(() => {
    const mapping = new Map<string, string>()
    for (const item of voiceLibraryData?.items || []) {
      const name = String(item.name || '').trim()
      const keys = [
        String(item.audio_url || '').trim(),
        String(item.audio_file_path || '').trim(),
      ].filter(Boolean)
      for (const key of keys) {
        mapping.set(key, name || key)
      }
    }
    return mapping
  }, [voiceLibraryData?.items])

  const voiceMeta = useReferenceVoiceMeta()
  const normalizedNewReferenceVoice = useMemo(
    () => voiceMeta.normalizeConfig(newReferenceVoice),
    [newReferenceVoice, voiceMeta]
  )
  const normalizedEditedReferenceVoice = useMemo(
    () => voiceMeta.normalizeConfig(editedReferenceVoice),
    [editedReferenceVoice, voiceMeta]
  )

  // ── Helper callbacks ───────────────────────────────────────────────────
  const buildDefaultNewReferenceVoice = useCallback((params?: {
    mode?: ScriptMode
    narratorIndex?: number
    isLockedNarrator?: boolean
  }): Partial<ReferenceVoiceConfig> => {
    const mode = params?.mode || 'single'
    const narratorIndex = params?.narratorIndex ?? 0
    const isLockedNarrator = params?.isLockedNarrator === true
    if (isLockedNarrator) {
      const presetVoice = resolveNarratorPresetVoiceByMode(mode, narratorStyle, narratorIndex)
      if (presetVoice) {
        return voiceMeta.normalizeConfig(presetVoice)
      }
    }
    if (isLockedNarrator && mode === 'single') {
      return voiceMeta.normalizeConfig({
        voice_audio_provider: 'edge_tts',
        voice_name: EDGE_TTS_DEFAULT_VOICE,
      })
    }
    if (isLockedNarrator && mode === 'duo_podcast') {
      return voiceMeta.normalizeConfig({
        voice_audio_provider: 'edge_tts',
        voice_name: narratorIndex === 0 ? EDGE_TTS_DUO_ROLE_1_VOICE : EDGE_TTS_DUO_ROLE_2_VOICE,
      })
    }
    return { voice_audio_provider: voiceMeta.defaultAudioProvider }
  }, [narratorStyle, voiceMeta])

  const getLockedNarratorCountByMode = useCallback((mode: ScriptMode): number => {
    if (mode === 'single') return 1
    if (mode === 'duo_podcast') return 2
    return 0
  }, [])

  const getNarratorDefaultNameByMode = useCallback((
    mode: ScriptMode,
    narratorIndex: number
  ): string => {
    const presetName = resolveNarratorPresetNameByMode(mode, narratorStyle, narratorIndex)
    if (presetName) return presetName
    const customName = resolveNarratorCustomNameByMode(mode, narratorIndex)
    if (customName) return customName
    if (mode === 'single') return SINGLE_ROLE_NAME
    if (mode === 'duo_podcast') return narratorIndex === 0 ? DUO_ROLE_1_NAME : DUO_ROLE_2_NAME
    return '新参考'
  }, [narratorStyle])

  const resolvedConfiguredScriptMode = resolveScriptMode(configuredScriptMode)
  const references = useMemo(
    () => stageData?.reference?.references || stageData?.storyboard?.references || [],
    [stageData?.reference?.references, stageData?.storyboard?.references]
  )
  const scriptMode = resolveScriptMode(
    configuredScriptMode || stageData?.content?.script_mode,
    resolvedConfiguredScriptMode
  )
  const hasReferences = references.length > 0
  const safeCurrentReferenceIndex = references.length > 0
    ? Math.min(currentReferenceIndex, references.length - 1)
    : 0
  const currentReference = references[safeCurrentReferenceIndex]
  const hasAnyGeneratingShot = !!generatingShots && Object.keys(generatingShots).length > 0
  const isReferenceImageActionRunningGlobal = isStageRunningWithFallback({
    runningStage,
    runningAction,
    targetStage: 'reference',
    requiredAction: 'generate_images',
    fallbackStageStatus: referenceStageStatus,
    hasGeneratingShot: hasAnyGeneratingShot,
    fallbackRequiresGeneratingShot: true,
  })

  // ── Effects ────────────────────────────────────────────────────────────
  useEffect(() => {
    setIsEditingReference(false)
    setShowNewReferenceCard(false)
  }, [currentReferenceIndex])

  useEffect(() => {
    const mode = resolveScriptMode(
      configuredScriptMode || stageData?.content?.script_mode,
      resolvedConfiguredScriptMode
    )
    const references = stageData?.reference?.references || stageData?.storyboard?.references || []
    const lockedNarratorCount = getLockedNarratorCountByMode(mode)
    if (lockedNarratorCount <= 0 || references.length >= lockedNarratorCount) return
    const pendingNarratorIndex = references.length
    const presetSetting = resolveNarratorPresetSettingByMode(mode, narratorStyle, pendingNarratorIndex)
    setNewReferenceName(getNarratorDefaultNameByMode(mode, pendingNarratorIndex))
    setNewReferenceCanSpeak(true)
    setNewReferenceVoice(buildDefaultNewReferenceVoice({
      mode,
      narratorIndex: pendingNarratorIndex,
      isLockedNarrator: true,
    }))
    setNewReferenceSetting(presetSetting || '')
  }, [
    buildDefaultNewReferenceVoice,
    configuredScriptMode,
    getLockedNarratorCountByMode,
    getNarratorDefaultNameByMode,
    narratorStyle,
    resolvedConfiguredScriptMode,
    stageData?.content?.script_mode,
    stageData?.reference?.references,
    stageData?.storyboard?.references,
  ])

  useEffect(() => {
    const references = stageData?.reference?.references || stageData?.storyboard?.references || []
    setCurrentReferenceIndex((prev) => {
      if (references.length <= 0) return 0
      return Math.min(prev, references.length - 1)
    })
  }, [
    stageData?.reference?.references,
    stageData?.storyboard?.references,
  ])

  const buildReferenceSignature = useCallback((input: {
    referenceId: string | number | null | undefined
    name: string
    setting: string
    appearanceDescription: string
    canSpeak: boolean
    voice: Partial<ReferenceVoiceConfig>
  }) => JSON.stringify({
    referenceId: input.referenceId == null ? '' : String(input.referenceId),
    name: String(input.name || ''),
    setting: String(input.setting || ''),
    appearanceDescription: String(input.appearanceDescription || ''),
    canSpeak: !!input.canSpeak,
    voice: voiceMeta.toPayload(!!input.canSpeak, input.voice),
  }), [voiceMeta])

  useEffect(() => {
    if (!currentReference) return
    const referenceIndex = references.findIndex((item) => String(item.id) === String(currentReference.id))
    const isLockedNarratorReference = referenceIndex >= 0
      && referenceIndex < getLockedNarratorCountByMode(scriptMode)
    const narratorPresetSetting = isLockedNarratorReference
      ? resolveNarratorPresetSettingByMode(scriptMode, narratorStyle, referenceIndex)
      : ''
    const lockNarratorSetting = isLockedNarratorReference && !!narratorPresetSetting
    const existingSetting = String(currentReference.setting || '').trim()
    const resolvedSetting = lockNarratorSetting
      ? narratorPresetSetting
      : (
        isLockedNarratorReference
        && !narratorPresetSetting
        && isNarratorPresetSettingTextByMode(scriptMode, existingSetting)
          ? ''
          : existingSetting
      )
    const canSpeak = isLockedNarratorReference ? true : (currentReference.can_speak !== false)
    setEditedReferenceName(currentReference.name)
    setEditedReferenceSetting(resolvedSetting)
    setEditedReferenceAppearanceDesc(String(currentReference.appearance_description || '').trim())
    setEditedReferenceCanSpeak(canSpeak)
    setEditedReferenceVoice(voiceMeta.normalizeConfig({
      voice_audio_provider: currentReference.voice_audio_provider,
      voice_name: currentReference.voice_name,
      voice_speed: currentReference.voice_speed,
      voice_wan2gp_preset: currentReference.voice_wan2gp_preset,
      voice_wan2gp_alt_prompt: currentReference.voice_wan2gp_alt_prompt,
      voice_wan2gp_audio_guide: currentReference.voice_wan2gp_audio_guide,
      voice_wan2gp_temperature: currentReference.voice_wan2gp_temperature,
      voice_wan2gp_top_k: currentReference.voice_wan2gp_top_k,
      voice_wan2gp_seed: currentReference.voice_wan2gp_seed,
    }))
  }, [
    currentReference,
    getLockedNarratorCountByMode,
    narratorStyle,
    references,
    scriptMode,
    voiceMeta,
  ])

  // ── Handlers ───────────────────────────────────────────────────────────
  const handlePrevReference = () => {
    const references = stageData?.reference?.references || stageData?.storyboard?.references || []
    setCurrentReferenceIndex((prev) => (prev > 0 ? prev - 1 : references.length - 1))
  }

  const handleNextReference = () => {
    const references = stageData?.reference?.references || stageData?.storyboard?.references || []
    setCurrentReferenceIndex((prev) => (prev < references.length - 1 ? prev + 1 : 0))
  }

  const handleStartEditReference = useCallback((reference: Reference) => {
    const references = stageData?.reference?.references || stageData?.storyboard?.references || []
    const mode = resolveScriptMode(
      configuredScriptMode || stageData?.content?.script_mode,
      resolvedConfiguredScriptMode
    )
    const referenceIndex = references.findIndex((item) => String(item.id) === String(reference.id))
    const isLockedNarratorReference = referenceIndex >= 0
      && referenceIndex < getLockedNarratorCountByMode(mode)
    const narratorPresetSetting = isLockedNarratorReference
      ? resolveNarratorPresetSettingByMode(mode, narratorStyle, referenceIndex)
      : ''
    const lockNarratorSetting = isLockedNarratorReference && !!narratorPresetSetting
    const existingSetting = String(reference.setting || '').trim()
    const resolvedSetting = lockNarratorSetting
      ? narratorPresetSetting
      : (
        isLockedNarratorReference
        && !narratorPresetSetting
        && isNarratorPresetSettingTextByMode(mode, existingSetting)
          ? ''
          : existingSetting
      )

    setEditedReferenceName(reference.name)
    setEditedReferenceSetting(resolvedSetting)
    setEditedReferenceAppearanceDesc(
      String(reference.appearance_description || '').trim()
    )
    const canSpeak = isLockedNarratorReference ? true : (reference.can_speak !== false)
    setEditedReferenceCanSpeak(canSpeak)
    setEditedReferenceVoice(voiceMeta.normalizeConfig({
      voice_audio_provider: reference.voice_audio_provider,
      voice_name: reference.voice_name,
      voice_speed: reference.voice_speed,
      voice_wan2gp_preset: reference.voice_wan2gp_preset,
      voice_wan2gp_alt_prompt: reference.voice_wan2gp_alt_prompt,
      voice_wan2gp_audio_guide: reference.voice_wan2gp_audio_guide,
      voice_wan2gp_temperature: reference.voice_wan2gp_temperature,
      voice_wan2gp_top_k: reference.voice_wan2gp_top_k,
      voice_wan2gp_seed: reference.voice_wan2gp_seed,
    }))
    setIsEditingReference(true)
  }, [
    configuredScriptMode,
    getLockedNarratorCountByMode,
    narratorStyle,
    resolvedConfiguredScriptMode,
    stageData?.content?.script_mode,
    stageData?.reference?.references,
    stageData?.storyboard?.references,
    voiceMeta,
  ])

  const handleCancelEditReference = () => {
    setIsEditingReference(false)
    setEditedReferenceName('')
    setEditedReferenceSetting('')
    setEditedReferenceAppearanceDesc('')
    setEditedReferenceCanSpeak(true)
    setEditedReferenceVoice({ voice_audio_provider: voiceMeta.defaultAudioProvider })
  }

  const handleSaveReference = useCallback(async (referenceId: string | number) => {
    if (!onSaveReference) return
    const references = stageData?.reference?.references || stageData?.storyboard?.references || []
    const mode = resolveScriptMode(
      configuredScriptMode || stageData?.content?.script_mode,
      resolvedConfiguredScriptMode
    )
    const referenceIndex = references.findIndex((item) => String(item.id) === String(referenceId))
    const isLockedNarratorReference = referenceIndex >= 0
      && referenceIndex < getLockedNarratorCountByMode(mode)
    const narratorPresetSetting = isLockedNarratorReference
      ? resolveNarratorPresetSettingByMode(mode, narratorStyle, referenceIndex)
      : ''
    const lockNarratorSetting = isLockedNarratorReference && !!narratorPresetSetting

    setIsSavingReference(true)
    setIsAutoSavingReference(true)
    try {
      const canSpeak = isLockedNarratorReference ? true : editedReferenceCanSpeak
      await onSaveReference(referenceId, {
        name: editedReferenceName,
        setting: lockNarratorSetting ? narratorPresetSetting : editedReferenceSetting,
        appearance_description: editedReferenceAppearanceDesc,
        can_speak: canSpeak,
        ...voiceMeta.toPayload(canSpeak, editedReferenceVoice),
      })
      lastSubmittedReferenceSignatureRef.current = buildReferenceSignature({
        referenceId,
        name: editedReferenceName,
        setting: lockNarratorSetting ? narratorPresetSetting : editedReferenceSetting,
        appearanceDescription: editedReferenceAppearanceDesc,
        canSpeak,
        voice: editedReferenceVoice,
      })
    } catch (error) {
      console.error('Failed to save reference:', error)
    } finally {
      setIsSavingReference(false)
      setIsAutoSavingReference(false)
    }
  }, [
    buildReferenceSignature,
    configuredScriptMode,
    editedReferenceAppearanceDesc,
    editedReferenceCanSpeak,
    editedReferenceName,
    editedReferenceSetting,
    editedReferenceVoice,
    getLockedNarratorCountByMode,
    narratorStyle,
    onSaveReference,
    resolvedConfiguredScriptMode,
    stageData?.content?.script_mode,
    stageData?.reference?.references,
    stageData?.storyboard?.references,
    voiceMeta,
  ])

  const savedReferenceSignature = useMemo(() => {
    if (!currentReference) return ''
    const referenceIndex = references.findIndex((item) => String(item.id) === String(currentReference.id))
    const isLockedNarratorReference = referenceIndex >= 0
      && referenceIndex < getLockedNarratorCountByMode(scriptMode)
    const narratorPresetSetting = isLockedNarratorReference
      ? resolveNarratorPresetSettingByMode(scriptMode, narratorStyle, referenceIndex)
      : ''
    const lockNarratorSetting = isLockedNarratorReference && !!narratorPresetSetting
    const existingSetting = String(currentReference.setting || '').trim()
    const resolvedSetting = lockNarratorSetting
      ? narratorPresetSetting
      : (
        isLockedNarratorReference
        && !narratorPresetSetting
        && isNarratorPresetSettingTextByMode(scriptMode, existingSetting)
          ? ''
          : existingSetting
      )
    return buildReferenceSignature({
      referenceId: currentReference.id,
      name: currentReference.name,
      setting: resolvedSetting,
      appearanceDescription: String(currentReference.appearance_description || '').trim(),
      canSpeak: isLockedNarratorReference ? true : (currentReference.can_speak !== false),
      voice: {
        voice_audio_provider: currentReference.voice_audio_provider,
        voice_name: currentReference.voice_name,
        voice_speed: currentReference.voice_speed,
        voice_wan2gp_preset: currentReference.voice_wan2gp_preset,
        voice_wan2gp_alt_prompt: currentReference.voice_wan2gp_alt_prompt,
        voice_wan2gp_audio_guide: currentReference.voice_wan2gp_audio_guide,
        voice_wan2gp_temperature: currentReference.voice_wan2gp_temperature,
        voice_wan2gp_top_k: currentReference.voice_wan2gp_top_k,
        voice_wan2gp_seed: currentReference.voice_wan2gp_seed,
      },
    })
  }, [
    buildReferenceSignature,
    currentReference,
    getLockedNarratorCountByMode,
    narratorStyle,
    references,
    scriptMode,
  ])

  const currentReferenceSignature = useMemo(() => {
    if (!currentReference) return ''
    return buildReferenceSignature({
      referenceId: currentReference.id,
      name: editedReferenceName,
      setting: editedReferenceSetting,
      appearanceDescription: editedReferenceAppearanceDesc,
      canSpeak: editedReferenceCanSpeak,
      voice: editedReferenceVoice,
    })
  }, [
    buildReferenceSignature,
    currentReference,
    editedReferenceAppearanceDesc,
    editedReferenceCanSpeak,
    editedReferenceName,
    editedReferenceSetting,
    editedReferenceVoice,
  ])

  useEffect(() => {
    if (!currentReference || !onSaveReference) return
    if (currentReferenceSignature === savedReferenceSignature) {
      lastSubmittedReferenceSignatureRef.current = ''
      return
    }
    if (currentReferenceSignature === lastSubmittedReferenceSignatureRef.current) return

    if (referenceAutoSaveTimerRef.current !== null) {
      window.clearTimeout(referenceAutoSaveTimerRef.current)
    }

    referenceAutoSaveTimerRef.current = window.setTimeout(() => {
      void handleSaveReference(currentReference.id)
    }, 800)

    return () => {
      if (referenceAutoSaveTimerRef.current !== null) {
        window.clearTimeout(referenceAutoSaveTimerRef.current)
        referenceAutoSaveTimerRef.current = null
      }
    }
  }, [
    currentReference,
    currentReferenceSignature,
    handleSaveReference,
    onSaveReference,
    savedReferenceSignature,
  ])

  const flushAutoSaveReference = useCallback(async () => {
    if (!currentReference || !onSaveReference) return
    if (currentReferenceSignature === savedReferenceSignature) return
    if (currentReferenceSignature === lastSubmittedReferenceSignatureRef.current) return
    if (referenceAutoSaveTimerRef.current !== null) {
      window.clearTimeout(referenceAutoSaveTimerRef.current)
      referenceAutoSaveTimerRef.current = null
    }
    await handleSaveReference(currentReference.id)
  }, [
    currentReference,
    currentReferenceSignature,
    handleSaveReference,
    onSaveReference,
    savedReferenceSignature,
  ])

  const handleDeleteClick = (reference: Reference) => {
    const mode = resolveScriptMode(
      configuredScriptMode || stageData?.content?.script_mode,
      resolvedConfiguredScriptMode
    )
    const references = stageData?.reference?.references || stageData?.storyboard?.references || []
    const lockedSceneReferenceId = mode === 'duo_podcast'
      ? String(references[2]?.id || '').trim()
      : ''
    const referenceIndex = references.findIndex((item) => String(item.id) === String(reference.id))
    if (referenceIndex >= 0 && referenceIndex < getLockedNarratorCountByMode(mode)) {
      if (mode === 'single') {
        toast.info('单人叙述模式下，首个参考固定为讲述者，不能删除')
      } else if (mode === 'duo_podcast') {
        toast.info('双人播客模式下，前3个参考固定为左角色、右角色和播客场景，不能删除')
      }
      return
    }
    if (mode === 'duo_podcast' && lockedSceneReferenceId && String(reference.id) === lockedSceneReferenceId) {
      toast.info('双人播客模式下，播客场景参考固定，不能删除')
      return
    }
    setReferenceToDelete(reference)
    setShowDeleteDialog(true)
  }

  const handleConfirmDelete = async () => {
    if (!onDeleteReference || !referenceToDelete) return
    const references = stageData?.reference?.references || stageData?.storyboard?.references || []
    const deletingIndex = references.findIndex((item) => String(item.id) === String(referenceToDelete.id))
    const targetIndexAfterDelete = (
      deletingIndex >= 0
      && deletingIndex < references.length - 1
    )
      ? deletingIndex
      : 0
    setIsDeleting(true)
    try {
      await onDeleteReference(referenceToDelete.id)
      setShowDeleteDialog(false)
      setReferenceToDelete(null)
      setCurrentReferenceIndex(targetIndexAfterDelete)
    } catch (error) {
      console.error('Failed to delete reference:', error)
    } finally {
      setIsDeleting(false)
    }
  }

  const handleCancelDelete = () => {
    setShowDeleteDialog(false)
    setReferenceToDelete(null)
  }

  const handleRegenerateImage = async (referenceId: string | number) => {
    if (!onRegenerateReferenceImage) return
    setRegeneratingReferenceId(referenceId)
    try {
      await onRegenerateReferenceImage(referenceId)
    } catch (error) {
      console.error('Failed to regenerate image:', error)
    } finally {
      setRegeneratingReferenceId(null)
    }
  }

  const handleImageClick = () => {
    if (
      !onUploadReferenceImage
      || isUploading
      || regeneratingReferenceId !== null
      || isReferenceImageActionRunningGlobal
    ) {
      return
    }
    fileInputRef.current?.click()
  }

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>, referenceId: string | number) => {
    const file = e.target.files?.[0]
    if (!file || !onUploadReferenceImage) return

    setIsUploading(true)
    try {
      await onUploadReferenceImage(referenceId, file)
    } catch (error) {
      console.error('Failed to upload image:', error)
    } finally {
      setIsUploading(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  const handleNewReferenceClick = async () => {
    if (!onCreateReference) return
    const mode = resolveScriptMode(
      configuredScriptMode || stageData?.content?.script_mode,
      resolvedConfiguredScriptMode
    )
    const references = stageData?.reference?.references || stageData?.storyboard?.references || []
    const lockedNarratorCount = getLockedNarratorCountByMode(mode)
    const pendingNarratorIndex = references.length
    const isPendingLockedNarrator = pendingNarratorIndex < lockedNarratorCount
    const narratorPresetSetting = isPendingLockedNarrator
      ? resolveNarratorPresetSettingByMode(mode, narratorStyle, pendingNarratorIndex)
      : ''

    const defaultName = isPendingLockedNarrator
      ? getNarratorDefaultNameByMode(mode, pendingNarratorIndex)
      : '新参考'
    const defaultSetting = (isPendingLockedNarrator && narratorPresetSetting)
      ? narratorPresetSetting
      : ''
    const defaultVoice = buildDefaultNewReferenceVoice({
      mode,
      narratorIndex: pendingNarratorIndex,
      isLockedNarrator: isPendingLockedNarrator,
    })
    const canSpeak = isPendingLockedNarrator ? true : false

    setIsEditingReference(false)
    setShowNewReferenceCard(false)
    setIsCreatingReference(true)
    try {
      await onCreateReference({
        name: defaultName,
        setting: defaultSetting,
        appearance_description: '',
        can_speak: canSpeak,
        ...voiceMeta.toPayload(canSpeak, defaultVoice),
      })
      setCurrentReferenceIndex(references.length)
      setNewReferenceName('新参考')
      setNewReferenceSetting('')
      setNewReferenceAppearanceDesc('')
      setNewReferenceCanSpeak(false)
      setNewReferenceVoice(buildDefaultNewReferenceVoice())
    } catch (error) {
      console.error('Failed to create reference:', error)
    } finally {
      setIsCreatingReference(false)
    }
  }

  const handleNewReferenceFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !onCreateReference) return
    const mode = resolveScriptMode(
      configuredScriptMode || stageData?.content?.script_mode,
      resolvedConfiguredScriptMode
    )
    const references = stageData?.reference?.references || stageData?.storyboard?.references || []
    const lockedNarratorCount = getLockedNarratorCountByMode(mode)
    const pendingNarratorIndex = references.length
    const isPendingLockedNarrator = pendingNarratorIndex < lockedNarratorCount
    const narratorPresetSetting = isPendingLockedNarrator
      ? resolveNarratorPresetSettingByMode(mode, narratorStyle, pendingNarratorIndex)
      : ''

    setIsCreatingReference(true)
    try {
      const canSpeak = isPendingLockedNarrator ? true : newReferenceCanSpeak
      await onCreateReference({
        name: isPendingLockedNarrator
          ? getNarratorDefaultNameByMode(mode, pendingNarratorIndex)
          : newReferenceName,
        setting: isPendingLockedNarrator && narratorPresetSetting
          ? narratorPresetSetting
          : newReferenceSetting,
        appearance_description: newReferenceAppearanceDesc,
        can_speak: canSpeak,
        ...voiceMeta.toPayload(
          canSpeak,
          newReferenceVoice
        ),
        file,
      })
      setIsEditingReference(false)
      setShowNewReferenceCard(false)
      setNewReferenceName('新参考')
      setNewReferenceSetting('')
      setNewReferenceAppearanceDesc('')
      setNewReferenceCanSpeak(false)
      setNewReferenceVoice(buildDefaultNewReferenceVoice())
      const latestReferences = stageData?.reference?.references || stageData?.storyboard?.references || []
      setCurrentReferenceIndex(latestReferences.length)
    } catch (error) {
      console.error('Failed to create reference:', error)
    } finally {
      setIsCreatingReference(false)
      if (newReferenceFileInputRef.current) {
        newReferenceFileInputRef.current.value = ''
      }
    }
  }

  const handleOpenNewReferenceFilePicker = useCallback(() => {
    if (!onCreateReference || isCreatingReference) return
    newReferenceFileInputRef.current?.click()
  }, [isCreatingReference, onCreateReference])

  const handleCreateReferenceWithoutImage = async () => {
    if (!onCreateReference) return
    const mode = resolveScriptMode(
      configuredScriptMode || stageData?.content?.script_mode,
      resolvedConfiguredScriptMode
    )
    const references = stageData?.reference?.references || stageData?.storyboard?.references || []
    const lockedNarratorCount = getLockedNarratorCountByMode(mode)
    const pendingNarratorIndex = references.length
    const isPendingLockedNarrator = pendingNarratorIndex < lockedNarratorCount
    const narratorPresetSetting = isPendingLockedNarrator
      ? resolveNarratorPresetSettingByMode(mode, narratorStyle, pendingNarratorIndex)
      : ''

    setIsCreatingReference(true)
    try {
      const canSpeak = isPendingLockedNarrator ? true : newReferenceCanSpeak
      await onCreateReference({
        name: isPendingLockedNarrator
          ? getNarratorDefaultNameByMode(mode, pendingNarratorIndex)
          : newReferenceName,
        setting: isPendingLockedNarrator && narratorPresetSetting
          ? narratorPresetSetting
          : newReferenceSetting,
        appearance_description: newReferenceAppearanceDesc,
        can_speak: canSpeak,
        ...voiceMeta.toPayload(
          canSpeak,
          newReferenceVoice
        ),
      })
      setIsEditingReference(false)
      setShowNewReferenceCard(false)
      setNewReferenceName('新参考')
      setNewReferenceSetting('')
      setNewReferenceAppearanceDesc('')
      setNewReferenceCanSpeak(false)
      setNewReferenceVoice(buildDefaultNewReferenceVoice())
      const latestReferences = stageData?.reference?.references || stageData?.storyboard?.references || []
      setCurrentReferenceIndex(latestReferences.length)
    } catch (error) {
      console.error('Failed to create reference:', error)
    } finally {
      setIsCreatingReference(false)
    }
  }

  const handleOpenImportDialog = (startIndex = 0) => {
    if (!onImportReferencesFromLibrary) return
    setImportStartReferenceIndex(Math.max(0, Math.floor(startIndex)))
    setImportSelectionOrder([])
    setImportSettingChecked(true)
    setImportAppearanceChecked(true)
    setImportImageChecked(true)
    setImportVoiceChecked(true)
    setImportResult(null)
    setShowImportDialog(true)
  }

  const handleToggleImportSelection = (libraryReferenceId: number, checked: boolean) => {
    setImportSelectionOrder((prev) => {
      const exists = prev.includes(libraryReferenceId)
      if (checked) {
        if (exists) return prev
        return [...prev, libraryReferenceId]
      }
      if (!exists) return prev
      return prev.filter((id) => id !== libraryReferenceId)
    })
  }

  const handleImportAllSelection = (checked: boolean) => {
    setImportSelectionOrder(checked ? libraryReferences.map((item) => item.id) : [])
  }

  const handleConfirmImportFromLibrary = async () => {
    if (!onImportReferencesFromLibrary) return
    const selectedIds = importSelectionOrder
    if (selectedIds.length === 0) {
      toast.info('请先勾选至少一个参考')
      return
    }
    const currentMode = resolveScriptMode(
      configuredScriptMode || stageData?.content?.script_mode,
      resolvedConfiguredScriptMode
    )
    const lockedNarratorReferences = getLockedNarratorCountByMode(currentMode)
    if (lockedNarratorReferences > 0) {
      const invalidReferences: string[] = []
      for (let offset = 0; offset < selectedIds.length; offset += 1) {
        const targetIndex = importStartReferenceIndex + offset
        if (targetIndex >= lockedNarratorReferences) continue
        const selectedId = selectedIds[offset]
        const selectedRef = libraryReferences.find((item) => item.id === selectedId)
        if (selectedRef && selectedRef.can_speak === false) {
          invalidReferences.push(`#${targetIndex + 1} ${selectedRef.name || `参考${selectedId}`}`)
        }
      }
      if (invalidReferences.length > 0) {
        toast.error(`讲述者固定槽位仅允许可说台词参考，当前不符合：${invalidReferences.join('、')}`)
        return
      }
    }
    const overwriteRefs = references.slice(
      importStartReferenceIndex,
      importStartReferenceIndex + selectedIds.length
    )
    if (overwriteRefs.length > 0) {
      const overwriteLabel = overwriteRefs
        .map((ref, idx) => `#${importStartReferenceIndex + idx + 1} ${ref.name || '未命名参考'}`)
        .join('、')
      const confirmed = await confirmDialog({
        title: '覆盖已有角色',
        description: `本次导入将覆盖以下已有角色：${overwriteLabel}\n是否继续？`,
        confirmText: '继续导入',
        cancelText: '取消',
      })
      if (!confirmed) return
    }

    setIsImportingReferences(true)
    try {
      const result = await onImportReferencesFromLibrary({
        library_reference_ids: selectedIds,
        start_reference_index: importStartReferenceIndex,
        import_setting: importSettingChecked,
        import_appearance_description: importAppearanceChecked,
        import_image: importImageChecked,
        import_voice: importVoiceChecked,
      })
      setImportResult(result)
    } catch (error) {
      console.error('Failed to import references from library:', error)
    } finally {
      setIsImportingReferences(false)
    }
  }

  const handleGenerateDescriptionFromImage = async (referenceId: string | number) => {
    if (!onGenerateDescriptionFromImage) return
    const referenceKey = String(referenceId)
    setGeneratingDescriptionReferenceIds((prev) => {
      const next = new Set(prev)
      next.add(referenceKey)
      return next
    })
    try {
      await onGenerateDescriptionFromImage(referenceId)
    } catch (error) {
      console.error('Failed to generate description:', error)
    } finally {
      setGeneratingDescriptionReferenceIds((prev) => {
        const next = new Set(prev)
        next.delete(referenceKey)
        return next
      })
    }
  }

  const handleDeleteReferenceImage = async (referenceId: string | number) => {
    if (!onDeleteReferenceImage) return
    setIsDeletingReferenceImage(true)
    try {
      await onDeleteReferenceImage(referenceId)
    } catch (error) {
      console.error('Failed to delete reference image:', error)
    } finally {
      setIsDeletingReferenceImage(false)
    }
  }

  // ── Derived view-model ─────────────────────────────────────────────────
  const referenceConstraintHintText = activeScriptModeForConstraint === 'single' || activeScriptModeForConstraint === 'duo_podcast'
    ? '该预设模式下已存在参考角色仅能在参考区直接修改'
    : ''
  const selectedImportCount = importSelectionOrder.length
  const overwriteReferencePreview = references.slice(
    importStartReferenceIndex,
    importStartReferenceIndex + selectedImportCount
  )
  const appendCountPreview = Math.max(0, selectedImportCount - overwriteReferencePreview.length)
  const lockedNarratorCount = getLockedNarratorCountByMode(scriptMode)
  const isCurrentLockedNarratorReference = !!currentReference && safeCurrentReferenceIndex < lockedNarratorCount
  const lockedDuoSceneReferenceId = scriptMode === 'duo_podcast'
    ? String(references[2]?.id || '').trim()
    : ''
  const isCurrentLockedDuoSceneReference = (
    scriptMode === 'duo_podcast'
    && !!currentReference
    && !!lockedDuoSceneReferenceId
    && String(currentReference.id) === lockedDuoSceneReferenceId
  )
  const isCurrentFixedReference = isCurrentLockedNarratorReference || isCurrentLockedDuoSceneReference
  const currentLockedNarratorIndex = isCurrentLockedNarratorReference ? safeCurrentReferenceIndex : -1
  const currentNarratorPresetSetting = currentLockedNarratorIndex >= 0
    ? resolveNarratorPresetSettingByMode(scriptMode, narratorStyle, currentLockedNarratorIndex)
    : ''
  const isCurrentNarratorSettingLocked = isCurrentLockedNarratorReference && !!currentNarratorPresetSetting
  const isPendingLockedNarratorReference = references.length < lockedNarratorCount
  const pendingLockedNarratorIndex = isPendingLockedNarratorReference ? references.length : -1
  const pendingNarratorPresetSetting = pendingLockedNarratorIndex >= 0
    ? resolveNarratorPresetSettingByMode(scriptMode, narratorStyle, pendingLockedNarratorIndex)
    : ''
  const isPendingNarratorSettingLocked = isPendingLockedNarratorReference && !!pendingNarratorPresetSetting
  const speakEnabledReferenceLimit = lockedNarratorCount > 0 ? lockedNarratorCount : Number.POSITIVE_INFINITY
  const hasSpeakEnabledReferenceLimit = Number.isFinite(speakEnabledReferenceLimit)
  const speakInactiveHintText = speakEnabledReferenceLimit === 1
    ? '单人叙述模式下仅首个参考可说台词，当前声音配置未生效。'
    : (
      speakEnabledReferenceLimit === 2
        ? '双人播客模式下仅前2个参考可说台词，当前声音配置未生效。'
        : ''
    )
  const isCurrentReferenceCanSpeak = currentReference?.can_speak !== false
  const isCurrentReferenceSpeakInactive = !!currentReference
    && isCurrentReferenceCanSpeak
    && hasSpeakEnabledReferenceLimit
    && safeCurrentReferenceIndex >= speakEnabledReferenceLimit
  const isEditedReferenceSpeakInactive = isEditingReference
    && editedReferenceCanSpeak
    && hasSpeakEnabledReferenceLimit
    && safeCurrentReferenceIndex >= speakEnabledReferenceLimit
  const pendingReferenceIndex = references.length
  const isNewReferenceSpeakInactive = showNewReferenceCard
    && newReferenceCanSpeak
    && !isPendingLockedNarratorReference
    && hasSpeakEnabledReferenceLimit
    && pendingReferenceIndex >= speakEnabledReferenceLimit
  const rawCurrentReferenceSetting = String(currentReference?.setting || '').trim()
  const currentReferenceSetting = isCurrentNarratorSettingLocked
    ? currentNarratorPresetSetting
    : (
      isCurrentLockedNarratorReference
      && !currentNarratorPresetSetting
      && isNarratorPresetSettingTextByMode(scriptMode, rawCurrentReferenceSetting)
        ? ''
        : rawCurrentReferenceSetting
    )
  const currentReferenceAppearanceDesc = String(
    currentReference?.appearance_description || ''
  ).trim()
  const isReferenceImageActionRunning = isReferenceImageActionRunningGlobal
  const currentReferenceGeneratingState =
    currentReference ? generatingShots?.[String(currentReference.id)] : undefined
  const hasReferenceSlotState = currentReferenceGeneratingState?.progress !== undefined
  const isCurrentReferenceByStage =
    !!currentReference
    && runningReferenceId !== undefined
    && String(currentReference.id) === String(runningReferenceId)
  const isReferenceSingleRun = runningReferenceId !== undefined
  const referenceGenerationState = resolveCurrentItemGenerationState({
    isStageRunning: isReferenceImageActionRunning,
    isSingleItemRun: isReferenceSingleRun,
    isTargetItem: isCurrentReferenceByStage,
    hasItemState: hasReferenceSlotState,
    hasGeneratingItem: hasAnyGeneratingShot,
    batchMode: 'active_only',
    singleRunUseItemState: true,
  })
  const isReferenceImageStageRunning = referenceGenerationState.isGenerating
  const isReferenceStarting = referenceGenerationState.isStarting
  const isLocalReferenceRegenerating =
    regeneratingReferenceId !== null
    && !!currentReference
    && String(currentReference.id) === String(regeneratingReferenceId)
  const isCurrentReferenceGeneratingDescription =
    !!currentReference && generatingDescriptionReferenceIds.has(String(currentReference.id))
  const showReferenceGenerating = isLocalReferenceRegenerating || isReferenceImageStageRunning
  const {
    progress: referenceProgress,
    progressText: referenceProgressText,
    isModelDownloading: isReferenceModelDownloading,
  } = resolveRuntimeDisplay({
    isGenerating: isReferenceImageStageRunning,
    isStarting: isReferenceStarting,
    shotProgress: currentReferenceGeneratingState?.progress,
    stageProgress: progress,
    progressMessage: isReferenceImageActionRunning ? progressMessage : undefined,
  })

  return {
    // Refs
    fileInputRef,
    newReferenceFileInputRef,

    // Navigation state
    currentReferenceIndex,
    setCurrentReferenceIndex,
    safeCurrentReferenceIndex,
    references,
    currentReference,
    hasReferences,

    // Edit state
    isEditingReference,
    editedReferenceName,
    setEditedReferenceName,
    editedReferenceSetting,
    setEditedReferenceSetting,
    editedReferenceAppearanceDesc,
    setEditedReferenceAppearanceDesc,
    editedReferenceCanSpeak,
    setEditedReferenceCanSpeak,
    editedReferenceVoice,
    setEditedReferenceVoice,
    isSavingReference,
    isAutoSavingReference,
    normalizedEditedReferenceVoice,
    isEditedReferenceSpeakInactive,
    isCurrentNarratorSettingLocked,
    isCurrentLockedNarratorReference,

    // New reference state
    showNewReferenceCard,
    setShowNewReferenceCard,
    isCreatingReference,
    newReferenceName,
    setNewReferenceName,
    newReferenceSetting,
    setNewReferenceSetting,
    newReferenceAppearanceDesc,
    setNewReferenceAppearanceDesc,
    newReferenceCanSpeak,
    setNewReferenceCanSpeak,
    newReferenceVoice,
    setNewReferenceVoice,
    normalizedNewReferenceVoice,
    isNewReferenceSpeakInactive,
    isPendingLockedNarratorReference,
    isPendingNarratorSettingLocked,
    pendingLockedNarratorIndex,

    // Delete state
    showDeleteDialog,
    setShowDeleteDialog,
    referenceToDelete,
    isDeleting,

    // Image state
    regeneratingReferenceId,
    isUploading,
    isDeletingReferenceImage,

    // Import state
    showImportDialog,
    setShowImportDialog,
    importStartReferenceIndex,
    importSelectionOrder,
    importSettingChecked,
    setImportSettingChecked,
    importAppearanceChecked,
    setImportAppearanceChecked,
    importImageChecked,
    setImportImageChecked,
    importVoiceChecked,
    setImportVoiceChecked,
    isImportingReferences,
    importResult,
    selectedImportCount,
    overwriteReferencePreview,
    appendCountPreview,

    // View-model values
    scriptMode,
    referenceConstraintHintText,
    lockedNarratorCount,
    isCurrentLockedDuoSceneReference,
    isCurrentFixedReference,
    currentReferenceSetting,
    currentReferenceAppearanceDesc,
    isCurrentReferenceCanSpeak,
    isCurrentReferenceSpeakInactive,
    speakInactiveHintText,
    isCurrentReferenceGeneratingDescription,
    showReferenceGenerating,
    isReferenceImageStageRunning,
    referenceProgress,
    referenceProgressText,
    isReferenceModelDownloading,
    generatingDescriptionReferenceIds,

    // Voice meta
    voiceMeta,
    voiceLibraryNameByAudioPath,

    // Handlers
    handlePrevReference,
    handleNextReference,
    handleStartEditReference,
    handleCancelEditReference,
    handleSaveReference,
    flushAutoSaveReference,
    handleDeleteClick,
    handleConfirmDelete,
    handleCancelDelete,
    handleRegenerateImage,
    handleImageClick,
    handleFileChange,
    handleNewReferenceClick,
    handleNewReferenceFileChange,
    handleOpenNewReferenceFilePicker,
    handleCreateReferenceWithoutImage,
    handleOpenImportDialog,
    handleToggleImportSelection,
    handleImportAllSelection,
    handleConfirmImportFromLibrary,
    handleGenerateDescriptionFromImage,
    handleDeleteReferenceImage,

    // Callbacks from props (pass-through for sub-components)
    onSaveReference,
    onDeleteReference,
    onRegenerateReferenceImage,
    onUploadReferenceImage,
    onCreateReference,
    onGenerateDescriptionFromImage,
    onDeleteReferenceImage,
    onImportReferencesFromLibrary,
    libraryReferences,
  }
}

export type UseScriptReferencePanelReturn = ReturnType<typeof useScriptReferencePanel>
