import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useJobs } from '../hooks/useJobs'
import { EMPTY_FILTERS } from '../lib/filters'
import type { Filters, JobListResponse } from '../types'

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

const MOCK_RESPONSE: JobListResponse = {
  total: 120,
  limit: 50,
  offset: 0,
  items: [
    {
      dedup_hash: 'hash-1',
      source: 'linkedin',
      source_url: null,
      title: 'Software Engineer',
      company: 'Acme',
      location: 'Remote',
      posted_at: '2024-01-01',
      remote_classification: 'fully_remote',
      salary_min_usd: null,
      salary_max_usd: null,
      salary_period: null,
      fit_score: 4,
      confidence: null,
      score_rationale: null,
      failure_reason: null,
      scored_at: '2024-01-02T00:00:00Z',
    },
    {
      dedup_hash: 'hash-2',
      source: 'indeed',
      source_url: null,
      title: 'Backend Engineer',
      company: 'Widget Co',
      location: 'Seattle, WA',
      posted_at: '2024-02-01',
      remote_classification: 'hybrid',
      salary_min_usd: 120000,
      salary_max_usd: 160000,
      salary_period: null,
      fit_score: 3,
      confidence: null,
      score_rationale: null,
      failure_reason: null,
      scored_at: '2024-02-02T00:00:00Z',
    },
  ],
}

describe('useJobs', () => {
  beforeEach(() => vi.restoreAllMocks())
  afterEach(() => vi.unstubAllGlobals())

  it('starts in loading state', () => {
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise(() => {})))
    const { result } = renderHook(() => useJobs(EMPTY_FILTERS, 0), { wrapper })
    expect(result.current.isLoading).toBe(true)
    expect(result.current.data).toBeUndefined()
  })

  it('returns job list on success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify(MOCK_RESPONSE), { status: 200 })),
    )

    const { result } = renderHook(() => useJobs(EMPTY_FILTERS, 0), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.total).toBe(120)
    expect(result.current.data?.items).toHaveLength(2)
    expect(result.current.data?.items[0].dedup_hash).toBe('hash-1')
  })

  it('includes active filters in the fetch URL', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ ...MOCK_RESPONSE, total: 0, items: [] }), { status: 200 }),
      )
    vi.stubGlobal('fetch', fetchMock)

    const filters: Filters = { ...EMPTY_FILTERS, minScore: '3', company: 'Acme' }
    const { result } = renderHook(() => useJobs(filters, 0), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const url = fetchMock.mock.calls[0][0] as string
    expect(url).toContain('min_score=3')
    expect(url).toContain('company=Acme')
  })

  it('includes pagination params in the fetch URL', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ ...MOCK_RESPONSE, offset: 100 }), { status: 200 }),
      )
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useJobs(EMPTY_FILTERS, 2), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const url = fetchMock.mock.calls[0][0] as string
    expect(url).toContain('limit=50')
    expect(url).toContain('offset=100')
  })

  it('enters error state on fetch failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('Internal Server Error', {
          status: 500,
          statusText: 'Internal Server Error',
        }),
      ),
    )

    const { result } = renderHook(() => useJobs(EMPTY_FILTERS, 0), { wrapper })

    // useJobs sets retry: 1, which overrides the wrapper's retry: false and adds
    // a ~1s backoff before the error surfaces — extend the wait accordingly.
    await waitFor(() => expect(result.current.isError).toBe(true), { timeout: 3000 })
    expect(result.current.data).toBeUndefined()
  })
})
