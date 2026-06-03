import { useRef, useState, type ReactNode } from 'react'
import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnOrderState,
  type ColumnSizingState,
  type SortingState,
} from '@tanstack/react-table'
import type { Application, ApplicationStatus, JobSummary } from '../types'
import {
  loadColumnOrder,
  loadColumnSizing,
  saveColumnOrder,
  saveColumnSizing,
  tableColumns,
} from '../lib/columns'
import { useDeleteApplication, useMarkApplication } from '../hooks/useApplications'
import ContextMenu from './ContextMenu'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const PAGE_SIZE = 50

interface Props {
  items: JobSummary[]
  visibleColumns: Set<string>
  onSelect: (hash: string) => void
  applications?: Map<string, Application>
}

interface ContextState {
  x: number
  y: number
  job: JobSummary
}

// ── Badge helpers ───────────────────────────────────────────────────────────

function ScoreBadge({ score }: { score: number | null }) {
  if (score === null) return <span className="text-faint">—</span>
  const variant = score >= 4 ? 'score_high' : score === 3 ? 'score_mid' : 'score_low'
  return <Badge variant={variant} className="font-mono">{score}</Badge>
}

function ClassificationBadge({ value }: { value: string | null }) {
  if (!value) return <span className="text-faint">—</span>
  const label = value.replace(/_/g, ' ')
  const variant =
    value === 'fully_remote'        ? 'remote' :
    value === 'location_restricted' ? 'local'  :
    value.startsWith('remote_with') ? 'travel' :
    'muted'
  return <Badge variant={variant}>{label}</Badge>
}

function ConfidenceBadge({ value }: { value: string | null }) {
  if (!value) return <span className="text-faint">—</span>
  const cls =
    value === 'high'   ? 'text-score-high' :
    value === 'medium' ? 'text-score-mid'  :
    'text-score-low'
  return <span className={cn('text-[11px] uppercase tracking-wider font-medium', cls)}>{value}</span>
}

function renderCell(key: string, job: JobSummary): ReactNode {
  switch (key) {
    case 'fit_score':
      return <ScoreBadge score={job.fit_score} />
    case 'title':
      return (
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="overflow-hidden text-ellipsis whitespace-nowrap flex-1 min-w-0">{job.title ?? '—'}</span>
          {job.source_url && (
            <a
              className="shrink-0 text-[11px] text-muted no-underline opacity-60 leading-none hover:text-primary hover:opacity-100"
              href={job.source_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              title="Open job posting"
              aria-label="Open job posting in a new tab"
            >↗</a>
          )}
        </div>
      )
    case 'remote_classification':
      return <ClassificationBadge value={job.remote_classification} />
    case 'confidence':
      return <ConfidenceBadge value={job.confidence} />
    case 'posted_at':
      return <span className="text-muted font-mono text-[12px]">{job.posted_at ?? '—'}</span>
    case 'score_rationale':
      return (
        <span className="overflow-hidden text-muted text-[12px] leading-[1.45]" style={{ display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
          {job.score_rationale ?? <span className="text-faint">—</span>}
        </span>
      )
    default: {
      const v = (job[key as keyof JobSummary] as string | null) ?? null
      return v ? <span>{v}</span> : <span className="text-faint">—</span>
    }
  }
}

// ── Quick-mark column ───────────────────────────────────────────────────────

const qBtn =
  'text-[11px] font-medium px-2 h-[22px] rounded-md border border-border bg-card text-muted cursor-pointer whitespace-nowrap ' +
  'hover:border-border-strong hover:text-fg disabled:opacity-40 disabled:cursor-default transition-all'
const qBtnActive = 'bg-primary/15 border-primary/40 text-primary-hov shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]'

function QuickMark({ dedupHash, current }: { dedupHash: string; current: string | undefined }) {
  const { mutate, isPending } = useMarkApplication()
  const buttons: { status: ApplicationStatus; label: string }[] = [
    { status: 'saved',    label: 'Save'     },
    { status: 'maybe',    label: 'Maybe'    },
    { status: 'to_apply', label: 'To Apply' },
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

export default function JobTable({ items, visibleColumns, onSelect, applications }: Props) {
  const [sorting, setSorting] = useState<SortingState>([{ id: 'fit_score', desc: true }])
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: PAGE_SIZE })
  const [columnOrder, setColumnOrder] = useState<ColumnOrderState>(loadColumnOrder)
  const [columnSizing, setColumnSizing] = useState<ColumnSizingState>(loadColumnSizing)
  const [ctx, setCtx] = useState<ContextState | null>(null)
  const { mutate: mark } = useMarkApplication()
  const { mutate: del } = useDeleteApplication()

  const columnVisibility = Object.fromEntries(
    tableColumns.map((col) => [col.id!, visibleColumns.has(col.id!)])
  )

  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: items,
    columns: tableColumns,
    state: { sorting, pagination, columnOrder, columnSizing, columnVisibility },
    onSortingChange: setSorting,
    onPaginationChange: setPagination,
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
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    columnResizeMode: 'onChange',
  })

  const dragCol    = useRef<string | null>(null)
  const isResizing = useRef(false)
  const { pageIndex } = table.getState().pagination
  const totalPages = table.getPageCount()

  if (items.length === 0) {
    return (
      <div className="py-20 text-center">
        <div className="text-muted text-sm">No jobs match the current filters.</div>
        <div className="text-faint text-xs mt-1">Adjust your filters in the sidebar to widen the search.</div>
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
                  const isLast     = i === hg.headers.length - 1
                  const startResize = (h: typeof header) => (e: React.MouseEvent) => {
                    isResizing.current = true
                    h.getResizeHandler()(e)
                    const reset = () => { isResizing.current = false; window.removeEventListener('mouseup', reset) }
                    window.addEventListener('mouseup', reset)
                  }
                  return (
                    <th
                      key={header.id}
                      style={{ position: 'relative', width: header.getSize() }}
                      className="cursor-pointer select-none hover:text-fg"
                      draggable
                      onDragStart={(e) => {
                        if (isResizing.current) { e.preventDefault(); return }
                        dragCol.current = header.column.id
                      }}
                      onDragEnd={() => { dragCol.current = null }}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={() => {
                        if (!dragCol.current || dragCol.current === header.column.id) return
                        const order = table.getState().columnOrder
                        const from = order.indexOf(dragCol.current)
                        const to   = order.indexOf(header.column.id)
                        if (from === -1 || to === -1) { dragCol.current = null; return }
                        const next = [...order]
                        next.splice(from, 1)
                        next.splice(to, 0, dragCol.current)
                        table.setColumnOrder(next)
                        dragCol.current = null
                      }}
                      onClick={header.column.getToggleSortingHandler()}
                    >
                      {prevHeader?.column.getCanResize() && (
                        <div
                          className="col-resize-handle col-resize-handle--left"
                          onMouseDown={startResize(prevHeader)}
                          onTouchStart={(e) => prevHeader.getResizeHandler()(e as unknown as React.MouseEvent)}
                          onClick={(e) => e.stopPropagation()}
                        />
                      )}
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {header.column.getIsSorted() === 'desc'
                        ? ' ↓'
                        : header.column.getIsSorted() === 'asc'
                        ? ' ↑'
                        : <span className="text-muted text-[10px]"> ↕</span>}
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
              const rank = pageIndex * PAGE_SIZE + i + 1
              return (
                <tr
                  key={row.id}
                  className={cn('cursor-pointer transition-colors hover:bg-hover', appStatus && 'bg-primary-dim/15')}
                  onClick={() => onSelect(job.dedup_hash)}
                  onContextMenu={(e) => { e.preventDefault(); setCtx({ x: e.clientX, y: e.clientY, job }) }}
                >
                  <td className="w-11 max-w-11 text-right text-muted">{rank}</td>
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} style={{ width: cell.column.getSize(), maxWidth: cell.column.getSize() }}>
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
            { label: 'Save',             active: applications?.get(ctx.job.dedup_hash)?.status === 'saved',     onClick: () => mark({ dedupHash: ctx.job.dedup_hash, status: 'saved'     }) },
            { label: 'Maybe',            active: applications?.get(ctx.job.dedup_hash)?.status === 'maybe',    onClick: () => mark({ dedupHash: ctx.job.dedup_hash, status: 'maybe'    }) },
            { label: 'To Apply',         active: applications?.get(ctx.job.dedup_hash)?.status === 'to_apply', onClick: () => mark({ dedupHash: ctx.job.dedup_hash, status: 'to_apply' }) },
            { label: 'Applied',          active: applications?.get(ctx.job.dedup_hash)?.status === 'applied',  onClick: () => mark({ dedupHash: ctx.job.dedup_hash, status: 'applied'  }) },
            ...(applications?.has(ctx.job.dedup_hash)
              ? [{ label: 'Remove tracking', active: false, onClick: () => { if (window.confirm('Remove tracking for this job?')) del(ctx.job.dedup_hash) } }]
              : []),
          ]}
        />
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-1 p-3 border-t border-border shrink-0 bg-card/40">
          <Button variant="secondary" size="icon-sm" onClick={() => table.setPageIndex(0)}         disabled={!table.getCanPreviousPage()}>«</Button>
          <Button variant="secondary" size="icon-sm" onClick={() => table.previousPage()}           disabled={!table.getCanPreviousPage()}>‹</Button>
          <span className="text-[12px] text-muted px-3 font-mono tabular-nums">
            <span className="text-fg">{pageIndex + 1}</span>
            <span className="text-faint mx-1">/</span>
            {totalPages}
          </span>
          <Button variant="secondary" size="icon-sm" onClick={() => table.nextPage()}               disabled={!table.getCanNextPage()}>›</Button>
          <Button variant="secondary" size="icon-sm" onClick={() => table.setPageIndex(totalPages - 1)} disabled={!table.getCanNextPage()}>»</Button>
        </div>
      )}
    </div>
  )
}
