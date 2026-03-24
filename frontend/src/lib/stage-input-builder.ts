import type { StageConfig } from '@/types/stage-panel'
import type { BackendStageType } from '@/types/stage'
import type { Settings } from '@/types/settings'
import { getComposeFixedResolutionOptions, parseComposeResolution } from '@/lib/compose-canvas'
import { rateToSpeed } from '@/lib/reference-voice'
import { resolveVideoProvider } from '@/lib/stage-runtime'
import { getImageModel, getVideoModelByProvider } from '@/lib/project-detail-helpers'
import {
  isNarratorPresetSettingTextByMode,
  resolveNarratorCustomNameByMode,
  resolveNarratorPresetNameByMode,
  resolveNarratorPresetSettingByMode,
} from '@/lib/narrator-style'

const QWEN3_LANGUAGE_MODES = [
  'auto',
  'chinese',
  'english',
  'japanese',
  'korean',
  'german',
  'french',
  'russian',
  'portuguese',
  'spanish',
  'italian',
]

const QWEN3_CUSTOM_VOICE_MODES = [
  'serena',
  'aiden',
  'dylan',
  'eric',
  'ono_anna',
  'ryan',
  'v_serena',
  'sohee',
  'uncle_fu',
  'vivian',
]

const VERTEX_LAST_FRAME_SUPPORTED_MODELS = [
  'veo-3.1',
  'veo-3.1-fast',
  'veo-3.1-preview',
  'veo-3.1-fast-preview',
]

const SEEDANCE_LAST_FRAME_SUPPORTED_MODELS = [
  'seedance-2-0',
  'seedance-2-0-fast',
]
const SINGLE_ROLE_ID = 'ref_01'
const SINGLE_ROLE_NAME = '讲述者'
const DUO_ROLE_1_ID = 'ref_01'
const DUO_ROLE_2_ID = 'ref_02'
const DUO_SCENE_ROLE_ID = 'ref_03'
const DUO_ROLE_1_NAME = '讲述者1'
const DUO_ROLE_2_NAME = '讲述者2'
const LLM_MODEL_BINDING_SEPARATOR = '::'

function parseLlmModelBinding(rawValue: unknown): { providerId: string; modelId: string } | null {
  const text = String(rawValue || '').trim()
  if (!text) return null
  const separatorIndex = text.indexOf(LLM_MODEL_BINDING_SEPARATOR)
  if (separatorIndex <= 0) return null
  const providerId = text.slice(0, separatorIndex).trim()
  const modelId = text.slice(separatorIndex + LLM_MODEL_BINDING_SEPARATOR.length).trim()
  if (!providerId || !modelId) return null
  return { providerId, modelId }
}

function resolveConfiguredLlmProviderPool(settings?: Settings) {
  const providers = settings?.llm_providers || []
  return providers.filter((provider) => String(provider.api_key || '').trim().length > 0)
}

function pickProviderModel(provider: Settings['llm_providers'][number] | undefined): string {
  if (!provider) return ''
  const enabled = provider.enabled_models || []
  const catalog = provider.catalog_models || []
  return String(provider.default_model || enabled[0] || catalog[0] || '').trim()
}

function resolveEffectiveLlmSelection(config: StageConfig, settings?: Settings): {
  providerId: string
  modelId: string
} {
  let requestedProviderId = String(config.llmProvider || '').trim()
  let requestedModelId = String(config.llmModel || '').trim()
  const configBinding = parseLlmModelBinding(requestedModelId)
  if (configBinding) {
    requestedProviderId = requestedProviderId || configBinding.providerId
    requestedModelId = configBinding.modelId
  }

  const configuredProviders = resolveConfiguredLlmProviderPool(settings)
  const providerById = new Map(configuredProviders.map((provider) => [provider.id, provider]))
  if (requestedProviderId && providerById.has(requestedProviderId)) {
    const provider = providerById.get(requestedProviderId)
    const modelId = requestedModelId || pickProviderModel(provider)
    return { providerId: requestedProviderId, modelId }
  }

  const defaultBinding = parseLlmModelBinding(settings?.default_general_llm_model)
  const fallbackProviderId = String(
    defaultBinding?.providerId
    || settings?.default_llm_provider
    || configuredProviders[0]?.id
    || ''
  ).trim()
  const fallbackProvider = providerById.get(fallbackProviderId) || configuredProviders[0]
  const fallbackModelId = String(
    defaultBinding?.modelId
    || pickProviderModel(fallbackProvider)
    || requestedModelId
  ).trim()

  return {
    providerId: String(fallbackProvider?.id || '').trim(),
    modelId: fallbackModelId,
  }
}

function resolveSingleTakeVideoModel(params: {
  provider: string
  preferredModel?: string
  settings?: Settings
  mode?: 't2v' | 'i2v'
}): string | undefined {
  const { provider, preferredModel, settings, mode = 't2v' } = params
  const preferred = String(preferredModel || '').trim()
  const providerFallback = String(
    settings ? getVideoModelByProvider(provider, settings, mode) : ''
  ).trim()
  if (provider === 'vertex_ai') {
    const fallback = providerFallback || 'veo-3.1-fast-preview'
    const candidate = preferred || fallback
    if (VERTEX_LAST_FRAME_SUPPORTED_MODELS.includes(candidate)) return candidate
    return VERTEX_LAST_FRAME_SUPPORTED_MODELS.includes(fallback)
      ? fallback
      : VERTEX_LAST_FRAME_SUPPORTED_MODELS[0]
  }
  if (provider === 'volcengine_seedance') {
    const fallback = providerFallback || 'seedance-2-0'
    const candidate = preferred || fallback
    if (SEEDANCE_LAST_FRAME_SUPPORTED_MODELS.includes(candidate)) return candidate
    return SEEDANCE_LAST_FRAME_SUPPORTED_MODELS.includes(fallback)
      ? fallback
      : SEEDANCE_LAST_FRAME_SUPPORTED_MODELS[0]
  }
  return preferred || providerFallback || undefined
}

function resolveDefaultVideoProviderByMode(
  settings: Settings | undefined,
  mode: 't2v' | 'i2v'
): string | undefined {
  const rawBinding = String(
    mode === 'i2v'
      ? settings?.default_video_i2v_model
      : settings?.default_video_t2v_model
  ).trim()
  if (!rawBinding) return undefined
  const separatorIndex = rawBinding.indexOf('::')
  if (separatorIndex <= 0) return undefined
  const provider = rawBinding.slice(0, separatorIndex).trim()
  return provider || undefined
}

export function resolveWan2gpAudioMode(preset: string, configuredMode: string | undefined): string {
  const fallback = preset === 'qwen3_tts_customvoice' ? 'serena' : 'auto'
  const allowedModes = preset === 'qwen3_tts_customvoice'
    ? QWEN3_CUSTOM_VOICE_MODES
    : QWEN3_LANGUAGE_MODES
  const mode = (configuredMode || '').trim().toLowerCase()
  return allowedModes.includes(mode) ? mode : fallback
}

export function getScopedWan2gpInferenceSteps(
  config: StageConfig,
  presetType: 't2i' | 'i2i'
): number | undefined {
  const scopedSteps = presetType === 'i2i'
    ? config.imageWan2gpInferenceStepsI2i
    : config.imageWan2gpInferenceStepsT2i
  if (typeof scopedSteps === 'number' && scopedSteps > 0) return scopedSteps
  if (typeof config.imageWan2gpInferenceSteps === 'number' && config.imageWan2gpInferenceSteps > 0) {
    return config.imageWan2gpInferenceSteps
  }
  return undefined
}

interface ReferenceVoiceFields {
  voice_audio_provider?: 'edge_tts' | 'wan2gp' | 'volcengine_tts' | 'kling_tts' | 'vidu_tts' | 'minimax_tts' | 'xiaomi_mimo_tts'
  voice_name?: string
  voice_speed?: number
  voice_wan2gp_preset?: string
  voice_wan2gp_alt_prompt?: string
  voice_wan2gp_audio_guide?: string
  voice_wan2gp_temperature?: number
  voice_wan2gp_top_k?: number
  voice_wan2gp_seed?: number
}

export function buildStageInputData(params: {
  stage: BackendStageType
  config?: StageConfig
  settings?: Settings
  inputData?: Record<string, unknown>
  stageData?: {
    content?: {
      roles?: Array<{
        id?: string
      }>
    }
    storyboard?: {
      shots?: Array<{
        speaker_id?: string
      }>
      references?: Array<{
        id?: string | number
        name?: string
        setting?: string
        can_speak?: boolean
      } & ReferenceVoiceFields>
    }
    reference?: {
      references?: Array<{
        id?: string | number
        name?: string
        setting?: string
        can_speak?: boolean
      } & ReferenceVoiceFields>
    }
  }
}): Record<string, unknown> {
  const { stage, config, settings, inputData, stageData } = params
  const mergedInputData: Record<string, unknown> = { ...(inputData || {}) }

  if (!config) {
    return mergedInputData
  }

  const isSingleTake = (config.singleTake ?? false) || config.scriptMode === 'duo_podcast'
  const effectiveUseFirstFrameRef = isSingleTake ? true : config.useFirstFrameRef

  if (['content', 'storyboard', 'first_frame_desc', 'reference', 'research'].includes(stage)) {
    if (stage === 'content' && config.scriptMode) {
      mergedInputData.script_mode = config.scriptMode
    }
    if (stage === 'content') {
      const scriptMode = String(mergedInputData.script_mode || config.scriptMode || '').trim() || 'single'
      if (scriptMode === 'single') {
        const narratorReference = stageData?.reference?.references?.[0]
        if (narratorReference) {
          const narratorReferenceId = String(narratorReference.id || '').trim()
          const narratorPresetSetting = resolveNarratorPresetSettingByMode('single', config.style, 0)
          const narratorPresetName = resolveNarratorPresetNameByMode('single', config.style, 0)
          const narratorSettingRaw = String(narratorReference.setting || '').trim()
          const narratorSetting = narratorPresetSetting
            ? narratorPresetSetting
            : (
              isNarratorPresetSettingTextByMode('single', narratorSettingRaw)
                ? ''
                : narratorSettingRaw
            )
          mergedInputData.roles = [{
            id: narratorReferenceId || SINGLE_ROLE_ID,
            name: String(narratorReference.name || '').trim()
              || narratorPresetName
              || resolveNarratorCustomNameByMode('single', 0)
              || SINGLE_ROLE_NAME,
            description: narratorSetting,
          }]
        }
      } else if (scriptMode === 'duo_podcast') {
        const roleRefs = (stageData?.reference?.references || []).slice(0, 2)
        const roles: Array<{
          id: string
          name: string
          description: string
        }> = []

        roleRefs.forEach((reference, index) => {
          const referenceId = String(reference.id || '').trim()
          const presetSetting = resolveNarratorPresetSettingByMode('duo_podcast', config.style, index)
          const presetName = resolveNarratorPresetNameByMode('duo_podcast', config.style, index)
          const settingRaw = String(reference.setting || '').trim()
          const setting = presetSetting
            ? presetSetting
            : (
              isNarratorPresetSettingTextByMode('duo_podcast', settingRaw)
                ? ''
                : settingRaw
            )
          roles.push({
            id: referenceId || (index === 0 ? DUO_ROLE_1_ID : DUO_ROLE_2_ID),
            name: String(reference.name || '').trim()
              || presetName
              || resolveNarratorCustomNameByMode('duo_podcast', index)
              || (index === 0 ? DUO_ROLE_1_NAME : DUO_ROLE_2_NAME),
            description: setting,
          })
        })
        const sceneReference = (stageData?.reference?.references || [])[2]
        if (sceneReference) {
          roles.push({
            id: String(sceneReference.id || '').trim() || DUO_SCENE_ROLE_ID,
            name: String(sceneReference.name || '').trim() || '播客场景',
            description: String(sceneReference.setting || '').trim(),
          })
        }
        if (roles.length > 0) {
          mergedInputData.roles = roles
        }
      } else if (scriptMode === 'dialogue_script') {
        const roleRefs = stageData?.reference?.references || []
        const narratorAliases = new Set(['narrator', '画外音', '旁白', 'vo', 'voiceover', 'voice_over'])
        const roles: Array<{
          id: string
          name: string
          description: string
        }> = []

        roleRefs.forEach((reference) => {
          if (reference.can_speak === false) return
          const referenceId = String(reference.id || '').trim()
          if (!referenceId) return
          const referenceName = String(reference.name || '').trim()
          const lowerName = referenceName.toLowerCase()
          const isNarrator = narratorAliases.has(lowerName)
          const roleId = referenceId
          const roleName = referenceName || (isNarrator ? '画外音' : `角色${roles.length + 1}`)
          const roleDescription = String(reference.setting || '').trim()
          roles.push({
            id: roleId,
            name: roleName,
            description: roleDescription,
          })
        })

        if (roles.length > 0) {
          mergedInputData.roles = roles
        }
      }
    }
    const llmSelection = resolveEffectiveLlmSelection(config, settings)
    if (llmSelection.providerId) mergedInputData.llm_provider = llmSelection.providerId
    if (llmSelection.modelId) mergedInputData.llm_model = llmSelection.modelId
    if (
      (stage === 'storyboard' || stage === 'first_frame_desc')
      && config.textTargetLanguage
    ) {
      mergedInputData.target_language = config.textTargetLanguage
    }
    if (
      (stage === 'storyboard' || stage === 'first_frame_desc')
      && config.textPromptComplexity
    ) {
      mergedInputData.prompt_complexity = config.textPromptComplexity
    }
    if (stage === 'storyboard' || stage === 'first_frame_desc') {
      mergedInputData.single_take = isSingleTake
    }
    if (stage === 'storyboard') {
      if (config.storyboardShotDensity) {
        mergedInputData.storyboard_shot_density = config.storyboardShotDensity
      }
      const videoModelMode: 't2v' | 'i2v' = effectiveUseFirstFrameRef ? 'i2v' : 't2v'
      const preferredVideoProvider = config.videoProvider
        || resolveDefaultVideoProviderByMode(settings, videoModelMode)
      const videoProvider = resolveVideoProvider(preferredVideoProvider, settings)
      if (videoProvider) mergedInputData.video_provider = videoProvider
      if (videoProvider === 'wan2gp') {
        const videoT2vPreset = config.videoWan2gpT2vPreset || settings?.video_wan2gp_t2v_preset
        const videoI2vPreset = config.videoWan2gpI2vPreset || settings?.video_wan2gp_i2v_preset
        const videoResolution = config.videoWan2gpResolution || settings?.video_wan2gp_resolution
        if (videoT2vPreset) mergedInputData.video_wan2gp_t2v_preset = videoT2vPreset
        if (videoI2vPreset) mergedInputData.video_wan2gp_i2v_preset = videoI2vPreset
        if (videoResolution) mergedInputData.video_wan2gp_resolution = videoResolution
        if (
          typeof config.videoWan2gpSlidingWindowSize === 'number'
          && config.videoWan2gpSlidingWindowSize > 0
        ) {
          mergedInputData.video_wan2gp_sliding_window_size = config.videoWan2gpSlidingWindowSize
        }
        delete mergedInputData.video_model
      } else {
        const preferredVideoModel = String(
          videoModelMode === 'i2v'
            ? (config.videoModelI2v || '')
            : (config.videoModel || '')
        ).trim()
        const fallbackVideoModel = String(
          settings ? getVideoModelByProvider(videoProvider, settings, videoModelMode) : ''
        ).trim()
        const resolvedModel = isSingleTake
          ? resolveSingleTakeVideoModel({
              provider: videoProvider,
              preferredModel: preferredVideoModel || fallbackVideoModel,
              settings,
              mode: videoModelMode,
            })
          : (preferredVideoModel || fallbackVideoModel || undefined)
        if (resolvedModel) mergedInputData.video_model = resolvedModel
      }
      if (config.videoAspectRatio) mergedInputData.video_aspect_ratio = config.videoAspectRatio
      if (videoProvider !== 'wan2gp' && config.resolution) mergedInputData.resolution = config.resolution
      if (config.videoWan2gpResolution) {
        mergedInputData.video_wan2gp_resolution = config.videoWan2gpResolution
      }
      if (effectiveUseFirstFrameRef !== undefined) {
        mergedInputData.use_first_frame_ref = effectiveUseFirstFrameRef
      }
      if (config.useReferenceImageRef !== undefined) {
        mergedInputData.use_reference_image_ref = config.useReferenceImageRef
      }
    }
  }

  if (stage === 'reference') {
    const imageProvider = config.imageProvider || settings?.default_image_provider
    if (imageProvider) mergedInputData.image_provider = imageProvider
    if (imageProvider === 'wan2gp') {
      const imageResolution = config.referenceImageResolution || settings?.image_wan2gp_reference_resolution
      const imagePreset = config.imageWan2gpPreset || settings?.image_wan2gp_preset
      const inferenceSteps = getScopedWan2gpInferenceSteps(config, 't2i')
      if (imageResolution) mergedInputData.image_resolution = imageResolution
      if (imagePreset) mergedInputData.image_wan2gp_preset = imagePreset
      if (inferenceSteps) mergedInputData.image_wan2gp_inference_steps = inferenceSteps
      mergedInputData.max_concurrency = 1
    } else {
      const resolvedImageModel = String(
        config.imageModel || (settings ? getImageModel(imageProvider, settings, 't2i') : '')
      ).trim()
      if (resolvedImageModel) mergedInputData.image_model = resolvedImageModel
      if (config.referenceAspectRatio) mergedInputData.image_aspect_ratio = config.referenceAspectRatio
      if (config.referenceImageSize) mergedInputData.image_size = config.referenceImageSize
      if (config.maxConcurrency) mergedInputData.max_concurrency = config.maxConcurrency
    }
    if (config.imageStyle?.trim()) mergedInputData.image_style = config.imageStyle.trim()
    if (config.textTargetLanguage) mergedInputData.target_language = config.textTargetLanguage
    if (config.textPromptComplexity) mergedInputData.prompt_complexity = config.textPromptComplexity
  }

  if (stage === 'frame') {
    mergedInputData.single_take = isSingleTake
    const imageProvider = config.imageProvider || settings?.default_image_provider
    if (imageProvider) mergedInputData.image_provider = imageProvider
    if (imageProvider === 'wan2gp') {
      const imageResolution = config.frameImageResolution || settings?.image_wan2gp_frame_resolution
      const useReferenceConsistency = config.useReferenceConsistency ?? false
      const imagePreset = useReferenceConsistency
        ? (config.imageWan2gpPresetI2i || settings?.image_wan2gp_preset_i2i || settings?.image_wan2gp_preset)
        : (config.imageWan2gpPreset || settings?.image_wan2gp_preset)
      const inferenceSteps = getScopedWan2gpInferenceSteps(config, useReferenceConsistency ? 'i2i' : 't2i')
      if (imageResolution) mergedInputData.image_resolution = imageResolution
      if (imagePreset) mergedInputData.image_wan2gp_preset = imagePreset
      if (inferenceSteps) mergedInputData.image_wan2gp_inference_steps = inferenceSteps
      mergedInputData.max_concurrency = 1
    } else {
      const imageModelMode = (config.useReferenceConsistency ?? false) ? 'i2i' : 't2i'
      const resolvedImageModel = String(
        config.frameImageModel
          || config.imageModel
          || (settings ? getImageModel(imageProvider, settings, imageModelMode) : '')
      ).trim()
      if (resolvedImageModel) mergedInputData.image_model = resolvedImageModel
      if (config.frameAspectRatio) mergedInputData.image_aspect_ratio = config.frameAspectRatio
      if (config.frameImageSize) mergedInputData.image_size = config.frameImageSize
      if (config.maxConcurrency) mergedInputData.max_concurrency = config.maxConcurrency
    }
    if (config.imageStyle?.trim()) mergedInputData.image_style = config.imageStyle.trim()
  }

  if (stage === 'frame' || stage === 'first_frame_desc') {
    mergedInputData.single_take = isSingleTake
    if (config.useReferenceConsistency !== undefined) {
      mergedInputData.use_reference_consistency = config.useReferenceConsistency
    }
  }

  if (stage === 'audio') {
    if (config.scriptMode) mergedInputData.script_mode = config.scriptMode
    const normalizeAudioProvider = (value: unknown): 'edge_tts' | 'wan2gp' | 'volcengine_tts' | 'kling_tts' | 'vidu_tts' | 'minimax_tts' | 'xiaomi_mimo_tts' => {
      const provider = String(value || '').trim().toLowerCase()
      if (provider === 'wan2gp') return 'wan2gp'
      if (provider === 'volcengine_tts') return 'volcengine_tts'
      if (provider === 'kling_tts') return 'kling_tts'
      if (provider === 'vidu_tts') return 'vidu_tts'
      if (provider === 'minimax_tts') return 'minimax_tts'
      if (provider === 'xiaomi_mimo_tts') return 'xiaomi_mimo_tts'
      return 'edge_tts'
    }
    const fallbackAudioProvider = normalizeAudioProvider(
      config.audioProvider || settings?.default_audio_provider || 'edge_tts'
    )
    const toFiniteNumber = (value: unknown): number | undefined => {
      if (typeof value !== 'number') return undefined
      if (!Number.isFinite(value)) return undefined
      return value
    }
    const resolveProviderDefaultSpeed = (
      provider: 'edge_tts' | 'wan2gp' | 'volcengine_tts' | 'kling_tts' | 'vidu_tts' | 'minimax_tts' | 'xiaomi_mimo_tts'
    ): number | undefined => {
      if (provider === 'edge_tts') {
        return rateToSpeed(String(settings?.edge_tts_rate || '+30%'))
      }
      if (provider === 'wan2gp') {
        return toFiniteNumber(settings?.audio_wan2gp_speed)
      }
      if (provider === 'volcengine_tts') {
        return toFiniteNumber(settings?.audio_volcengine_tts_speed_ratio)
      }
      if (provider === 'kling_tts') {
        return toFiniteNumber(settings?.audio_kling_voice_speed)
      }
      if (provider === 'vidu_tts') {
        return toFiniteNumber(settings?.audio_vidu_speed)
      }
      if (provider === 'minimax_tts') {
        return toFiniteNumber(settings?.audio_minimax_speed)
      }
      return 1.0
    }

    const roleConfigsFromReferences: Record<string, Record<string, unknown>> = {}
    const referenceList = stageData?.reference?.references || stageData?.storyboard?.references || []
    const referenceById = new Map(
      referenceList
        .map((item) => [String(item.id || '').trim(), item] as const)
        .filter((item): item is [string, {
          id?: string | number
          can_speak?: boolean
        } & ReferenceVoiceFields] => !!item[0])
    )
    const scriptModeForAudio = String(
      mergedInputData.script_mode || config.scriptMode || 'single'
    ).trim() || 'single'
    const speakerIds = Array.from(new Set(
      [
        ...(stageData?.storyboard?.shots || [])
        .map((shot) => String(shot.speaker_id || '').trim())
        .filter((speakerId) => !!speakerId),
        ...(stageData?.content?.roles || [])
          .map((role) => String(role.id || '').trim())
          .filter((speakerId) => !!speakerId),
        ...(scriptModeForAudio === 'single' ? [String(referenceList[0]?.id || SINGLE_ROLE_ID).trim()] : []),
      ]
    ))
    for (const speakerId of speakerIds) {
      const directReference = referenceById.get(speakerId)
      const matchedReference = directReference
      if (!matchedReference || matchedReference.can_speak === false) continue
      const provider = normalizeAudioProvider(matchedReference.voice_audio_provider)
      const voiceName = String(matchedReference.voice_name || '').trim()
      const referenceVoiceSpeed = toFiniteNumber(matchedReference.voice_speed)
      if (provider === 'wan2gp') {
        const preset = String(
          matchedReference.voice_wan2gp_preset
          || config.audioWan2gpPreset
          || settings?.audio_wan2gp_preset
          || 'qwen3_tts_base'
        ).trim() || 'qwen3_tts_base'
        roleConfigsFromReferences[speakerId] = {
          audioProvider: 'wan2gp',
          audioWan2gpPreset: preset,
          audioWan2gpModelMode: resolveWan2gpAudioMode(
            preset,
            voiceName || config.audioWan2gpModelMode || settings?.audio_wan2gp_model_mode
          ),
        }
        if (referenceVoiceSpeed !== undefined) {
          roleConfigsFromReferences[speakerId].speed = referenceVoiceSpeed
        }
        if (matchedReference.voice_wan2gp_alt_prompt !== undefined) {
          roleConfigsFromReferences[speakerId].audioWan2gpAltPrompt = matchedReference.voice_wan2gp_alt_prompt
        }
        if (matchedReference.voice_wan2gp_audio_guide !== undefined) {
          roleConfigsFromReferences[speakerId].audioWan2gpAudioGuide = matchedReference.voice_wan2gp_audio_guide
        }
        if (
          typeof matchedReference.voice_wan2gp_temperature === 'number'
          && Number.isFinite(matchedReference.voice_wan2gp_temperature)
        ) {
          roleConfigsFromReferences[speakerId].audioWan2gpTemperature = matchedReference.voice_wan2gp_temperature
        }
        if (
          typeof matchedReference.voice_wan2gp_top_k === 'number'
          && Number.isFinite(matchedReference.voice_wan2gp_top_k)
        ) {
          roleConfigsFromReferences[speakerId].audioWan2gpTopK = Math.trunc(matchedReference.voice_wan2gp_top_k)
        }
        if (
          typeof matchedReference.voice_wan2gp_seed === 'number'
          && Number.isFinite(matchedReference.voice_wan2gp_seed)
        ) {
          roleConfigsFromReferences[speakerId].audioWan2gpSeed = Math.trunc(matchedReference.voice_wan2gp_seed)
        }
      } else {
        const fallbackVoice = provider === 'volcengine_tts'
          ? String(settings?.audio_volcengine_tts_voice_type || '').trim()
          : (
            provider === 'kling_tts'
              ? String(settings?.audio_kling_voice_id || '').trim()
              : (
                provider === 'vidu_tts'
                  ? String(settings?.audio_vidu_voice_id || '').trim()
                  : provider === 'minimax_tts'
                    ? String(settings?.audio_minimax_voice_id || '').trim()
                  : provider === 'xiaomi_mimo_tts'
                    ? String(settings?.audio_xiaomi_mimo_voice || '').trim()
                  : String(settings?.edge_tts_voice || '').trim()
              )
          )
        const resolvedVoice = voiceName || fallbackVoice
        if (!resolvedVoice) continue
        roleConfigsFromReferences[speakerId] = {
          audioProvider: provider,
          voice: resolvedVoice,
        }
        if (referenceVoiceSpeed !== undefined) {
          roleConfigsFromReferences[speakerId].speed = referenceVoiceSpeed
        }
      }
    }
    const roleConfigs = {
      ...(config.audioRoleConfigs || {}),
      ...roleConfigsFromReferences,
    }
    const normalizedRoleConfigs: Record<string, Record<string, unknown>> = {}
    for (const [roleId, rawRoleConfig] of Object.entries(roleConfigs)) {
      const normalizedRoleId = String(roleId || '').trim()
      if (!normalizedRoleId || !rawRoleConfig || typeof rawRoleConfig !== 'object') continue
      const roleConfig = rawRoleConfig
      const roleProvider = normalizeAudioProvider(
        (roleConfig as { audioProvider?: string }).audioProvider || fallbackAudioProvider
      )

      if (roleProvider === 'wan2gp') {
        const rolePreset = String(
          (roleConfig as { audioWan2gpPreset?: string }).audioWan2gpPreset
          || config.audioWan2gpPreset
          || settings?.audio_wan2gp_preset
          || 'qwen3_tts_base'
        ).trim() || 'qwen3_tts_base'
        const roleModelMode = resolveWan2gpAudioMode(
          rolePreset,
          (roleConfig as { audioWan2gpModelMode?: string }).audioWan2gpModelMode
          || config.audioWan2gpModelMode
          || settings?.audio_wan2gp_model_mode
        )
        const roleAltPrompt = (
          (roleConfig as { audioWan2gpAltPrompt?: string }).audioWan2gpAltPrompt
          ?? config.audioWan2gpAltPrompt
          ?? settings?.audio_wan2gp_alt_prompt
          ?? ''
        )
        const roleAudioGuide = (
          (roleConfig as { audioWan2gpAudioGuide?: string }).audioWan2gpAudioGuide
          ?? config.audioWan2gpAudioGuide
          ?? settings?.audio_wan2gp_audio_guide
          ?? ''
        )
        const roleSpeed = toFiniteNumber(
          (roleConfig as { speed?: number }).speed
        ) ?? toFiniteNumber(config.speed) ?? settings?.audio_wan2gp_speed
        const roleDurationSeconds = (
          (roleConfig as { audioWan2gpDurationSeconds?: number }).audioWan2gpDurationSeconds
          ?? config.audioWan2gpDurationSeconds
          ?? settings?.audio_wan2gp_duration_seconds
        )
        const roleTemperature = (
          (roleConfig as { audioWan2gpTemperature?: number }).audioWan2gpTemperature
          ?? config.audioWan2gpTemperature
          ?? settings?.audio_wan2gp_temperature
        )
        const roleTopK = (
          (roleConfig as { audioWan2gpTopK?: number }).audioWan2gpTopK
          ?? config.audioWan2gpTopK
          ?? settings?.audio_wan2gp_top_k
        )
        const roleSeed = (
          (roleConfig as { audioWan2gpSeed?: number }).audioWan2gpSeed
          ?? config.audioWan2gpSeed
          ?? settings?.audio_wan2gp_seed
        )

        normalizedRoleConfigs[normalizedRoleId] = {
          audio_provider: 'wan2gp',
          audio_wan2gp_preset: rolePreset,
          audio_wan2gp_model_mode: roleModelMode,
          audio_wan2gp_alt_prompt: roleAltPrompt,
          audio_wan2gp_audio_guide: roleAudioGuide,
        }
        if (typeof roleDurationSeconds === 'number' && Number.isFinite(roleDurationSeconds)) {
          normalizedRoleConfigs[normalizedRoleId].audio_wan2gp_duration_seconds = roleDurationSeconds
        }
        if (typeof roleTemperature === 'number' && Number.isFinite(roleTemperature)) {
          normalizedRoleConfigs[normalizedRoleId].audio_wan2gp_temperature = roleTemperature
        }
        if (typeof roleTopK === 'number' && Number.isFinite(roleTopK)) {
          normalizedRoleConfigs[normalizedRoleId].audio_wan2gp_top_k = roleTopK
        }
        if (typeof roleSeed === 'number' && Number.isFinite(roleSeed)) {
          normalizedRoleConfigs[normalizedRoleId].audio_wan2gp_seed = roleSeed
        }
        if (typeof roleSpeed === 'number' && Number.isFinite(roleSpeed)) {
          normalizedRoleConfigs[normalizedRoleId].speed = roleSpeed
        }
        continue
      }

      const roleVoice = String(
        (roleConfig as { voice?: string }).voice
        || (
          roleProvider === 'volcengine_tts'
            ? settings?.audio_volcengine_tts_voice_type
            : (
              roleProvider === 'kling_tts'
                ? (settings?.audio_kling_voice_id || config.voice)
                : (
                  roleProvider === 'vidu_tts'
                    ? (settings?.audio_vidu_voice_id || config.voice)
                    : roleProvider === 'minimax_tts'
                      ? (settings?.audio_minimax_voice_id || config.voice)
                    : (config.voice || settings?.edge_tts_voice)
                )
            )
        )
        || ''
      ).trim()
      const roleSpeed = toFiniteNumber(
        (roleConfig as { speed?: number }).speed
      ) ?? toFiniteNumber(config.speed) ?? resolveProviderDefaultSpeed(roleProvider)
      normalizedRoleConfigs[normalizedRoleId] = {
        audio_provider: roleProvider,
      }
      if (roleVoice) normalizedRoleConfigs[normalizedRoleId].voice = roleVoice
      if (typeof roleSpeed === 'number' && Number.isFinite(roleSpeed)) {
        normalizedRoleConfigs[normalizedRoleId].speed = roleSpeed
      }
    }

    const roleProviders = Object.values(normalizedRoleConfigs)
      .map((item) => item.audio_provider)
      .filter((provider): provider is 'wan2gp' | 'edge_tts' | 'volcengine_tts' | 'kling_tts' | 'vidu_tts' | 'minimax_tts' | 'xiaomi_mimo_tts' => (
        provider === 'wan2gp'
        || provider === 'edge_tts'
        || provider === 'volcengine_tts'
        || provider === 'kling_tts'
        || provider === 'vidu_tts'
        || provider === 'minimax_tts'
        || provider === 'xiaomi_mimo_tts'
      ))
    const audioProvider = roleProviders.length === 0
      ? fallbackAudioProvider
      : (roleProviders.every((provider) => provider === roleProviders[0]) ? roleProviders[0] : fallbackAudioProvider)
    mergedInputData.audio_provider = audioProvider
    if (Object.keys(normalizedRoleConfigs).length > 0) {
      mergedInputData.audio_role_configs = normalizedRoleConfigs
    }

    if (audioProvider === 'wan2gp') {
      const audioPreset = config.audioWan2gpPreset || settings?.audio_wan2gp_preset
      const audioAltPrompt = config.audioWan2gpAltPrompt ?? settings?.audio_wan2gp_alt_prompt
      const audioGuide = config.audioWan2gpAudioGuide ?? settings?.audio_wan2gp_audio_guide
      const effectivePreset = audioPreset || 'qwen3_tts_base'
      if (effectivePreset) mergedInputData.audio_wan2gp_preset = effectivePreset
      if (audioAltPrompt !== undefined) mergedInputData.audio_wan2gp_alt_prompt = audioAltPrompt
      const audioModelMode = resolveWan2gpAudioMode(
        effectivePreset,
        config.audioWan2gpModelMode || settings?.audio_wan2gp_model_mode
      )
      if (audioModelMode !== undefined) mergedInputData.audio_wan2gp_model_mode = audioModelMode
      if (effectivePreset === 'qwen3_tts_base' && audioGuide !== undefined) {
        mergedInputData.audio_wan2gp_audio_guide = audioGuide
      }
      if (typeof config.speed === 'number' && Number.isFinite(config.speed)) {
        mergedInputData.speed = config.speed
      }
    } else if (audioProvider === 'volcengine_tts') {
      const defaultVolcVoice = 'zh_female_vv_uranus_bigtts'
      const volcVoice = String(
        settings?.audio_volcengine_tts_voice_type
        || config.voice
        || defaultVolcVoice
      ).trim() || defaultVolcVoice
      mergedInputData.voice = volcVoice
      mergedInputData.audio_volcengine_tts_voice_type = volcVoice
      mergedInputData.volcengine_tts_model_name = settings?.volcengine_tts_model_name || 'seed-tts-2.0'
      mergedInputData.audio_volcengine_tts_speed_ratio = settings?.audio_volcengine_tts_speed_ratio ?? 1.0
      mergedInputData.audio_volcengine_tts_volume_ratio = 1.0
      mergedInputData.audio_volcengine_tts_pitch_ratio = 1.0
      mergedInputData.audio_volcengine_tts_encoding = 'mp3'
      if (typeof config.speed === 'number' && Number.isFinite(config.speed)) {
        mergedInputData.speed = config.speed
        mergedInputData.audio_volcengine_tts_speed_ratio = config.speed
      }
    } else if (audioProvider === 'kling_tts') {
      const klingVoice = String(
        settings?.audio_kling_voice_id
        || config.voice
        || 'zh_male_qn_qingse'
      ).trim() || 'zh_male_qn_qingse'
      mergedInputData.voice = klingVoice
      mergedInputData.audio_kling_voice_id = klingVoice
      mergedInputData.audio_kling_voice_language = String(
        settings?.audio_kling_voice_language || 'zh'
      ).trim() || 'zh'
      if (typeof config.speed === 'number' && Number.isFinite(config.speed)) {
        mergedInputData.speed = config.speed
        mergedInputData.audio_kling_voice_speed = config.speed
      }
    } else if (audioProvider === 'vidu_tts') {
      const viduVoice = String(
        settings?.audio_vidu_voice_id
        || config.voice
        || 'female-shaonv'
      ).trim() || 'female-shaonv'
      mergedInputData.voice = viduVoice
      mergedInputData.audio_vidu_voice_id = viduVoice
      mergedInputData.audio_vidu_speed = settings?.audio_vidu_speed ?? 1.0
      mergedInputData.audio_vidu_volume = settings?.audio_vidu_volume ?? 1.0
      mergedInputData.audio_vidu_pitch = settings?.audio_vidu_pitch ?? 0.0
      mergedInputData.audio_vidu_emotion = settings?.audio_vidu_emotion ?? ''
      if (typeof config.speed === 'number' && Number.isFinite(config.speed)) {
        mergedInputData.speed = config.speed
        mergedInputData.audio_vidu_speed = config.speed
      }
    } else if (audioProvider === 'minimax_tts') {
      const minimaxVoice = String(
        settings?.audio_minimax_voice_id
        || config.voice
        || 'Chinese (Mandarin)_Reliable_Executive'
      ).trim() || 'Chinese (Mandarin)_Reliable_Executive'
      mergedInputData.voice = minimaxVoice
      mergedInputData.audio_minimax_voice_id = minimaxVoice
      mergedInputData.audio_minimax_model = settings?.audio_minimax_model || 'speech-2.8-turbo'
      mergedInputData.audio_minimax_speed = settings?.audio_minimax_speed ?? 1.0
      if (typeof config.speed === 'number' && Number.isFinite(config.speed)) {
        mergedInputData.speed = config.speed
        mergedInputData.audio_minimax_speed = config.speed
      }
    } else if (audioProvider === 'xiaomi_mimo_tts') {
      const xiaomiVoice = String(
        settings?.audio_xiaomi_mimo_voice
        || config.voice
        || 'mimo_default'
      ).trim() || 'mimo_default'
      mergedInputData.voice = xiaomiVoice
      mergedInputData.audio_xiaomi_mimo_voice = xiaomiVoice
      mergedInputData.audio_xiaomi_mimo_style_preset = settings?.audio_xiaomi_mimo_style_preset ?? ''
      mergedInputData.audio_xiaomi_mimo_speed = settings?.audio_xiaomi_mimo_speed ?? 1.0
      if (typeof config.speed === 'number' && Number.isFinite(config.speed)) {
        mergedInputData.speed = config.speed
        mergedInputData.audio_xiaomi_mimo_speed = config.speed
      }
    } else {
      if (config.voice) mergedInputData.voice = config.voice
      if (typeof config.speed === 'number' && Number.isFinite(config.speed)) {
        mergedInputData.speed = config.speed
      }
    }
    mergedInputData.max_concurrency = 1
  }

  if (stage === 'video') {
    mergedInputData.single_take = isSingleTake
    const videoModelMode: 't2v' | 'i2v' = effectiveUseFirstFrameRef ? 'i2v' : 't2v'
    const preferredVideoProvider = config.videoProvider
      || resolveDefaultVideoProviderByMode(settings, videoModelMode)
    const videoProvider = resolveVideoProvider(preferredVideoProvider, settings)
    mergedInputData.video_provider = videoProvider
    if (videoProvider === 'wan2gp') {
      const videoT2vPreset = config.videoWan2gpT2vPreset || settings?.video_wan2gp_t2v_preset
      const videoI2vPreset = config.videoWan2gpI2vPreset || settings?.video_wan2gp_i2v_preset
      const videoResolution = config.videoWan2gpResolution || settings?.video_wan2gp_resolution
      if (videoT2vPreset) mergedInputData.video_wan2gp_t2v_preset = videoT2vPreset
      if (videoI2vPreset) mergedInputData.video_wan2gp_i2v_preset = videoI2vPreset
      if (videoResolution) mergedInputData.video_wan2gp_resolution = videoResolution
      if (config.videoWan2gpInferenceSteps && config.videoWan2gpInferenceSteps > 0) {
        mergedInputData.video_wan2gp_inference_steps = config.videoWan2gpInferenceSteps
      }
      if (
        typeof config.videoWan2gpSlidingWindowSize === 'number'
        && config.videoWan2gpSlidingWindowSize > 0
      ) {
        mergedInputData.video_wan2gp_sliding_window_size = config.videoWan2gpSlidingWindowSize
      }
      mergedInputData.max_concurrency = 1
    } else {
      const preferredVideoModel = String(
        videoModelMode === 'i2v'
          ? (config.videoModelI2v || '')
          : (config.videoModel || '')
      ).trim()
      const fallbackVideoModel = String(
        settings ? getVideoModelByProvider(videoProvider, settings, videoModelMode) : ''
      ).trim()
      const resolvedModel = isSingleTake
        ? resolveSingleTakeVideoModel({
            provider: videoProvider,
            preferredModel: preferredVideoModel || fallbackVideoModel,
            settings,
            mode: videoModelMode,
          })
        : (preferredVideoModel || fallbackVideoModel || undefined)
      if (resolvedModel) mergedInputData.video_model = resolvedModel
      if (config.videoAspectRatio) mergedInputData.video_aspect_ratio = config.videoAspectRatio
      if (config.resolution) mergedInputData.resolution = config.resolution
      if (
        typeof config.maxConcurrency === 'number'
        && Number.isFinite(config.maxConcurrency)
        && config.maxConcurrency > 0
      ) {
        mergedInputData.max_concurrency = Math.max(1, Math.floor(config.maxConcurrency))
      }
    }
    if (effectiveUseFirstFrameRef !== undefined) {
      mergedInputData.use_first_frame_ref = effectiveUseFirstFrameRef
    }
    if (config.useReferenceImageRef !== undefined) {
      mergedInputData.use_reference_image_ref = config.useReferenceImageRef
    }
  }

  if (['compose', 'subtitle', 'burn_subtitle', 'finalize'].includes(stage)) {
    mergedInputData.single_take = isSingleTake
    if (config.composeCanvasStrategy) {
      mergedInputData.concat_canvas_strategy = config.composeCanvasStrategy
    }
    const normalizedComposeAspectRatio = config.composeFixedAspectRatio || '9:16'
    const normalizedComposeResolution = parseComposeResolution(config.composeFixedResolution)
      ? config.composeFixedResolution
      : (getComposeFixedResolutionOptions(normalizedComposeAspectRatio)[0]?.value || '1080x1920')
    if (normalizedComposeAspectRatio) {
      mergedInputData.concat_target_aspect_ratio = normalizedComposeAspectRatio
    }
    if (normalizedComposeResolution) {
      mergedInputData.concat_target_resolution = normalizedComposeResolution
    }
    if (config.includeSubtitle !== undefined) {
      mergedInputData.include_subtitle = config.includeSubtitle
    }
    if (config.subtitleFontSize) mergedInputData.subtitle_font_size = config.subtitleFontSize
    if (
      typeof config.subtitlePositionPercent === 'number'
      && Number.isFinite(config.subtitlePositionPercent)
    ) {
      mergedInputData.subtitle_position_percent = config.subtitlePositionPercent
    }
    if (isSingleTake) {
      mergedInputData.video_fit_mode = 'scale'
    } else if (config.videoFitMode) {
      mergedInputData.video_fit_mode = config.videoFitMode
    }
  }

  return mergedInputData
}
