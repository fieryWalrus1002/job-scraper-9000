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

export default function FilterBar({
  filters,
  search,
  onFiltersChange,
  onSearchChange,
  visibleColumns,
  onToggleColumn,
  total,
}: Props) {
  const [colMenuOpen, setColMenuOpen] = useState(false)

  function set(field: keyof Filters, value: string) {
    onFiltersChange({ ...filters, [field]: value })
  }

  const active = hasActiveFilters(filters) || search.length > 0

  return (
    <div className="filter-bar">
      <div className="filter-row">
        <div className="filter-group">
          <label className="filter-label">Search</label>
          <input
            className="filter-input filter-input--wide"
            type="text"
            placeholder="title or description…"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
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
          <label className="filter-label">Remote</label>
          <select
            className="filter-select"
            value={filters.remoteClassification}
            onChange={(e) => set('remoteClassification', e.target.value)}
          >
            {REMOTE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label className="filter-label">Posted from</label>
          <input
            className="filter-input"
            type="date"
            value={filters.minPostedAt}
            onChange={(e) => set('minPostedAt', e.target.value)}
          />
        </div>

        <div className="filter-group">
          <label className="filter-label">to</label>
          <input
            className="filter-input"
            type="date"
            value={filters.maxPostedAt}
            onChange={(e) => set('maxPostedAt', e.target.value)}
          />
        </div>

        <div className="filter-actions">
          {active && (
            <button
              className="btn btn--ghost"
              onClick={() => { onFiltersChange(EMPTY_FILTERS); onSearchChange('') }}
            >
              Clear
            </button>
          )}

          <div className="col-toggle">
            <button
              className="btn btn--ghost"
              onClick={() => setColMenuOpen((v) => !v)}
            >
              Columns ▾
            </button>
            {colMenuOpen && (
              <div className="col-menu">
                {COLUMNS.map((col) => (
                  <label key={col.key} className="col-menu-item">
                    <input
                      type="checkbox"
                      checked={visibleColumns.has(col.key)}
                      onChange={() => onToggleColumn(col.key)}
                    />
                    {col.label}
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {total !== undefined && (
        <div className="filter-count">
          {total.toLocaleString()} job{total !== 1 ? 's' : ''}
          {active ? ' matching filters' : ' total'}
        </div>
      )}
    </div>
  )
}
