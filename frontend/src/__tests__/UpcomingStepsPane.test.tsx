import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { UpcomingStepsPane } from '../components/UpcomingStepsPane'

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

const MOCK_RESPONSE_ALERTS = {
  alerts: [
    {
      kind: 'stale_to_apply' as const,
      message: "2 job(s) have been in 'to apply' for 5 day(s) without moving forward.",
      count: 2,
      dedup_hashes: ['dh-1', 'dh-2'],
      days: 5,
    },
  ],
}

const MOCK_RESPONSE_MULTI = {
  alerts: [
    {
      kind: 'stale_to_apply' as const,
      message: "1 job(s) have been in 'to apply' for 4 day(s) without moving forward.",
      count: 1,
      dedup_hashes: ['dh-1'],
      days: 4,
    },
    {
      kind: 'post_interview' as const,
      message: "1 job(s) haven't progressed past interview for 10 day(s).",
      count: 1,
      dedup_hashes: ['dh-3'],
      days: 10,
    },
    {
      kind: 'inactivity' as const,
      message: 'No applications submitted in the last 20 days.',
      days: 20,
    },
  ],
}

describe('UpcomingStepsPane', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => vi.unstubAllGlobals())

  it('renders alert messages when alerts are present', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(new Response(JSON.stringify(MOCK_RESPONSE_ALERTS), { status: 200 })),
    )

    render(<UpcomingStepsPane />, { wrapper: makeWrapper() })

    await waitFor(() => {
      expect(screen.getByText(/Upcoming Steps/)).toBeInTheDocument()
    })

    expect(screen.getByText(/job\(s\) have been in 'to apply'/)).toBeInTheDocument()
  })

  it('renders multiple alert kinds with their labels', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify(MOCK_RESPONSE_MULTI), { status: 200 })),
    )

    render(<UpcomingStepsPane />, { wrapper: makeWrapper() })

    await waitFor(() => {
      expect(screen.getByText(/Upcoming Steps/)).toBeInTheDocument()
    })

    // All three alert kinds render
    expect(screen.getByText('Stale to-apply')).toBeInTheDocument()
    expect(screen.getByText('Post-interview')).toBeInTheDocument()
    expect(screen.getByText('Inactivity')).toBeInTheDocument()

    // Messages render
    expect(screen.getByText(/job\(s\) have been in 'to apply'/)).toBeInTheDocument()
    expect(screen.getByText(/haven't progressed past interview/)).toBeInTheDocument()
    expect(screen.getByText(/No applications submitted/)).toBeInTheDocument()
  })

  it('is hidden when there are no alerts', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ alerts: [] }), { status: 200 })),
    )

    render(<UpcomingStepsPane />, { wrapper: makeWrapper() })

    await waitFor(() => {
      // The pane renders nothing (returns null) when alerts is empty
      expect(screen.queryByText(/Upcoming Steps/)).not.toBeInTheDocument()
    })
  })

  it('does not crash when the fetch errors', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response('Server Error', { status: 500, statusText: 'Internal Server Error' }),
        ),
    )

    render(<UpcomingStepsPane />, { wrapper: makeWrapper() })

    // Pane degrades quietly — no error text, no crash
    await waitFor(() => {
      expect(screen.queryByText(/Upcoming Steps/)).not.toBeInTheDocument()
    })
    expect(screen.queryByText(/error/i)).not.toBeInTheDocument()
  })
})
