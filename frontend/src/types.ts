// API types — generated from Pydantic models via `just sync-types`.
// Do not edit the type aliases below; edit src/api/schemas.py and regenerate.
import type { components } from './schema.gen'

export type JobSummary = components['schemas']['JobSummary']
export type JobDetail = components['schemas']['JobDetail']
export type JobListResponse = components['schemas']['JobListResponse']
export type AiFitDetail = components['schemas']['AiFitDetail']
export type Application = components['schemas']['Application']
export type ApplicationCreate = components['schemas']['ApplicationCreate']
export type ApplicationUpdate = components['schemas']['ApplicationUpdate']
export type EvalCorrectionIn = components['schemas']['EvalCorrectionIn']
export type EvalCorrectionOut = components['schemas']['EvalCorrectionOut']
export type SettingsResponse = components['schemas']['SettingsResponse']
export type CandidateProfileInput = components['schemas']['CandidateProfileInput']
export type SearchConfigInput = components['schemas']['SearchConfigInput']
export type SearchEmploymentType = NonNullable<
  NonNullable<NonNullable<SearchConfigInput['work_constraints']>['employment_types']>['acceptable']
>[number]
export const SEARCH_EMPLOYMENT_TYPES = [
  'fulltime',
  'parttime',
  'contract',
] as const satisfies readonly SearchEmploymentType[]
export type SearchSalaryFloorK = NonNullable<
  NonNullable<SearchConfigInput['scrape_preferences']>['salary_floor_k']
>
export const SEARCH_SALARY_FLOORS_K = [
  40, 60, 80, 100, 120,
] as const satisfies readonly SearchSalaryFloorK[]
export type LinkedInExperienceCode = NonNullable<
  NonNullable<SearchConfigInput['scrape_preferences']>['linkedin_experience_codes']
>[number]
export const LINKEDIN_EXPERIENCE_CODES = [
  '1',
  '2',
  '3',
  '4',
  '5',
  '6',
] as const satisfies readonly LinkedInExperienceCode[]
export const LINKEDIN_EXPERIENCE_LABELS: Record<LinkedInExperienceCode, string> = {
  '1': 'Internship',
  '2': 'Entry level',
  '3': 'Associate',
  '4': 'Mid-Senior level',
  '5': 'Director',
  '6': 'Executive',
}
export const DEFAULT_LINKEDIN_EXPERIENCE_CODES = [
  '2',
  '3',
  '4',
  '5',
] as const satisfies readonly LinkedInExperienceCode[]
export type ProfileSaveResponse = components['schemas']['ProfileSaveResponse']
export type SearchSaveResponse = components['schemas']['SearchSaveResponse']
export type PipelineEnabledResponse = components['schemas']['PipelineEnabledResponse']
export interface ManualJobCreate {
  title: string
  fit_score: number
  company?: string | null
  source_url?: string | null
  description?: string | null
  location?: string | null
  posted_at?: string | null
  status: ApplicationStatus
}

// Derived from the generated schema — TS will error if this list diverges from the backend.
export type ApplicationStatus = NonNullable<Application['status']>
export const APPLICATION_STATUSES = [
  'maybe',
  'to_apply',
  'applied',
  'screening',
  'interview',
  'offer',
  'rejected',
  'candidate_withdrew',
  'hired',
  'ghosted',
  'passed',
] as const satisfies readonly ApplicationStatus[]

// Status display labels — used across the triage tabs and in AddJobModal's status dropdown.
export const STATUS_LABELS: Record<ApplicationStatus, string> = {
  maybe: 'Maybe',
  to_apply: 'To Apply',
  applied: 'Applied',
  screening: 'Screening',
  interview: 'Interview',
  offer: 'Offer',
  rejected: 'Rejected',
  candidate_withdrew: 'I Withdrew',
  hired: 'Hired!',
  ghosted: 'Ghosted',
  passed: 'Trashed',
}

// Application event — returned by GET /api/applications/{dedup_hash}/events.
// Mirrors the backend ApplicationEvent Pydantic model.
export interface ApplicationEvent {
  id: string
  dedup_hash: string
  kind: 'status_change' | 'event'
  occurred_at: string
  body: string | null
  tags: string[]
  metadata: Record<string, unknown>
  created_at: string
}

/** Payload for POST /api/applications/{dedup_hash}/events (GenericEvent side of the discriminated union). */
export interface ApplicationEventCreate {
  kind: 'event'
  occurred_at?: string
  body?: string | null
  tags?: string[]
  metadata?: Record<string, unknown>
}

/** Payload for PATCH /api/applications/{dedup_hash}/events/{id}. All fields optional. */
export interface ApplicationEventUpdate {
  occurred_at?: string | null
  body?: string | null
  tags?: string[] | null
  metadata?: Record<string, unknown> | null
}

/** Read `{from, to}` from a status_change event's metadata. */
export function readStatusTransition(event: ApplicationEvent): { from: string | null; to: string } {
  if (event.kind !== 'status_change') {
    throw new Error(`readStatusTransition called on non-status_change event (kind=${event.kind})`)
  }
  const from = event.metadata.from_status as string | null | undefined
  const to = event.metadata.to_status as string | undefined
  if (!to) {
    throw new Error(`status_change event missing metadata.to_status (id=${event.id})`)
  }
  return { from, to }
}

// Frontend-only — not part of the API schema.
export interface Filters {
  search: string
  minScore: string
  maxScore: string
  remoteClassification: string[]
  minPostedAt: string
  maxPostedAt: string
  company: string
  minSalaryK: string
}
