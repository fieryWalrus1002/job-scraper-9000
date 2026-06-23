/**
 * Seeded tag suggestions for the add-note form.
 * Phase A: frontend-only constant (no backend YAML consumer yet).
 * Users can also type freeform tags not in this list.
 */
export const EVENT_TAG_SUGGESTIONS = [
  'contact',
  'follow_up',
  'interview_prep',
  'offer_terms',
  'application_submitted',
  'salary_discussion',
  'technical_screen',
  'culture_fit',
  'reference_check',
  'offer_received',
] as const satisfies readonly string[]
