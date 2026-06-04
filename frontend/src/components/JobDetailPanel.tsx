import { useEffect, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchJobDetail } from '../api'
import type { AiFitDetail, Application, ApplicationStatus, EvalCorrectionOut } from '../types'
import { APPLICATION_STATUSES, STATUS_LABELS } from '../types'
import { useDeleteApplication, useMarkApplication, useUpdateApplication } from '../hooks/useApplications'
import { useDeleteEvalCorrection, useEvalCorrection, useSetEvalCorrection } from '../hooks/useEvalCorrection'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface Props {
  dedupHash: string | null
  onClose: () => void
  application?: Application
}

function scoreVariant(score: number | null | undefined) {
  if (score == null) return 'muted' as const
  if (score >= 4) return 'score_high' as const
  if (score === 3) return 'score_mid' as const
  return 'score_low' as const
}

function classificationVariant(value: string | null | undefined) {
  if (!value) return 'muted' as const
  if (value === 'fully_remote') return 'remote' as const
  if (value === 'location_restricted') return 'local' as const
  if (value.startsWith('remote_with')) return 'travel' as const
  return 'muted' as const
}

const sectionLabel = 'text-[10px] font-semibold text-muted uppercase tracking-[0.08em]'

function ApplicationTrackingSection({ dedupHash, application }: { dedupHash: string; application: Application | undefined }) {
  const mark = useMarkApplication()
  const update = useUpdateApplication()
  const del = useDeleteApplication()
  const [notes, setNotes] = useState(application?.notes ?? '')
  const isPending = mark.isPending || update.isPending || del.isPending

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
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <div className={sectionLabel}>Status</div>
        <div className="flex flex-wrap gap-1.5">
          {APPLICATION_STATUSES.map((s) => {
            const active = application?.status === s
            return (
              <button
                key={s}
                disabled={isPending}
                onClick={() => handleStatusChange(s)}
                className={cn(
                  'text-xs px-2.5 h-7 rounded-md border border-border bg-card text-muted cursor-pointer transition-all',
                  'hover:border-border-strong hover:text-fg',
                  'disabled:opacity-40 disabled:cursor-default',
                  active && 'bg-primary/15 border-primary/40 text-primary-hov font-medium shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]',
                )}
              >
                {STATUS_LABELS[s]}
              </button>
            )
          })}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <div className={sectionLabel}>Notes</div>
        <textarea
          className="w-full min-h-[110px] resize-y bg-bg-elevated border border-border rounded-md text-fg text-[13px] leading-[1.55] p-2.5 outline-none placeholder:text-faint hover:border-border-strong focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/25 transition-[color,border-color,box-shadow]"
          value={notes}
          rows={4}
          placeholder="Add notes…"
          onChange={(e) => setNotes(e.target.value)}
          onBlur={handleNotesBlur}
        />
      </div>

      {application && (
        <div className="flex items-center gap-3 text-[11px] pt-1 border-t border-border/60 mt-1">
          <span className="text-muted">Last updated</span>
          <span className="text-fg font-mono">{application.updated_at}</span>
          <Button
            variant="ghost"
            size="xs"
            className="ml-auto text-faint hover:text-score-low"
            disabled={isPending}
            onClick={() => { if (window.confirm('Remove tracking for this job?')) del.mutate(dedupHash) }}
          >
            Remove tracking
          </Button>
        </div>
      )}
    </div>
  )
}

function EvalCorrectionSection({
  dedupHash,
  existing,
}: {
  dedupHash: string
  existing: EvalCorrectionOut | null | undefined
}) {
  const upsert = useSetEvalCorrection()
  const del = useDeleteEvalCorrection()
  const [correctedScore, setCorrectedScore] = useState<number | null>(
    existing?.corrected_score ?? null,
  )
  const [reason, setReason] = useState(existing?.correction_reason ?? '')
  const isPending = upsert.isPending || del.isPending

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCorrectedScore(existing?.corrected_score ?? null)
    setReason(existing?.correction_reason ?? '')
  }, [existing?.corrected_score, existing?.correction_reason, dedupHash])

  function handleSave() {
    if (correctedScore == null) return
    upsert.mutate({
      dedup_hash: dedupHash,
      corrected_score: correctedScore,
      correction_reason: reason.trim() || null,
    })
  }

  function handleClear() {
    if (existing) del.mutate(dedupHash)
    setCorrectedScore(null)
    setReason('')
  }

  const isDirty =
    correctedScore !== (existing?.corrected_score ?? null) ||
    reason !== (existing?.correction_reason ?? '')
  const canSave = correctedScore != null && (isDirty || !existing)

  function chipCls(n: number, active: boolean) {
    const variant = n >= 4 ? 'high' : n === 3 ? 'mid' : 'low'
    if (!active) {
      return 'bg-card text-muted border-border hover:border-border-strong hover:text-fg'
    }
    return variant === 'high'
      ? 'bg-score-high/20 text-score-high border-score-high/40 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]'
      : variant === 'mid'
        ? 'bg-score-mid/20 text-score-mid border-score-mid/40 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]'
        : 'bg-score-low/20 text-score-low border-score-low/40 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]'
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <div className={sectionLabel}>Corrected score</div>
        <div className="flex flex-wrap gap-1.5">
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              disabled={isPending}
              onClick={() => setCorrectedScore(n)}
              className={cn(
                'size-9 inline-flex items-center justify-center rounded-md border text-[14px] font-mono font-semibold cursor-pointer transition-all tabular-nums disabled:opacity-40 disabled:cursor-default',
                chipCls(n, correctedScore === n),
              )}
            >
              {n}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <div className={sectionLabel}>Reason (optional)</div>
        <textarea
          className="w-full min-h-[80px] resize-y bg-bg border border-border rounded-md text-fg text-[13px] leading-[1.55] px-3 py-2 outline-none placeholder:text-faint hover:border-border-strong focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/25 transition-[color,border-color,box-shadow]"
          value={reason}
          placeholder="What did the AI get wrong?"
          onChange={(e) => setReason(e.target.value)}
        />
      </div>

      <div className="flex items-center gap-3 pt-1 border-t border-border/60 -mx-0 pt-3">
        {existing && (
          <div className="text-[11px] text-muted">
            <span className="font-mono">{existing.original_score ?? '—'}</span>
            <span className="text-faint mx-1">→</span>
            <span className="font-mono text-fg">{existing.corrected_score}</span>
            <span className="text-faint ml-2">
              · {new Date(existing.corrected_at).toLocaleDateString()}
            </span>
          </div>
        )}
        <div className="flex gap-2 ml-auto">
          {existing && (
            <Button variant="ghost" size="sm" disabled={isPending} onClick={handleClear}>
              Clear
            </Button>
          )}
          <Button size="sm" disabled={!canSave || isPending} onClick={handleSave}>
            {upsert.isPending ? 'Saving…' : existing ? 'Update' : 'Save'}
          </Button>
        </div>
      </div>
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
    <div className="border-b border-border last:border-b-0">
      <button
        className="flex items-center justify-between w-full px-7 py-3.5 bg-transparent border-none text-fg text-[13px] font-medium cursor-pointer text-left hover:bg-hover/60 transition-colors group"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="flex items-center gap-2.5">
          <svg
            width="10"
            height="10"
            viewBox="0 0 10 10"
            className={cn('text-faint transition-transform duration-200 group-hover:text-muted', open && 'rotate-90')}
            aria-hidden="true"
          >
            <path d="M3.5 2 L6.5 5 L3.5 8" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {title}
        </span>
        {badge && <span>{badge}</span>}
      </button>
      {open && <div className="px-7 pb-6 pt-2">{children}</div>}
    </div>
  )
}

function BulletList({
  items,
  markerClass,
  itemClass,
}: {
  items: unknown
  markerClass?: string
  itemClass?: string
}) {
  const arr = Array.isArray(items)
    ? items.filter((v): v is string => typeof v === 'string')
    : []
  if (arr.length === 0) return <span className="text-faint text-[13px]">None</span>
  return (
    <ul className={cn('m-0 pl-4 flex flex-col gap-1.5', markerClass, itemClass)}>
      {arr.map((item, i) => (
        <li key={`${i}-${item}`} className="text-[13px] leading-[1.6] text-fg marker:text-faint">{item}</li>
      ))}
    </ul>
  )
}

function SkillsFitSection({ ai }: { ai: AiFitDetail | null }) {
  if (!ai) return <p className="text-faint text-[13px]">No skills fit data available.</p>
  return (
    <div className="flex flex-col gap-4">
      {ai.score_rationale && (
        <div className="flex flex-col gap-1.5">
          <div className={sectionLabel}>Rationale</div>
          <div className="text-[13px] leading-[1.65] text-fg bg-bg border border-border rounded-md px-4 py-3 whitespace-pre-wrap shadow-[inset_0_1px_0_rgba(255,255,255,0.02)]">
            {ai.score_rationale}
          </div>
        </div>
      )}
      {!!ai.core_job_duties?.length && (
        <div className="flex flex-col gap-1.5">
          <div className={sectionLabel}>Core Duties</div>
          <BulletList items={ai.core_job_duties} />
        </div>
      )}
      {!!ai.top_matches?.length && (
        <div className="flex flex-col gap-1.5">
          <div className={cn(sectionLabel, 'text-score-high/80')}>Matches</div>
          <BulletList items={ai.top_matches} markerClass="[&_li]:marker:text-score-high" />
        </div>
      )}
      {!!ai.gaps?.length && (
        <div className="flex flex-col gap-1.5">
          <div className={cn(sectionLabel, 'text-score-mid/80')}>Gaps</div>
          <BulletList items={ai.gaps} markerClass="[&_li]:marker:text-score-mid" />
        </div>
      )}
      {!!ai.hard_concerns?.length && (
        <div className="flex flex-col gap-1.5">
          <div className={cn(sectionLabel, 'text-score-low/80')}>Hard Concerns</div>
          <BulletList
            items={ai.hard_concerns}
            markerClass="[&_li]:marker:text-score-low [&_li]:text-score-low/90"
          />
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
  const { data: correction } = useEvalCorrection(dedupHash)

  if (!dedupHash) return null

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        showCloseButton={false}
        className="sm:max-w-[940px] w-full h-[88vh] p-0 gap-0 overflow-hidden"
      >
        {/* ── Header ───────────────────────────────── */}
        <div className="flex items-start gap-4 px-7 pt-5 pb-4 border-b border-border shrink-0 bg-gradient-to-b from-card to-card/70">
          <div className="flex-1 min-w-0">
            <DialogTitle asChild>
              <h2 className="text-[18px] font-semibold text-fg m-0 mb-1.5 leading-[1.3] tracking-tight">
                {data?.title ?? '—'}
              </h2>
            </DialogTitle>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-fg mb-2.5">
              <span className="font-medium">{data?.company ?? '—'}</span>
              {data?.location && (
                <>
                  <span className="text-faint">·</span>
                  <span className="text-muted">{data.location}</span>
                </>
              )}
              {data?.posted_at && (
                <>
                  <span className="text-faint">·</span>
                  <span className="text-muted font-mono text-[12px]">{data.posted_at}</span>
                </>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              {data?.fit_score != null && (
                <Badge variant={scoreVariant(data.fit_score)} className="text-[11px] px-2">
                  Score <span className="font-mono ml-0.5">{data.fit_score}</span>
                </Badge>
              )}
              {correction && (
                <Badge
                  variant={scoreVariant(correction.corrected_score)}
                  className="text-[11px] px-2 gap-1"
                  title={`Original ${correction.original_score ?? '—'} → corrected ${correction.corrected_score}`}
                >
                  <span className="text-[10px] uppercase tracking-wider opacity-80">Corrected</span>
                  <span className="font-mono">{correction.corrected_score}</span>
                </Badge>
              )}
              {data?.confidence && (
                <Badge variant="secondary" className="text-[10px] uppercase tracking-wider">
                  {data.confidence}
                </Badge>
              )}
              {data?.remote_classification && (
                <Badge variant={classificationVariant(data.remote_classification)}>
                  {data.remote_classification.replace(/_/g, ' ')}
                </Badge>
              )}
              {(data?.salary_min_usd || data?.salary_max_usd) && (
                <Badge variant="secondary" className="font-mono">
                  {data.salary_min_usd && data.salary_max_usd
                    ? `$${(data.salary_min_usd / 1000).toFixed(0)}–$${(data.salary_max_usd / 1000).toFixed(0)}K`
                    : data.salary_min_usd
                    ? `$${(data.salary_min_usd / 1000).toFixed(0)}K+`
                    : `≤ $${(data.salary_max_usd! / 1000).toFixed(0)}K`}
                  {data.salary_period ? ` / ${data.salary_period}` : ''}
                </Badge>
              )}
            </div>
          </div>
          <div className="flex gap-2 shrink-0">
            {data?.source_url && (
              <Button variant="secondary" size="sm" asChild>
                <a href={data.source_url} target="_blank" rel="noopener noreferrer">
                  View posting <span className="text-faint">↗</span>
                </a>
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={onClose}
              aria-label="Close job detail panel"
            >
              ✕
            </Button>
          </div>
        </div>

        {/* ── Body ─────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto">
          {isLoading && <div className="py-16 text-center text-muted text-sm">Loading…</div>}
          {isError && (
            <div className="py-16 text-center text-score-low text-sm">
              {(error as Error).message}
            </div>
          )}

          {data && (
            <>
              <Section title="Description">
                <div className="font-sans text-[13px] leading-[1.7] text-fg whitespace-pre-wrap break-words m-0 max-h-[420px] overflow-y-auto bg-bg border border-border rounded-md px-4 py-3.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.02)]">
                  {data.description ?? <span className="text-faint">No description available.</span>}
                </div>
              </Section>

              <Section
                title="Skills Fit"
                badge={
                  data.fit_score != null ? (
                    <Badge variant={scoreVariant(data.fit_score)} className="font-mono">
                      {data.fit_score}
                    </Badge>
                  ) : undefined
                }
              >
                <SkillsFitSection ai={data.ai_fit_detail} />
              </Section>

              <Section
                title="Eval Correction"
                defaultOpen={false}
                badge={
                  correction ? (
                    <Badge variant={scoreVariant(correction.corrected_score)} className="font-mono">
                      {correction.corrected_score}
                    </Badge>
                  ) : undefined
                }
              >
                <EvalCorrectionSection dedupHash={data.dedup_hash} existing={correction} />
              </Section>

              <Section title="Application Tracking" defaultOpen={false}>
                <ApplicationTrackingSection dedupHash={data.dedup_hash} application={application} />
              </Section>

              <Section title="Dev Metadata" defaultOpen={false}>
                <div className="flex flex-col gap-1.5">
                  {[
                    ['Dedup hash', data.dedup_hash],
                    ['Model', data.model],
                    ['Provider', data.provider],
                    ['Profile version', data.profile_version],
                    ['Run ID', data.run_id],
                    ['Scored at', data.scored_at],
                    ['Ingested at', data.ingested_at],
                    ['Source', data.source],
                    ['Source job ID', data.source_job_id],
                  ].map(([label, value]) => (
                    <div key={label} className="flex gap-3 text-[12px] py-1 border-b border-border/40 last:border-b-0">
                      <span className="w-[140px] shrink-0 text-muted">{label}</span>
                      {value ? (
                        <span
                          className="text-fg font-mono break-all cursor-pointer hover:text-primary-hov transition-colors"
                          title="Click to copy"
                          onClick={() => navigator.clipboard?.writeText(String(value))}
                        >
                          {value}
                        </span>
                      ) : (
                        <span className="text-faint font-mono">—</span>
                      )}
                    </div>
                  ))}
                </div>
              </Section>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
