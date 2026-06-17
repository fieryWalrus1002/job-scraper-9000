import type {
  Application,
  ApplicationCreate,
  ApplicationStatus,
  ApplicationUpdate,
  CandidateProfileInput,
  EvalCorrectionIn,
  EvalCorrectionOut,
  Filters,
  JobDetail,
  JobListResponse,
  ManualJobCreate,
  ProfileSaveResponse,
  SearchConfigInput,
  SearchSaveResponse,
  SettingsResponse,
} from './types'

// Empty in dev/prod (Vite proxy + Azure SWA both handle /api/* routing).
// Set VITE_API_URL only if calling the backend directly without a proxy.
const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

/** Field path (e.g. "summary", "constraints.hard") → first validation message. */
export type FieldErrors = Record<string, string>

/** Thrown on a 422 so forms can render messages next to the offending field. */
export class ApiValidationError extends Error {
  fields: FieldErrors
  constructor(fields: FieldErrors) {
    super('Validation failed')
    this.name = 'ApiValidationError'
    this.fields = fields
  }
}

interface FastApiDetailItem {
  loc: (string | number)[]
  msg: string
}

// FastAPI 422 bodies are { detail: [{ loc: ["body", <field>...], msg }] }.
// Drop the leading "body" and join the rest so nested fields get a stable key;
// first message per field wins (one inline error is enough).
function parseValidationErrors(detail: FastApiDetailItem[]): FieldErrors {
  const fields: FieldErrors = {}
  for (const item of detail) {
    const path = item.loc.filter((p) => p !== 'body').join('.')
    if (path && !(path in fields)) fields[path] = item.msg
  }
  return fields
}

export async function fetchJobs(
  filters: Filters,
  page: number,
  pageSize: number,
  signal?: AbortSignal,
): Promise<JobListResponse> {
  const params = new URLSearchParams()
  if (filters.search) params.set('search', filters.search)
  if (filters.minScore) params.set('min_score', filters.minScore)
  if (filters.maxScore) params.set('max_score', filters.maxScore)
  filters.remoteClassification.forEach((v) => params.append('remote_classification', v))
  if (filters.minPostedAt) params.set('min_posted_at', filters.minPostedAt)
  if (filters.maxPostedAt) params.set('max_posted_at', filters.maxPostedAt)
  if (filters.company) params.set('company', filters.company)
  if (filters.minSalaryK) params.set('min_salary_usd', String(Number(filters.minSalaryK) * 1000))
  params.set('limit', String(pageSize))
  params.set('offset', String(page * pageSize))

  const res = await fetch(`${API_BASE}/api/jobs?${params.toString()}`, { signal })
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
  return res.json() as Promise<JobListResponse>
}

export async function fetchJobDetail(dedupHash: string, signal?: AbortSignal): Promise<JobDetail> {
  const res = await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(dedupHash)}`, { signal })
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
  return res.json() as Promise<JobDetail>
}

export function normalizeApplicationStatuses(statuses?: ApplicationStatus[]): ApplicationStatus[] {
  return Array.from(new Set(statuses ?? [])).sort()
}

export async function fetchApplications(
  statuses?: ApplicationStatus[],
  signal?: AbortSignal,
): Promise<Application[]> {
  const params = new URLSearchParams()
  normalizeApplicationStatuses(statuses).forEach((status) => params.append('status', status))
  const query = params.toString()
  const res = await fetch(`${API_BASE}/api/applications${query ? `?${query}` : ''}`, { signal })
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

export async function deleteApplication(dedupHash: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/applications/${encodeURIComponent(dedupHash)}`, {
    method: 'DELETE',
  })
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
}

export async function createManualJob(body: ManualJobCreate): Promise<Application> {
  const res = await fetch(`${API_BASE}/api/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (res.status === 409) throw new Error('409: Job already exists')
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
  return res.json() as Promise<Application>
}

export async function updateApplication(
  dedupHash: string,
  body: ApplicationUpdate,
): Promise<Application> {
  const res = await fetch(`${API_BASE}/api/applications/${encodeURIComponent(dedupHash)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
  return res.json() as Promise<Application>
}

// ───── Settings ─────

export async function fetchSettings(signal?: AbortSignal): Promise<SettingsResponse> {
  const res = await fetch(`${API_BASE}/api/settings`, { signal })
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
  return res.json() as Promise<SettingsResponse>
}

export async function saveProfile(body: CandidateProfileInput): Promise<ProfileSaveResponse> {
  const res = await fetch(`${API_BASE}/api/settings/profile`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (res.status === 422) {
    const data = (await res.json()) as { detail?: FastApiDetailItem[] }
    throw new ApiValidationError(parseValidationErrors(data.detail ?? []))
  }
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
  return res.json() as Promise<ProfileSaveResponse>
}

export async function saveSearch(body: SearchConfigInput): Promise<SearchSaveResponse> {
  const res = await fetch(`${API_BASE}/api/settings/search`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (res.status === 422) {
    const data = (await res.json()) as { detail?: FastApiDetailItem[] }
    throw new ApiValidationError(parseValidationErrors(data.detail ?? []))
  }
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
  return res.json() as Promise<SearchSaveResponse>
}

// ───── Eval corrections ─────

export async function fetchEvalCorrection(
  dedupHash: string,
  signal?: AbortSignal,
): Promise<EvalCorrectionOut | null> {
  const res = await fetch(`${API_BASE}/api/eval/corrections/${encodeURIComponent(dedupHash)}`, {
    signal,
  })
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
  return res.json() as Promise<EvalCorrectionOut>
}

export async function upsertEvalCorrection(body: EvalCorrectionIn): Promise<EvalCorrectionOut> {
  const res = await fetch(`${API_BASE}/api/eval/corrections`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
  return res.json() as Promise<EvalCorrectionOut>
}

export async function deleteEvalCorrection(dedupHash: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/eval/corrections/${encodeURIComponent(dedupHash)}`, {
    method: 'DELETE',
  })
  // Idempotent: 404 means it's already gone, which is the desired end state.
  // The UI "Clear" flow can race with stale state or concurrent deletes.
  if (res.status === 404) return
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`)
}
