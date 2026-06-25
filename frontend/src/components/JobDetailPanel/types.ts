import type { Application, EvalCorrectionOut, JobDetail } from '../../types'

export type JobDetailSurface = 'jobs' | 'shortlist' | 'tracking' | 'trash' | 'grabbag'

export interface DetailSurfaceProps {
  jobData: JobDetail
  correction: EvalCorrectionOut | null | undefined
  application: Application | undefined
  onClose: () => void
}
