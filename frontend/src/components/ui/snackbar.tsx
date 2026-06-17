import * as React from 'react'
import { Toast } from 'radix-ui'

import { cn } from '@/lib/utils'

export interface SnackbarAction {
  label: string
  onClick: () => void
}

export interface SnackbarOptions {
  message: string
  action?: SnackbarAction
  /** Auto-dismiss after this many ms. Defaults to 6000. */
  durationMs?: number
}

interface SnackbarContextValue {
  show: (options: SnackbarOptions) => void
  dismiss: () => void
}

const SnackbarContext = React.createContext<SnackbarContextValue | null>(null)

/**
 * App-wide single-slot snackbar. A new `show()` replaces whatever is on screen —
 * triage is rapid-fire, so the latest action's undo is the only one that matters.
 * Built on Radix Toast for focus/hover-pause/escape behavior; styled to the theme
 * tokens like the other ui/ primitives.
 */
export function SnackbarProvider({ children }: { children: React.ReactNode }) {
  const [snack, setSnack] = React.useState<SnackbarOptions | null>(null)
  const [open, setOpen] = React.useState(false)
  // Bumped on every show() so a back-to-back snackbar re-triggers the enter
  // animation and resets the auto-dismiss timer even when the message is identical.
  const [key, setKey] = React.useState(0)

  const show = React.useCallback((options: SnackbarOptions) => {
    setSnack(options)
    setKey((k) => k + 1)
    setOpen(true)
  }, [])

  const dismiss = React.useCallback(() => setOpen(false), [])

  const value = React.useMemo(() => ({ show, dismiss }), [show, dismiss])

  return (
    <SnackbarContext.Provider value={value}>
      <Toast.Provider swipeDirection="down">
        {children}
        <Toast.Root
          key={key}
          open={open}
          onOpenChange={setOpen}
          duration={snack?.durationMs ?? 6000}
          className={cn(
            'flex items-center gap-3 rounded-md border border-border bg-card px-3.5 py-2.5 shadow-lg',
            'data-[state=open]:animate-in data-[state=open]:slide-in-from-bottom-2 data-[state=open]:fade-in-0',
            'data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:slide-out-to-bottom-2',
          )}
        >
          <Toast.Title className="text-[13px] text-fg">{snack?.message}</Toast.Title>
          {snack?.action && (
            <Toast.Action
              asChild
              altText={snack.action.label}
              onClick={() => {
                snack.action!.onClick()
                setOpen(false)
              }}
            >
              <button
                type="button"
                className="text-[13px] font-medium text-primary-hov hover:text-primary underline-offset-2 hover:underline cursor-pointer"
              >
                {snack.action.label}
              </button>
            </Toast.Action>
          )}
          <Toast.Close
            aria-label="Dismiss"
            className="text-faint hover:text-fg cursor-pointer text-sm leading-none"
          >
            ✕
          </Toast.Close>
        </Toast.Root>
        <Toast.Viewport className="fixed bottom-4 left-1/2 z-[100] flex -translate-x-1/2 flex-col gap-2 outline-none" />
      </Toast.Provider>
    </SnackbarContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useSnackbar(): SnackbarContextValue {
  const ctx = React.useContext(SnackbarContext)
  if (!ctx) throw new Error('useSnackbar must be used within a SnackbarProvider')
  return ctx
}
