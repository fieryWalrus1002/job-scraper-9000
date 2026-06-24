import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ApplicationTrackingSection } from '../shared/ApplicationTrackingSection'
import { AddNoteForm } from '../shared/AddNoteForm'
import { DevMetadataSection } from '../shared/DevMetadataSection'
import { EvalCorrectionSection } from '../shared/EvalCorrectionSection'
import { JobDescriptionSection } from '../shared/JobDescriptionSection'
import { Section } from '../shared/Section'
import { SkillsFitSection } from '../shared/SkillsFitSection'
import { scoreVariant } from '../shared/variants'
import { useApplicationEvents, useDeleteEvent, useUpdateEvent } from '@/hooks/useApplications'
import { readStatusTransition, STATUS_LABELS } from '@/types'
import type { ApplicationEvent, ApplicationEventUpdate } from '@/types'
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
      <span className="text-faint font-mono whitespace-nowrap shrink-0">
        {formatDate(event.occurred_at)}
      </span>
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-faint">⚙</span>
        <span className="text-muted italic">{label}</span>
      </div>
    </div>
  )
}

function EventRow({
  event,
  dedupHash,
  onRefresh,
}: {
  event: ApplicationEvent
  dedupHash: string
  onRefresh: () => void
}) {
  const [isEditing, setIsEditing] = useState(false)
  const [editBody, setEditBody] = useState(event.body ?? '')
  const deleteMutation = useDeleteEvent()
  const updateMutation = useUpdateEvent()

  const textareaCls =
    'w-full min-h-[50px] resize-y bg-bg-elevated border border-border rounded-md text-fg text-[12px] leading-[1.55] px-2 py-1.5 outline-none ' +
    'placeholder:text-faint hover:border-border-strong ' +
    'focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/25 ' +
    'transition-[color,border-color,box-shadow]'

  async function handleDelete() {
    await deleteMutation.mutateAsync({ dedupHash, eventId: event.id })
    onRefresh()
  }

  async function handleSave() {
    const update: ApplicationEventUpdate = {
      body: editBody.trim() || null,
    }
    await updateMutation.mutateAsync({ dedupHash, eventId: event.id, update })
    setIsEditing(false)
    onRefresh()
  }

  if (isEditing) {
    return (
      <div className="flex flex-col gap-2 text-[12px]">
        <textarea
          className={textareaCls}
          value={editBody}
          onChange={(e) => setEditBody(e.target.value)}
          placeholder="Edit note…"
        />
        <div className="flex gap-2 pl-7">
          <Button
            size="sm"
            variant="secondary"
            className="text-[11px] h-6 px-2"
            onClick={handleSave}
            disabled={updateMutation.isPending}
          >
            {updateMutation.isPending ? 'Saving…' : 'Save'}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-[11px] h-6 px-2"
            onClick={() => setIsEditing(false)}
          >
            Cancel
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1.5 text-[12px]">
      <div className="flex items-center gap-2">
        <span className="text-faint font-mono whitespace-nowrap shrink-0">
          {formatDate(event.occurred_at)}
        </span>
        <div className="flex gap-1 ml-auto">
          <Button
            size="sm"
            variant="ghost"
            className="text-[10px] h-5 px-1.5 text-muted hover:text-fg"
            onClick={() => setIsEditing(true)}
          >
            edit
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-[10px] h-5 px-1.5 text-muted hover:text-score-low"
            onClick={handleDelete}
            disabled={deleteMutation.isPending}
          >
            del
          </Button>
        </div>
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
  const { data: events, isLoading, isError, refetch } = useApplicationEvents(jobData.dedup_hash)
  const [showAddForm, setShowAddForm] = useState(false)

  function handleRefresh() {
    void refetch()
  }

  return (
    <Section title="Activity Timeline" defaultOpen={false}>
      {isLoading && <div className="text-faint text-[12px] py-2">Loading…</div>}
      {isError && <div className="text-score-low text-[12px] py-2">Could not load activity</div>}
      {!isLoading && !isError && events && (
        <div className="flex flex-col gap-4">
          {events.length === 0 && (
            <div className="text-faint text-[12px] py-2 italic">
              No activity yet. Status changes and notes will appear here.
            </div>
          )}

          {events.map((event) =>
            event.kind === 'status_change' ? (
              <StatusChangeRow key={event.id} event={event} />
            ) : (
              <EventRow
                key={event.id}
                event={event}
                dedupHash={jobData.dedup_hash}
                onRefresh={handleRefresh}
              />
            ),
          )}

          {showAddForm ? (
            <div className="flex flex-col gap-3 pt-3 border-t border-border">
              <AddNoteForm
                dedupHash={jobData.dedup_hash}
                onSuccess={() => {
                  setShowAddForm(false)
                  handleRefresh()
                }}
              />
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="text-[11px] self-start text-muted"
                onClick={() => setShowAddForm(false)}
              >
                Cancel
              </Button>
            </div>
          ) : (
            <Button
              type="button"
              variant="secondary"
              size="sm"
              className="text-[12px] self-start"
              onClick={() => setShowAddForm(true)}
            >
              + Add note
            </Button>
          )}
        </div>
      )}
    </Section>
  )
}
