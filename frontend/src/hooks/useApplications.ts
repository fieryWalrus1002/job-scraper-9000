import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import {
  createApplication,
  createEvent,
  createManualJob,
  deleteApplication,
  deleteEvent,
  fetchApplicationEvents,
  fetchApplications,
  normalizeApplicationStatuses,
  updateApplication,
  updateEvent,
} from '../api'
import type {
  Application,
  ApplicationEvent,
  ApplicationEventCreate,
  ApplicationEventUpdate,
  ApplicationStatus,
  ApplicationUpdate,
  ManualJobCreate,
} from '../types'
import { logMutationError } from '../lib/mutations'

export function useApplications(statuses?: ApplicationStatus[]) {
  const normalizedStatuses = normalizeApplicationStatuses(statuses)
  return useQuery<Application[], Error, Map<string, Application>>({
    queryKey: ['applications', normalizedStatuses.length > 0 ? normalizedStatuses : 'all'],
    queryFn: ({ signal }) => fetchApplications(normalizedStatuses, signal),
    select: (data: Application[]) => new Map(data.map((a) => [a.dedup_hash, a])),
  })
}

export function useApplicationEvents(dedupHash: string) {
  return useQuery<ApplicationEvent[], Error>({
    queryKey: ['application-events', dedupHash],
    queryFn: ({ signal }) => fetchApplicationEvents(dedupHash, signal),
  })
}

export function useMarkApplication() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      dedupHash,
      status,
      notes,
    }: {
      dedupHash: string
      status: ApplicationStatus
      notes?: string
    }) => createApplication({ dedup_hash: dedupHash, status, notes }),
    onSuccess: (_, variables) => {
      invalidateApplications(qc)
      // A status change auto-emits a status_change event (#381) — refresh the timeline.
      invalidateEvents(qc, variables.dedupHash)
    },
    onError: logMutationError('mark application'),
  })
}

export function useUpdateApplication() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ dedupHash, update }: { dedupHash: string; update: ApplicationUpdate }) =>
      updateApplication(dedupHash, update),
    onSuccess: (_, variables) => {
      invalidateApplications(qc)
      // A status change auto-emits a status_change event (#381) — refresh the timeline.
      invalidateEvents(qc, variables.dedupHash)
    },
    onError: logMutationError('update application'),
  })
}

export function useDeleteApplication() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (dedupHash: string) => deleteApplication(dedupHash),
    onSuccess: () => invalidateApplications(qc),
    onError: logMutationError('delete application'),
  })
}

export function useCreateManualJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ManualJobCreate) => createManualJob(body),
    onSuccess: () => invalidateApplicationsAndJobs(qc),
    onError: logMutationError('create manual job'),
  })
}

export function useCreateEvent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ dedupHash, body }: { dedupHash: string; body: ApplicationEventCreate }) =>
      createEvent(dedupHash, body),
    onSuccess: (_, variables) => invalidateEvents(qc, variables.dedupHash),
    onError: logMutationError('create event'),
  })
}

export function useUpdateEvent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      dedupHash,
      eventId,
      update,
    }: {
      dedupHash: string
      eventId: string
      update: ApplicationEventUpdate
    }) => updateEvent(dedupHash, eventId, update),
    onSuccess: (_, variables) => invalidateEvents(qc, variables.dedupHash),
    onError: logMutationError('update event'),
  })
}

export function useDeleteEvent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ dedupHash, eventId }: { dedupHash: string; eventId: string }) =>
      deleteEvent(dedupHash, eventId),
    onSuccess: (_, variables) => invalidateEvents(qc, variables.dedupHash),
    onError: logMutationError('delete event'),
  })
}

// Status mark/update/delete only change application state, not the job list, so
// invalidating ['jobs'] would trigger a pointless refetch (and a loading flash)
// of the current page on every triage action.
function invalidateApplications(qc: QueryClient) {
  void qc.invalidateQueries({ queryKey: ['applications'], exact: false })
}

// Adding a manual job genuinely changes the job list, so refresh both.
function invalidateApplicationsAndJobs(qc: QueryClient) {
  void qc.invalidateQueries({ queryKey: ['applications'], exact: false })
  void qc.invalidateQueries({ queryKey: ['jobs'], exact: false })
}

function invalidateEvents(qc: QueryClient, dedupHash: string) {
  void qc.invalidateQueries({ queryKey: ['application-events', dedupHash] })
}
