import { useState, type ReactNode } from 'react'
import { useApplications } from '../hooks/useApplications'
import { STATUS_LABELS, type Application, type ApplicationStatus } from '../types'
import { Badge } from './ui/badge'

type ApplicationSortCol = 'status' | 'title' | 'score' | 'updated'
type SortDir = 'asc' | 'desc'

interface Props {
  statuses: ApplicationStatus[]
  onSelect: (application: Application) => void
  emptyMessage: string
  /** Optional per-row actions; when set, a trailing actions column is rendered. */
  renderRowActions?: (application: Application) => ReactNode
}

export function TriageApplicationTable({
  statuses,
  onSelect,
  emptyMessage,
  renderRowActions,
}: Props) {
  const { data, isLoading, isError, error } = useApplications(statuses)
  const [sortCol, setSortCol] = useState<ApplicationSortCol>('updated')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const visible = sortApplications(Array.from(data?.values() ?? []), sortCol, sortDir)

  function handleSort(col: ApplicationSortCol) {
    if (sortCol === col) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortCol(col)
      setSortDir(col === 'updated' ? 'desc' : 'asc')
    }
  }

  function sortIndicator(col: ApplicationSortCol) {
    if (sortCol !== col) return <span className="text-muted text-[10px]"> ↕</span>
    return sortDir === 'asc' ? ' ↑' : ' ↓'
  }

  if (isLoading) return <div className="py-12 text-center text-muted text-sm">Loading…</div>
  if (isError) {
    return (
      <div className="py-12 text-center text-score-low text-sm">
        Failed to load applications: {(error as Error).message}
      </div>
    )
  }

  if (visible.length === 0) {
    return (
      <div className="py-20 text-center">
        <div className="text-muted text-sm">{emptyMessage}</div>
        <div className="text-faint text-xs mt-1.5">
          Jobs will appear here when their status matches this tab.
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-auto">
      <table className="job-table [&_td]:max-w-none">
        <colgroup>
          <col style={{ width: '160px' }} />
          <col style={{ width: '40%' }} />
          <col style={{ width: '70px' }} />
          <col style={{ width: '110px' }} />
          <col />
          {renderRowActions && <col style={{ width: '150px' }} />}
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
            {renderRowActions && <th className="text-right pr-3">Actions</th>}
          </tr>
        </thead>
        <tbody>
          {visible.map((app) => (
            <tr
              key={app.dedup_hash}
              className="cursor-pointer transition-colors hover:bg-hover"
              onClick={() => onSelect(app)}
            >
              <td>
                <Badge variant="secondary">{STATUS_LABELS[app.status]}</Badge>
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
              {renderRowActions && (
                <td className="text-right pr-3" onClick={(e) => e.stopPropagation()}>
                  <div className="inline-flex justify-end">{renderRowActions(app)}</div>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function sortApplications(
  rows: Application[],
  col: ApplicationSortCol,
  dir: SortDir,
): Application[] {
  return [...rows].sort((a, b) => {
    let cmp = 0
    switch (col) {
      case 'status':
        cmp = a.status.localeCompare(b.status)
        break
      case 'title':
        cmp = (a.title ?? '').localeCompare(b.title ?? '')
        break
      case 'score':
        cmp = (a.fit_score ?? -1) - (b.fit_score ?? -1)
        break
      case 'updated':
        cmp = a.updated_at.localeCompare(b.updated_at)
        break
    }
    return dir === 'asc' ? cmp : -cmp
  })
}
