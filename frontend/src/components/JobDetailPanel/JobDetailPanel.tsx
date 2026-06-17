import { useQuery } from '@tanstack/react-query'
import { DialogTitle } from '@/components/ui/dialog'
import { fetchJobDetail } from '../../api'
import { useEvalCorrection } from '../../hooks/useEvalCorrection'
import type { Application, EvalCorrectionOut, JobDetail, JobSummary } from '../../types'
import { JobDetailShell } from './shared/JobDetailShell'
import { JobsDetailSurface } from './surfaces/JobsDetailSurface'
import { ShortlistDetailSurface } from './surfaces/ShortlistDetailSurface'
import { TrackingDetailSurface } from './surfaces/TrackingDetailSurface'
import { TrashDetailSurface } from './surfaces/TrashDetailSurface'
import type { JobDetailSurface } from './types'

interface Props {
  dedupHash: string | null
  onClose: () => void
  application?: Application
  surface?: JobDetailSurface
  /** List-row data already in memory, used as a placeholder so the panel
   * renders instantly instead of flashing "Loading…" during the detail fetch. */
  summary?: JobSummary
}

// The list row (JobSummary) overlaps the detail header fields, so we can render
// those instantly. Detail-only fields (description, dev metadata, skills-fit)
// aren't known yet — fill them with empty defaults until the real fetch lands.
function placeholderFromSummary(s: JobSummary): JobDetail {
  return {
    ...s,
    source_job_id: null,
    description: null,
    scraped_at: null,
    ai_fit_detail: null,
    pipeline_metadata: {},
    run_id: '',
    model: '',
    provider: '',
    profile_version: '',
    metadata: {},
    ingested_at: s.scored_at,
  }
}

export function JobDetailPanel({
  dedupHash,
  onClose,
  application,
  surface = 'jobs',
  summary,
}: Props) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['job', dedupHash],
    queryFn: ({ signal }) => fetchJobDetail(dedupHash!, signal),
    enabled: !!dedupHash,
    placeholderData: summary ? placeholderFromSummary(summary) : undefined,
  })
  const { data: correction } = useEvalCorrection(dedupHash)

  if (!dedupHash) return null

  return (
    <JobDetailShell onClose={onClose}>
      {!data && <DialogTitle className="sr-only">Job detail</DialogTitle>}
      {isLoading && <div className="py-16 text-center text-muted text-sm">Loading…</div>}
      {isError && (
        <div className="py-16 text-center text-score-low text-sm">{(error as Error).message}</div>
      )}
      {data && (
        <DetailSurface
          surface={surface}
          jobData={data}
          correction={correction}
          application={application}
          onClose={onClose}
        />
      )}
    </JobDetailShell>
  )
}

function DetailSurface(props: {
  surface: JobDetailSurface
  jobData: JobDetail
  correction: EvalCorrectionOut | null | undefined
  application: Application | undefined
  onClose: () => void
}) {
  switch (props.surface) {
    case 'jobs':
      return <JobsDetailSurface {...props} />
    case 'shortlist':
      return <ShortlistDetailSurface {...props} />
    case 'tracking':
      return <TrackingDetailSurface {...props} />
    case 'trash':
      return <TrashDetailSurface {...props} />
  }
}
