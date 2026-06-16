import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import {
  createApplication,
  createManualJob,
  deleteApplication,
  fetchApplications,
  normalizeApplicationStatuses,
  updateApplication,
} from '../api'
import type { Application, ApplicationStatus, ApplicationUpdate, ManualJobCreate } from '../types'

export function useApplications(statuses?: ApplicationStatus[]) {
  const normalizedStatuses = normalizeApplicationStatuses(statuses)
  return useQuery<Application[], Error, Map<string, Application>>({
    queryKey: ['applications', normalizedStatuses.length > 0 ? normalizedStatuses : 'all'],
    queryFn: () => fetchApplications(normalizedStatuses),
    select: (data: Application[]) => new Map(data.map((a) => [a.dedup_hash, a])),
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
    onSuccess: () => invalidateJobApplicationQueries(qc),
  })
}

export function useUpdateApplication() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ dedupHash, update }: { dedupHash: string; update: ApplicationUpdate }) =>
      updateApplication(dedupHash, update),
    onSuccess: () => invalidateJobApplicationQueries(qc),
  })
}

export function useDeleteApplication() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (dedupHash: string) => deleteApplication(dedupHash),
    onSuccess: () => invalidateJobApplicationQueries(qc),
  })
}

export function useCreateManualJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ManualJobCreate) => createManualJob(body),
    onSuccess: () => invalidateJobApplicationQueries(qc),
  })
}

function invalidateJobApplicationQueries(qc: QueryClient) {
  void qc.invalidateQueries({ queryKey: ['applications'], exact: false })
  void qc.invalidateQueries({ queryKey: ['jobs'], exact: false })
}
