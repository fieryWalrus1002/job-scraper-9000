import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import {
  useMarkApplication,
  useUpdateApplication,
  useDeleteApplication,
  useCreateManualJob,
} from '../hooks/useApplications'
import type { Application } from '../types'

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

// Same as makeWrapper but exposes the QueryClient so tests can spy on
// invalidateQueries and assert which caches a mutation touches.
function makeWrapperWithClient() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
  return { qc, wrapper }
}

function invalidatedKeys(spy: ReturnType<typeof vi.spyOn>): string[] {
  return spy.mock.calls.map((call) => (call[0] as { queryKey: string[] }).queryKey[0])
}

beforeEach(() => vi.restoreAllMocks())
afterEach(() => vi.unstubAllGlobals())

const MOCK_APPLICATION: Application = {
  dedup_hash: 'hash-a',
  status: 'maybe',
  applied_at: null,
  notes: null,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
  title: 'Software Engineer',
  company: 'Acme',
}

describe('useMarkApplication', () => {
  it('posts to /api/applications and resolves on success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify(MOCK_APPLICATION), { status: 200 })),
    )

    const { result } = renderHook(() => useMarkApplication(), { wrapper: makeWrapper() })

    await act(async () => {
      await result.current.mutateAsync({ dedupHash: 'hash-a', status: 'maybe' })
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
  })

  it('invalidates applications but not jobs (status-only change)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify(MOCK_APPLICATION), { status: 200 })),
    )
    const { qc, wrapper } = makeWrapperWithClient()
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')

    const { result } = renderHook(() => useMarkApplication(), { wrapper })
    await act(async () => {
      await result.current.mutateAsync({ dedupHash: 'hash-a', status: 'maybe' })
    })

    const keys = invalidatedKeys(invalidateSpy)
    expect(keys).toContain('applications')
    expect(keys).not.toContain('jobs')
  })

  it('enters error state on fetch failure', async () => {
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
  })
})

describe('useUpdateApplication', () => {
  it('patches the application and resolves on success', async () => {
    const updated = { ...MOCK_APPLICATION, status: 'applied' as const, notes: 'Sent resume' }
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify(updated), { status: 200 })),
    )

    const { result } = renderHook(() => useUpdateApplication(), { wrapper: makeWrapper() })

    await act(async () => {
      await result.current.mutateAsync({
        dedupHash: 'hash-a',
        update: { status: 'applied', notes: 'Sent resume' },
      })
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
  })
})

describe('useDeleteApplication', () => {
  it('deletes the application and resolves on success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))

    const { result } = renderHook(() => useDeleteApplication(), { wrapper: makeWrapper() })

    await act(async () => {
      await result.current.mutateAsync('hash-a')
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
  })

  it('enters error state on fetch failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(new Response('Not Found', { status: 404, statusText: 'Not Found' })),
    )

    const { result } = renderHook(() => useDeleteApplication(), { wrapper: makeWrapper() })

    await act(async () => {
      result.current.mutate('hash-missing')
    })

    await waitFor(() => expect(result.current.isError).toBe(true))
  })
})

describe('useCreateManualJob', () => {
  it('posts to /api/jobs and resolves on success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify(MOCK_APPLICATION), { status: 200 })),
    )

    const { result } = renderHook(() => useCreateManualJob(), { wrapper: makeWrapper() })

    await act(async () => {
      await result.current.mutateAsync({
        title: 'Software Engineer',
        fit_score: 4,
        company: 'Acme',
        status: 'maybe',
      })
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
  })

  it('invalidates both applications and jobs (adds a job)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify(MOCK_APPLICATION), { status: 200 })),
    )
    const { qc, wrapper } = makeWrapperWithClient()
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')

    const { result } = renderHook(() => useCreateManualJob(), { wrapper })
    await act(async () => {
      await result.current.mutateAsync({
        title: 'Software Engineer',
        fit_score: 4,
        company: 'Acme',
        status: 'maybe',
      })
    })

    const keys = invalidatedKeys(invalidateSpy)
    expect(keys).toContain('applications')
    expect(keys).toContain('jobs')
  })

  it('throws a specific error message on 409 conflict', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('Conflict', { status: 409, statusText: 'Conflict' })),
    )

    const { result } = renderHook(() => useCreateManualJob(), { wrapper: makeWrapper() })

    await act(async () => {
      result.current.mutate({ title: 'Duplicate Job', fit_score: 3, status: 'maybe' })
    })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect((result.current.error as Error).message).toBe('409: Job already exists')
  })
})
