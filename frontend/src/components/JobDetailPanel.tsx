import { useEffect, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchJobDetail } from '../api'
import type { AiFitDetail, Application, ApplicationStatus } from '../types'
import { APPLICATION_STATUSES } from '../types'
import { useDeleteApplication, useMarkApplication, useUpdateApplication } from '../hooks/useApplications'
import styles from './JobDetailPanel.module.css'


interface Props {
  dedupHash: string | null
  onClose: () => void
  application?: Application
}

function ApplicationTrackingSection({ dedupHash, application }: { dedupHash: string; application: Application | undefined }) {
  const mark = useMarkApplication()
  const update = useUpdateApplication()
  const del = useDeleteApplication()
  const [notes, setNotes] = useState(application?.notes ?? '')
  const isPending = mark.isPending || update.isPending || del.isPending

  // Sync textarea when the application record or job changes (server → local state).
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setNotes(application?.notes ?? '')
  }, [application?.notes, dedupHash])

  function handleStatusChange(status: ApplicationStatus) {
    if (application) {
      update.mutate({ dedupHash, update: { status } })
    } else {
      mark.mutate({ dedupHash, status })
    }
  }

  function handleNotesBlur() {
    if (notes === (application?.notes ?? '')) return
    if (application) {
      update.mutate({ dedupHash, update: { notes } })
    } else if (notes.trim()) {
      mark.mutate({ dedupHash, status: 'saved', notes })
    }
  }

  return (
    <div className={styles['app-tracking']}>
      <div className={styles['detail-field']}>
        <div className={styles['detail-field-label']}>Status</div>
        <div className={styles['app-status-buttons']}>
          {APPLICATION_STATUSES.map((s) => (
            <button
              key={s}
              className={`app-status-btn${application?.status === s ? ' app-status-btn--active' : ''}`}
              disabled={isPending}
              onClick={() => handleStatusChange(s)}
            >
              {s.replace(/_/g, ' ')}
            </button>
          ))}
        </div>
      </div>
      <div className={styles['detail-field']}>
        <div className={styles['detail-field-label']}>Notes</div>
        <textarea
          className={"app-notes"}
          value={notes}
          rows={4}
          placeholder="Add notes…"
          onChange={(e) => setNotes(e.target.value)}
          onBlur={handleNotesBlur}
        />
      </div>
      {application && (
        <div className={styles['detail-meta-row']} style={{ marginTop: 8 }}>
          <span className={styles['detail-meta-label']}>Last updated</span>
          <span className={styles['detail-meta-value']}>{application.updated_at}</span>
          <button
            className="btn btn--danger btn--sm"
            disabled={isPending}
            onClick={() => { if (window.confirm('Remove tracking for this job?')) del.mutate(dedupHash) }}
            style={{ marginLeft: 'auto' }}
          >
            Remove tracking
          </button>
        </div>
      )}
    </div>
  )
}

function Section({
  title,
  children,
  defaultOpen = true,
  badge,
}: {
  title: string
  children: ReactNode
  defaultOpen?: boolean
  badge?: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className={styles['detail-section']}>
      <button className={styles['detail-section-header']} onClick={() => setOpen((v) => !v)}>
        <span>{title}</span>
        <span className={styles['detail-section-header-right']}>
          {badge}
          <span className={styles['filter-toggle-arrow']}>{open ? '▴' : '▾'}</span>
        </span>
      </button>
      {open && <div className={styles['detail-section-body']}>{children}</div>}
    </div>
  )
}

function BulletList({ items, className }: { items: unknown; className?: string }) {
  const arr = Array.isArray(items)
    ? items.filter((v): v is string => typeof v === 'string')
    : []
  if (arr.length === 0) return <span className={"text-muted"}>None</span>
  return (
    <ul className={`detail-bullet-list ${className ?? ''}`}>
      {arr.map((item, i) => <li key={`${i}-${item}`}>{item}</li>)}
    </ul>
  )
}

function SkillsFitSection({ ai }: { ai: AiFitDetail | null }) {
  if (!ai) return <p className={"text-muted"}>No skills fit data available.</p>
  return (
    <div className={styles['detail-skills-fit']}>
      {ai.score_rationale && (
        <div className={styles['detail-field']}>
          <div className={styles['detail-field-label']}>Rationale</div>
          <div className={styles['detail-rationale']}>{ai.score_rationale}</div>
        </div>
      )}
      {!!ai.core_job_duties?.length && (
        <div className={styles['detail-field']}>
          <div className={styles['detail-field-label']}>Core Duties</div>
          <BulletList items={ai.core_job_duties} />
        </div>
      )}
      {!!ai.top_matches?.length && (
        <div className={styles['detail-field']}>
          <div className={styles['detail-field-label']}>Matches</div>
          <BulletList items={ai.top_matches} className={styles['detail-bullet-list--good']} />
        </div>
      )}
      {!!ai.gaps?.length && (
        <div className={styles['detail-field']}>
          <div className={styles['detail-field-label']}>Gaps</div>
          <BulletList items={ai.gaps} className={styles['detail-bullet-list--warn']} />
        </div>
      )}
      {!!ai.hard_concerns?.length && (
        <div className={styles['detail-field']}>
          <div className={styles['detail-field-label']}>Hard Concerns</div>
          <BulletList items={ai.hard_concerns} className={styles['detail-bullet-list--bad']} />
        </div>
      )}
    </div>
  )
}

export default function JobDetailPanel({ dedupHash, onClose, application }: Props) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['job', dedupHash],
    queryFn: () => fetchJobDetail(dedupHash!),
    enabled: !!dedupHash,
  })

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  // Lock body scroll while open
  useEffect(() => {
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prevOverflow }
  }, [])

  if (!dedupHash) return null

  const scoreClass = data?.fit_score != null
    ? data.fit_score >= 4 ? 'badge--high' : data.fit_score === 3 ? 'badge--mid' : 'badge--low'
    : 'badge--muted'

  return (
    <div className={styles['modal-overlay']} onClick={onClose} role="presentation">
      <div
        className={styles['job-detail-panel']}
        role="dialog"
        aria-modal="true"
        aria-labelledby="job-detail-title"
        onClick={(e) => e.stopPropagation()}
      >

        {/* ── Header ───────────────────────────────── */}
        <div className={styles['job-detail-header']}>
          <div className={styles['job-detail-header-main']}>
            <h2 id="job-detail-title" className={styles['job-detail-title']}>{data?.title ?? '—'}</h2>
            <div className={styles['job-detail-meta']}>
              <span>{data?.company ?? '—'}</span>
              {data?.location && <><span className="text-muted">·</span><span>{data.location}</span></>}
              {data?.posted_at && <><span className="text-muted">·</span><span className="text-muted">{data.posted_at}</span></>}
            </div>
            <div className={styles['job-detail-badges']}>
              {data?.fit_score != null && (
                <span className={`badge ${scoreClass}`}>Score {data.fit_score}</span>
              )}
              {data?.confidence && (
                <span className="text-muted" style={{ fontSize: 12 }}>{data.confidence} confidence</span>
              )}
              {data?.remote_classification && (
                <span className="badge badge--muted" style={{ fontSize: 11 }}>
                  {data.remote_classification.replace(/_/g, ' ')}
                </span>
              )}
              {(data?.salary_min_usd || data?.salary_max_usd) && (
                <span className="badge badge--muted" style={{ fontSize: 11 }}>
                  {data.salary_min_usd && data.salary_max_usd
                    ? `$${(data.salary_min_usd / 1000).toFixed(0)}–$${(data.salary_max_usd / 1000).toFixed(0)}K`
                    : data.salary_min_usd
                    ? `$${(data.salary_min_usd / 1000).toFixed(0)}K+`
                    : `Up to $${(data.salary_max_usd! / 1000).toFixed(0)}K`}
                  {data.salary_period ? ` / ${data.salary_period}` : ''}
                </span>
              )}
            </div>
          </div>
          <div className={styles['job-detail-header-actions']}>
            {data?.source_url && (
              <a
                className="btn"
                href={data.source_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                View posting ↗
              </a>
            )}
            <button className="btn btn--ghost" onClick={onClose} aria-label="Close job detail panel">✕</button>
          </div>
        </div>

        {/* ── Body ─────────────────────────────────── */}
        <div className={styles['job-detail-body']}>
          {isLoading && <div className="status-msg">Loading…</div>}
          {isError && (
            <div className="status-msg status-msg--error">
              {(error as Error).message}
            </div>
          )}

          {data && (
            <>
              <Section title="Description">
                <pre className={styles['detail-description']}>
                  {data.description ?? <span className={"text-muted"}>No description available.</span>}
                </pre>
              </Section>

              <Section
                title="Skills Fit"
                badge={data.fit_score != null
                  ? <span className={`badge ${scoreClass}`} style={{ marginRight: 8 }}>{data.fit_score}</span>
                  : undefined}
              >
                <SkillsFitSection ai={data.ai_fit_detail} />
              </Section>

              <Section title="Eval Correction" defaultOpen={false}>
                <div className={styles['detail-placeholder']}>
                  Mark scoring errors and add corrections for gold dataset export.
                  <span className="filter-label-note" style={{ marginLeft: 6 }}>coming soon</span>
                </div>
              </Section>

              <Section title="Application Tracking" defaultOpen={false}>
                <ApplicationTrackingSection dedupHash={data.dedup_hash} application={application} />
              </Section>

              <Section title="Dev Metadata" defaultOpen={false}>
                <div className={styles['detail-meta-grid']}>
                  {[
                    ['Model', data.model],
                    ['Provider', data.provider],
                    ['Profile version', data.profile_version],
                    ['Run ID', data.run_id],
                    ['Scored at', data.scored_at],
                    ['Ingested at', data.ingested_at],
                    ['Source', data.source],
                    ['Source job ID', data.source_job_id],
                  ].map(([label, value]) => (
                    <div key={label} className={styles['detail-meta-row']}>
                      <span className={styles['detail-meta-label']}>{label}</span>
                      <span className={styles['detail-meta-value']}>{value ?? '—'}</span>
                    </div>
                  ))}
                </div>
              </Section>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
