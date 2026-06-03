
import { APPLICATION_STATUSES, type ApplicationStatus, STATUS_LABELS} from '../../types'
import { cn } from '@/lib/utils'

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

const filterBtn =
  'h-[28px] px-2.5 bg-transparent border border-transparent rounded-md text-muted text-[12px] font-medium cursor-pointer whitespace-nowrap transition-all ' +
  'hover:bg-hover hover:text-fg disabled:opacity-30 disabled:cursor-default'
const filterBtnActive = 'bg-primary/15 border-primary/40 text-primary-hov shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]'
const countCls = 'ml-1 text-[11px] font-mono text-faint'
const countActive = 'text-primary-hov/80'

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
    <div className="flex items-center gap-1 px-4 py-2.5 border-b border-border shrink-0 bg-card/30">
      {/* 1. All Active View Button */}
      <button
        className={cn(filterBtn, !showOnlyInProgress && !showArchived && filterBtnActive)}
        onClick={() => {
          setShowOnlyInProgress(false)
          setShowArchived(false)
          setFilter('all')
        }}
      >
        Active
        <span className={cn(countCls, !showOnlyInProgress && !showArchived && countActive)}>
          {allCount - archivedCount}
        </span>
      </button>

      {/* 2. In Progress View Button */}
      <button
        className={cn(filterBtn, showOnlyInProgress && filterBtnActive)}
        onClick={() => {
          setShowOnlyInProgress(true)
          setShowArchived(false)
          setFilter('all')
        }}
      >
        In Progress
        <span className={cn(countCls, showOnlyInProgress && countActive)}>
          {inProgressCount}
        </span>
      </button>

      <span className="border-l border-border mx-1.5 h-5" />

      {/* 3. Dynamic Sub-tabs for specific statuses */}
      {APPLICATION_STATUSES.filter((s) => counts[s] > 0).map((s) => (
        <button
          key={s}
          className={cn(filterBtn, filter === s && filterBtnActive)}
          onClick={() => setFilter(s as ApplicationStatus)}
        >
          {STATUS_LABELS[s]}
          <span className={cn(countCls, filter === s && countActive)}>{counts[s]}</span>
        </button>
      ))}

      {/* 4. Archived View Button (Floated Right) */}
      <button
        className={cn(filterBtn, 'ml-auto', showArchived ? filterBtnActive : 'opacity-70')}
        disabled={archivedCount === 0}
        onClick={() => {
          setShowArchived(true)
          setShowOnlyInProgress(false)
          setFilter('all')
        }}
      >
        Archive
        <span className={cn(countCls, showArchived && countActive)}>{archivedCount}</span>
      </button>
    </div>
  )
}
