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
