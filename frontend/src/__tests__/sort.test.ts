import { describe, it, expect } from 'vitest'
import { DEFAULT_SORT, applySortParams, defaultDirectionFor, sortFromParams } from '../lib/sort'

describe('sortFromParams', () => {
  it('returns the default when params are absent', () => {
    expect(sortFromParams(new URLSearchParams())).toEqual(DEFAULT_SORT)
  })

  it('parses a valid sort + order', () => {
    expect(sortFromParams(new URLSearchParams('sort=company&order=asc'))).toEqual({
      sort: 'company',
      order: 'asc',
    })
  })

  it('falls back to defaults for unknown / off-whitelist values', () => {
    expect(sortFromParams(new URLSearchParams('sort=scored_at&order=sideways'))).toEqual(
      DEFAULT_SORT,
    )
  })
})

describe('applySortParams', () => {
  it('omits the params entirely when equal to the default (clean URLs)', () => {
    const p = applySortParams(new URLSearchParams('q=eng'), DEFAULT_SORT)
    expect(p.has('sort')).toBe(false)
    expect(p.has('order')).toBe(false)
    expect(p.get('q')).toBe('eng')
  })

  it('writes sort + order when non-default', () => {
    const p = applySortParams(new URLSearchParams(), { sort: 'salary_min_usd', order: 'asc' })
    expect(p.get('sort')).toBe('salary_min_usd')
    expect(p.get('order')).toBe('asc')
  })
})

describe('defaultDirectionFor', () => {
  it('defaults numeric/date columns to desc and text columns to asc', () => {
    expect(defaultDirectionFor('fit_score')).toBe('desc')
    expect(defaultDirectionFor('posted_at')).toBe('desc')
    expect(defaultDirectionFor('salary_min_usd')).toBe('desc')
    expect(defaultDirectionFor('company')).toBe('asc')
    expect(defaultDirectionFor('title')).toBe('asc')
  })
})
