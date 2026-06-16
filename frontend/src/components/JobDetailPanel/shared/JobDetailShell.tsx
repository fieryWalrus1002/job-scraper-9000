import type { ReactNode } from 'react'
import { X } from 'lucide-react'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'

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
      >
        {children}
      </DialogContent>
    </Dialog>
  )
}

export function JobDetailBody({ children }: { children: ReactNode }) {
  return <div className="flex-1 overflow-y-auto">{children}</div>
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
