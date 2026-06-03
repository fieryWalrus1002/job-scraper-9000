import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createApplication, createManualJob, deleteApplication, fetchApplications, updateApplication } from '../api'
import type { Application, ApplicationStatus, ApplicationUpdate, ManualJobCreate } from '../types'

export function useApplications() {
  return useQuery<Application[], Error, Map<string, Application>>({
    queryKey: ['applications'],
    queryFn: fetchApplications,
    select: (data: Application[]) => new Map(data.map((a) => [a.dedup_hash, a])),
  })
}

export function useMarkApplication() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ dedupHash, status, notes }: { dedupHash: string; status: ApplicationStatus; notes?: string }) =>
      createApplication({ dedup_hash: dedupHash, status, notes }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['applications'] }),
  })
}

export function useUpdateApplication() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ dedupHash, update }: { dedupHash: string; update: ApplicationUpdate }) =>
      updateApplication(dedupHash, update),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['applications'] }),
  })
}

export function useDeleteApplication() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (dedupHash: string) => deleteApplication(dedupHash),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['applications'] }),
  })
}

export function useCreateManualJob() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ManualJobCreate) => createManualJob(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['applications'] }),
  })
}
