import { useEffect, useState } from 'react'
import type { Application, ApplicationStatus } from '../../../types'
import { APPLICATION_STATUSES, STATUS_LABELS } from '../../../types'
import {
  useDeleteApplication,
  useMarkApplication,
  useUpdateApplication,
} from '../../../hooks/useApplications'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { sectionLabel } from './variants'
import { MutationError } from './MutationError'

export function ApplicationTrackingSection({
  dedupHash,
  application,
}: {
  dedupHash: string
  application: Application | undefined
}) {
  const mark = useMarkApplication()
  const update = useUpdateApplication()
  const del = useDeleteApplication()
  const [notes, setNotes] = useState(application?.notes ?? '')
  const isPending = mark.isPending || update.isPending || del.isPending

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setNotes(application?.notes ?? '')
  }, [application?.notes, dedupHash])

  function handleStatusChange(status: ApplicationStatus) {
    if (application) {
      update.mutate({ dedupHash, update: { status } })
    } else {
      mark.mutate({ dedupHash, status })
    }
  }

  function handleNotesBlur() {
    if (notes === (application?.notes ?? '')) return
    if (application) {
      update.mutate({ dedupHash, update: { notes } })
    } else if (notes.trim()) {
      mark.mutate({ dedupHash, status: 'maybe', notes })
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <MutationError error={mark.error ?? update.error ?? del.error} />

      <div className="flex flex-col gap-2">
        <div className={sectionLabel}>Status</div>
        <div className="flex flex-wrap gap-1.5">
          {APPLICATION_STATUSES.map((s) => {
            const active = application?.status === s
            return (
              <button
                key={s}
                disabled={isPending}
                onClick={() => handleStatusChange(s)}
                className={cn(
                  'text-xs px-2.5 h-7 rounded-md border border-border bg-card text-muted cursor-pointer transition-all',
                  'hover:border-border-strong hover:text-fg',
                  'disabled:opacity-40 disabled:cursor-default',
                  active &&
                    'bg-primary/15 border-primary/40 text-primary-hov font-medium shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]',
                )}
              >
                {STATUS_LABELS[s]}
              </button>
            )
          })}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <div className={sectionLabel}>Notes</div>
        <textarea
          className="w-full min-h-[110px] resize-y bg-bg-elevated border border-border rounded-md text-fg text-[13px] leading-[1.55] p-2.5 outline-none placeholder:text-faint hover:border-border-strong focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/25 transition-[color,border-color,box-shadow]"
          value={notes}
          rows={4}
          placeholder="Add notes…"
          onChange={(e) => setNotes(e.target.value)}
          onBlur={handleNotesBlur}
        />
      </div>

      {application && (
        <div className="flex items-center gap-3 text-[11px] pt-1 border-t border-border/60 mt-1">
          <span className="text-muted">Last updated</span>
          <span className="text-fg font-mono">{application.updated_at}</span>
          <Button
            variant="ghost"
            size="xs"
            className="ml-auto text-faint hover:text-score-low"
            disabled={isPending}
            onClick={() => {
              if (window.confirm('Remove tracking for this job?')) del.mutate(dedupHash)
            }}
          >
            Remove tracking
          </Button>
        </div>
      )}
    </div>
  )
}
