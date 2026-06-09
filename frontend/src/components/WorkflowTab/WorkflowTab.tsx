import { useState } from 'react'
import {
  useApplications,
  useDeleteApplication,
  useUpdateApplication,
} from '../../hooks/useApplications'
import {
  APPLICATION_STATUSES,
  type Application,
  type ApplicationStatus,
  STATUS_LABELS,
} from '../../types'
import { Badge } from '@/components/ui/badge'
import { FilterBar } from './FilterBar'

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
      case 'status':
        cmp = (a.status ?? '').localeCompare(b.status ?? '')
        break
      case 'title':
        cmp = (a.title ?? '').localeCompare(b.title ?? '')
        break
      case 'score':
        cmp = (a.fit_score ?? -1) - (b.fit_score ?? -1)
        break
      case 'updated':
        cmp = (a.updated_at ?? '').localeCompare(b.updated_at ?? '')
        break
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

  if (isLoading) return <div className="py-12 text-center text-muted text-sm">Loading…</div>

  const all = Array.from(applications?.values() ?? []) as Application[]

  const archivedCount = all.filter((a) =>
    ARCHIVED_STATUSES.includes(a.status as ApplicationStatus),
  ).length
  const inProgressCount = all.filter((a) =>
    IN_PROGRESS_STATUSES.includes(a.status as ApplicationStatus),
  ).length

  let bucketFiltered = all
  if (showArchived) {
    bucketFiltered = all.filter((a) => ARCHIVED_STATUSES.includes(a.status as ApplicationStatus))
  } else if (showOnlyInProgress) {
    bucketFiltered = all.filter((a) => IN_PROGRESS_STATUSES.includes(a.status as ApplicationStatus))
  } else {
    bucketFiltered = all.filter((a) => !ARCHIVED_STATUSES.includes(a.status as ApplicationStatus))
  }

  const counts = APPLICATION_STATUSES.reduce<Record<string, number>>((acc, s) => {
    acc[s] = bucketFiltered.filter((a) => a.status === s).length
    return acc
  }, {})

  const filtered =
    filter === 'all' ? bucketFiltered : bucketFiltered.filter((a) => a.status === filter)
  const visible = sortApplications(filtered, sortCol, sortDir)

  function handleSort(col: SortCol) {
    if (sortCol === col) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortCol(col)
      setSortDir(col === 'updated' ? 'desc' : 'asc')
    }
  }

  function sortIndicator(col: SortCol) {
    if (sortCol !== col) return <span className="text-muted text-[10px]"> ↕</span>
    return sortDir === 'asc' ? ' ↑' : ' ↓'
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
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
        <div className="py-20 text-center">
          <div className="text-muted text-sm">
            {filter === 'all'
              ? 'No tracked jobs yet.'
              : `No jobs with status "${STATUS_LABELS[filter]}".`}
          </div>
          {filter === 'all' && (
            <div className="text-faint text-xs mt-1.5">
              Use the <span className="text-muted">Save / Maybe / To Apply</span> buttons in the
              Jobs tab.
            </div>
          )}
        </div>
      ) : (
        <div className="flex-1 overflow-auto">
          <table className="job-table [&_td]:max-w-none">
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
                  className="cursor-pointer transition-colors hover:bg-hover"
                  onClick={() => onSelectJob(app.dedup_hash)}
                >
                  <td>
                    <select
                      className="h-7 bg-bg-elevated border border-border rounded-md text-fg text-[12px] px-2 cursor-pointer hover:border-border-strong focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/25 outline-none transition-[color,border-color,box-shadow]"
                      value={app.status}
                      onClick={(e) => e.stopPropagation()}
                      onChange={(e) => {
                        e.stopPropagation()
                        update.mutate({
                          dedupHash: app.dedup_hash,
                          update: { status: e.target.value as ApplicationStatus },
                        })
                      }}
                    >
                      {APPLICATION_STATUSES.map((s) => (
                        <option key={s} value={s}>
                          {STATUS_LABELS[s]}
                        </option>
                      ))}
                    </select>
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
                          app.fit_score >= 4
                            ? 'score_high'
                            : app.fit_score === 3
                              ? 'score_mid'
                              : 'score_low'
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
                    <span className="truncate block text-muted text-[12px]">
                      {app.notes ?? <span className="text-faint">—</span>}
                    </span>
                  </td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <button
                      type="button"
                      className="size-6 rounded-md bg-transparent border-none text-faint cursor-pointer hover:bg-score-low/15 hover:text-score-low disabled:opacity-40 disabled:cursor-default transition-colors flex items-center justify-center"
                      title="Remove tracking"
                      aria-label="Remove tracking"
                      disabled={del.isPending}
                      onClick={() => {
                        if (window.confirm('Remove tracking for this job?'))
                          del.mutate(app.dedup_hash)
                      }}
                    >
                      ×
                    </button>
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
