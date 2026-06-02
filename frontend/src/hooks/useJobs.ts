import { useQuery } from '@tanstack/react-query'
import { fetchJobs } from '../api'
import type { Filters } from '../types'

export function useJobs(filters: Filters) {
  return useQuery({
    queryKey: ['jobs', filters],
    queryFn: () => fetchJobs(filters),
    staleTime: 1000 * 60 * 5,
  })
}
