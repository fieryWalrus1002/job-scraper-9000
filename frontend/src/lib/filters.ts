import type { Filters } from '../types'

export const EMPTY_FILTERS: Filters = {
  minScore: '',
  maxScore: '',
  remoteClassification: '',
  minPostedAt: '',
  maxPostedAt: '',
}

export function filtersFromParams(params: URLSearchParams): Filters {
  return {
    minScore: params.get('minScore') ?? '',
    maxScore: params.get('maxScore') ?? '',
    remoteClassification: params.get('rc') ?? '',
    minPostedAt: params.get('from') ?? '',
    maxPostedAt: params.get('to') ?? '',
  }
}

export function filtersToParams(filters: Filters): URLSearchParams {
  const p = new URLSearchParams()
  if (filters.minScore) p.set('minScore', filters.minScore)
  if (filters.maxScore) p.set('maxScore', filters.maxScore)
  if (filters.remoteClassification) p.set('rc', filters.remoteClassification)
  if (filters.minPostedAt) p.set('from', filters.minPostedAt)
  if (filters.maxPostedAt) p.set('to', filters.maxPostedAt)
  return p
}

export function hasActiveFilters(filters: Filters): boolean {
  return Object.values(filters).some(Boolean)
}

export const REMOTE_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'fully_remote', label: 'Fully Remote' },
  { value: 'remote_with_quarterly_travel', label: 'Remote + quarterly travel' },
  { value: 'remote_with_monthly_travel', label: 'Remote + monthly travel' },
  { value: 'remote_with_frequent_travel', label: 'Remote + frequent travel' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'location_restricted', label: 'Location restricted' },
  { value: 'onsite_disguised', label: 'Onsite (disguised)' },
  { value: 'unclear', label: 'Unclear' },
]
