import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { fetchSettings, saveProfile, saveSearch } from '../api'
import type { CandidateProfileInput, SearchConfigInput, SettingsResponse } from '../types'

export function useSettings() {
  return useQuery<SettingsResponse, Error>({
    queryKey: ['settings'],
    queryFn: ({ signal }) => fetchSettings(signal),
  })
}

export function useSaveProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CandidateProfileInput) => saveProfile(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }),
  })
}

export function useSaveSearch() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: SearchConfigInput) => saveSearch(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }),
  })
}
