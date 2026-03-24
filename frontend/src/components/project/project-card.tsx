'use client'

import Link from 'next/link'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import { MoreVertical, Trash2, Copy, Sparkles } from 'lucide-react'
import type { Project } from '@/types/project'
import { resolveApiResourceUrl } from '@/lib/media-url'
import { cn } from '@/lib/utils'
import { buildProjectModeLabel } from '@/lib/project-mode'

const DEFAULT_PROJECT_COVER_EMOJI = '🎬'

const GRADIENTS = [
  'from-pink-100 to-rose-100',
  'from-purple-100 to-violet-100',
  'from-blue-100 to-cyan-100',
  'from-teal-100 to-emerald-100',
  'from-green-100 to-lime-100',
  'from-yellow-100 to-amber-100',
  'from-orange-100 to-red-100',
  'from-fuchsia-100 to-pink-100',
  'from-indigo-100 to-blue-100',
  'from-cyan-100 to-teal-100',
]

function getProjectVisuals(id: number, title: string, coverEmoji?: string) {
  const gradientSeed = coverEmoji?.trim() || title
  const hash = gradientSeed.split('').reduce((acc, char) => acc + char.charCodeAt(0), id)
  const emoji = coverEmoji?.trim() || DEFAULT_PROJECT_COVER_EMOJI
  const gradient = GRADIENTS[hash % GRADIENTS.length]
  return { emoji, gradient }
}

interface ProjectCardProps {
  project: Project
  onDuplicate?: (id: number) => void
  onDelete?: (id: number) => void
  onRegenerateCover?: (id: number) => void
  viewMode?: 'grid' | 'list'
}

export function ProjectCard({ project, onDuplicate, onDelete, onRegenerateCover, viewMode = 'grid' }: ProjectCardProps) {
  const { emoji, gradient } = getProjectVisuals(project.id, project.title, project.cover_emoji)
  const modeLabel = buildProjectModeLabel(project.video_mode, project.video_type)
  const dialoguePreview = project.dialogue_preview?.trim() || '暂无台词'
  const firstVideoUrl = resolveApiResourceUrl(project.first_video_url)
  const hasFirstVideo = firstVideoUrl.length > 0

  const handleMenuClick = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }

  if (viewMode === 'list') {
    return (
      <Link href={`/projects/${project.id}`}>
        <Card className="group hover:shadow-md hover:border-primary/50 transition-all cursor-pointer">
          <CardContent className="flex items-center gap-4 p-4">
            <div className={cn(
              "h-12 w-12 rounded-xl bg-gradient-to-br flex items-center justify-center flex-shrink-0",
              gradient
            )}>
              <span className="text-2xl">{emoji}</span>
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="font-semibold truncate">{project.title}</h3>
              <div className="mt-1 flex items-center gap-2 min-w-0">
                <Badge variant="outline" className="text-[11px] whitespace-nowrap">
                  {modeLabel}
                </Badge>
                <p className="text-sm text-muted-foreground truncate">
                  {project.keywords || project.input_text?.slice(0, 50) || '暂无描述'}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2" onClick={handleMenuClick}>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" className="opacity-0 group-hover:opacity-100 h-8 w-8">
                    <MoreVertical className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={() => onRegenerateCover?.(project.id)}>
                    <Sparkles className="mr-2 h-4 w-4" />
                    重新生成 emoji
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => onDuplicate?.(project.id)}>
                    <Copy className="mr-2 h-4 w-4" />
                    复制
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    className="text-destructive"
                    onClick={() => onDelete?.(project.id)}
                  >
                    <Trash2 className="mr-2 h-4 w-4" />
                    删除
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          </CardContent>
        </Card>
      </Link>
    )
  }

  return (
    <Link href={`/projects/${project.id}`}>
      <Card className="group h-[252px] cursor-pointer overflow-hidden transition-all hover:-translate-y-0.5 hover:shadow-md">
        <CardContent className="flex h-full flex-col p-0">
          <div className="px-4 pt-4">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <h3 className="truncate text-base font-semibold leading-tight">
                  {project.title}
                </h3>
                <div className="mt-1 flex items-center gap-1.5 text-xs">
                  <Badge variant="outline" className="text-[11px]">
                    {modeLabel}
                  </Badge>
                </div>
              </div>
              <div className="opacity-0 transition-opacity group-hover:opacity-100" onClick={handleMenuClick}>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="secondary" size="icon" className="h-7 w-7 bg-white/80 shadow-sm hover:bg-white">
                      <MoreVertical className="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={() => onRegenerateCover?.(project.id)}>
                      <Sparkles className="mr-2 h-4 w-4" />
                      重新生成 emoji
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => onDuplicate?.(project.id)}>
                      <Copy className="mr-2 h-4 w-4" />
                      复制
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      className="text-destructive"
                      onClick={() => onDelete?.(project.id)}
                    >
                      <Trash2 className="mr-2 h-4 w-4" />
                      删除
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </div>
          </div>

          <div className={cn(
            'relative mt-3 flex h-24 w-full shrink-0 overflow-hidden border-y bg-gradient-to-br',
            gradient
          )}>
            {hasFirstVideo ? (
              <>
                <div className="absolute inset-0 overflow-hidden">
                  <video
                    key={firstVideoUrl}
                    src={firstVideoUrl}
                    preload="metadata"
                    muted
                    playsInline
                    className="h-full w-full scale-110 object-cover blur-md"
                  />
                </div>
                <div className="absolute inset-0 bg-black/15" />
                <div className="absolute inset-0 flex items-center justify-center px-6">
                  <video
                    key={`${firstVideoUrl}-foreground`}
                    src={firstVideoUrl}
                    preload="metadata"
                    muted
                    playsInline
                    className="h-full w-auto max-w-none object-contain drop-shadow-sm"
                  />
                </div>
                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-black/40 via-black/10 to-transparent" />
                <div className="absolute bottom-2 left-3 flex h-9 w-9 items-center justify-center rounded-full bg-white/88 shadow-sm backdrop-blur">
                  <span className="text-2xl">{emoji}</span>
                </div>
              </>
            ) : (
              <div className="flex h-full w-full items-center justify-center">
                <span className="text-[4.35rem] leading-none sm:text-[5rem]">{emoji}</span>
              </div>
            )}
          </div>

          <div className="h-[96px] px-4 pb-4 pt-3">
            <div className="h-[40px] overflow-hidden">
              <p className="line-clamp-2 text-[13px] leading-5 text-muted-foreground">
                {dialoguePreview}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}
