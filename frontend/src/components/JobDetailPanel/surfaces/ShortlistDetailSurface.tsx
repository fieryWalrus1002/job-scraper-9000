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

export function ShortlistDetailSurface({
  jobData,
  correction,
  application,
  onClose,
}: DetailSurfaceProps) {
  const { removeAction, statusAction } = useApplicationDetailActions(
    jobData.dedup_hash,
    application,
    onClose,
  )
  const actions = [
    statusAction({ label: 'Trash', status: 'passed', shortcut: 'T', variant: 'danger' }),
    removeAction({ id: 'back-to-jobs', label: 'Back to Jobs', shortcut: 'B' }),
    statusAction({
      id: 'pursue',
      label: 'Pursue',
      status: 'to_apply',
      shortcut: 'P',
      variant: 'success',
    }),
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
        <SkillsFitPanel jobData={jobData} />
        <DescriptionPanel jobData={jobData} />
        <ApplicationTrackingPanel jobData={jobData} application={application} defaultOpen={false} />
        <EvalCorrectionPanel jobData={jobData} correction={correction} />
        <DevMetadataPanel jobData={jobData} />
      </JobDetailBody>
    </>
  )
}
