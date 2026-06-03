import { useState } from 'react'
import type { Filters } from '../types'
import { EMPTY_FILTERS, REMOTE_OPTIONS, hasActiveFilters } from '../lib/filters'
import { COLUMNS } from '../lib/columns'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface Props {
  filters: Filters
  search: string
  onFiltersChange: (f: Filters) => void
  onSearchChange: (s: string) => void
  visibleColumns: Set<string>
  onToggleColumn: (key: string) => void
  total: number | undefined
  collapsed?: boolean
}

const getRelativeDateString = (daysOffset: number) => {
  const targetDate = new Date()
  targetDate.setDate(targetDate.getDate() + daysOffset)
  const year = targetDate.getFullYear()
  const month = String(targetDate.getMonth() + 1).padStart(2, '0')
  const day = String(targetDate.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

const labelCls = 'text-[10px] font-semibold text-muted uppercase tracking-[0.08em]'
const nativeSelect =
  'h-8 px-2 bg-bg-elevated border border-border rounded-md text-fg text-[13px] outline-none cursor-pointer ' +
  'hover:border-border-strong focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/25 ' +
  'transition-[color,border-color,box-shadow]'

function Section({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn('flex flex-col gap-1.5', className)}>{children}</div>
}

function Disclosure({
  label,
  open,
  onToggle,
  children,
}: {
  label: string
  open: boolean
  onToggle: () => void
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <button
        className={cn(
          labelCls,
          'bg-transparent border-none cursor-pointer flex items-center justify-between gap-1 p-0 w-full text-left hover:text-fg transition-colors',
        )}
        onClick={onToggle}
      >
        <span>{label}</span>
        <svg
          width="10"
          height="10"
          viewBox="0 0 10 10"
          className={cn('transition-transform duration-200', open && 'rotate-90')}
          aria-hidden="true"
        >
          <path d="M3.5 2 L6.5 5 L3.5 8" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && <div className="flex flex-col gap-0.5 pl-px">{children}</div>}
    </div>
  )
}

export default function FilterPane({
  filters,
  search,
  onFiltersChange,
  onSearchChange,
  visibleColumns,
  onToggleColumn,
  total,
  collapsed = false,
}: Props) {
  const [colsOpen, setColsOpen] = useState(false)
  const [remoteOpen, setRemoteOpen] = useState(false)

  type StringFilterKey = 'minScore' | 'maxScore' | 'minPostedAt' | 'maxPostedAt' | 'company' | 'minSalaryK'

  function set(field: StringFilterKey, value: string) {
    onFiltersChange({ ...filters, [field]: value })
  }

  function toggleRemote(value: string) {
    const next = filters.remoteClassification.includes(value)
      ? filters.remoteClassification.filter((v) => v !== value)
      : [...filters.remoteClassification, value]
    onFiltersChange({ ...filters, remoteClassification: next })
  }

  const active = hasActiveFilters(filters) || search.length > 0
  const defaultMinPostedAt = getRelativeDateString(-14)
  const defaultMaxPostedAt = getRelativeDateString(0)

  return (
    <aside
      className={cn(
        'w-[212px] shrink-0 border-r border-border bg-card/40 backdrop-blur-sm px-3 py-3 flex flex-col gap-3 overflow-y-auto transition-[opacity,width] duration-150 ease',
        collapsed && 'overflow-hidden opacity-0 pointer-events-none w-0 p-0 border-none',
      )}
    >
      <Section>
        <label className={labelCls}>Search</label>
        <Input
          type="text"
          placeholder="title, company…"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
        />
      </Section>

      <Section>
        <label className={labelCls}>Company</label>
        <Input
          type="text"
          placeholder="e.g. SEL, Google…"
          value={filters.company}
          onChange={(e) => set('company', e.target.value)}
        />
      </Section>

      <Section>
        <label className={labelCls}>Score</label>
        <div className="flex items-center gap-1.5">
          <select
            className={cn(nativeSelect, 'flex-1')}
            value={filters.minScore}
            onChange={(e) => set('minScore', e.target.value)}
          >
            <option value="">min</option>
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
          <span className="text-faint text-xs">–</span>
          <select
            className={cn(nativeSelect, 'flex-1')}
            value={filters.maxScore}
            onChange={(e) => set('maxScore', e.target.value)}
          >
            <option value="">max</option>
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </div>
      </Section>

      <Disclosure label="Remote" open={remoteOpen} onToggle={() => setRemoteOpen((v) => !v)}>
        {REMOTE_OPTIONS.filter((o) => o.value).map((o) => (
          <label
            key={o.value}
            className="flex items-center gap-2 text-[13px] text-fg py-1 cursor-pointer select-none rounded hover:text-fg group"
          >
            <input
              type="checkbox"
              className="accent-primary size-3.5"
              checked={filters.remoteClassification.includes(o.value)}
              onChange={() => toggleRemote(o.value)}
            />
            <span className="text-muted group-hover:text-fg transition-colors">{o.label}</span>
          </label>
        ))}
      </Disclosure>

      <Section>
        <label className={labelCls}>Posted</label>
        <Input
          type="date"
          value={filters.minPostedAt || defaultMinPostedAt}
          onChange={(e) => set('minPostedAt', e.target.value)}
        />
        <div className="flex items-center gap-2 mt-1">
          <span className={cn(labelCls, 'shrink-0')}>to</span>
          <Input
            type="date"
            value={filters.maxPostedAt || defaultMaxPostedAt}
            onChange={(e) => set('maxPostedAt', e.target.value)}
          />
        </div>
      </Section>

      <Section>
        <label className={labelCls}>Min salary <span className="text-faint normal-case font-normal">($k/yr)</span></label>
        <Input
          type="number"
          placeholder="e.g. 120"
          min={0}
          value={filters.minSalaryK}
          onChange={(e) => set('minSalaryK', e.target.value)}
        />
      </Section>

      <div className="border-t border-border/60 -mx-3" />

      <Disclosure label="Columns" open={colsOpen} onToggle={() => setColsOpen((v) => !v)}>
        {COLUMNS.map((col) => (
          <label
            key={col.key}
            className="flex items-center gap-2 text-[13px] py-1 cursor-pointer select-none group"
          >
            <input
              type="checkbox"
              className="accent-primary size-3.5"
              checked={visibleColumns.has(col.key)}
              onChange={() => onToggleColumn(col.key)}
            />
            <span className="text-muted group-hover:text-fg transition-colors">{col.label}</span>
          </label>
        ))}
      </Disclosure>

      <div className="flex flex-col gap-1.5 mt-auto pt-2 border-t border-border/60 -mx-3 px-3">
        {total !== undefined && (
          <div className="text-[11px] text-muted flex items-baseline gap-1.5 mt-2">
            <span className="font-mono text-fg tabular-nums">{total.toLocaleString()}</span>
            <span>job{total !== 1 ? 's' : ''} {active ? 'matching' : 'total'}</span>
          </div>
        )}
        {active && (
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start"
            onClick={() => { onFiltersChange(EMPTY_FILTERS); onSearchChange('') }}
          >
            Clear filters
          </Button>
        )}
      </div>
    </aside>
  )
}
