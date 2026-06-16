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

export function TrashDetailSurface({
  jobData,
  correction,
  application,
  onClose,
}: DetailSurfaceProps) {
  const { removeAction, statusAction } = useApplicationDetailActions(
    jobData.dedup_hash,
    application,
  )
  const actions = [
    removeAction({ id: 'restore', label: 'Restore to Jobs', shortcut: 'R' }),
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
        <ApplicationTrackingPanel jobData={jobData} application={application} defaultOpen={false} />
        <EvalCorrectionPanel jobData={jobData} correction={correction} />
        <DevMetadataPanel jobData={jobData} />
      </JobDetailBody>
    </>
  )
}
