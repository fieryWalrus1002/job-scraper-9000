import type { ReactNode } from 'react'
import { X } from 'lucide-react'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { isEditableTarget, isQuitKey } from '@/lib/keyboard'

// How far j/k and the arrows nudge the description per press.
const SCROLL_STEP = 120

export function JobDetailShell({
  onClose,
  children,
}: {
  onClose: () => void
  children: ReactNode
}) {
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        showCloseButton={false}
        className="sm:max-w-[940px] w-full h-[88vh] p-0 gap-0 overflow-hidden"
        // Land focus on the description so it's immediately scrollable with the
        // keyboard, rather than on the first action button.
        onOpenAutoFocus={(e) => {
          const content = e.currentTarget as HTMLElement
          const body = content.querySelector<HTMLElement>('[data-detail-scroll]')
          if (body) {
            e.preventDefault()
            body.focus()
          }
        }}
        onKeyDown={(e) => {
          // `q` quits the panel, alongside Radix's built-in Escape.
          if (isQuitKey(e)) {
            e.preventDefault()
            onClose()
            return
          }
          if (isEditableTarget(e.target) || e.ctrlKey || e.metaKey || e.altKey) return
          // Scroll the description region directly rather than leaning on which
          // element holds focus, so the arrows/j/k always drive the read pane.
          const body = e.currentTarget.querySelector<HTMLElement>('[data-detail-scroll]')
          if (!body) return
          const pageStep = body.clientHeight * 0.9
          let dy: number
          switch (e.key) {
            case 'j':
            case 'ArrowDown':
              dy = SCROLL_STEP
              break
            case 'k':
            case 'ArrowUp':
              dy = -SCROLL_STEP
              break
            case 'PageDown':
              dy = pageStep
              break
            case 'PageUp':
              dy = -pageStep
              break
            default:
              return
          }
          e.preventDefault()
          body.scrollBy({ top: dy })
        }}
      >
        {children}
      </DialogContent>
    </Dialog>
  )
}

export function JobDetailBody({ children }: { children: ReactNode }) {
  // The scroll target for JobDetailShell's keyboard handler. Focusable
  // (programmatically, not via Tab) so opening the panel lands focus here and
  // Space/Home/End still scroll natively.
  return (
    <div data-detail-scroll tabIndex={-1} className="flex-1 overflow-y-auto outline-none">
      {children}
    </div>
  )
}

export function JobDetailVisitButton({ url }: { url: string | null | undefined }) {
  return url ? (
    <Button variant="secondary" size="sm" asChild>
      <a href={url} target="_blank" rel="noopener noreferrer">
        View posting <span className="text-faint">↗</span>
      </a>
    </Button>
  ) : null
}

export function JobDetailCloseButton({ onClose }: { onClose: () => void }) {
  return (
    <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close job detail panel">
      <X className="h-4 w-4 md:h-5 md:w-5" />
    </Button>
  )
}
