import { useQuery } from '@tanstack/react-query'
import { fetchGrabBag, type GrabBagFilters } from '../api'

/**
 * Fetch a seeded grab-bag batch from `GET /jobs?mode=grabbag`.
 * Keyed on `[seed]` so a seed change (reroll) triggers a fresh fetch.
 * Refreshing the page with the same seed in the URL returns the same batch.
 */
export function useGrabBag(seed: number, filters?: GrabBagFilters) {
  return useQuery({
    queryKey: ['grabbag', seed, filters],
    queryFn: ({ signal }) => fetchGrabBag(seed, filters, signal),
    staleTime: 0, // grab-bag is a live sample; always refetch on seed change
    retry: 1,
  })
}
