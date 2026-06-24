import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { TrackingBoard } from '../components/TrackingBoard'
import type { Application, ApplicationStatus } from '../types'

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

function app(dedup_hash: string, status: ApplicationStatus, title: string): Application {
  return {
    dedup_hash,
    status,
    applied_at: null,
    notes: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    title,
    company: 'Acme',
  }
}

const APPS = [
  app('h-queue', 'to_apply', 'Queue Role'),
  app('h-active', 'applied', 'Active Role'),
  app('h-closed', 'rejected', 'Closed Role'),
]

// The board now always mounts <UpcomingStepsPane />, so two queries hit fetch:
// the applications list and GET /api/upcoming-steps. Route by URL and return a
// fresh Response per call (a Response body can only be read once).
function stubFetch(apps: Application[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString()
      if (url.includes('/upcoming-steps')) {
        return new Response(JSON.stringify({ alerts: [] }), { status: 200 })
      }
      return new Response(JSON.stringify(apps), { status: 200 })
    }),
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
  stubFetch(APPS)
})
afterEach(() => vi.unstubAllGlobals())

describe('TrackingBoard', () => {
  it('partitions into To Apply / Active / Closed with Closed collapsed by default', async () => {
    render(<TrackingBoard onSelect={vi.fn()} />, { wrapper: makeWrapper() })

    // To Apply + Active open by default → their rows are visible.
    expect(await screen.findByText('Queue Role')).toBeInTheDocument()
    expect(screen.getByText('Active Role')).toBeInTheDocument()

    // All three group headers render.
    expect(screen.getByRole('button', { name: /To Apply/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Active/ })).toBeInTheDocument()
    const closed = screen.getByRole('button', { name: /Closed/ })

    // Closed is collapsed → its row is hidden until expanded.
    expect(screen.queryByText('Closed Role')).not.toBeInTheDocument()
    expect(closed).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(closed)
    await waitFor(() => expect(screen.getByText('Closed Role')).toBeInTheDocument())
  })

  it('shows an empty-state message when there are no tracking jobs', async () => {
    stubFetch([])

    render(<TrackingBoard onSelect={vi.fn()} />, { wrapper: makeWrapper() })

    expect(await screen.findByText('No tracking jobs yet.')).toBeInTheDocument()
  })
})
