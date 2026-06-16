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

export function TrackingDetailSurface({
  jobData,
  correction,
  application,
  onClose,
}: DetailSurfaceProps) {
  const { statusAction } = useApplicationDetailActions(jobData.dedup_hash, application)
  const actions = [
    statusAction({
      id: 'back-to-shortlist',
      label: 'Back to Shortlist',
      status: 'maybe',
      shortcut: 'B',
    }),
    statusAction({ label: 'Trash', status: 'passed', shortcut: 'T', variant: 'danger' }),
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
        <ApplicationTrackingPanel jobData={jobData} application={application} defaultOpen />
        <DescriptionPanel jobData={jobData} />
        <SkillsFitPanel jobData={jobData} />
        <EvalCorrectionPanel jobData={jobData} correction={correction} />
        <DevMetadataPanel jobData={jobData} />
      </JobDetailBody>
    </>
  )
}
