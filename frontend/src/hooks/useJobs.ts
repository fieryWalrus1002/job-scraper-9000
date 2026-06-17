import { useQuery } from '@tanstack/react-query'
import { fetchJobs } from '../api'
import type { Filters } from '../types'

const PAGE_SIZE = 50

export function useJobs(filters: Filters, page: number) {
  const safePage = Math.max(0, page)
  return useQuery({
    queryKey: ['jobs', filters, page],
    queryFn: ({ signal }) => fetchJobs(filters, safePage, PAGE_SIZE, signal),
    staleTime: 1000 * 60 * 5,
    // Default is 3 retries with exponential backoff (~7s of stale view before
    // an error surfaces). staleTime already serves cached data through transient
    // blips, so cap retries at 1 for prompt failure feedback.
    retry: 1,
  })
}

export { PAGE_SIZE }
