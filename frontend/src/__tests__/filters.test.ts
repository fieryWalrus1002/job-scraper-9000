import { describe, it, expect } from 'vitest'
import {
  EMPTY_FILTERS,
  REMOTE_OPTIONS,
  buildJobsParams,
  filtersFromParams,
  filtersToParams,
  hasActiveFilters,
} from '../lib/filters'
import { DEFAULT_SORT } from '../lib/sort'
import type { Filters } from '../types'

describe('REMOTE_OPTIONS', () => {
  it('offers only the canonical 4-way remote axis in the UI', () => {
    expect(REMOTE_OPTIONS).toEqual([
      { value: 'remote', label: 'Remote' },
      { value: 'hybrid', label: 'Hybrid' },
      { value: 'onsite', label: 'Onsite' },
      { value: 'unclear', label: 'Unclear' },
    ])
  })
})

describe('filtersFromParams', () => {
  it('returns EMPTY_FILTERS for empty params', () => {
    expect(filtersFromParams(new URLSearchParams())).toEqual(EMPTY_FILTERS)
  })

  it('maps scalar params to filter fields', () => {
    const p = new URLSearchParams(
      'q=engineer&minScore=3&maxScore=5&from=2024-01-01&to=2024-12-31&co=Acme&salMin=100',
    )
    expect(filtersFromParams(p)).toEqual({
      search: 'engineer',
      minScore: '3',
      maxScore: '5',
      remoteClassification: [],
      minPostedAt: '2024-01-01',
      maxPostedAt: '2024-12-31',
      company: 'Acme',
      minSalaryK: '100',
    })
  })

  it('collects multiple rc values into remoteClassification array', () => {
    const p = new URLSearchParams('rc=fully_remote&rc=hybrid')
    expect(filtersFromParams(p).remoteClassification).toEqual(['fully_remote', 'hybrid'])
  })

  it('defaults missing scalar params to empty string', () => {
    const p = new URLSearchParams('rc=hybrid')
    const f = filtersFromParams(p)
    expect(f.search).toBe('')
    expect(f.minScore).toBe('')
    expect(f.company).toBe('')
  })
})

describe('filtersToParams', () => {
  it('returns empty URLSearchParams for EMPTY_FILTERS', () => {
    expect(filtersToParams(EMPTY_FILTERS).toString()).toBe('')
  })

  it('sets scalar params only when non-empty', () => {
    const f: Filters = { ...EMPTY_FILTERS, minScore: '2', company: 'Acme' }
    const p = filtersToParams(f)
    expect(p.get('minScore')).toBe('2')
    expect(p.get('co')).toBe('Acme')
    expect(p.has('maxScore')).toBe(false)
  })

  it('appends multiple rc values', () => {
    const f: Filters = { ...EMPTY_FILTERS, remoteClassification: ['fully_remote', 'hybrid'] }
    expect(filtersToParams(f).getAll('rc')).toEqual(['fully_remote', 'hybrid'])
  })
})

describe('filtersFromParams / filtersToParams round-trip', () => {
  it('round-trips a fully-populated filter', () => {
    const original: Filters = {
      search: 'engineer',
      minScore: '2',
      maxScore: '4',
      remoteClassification: ['fully_remote', 'hybrid'],
      minPostedAt: '2024-01-01',
      maxPostedAt: '2024-12-31',
      company: 'Acme',
      minSalaryK: '80',
    }
    expect(filtersFromParams(filtersToParams(original))).toEqual(original)
  })
})

describe('buildJobsParams', () => {
  it('combines filter params with non-default sort params', () => {
    const p = buildJobsParams(
      { ...EMPTY_FILTERS, search: 'eng' },
      { sort: 'company', order: 'asc' },
    )
    expect(p.get('q')).toBe('eng')
    expect(p.get('sort')).toBe('company')
    expect(p.get('order')).toBe('asc')
  })

  it('omits sort params when sort is the default (clean URLs)', () => {
    const p = buildJobsParams({ ...EMPTY_FILTERS, company: 'Acme' }, DEFAULT_SORT)
    expect(p.get('co')).toBe('Acme')
    expect(p.has('sort')).toBe(false)
    expect(p.has('order')).toBe(false)
  })
})

describe('hasActiveFilters', () => {
  it('returns false for EMPTY_FILTERS', () => {
    expect(hasActiveFilters(EMPTY_FILTERS)).toBe(false)
  })

  it('returns true when any scalar field is set', () => {
    expect(hasActiveFilters({ ...EMPTY_FILTERS, search: 'engineer' })).toBe(true)
    expect(hasActiveFilters({ ...EMPTY_FILTERS, minScore: '3' })).toBe(true)
    expect(hasActiveFilters({ ...EMPTY_FILTERS, company: 'Acme' })).toBe(true)
    expect(hasActiveFilters({ ...EMPTY_FILTERS, minSalaryK: '100' })).toBe(true)
  })

  it('returns true when remoteClassification is non-empty', () => {
    expect(hasActiveFilters({ ...EMPTY_FILTERS, remoteClassification: ['hybrid'] })).toBe(true)
  })
})
