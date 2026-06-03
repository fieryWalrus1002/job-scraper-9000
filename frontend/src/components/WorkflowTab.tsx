import { useState } from 'react'
import { useApplications, useUpdateApplication } from '../hooks/useApplications'
import { APPLICATION_STATUSES, type ApplicationStatus } from '../types'

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
}

interface Props {
  onSelectJob: (hash: string) => void
}

export default function WorkflowTab({ onSelectJob }: Props) {
  const { data: applications, isLoading } = useApplications()
  const update = useUpdateApplication()
  const [filter, setFilter] = useState<ApplicationStatus | 'all'>('all')

  if (isLoading) return <div className="status-msg">Loading…</div>

  const all = Array.from(applications?.values() ?? [])
  const visible = filter === 'all' ? all : all.filter((a) => a.status === filter)

  const counts = APPLICATION_STATUSES.reduce<Record<string, number>>((acc, s) => {
    acc[s] = all.filter((a) => a.status === s).length
    return acc
  }, {})

  return (
    <div className="workflow-tab">
      <div className="workflow-filters">
        <button
          className={`workflow-filter-btn${filter === 'all' ? ' workflow-filter-btn--active' : ''}`}
          onClick={() => setFilter('all')}
        >
          All ({all.length})
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
      </div>

      {visible.length === 0 ? (
        <div className="empty-state">
          {filter === 'all'
            ? 'No tracked jobs yet. Use the Save / Maybe / To Apply buttons in the Jobs tab.'
            : `No jobs with status "${STATUS_LABELS[filter]}".`}
        </div>
      ) : (
        <table className="job-table">
          <thead>
            <tr>
              <th>Status</th>
              <th>Job</th>
              <th>Updated</th>
              <th>Notes</th>
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
                      update.mutate({ dedupHash: app.dedup_hash, update: { status: e.target.value } })
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
                <td className="text-muted" style={{ fontSize: 11 }}>
                  {new Date(app.updated_at).toLocaleDateString()}
                </td>
                <td className="rationale-preview">{app.notes ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
