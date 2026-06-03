import { useState } from 'react'
import { useApplications, useDeleteApplication, useUpdateApplication } from '../../hooks/useApplications'
import { APPLICATION_STATUSES, type Application, type ApplicationStatus, STATUS_LABELS } from '../../types'
import { FilterBar } from './FilterBar'
import styles from './WorkflowTab.module.css'

const ARCHIVED_STATUSES: ApplicationStatus[] = ['rejected', 'withdrawn', 'hired', 'ghosted']
const IN_PROGRESS_STATUSES: ApplicationStatus[] = ['applied', 'screening', 'interview', 'offer']

type SortCol = 'status' | 'title' | 'score' | 'updated'
type SortDir = 'asc' | 'desc'

interface Props {
  onSelectJob: (hash: string) => void
}

function sortApplications(rows: Application[], col: SortCol, dir: SortDir): Application[] {
  return [...rows].sort((a, b) => {
    let cmp = 0
    switch (col) {
      case 'status':  cmp = (a.status ?? '').localeCompare(b.status ?? ''); break
      case 'title':   cmp = (a.title ?? '').localeCompare(b.title ?? ''); break
      case 'score':   cmp = (a.fit_score ?? -1) - (b.fit_score ?? -1); break
      case 'updated': cmp = (a.updated_at ?? '').localeCompare(b.updated_at ?? ''); break
    }
    return dir === 'asc' ? cmp : -cmp
  })
}

export default function WorkflowTab({ onSelectJob }: Props) {
  const { data: applications, isLoading } = useApplications()
  const update = useUpdateApplication()
  const del = useDeleteApplication()

  const [filter, setFilter] = useState<ApplicationStatus | 'all'>('all')
  const [showArchived, setShowArchived] = useState(false)
  const [showOnlyInProgress, setShowOnlyInProgress] = useState(false)
  const [sortCol, setSortCol] = useState<SortCol>('updated')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  if (isLoading) return <div className="status-msg">Loading…</div>

  // const all = Array.from(applications?.values() ?? [])
  const all = Array.from(applications?.values() ?? []) as Application[]

  // 1. Calculate overall global pool metrics for button counts
  const archivedCount = all.filter((a) => ARCHIVED_STATUSES.includes(a.status as ApplicationStatus)).length
  const inProgressCount = all.filter((a) => IN_PROGRESS_STATUSES.includes(a.status as ApplicationStatus)).length

  // 2. Core Data Pipeline: Determine the base bucket array based on active toggle state
  let bucketFiltered = all
  if (showArchived) {
    // If showing archived view, isolate to archived statuses
    bucketFiltered = all.filter((a) => ARCHIVED_STATUSES.includes(a.status as ApplicationStatus))
  } else if (showOnlyInProgress) {
    // If showing "In Progress" view, isolate strictly to active tracking pipeline
    bucketFiltered = all.filter((a) => IN_PROGRESS_STATUSES.includes(a.status as ApplicationStatus))
  } else {
    // Default base view: Show all active, unarchived listings
    bucketFiltered = all.filter((a) => !ARCHIVED_STATUSES.includes(a.status as ApplicationStatus))
  }

  // 3. Calculate dynamic sub-counts relative ONLY to the currently selected context pool
  const counts = APPLICATION_STATUSES.reduce<Record<string, number>>((acc, s) => {
    acc[s] = bucketFiltered.filter((a) => a.status === s).length
    return acc
  }, {})

  // 4. Final step: Apply specific sub-tab selection matching, then sort the array
  const filtered = filter === 'all' ? bucketFiltered : bucketFiltered.filter((a) => a.status === filter)
  const visible = sortApplications(filtered, sortCol, sortDir)

  function handleSort(col: SortCol) {
    if (sortCol === col) {
      setSortDir((d) => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortCol(col)
      setSortDir(col === 'updated' ? 'desc' : 'asc')
    }
  }

  function sortIndicator(col: SortCol) {
    if (sortCol !== col) return <span className="sort-indicator"> ↕</span>
    return sortDir === 'asc' ? ' ↑' : ' ↓'
  }

  return (
    <div className={styles['workflow-tab']}>

      <FilterBar
        filter={filter}
        setFilter={setFilter}
        showArchived={showArchived}
        setShowArchived={setShowArchived}
        showOnlyInProgress={showOnlyInProgress}
        setShowOnlyInProgress={setShowOnlyInProgress}
        counts={counts}
        allCount={all.length}
        archivedCount={archivedCount}
        inProgressCount={inProgressCount}
      />

      {visible.length === 0 ? (
        <div className="empty-state">
          {filter === 'all'
            ? 'No tracked jobs yet. Use the Save / Maybe / To Apply buttons in the Jobs tab.'
            : `No jobs with status "${STATUS_LABELS[filter]}".`}
        </div>
      ) : (
        <div className="table-wrapper">
        <table className={`job-table ${styles['workflow-table']}`}>
          <colgroup>
            <col style={{ width: '160px' }} />
            <col style={{ width: '40%' }} />
            <col style={{ width: '70px' }} />
            <col style={{ width: '100px' }} />
            <col />
            <col style={{ width: '44px' }} />
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
                    className={styles['workflow-status-select']}
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
                  <span className="text-muted" style={{ fontSize: 12 }}>
                    {app.fit_score ?? '—'}
                  </span>
                </td>
                <td>
                  <span className={styles['workflow-cell-truncate'] + ' ' + styles['text-muted']} style={{ fontSize: 11 }}>
                    {new Date(app.updated_at).toLocaleDateString()}
                  </span>
                </td>
                <td>
                  <span className={styles['workflow-cell-truncate']} style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    {app.notes ?? '—'}
                  </span>
                </td>
                <td onClick={(e) => e.stopPropagation()}>
                  <button
                    type="button"
                    className="btn btn--icon btn--danger"
                    title="Remove tracking"
                    aria-label="Remove tracking"
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
