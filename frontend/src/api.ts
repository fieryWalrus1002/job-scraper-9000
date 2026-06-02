import type { Filters, JobListResponse } from './types'

// Empty in dev/prod (Vite proxy + Azure SWA both handle /api/* routing).
// Set VITE_API_URL only if calling the backend directly without a proxy.
const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

export async function fetchJobs(filters: Filters): Promise<JobListResponse> {
  const params = new URLSearchParams()
  if (filters.minScore) params.set('min_score', filters.minScore)
  if (filters.maxScore) params.set('max_score', filters.maxScore)
  if (filters.remoteClassification) params.set('remote_classification', filters.remoteClassification)
  if (filters.minPostedAt) params.set('min_posted_at', filters.minPostedAt)
  if (filters.maxPostedAt) params.set('max_posted_at', filters.maxPostedAt)
  params.set('limit', '1000')

  const res = await fetch(`${API_BASE}/api/jobs?${params.toString()}`)
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
  return res.json() as Promise<JobListResponse>
}
