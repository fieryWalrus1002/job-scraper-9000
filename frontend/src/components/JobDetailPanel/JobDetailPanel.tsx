import { useQuery } from '@tanstack/react-query'
import { DialogTitle } from '@/components/ui/dialog'
import { fetchJobDetail } from '../../api'
import { useEvalCorrection } from '../../hooks/useEvalCorrection'
import type { Application, EvalCorrectionOut, JobDetail } from '../../types'
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
}

export function JobDetailPanel({ dedupHash, onClose, application, surface = 'jobs' }: Props) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['job', dedupHash],
    queryFn: () => fetchJobDetail(dedupHash!),
    enabled: !!dedupHash,
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
