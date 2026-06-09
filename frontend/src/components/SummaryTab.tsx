import type { JobSummary } from '../types'

interface Props {
  items: JobSummary[]
}

function pct(n: number, total: number) {
  if (total === 0) return '0%'
  return `${Math.round((n / total) * 100)}%`
}

const BAR_COLOR: Record<string, string> = {
  '5': 'bg-score-high',
  '4': 'bg-score-high/80',
  '3': 'bg-score-mid',
  '2': 'bg-score-low/80',
  '1': 'bg-score-low',
  none: 'bg-faint',
}

function StatCard({
  value,
  label,
  accent,
}: {
  value: string | number
  label: string
  accent?: 'high' | 'mid' | 'low' | 'primary'
}) {
  const accentMap = {
    high: 'before:bg-score-high',
    mid: 'before:bg-score-mid',
    low: 'before:bg-score-low',
    primary: 'before:bg-primary',
  } as const
  return (
    <div
      className={
        'relative bg-card border border-border rounded-lg px-5 py-4 ' +
        'shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] ' +
        'overflow-hidden ' +
        'before:absolute before:inset-x-0 before:top-0 before:h-px ' +
        (accent ? accentMap[accent] : 'before:bg-transparent')
      }
    >
      <div className="text-[28px] font-semibold text-fg leading-none font-mono tabular-nums tracking-tight">
        {value}
      </div>
      <div className="mt-1.5 text-[11px] font-medium text-muted uppercase tracking-[0.08em]">
        {label}
      </div>
    </div>
  )
}

export default function SummaryTab({ items }: Props) {
  const total = items.length
  const scored = items.filter((j) => j.fit_score !== null)
  const avgScore =
    scored.length > 0
      ? (scored.reduce((s, j) => s + (j.fit_score ?? 0), 0) / scored.length).toFixed(2)
      : '—'

  const fullyRemote = items.filter((j) => j.remote_classification === 'fully_remote').length
  const failures = items.filter((j) => j.failure_reason !== null).length

  const scoreDist: Record<string, number> = { '5': 0, '4': 0, '3': 0, '2': 0, '1': 0, none: 0 }
  for (const j of items) {
    const k = j.fit_score !== null ? String(j.fit_score) : 'none'
    scoreDist[k] = (scoreDist[k] ?? 0) + 1
  }

  const classificationCounts: Record<string, number> = {}
  for (const j of items) {
    const k = j.remote_classification ?? 'unknown'
    classificationCounts[k] = (classificationCounts[k] ?? 0) + 1
  }
  const sortedClassifications = Object.entries(classificationCounts).sort((a, b) => b[1] - a[1])

  const maxCount = Math.max(...Object.values(scoreDist), 1)

  return (
    <div className="p-6 overflow-y-auto">
      <div className="grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-3 mb-8">
        <StatCard value={total.toLocaleString()} label="Jobs" accent="primary" />
        <StatCard value={avgScore} label="Avg fit score" accent="high" />
        <StatCard value={fullyRemote.toLocaleString()} label="Fully remote" accent="mid" />
        <StatCard
          value={failures > 0 ? failures : '0'}
          label="Scoring failures"
          accent={failures > 0 ? 'low' : undefined}
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-card border border-border rounded-lg px-5 py-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
          <h3 className="text-[11px] uppercase tracking-[0.08em] text-muted mb-4 font-semibold flex items-center gap-2">
            Score distribution
            <span className="text-faint font-mono normal-case tracking-normal">
              · {total.toLocaleString()} jobs
            </span>
          </h3>
          <div className="flex flex-col gap-2.5">
            {(['5', '4', '3', '2', '1', 'none'] as const).map((k) => {
              const count = scoreDist[k] ?? 0
              const barPct = (count / maxCount) * 100
              return (
                <div key={k} className="flex items-center gap-3 group">
                  <div className="w-20 text-[12px] text-muted shrink-0 whitespace-nowrap">
                    {k === 'none' ? (
                      'No score'
                    ) : (
                      <>
                        <span className="text-faint">Score</span>{' '}
                        <span className="font-mono text-fg">{k}</span>
                      </>
                    )}
                  </div>
                  <div className="flex-1 h-2.5 bg-bg-elevated rounded-full overflow-hidden border border-border/40">
                    <div
                      className={`h-full rounded-full transition-[width] duration-500 ease-out min-w-[2px] ${BAR_COLOR[k]}`}
                      style={{ width: `${barPct}%` }}
                    />
                  </div>
                  <div className="text-[12px] whitespace-nowrap w-24 text-right font-mono tabular-nums">
                    <span className="text-fg">{count}</span>
                    <span className="text-faint ml-1.5">({pct(count, total)})</span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        <div className="bg-card border border-border rounded-lg px-5 py-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]">
          <h3 className="text-[11px] uppercase tracking-[0.08em] text-muted mb-4 font-semibold">
            Remote classification
          </h3>
          <div className="flex flex-col gap-2.5">
            {sortedClassifications.map(([cls, count]) => {
              const color =
                cls === 'fully_remote'
                  ? 'bg-remote'
                  : cls === 'location_restricted'
                    ? 'bg-local'
                    : cls.startsWith('remote_with')
                      ? 'bg-travel'
                      : 'bg-faint'
              return (
                <div key={cls} className="flex items-center gap-3">
                  <div className="w-32 text-[12px] text-muted shrink-0 whitespace-nowrap overflow-hidden text-ellipsis">
                    {cls.replace(/_/g, ' ')}
                  </div>
                  <div className="flex-1 h-2.5 bg-bg-elevated rounded-full overflow-hidden border border-border/40">
                    <div
                      className={`h-full rounded-full min-w-[2px] transition-[width] duration-500 ease-out ${color}`}
                      style={{ width: pct(count, total) }}
                    />
                  </div>
                  <div className="text-[12px] whitespace-nowrap w-24 text-right font-mono tabular-nums">
                    <span className="text-fg">{count}</span>
                    <span className="text-faint ml-1.5">({pct(count, total)})</span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
