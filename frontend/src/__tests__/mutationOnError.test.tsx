import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useMarkApplication } from '../hooks/useApplications'

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

beforeEach(() => vi.restoreAllMocks())
afterEach(() => vi.unstubAllGlobals())

describe('mutation onError wiring', () => {
  it('logs to console.error when a mutation fails', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(new Response('Bad Request', { status: 400, statusText: 'Bad Request' })),
    )

    const { result } = renderHook(() => useMarkApplication(), { wrapper: makeWrapper() })
    await act(async () => {
      result.current.mutate({ dedupHash: 'hash-a', status: 'maybe' })
    })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(errorSpy).toHaveBeenCalledWith('Mutation failed: mark application', expect.any(Error))
  })
})
