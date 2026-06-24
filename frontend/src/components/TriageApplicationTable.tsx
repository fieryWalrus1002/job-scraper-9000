import { useState, type ReactNode } from 'react'
import { useApplications } from '../hooks/useApplications'
import { STATUS_LABELS, type Application, type ApplicationStatus } from '../types'
import type { components } from '../schema.gen'
import { Badge } from './ui/badge'
import { useSwipe } from '@/lib/swipe/useSwipe'
import { SwipeAffordance } from '@/lib/swipe/SwipeAffordance'
import { useTriageAction, type TriageTarget } from '../hooks/useTriage'
import { ArrowRight, ArrowUp, Trash2 } from 'lucide-react'

type LatestEvent = components['schemas']['LatestEvent']

type ApplicationSortCol = 'status' | 'title' | 'score' | 'updated'
type SortDir = 'asc' | 'desc'

/** Per-direction swipe commit target; omit a direction to make it a no-op. */
export interface RowSwipeActions {
  left?: { to: TriageTarget; label: string; polarity: 'positive' | 'negative' }
  right?: { to: TriageTarget; label: string; polarity: 'positive' | 'negative' }
}

interface Props {
  statuses: ApplicationStatus[]
  onSelect: (application: Application) => void
  emptyMessage: string
  /** Optional per-row actions; when set, a trailing actions column is rendered. */
  renderRowActions?: (application: Application) => ReactNode
  /** Optional swipe-to-triage mapping per direction. */
  swipeActions?: RowSwipeActions
}

/**
 * Status-filtered application list for a funnel tab. Fetches its own bucket and
 * handles loading/error/empty; delegates row rendering to {@link ApplicationTable}.
 */
export function TriageApplicationTable({
  statuses,
  onSelect,
  emptyMessage,
  renderRowActions,
  swipeActions,
}: Props) {
  const { data, isLoading, isError, error } = useApplications(statuses)

  if (isLoading) return <div className="py-12 text-center text-muted text-sm">Loading…</div>
  if (isError) {
    return (
      <div className="py-12 text-center text-score-low text-sm">
        Failed to load applications: {(error as Error).message}
      </div>
    )
  }

  const applications = Array.from(data?.values() ?? [])
  if (applications.length === 0) {
    return (
      <div className="py-20 text-center">
        <div className="text-muted text-sm">{emptyMessage}</div>
        <div className="text-faint text-xs mt-1.5">
          Jobs will appear here when their status matches this tab.
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-auto">
      <ApplicationTable
        applications={applications}
        onSelect={onSelect}
        renderRowActions={renderRowActions}
        swipeActions={swipeActions}
      />
    </div>
  )
}

interface ApplicationTableProps {
  applications: Application[]
  onSelect: (application: Application) => void
  renderRowActions?: (application: Application) => ReactNode
  swipeActions?: RowSwipeActions
}

// ── Row components ──────────────────────────────────────────────────────────

// Shared cell content — rendered inside either a plain <tr> or a swipeable wrapper.
function AppRowCells({ app }: { app: Application }) {
  return (
    <>
      <td>
        <Badge variant="secondary">{STATUS_LABELS[app.status]}</Badge>
      </td>
      <td>
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="overflow-hidden text-ellipsis whitespace-nowrap flex-1 min-w-0 text-fg">
            {app.title ?? '—'}
          </span>
          {app.source_url && (
            <a
              className="shrink-0 text-[11px] text-faint no-underline leading-none hover:text-primary-hov transition-colors"
              href={app.source_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              title="Open job posting"
            >
              ↗
            </a>
          )}
        </div>
        <span className="text-muted text-[11px]">{app.company ?? '—'}</span>
      </td>
      <td>
        {app.fit_score != null ? (
          <Badge
            variant={
              app.fit_score >= 4 ? 'score_high' : app.fit_score === 3 ? 'score_mid' : 'score_low'
            }
            className="font-mono"
          >
            {app.fit_score}
          </Badge>
        ) : (
          <span className="text-faint">—</span>
        )}
      </td>
      <td>
        <span className="truncate block text-muted font-mono text-[11px]">
          {new Date(app.updated_at).toLocaleDateString()}
        </span>
      </td>
      <td>
        <span className="truncate block text-muted text-[12px]">
          {renderLatestActivity(app.latest_event)}
        </span>
      </td>
    </>
  )
}

// Plain (non-swipeable) row — used by TrackingBoard and surfaces without swipe.
function AppRowContent({
  app,
  onSelect,
  renderRowActions,
}: {
  app: Application
  onSelect: (application: Application) => void
  renderRowActions?: (application: Application) => ReactNode
}) {
  return (
    <tr className="cursor-pointer transition-colors hover:bg-hover" onClick={() => onSelect(app)}>
      <AppRowCells app={app} />
      {renderRowActions && (
        <td
          className="text-right pr-3"
          onClick={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
        >
          <div className="inline-flex justify-end">{renderRowActions(app)}</div>
        </td>
      )}
    </tr>
  )
}

// Icon + color mapping for swipe action labels.
const SWIPE_ACTION_VISUALS: Record<string, { icon: typeof Trash2; color: string }> = {
  Trash: { icon: Trash2, color: 'var(--color-score-low)' },
  'Un-trash': { icon: ArrowUp, color: 'var(--color-score-mid)' },
  Pursue: { icon: ArrowRight, color: 'var(--color-score-mid)' },
}

// Swipeable application row — wraps the row in swipe gesture handlers and
// reveals an affordance as the row slides. When swipeActions is set, the row
// responds to horizontal drag; otherwise it falls back to plain tap-to-select.
function SwipeableAppRow({
  app,
  onSelect,
  renderRowActions,
  swipeActions,
}: {
  app: Application
  onSelect: (application: Application) => void
  renderRowActions?: (application: Application) => ReactNode
  swipeActions: RowSwipeActions
}) {
  const { triage } = useTriageAction()

  const activeDir =
    swipeActions.left && swipeActions.right
      ? null
      : swipeActions.left
        ? 'right'
        : swipeActions.right
          ? 'left'
          : null

  const { offset, progress, armed, direction, settling, handlers, consumeClickSuppression } =
    useSwipe({
      onCommit: (dir) => {
        const action = swipeActions[dir]
        if (!action) return
        triage({ dedupHash: app.dedup_hash, from: app.status, to: action.to })
      },
    })

  const tint = direction
    ? `color-mix(in oklab, ${
        swipeActions[direction]?.polarity === 'negative'
          ? 'var(--color-score-low)'
          : 'var(--color-score-mid)'
      } ${armed ? 22 : 6 + progress * 10}%, transparent)`
    : undefined
  const edgeCell = direction ? { overflow: 'visible' as const } : undefined

  return (
    <tr
      {...handlers}
      className="cursor-pointer hover:bg-hover"
      style={{
        position: 'relative',
        transform: direction ? `translateX(${offset}px)` : undefined,
        backgroundColor: tint,
        touchAction: 'pan-y',
        ...(settling
          ? { transition: 'transform 150ms ease-out, background-color 150ms ease-out' }
          : {}),
      }}
      onClick={() => {
        if (consumeClickSuppression()) return
        onSelect(app)
      }}
    >
      {activeDir && swipeActions[activeDir] && (
        <td className="w-11 max-w-11" style={edgeCell}>
          <SwipeAffordance
            direction={activeDir}
            progress={progress}
            armed={armed}
            offset={offset}
            label={swipeActions[activeDir].label}
            {...SWIPE_ACTION_VISUALS[swipeActions[activeDir].label]}
          />
        </td>
      )}
      <AppRowCells app={app} />
      {renderRowActions && (
        <td
          className="text-right pr-3"
          onClick={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
          style={edgeCell}
        >
          <div className="inline-flex justify-end">{renderRowActions(app)}</div>
        </td>
      )}
      {activeDir && swipeActions[activeDir] && (
        <td className="w-11 max-w-11" style={edgeCell}>
          <SwipeAffordance
            direction={activeDir}
            progress={progress}
            armed={armed}
            offset={offset}
            label={swipeActions[activeDir].label}
            {...SWIPE_ACTION_VISUALS[swipeActions[activeDir].label]}
          />
        </td>
      )}
    </tr>
  )
}

// ── Table component ─────────────────────────────────────────────────────────

/**
 * Presentational, sortable table of applications. Does no fetching — callers pass
 * the rows in, so it can back a single tab or one group of a multi-group board.
 */
export function ApplicationTable({
  applications,
  onSelect,
  renderRowActions,
  swipeActions,
}: ApplicationTableProps) {
  const [sortCol, setSortCol] = useState<ApplicationSortCol>('updated')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const visible = sortApplications(applications, sortCol, sortDir)

  function handleSort(col: ApplicationSortCol) {
    if (sortCol === col) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortCol(col)
      setSortDir(col === 'updated' ? 'desc' : 'asc')
    }
  }

  function sortIndicator(col: ApplicationSortCol) {
    if (sortCol !== col) return <span className="text-muted text-[10px]"> ↕</span>
    return sortDir === 'asc' ? ' ↑' : ' ↓'
  }

  return (
    <table className="job-table [&_td]:max-w-none">
      <colgroup>
        <col style={{ width: '160px' }} />
        <col style={{ width: '40%' }} />
        <col style={{ width: '70px' }} />
        <col style={{ width: '110px' }} />
        <col />
        {renderRowActions && <col style={{ width: '150px' }} />}
      </colgroup>
      <thead>
        <tr>
          <th className="col-sortable" onClick={() => handleSort('status')}>
            Status{sortIndicator('status')}
          </th>
          <th className="col-sortable" onClick={() => handleSort('title')}>
            Job{sortIndicator('title')}
          </th>
          <th className="col-sortable" onClick={() => handleSort('score')}>
            Score{sortIndicator('score')}
          </th>
          <th className="col-sortable" onClick={() => handleSort('updated')}>
            Updated{sortIndicator('updated')}
          </th>
          <th>Latest activity</th>
          {renderRowActions && <th className="text-right pr-3">Actions</th>}
        </tr>
      </thead>
      <tbody>
        {visible.map((app) =>
          swipeActions ? (
            <SwipeableAppRow
              key={app.dedup_hash}
              app={app}
              onSelect={onSelect}
              renderRowActions={renderRowActions}
              swipeActions={swipeActions}
            />
          ) : (
            <AppRowContent
              key={app.dedup_hash}
              app={app}
              onSelect={onSelect}
              renderRowActions={renderRowActions}
            />
          ),
        )}
      </tbody>
    </table>
  )
}

const MINUTE = 60
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR
const WEEK = 7 * DAY

function relativeTime(iso: string): string {
  const diff = (Date.now() - Date.parse(iso)) / 1000
  if (diff < 0) return 'just now'
  if (diff < 60) return 'just now'
  if (diff < 5 * MINUTE) return `${Math.floor(diff / MINUTE)}m ago`
  if (diff < 45 * MINUTE) return `${Math.floor(diff / MINUTE)}m ago`
  if (diff < 2 * HOUR) return '1h ago'
  if (diff < 24 * HOUR) return `${Math.floor(diff / HOUR)}h ago`
  if (diff < 30 * DAY) return `${Math.floor(diff / DAY)}d ago`
  return `${Math.floor(diff / WEEK)}w ago`
}

function renderLatestActivity(ev: LatestEvent | null | undefined): ReactNode {
  if (!ev) return <span className="text-faint">—</span>

  const time = relativeTime(ev.occurred_at)

  if (ev.kind === 'status_change') {
    const label = STATUS_LABELS[ev.to_status as ApplicationStatus] ?? ev.to_status ?? 'Unknown'
    return (
      <>
        Entered {label} <span className="text-faint">· {time}</span>
      </>
    )
  }

  // kind === 'event'
  const body = ev.body?.trim() ?? ''
  return (
    <>
      {body ? <span className="truncate">{body}</span> : <span className="text-faint">—</span>}{' '}
      <span className="text-faint">· {time}</span>
    </>
  )
}

function sortApplications(
  rows: Application[],
  col: ApplicationSortCol,
  dir: SortDir,
): Application[] {
  return [...rows].sort((a, b) => {
    let cmp = 0
    switch (col) {
      case 'status':
        cmp = a.status.localeCompare(b.status)
        break
      case 'title':
        cmp = (a.title ?? '').localeCompare(b.title ?? '')
        break
      case 'score':
        cmp = (a.fit_score ?? -1) - (b.fit_score ?? -1)
        break
      case 'updated':
        cmp = a.updated_at.localeCompare(b.updated_at)
        break
    }
    return dir === 'asc' ? cmp : -cmp
  })
}
