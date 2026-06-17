import { useEffect, useRef, useState, type ReactNode } from 'react'
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnOrderState,
  type ColumnSizingState,
  type Row,
} from '@tanstack/react-table'
import type { Application, ApplicationStatus, JobSummary } from '../types'
import {
  loadColumnOrder,
  loadColumnSizing,
  saveColumnOrder,
  saveColumnSizing,
  sortKeyForColumn,
  tableColumns,
} from '../lib/columns'
import { useTriageAction } from '../hooks/useTriage'
import { useRowSwipe } from './JobTable/useRowSwipe'
import { useTriageKeys } from './JobTable/useTriageKeys'
import { TitleCell } from './JobTable/cells/TitleCell'
import { PostedAtCell } from './JobTable/cells/PostedAtCell'
import { RationaleCell } from './JobTable/cells/RationaleCell'
import { DefaultCell } from './JobTable/cells/DefaultCell'
import { SalaryCell } from './JobTable/cells/SalaryCell'
import { Star, Trash2 } from 'lucide-react'
import ContextMenu from './ContextMenu'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { defaultDirectionFor, type SortKey, type SortOrder, type SortState } from '@/lib/sort'

interface Props {
  items: JobSummary[]
  visibleColumns: Set<string>
  onSelect: (hash: string) => void
  applications?: Map<string, Application>
  page: number
  pageSize: number
  total: number | undefined
  onPageChange: (page: number) => void
  sort: SortState
  onSortChange: (next: SortState) => void
}

interface ContextState {
  x: number
  y: number
  job: JobSummary
}

// ── Badge helpers ───────────────────────────────────────────────────────────

function ScoreBadge({ score }: { score: number | null }) {
  if (score === null) {
    return (
      <span className="inline-flex items-center justify-center size-7 rounded-md text-[13px] font-mono text-faint border border-border/40">
        —
      </span>
    )
  }
  const cls =
    score >= 4
      ? 'bg-score-high/15 text-score-high border-score-high/30 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]'
      : score === 3
        ? 'bg-score-mid/15 text-score-mid border-score-mid/30 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]'
        : 'bg-score-low/15 text-score-low border-score-low/30 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]'
  return (
    <span
      className={cn(
        'inline-flex items-center justify-center size-7 rounded-md text-[14px] font-mono font-semibold border tabular-nums',
        cls,
      )}
    >
      {score}
    </span>
  )
}

function ClassificationBadge({ value }: { value: string | null }) {
  if (!value) return <span className="text-faint">—</span>
  const label = value.replace(/_/g, ' ')
  const variant =
    value === 'fully_remote'
      ? 'remote'
      : value === 'location_restricted'
        ? 'local'
        : value.startsWith('remote_with')
          ? 'travel'
          : 'muted'
  return <Badge variant={variant}>{label}</Badge>
}

function ConfidenceBadge({ value }: { value: string | null }) {
  if (!value) return <span className="text-faint">—</span>
  const cls =
    value === 'high' ? 'text-score-high' : value === 'medium' ? 'text-score-mid' : 'text-score-low'
  return (
    <span className={cn('text-[11px] uppercase tracking-wider font-medium', cls)}>{value}</span>
  )
}

// Faint indicator on every sortable header; brightened and flipped to match
// direction on the column currently driving the server-side sort.
function SortArrow({ active, order }: { active: boolean; order: SortOrder }) {
  const glyph = active ? (order === 'asc' ? '▲' : '▼') : '▾'
  return (
    <span
      aria-hidden="true"
      className={cn(
        'ml-1 inline-block text-[9px] align-middle transition-colors',
        active ? 'text-fg' : 'text-faint/50',
      )}
    >
      {glyph}
    </span>
  )
}

function renderCell(key: string, job: JobSummary): ReactNode {
  switch (key) {
    case 'fit_score':
      return <ScoreBadge score={job.fit_score} />
    case 'title':
      return <TitleCell job={job} />
    case 'remote_classification':
      return <ClassificationBadge value={job.remote_classification} />
    case 'confidence':
      return <ConfidenceBadge value={job.confidence} />
    case 'posted_at':
      return <PostedAtCell value={job.posted_at} />
    case 'salary_min_usd':
      return <SalaryCell job={job} />
    case 'score_rationale':
      return <RationaleCell value={job.score_rationale} />
    default:
      return <DefaultCell value={(job[key as keyof JobSummary] as string | null) ?? null} />
  }
}

// ── Quick-mark column ───────────────────────────────────────────────────────

const qBtn =
  'text-[11px] font-medium px-2 h-[22px] rounded-md border border-border bg-card text-muted cursor-pointer whitespace-nowrap ' +
  'hover:border-border-strong hover:text-fg disabled:opacity-40 disabled:cursor-default transition-all'
const qBtnActive =
  'bg-primary/15 border-primary/40 text-primary-hov shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]'

function QuickMark({
  dedupHash,
  current,
}: {
  dedupHash: string
  current: ApplicationStatus | undefined
}) {
  const { triage, isPending } = useTriageAction()
  // Jobs is the funnel's fast binary: Trash (passed) or Shortlist (maybe).
  // Forward moves into Tracking (to_apply etc.) happen from the Shortlist/Tracking tabs.
  const buttons: { status: ApplicationStatus; label: string }[] = [
    { status: 'passed', label: 'Trash' },
    { status: 'maybe', label: 'Shortlist' },
  ]
  return (
    // Stop pointer/click bubbling so pressing a Track button never starts a row
    // swipe or opens the detail panel.
    <div
      className="flex gap-1"
      onClick={(e) => e.stopPropagation()}
      onPointerDown={(e) => e.stopPropagation()}
    >
      {buttons.map(({ status, label }) => (
        <button
          key={status}
          className={cn(qBtn, current === status && qBtnActive)}
          disabled={isPending}
          onClick={() => triage({ dedupHash, from: current ?? null, to: status })}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

// ── Swipeable row ─────────────────────────────────────────────────────────────

const SWIPE_ACTIONS = {
  left: { label: 'Trash', icon: Trash2, color: 'var(--color-score-low)' },
  right: { label: 'Shortlist', icon: Star, color: 'var(--color-score-mid)' },
} as const

// The action affordance revealed in the gap a swipe opens up. It lives inside an
// edge cell (which we let overflow) but counter-translates by the row's offset so
// it stays pinned at the table edge — i.e. it appears to sit still while the row
// slides off it. Fades/scales in with progress and flips to a solid "armed" fill
// once releasing would commit.
function SwipeAffordance({
  direction,
  progress,
  armed,
  offset,
}: {
  direction: 'left' | 'right'
  progress: number
  armed: boolean
  offset: number
}) {
  const { label, icon: Icon, color } = SWIPE_ACTIONS[direction]
  return (
    <span
      aria-hidden
      className="pointer-events-none absolute top-1/2 z-20 flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold whitespace-nowrap"
      style={{
        [direction === 'left' ? 'right' : 'left']: 12,
        transform: `translateY(-50%) translateX(${-offset}px) scale(${0.85 + progress * 0.15})`,
        opacity: Math.min(progress * 1.5, 1),
        color: armed ? '#fff' : color,
        backgroundColor: armed ? color : `color-mix(in oklab, ${color} 16%, transparent)`,
      }}
    >
      <Icon className="size-3.5" />
      {label}
    </span>
  )
}

// A single Jobs-feed row. Swipe left = Trash, right = Shortlist — both route
// through the same triage primitive as the buttons, so undo comes for free. The
// row slides (rubber-banded), tints toward the action color, and reveals an
// armed affordance once releasing would commit.
function JobRow({
  row,
  rank,
  appStatus,
  focused,
  onSelect,
  onContextMenu,
  triage,
}: {
  row: Row<JobSummary>
  rank: number
  appStatus: ApplicationStatus | undefined
  focused: boolean
  onSelect: (hash: string) => void
  onContextMenu: (job: JobSummary, x: number, y: number) => void
  triage: ReturnType<typeof useTriageAction>['triage']
}) {
  const job = row.original
  const rowRef = useRef<HTMLTableRowElement>(null)

  // Keep the keyboard cursor on screen as it moves through a long feed.
  useEffect(() => {
    if (focused) rowRef.current?.scrollIntoView({ block: 'nearest' })
  }, [focused])
  const { offset, progress, armed, direction, settling, handlers, consumeClickSuppression } =
    useRowSwipe({
      onCommit: (dir) =>
        triage({
          dedupHash: job.dedup_hash,
          from: appStatus ?? null,
          to: dir === 'left' ? 'passed' : 'maybe',
        }),
    })

  const tint = direction
    ? `color-mix(in oklab, ${SWIPE_ACTIONS[direction].color} ${armed ? 22 : 6 + progress * 10}%, transparent)`
    : undefined
  // Edge cells host the affordance, so they must not clip it.
  const edgeCell = direction
    ? { position: 'relative' as const, overflow: 'visible' as const }
    : undefined

  return (
    <tr
      ref={rowRef}
      {...handlers}
      className={cn(
        'cursor-pointer hover:bg-hover',
        // Keyboard cursor: a left accent bar + subtle fill, distinct from hover.
        focused && 'bg-hover shadow-[inset_2px_0_0_var(--color-primary)]',
        settling
          ? 'transition-[transform,background-color] duration-150 ease-out'
          : 'transition-colors',
      )}
      style={{
        transform: direction ? `translateX(${offset}px)` : undefined,
        backgroundColor: tint,
        touchAction: 'pan-y',
      }}
      onClick={() => {
        // A horizontal swipe also fires a click on release; swallow that one.
        if (consumeClickSuppression()) return
        onSelect(job.dedup_hash)
      }}
      onContextMenu={(e) => {
        e.preventDefault()
        onContextMenu(job, e.clientX, e.clientY)
      }}
    >
      <td className="w-11 max-w-11 text-right text-muted" style={edgeCell}>
        {direction === 'right' && (
          <SwipeAffordance direction="right" progress={progress} armed={armed} offset={offset} />
        )}
        {rank}
      </td>
      {row.getVisibleCells().map((cell) => (
        <td key={cell.id} style={{ width: cell.column.getSize(), maxWidth: cell.column.getSize() }}>
          {renderCell(cell.column.id, job)}
        </td>
      ))}
      <td className="w-[220px] min-w-[220px] max-w-[220px]" style={edgeCell}>
        {direction === 'left' && (
          <SwipeAffordance direction="left" progress={progress} armed={armed} offset={offset} />
        )}
        <QuickMark dedupHash={job.dedup_hash} current={appStatus} />
      </td>
    </tr>
  )
}

// ── Main component ──────────────────────────────────────────────────────────

export default function JobTable({
  items,
  visibleColumns,
  onSelect,
  applications,
  page,
  pageSize,
  total,
  onPageChange,
  sort,
  onSortChange,
}: Props) {
  const [columnOrder, setColumnOrder] = useState<ColumnOrderState>(loadColumnOrder)
  const [columnSizing, setColumnSizing] = useState<ColumnSizingState>(loadColumnSizing)
  const [ctx, setCtx] = useState<ContextState | null>(null)
  const { triage } = useTriageAction()

  // Single-key triage on the focused row — the keyboard twin of the swipe
  // gestures, routed through the same triage primitive so undo comes for free.
  const { focusedIndex } = useTriageKeys({
    count: items.length,
    onTrash: (i) =>
      triage({
        dedupHash: items[i].dedup_hash,
        from: applications?.get(items[i].dedup_hash)?.status ?? null,
        to: 'passed',
      }),
    onShortlist: (i) =>
      triage({
        dedupHash: items[i].dedup_hash,
        from: applications?.get(items[i].dedup_hash)?.status ?? null,
        to: 'maybe',
      }),
    onOpen: (i) => onSelect(items[i].dedup_hash),
  })

  const columnVisibility = Object.fromEntries(
    tableColumns.map((col) => [col.id!, visibleColumns.has(col.id!)]),
  )

  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: items,
    columns: tableColumns,
    state: { columnOrder, columnSizing, columnVisibility },
    getRowId: (row) => row.dedup_hash,
    onColumnOrderChange: (updater) => {
      setColumnOrder((prev) => {
        const next = typeof updater === 'function' ? updater(prev) : updater
        saveColumnOrder(next)
        return next
      })
    },
    onColumnSizingChange: (updater) => {
      setColumnSizing((prev) => {
        const next = typeof updater === 'function' ? updater(prev) : updater
        saveColumnSizing(next)
        return next
      })
    },
    getCoreRowModel: getCoreRowModel(),
    columnResizeMode: 'onChange',
  })

  const dragCol = useRef<string | null>(null)
  const isResizing = useRef(false)
  // mouseup listeners added during a column resize self-remove on release, but
  // if the component unmounts mid-resize that release never fires and the
  // listener leaks. Track each removal fn so unmount can clear any in flight.
  const resizeCleanups = useRef<Set<() => void>>(new Set())
  useEffect(() => {
    const cleanups = resizeCleanups.current
    return () => {
      cleanups.forEach((remove) => remove())
      cleanups.clear()
    }
  }, [])
  const totalPages = total && total > 0 ? Math.ceil(total / pageSize) : 0

  function toggleSort(key: SortKey) {
    if (sort.sort === key) {
      onSortChange({ sort: key, order: sort.order === 'asc' ? 'desc' : 'asc' })
    } else {
      onSortChange({ sort: key, order: defaultDirectionFor(key) })
    }
  }

  if (items.length === 0) {
    return (
      <div className="py-20 text-center">
        <div className="text-muted text-sm">No jobs match the current filters.</div>
        <div className="text-faint text-xs mt-1">
          Adjust your filters in the sidebar to widen the search.
        </div>
      </div>
    )
  }

  return (
    <div className="table-outer">
      <div className="table-wrapper">
        <table className="job-table" style={{ width: '100%' }}>
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                <th
                  className="w-11 max-w-11 text-right"
                  // The number is the row's position on this page, not a global
                  // rank — clarify on hover since the column is too narrow to say so.
                  title="Position on this page"
                >
                  #
                </th>
                {hg.headers.map((header, i) => {
                  const prevHeader = i > 0 ? hg.headers[i - 1] : null
                  const isLast = i === hg.headers.length - 1
                  const sortKey = sortKeyForColumn(header.column.id)
                  const sortActive = sortKey != null && sort.sort === sortKey
                  const startResize = (h: typeof header) => (e: React.MouseEvent) => {
                    isResizing.current = true
                    h.getResizeHandler()(e)
                    const reset = () => {
                      isResizing.current = false
                      window.removeEventListener('mouseup', reset)
                      resizeCleanups.current.delete(remove)
                    }
                    const remove = () => window.removeEventListener('mouseup', reset)
                    resizeCleanups.current.add(remove)
                    window.addEventListener('mouseup', reset)
                  }
                  return (
                    <th
                      key={header.id}
                      style={{ position: 'relative', width: header.getSize() }}
                      className="cursor-pointer select-none hover:text-fg"
                      aria-sort={
                        sortActive ? (sort.order === 'asc' ? 'ascending' : 'descending') : undefined
                      }
                      onClick={() => {
                        // Resize handles stopPropagation; a drag won't fire click.
                        if (sortKey && !isResizing.current) toggleSort(sortKey)
                      }}
                      draggable
                      onDragStart={(e) => {
                        if (isResizing.current) {
                          e.preventDefault()
                          return
                        }
                        dragCol.current = header.column.id
                      }}
                      onDragEnd={() => {
                        dragCol.current = null
                      }}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={() => {
                        if (!dragCol.current || dragCol.current === header.column.id) return
                        const order = table.getState().columnOrder
                        const from = order.indexOf(dragCol.current)
                        const to = order.indexOf(header.column.id)
                        if (from === -1 || to === -1) {
                          dragCol.current = null
                          return
                        }
                        const next = [...order]
                        next.splice(from, 1)
                        next.splice(to, 0, dragCol.current)
                        table.setColumnOrder(next)
                        dragCol.current = null
                      }}
                    >
                      {prevHeader?.column.getCanResize() && (
                        <div
                          className="col-resize-handle col-resize-handle--left"
                          onMouseDown={startResize(prevHeader)}
                          onTouchStart={(e) =>
                            prevHeader.getResizeHandler()(e as unknown as React.MouseEvent)
                          }
                          onClick={(e) => e.stopPropagation()}
                        />
                      )}
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {sortKey && <SortArrow active={sortActive} order={sort.order} />}
                      {isLast && header.column.getCanResize() && (
                        <div
                          className="col-resize-handle"
                          onMouseDown={startResize(header)}
                          onTouchStart={header.getResizeHandler()}
                          onClick={(e) => e.stopPropagation()}
                        />
                      )}
                    </th>
                  )
                })}
                <th className="w-[220px] min-w-[220px] max-w-[220px]">Track</th>
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row, i) => (
              <JobRow
                key={row.id}
                row={row}
                rank={page * pageSize + i + 1}
                appStatus={applications?.get(row.original.dedup_hash)?.status}
                focused={i === focusedIndex}
                onSelect={onSelect}
                onContextMenu={(job, x, y) => setCtx({ x, y, job })}
                triage={triage}
              />
            ))}
          </tbody>
        </table>
      </div>

      {ctx && (
        <ContextMenu
          x={ctx.x}
          y={ctx.y}
          onClose={() => setCtx(null)}
          items={[
            {
              label: 'Trash',
              active: applications?.get(ctx.job.dedup_hash)?.status === 'passed',
              onClick: () =>
                triage({
                  dedupHash: ctx.job.dedup_hash,
                  from: applications?.get(ctx.job.dedup_hash)?.status ?? null,
                  to: 'passed',
                }),
            },
            {
              label: 'Shortlist',
              active: applications?.get(ctx.job.dedup_hash)?.status === 'maybe',
              onClick: () =>
                triage({
                  dedupHash: ctx.job.dedup_hash,
                  from: applications?.get(ctx.job.dedup_hash)?.status ?? null,
                  to: 'maybe',
                }),
            },
          ]}
        />
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-1 p-3 border-t border-border shrink-0 bg-card/40">
          <Button
            variant="secondary"
            size="icon-sm"
            onClick={() => onPageChange(0)}
            disabled={page === 0}
          >
            «
          </Button>
          <Button
            variant="secondary"
            size="icon-sm"
            onClick={() => onPageChange(page - 1)}
            disabled={page === 0}
          >
            ‹
          </Button>
          <span className="text-[12px] text-muted px-3 font-mono tabular-nums">
            <span className="text-fg">{page + 1}</span>
            <span className="text-faint mx-1">/</span>
            {totalPages}
          </span>
          <Button
            variant="secondary"
            size="icon-sm"
            onClick={() => onPageChange(page + 1)}
            disabled={page >= totalPages - 1}
          >
            ›
          </Button>
          <Button
            variant="secondary"
            size="icon-sm"
            onClick={() => onPageChange(totalPages - 1)}
            disabled={page >= totalPages - 1}
          >
            »
          </Button>
        </div>
      )}
    </div>
  )
}
