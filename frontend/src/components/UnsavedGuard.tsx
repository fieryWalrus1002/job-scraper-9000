import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'

/**
 * Guards in-flight edits when leaving a page that holds unsaved form state.
 *
 * The app routes with `<BrowserRouter>` + `<Routes>` (component routing), so
 * react-router's `useBlocker` is unavailable (it needs a data router). Instead
 * a page reports its dirtiness via `setBlocked`, and any in-app navigation that
 * could discard those edits is routed through `requestNavigation`: when
 * blocked it pops a confirm dialog instead of navigating straight away. A
 * `beforeunload` handler covers the browser-level exits (refresh, close, and
 * full-page `<a href>` links like logout) the SPA router never sees.
 */
interface UnsavedGuard {
  /** A page with unsaved edits calls this to arm/disarm the guard. */
  setBlocked: (blocked: boolean) => void
  /** Run `proceed` now if unblocked, else confirm first. */
  requestNavigation: (proceed: () => void) => void
}

const Ctx = createContext<UnsavedGuard | null>(null)

/** No-throw: outside the provider, navigation is never blocked. */
// eslint-disable-next-line react-refresh/only-export-components
export function useUnsavedGuard(): UnsavedGuard {
  return (
    useContext(Ctx) ?? {
      setBlocked: () => {},
      requestNavigation: (proceed) => proceed(),
    }
  )
}

export function UnsavedGuardProvider({ children }: { children: React.ReactNode }) {
  const [blocked, setBlockedState] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const pendingRef = useRef<(() => void) | null>(null)

  const setBlocked = useCallback((b: boolean) => setBlockedState(b), [])

  const requestNavigation = useCallback(
    (proceed: () => void) => {
      if (!blocked) {
        proceed()
        return
      }
      pendingRef.current = proceed
      setConfirming(true)
    },
    [blocked],
  )

  // Browser-level exits the SPA router can't intercept. Setting returnValue is
  // what triggers the native "leave site?" prompt across browsers.
  useEffect(() => {
    if (!blocked) return
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [blocked])

  function discard() {
    const proceed = pendingRef.current
    pendingRef.current = null
    setConfirming(false)
    proceed?.()
  }

  function cancel() {
    pendingRef.current = null
    setConfirming(false)
  }

  return (
    <Ctx.Provider value={{ setBlocked, requestNavigation }}>
      {children}
      <Dialog open={confirming} onOpenChange={(open) => !open && cancel()}>
        <DialogContent showCloseButton={false} className="p-5 gap-4">
          <DialogHeader>
            <DialogTitle className="text-[15px]">Discard unsaved changes?</DialogTitle>
            <DialogDescription className="text-[12px]">
              You have edits that haven't been saved. Leaving this page will discard them.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" size="sm" onClick={cancel}>
              Keep editing
            </Button>
            <Button variant="destructive" size="sm" onClick={discard}>
              Discard changes
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Ctx.Provider>
  )
}
