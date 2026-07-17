export function scoreVariant(score: number | null | undefined) {
  if (score == null) return 'muted' as const
  if (score >= 4) return 'score_high' as const
  if (score === 3) return 'score_mid' as const
  return 'score_low' as const
}

export function classificationVariant(value: string | null | undefined) {
  if (!value) return 'muted' as const
  if (value === 'remote' || value === 'fully_remote') return 'remote' as const
  if (value === 'location_restricted') return 'local' as const
  if (value.startsWith('remote_with')) return 'travel' as const
  return 'muted' as const
}

export const sectionLabel = 'text-[10px] font-semibold text-muted uppercase tracking-[0.08em]'
