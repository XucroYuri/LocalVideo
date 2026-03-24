'use client'

import { Bot, Check, Trash2 } from 'lucide-react'

import { SecretInput } from '@/components/settings/secret-input'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { ModelManagerDialog } from '@/components/settings/model-manager-dialog'
import type { ModelManagerDialogRow } from '@/components/settings/model-manager-dialog'
import { useModelManager } from '@/hooks/use-model-manager'
import { useSettingsLlmProvider } from '@/hooks/use-settings-llm-provider'
import { getLlmProviderDisplayName, normalizeModelIds } from '@/lib/provider-config'
import type {
  LLMProviderConfig,
  LLMProviderType,
  SettingsUpdate,
} from '@/types/settings'

const CUSTOM_LLM_PROVIDER_TYPES: Array<{ value: LLMProviderType; label: string; endpoint: string }> = [
  { value: 'openai_chat', label: 'OpenAI', endpoint: '/chat/completions' },
  { value: 'openai_responses', label: 'OpenAI-Response', endpoint: '/responses' },
  { value: 'gemini', label: 'Gemini', endpoint: '/v1beta/openai/chat/completions' },
  { value: 'anthropic_messages', label: 'Anthropic', endpoint: '/messages' },
]

interface SettingsLlmProviderSectionProps {
  currentDefaultLlmProviderId: string
  updateField: <K extends keyof SettingsUpdate>(key: K, value: SettingsUpdate[K]) => void
  llmProviders: LLMProviderConfig[]
  showApiKeys: Record<string, boolean>
  onToggleApiKey: (key: string) => void
}

export function SettingsLlmProviderSection({
  currentDefaultLlmProviderId,
  updateField,
  llmProviders,
  showApiKeys,
  onToggleApiKey,
}: SettingsLlmProviderSectionProps) {
  const llmModelManager = useModelManager()

  const {
    isLoadingModels,
    isCreatingCustomProvider,
    setIsCreatingCustomProvider,
    customProviderName,
    setCustomProviderName,
    customProviderType,
    setCustomProviderType,
    llmProviderFetchedCatalogMap,
    updateLlmProvider,
    llmModelManagerCatalogIds,
    llmModelManagerEnabledIds,
    llmModelManagerAdapter,
    llmModelManagerAllSelected,
    canRefreshLlmModelManagerCatalog,
    handleOpenModelManager,
    handleLlmModelEnabledChange,
    handleToggleAllLlmModels,
    handleRefreshCurrentProviderModels,
    handleTestLlmModel,
    handleAddCustomProvider,
    handleDeleteCustomProvider,
  } = useSettingsLlmProvider({
    llmProviders,
    llmModelManager,
    updateField,
    currentDefaultProviderId: currentDefaultLlmProviderId,
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Bot className="h-5 w-5" />
          LLM
        </CardTitle>
        <CardDescription>用于生成文案和脚本的语言模型</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-4">
          {llmProviders.map((provider) => {
            const enabledModels = normalizeModelIds(provider.enabled_models ?? [])
            const latestCatalog = llmProviderFetchedCatalogMap[provider.id]
            const latestCatalogSet = latestCatalog ? new Set(latestCatalog) : null
            return (
              <div key={provider.id} className="border rounded-lg p-4 space-y-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-2 flex-wrap">
                    <div className="font-medium">
                      {getLlmProviderDisplayName(provider)}
                    </div>
                    <Badge variant="outline">{provider.is_builtin ? '内置' : '自定义'}</Badge>
                    {provider.api_key.trim() && (
                      <Badge variant="outline" className="text-green-600">
                        <Check className="h-3 w-3 mr-1" />
                        已配置
                      </Badge>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => handleOpenModelManager(provider.id)}
                    >
                      管理模型列表
                    </Button>
                    {!provider.is_builtin && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="text-destructive border-destructive/40 hover:bg-destructive/10 hover:text-destructive"
                        onClick={() => handleDeleteCustomProvider(provider.id)}
                      >
                        <Trash2 className="h-4 w-4 mr-1" />
                        删除
                      </Button>
                    )}
                  </div>
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor={`llm_api_key_${provider.id}`}>API Key</Label>
                    <SecretInput
                      id={`llm_api_key_${provider.id}`}
                      visible={Boolean(showApiKeys[provider.id])}
                      onToggleVisibility={() => onToggleApiKey(provider.id)}
                      placeholder="sk-..."
                      value={provider.api_key}
                      onChange={(e) => updateLlmProvider(provider.id, { api_key: e.target.value })}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor={`llm_base_url_${provider.id}`}>Base URL</Label>
                    <Input
                      id={`llm_base_url_${provider.id}`}
                      placeholder="https://api.openai.com"
                      value={provider.base_url}
                      onChange={(e) => updateLlmProvider(provider.id, { base_url: e.target.value })}
                    />
                  </div>
                  <div className="space-y-2 md:col-span-2">
                    <Label>模型列表</Label>
                    <div className="min-h-10 rounded-md border px-3 py-2">
                      {enabledModels.length > 0 ? (
                        <div className="flex flex-wrap gap-2">
                          {enabledModels.map((modelId) => (
                            <Badge key={modelId} variant="secondary">
                              {modelId}
                              {!provider.is_builtin && latestCatalogSet && !latestCatalogSet.has(modelId)
                                ? '（已失效）'
                                : ''}
                            </Badge>
                          ))}
                        </div>
                      ) : (
                        <div className="text-sm text-muted-foreground">
                          请在「管理模型列表」中勾选模型
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => setIsCreatingCustomProvider(true)}
        >
          添加自定义供应商
        </Button>
        <ModelManagerDialog
          open={llmModelManager.isOpen}
          onOpenChange={llmModelManager.onOpenChange}
          selectedCount={llmModelManagerEnabledIds.length}
          totalCount={llmModelManagerCatalogIds.length}
          rows={llmModelManagerCatalogIds.map((modelId) => ({
            tags: (() => {
              const activeProviderId = llmModelManager.providerId
              if (!activeProviderId) return []
              const activeProvider = llmProviders.find((provider) => provider.id === activeProviderId)
              if (!activeProvider || activeProvider.is_builtin) return []
              const latestCatalog = llmProviderFetchedCatalogMap[activeProviderId]
              if (!latestCatalog) return []
              return latestCatalog.includes(modelId) ? [] : ['已失效']
            })(),
            id: modelId,
            label: modelId,
            checked: llmModelManagerEnabledIds.includes(modelId),
            connectivity: llmModelManager.getModelConnectivity(modelId),
            canTest: Boolean(llmModelManagerAdapter),
            onTest: () => handleTestLlmModel(modelId),
            onCheckedChange: (checked: boolean) => handleLlmModelEnabledChange(modelId, checked),
          })) as ModelManagerDialogRow[]}
          allSelected={llmModelManagerAllSelected}
          onToggleAll={handleToggleAllLlmModels}
          showRefreshButton={canRefreshLlmModelManagerCatalog}
          onRefresh={handleRefreshCurrentProviderModels}
          isRefreshing={isLoadingModels}
          refreshDisabled={!llmModelManagerAdapter}
          emptyText={canRefreshLlmModelManagerCatalog
            ? '暂无模型，请检查 API 配置后点击「刷新模型列表」。'
            : '暂无模型。'}
        />
        <Dialog open={isCreatingCustomProvider} onOpenChange={setIsCreatingCustomProvider}>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>添加自定义供应商</DialogTitle>
              <DialogDescription>创建一个自定义 LLM 供应商卡片。</DialogDescription>
            </DialogHeader>
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="custom_llm_name">供应商名称</Label>
                <Input
                  id="custom_llm_name"
                  value={customProviderName}
                  onChange={(e) => setCustomProviderName(e.target.value)}
                  placeholder="例如：Acme API"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="custom_llm_type">供应商类型</Label>
                <Select
                  value={customProviderType}
                  onValueChange={(value) => setCustomProviderType(value as LLMProviderType)}
                >
                  <SelectTrigger id="custom_llm_type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {CUSTOM_LLM_PROVIDER_TYPES.map((item) => (
                      <SelectItem key={item.value} value={item.value}>
                        {item.label} ({item.endpoint})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex justify-end">
                <Button type="button" onClick={handleAddCustomProvider}>创建</Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  )
}
