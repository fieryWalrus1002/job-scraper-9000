import { useState } from 'react'
import { useApplications, useDeleteApplication, useUpdateApplication } from '../hooks/useApplications'
import { APPLICATION_STATUSES, type ApplicationStatus } from '../types'

const ARCHIVED_STATUSES: ApplicationStatus[] = ['rejected', 'withdrawn', 'hired', 'ghosted']

const STATUS_LABELS: Record<string, string> = {
  saved: 'Saved',
  maybe: 'Maybe',
  to_apply: 'To Apply',
  applied: 'Applied',
  screening: 'Screening',
  interview: 'Interview',
  offer: 'Offer',
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
  hired: 'Hired!',
  ghosted: 'Ghosted',
}

interface Props {
  onSelectJob: (hash: string) => void
}

export default function WorkflowTab({ onSelectJob }: Props) {
  const { data: applications, isLoading } = useApplications()
  const update = useUpdateApplication()
  const del = useDeleteApplication()
  const [filter, setFilter] = useState<ApplicationStatus | 'all'>('all')
  const [showArchived, setShowArchived] = useState(false)

  if (isLoading) return <div className="status-msg">Loading…</div>

  const all = Array.from(applications?.values() ?? [])
  const active = showArchived ? all : all.filter((a) => !ARCHIVED_STATUSES.includes(a.status as ApplicationStatus))
  const visible = filter === 'all' ? active : active.filter((a) => a.status === filter)

  const counts = APPLICATION_STATUSES.reduce<Record<string, number>>((acc, s) => {
    acc[s] = active.filter((a) => a.status === s).length
    return acc
  }, {})
  const archivedCount = all.filter((a) => ARCHIVED_STATUSES.includes(a.status as ApplicationStatus)).length

  return (
    <div className="workflow-tab">
      <div className="workflow-filters">
        <button
          className={`workflow-filter-btn${filter === 'all' ? ' workflow-filter-btn--active' : ''}`}
          onClick={() => setFilter('all')}
        >
          All ({active.length})
        </button>
        {APPLICATION_STATUSES.filter((s) => counts[s] > 0).map((s) => (
          <button
            key={s}
            className={`workflow-filter-btn${filter === s ? ' workflow-filter-btn--active' : ''}`}
            onClick={() => setFilter(s as ApplicationStatus)}
          >
            {STATUS_LABELS[s]} ({counts[s]})
          </button>
        ))}
        <button
          className={`workflow-filter-btn workflow-filter-btn--archive${showArchived ? ' workflow-filter-btn--active' : ''}`}
          disabled={archivedCount === 0}
          onClick={() => { setShowArchived((v) => !v); setFilter('all') }}
        >
          {showArchived ? 'Hide archived' : `Show archived (${archivedCount})`}
        </button>
      </div>

      {visible.length === 0 ? (
        <div className="empty-state">
          {filter === 'all'
            ? 'No tracked jobs yet. Use the Save / Maybe / To Apply buttons in the Jobs tab.'
            : `No jobs with status "${STATUS_LABELS[filter]}".`}
        </div>
      ) : (
        <div className="table-wrapper">
        <table className="job-table workflow-table">
          <colgroup>
            <col style={{ width: '160px' }} />
            <col style={{ width: '40%' }} />
            <col style={{ width: '100px' }} />
            <col />
            <col style={{ width: '44px' }} />
          </colgroup>
          <thead>
            <tr>
              <th>Status</th>
              <th>Job</th>
              <th>Updated</th>
              <th>Notes</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {visible.map((app) => (
              <tr
                key={app.dedup_hash}
                className="job-row"
                onClick={() => onSelectJob(app.dedup_hash)}
              >
                <td>
                  <select
                    className="workflow-status-select"
                    value={app.status}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => {
                      e.stopPropagation()
                      update.mutate({ dedupHash: app.dedup_hash, update: { status: e.target.value as ApplicationStatus } })
                    }}
                  >
                    {APPLICATION_STATUSES.map((s) => (
                      <option key={s} value={s}>{STATUS_LABELS[s]}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <div className="title-cell">
                    <span className="title-text">{app.title ?? '—'}</span>
                    {app.source_url && (
                      <a
                        className="title-ext-link"
                        href={app.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        title="Open job posting"
                      >↗</a>
                    )}
                  </div>
                  <span className="text-muted" style={{ fontSize: 11 }}>{app.company ?? '—'}</span>
                </td>
                <td>
                  <span className="workflow-cell-truncate text-muted" style={{ fontSize: 11 }}>
                    {new Date(app.updated_at).toLocaleDateString()}
                  </span>
                </td>
                <td>
                  <span className="workflow-cell-truncate" style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    {app.notes ?? '—'}
                  </span>
                </td>
                <td onClick={(e) => e.stopPropagation()}>
                  <button
                    className="btn btn--icon btn--danger"
                    title="Remove tracking"
                    disabled={del.isPending}
                    onClick={() => { if (window.confirm('Remove tracking for this job?')) del.mutate(app.dedup_hash) }}
                  >×</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
    </div>
  )
}
