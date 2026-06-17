import type { JobSummary } from '../../../types'

function thousands(n: number): number {
  // 120000 → 120, 162500 → 163 (whole thousands read cleaner in a table).
  return Math.round(n / 1000)
}

/** Salary range as "$120–160k"; falls back to a single bound or an em dash. */
export function SalaryCell({ job }: { job: JobSummary }) {
  const { salary_min_usd: min, salary_max_usd: max } = job
  let text: string | null = null
  if (min != null && max != null) text = `$${thousands(min)}–${thousands(max)}k`
  else if (min != null) text = `$${thousands(min)}k+`
  else if (max != null) text = `up to $${thousands(max)}k`

  if (text === null) return <span className="text-faint">—</span>
  return (
    <span className="text-muted font-mono text-[12px] tabular-nums whitespace-nowrap">{text}</span>
  )
}
