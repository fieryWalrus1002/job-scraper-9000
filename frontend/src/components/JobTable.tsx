import { useState } from 'react'
import type { JobSummary } from '../types'
import { COLUMNS } from '../lib/columns'

const PAGE_SIZE = 50

interface Props {
  items: JobSummary[]
  visibleColumns: Set<string>
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

export default function JobTable({ items, visibleColumns }: Props) {
  const [page, setPage] = useState(0)
  const [expandedHash, setExpandedHash] = useState<string | null>(null)

  const totalPages = Math.ceil(items.length / PAGE_SIZE)
  const pageItems = items.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const globalOffset = page * PAGE_SIZE

  function toggleExpand(hash: string) {
    setExpandedHash((prev) => (prev === hash ? null : hash))
  }

  if (items.length === 0) {
    return <div className="empty-state">No jobs match the current filters.</div>
  }

  const visibleCols = COLUMNS.filter((c) => visibleColumns.has(c.key))

  return (
    <div className="table-outer">
      <div className="table-wrapper">
        <table className="job-table">
          <thead>
            <tr>
              <th className="col-rank">#</th>
              {visibleCols.map((col) => (
                <th key={col.key} style={col.width ? { width: col.width } : undefined}>
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageItems.map((job, i) => {
              const rank = globalOffset + i + 1
              const expanded = expandedHash === job.dedup_hash
              return (
                <>
                  <tr
                    key={job.dedup_hash}
                    className={`job-row${expanded ? ' job-row--expanded' : ''}`}
                    onClick={() => toggleExpand(job.dedup_hash)}
                  >
                    <td className="col-rank text-muted">{rank}</td>
                    {visibleCols.map((col) => (
                      <td key={col.key}>
                        {renderCell(col.key, job)}
                      </td>
                    ))}
                  </tr>
                  {expanded && (
                    <tr key={`${job.dedup_hash}-expanded`} className="rationale-row">
                      <td colSpan={visibleCols.length + 1}>
                        <div className="rationale-content">
                          {job.failure_reason ? (
                            <span className="text-error">Failed: {job.failure_reason}</span>
                          ) : job.score_rationale ? (
                            job.score_rationale
                          ) : (
                            <span className="text-muted">No rationale available.</span>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </>
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

function renderCell(key: string, job: JobSummary): React.ReactNode {
  switch (key) {
    case 'fit_score':
      return <ScoreBadge score={job.fit_score} />
    case 'title':
      return job.source_url ? (
        <a
          className="job-link"
          href={job.source_url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
        >
          {job.title ?? '—'}
        </a>
      ) : (
        <span>{job.title ?? '—'}</span>
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
