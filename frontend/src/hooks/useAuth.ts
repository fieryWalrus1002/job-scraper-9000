import { useQuery } from '@tanstack/react-query'
import { fetchPrincipal } from '../lib/auth'

export function useAuth() {
  const {
    data: principal,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ['principal'],
    queryFn: fetchPrincipal,
    staleTime: Infinity,
    retry: false,
  })
  return {
    principal: principal ?? null,
    isLoading,
    isError,
    error: error ?? null,
    isAuthenticated: !!principal,
  }
}
