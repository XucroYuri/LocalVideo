'use client'

import dynamic from 'next/dynamic'

import type { VideoPreviewPlayerProps } from '@/components/ui/video-preview-player'

const DynamicVideoPreviewPlayer = dynamic(
  () => import('@/components/ui/video-preview-player').then((mod) => mod.VideoPreviewPlayer),
  {
    ssr: false,
    loading: () => <div className="h-full w-full rounded-lg bg-muted/20" aria-hidden="true" />,
  }
)

export function VideoPreviewPlayerClient(props: VideoPreviewPlayerProps) {
  return <DynamicVideoPreviewPlayer {...props} />
}
