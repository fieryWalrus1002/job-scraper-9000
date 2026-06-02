import type { JobSummary } from '../types'

export interface ColumnDef {
  key: keyof JobSummary
  label: string
  defaultVisible: boolean
  width?: string
}

export const COLUMNS: ColumnDef[] = [
  { key: 'fit_score', label: 'Score', defaultVisible: true, width: '60px' },
  { key: 'title', label: 'Title', defaultVisible: true },
  { key: 'company', label: 'Company', defaultVisible: true, width: '160px' },
  { key: 'location', label: 'Location', defaultVisible: true, width: '180px' },
  { key: 'remote_classification', label: 'Remote', defaultVisible: true, width: '160px' },
  { key: 'posted_at', label: 'Posted', defaultVisible: true, width: '100px' },
  { key: 'confidence', label: 'Confidence', defaultVisible: true, width: '100px' },
]

const STORAGE_KEY = 'job9000-columns'

export function loadColumnVisibility(): Set<string> {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) return new Set(JSON.parse(saved) as string[])
  } catch {}
  return new Set(COLUMNS.filter((c) => c.defaultVisible).map((c) => c.key))
}

export function saveColumnVisibility(visible: Set<string>): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...visible]))
}
