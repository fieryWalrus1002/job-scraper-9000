import type { Filters } from '../types'
import { applySortParams, type SortState } from './sort'

export const EMPTY_FILTERS: Filters = {
  search: '',
  minScore: '',
  maxScore: '',
  remoteClassification: [],
  minPostedAt: '',
  maxPostedAt: '',
  company: '',
  minSalaryK: '',
}

export function filtersFromParams(params: URLSearchParams): Filters {
  return {
    search: params.get('q') ?? '',
    minScore: params.get('minScore') ?? '',
    maxScore: params.get('maxScore') ?? '',
    remoteClassification: params.getAll('rc'),
    minPostedAt: params.get('from') ?? '',
    maxPostedAt: params.get('to') ?? '',
    company: params.get('co') ?? '',
    minSalaryK: params.get('salMin') ?? '',
  }
}

export function filtersToParams(filters: Filters): URLSearchParams {
  const p = new URLSearchParams()
  if (filters.search) p.set('q', filters.search)
  if (filters.minScore) p.set('minScore', filters.minScore)
  if (filters.maxScore) p.set('maxScore', filters.maxScore)
  filters.remoteClassification.forEach((v) => p.append('rc', v))
  if (filters.minPostedAt) p.set('from', filters.minPostedAt)
  if (filters.maxPostedAt) p.set('to', filters.maxPostedAt)
  if (filters.company) p.set('co', filters.company)
  if (filters.minSalaryK) p.set('salMin', filters.minSalaryK)
  return p
}

/**
 * Single source of truth for the Jobs feed's URL query string: filters + sort.
 * Both URL writers (filter changes and sort changes) go through this, so adding
 * a new param means touching one place.
 */
export function buildJobsParams(filters: Filters, sort: SortState): URLSearchParams {
  return applySortParams(filtersToParams(filters), sort)
}

export function hasActiveFilters(filters: Filters): boolean {
  return (
    Boolean(filters.search) ||
    Boolean(filters.minScore) ||
    Boolean(filters.maxScore) ||
    filters.remoteClassification.length > 0 ||
    Boolean(filters.minPostedAt) ||
    Boolean(filters.maxPostedAt) ||
    Boolean(filters.company) ||
    Boolean(filters.minSalaryK)
  )
}

// Remote-classification filter options offered in the UI. The legacy
// remote_with_*_travel buckets are intentionally omitted as of remote_filter
// SCHEMA_VERSION 3.0.0 — the pipeline no longer produces them (travel is now
// numeric). Historical rows that still carry those values continue to render:
// ClassificationBadge / classificationVariant handle any `remote_with_*` string
// generically (the 'travel' badge variant). The API filter still accepts the
// values, so historical rows remain filterable by URL param if needed.
// See specs/remote_filter_simplification.md §5.
export const REMOTE_OPTIONS: { value: string; label: string }[] = [
  { value: 'fully_remote', label: 'Fully remote' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'location_restricted', label: 'Location restricted' },
  { value: 'onsite_disguised', label: 'Onsite (disguised)' },
  { value: 'unclear', label: 'Unclear' },
]
