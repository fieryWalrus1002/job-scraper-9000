import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useApplications } from '../hooks/useApplications'
import type { Application } from '../types'

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

const MOCK_APPLICATIONS: Application[] = [
  {
    dedup_hash: 'hash-a',
    status: 'saved',
    applied_at: null,
    notes: null,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    title: 'Software Engineer',
    company: 'Acme',
  },
  {
    dedup_hash: 'hash-b',
    status: 'applied',
    applied_at: '2024-02-01T00:00:00Z',
    notes: 'Strong fit',
    created_at: '2024-02-01T00:00:00Z',
    updated_at: '2024-02-01T00:00:00Z',
    title: 'Backend Engineer',
    company: 'Widget Co',
  },
]

describe('useApplications', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('returns a Map keyed by dedup_hash on success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(MOCK_APPLICATIONS), { status: 200 }),
      ),
    )

    const { result } = renderHook(() => useApplications(), { wrapper })

    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.isSuccess).toBe(true)

    const map = result.current.data!
    expect(map).toBeInstanceOf(Map)
    expect(map.size).toBe(2)
    expect(map.get('hash-a')?.company).toBe('Acme')
    expect(map.get('hash-b')?.status).toBe('applied')
  })

  it('enters error state on fetch failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('Internal Server Error', { status: 500, statusText: 'Internal Server Error' })),
    )

    const { result } = renderHook(() => useApplications(), { wrapper })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.data).toBeUndefined()
  })
})
