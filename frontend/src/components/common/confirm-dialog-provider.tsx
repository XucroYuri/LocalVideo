'use client'

import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'

type ConfirmDialogVariant = 'default' | 'destructive'

export interface ConfirmDialogOptions {
  title?: string
  description: string
  confirmText?: string
  cancelText?: string
  variant?: ConfirmDialogVariant
  hideCancel?: boolean
}

interface ConfirmDialogState {
  open: boolean
  options: ConfirmDialogOptions | null
}

interface ConfirmDialogContextValue {
  confirm: (options: ConfirmDialogOptions) => Promise<boolean>
}

const ConfirmDialogContext = createContext<ConfirmDialogContextValue | null>(null)

export function ConfirmDialogProvider({ children }: { children: React.ReactNode }) {
  const resolverRef = useRef<((value: boolean) => void) | null>(null)
  const [state, setState] = useState<ConfirmDialogState>({
    open: false,
    options: null,
  })

  const closeWith = useCallback((value: boolean) => {
    const resolve = resolverRef.current
    resolverRef.current = null
    setState({ open: false, options: null })
    if (resolve) {
      resolve(value)
    }
  }, [])

  const confirm = useCallback((options: ConfirmDialogOptions) => {
    return new Promise<boolean>((resolve) => {
      if (resolverRef.current) {
        resolverRef.current(false)
      }
      resolverRef.current = resolve
      setState({ open: true, options })
    })
  }, [])

  const value = useMemo<ConfirmDialogContextValue>(() => ({ confirm }), [confirm])
  const options = state.options
  const title = options?.title || '请确认'
  const confirmText = options?.confirmText || '确定'
  const cancelText = options?.cancelText || '取消'
  const variant = options?.variant || 'default'
  const hideCancel = options?.hideCancel === true

  return (
    <ConfirmDialogContext.Provider value={value}>
      {children}
      <Dialog
        open={state.open}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) {
            closeWith(false)
          }
        }}
      >
        <DialogContent className="sm:max-w-md" showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription className="whitespace-pre-line leading-6 text-foreground/90">
              {options?.description || ''}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="pt-2">
            {!hideCancel ? (
              <Button
                type="button"
                variant="outline"
                onClick={() => closeWith(false)}
              >
                {cancelText}
              </Button>
            ) : null}
            <Button
              type="button"
              variant={variant === 'destructive' ? 'destructive' : 'default'}
              onClick={() => closeWith(true)}
            >
              {confirmText}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </ConfirmDialogContext.Provider>
  )
}

export function useConfirmDialog() {
  const context = useContext(ConfirmDialogContext)
  if (!context) {
    throw new Error('useConfirmDialog must be used within ConfirmDialogProvider')
  }
  return context.confirm
}
