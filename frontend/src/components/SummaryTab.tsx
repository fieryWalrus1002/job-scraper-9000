import type { JobSummary } from '../types'

interface Props {
  items: JobSummary[]
}

function pct(n: number, total: number) {
  if (total === 0) return '0%'
  return `${Math.round((n / total) * 100)}%`
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

  const scoreDist: Record<string, number> = { '5': 0, '4': 0, '3': 0, '2': 0, '1': 0, 'none': 0 }
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
    <div className="summary">
      <div className="summary-stats">
        <div className="stat-card">
          <div className="stat-value">{total.toLocaleString()}</div>
          <div className="stat-label">Jobs</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{avgScore}</div>
          <div className="stat-label">Avg fit score</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{fullyRemote.toLocaleString()}</div>
          <div className="stat-label">Fully remote</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{failures > 0 ? failures : '0'}</div>
          <div className="stat-label">Scoring failures</div>
        </div>
      </div>

      <div className="summary-sections">
        <div className="summary-section">
          <h3 className="summary-section-title">Score distribution</h3>
          <div className="dist-chart">
            {(['5', '4', '3', '2', '1', 'none'] as const).map((k) => {
              const count = scoreDist[k] ?? 0
              const barPct = (count / maxCount) * 100
              const cls =
                k === '5' || k === '4' ? 'dist-bar--high' :
                k === '3' ? 'dist-bar--mid' :
                k === '1' || k === '2' ? 'dist-bar--low' : 'dist-bar--muted'
              return (
                <div key={k} className="dist-row">
                  <div className="dist-label">{k === 'none' ? 'No score' : `Score ${k}`}</div>
                  <div className="dist-track">
                    <div className={`dist-bar ${cls}`} style={{ width: `${barPct}%` }} />
                  </div>
                  <div className="dist-count">{count} <span className="text-muted">({pct(count, total)})</span></div>
                </div>
              )
            })}
          </div>
        </div>

        <div className="summary-section">
          <h3 className="summary-section-title">Remote classification</h3>
          <div className="dist-chart">
            {sortedClassifications.map(([cls, count]) => (
              <div key={cls} className="dist-row">
                <div className="dist-label">{cls.replace(/_/g, ' ')}</div>
                <div className="dist-track">
                  <div className="dist-bar dist-bar--muted" style={{ width: pct(count, total) }} />
                </div>
                <div className="dist-count">{count} <span className="text-muted">({pct(count, total)})</span></div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
