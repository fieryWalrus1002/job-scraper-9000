import type { Application, ApplicationCreate, ApplicationUpdate, Filters, JobDetail, JobListResponse } from './types'

// Empty in dev/prod (Vite proxy + Azure SWA both handle /api/* routing).
// Set VITE_API_URL only if calling the backend directly without a proxy.
const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

export async function fetchJobs(filters: Filters): Promise<JobListResponse> {
  const params = new URLSearchParams()
  if (filters.minScore) params.set('min_score', filters.minScore)
  if (filters.maxScore) params.set('max_score', filters.maxScore)
  filters.remoteClassification.forEach((v) => params.append('remote_classification', v))
  if (filters.minPostedAt) params.set('min_posted_at', filters.minPostedAt)
  if (filters.maxPostedAt) params.set('max_posted_at', filters.maxPostedAt)
  if (filters.company) params.set('company', filters.company)
  if (filters.minSalaryK) params.set('min_salary_usd', String(Number(filters.minSalaryK) * 1000))
  params.set('limit', '1000')

  const res = await fetch(`${API_BASE}/api/jobs?${params.toString()}`)
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
  return res.json() as Promise<JobListResponse>
}

export async function fetchJobDetail(dedupHash: string): Promise<JobDetail> {
  const res = await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(dedupHash)}`)
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
  return res.json() as Promise<JobDetail>
}

export async function fetchApplications(): Promise<Application[]> {
  const res = await fetch(`${API_BASE}/api/applications`)
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
  return res.json() as Promise<Application[]>
}

export async function createApplication(body: ApplicationCreate): Promise<Application> {
  const res = await fetch(`${API_BASE}/api/applications`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
  return res.json() as Promise<Application>
}

export async function updateApplication(dedupHash: string, body: ApplicationUpdate): Promise<Application> {
  const res = await fetch(`${API_BASE}/api/applications/${encodeURIComponent(dedupHash)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
  return res.json() as Promise<Application>
}
