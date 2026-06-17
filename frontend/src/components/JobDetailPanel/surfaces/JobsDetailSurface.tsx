import { JobDetailBody } from '../shared/JobDetailShell'
import { JobSummaryHeader } from '../shared/JobSummaryHeader'
import type { DetailSurfaceProps } from '../types'
import { useApplicationDetailActions } from './actionHelpers'
import {
  ApplicationTrackingPanel,
  DescriptionPanel,
  DevMetadataPanel,
  EvalCorrectionPanel,
  SkillsFitPanel,
} from './commonSections'

export function JobsDetailSurface({
  jobData,
  correction,
  application,
  onClose,
}: DetailSurfaceProps) {
  const { statusAction } = useApplicationDetailActions(jobData.dedup_hash, application, onClose)
  const actions = [
    statusAction({ label: 'Trash', status: 'passed', shortcut: 'T', variant: 'danger' }),
    statusAction({ label: 'Shortlist', status: 'maybe', shortcut: 'S', variant: 'warn' }),
  ]

  return (
    <>
      <JobSummaryHeader
        jobData={jobData}
        correction={correction}
        actions={actions}
        onClose={onClose}
      />
      <JobDetailBody>
        <DescriptionPanel jobData={jobData} />
        <SkillsFitPanel jobData={jobData} />
        <EvalCorrectionPanel jobData={jobData} correction={correction} />
        <DevMetadataPanel jobData={jobData} />
        <ApplicationTrackingPanel jobData={jobData} application={application} defaultOpen={false} />
      </JobDetailBody>
    </>
  )
}
