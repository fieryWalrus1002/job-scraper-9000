import { useQuery } from '@tanstack/react-query'
import { fetchJobs } from '../api'
import type { Filters } from '../types'

const PAGE_SIZE = 50

export function useJobs(filters: Filters, page: number) {
  return useQuery({
    queryKey: ['jobs', filters, page],
    queryFn: () => fetchJobs(filters, page, PAGE_SIZE),
    staleTime: 1000 * 60 * 5,
  })
}

export { PAGE_SIZE }
