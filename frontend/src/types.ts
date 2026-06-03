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

// Derived from the generated schema — TS will error if this list diverges from the backend.
export type ApplicationStatus = NonNullable<Application['status']>
export const APPLICATION_STATUSES = [
  'saved', 'maybe', 'to_apply', 'applied',
  'screening', 'interview', 'offer',
  'rejected', 'withdrawn', 'hired', 'ghosted',
] as const satisfies readonly ApplicationStatus[]

// Frontend-only — not part of the API schema.
export interface Filters {
  minScore: string
  maxScore: string
  remoteClassification: string[]
  minPostedAt: string
  maxPostedAt: string
  company: string
  minSalaryK: string
}
