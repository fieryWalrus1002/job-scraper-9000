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

// ── Cell renderers ──────────────────────────────────────────────────────────

function ScoreBadge({ score }: { score: number | null }) {
  if (score === null) return <span className="badge badge--muted">—</span>
  const cls = score >= 4 ? 'badge--high' : score === 3 ? 'badge--mid' : 'badge--low'
  return <span className={`badge ${cls}`}>{score}</span>
}

function ClassificationBadge({ value }: { value: string | null }) {
  if (!value) return <span className="badge badge--muted">—</span>
  const label = value.replace(/_/g, ' ')
  const cls =
    value === 'fully_remote'       ? 'badge--remote' :
    value === 'location_restricted' ? 'badge--local'  :
    value.startsWith('remote_with') ? 'badge--travel' :
    'badge--muted'
  return <span className={`badge ${cls}`}>{label}</span>
}

function ConfidenceBadge({ value }: { value: string | null }) {
  if (!value) return <span className="text-muted">—</span>
  const cls = value === 'high' ? 'conf--high' : value === 'medium' ? 'conf--mid' : 'conf--low'
  return <span className={`conf ${cls}`}>{value}</span>
}

function renderCell(key: string, job: JobSummary): ReactNode {
  switch (key) {
    case 'fit_score':
      return <ScoreBadge score={job.fit_score} />
    case 'title':
      return (
        <div className="title-cell">
          <span className="title-text">{job.title ?? '—'}</span>
          {job.source_url && (
            <a
              className="title-ext-link"
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
      return <span className="text-muted">{job.posted_at ?? '—'}</span>
    case 'score_rationale':
      return <span className="rationale-preview">{job.score_rationale ?? '—'}</span>
    default:
      return <span>{(job[key as keyof JobSummary] as string | null) ?? '—'}</span>
  }
}

// ── Quick-mark column ───────────────────────────────────────────────────────

function QuickMark({ dedupHash, current }: { dedupHash: string; current: string | undefined }) {
  const { mutate, isPending } = useMarkApplication()
  const buttons: { status: ApplicationStatus; label: string }[] = [
    { status: 'saved',    label: 'Save'     },
    { status: 'maybe',    label: 'Maybe'    },
    { status: 'to_apply', label: 'To Apply' },
  ]
  return (
    <div className="quick-mark" onClick={(e) => e.stopPropagation()}>
      {buttons.map(({ status, label }) => (
        <button
          key={status}
          className={`quick-mark-btn${current === status ? ' quick-mark-btn--active' : ''}`}
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
    onColumnOrderChange: (updater) => {
      const next = typeof updater === 'function' ? updater(columnOrder) : updater
      setColumnOrder(next)
      saveColumnOrder(next)
    },
    onColumnSizingChange: (updater) => {
      const next = typeof updater === 'function' ? updater(columnSizing) : updater
      setColumnSizing(next)
      saveColumnSizing(next)
    },
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    columnResizeMode: 'onChange',
  })

  const dragCol = useRef<string | null>(null)
  const { pageIndex } = table.getState().pagination
  const totalPages = table.getPageCount()

  if (items.length === 0) {
    return <div className="empty-state">No jobs match the current filters.</div>
  }

  return (
    <div className="table-outer">
      <div className="table-wrapper">
        <table
          className="job-table"
          style={{ width: '100%' }}
        >
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                <th className="col-rank">#</th>
                {hg.headers.map((header) => (
                  <th
                    key={header.id}
                    style={header.column.id === 'title'
                      ? { position: 'relative', minWidth: header.getSize() }
                      : { position: 'relative', width: header.getSize(), maxWidth: header.getSize() }}
                    className="col-sortable"
                    draggable
                    onDragStart={() => { dragCol.current = header.column.id }}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={() => {
                      if (!dragCol.current || dragCol.current === header.column.id) return
                      const order = table.getState().columnOrder
                      const from = order.indexOf(dragCol.current)
                      const to   = order.indexOf(header.column.id)
                      const next = [...order]
                      next.splice(from, 1)
                      next.splice(to, 0, dragCol.current)
                      table.setColumnOrder(next)
                      saveColumnOrder(next)
                      dragCol.current = null
                    }}
                    onClick={header.column.getToggleSortingHandler()}
                  >
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    {header.column.getIsSorted() === 'desc' ? ' ↓' : header.column.getIsSorted() === 'asc' ? ' ↑' : <span className="sort-indicator"> ↕</span>}
                    {header.column.getCanResize() && (
                      <div
                        className="col-resize-handle"
                        onMouseDown={header.getResizeHandler()}
                        onTouchStart={header.getResizeHandler()}
                        onClick={(e) => e.stopPropagation()}
                      />
                    )}
                  </th>
                ))}
                <th className="col-track">Track</th>
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
                  className={`job-row${appStatus ? ' job-row--tracked' : ''}`}
                  onClick={() => onSelect(job.dedup_hash)}
                  onContextMenu={(e) => { e.preventDefault(); setCtx({ x: e.clientX, y: e.clientY, job }) }}
                >
                  <td className="col-rank text-muted">{rank}</td>
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} style={cell.column.id === 'title'
                      ? { minWidth: cell.column.getSize() }
                      : { width: cell.column.getSize(), maxWidth: cell.column.getSize() }}>
                      {renderCell(cell.column.id, job)}
                    </td>
                  ))}
                  <td className="col-track">
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
        <div className="pagination">
          <button className="btn" onClick={() => table.setPageIndex(0)} disabled={!table.getCanPreviousPage()}>«</button>
          <button className="btn" onClick={() => table.previousPage()}  disabled={!table.getCanPreviousPage()}>‹</button>
          <span className="pagination-info">{pageIndex + 1} / {totalPages}</span>
          <button className="btn" onClick={() => table.nextPage()}      disabled={!table.getCanNextPage()}>›</button>
          <button className="btn" onClick={() => table.setPageIndex(totalPages - 1)} disabled={!table.getCanNextPage()}>»</button>
        </div>
      )}
    </div>
  )
}
