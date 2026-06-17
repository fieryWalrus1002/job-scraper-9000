import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { deleteEvalCorrection, fetchEvalCorrection, upsertEvalCorrection } from '../api'
import type { EvalCorrectionIn, EvalCorrectionOut } from '../types'
import { logMutationError } from '../lib/mutations'

export function useEvalCorrection(dedupHash: string | null) {
  return useQuery<EvalCorrectionOut | null, Error>({
    queryKey: ['eval-correction', dedupHash],
    queryFn: ({ signal }) => fetchEvalCorrection(dedupHash!, signal),
    enabled: !!dedupHash,
  })
}

export function useSetEvalCorrection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: EvalCorrectionIn) => upsertEvalCorrection(body),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['eval-correction', data.dedup_hash] })
    },
    onError: logMutationError('save eval correction'),
  })
}

export function useDeleteEvalCorrection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (dedupHash: string) => deleteEvalCorrection(dedupHash),
    onSuccess: (_data, dedupHash) => {
      qc.invalidateQueries({ queryKey: ['eval-correction', dedupHash] })
    },
    onError: logMutationError('delete eval correction'),
  })
}
