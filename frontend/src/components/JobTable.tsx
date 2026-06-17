import { useRef, useState, type ReactNode } from 'react'
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnOrderState,
  type ColumnSizingState,
} from '@tanstack/react-table'
import type { Application, ApplicationStatus, JobSummary } from '../types'
import {
  loadColumnOrder,
  loadColumnSizing,
  saveColumnOrder,
  saveColumnSizing,
  tableColumns,
} from '../lib/columns'
import { useMarkApplication } from '../hooks/useApplications'
import { TitleCell } from './JobTable/cells/TitleCell'
import { PostedAtCell } from './JobTable/cells/PostedAtCell'
import { RationaleCell } from './JobTable/cells/RationaleCell'
import { DefaultCell } from './JobTable/cells/DefaultCell'
import ContextMenu from './ContextMenu'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface Props {
  items: JobSummary[]
  visibleColumns: Set<string>
  onSelect: (hash: string) => void
  applications?: Map<string, Application>
  page: number
  pageSize: number
  total: number | undefined
  onPageChange: (page: number) => void
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

function QuickMark({ dedupHash, current }: { dedupHash: string; current: string | undefined }) {
  const { mutate, isPending } = useMarkApplication()
  // Jobs is the funnel's fast binary: Trash (passed) or Shortlist (maybe).
  // Forward moves into Tracking (to_apply etc.) happen from the Shortlist/Tracking tabs.
  const buttons: { status: ApplicationStatus; label: string }[] = [
    { status: 'passed', label: 'Trash' },
    { status: 'maybe', label: 'Shortlist' },
  ]
  return (
    <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
      {buttons.map(({ status, label }) => (
        <button
          key={status}
          className={cn(qBtn, current === status && qBtnActive)}
          disabled={isPending}
          onClick={() => mutate({ dedupHash, status })}
        >
          {label}
        </button>
      ))}
    </div>
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
}: Props) {
  const [columnOrder, setColumnOrder] = useState<ColumnOrderState>(loadColumnOrder)
  const [columnSizing, setColumnSizing] = useState<ColumnSizingState>(loadColumnSizing)
  const [ctx, setCtx] = useState<ContextState | null>(null)
  const { mutate: mark } = useMarkApplication()

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
  const totalPages = total && total > 0 ? Math.ceil(total / pageSize) : 0

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
                <th className="w-11 max-w-11 text-right">#</th>
                {hg.headers.map((header, i) => {
                  const prevHeader = i > 0 ? hg.headers[i - 1] : null
                  const isLast = i === hg.headers.length - 1
                  const startResize = (h: typeof header) => (e: React.MouseEvent) => {
                    isResizing.current = true
                    h.getResizeHandler()(e)
                    const reset = () => {
                      isResizing.current = false
                      window.removeEventListener('mouseup', reset)
                    }
                    window.addEventListener('mouseup', reset)
                  }
                  return (
                    <th
                      key={header.id}
                      style={{ position: 'relative', width: header.getSize() }}
                      className="cursor-pointer select-none hover:text-fg"
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
            {table.getRowModel().rows.map((row, i) => {
              const job = row.original
              const appStatus = applications?.get(job.dedup_hash)?.status
              const rank = page * pageSize + i + 1
              return (
                <tr
                  key={row.id}
                  className={cn(
                    'cursor-pointer transition-colors hover:bg-hover',
                    appStatus && 'bg-primary-dim/15',
                  )}
                  onClick={() => onSelect(job.dedup_hash)}
                  onContextMenu={(e) => {
                    e.preventDefault()
                    setCtx({ x: e.clientX, y: e.clientY, job })
                  }}
                >
                  <td className="w-11 max-w-11 text-right text-muted">{rank}</td>
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      style={{ width: cell.column.getSize(), maxWidth: cell.column.getSize() }}
                    >
                      {renderCell(cell.column.id, job)}
                    </td>
                  ))}
                  <td className="w-[220px] min-w-[220px] max-w-[220px]">
                    <QuickMark dedupHash={job.dedup_hash} current={appStatus} />
                  </td>
                </tr>
              )
            })}
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
              onClick: () => mark({ dedupHash: ctx.job.dedup_hash, status: 'passed' }),
            },
            {
              label: 'Shortlist',
              active: applications?.get(ctx.job.dedup_hash)?.status === 'maybe',
              onClick: () => mark({ dedupHash: ctx.job.dedup_hash, status: 'maybe' }),
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
