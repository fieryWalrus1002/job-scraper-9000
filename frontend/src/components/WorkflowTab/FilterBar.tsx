import { APPLICATION_STATUSES, type ApplicationStatus, STATUS_LABELS} from '../../types'



interface FilterBarProps {
  filter: ApplicationStatus | 'all'
  setFilter: (f: ApplicationStatus | 'all') => void
  showArchived: boolean
  setShowArchived: (v: boolean) => void
  showOnlyInProgress: boolean
  setShowOnlyInProgress: (v: boolean) => void
  counts: Record<string, number>
  allCount: number
  archivedCount: number
  inProgressCount: number
}

export function FilterBar({
  filter,
  setFilter,
  showArchived,
  setShowArchived,
  showOnlyInProgress,
  setShowOnlyInProgress,
  counts,
  allCount,
  archivedCount,
  inProgressCount,
}: FilterBarProps) {
  return (
    <div className="workflow-filters">
      {/* 1. All Active View Button */}
      <button
        className={`workflow-filter-btn${(!showOnlyInProgress && !showArchived) ? ' workflow-filter-btn--active' : ''}`}
        onClick={() => {
          setShowOnlyInProgress(false)
          setShowArchived(false)
          setFilter('all')
        }}
      >
        Active ({allCount - archivedCount})
      </button>

      {/* 2. In Progress View Button */}
      <button
        className={`workflow-filter-btn${showOnlyInProgress ? ' workflow-filter-btn--active' : ''}`}
        onClick={() => {
          setShowOnlyInProgress(true)
          setShowArchived(false)
          setFilter('all')
        }}
      >
        In Progress ({inProgressCount})
      </button>

      {/* Visual Divider Segment */}
      <span style={{ borderLeft: '1px solid var(--border)', margin: '0 4px', height: '24px' }} />

      {/* 3. Dynamic Sub-tabs for specific statuses */}
      {APPLICATION_STATUSES.filter((s) => counts[s] > 0).map((s) => (
        <button
          key={s}
          className={`workflow-filter-btn${filter === s ? ' workflow-filter-btn--active' : ''}`}
          onClick={() => setFilter(s as ApplicationStatus)}
        >
          {STATUS_LABELS[s]} ({counts[s]})
        </button>
      ))}

      {/* 4. Archived View Button (Floated Right) */}
      <button
        className={`workflow-filter-btn workflow-filter-btn--archive${showArchived ? ' workflow-filter-btn--active' : ''}`}
        style={{ marginLeft: 'auto' }}
        disabled={archivedCount === 0}
        onClick={() => {
          setShowArchived(true)
          setShowOnlyInProgress(false)
          setFilter('all')
        }}
      >
        Archive ({archivedCount})
      </button>
    </div>
  )
}
