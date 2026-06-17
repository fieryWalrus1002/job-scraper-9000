import { useEffect, useState } from 'react'
import {
  SearchIcon,
  Building2Icon,
  StarIcon,
  GlobeIcon,
  CalendarIcon,
  DollarSignIcon,
  Columns3Icon,
} from 'lucide-react'
import type { Filters } from '../types'
import { EMPTY_FILTERS, REMOTE_OPTIONS, hasActiveFilters } from '../lib/filters'
import { COLUMNS } from '../lib/columns'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface Props {
  filters: Filters
  onFiltersChange: (f: Filters, opts?: { replace?: boolean }) => void
  visibleColumns: Set<string>
  onToggleColumn: (key: string) => void
  total: number | undefined
  collapsed?: boolean
}

const SEARCH_DEBOUNCE_MS = 280

const getRelativeDateString = (daysOffset: number) => {
  const targetDate = new Date()
  targetDate.setDate(targetDate.getDate() + daysOffset)
  const year = targetDate.getFullYear()
  const month = String(targetDate.getMonth() + 1).padStart(2, '0')
  const day = String(targetDate.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

const labelCls =
  'text-[10.5px] font-semibold text-muted uppercase tracking-[0.08em] flex items-center gap-1.5'
const iconCls = 'size-3 text-faint'
const nativeSelect =
  'h-8 px-2 bg-bg-elevated border border-border rounded-md text-fg text-[13px] outline-none cursor-pointer ' +
  'hover:border-border-strong focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/25 ' +
  'transition-[color,border-color,box-shadow]'

function SectionLabel({
  icon: Icon,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>
  children: React.ReactNode
}) {
  return (
    <span className={labelCls}>
      <Icon className={iconCls} />
      {children}
    </span>
  )
}

function Section({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn('flex flex-col gap-1.5', className)}>{children}</div>
}

function Disclosure({
  label,
  icon: Icon,
  open,
  onToggle,
  children,
}: {
  label: string
  icon: React.ComponentType<{ className?: string }>
  open: boolean
  onToggle: () => void
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <button
        className={cn(
          labelCls,
          'bg-transparent border-none cursor-pointer justify-between p-0 w-full text-left hover:text-fg group transition-colors',
        )}
        onClick={onToggle}
      >
        <span className="flex items-center gap-1.5">
          <Icon className={cn(iconCls, 'group-hover:text-muted transition-colors')} />
          {label}
        </span>
        <svg
          width="10"
          height="10"
          viewBox="0 0 10 10"
          className={cn(
            'transition-transform duration-200 text-faint group-hover:text-muted',
            open && 'rotate-90',
          )}
          aria-hidden="true"
        >
          <path
            d="M3.5 2 L6.5 5 L3.5 8"
            stroke="currentColor"
            strokeWidth="1.5"
            fill="none"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      {open && <div className="flex flex-col gap-0.5 pl-px">{children}</div>}
    </div>
  )
}

export default function FilterPane({
  filters,
  onFiltersChange,
  visibleColumns,
  onToggleColumn,
  total,
  collapsed = false,
}: Props) {
  const [colsOpen, setColsOpen] = useState(false)
  const [remoteOpen, setRemoteOpen] = useState(false)

  // Search is debounced: the input stays instantly responsive via local state,
  // but the URL write (which drives the fetch + history) only fires once typing
  // settles, and uses replace so keystrokes don't stack history entries.
  const [searchInput, setSearchInput] = useState(filters.search)

  // Re-sync when search changes outside the box (Clear filters, back/forward).
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSearchInput(filters.search)
  }, [filters.search])

  useEffect(() => {
    if (searchInput === filters.search) return
    const t = setTimeout(() => {
      onFiltersChange({ ...filters, search: searchInput }, { replace: true })
    }, SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [searchInput, filters, onFiltersChange])

  type StringFilterKey =
    | 'search'
    | 'minScore'
    | 'maxScore'
    | 'minPostedAt'
    | 'maxPostedAt'
    | 'company'
    | 'minSalaryK'

  function set(field: StringFilterKey, value: string) {
    onFiltersChange({ ...filters, [field]: value })
  }

  function toggleRemote(value: string) {
    const next = filters.remoteClassification.includes(value)
      ? filters.remoteClassification.filter((v) => v !== value)
      : [...filters.remoteClassification, value]
    onFiltersChange({ ...filters, remoteClassification: next })
  }

  const active = hasActiveFilters(filters)
  const defaultMinPostedAt = getRelativeDateString(-14)
  const defaultMaxPostedAt = getRelativeDateString(0)

  return (
    <aside
      className={cn(
        'w-[224px] shrink-0 border-r border-border bg-card/40 backdrop-blur-sm px-4 py-4 flex flex-col gap-3.5 overflow-y-auto transition-[opacity,width] duration-150 ease',
        collapsed && 'overflow-hidden opacity-0 pointer-events-none w-0 p-0 border-none',
      )}
    >
      <Section>
        <SectionLabel icon={SearchIcon}>Search</SectionLabel>
        <Input
          type="text"
          placeholder="title, company…"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />
      </Section>

      <Section>
        <SectionLabel icon={Building2Icon}>Company</SectionLabel>
        <Input
          type="text"
          placeholder="e.g. SEL, Google…"
          value={filters.company}
          onChange={(e) => set('company', e.target.value)}
        />
      </Section>

      <Section>
        <SectionLabel icon={StarIcon}>Score</SectionLabel>
        <div className="flex items-center gap-1.5">
          <select
            className={cn(nativeSelect, 'flex-1')}
            value={filters.minScore}
            onChange={(e) => set('minScore', e.target.value)}
          >
            <option value="">min</option>
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
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
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>
      </Section>

      <Disclosure
        label="Remote"
        icon={GlobeIcon}
        open={remoteOpen}
        onToggle={() => setRemoteOpen((v) => !v)}
      >
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
        <SectionLabel icon={CalendarIcon}>Posted</SectionLabel>
        <Input
          type="date"
          value={filters.minPostedAt || defaultMinPostedAt}
          onChange={(e) => set('minPostedAt', e.target.value)}
        />
        <div className="flex items-center gap-2 mt-1">
          <span className="text-[10.5px] font-semibold text-faint uppercase tracking-[0.08em] shrink-0 w-7">
            to
          </span>
          <Input
            type="date"
            value={filters.maxPostedAt || defaultMaxPostedAt}
            onChange={(e) => set('maxPostedAt', e.target.value)}
          />
        </div>
      </Section>

      <Section>
        <SectionLabel icon={DollarSignIcon}>
          Min salary <span className="text-faint normal-case font-normal ml-0.5">($k/yr)</span>
        </SectionLabel>
        <Input
          type="number"
          placeholder="e.g. 120"
          min={0}
          value={filters.minSalaryK}
          onChange={(e) => set('minSalaryK', e.target.value)}
        />
      </Section>

      <div className="border-t border-border/60 -mx-4" />

      <Disclosure
        label="Columns"
        icon={Columns3Icon}
        open={colsOpen}
        onToggle={() => setColsOpen((v) => !v)}
      >
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

      <div className="flex flex-col gap-1.5 mt-auto pt-2 border-t border-border/60 -mx-4 px-4">
        {total !== undefined && (
          <div className="text-[11px] text-muted flex items-baseline gap-1.5 mt-2">
            <span className="font-mono text-fg tabular-nums">{total.toLocaleString()}</span>
            <span>
              job{total !== 1 ? 's' : ''} {active ? 'matching' : 'total'}
            </span>
          </div>
        )}
        {active && (
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start"
            onClick={() => {
              onFiltersChange(EMPTY_FILTERS)
            }}
          >
            Clear filters
          </Button>
        )}
      </div>
    </aside>
  )
}
