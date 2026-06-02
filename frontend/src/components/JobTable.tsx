import { useState, type ReactNode } from 'react'
import type { JobSummary } from '../types'
import { COLUMNS } from '../lib/columns'

const PAGE_SIZE = 50

type SortKey = keyof JobSummary
type SortDir = 'asc' | 'desc'

interface SortState {
  key: SortKey
  dir: SortDir
}

interface Props {
  items: JobSummary[]
  visibleColumns: Set<string>
  onSelect: (hash: string) => void
}

function compareValues(a: unknown, b: unknown, dir: SortDir): number {
  if (a === null && b === null) return 0
  if (a === null) return 1
  if (b === null) return -1
  const mul = dir === 'asc' ? 1 : -1
  if (typeof a === 'number' && typeof b === 'number') return (a - b) * mul
  return String(a).localeCompare(String(b)) * mul
}

function sortItems(items: JobSummary[], sort: SortState): JobSummary[] {
  return [...items].sort((a, b) => compareValues(a[sort.key], b[sort.key], sort.dir))
}

function SortIndicator({ active, dir }: { active: boolean; dir: SortDir }) {
  return (
    <span className={`sort-indicator${active ? ' sort-indicator--active' : ''}`}>
      {active ? (dir === 'desc' ? ' ↓' : ' ↑') : ' ↕'}
    </span>
  )
}

function ScoreBadge({ score }: { score: number | null }) {
  if (score === null) return <span className="badge badge--muted">—</span>
  const cls = score >= 4 ? 'badge--high' : score === 3 ? 'badge--mid' : 'badge--low'
  return <span className={`badge ${cls}`}>{score}</span>
}

function ClassificationBadge({ value }: { value: string | null }) {
  if (!value) return <span className="badge badge--muted">—</span>
  const label = value.replace(/_/g, ' ')
  const cls =
    value === 'fully_remote' ? 'badge--remote' :
    value === 'location_restricted' ? 'badge--local' :
    value.startsWith('remote_with') ? 'badge--travel' :
    'badge--muted'
  return <span className={`badge ${cls}`}>{label}</span>
}

function ConfidenceBadge({ value }: { value: string | null }) {
  if (!value) return <span className="text-muted">—</span>
  const cls = value === 'high' ? 'conf--high' : value === 'medium' ? 'conf--mid' : 'conf--low'
  return <span className={`conf ${cls}`}>{value}</span>
}

export default function JobTable({ items, visibleColumns, onSelect }: Props) {
  const [page, setPage] = useState(0)
  const [sort, setSort] = useState<SortState>({ key: 'fit_score', dir: 'desc' })

  function handleSort(key: SortKey) {
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === 'desc' ? 'asc' : 'desc' }
        : { key, dir: 'desc' }
    )
    setPage(0)
  }

  if (items.length === 0) {
    return <div className="empty-state">No jobs match the current filters.</div>
  }

  const visibleCols = COLUMNS.filter((c) => visibleColumns.has(c.key))
  const sorted = sortItems(items, sort)
  const totalPages = Math.ceil(sorted.length / PAGE_SIZE)
  const pageItems = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const globalOffset = page * PAGE_SIZE

  return (
    <div className="table-outer">
      <div className="table-wrapper">
        <table className="job-table">
          <thead>
            <tr>
              <th className="col-rank">#</th>
              {visibleCols.map((col) => (
                <th
                  key={col.key}
                  className="col-sortable"
                  style={col.width ? { width: col.width } : undefined}
                  onClick={() => handleSort(col.key as SortKey)}
                >
                  {col.label}
                  <SortIndicator active={sort.key === col.key} dir={sort.dir} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageItems.map((job, i) => {
              const rank = globalOffset + i + 1
              return (
                <tr
                  key={job.dedup_hash}
                  className="job-row"
                  onClick={() => onSelect(job.dedup_hash)}
                >
                  <td className="col-rank text-muted">{rank}</td>
                  {visibleCols.map((col) => (
                    <td key={col.key}>
                      {renderCell(col.key, job)}
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="pagination">
          <button className="btn" onClick={() => setPage(0)} disabled={page === 0}>«</button>
          <button className="btn" onClick={() => setPage((p) => p - 1)} disabled={page === 0}>‹</button>
          <span className="pagination-info">
            {page + 1} / {totalPages}
          </span>
          <button className="btn" onClick={() => setPage((p) => p + 1)} disabled={page >= totalPages - 1}>›</button>
          <button className="btn" onClick={() => setPage(totalPages - 1)} disabled={page >= totalPages - 1}>»</button>
        </div>
      )}
    </div>
  )
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
      return (
        <span className="rationale-preview">
          {job.score_rationale ?? '—'}
        </span>
      )
    default:
      return <span>{(job[key as keyof JobSummary] as string | null) ?? '—'}</span>
  }
}
