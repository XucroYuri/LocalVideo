'use client'

import type * as React from 'react'
import { Eye, EyeOff } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

interface SecretInputProps extends Omit<React.ComponentProps<typeof Input>, 'type'> {
  visible: boolean
  onToggleVisibility: () => void
  buttonClassName?: string
}

export function SecretInput({
  visible,
  onToggleVisibility,
  className,
  buttonClassName,
  ...props
}: SecretInputProps) {
  return (
    <div className="relative">
      <Input
        {...props}
        type={visible ? 'text' : 'password'}
        className={cn('pr-10', className)}
      />
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className={cn('absolute right-2 top-1/2 h-6 w-6 -translate-y-1/2 p-0', buttonClassName)}
        onClick={onToggleVisibility}
      >
        {visible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </Button>
    </div>
  )
}
