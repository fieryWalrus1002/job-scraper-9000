import { DialogTitle } from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import type { EvalCorrectionOut, JobDetail } from '../../../types'
import { DetailActionBar, type DetailAction } from './DetailActionBar'
import { JobDetailCloseButton, JobDetailVisitButton } from './JobDetailShell'
import { classificationVariant, scoreVariant } from './variants'

export function JobSummaryHeader({
  jobData,
  correction,
  actions,
  onClose,
}: {
  jobData: JobDetail
  correction: EvalCorrectionOut | null | undefined
  actions: DetailAction[]
  onClose: () => void
}) {
  return (
    <div className="flex flex-wrap items-start gap-4 px-7 pt-5 pb-4 border-b border-border shrink-0 bg-gradient-to-b from-card to-card/70">
      <div className="flex-1 min-w-0">
        <DialogTitle asChild>
          <h2 className="text-[18px] font-semibold text-fg m-0 mb-1.5 leading-[1.3] tracking-tight">
            {jobData.title ?? '—'}
          </h2>
        </DialogTitle>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-fg mb-2.5">
          <span className="font-medium">{jobData.company ?? '—'}</span>
          {jobData.location && (
            <>
              <span className="text-faint">·</span>
              <span className="text-muted">{jobData.location}</span>
            </>
          )}
          {jobData.posted_at && (
            <>
              <span className="text-faint">·</span>
              <span className="text-muted font-mono text-[12px]">{jobData.posted_at}</span>
            </>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {jobData.fit_score != null && (
            <Badge variant={scoreVariant(jobData.fit_score)} className="text-[11px] px-2">
              Score <span className="font-mono ml-0.5">{jobData.fit_score}</span>
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
          {jobData.confidence && (
            <Badge variant="secondary" className="text-[10px] uppercase tracking-wider">
              {jobData.confidence}
            </Badge>
          )}
          {jobData.remote_classification && (
            <Badge variant={classificationVariant(jobData.remote_classification)}>
              {jobData.remote_classification.replace(/_/g, ' ')}
            </Badge>
          )}
          {(jobData.salary_min_usd || jobData.salary_max_usd) && (
            <Badge variant="secondary" className="font-mono">
              {jobData.salary_min_usd && jobData.salary_max_usd
                ? `$${(jobData.salary_min_usd / 1000).toFixed(0)}–$${(jobData.salary_max_usd / 1000).toFixed(0)}K`
                : jobData.salary_min_usd
                  ? `$${(jobData.salary_min_usd / 1000).toFixed(0)}K+`
                  : `≤ $${(jobData.salary_max_usd! / 1000).toFixed(0)}K`}
              {jobData.salary_period ? ` / ${jobData.salary_period}` : ''}
            </Badge>
          )}

          <div className="basis-full pt-3 mt-1 border-t border-border/50">
            <DetailActionBar actions={actions} />
          </div>
        </div>
      </div>

      <div className="flex gap-2 shrink-0">
        <JobDetailVisitButton url={jobData.source_url} />
        <JobDetailCloseButton onClose={onClose} />
      </div>
    </div>
  )
}
