// Sort state for the Jobs feed. Mirrors the backend whitelist in
// src/api/routes/jobs.py (_SORT_COLUMNS) — keep the two in sync.

export const SORT_KEYS = ['fit_score', 'posted_at', 'company', 'title', 'salary_min_usd'] as const
export type SortKey = (typeof SORT_KEYS)[number]
export type SortOrder = 'asc' | 'desc'

export interface SortState {
  sort: SortKey
  order: SortOrder
}

export const DEFAULT_SORT: SortState = { sort: 'fit_score', order: 'desc' }

// Per-key default direction when a column is newly selected: numeric/date
// columns read best high-to-low (newest/highest first); text reads A→Z.
const DEFAULT_DIRECTION: Record<SortKey, SortOrder> = {
  fit_score: 'desc',
  posted_at: 'desc',
  salary_min_usd: 'desc',
  company: 'asc',
  title: 'asc',
}

export function defaultDirectionFor(key: SortKey): SortOrder {
  return DEFAULT_DIRECTION[key]
}

function isSortKey(v: string | null): v is SortKey {
  return v !== null && (SORT_KEYS as readonly string[]).includes(v)
}

export function sortFromParams(params: URLSearchParams): SortState {
  const sort = params.get('sort')
  // An invalid/absent sort key falls back to the whole default pair.
  if (!isSortKey(sort)) return DEFAULT_SORT
  // A valid key with an invalid/absent order keeps the chosen column but uses
  // that column's natural direction (what clicking its header would give), so a
  // hand-edited `?sort=company&order=bogus` resolves to a coherent {company, asc}
  // rather than a pairing the user never chose.
  const order = params.get('order')
  return { sort, order: order === 'asc' || order === 'desc' ? order : defaultDirectionFor(sort) }
}

/** Apply sort onto an existing params object (mutates + returns it). Omits the
 * params entirely when they equal the default so default URLs stay clean. */
export function applySortParams(params: URLSearchParams, state: SortState): URLSearchParams {
  if (state.sort === DEFAULT_SORT.sort && state.order === DEFAULT_SORT.order) {
    params.delete('sort')
    params.delete('order')
  } else {
    params.set('sort', state.sort)
    params.set('order', state.order)
  }
  return params
}
