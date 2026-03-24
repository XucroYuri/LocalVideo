'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useQueryClient } from '@tanstack/react-query'
import { ProjectLayout } from '@/components/layout/project-layout'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ArrowLeft, Loader2 } from 'lucide-react'
import Link from 'next/link'
import { api } from '@/lib/api-client'
import { queryKeys } from '@/lib/query-keys'
import { toast } from 'sonner'

export default function NewProjectPage() {
  const router = useRouter()
  const queryClient = useQueryClient()
  const [loading, setLoading] = useState(false)
  const [formData, setFormData] = useState({
    title: '',
    keywords: '',
    input_text: '',
    style: '',
    target_duration: 60,
  })
  const [targetDurationInput, setTargetDurationInput] = useState('60')
  let targetDurationHint = ''
  if (targetDurationInput.trim() === '') {
    targetDurationHint = '请输入 10-600 秒'
  } else {
    const parsedTargetDuration = Number.parseInt(targetDurationInput, 10)
    if (!Number.isFinite(parsedTargetDuration)) {
      targetDurationHint = '请输入整数秒'
    } else if (parsedTargetDuration < 10) {
      targetDurationHint = '最少 10 秒'
    } else if (parsedTargetDuration > 600) {
      targetDurationHint = '最多 600 秒'
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!formData.title.trim()) {
      toast.error('请输入项目标题')
      return
    }

    setLoading(true)
    try {
      const parsedTargetDuration = Number.parseInt(targetDurationInput, 10)
      const normalizedTargetDuration = Number.isFinite(parsedTargetDuration)
        ? Math.max(10, Math.min(600, parsedTargetDuration))
        : 60
      const project = await api.projects.create({
        ...formData,
        target_duration: normalizedTargetDuration,
        keywords: formData.keywords || undefined,
        input_text: formData.input_text || undefined,
      })
      toast.success('项目创建成功')
      router.push(`/projects/${project.id}`)
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects.root })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '创建失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <ProjectLayout>
      <div className="container max-w-2xl py-8">
        <div className="mb-6">
          <Button variant="ghost" size="sm" asChild>
            <Link href="/">
              <ArrowLeft className="mr-2 h-4 w-4" />
              返回
            </Link>
          </Button>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>创建新项目</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-6">
              <div className="space-y-2">
                <Label htmlFor="title">项目标题 *</Label>
                <Input
                  id="title"
                  placeholder="例如：西贝贾国龙公关事件评论"
                  value={formData.title}
                  onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="keywords">关键词</Label>
                <Input
                  id="keywords"
                  placeholder="空格分隔，例如：西贝 贾国龙 公关"
                  value={formData.keywords}
                  onChange={(e) => setFormData({ ...formData, keywords: e.target.value })}
                />
                <p className="text-xs text-muted-foreground">
                  系统会根据关键词自动搜索相关信息
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="input_text">输入文本</Label>
                <Textarea
                  id="input_text"
                  placeholder="直接输入文本内容..."
                  rows={5}
                  value={formData.input_text}
                  onChange={(e) => setFormData({ ...formData, input_text: e.target.value })}
                />
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>视频风格</Label>
                  <Select
                    value={formData.style}
                    onValueChange={(value) => setFormData({ ...formData, style: value })}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="幽默">幽默</SelectItem>
                      <SelectItem value="犀利">犀利</SelectItem>
                      <SelectItem value="理性">理性</SelectItem>
                      <SelectItem value="讽刺">讽刺</SelectItem>
                      <SelectItem value="正经">正经</SelectItem>
                      <SelectItem value="出奇">出奇</SelectItem>
                      <SelectItem value="批判">批判</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-3">
                    <Label>目标时长 (秒)</Label>
                    {targetDurationHint ? (
                      <span className="text-xs text-amber-600">{targetDurationHint}</span>
                    ) : null}
                  </div>
                  <Input
                    type="number"
                    min={10}
                    max={600}
                    value={targetDurationInput}
                    onChange={(e) => {
                      const rawValue = e.target.value
                      if (rawValue === '') {
                        setTargetDurationInput('')
                        return
                      }
                      const parsedValue = Number.parseInt(rawValue, 10)
                      if (!Number.isFinite(parsedValue)) return
                      setTargetDurationInput(rawValue)
                      if (parsedValue >= 10 && parsedValue <= 600) {
                        setFormData((prev) => ({ ...prev, target_duration: parsedValue }))
                      }
                    }}
                    onBlur={() => {
                      const parsedValue = Number.parseInt(targetDurationInput, 10)
                      const normalizedValue = Number.isFinite(parsedValue)
                        ? Math.max(10, Math.min(600, parsedValue))
                        : 60
                      setTargetDurationInput(String(normalizedValue))
                      setFormData((prev) => ({ ...prev, target_duration: normalizedValue }))
                    }}
                  />
                </div>
              </div>

              <div className="flex justify-end gap-3">
                <Button type="button" variant="outline" asChild>
                  <Link href="/">取消</Link>
                </Button>
                <Button type="submit" disabled={loading}>
                  {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  创建项目
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      </div>
    </ProjectLayout>
  )
}
