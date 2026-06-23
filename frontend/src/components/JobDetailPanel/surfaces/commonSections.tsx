import { Badge } from '@/components/ui/badge'
import { ApplicationTrackingSection } from '../shared/ApplicationTrackingSection'
import { DevMetadataSection } from '../shared/DevMetadataSection'
import { EvalCorrectionSection } from '../shared/EvalCorrectionSection'
import { JobDescriptionSection } from '../shared/JobDescriptionSection'
import { Section } from '../shared/Section'
import { SkillsFitSection } from '../shared/SkillsFitSection'
import { scoreVariant } from '../shared/variants'
import { useApplicationEvents } from '@/hooks/useApplications'
import { readStatusTransition, STATUS_LABELS } from '@/types'
import type { ApplicationEvent } from '@/types'
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

// ---------------------------------------------------------------------------
// Activity Timeline
// ---------------------------------------------------------------------------

function formatDate(iso: string): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(iso))
  } catch {
    return iso
  }
}

function StatusChangeRow({ event }: { event: ApplicationEvent }) {
  const { from, to } = readStatusTransition(event)
  const toLabel = STATUS_LABELS[to as keyof typeof STATUS_LABELS] ?? to
  const fromLabel = from ? (STATUS_LABELS[from as keyof typeof STATUS_LABELS] ?? from) : null
  const label = fromLabel ? `Moved from ${fromLabel} → ${toLabel}` : `Entered ${toLabel}`

  return (
    <div className="flex items-start gap-3 text-[12px]">
      <span className="text-faint font-mono whitespace-nowrap shrink-0 w-36">
        {formatDate(event.occurred_at)}
      </span>
      <div className="flex items-center gap-2">
        <span className="text-faint">⚙</span>
        <span className="text-muted italic">{label}</span>
      </div>
    </div>
  )
}

function EventRow({ event }: { event: ApplicationEvent }) {
  return (
    <div className="flex flex-col gap-1.5 text-[12px]">
      <div className="flex items-center gap-2">
        <span className="text-faint font-mono whitespace-nowrap shrink-0">
          {formatDate(event.occurred_at)}
        </span>
      </div>
      {event.body && <div className="text-fg pl-7">{event.body}</div>}
      {event.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 pl-7">
          {event.tags.map((tag) => (
            <Badge key={tag} variant="secondary" className="text-[10px]">
              {tag}
            </Badge>
          ))}
        </div>
      )}
    </div>
  )
}

export function ActivityTimelinePanel({ jobData }: Pick<DetailSurfaceProps, 'jobData'>) {
  const { data: events, isLoading, isError } = useApplicationEvents(jobData.dedup_hash)

  return (
    <Section title="Activity Timeline" defaultOpen={false}>
      {isLoading && <div className="text-faint text-[12px] py-2">Loading…</div>}
      {isError && <div className="text-score-low text-[12px] py-2">Could not load activity</div>}
      {!isLoading && !isError && events && events.length === 0 && (
        <div className="text-faint text-[12px] py-2 italic">
          No activity yet. Status changes and notes will appear here.
        </div>
      )}
      {!isLoading && !isError && events && events.length > 0 && (
        <div className="flex flex-col gap-4">
          {events.map((event) =>
            event.kind === 'status_change' ? (
              <StatusChangeRow key={event.id} event={event} />
            ) : (
              <EventRow key={event.id} event={event} />
            ),
          )}
        </div>
      )}
    </Section>
  )
}
