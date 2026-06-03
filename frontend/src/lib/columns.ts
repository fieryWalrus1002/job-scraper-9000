import { createColumnHelper } from '@tanstack/react-table'
import type { JobSummary } from '../types'

export interface ColumnMeta {
  key: keyof JobSummary
  label: string
  defaultVisible: boolean
  defaultWidth: number
}

export const COLUMNS: ColumnMeta[] = [
  { key: 'fit_score',             label: 'Score',      defaultVisible: true,  defaultWidth: 70  },
  { key: 'title',                 label: 'Title',      defaultVisible: true,  defaultWidth: 280 },
  { key: 'company',               label: 'Company',    defaultVisible: true,  defaultWidth: 160 },
  { key: 'location',              label: 'Location',   defaultVisible: true,  defaultWidth: 180 },
  { key: 'remote_classification', label: 'Remote',     defaultVisible: false, defaultWidth: 160 },
  { key: 'posted_at',             label: 'Posted',     defaultVisible: true,  defaultWidth: 100 },
  { key: 'confidence',            label: 'Confidence', defaultVisible: false, defaultWidth: 100 },
  { key: 'source',                label: 'Source',     defaultVisible: false, defaultWidth: 100 },
]

const helper = createColumnHelper<JobSummary>()

export const tableColumns = COLUMNS.map((col) =>
  helper.accessor(col.key, {
    id: col.key,
    header: col.label,
    size: col.defaultWidth,
    minSize: 50,
    enableSorting: true,
    enableResizing: true,
  })
)

// ── Persistence ────────────────────────────────────────────────────────────

const STORAGE_KEY = 'job9000-columns'
const ORDER_KEY   = 'job9000-column-order'
const SIZING_KEY  = 'job9000-column-sizing'

function tryParse<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    if (raw) return JSON.parse(raw) as T
  } catch { /* ignore */ }
  return fallback
}

export function loadColumnVisibility(): Set<string> {
  const saved = tryParse<string[]>(STORAGE_KEY, [])
  return saved.length
    ? new Set(saved)
    : new Set(COLUMNS.filter((c) => c.defaultVisible).map((c) => c.key))
}

export function saveColumnVisibility(visible: Set<string>): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...visible]))
}

export function loadColumnOrder(): string[] {
  return tryParse<string[]>(ORDER_KEY, COLUMNS.map((c) => c.key))
}

export function saveColumnOrder(order: string[]): void {
  localStorage.setItem(ORDER_KEY, JSON.stringify(order))
}

export function loadColumnSizing(): Record<string, number> {
  return tryParse<Record<string, number>>(SIZING_KEY, {})
}

export function saveColumnSizing(sizing: Record<string, number>): void {
  localStorage.setItem(SIZING_KEY, JSON.stringify(sizing))
}
