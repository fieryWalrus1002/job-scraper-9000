import { useCallback, type ComponentType } from 'react'
import type { JobSummary } from '../types'
import { Badge } from './ui/badge'
import { useSwipe } from '@/lib/swipe/useSwipe'
import { SwipeAffordance } from '@/lib/swipe/SwipeAffordance'
import { useTriageAction, type TriageTarget } from '../hooks/useTriage'
import { cn } from '../lib/utils'

/** A single swipe direction's commit + affordance. */
interface CardSwipeAction {
  to: TriageTarget
  label: string
  polarity: 'positive' | 'negative'
  icon?: ComponentType<{ className?: string }>
}

export interface CardSwipeActions {
  left?: CardSwipeAction
  right?: CardSwipeAction
}

interface Props {
  job: JobSummary
  actions: CardSwipeActions
  onSelect: (job: JobSummary) => void
  /** True when the keyboard cursor is on this card. */
  isFocused: boolean
}

function polarityColor(polarity: 'positive' | 'negative'): string {
  return polarity === 'negative' ? 'var(--color-score-low)' : 'var(--color-score-mid)'
}

/**
 * A single swipeable grab-bag card. Reuses the `useSwipe` gesture engine and
 * `SwipeAffordance` pill from the table surface. On commit the card triages
 * via the existing applications mutation; on tap it opens the detail panel.
 */
export function GrabBagCard({ job, actions, onSelect, isFocused }: Props) {
  const { triage } = useTriageAction()

  const { offset, progress, armed, direction, settling, handlers, consumeClickSuppression } =
    useSwipe({
      onCommit: (dir) => {
        const action = actions[dir]
        if (!action) return
        triage({ dedupHash: job.dedup_hash, from: null, to: action.to })
      },
    })

  const activeAction = direction ? actions[direction] : undefined
  const tint = activeAction
    ? `color-mix(in oklab, ${polarityColor(activeAction.polarity)} ${
        armed ? 22 : 6 + progress * 10
      }%, transparent)`
    : undefined

  const affordance = (dir: 'left' | 'right') => {
    if (direction !== dir) return undefined
    const action = actions[dir]
    if (!action) return undefined
    return (
      <SwipeAffordance
        direction={dir}
        progress={progress}
        armed={armed}
        offset={offset}
        label={action.label}
        icon={action.icon}
        color={polarityColor(action.polarity)}
      />
    )
  }

  const handleSelect = useCallback(() => {
    onSelect(job)
  }, [job, onSelect])

  return (
    <div
      {...handlers}
      className={cn(
        'relative overflow-hidden rounded-lg border border-border bg-card cursor-pointer',
        'transition-shadow',
        isFocused && 'ring-2 ring-primary/40 shadow-[0_0_0_1px_rgba(99,102,241,0.3)]',
      )}
      style={{
        transform: direction ? `translateX(${offset}px)` : undefined,
        backgroundColor: tint,
        touchAction: 'pan-y',
        ...(settling
          ? { transition: 'transform 150ms ease-out, background-color 150ms ease-out' }
          : {}),
      }}
      onClick={() => {
        if (consumeClickSuppression()) return
        handleSelect()
      }}
    >
      {/* Affordance pills — pinned at card edges, counter-translated so they
          stay fixed at the container edge while the card slides. */}
      {affordance('right')}
      {affordance('left')}

      <div className="p-4">
        {/* Title + company */}
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <div className="font-medium text-[13px] text-fg truncate">{job.title ?? '—'}</div>
            <div className="text-muted text-[12px] truncate">{job.company ?? '—'}</div>
          </div>
          <Badge
            variant={
              job.fit_score != null
                ? job.fit_score >= 4
                  ? 'score_high'
                  : job.fit_score === 3
                    ? 'score_mid'
                    : 'score_low'
                : 'secondary'
            }
            className="shrink-0 font-mono"
          >
            {job.fit_score ?? '—'}
          </Badge>
        </div>

        {/* Metadata row */}
        <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted">
          {job.remote_classification && (
            <span className="flex items-center gap-1">
              <RemoteBadge remote={job.remote_classification} />
            </span>
          )}
          {job.location && <span>{job.location}</span>}
          {renderSalary(job)}
        </div>
      </div>
    </div>
  )
}

function RemoteBadge({ remote }: { remote: string }) {
  const label =
    remote === 'remote' || remote === 'fully_remote'
      ? 'Remote'
      : remote === 'hybrid'
        ? 'Hybrid'
        : remote === 'onsite' || remote === 'onsite_disguised'
          ? 'Onsite'
          : remote === 'location_restricted'
            ? 'Location-only'
            : remote === 'unclear'
              ? 'Unclear'
              : remote.replace(/_/g, ' ')
  const variant =
    remote === 'remote' || remote === 'fully_remote'
      ? 'score_high'
      : remote === 'hybrid'
        ? 'score_mid'
        : 'secondary'
  return (
    <Badge variant={variant} className="text-[10px] px-1.5 py-0">
      {label}
    </Badge>
  )
}

function renderSalary(job: JobSummary): string | null {
  if (job.salary_min_usd == null) return null
  const min = job.salary_min_usd
  const max = job.salary_max_usd ?? min
  const period =
    job.salary_period === 'year' ? '' : job.salary_period ? `/${job.salary_period}` : ''
  const fmt = (n: number) => (n >= 1000 ? `${Math.round(n / 1000)}k` : String(n))
  return min === max ? `$${fmt(min)}${period}` : `$${fmt(min)}–$${fmt(max)}${period}`
}
