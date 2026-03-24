'use client'

import { Loader2, Mic } from 'lucide-react'

import { SecretInput } from '@/components/settings/secret-input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { Settings, SettingsUpdate } from '@/types/settings'
import { RuntimeValidationBadge } from './settings-runtime-validation-badge'

const VOLCENGINE_MODEL_OPTIONS = [
  { value: 'volc.seedasr.auc', label: '豆包录音文件识别模型 2.0' },
  { value: 'volc.bigasr.auc', label: '豆包录音文件识别模型 1.0' },
]

interface SettingsSpeechRecognitionSectionProps {
  settings: Settings | undefined
  formData: SettingsUpdate
  updateField: <K extends keyof SettingsUpdate>(key: K, value: SettingsUpdate[K]) => void
  showApiKeys: Record<string, boolean>
  onToggleApiKey: (key: string) => void
  selectedFasterWhisperModel: string
  fasterWhisperModelOptions: readonly string[]
  onTestFasterWhisper: () => void
  isTestingFasterWhisper: boolean
  onTestVolcengineSpeechRecognition: () => void
  isTestingVolcengineSpeechRecognition: boolean
}

export function SettingsSpeechRecognitionSection(props: SettingsSpeechRecognitionSectionProps) {
  const {
    settings,
    formData,
    updateField,
    showApiKeys,
    onToggleApiKey,
    selectedFasterWhisperModel,
    fasterWhisperModelOptions,
    onTestFasterWhisper,
    isTestingFasterWhisper,
    onTestVolcengineSpeechRecognition,
    isTestingVolcengineSpeechRecognition,
  } = props
  const deploymentProfile = (formData.deployment_profile ?? settings?.deployment_profile ?? 'cpu')
    .trim()
    .toLowerCase()

  const speechVolcengineAppKey = formData.speech_volcengine_app_key ?? settings?.speech_volcengine_app_key ?? ''
  const speechVolcengineAccessKey = formData.speech_volcengine_access_key ?? settings?.speech_volcengine_access_key ?? ''
  const speechVolcengineResourceId = formData.speech_volcengine_resource_id
    ?? settings?.speech_volcengine_resource_id
    ?? 'volc.seedasr.auc'

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Mic className="h-5 w-5" />
          语音识别
        </CardTitle>
        <CardDescription>用于音频切分/字幕对齐、语音库导入转写、外部视频链接导入转写</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-3 rounded-lg border p-3">
          <div className="flex items-center gap-2 flex-wrap">
            <div className="font-medium">fast-whisper</div>
            <Badge variant="outline">本地</Badge>
            <RuntimeValidationBadge status={settings?.faster_whisper_validation_status} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="faster_whisper_model">模型</Label>
            <Select
              value={selectedFasterWhisperModel}
              onValueChange={(v) => updateField('faster_whisper_model', v)}
            >
              <SelectTrigger id="faster_whisper_model">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {fasterWhisperModelOptions.map((model) => (
                  <SelectItem key={model} value={model}>
                    {model}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="space-y-1 text-xs text-muted-foreground">
              {deploymentProfile === 'gpu' ? (
                <p>GPU 模式下使用“本地模型依赖”中的共享 Python 路径。不同显卡、CUDA 与 CTranslate2 组合的兼容性差异较大；如需排查 GPU 环境，请参考
                  <a
                    href="https://github.com/SYSTRAN/faster-whisper"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="ml-1 text-primary underline underline-offset-2"
                  >
                    faster-whisper 官方说明
                  </a>
                  。
                </p>
              ) : (
                <p>CPU 模式下由后端主 uv 环境统一管理，无需额外配置“本地模型依赖”中的共享 Python 路径。</p>
              )}
            </div>
          </div>
          <div className="flex justify-end">
            <Button
              type="button"
              variant="outline"
              onClick={onTestFasterWhisper}
              disabled={isTestingFasterWhisper}
            >
              {isTestingFasterWhisper && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              校验 fast-whisper
            </Button>
          </div>
        </div>

        <div className="space-y-3 rounded-lg border p-3">
          <div className="flex items-center gap-2 flex-wrap">
            <div className="font-medium">火山引擎 ASR</div>
            <Badge variant="outline">内置</Badge>
            <RuntimeValidationBadge status={settings?.speech_volcengine_validation_status} />
          </div>
          <p className="text-xs text-muted-foreground">
            参数获取教程：
            <a
              href="https://www.volcengine.com/docs/6561/196768?lang=zh#q1%EF%BC%9A%E5%93%AA%E9%87%8C%E5%8F%AF%E4%BB%A5%E8%8E%B7%E5%8F%96%E5%88%B0%E4%BB%A5%E4%B8%8B%E5%8F%82%E6%95%B0appid%EF%BC%8Ccluster%EF%BC%8Ctoken%EF%BC%8Cauthorization-type%EF%BC%8Csecret-key-%EF%BC%9F"
              target="_blank"
              rel="noopener noreferrer"
              className="ml-1 text-primary underline underline-offset-2"
            >
              查看如何获取 APP ID / Access Token
            </a>
          </p>
          <div className="grid gap-3 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="speech_volcengine_app_key">APP ID</Label>
              <SecretInput
                id="speech_volcengine_app_key"
                visible={Boolean(showApiKeys.speech_volcengine_app_key)}
                onToggleVisibility={() => onToggleApiKey('speech_volcengine_app_key')}
                placeholder="输入火山语音识别 APP ID"
                value={speechVolcengineAppKey}
                onChange={(e) => updateField('speech_volcengine_app_key', e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="speech_volcengine_access_key">Access Token</Label>
              <SecretInput
                id="speech_volcengine_access_key"
                visible={Boolean(showApiKeys.speech_volcengine_access_key)}
                onToggleVisibility={() => onToggleApiKey('speech_volcengine_access_key')}
                placeholder="输入火山语音识别 Access Token"
                value={speechVolcengineAccessKey}
                onChange={(e) => updateField('speech_volcengine_access_key', e.target.value)}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="speech_volcengine_resource_id">识别模型</Label>
            <Select
              value={speechVolcengineResourceId}
              onValueChange={(v) => updateField('speech_volcengine_resource_id', v)}
            >
              <SelectTrigger id="speech_volcengine_resource_id">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {VOLCENGINE_MODEL_OPTIONS.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              默认支持中英文、上海话、闽南语、四川话、陕西话、粤语识别。
            </p>
          </div>
          <div className="flex justify-end">
            <Button
              type="button"
              variant="outline"
              onClick={onTestVolcengineSpeechRecognition}
              disabled={isTestingVolcengineSpeechRecognition}
            >
              {isTestingVolcengineSpeechRecognition && <Loader2 className="h-4 w-4 animate-spin mr-2" />}
              校验火山语音识别
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
