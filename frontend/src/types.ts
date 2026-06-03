// API types — generated from Pydantic models via `just sync-types`.
// Do not edit the type aliases below; edit src/api/schemas.py and regenerate.
import type { components } from './schema.gen'

export type JobSummary = components['schemas']['JobSummary']
export type JobDetail = components['schemas']['JobDetail']
export type JobListResponse = components['schemas']['JobListResponse']
export type AiFitDetail = components['schemas']['AiFitDetail']

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
