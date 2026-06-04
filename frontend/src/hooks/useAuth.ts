import { useQuery } from '@tanstack/react-query'
import { fetchPrincipal } from '../lib/auth'

export function useAuth() {
  const { data: principal, isLoading } = useQuery({
    queryKey: ['principal'],
    queryFn: fetchPrincipal,
    staleTime: Infinity,
    retry: false,
  })
  return {
    principal: principal ?? null,
    isLoading,
    isAuthenticated: !!principal,
  }
}
