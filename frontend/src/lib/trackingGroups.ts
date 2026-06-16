import type { ApplicationStatus } from '../types'

// The Tracking tab is a 3-group action board (spec §3.3). Every committed status
// belongs to exactly one group. `as const satisfies …` keeps the literal types
// (for the exhaustiveness guard below) while rejecting any non-ApplicationStatus.
const TO_APPLY = ['to_apply'] as const satisfies readonly ApplicationStatus[]
const ACTIVE = [
  'applied',
  'screening',
  'interview',
  'offer',
] as const satisfies readonly ApplicationStatus[]
const CLOSED = [
  'rejected',
  'candidate_withdrew',
  'hired',
  'ghosted',
] as const satisfies readonly ApplicationStatus[]

// Compile-time funnel-totality guard: every ApplicationStatus must map to exactly
// one tab — Shortlist (`maybe`), Trash (`passed`), or one Tracking group. Add a
// status to the type without slotting it here and `Uncovered` becomes non-empty,
// which fails this assertion at build time instead of silently dropping rows.
type TrackedStatus = (typeof TO_APPLY | typeof ACTIVE | typeof CLOSED)[number]
type Uncovered = Exclude<ApplicationStatus, TrackedStatus | 'maybe' | 'passed'>
type AssertNever<T extends never> = T
export type FunnelStatusesAreExhaustive = AssertNever<Uncovered>

export const TO_APPLY_STATUSES: ApplicationStatus[] = [...TO_APPLY]
export const ACTIVE_STATUSES: ApplicationStatus[] = [...ACTIVE]
export const CLOSED_STATUSES: ApplicationStatus[] = [...CLOSED]

export const TRACKING_STATUSES: ApplicationStatus[] = [
  ...TO_APPLY_STATUSES,
  ...ACTIVE_STATUSES,
  ...CLOSED_STATUSES,
]
