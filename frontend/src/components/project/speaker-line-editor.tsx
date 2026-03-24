'use client'

import { ChevronDown, X } from 'lucide-react'

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

interface SpeakerOption {
  id: string
  name: string
}

interface SpeakerLineEditorProps {
  speakerId: string
  speakerName: string
  speakerOptions: SpeakerOption[]
  text: string
  placeholder?: string
  disabled?: boolean
  showDeleteAction?: boolean
  onSpeakerChange?: (speakerId: string) => void
  onDelete?: () => void
  onTextChange: (value: string) => void
  onBlur?: () => void
  onKeyDown?: React.KeyboardEventHandler<HTMLTextAreaElement>
  onCompositionStart?: React.CompositionEventHandler<HTMLTextAreaElement>
  onCompositionEnd?: React.CompositionEventHandler<HTMLTextAreaElement>
  textareaRef?: (node: HTMLTextAreaElement | null) => void
  rowClassName?: string
  textareaClassName?: string
  speakerButtonClassName?: string
}

export function SpeakerLineEditor({
  speakerId,
  speakerName,
  speakerOptions,
  text,
  placeholder,
  disabled = false,
  showDeleteAction = false,
  onSpeakerChange,
  onDelete,
  onTextChange,
  onBlur,
  onKeyDown,
  onCompositionStart,
  onCompositionEnd,
  textareaRef,
  rowClassName,
  textareaClassName,
  speakerButtonClassName,
}: SpeakerLineEditorProps) {
  return (
    <div className={cn('group/line grid grid-cols-[auto_minmax(0,1fr)] items-center gap-2.5 px-1 py-0.5', rowClassName)}>
      <div className="relative">
        <DropdownMenu>
          <DropdownMenuTrigger asChild disabled={disabled || !onSpeakerChange}>
            <button
              type="button"
              className={cn(
                'inline-flex h-8 items-center gap-1 rounded-full border bg-muted/35 px-3.5 text-xs font-medium text-foreground transition-colors hover:bg-muted',
                speakerButtonClassName
              )}
            >
              <span>{speakerName}</span>
              <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="min-w-[140px]">
            {speakerOptions.map((speaker) => (
              <DropdownMenuItem
                key={speaker.id}
                onSelect={() => onSpeakerChange?.(speaker.id)}
                className={cn(String(speaker.id) === String(speakerId) && 'bg-accent')}
              >
                {speaker.name}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
        {showDeleteAction && onDelete && !disabled && (
          <button
            type="button"
            className="absolute -right-1 -top-1 hidden h-4 w-4 items-center justify-center rounded-full border bg-background text-muted-foreground transition-colors group-hover/line:flex hover:text-destructive"
            onClick={onDelete}
            aria-label={`删除 ${speakerName} 台词`}
            title={`删除 ${speakerName} 台词`}
          >
            <X className="h-3 w-3" />
          </button>
        )}
      </div>

      <Textarea
        ref={textareaRef}
        value={text}
        onChange={(event) => onTextChange(event.target.value)}
        onKeyDown={onKeyDown}
        onCompositionStart={onCompositionStart}
        onCompositionEnd={onCompositionEnd}
        onBlur={onBlur}
        placeholder={placeholder}
        rows={1}
        className={cn(
          'min-h-7 resize-none border-0 bg-transparent px-0 py-1 text-sm leading-5 shadow-none focus-visible:ring-0',
          'field-sizing-content',
          textareaClassName
        )}
        disabled={disabled}
      />
    </div>
  )
}
