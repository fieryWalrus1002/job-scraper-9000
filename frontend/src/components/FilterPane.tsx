import { useState } from 'react'
import type { Filters } from '../types'
import { EMPTY_FILTERS, REMOTE_OPTIONS, hasActiveFilters } from '../lib/filters'
import { COLUMNS } from '../lib/columns'

interface Props {
  filters: Filters
  search: string
  onFiltersChange: (f: Filters) => void
  onSearchChange: (s: string) => void
  visibleColumns: Set<string>
  onToggleColumn: (key: string) => void
  total: number | undefined
}

export default function FilterPane({
  filters,
  search,
  onFiltersChange,
  onSearchChange,
  visibleColumns,
  onToggleColumn,
  total,
}: Props) {
  const [colsOpen, setColsOpen] = useState(false)
  const [remoteOpen, setRemoteOpen] = useState(true)

  function set(field: keyof Filters, value: string) {
    onFiltersChange({ ...filters, [field]: value })
  }

  function toggleRemote(value: string) {
    const next = filters.remoteClassification.includes(value)
      ? filters.remoteClassification.filter((v) => v !== value)
      : [...filters.remoteClassification, value]
    onFiltersChange({ ...filters, remoteClassification: next })
  }

  const active = hasActiveFilters(filters) || search.length > 0

  return (
    <aside className="filter-pane">
      <div className="filter-group">
        <label className="filter-label">Search</label>
        <input
          className="filter-input"
          type="text"
          placeholder="title, description…"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
        />
      </div>

      <div className="filter-group">
        <label className="filter-label">Company</label>
        <input
          className="filter-input"
          type="text"
          placeholder="e.g. SEL, Google…"
          value={filters.company}
          onChange={(e) => set('company', e.target.value)}
        />
      </div>

      <div className="filter-group">
        <label className="filter-label">Score</label>
        <div className="filter-range">
          <select
            className="filter-select"
            value={filters.minScore}
            onChange={(e) => set('minScore', e.target.value)}
          >
            <option value="">min</option>
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
          <span className="filter-range-sep">–</span>
          <select
            className="filter-select"
            value={filters.maxScore}
            onChange={(e) => set('maxScore', e.target.value)}
          >
            <option value="">max</option>
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="filter-group">
        <button
          className="filter-label filter-label--toggle"
          onClick={() => setRemoteOpen((v) => !v)}
        >
          Remote <span className="filter-toggle-arrow">{remoteOpen ? '▴' : '▾'}</span>
        </button>
        {remoteOpen && REMOTE_OPTIONS.filter((o) => o.value).map((o) => (
          <label key={o.value} className="col-check-item">
            <input
              type="checkbox"
              checked={filters.remoteClassification.includes(o.value)}
              onChange={() => toggleRemote(o.value)}
            />
            {o.label}
          </label>
        ))}
      </div>

      <div className="filter-group">
        <label className="filter-label">Posted from</label>
        <input
          className="filter-input"
          type="date"
          value={filters.minPostedAt}
          onChange={(e) => set('minPostedAt', e.target.value)}
        />
        <label className="filter-label" style={{ marginTop: 6 }}>to</label>
        <input
          className="filter-input"
          type="date"
          value={filters.maxPostedAt}
          onChange={(e) => set('maxPostedAt', e.target.value)}
        />
      </div>

      <div className="filter-group filter-group--disabled">
        <label className="filter-label">
          Salary <span className="filter-label-note">coming soon</span>
        </label>
        <div className="filter-range">
          <input className="filter-input" type="number" placeholder="min $" disabled />
          <span className="filter-range-sep">–</span>
          <input className="filter-input" type="number" placeholder="max $" disabled />
        </div>
      </div>

      <div className="filter-group">
        <button
          className="filter-label filter-label--toggle"
          onClick={() => setColsOpen((v) => !v)}
        >
          Columns <span className="filter-toggle-arrow">{colsOpen ? '▴' : '▾'}</span>
        </button>
        {colsOpen && COLUMNS.map((col) => (
          <label key={col.key} className="col-check-item">
            <input
              type="checkbox"
              checked={visibleColumns.has(col.key)}
              onChange={() => onToggleColumn(col.key)}
            />
            {col.label}
          </label>
        ))}
      </div>

      <div className="filter-pane-actions">
        {active && (
          <button
            className="btn btn--ghost"
            onClick={() => { onFiltersChange(EMPTY_FILTERS); onSearchChange('') }}
          >
            Clear filters
          </button>
        )}
      </div>

      {total !== undefined && (
        <div className="filter-count">
          {total.toLocaleString()} job{total !== 1 ? 's' : ''}
          {active ? ' matching' : ' total'}
        </div>
      )}
    </aside>
  )
}
