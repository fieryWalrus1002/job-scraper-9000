import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchSettings, saveProfile } from '../api'
import type { CandidateProfileInput, SettingsResponse } from '../types'

export function useSettings() {
  return useQuery<SettingsResponse, Error>({
    queryKey: ['settings'],
    queryFn: fetchSettings,
  })
}

export function useSaveProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CandidateProfileInput) => saveProfile(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }),
  })
}
