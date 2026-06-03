import type { Filters } from '../types'

export const EMPTY_FILTERS: Filters = {
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
  if (filters.minScore) p.set('minScore', filters.minScore)
  if (filters.maxScore) p.set('maxScore', filters.maxScore)
  filters.remoteClassification.forEach((v) => p.append('rc', v))
  if (filters.minPostedAt) p.set('from', filters.minPostedAt)
  if (filters.maxPostedAt) p.set('to', filters.maxPostedAt)
  if (filters.company) p.set('co', filters.company)
  if (filters.minSalaryK) p.set('salMin', filters.minSalaryK)
  return p
}

export function hasActiveFilters(filters: Filters): boolean {
  return (
    Boolean(filters.minScore) ||
    Boolean(filters.maxScore) ||
    filters.remoteClassification.length > 0 ||
    Boolean(filters.minPostedAt) ||
    Boolean(filters.maxPostedAt) ||
    Boolean(filters.company) ||
    Boolean(filters.minSalaryK)
  )
}

export const REMOTE_OPTIONS: { value: string; label: string }[] = [
  { value: 'fully_remote', label: 'Fully remote' },
  { value: 'remote_with_quarterly_travel', label: 'Remote + quarterly travel' },
  { value: 'remote_with_monthly_travel', label: 'Remote + monthly travel' },
  { value: 'remote_with_frequent_travel', label: 'Remote + frequent travel' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'location_restricted', label: 'Location restricted' },
  { value: 'onsite_disguised', label: 'Onsite (disguised)' },
  { value: 'unclear', label: 'Unclear' },
]
