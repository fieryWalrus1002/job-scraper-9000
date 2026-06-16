import { Badge } from '@/components/ui/badge'
import { ApplicationTrackingSection } from '../shared/ApplicationTrackingSection'
import { DevMetadataSection } from '../shared/DevMetadataSection'
import { EvalCorrectionSection } from '../shared/EvalCorrectionSection'
import { JobDescriptionSection } from '../shared/JobDescriptionSection'
import { Section } from '../shared/Section'
import { SkillsFitSection } from '../shared/SkillsFitSection'
import { scoreVariant } from '../shared/variants'
import type { DetailSurfaceProps } from '../types'

export function SkillsFitPanel({ jobData }: Pick<DetailSurfaceProps, 'jobData'>) {
  return (
    <Section
      title="Skills Fit"
      badge={
        jobData.fit_score != null ? (
          <Badge variant={scoreVariant(jobData.fit_score)} className="font-mono">
            {jobData.fit_score}
          </Badge>
        ) : undefined
      }
    >
      <SkillsFitSection ai={jobData.ai_fit_detail} />
    </Section>
  )
}

export function DescriptionPanel({ jobData }: Pick<DetailSurfaceProps, 'jobData'>) {
  return (
    <Section title="Description">
      <JobDescriptionSection description={jobData.description} />
    </Section>
  )
}

export function EvalCorrectionPanel({
  jobData,
  correction,
}: Pick<DetailSurfaceProps, 'jobData' | 'correction'>) {
  return (
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
      <EvalCorrectionSection dedupHash={jobData.dedup_hash} existing={correction} />
    </Section>
  )
}

export function DevMetadataPanel({ jobData }: Pick<DetailSurfaceProps, 'jobData'>) {
  return (
    <Section title="Dev Metadata" defaultOpen={false}>
      <DevMetadataSection jobData={jobData} />
    </Section>
  )
}

export function ApplicationTrackingPanel({
  jobData,
  application,
  defaultOpen = false,
}: Pick<DetailSurfaceProps, 'jobData' | 'application'> & { defaultOpen?: boolean }) {
  return (
    <Section title="Application Tracking" defaultOpen={defaultOpen}>
      <ApplicationTrackingSection dedupHash={jobData.dedup_hash} application={application} />
    </Section>
  )
}
