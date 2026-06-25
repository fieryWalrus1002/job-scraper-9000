import { useState, type ComponentType, type ReactNode } from 'react'
import { useApplications } from '../hooks/useApplications'
import { STATUS_LABELS, type Application, type ApplicationStatus } from '../types'
import type { components } from '../schema.gen'
import { Badge } from './ui/badge'
import { useSwipe } from '@/lib/swipe/useSwipe'
import { SwipeAffordance } from '@/lib/swipe/SwipeAffordance'
import { useTriageAction, type TriageTarget } from '../hooks/useTriage'

type LatestEvent = components['schemas']['LatestEvent']

type ApplicationSortCol = 'status' | 'title' | 'score' | 'updated'
type SortDir = 'asc' | 'desc'

/** A single swipe direction's commit + affordance. The defining surface owns the
 *  glyph, so there is no label→icon lookup to keep in sync (and nothing to crash
 *  on a missing entry). `polarity` drives the tint/affordance color. */
export interface RowSwipeAction {
  to: TriageTarget
  label: string
  polarity: 'positive' | 'negative'
  icon?: ComponentType<{ className?: string }>
}

/** Per-direction swipe mapping; omit a direction to make it a no-op. */
export interface RowSwipeActions {
  left?: RowSwipeAction
  right?: RowSwipeAction
}

// Tint/affordance color for a swipe action, derived from its polarity.
function polarityColor(polarity: 'positive' | 'negative'): string {
  return polarity === 'negative' ? 'var(--color-score-low)' : 'var(--color-score-mid)'
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
// `leading`/`trailing` host the swipe affordance inside the first/last existing
// cell (it's absolutely positioned against the row, so it pins to the row edge);
// this keeps the column count identical to a non-swiping row — no extra <td>s.
function AppRowCells({
  app,
  leading,
  trailing,
}: {
  app: Application
  leading?: ReactNode
  trailing?: ReactNode
}) {
  return (
    <>
      <td>
        {leading}
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
        {trailing}
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

  const { offset, progress, armed, direction, settling, handlers, consumeClickSuppression } =
    useSwipe({
      onCommit: (dir) => {
        const action = swipeActions[dir]
        if (!action) return
        triage({ dedupHash: app.dedup_hash, from: app.status, to: action.to })
      },
    })

  const activeAction = direction ? swipeActions[direction] : undefined
  const tint = activeAction
    ? `color-mix(in oklab, ${polarityColor(activeAction.polarity)} ${
        armed ? 22 : 6 + progress * 10
      }%, transparent)`
    : undefined

  // The affordance pins to the row edge (absolute vs the relative <tr>), so it
  // lives inside an existing edge cell rather than adding a column.
  const affordance = (dir: 'left' | 'right') => {
    if (direction !== dir) return undefined
    const action = swipeActions[dir]
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
      <AppRowCells app={app} leading={affordance('right')} trailing={affordance('left')} />
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
