import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createApplication, deleteApplication, fetchApplications, updateApplication } from '../api'
import type { Application, ApplicationStatus, ApplicationUpdate } from '../types'

export function useApplications() {
  return useQuery({
    queryKey: ['applications'],
    queryFn: fetchApplications,
    select: (data): Map<string, Application> =>
      new Map(data.map((a) => [a.dedup_hash, a])),
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
