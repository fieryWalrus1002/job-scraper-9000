import { useState } from 'react'
import { useApplications } from '../hooks/useApplications'
import type { Application, ApplicationStatus } from '../types'
import {
  ACTIVE_STATUSES,
  CLOSED_STATUSES,
  TO_APPLY_STATUSES,
  TRACKING_STATUSES,
} from '../lib/trackingGroups'
import { ApplicationTable } from './TriageApplicationTable'
import { cn } from '../lib/utils'

interface Props {
  onSelect: (application: Application) => void
}

/**
 * Tracking tab: one fetch over all committed statuses, partitioned into
 * To Apply / Active / Closed. To Apply + Active open by default; Closed collapses
 * so dead applications don't pile up in view.
 */
export function TrackingBoard({ onSelect }: Props) {
  const { data, isLoading, isError, error } = useApplications(TRACKING_STATUSES)

  if (isLoading) return <div className="py-12 text-center text-muted text-sm">Loading…</div>
  if (isError) {
    return (
      <div className="py-12 text-center text-score-low text-sm">
        Failed to load applications: {(error as Error).message}
      </div>
    )
  }

  const all = Array.from(data?.values() ?? [])
  if (all.length === 0) {
    return (
      <div className="py-20 text-center">
        <div className="text-muted text-sm">No tracking jobs yet.</div>
        <div className="text-faint text-xs mt-1.5">
          Pursue a shortlisted job to move it into Tracking.
        </div>
      </div>
    )
  }

  const inGroup = (statuses: ApplicationStatus[]) => all.filter((a) => statuses.includes(a.status))

  return (
    <div className="flex-1 overflow-auto">
      <TrackingGroup
        title="To Apply"
        applications={inGroup(TO_APPLY_STATUSES)}
        defaultOpen
        onSelect={onSelect}
      />
      <TrackingGroup
        title="Active"
        applications={inGroup(ACTIVE_STATUSES)}
        defaultOpen
        onSelect={onSelect}
      />
      <TrackingGroup
        title="Closed"
        applications={inGroup(CLOSED_STATUSES)}
        defaultOpen={false}
        onSelect={onSelect}
      />
    </div>
  )
}

function TrackingGroup({
  title,
  applications,
  defaultOpen,
  onSelect,
}: {
  title: string
  applications: Application[]
  defaultOpen: boolean
  onSelect: (application: Application) => void
}) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <section className="border-b border-border last:border-b-0">
      <button
        type="button"
        className="flex items-center gap-2.5 w-full px-5 py-3 bg-transparent border-none cursor-pointer text-left hover:bg-hover/60 transition-colors group"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <svg
          width="10"
          height="10"
          viewBox="0 0 10 10"
          className={cn(
            'text-faint transition-transform duration-200 group-hover:text-muted',
            open && 'rotate-90',
          )}
          aria-hidden="true"
        >
          <path
            d="M3.5 2 L6.5 5 L3.5 8"
            stroke="currentColor"
            strokeWidth="1.5"
            fill="none"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <span className="text-[13px] font-medium text-fg">{title}</span>
        <span className="inline-flex items-center justify-center min-w-[20px] h-[18px] px-1.5 rounded text-[10.5px] font-mono tabular-nums text-faint bg-bg-elevated/80 border border-border/60">
          {applications.length}
        </span>
      </button>
      {open &&
        (applications.length > 0 ? (
          <ApplicationTable applications={applications} onSelect={onSelect} />
        ) : (
          <div className="px-5 pb-4 text-faint text-xs">Nothing here yet.</div>
        ))}
    </section>
  )
}
