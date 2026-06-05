import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useAuth } from '../hooks/useAuth'
import * as auth from '../lib/auth'

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('useAuth', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('starts in loading state', () => {
    vi.spyOn(auth, 'fetchPrincipal').mockReturnValue(new Promise(() => {}))
    const { result } = renderHook(() => useAuth(), { wrapper })
    expect(result.current.isLoading).toBe(true)
    expect(result.current.principal).toBeNull()
    expect(result.current.isAuthenticated).toBe(false)
  })

  it('returns principal and isAuthenticated=true when authenticated', async () => {
    const principal = { userId: 'u1', userDetails: 'test@example.com', userRoles: ['authenticated'] }
    vi.spyOn(auth, 'fetchPrincipal').mockResolvedValue(principal)

    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.principal).toEqual(principal)
    expect(result.current.isAuthenticated).toBe(true)
  })

  it('returns principal=null and isAuthenticated=false when unauthenticated', async () => {
    vi.spyOn(auth, 'fetchPrincipal').mockResolvedValue(null)

    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.principal).toBeNull()
    expect(result.current.isAuthenticated).toBe(false)
  })
})
