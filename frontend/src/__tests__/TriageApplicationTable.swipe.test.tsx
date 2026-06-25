import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { ApplicationTable } from '../components/TriageApplicationTable'
import { SnackbarProvider } from '../components/ui/snackbar'
import type { Application } from '../types'

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <SnackbarProvider>{children}</SnackbarProvider>
    </QueryClientProvider>
  )
}

const APP: Application = {
  dedup_hash: 'hash-swipe',
  status: 'maybe',
  applied_at: null,
  created_at: '2026-01-16T00:00:00Z',
  updated_at: '2026-01-16T00:00:00Z',
  title: 'Swipeable Role',
  company: 'SwipeCo',
  source_url: null,
  fit_score: 4,
  latest_event: null,
}

const APP_TRASHED: Application = {
  ...APP,
  dedup_hash: 'hash-trash',
  status: 'passed',
}

function swipeRow(row: HTMLElement, deltaX: number) {
  const startX = 200
  const opts = { pointerId: 1, pointerType: 'touch', clientY: 100 }
  fireEvent.pointerDown(row, { ...opts, clientX: startX })
  fireEvent.pointerMove(row, { ...opts, clientX: startX + deltaX })
  fireEvent.pointerUp(row, { ...opts, clientX: startX + deltaX })
}

// Start a drag (pointerDown + pointerMove) but do NOT release — captures mid-drag
// state where the swipe affordance pill is visible.
function dragRow(row: HTMLElement, deltaX: number) {
  const startX = 200
  const opts = { pointerId: 1, pointerType: 'touch', clientY: 100 }
  fireEvent.pointerDown(row, { ...opts, clientX: startX })
  fireEvent.pointerMove(row, { ...opts, clientX: startX + deltaX })
}

function applicationCalls() {
  return vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes('/api/applications'))
}

// ── Tests ────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.restoreAllMocks()
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 200 })),
  )
})

afterEach(() => vi.unstubAllGlobals())

describe('Shortlist swipe-to-triage', () => {
  it('swipe left → Trash (passed)', async () => {
    render(
      <ApplicationTable
        applications={[APP]}
        onSelect={vi.fn()}
        swipeActions={{
          left: { to: 'passed', label: 'Trash', polarity: 'negative' },
          right: { to: 'to_apply', label: 'Pursue', polarity: 'positive' },
        }}
      />,
      { wrapper: makeWrapper() },
    )

    const row = screen.getByText('Swipeable Role').closest('tr')!
    swipeRow(row, -120)

    await waitFor(() => expect(applicationCalls()).toHaveLength(1))
    const [, init] = applicationCalls()[0]
    expect(init?.method).toBe('PATCH')
    expect(init?.body).toContain('passed')
  })

  it('swipe right → Pursue (to_apply)', async () => {
    render(
      <ApplicationTable
        applications={[APP]}
        onSelect={vi.fn()}
        swipeActions={{
          left: { to: 'passed', label: 'Trash', polarity: 'negative' },
          right: { to: 'to_apply', label: 'Pursue', polarity: 'positive' },
        }}
      />,
      { wrapper: makeWrapper() },
    )

    const row = screen.getByText('Swipeable Role').closest('tr')!
    swipeRow(row, 120)

    await waitFor(() => expect(applicationCalls()).toHaveLength(1))
    const [, init] = applicationCalls()[0]
    expect(init?.method).toBe('PATCH')
    expect(init?.body).toContain('to_apply')
  })

  it('a horizontal swipe does NOT call onSelect', async () => {
    const onSelect = vi.fn()
    render(
      <ApplicationTable
        applications={[APP]}
        onSelect={onSelect}
        swipeActions={{
          left: { to: 'passed', label: 'Trash', polarity: 'negative' },
          right: { to: 'to_apply', label: 'Pursue', polarity: 'positive' },
        }}
      />,
      { wrapper: makeWrapper() },
    )

    const row = () => screen.getByText('Swipeable Role').closest('tr')!
    swipeRow(row(), -120)
    fireEvent.click(row())
    expect(onSelect).not.toHaveBeenCalled()
  })
})

describe('Trash swipe-to-triage', () => {
  it('swipe right → Un-trash (remove)', async () => {
    render(
      <ApplicationTable
        applications={[APP_TRASHED]}
        onSelect={vi.fn()}
        swipeActions={{
          right: { to: 'remove', label: 'Un-trash', polarity: 'positive' },
        }}
      />,
      { wrapper: makeWrapper() },
    )

    const row = screen.getByText('Swipeable Role').closest('tr')!
    swipeRow(row, 120)

    await waitFor(() => expect(applicationCalls()).toHaveLength(1))
    const [, init] = applicationCalls()[0]
    expect(init?.method).toBe('DELETE')
  })

  it('swipe left → no-op (no triage call)', async () => {
    render(
      <ApplicationTable
        applications={[APP_TRASHED]}
        onSelect={vi.fn()}
        swipeActions={{
          right: { to: 'remove', label: 'Un-trash', polarity: 'positive' },
        }}
      />,
      { wrapper: makeWrapper() },
    )

    const row = screen.getByText('Swipeable Role').closest('tr')!
    swipeRow(row, -120)

    // No API call should be made for left swipe on Trash (no left action defined).
    await vi.waitFor(
      () => {
        expect(applicationCalls()).toHaveLength(0)
      },
      { timeout: 500 },
    )
  })
})

describe('Tracking (no swipeActions) — unchanged', () => {
  it('renders rows with no swipe transform and tap still selects', () => {
    const onSelect = vi.fn()
    render(<ApplicationTable applications={[APP]} onSelect={onSelect} />, {
      wrapper: makeWrapper(),
    })

    const row = screen.getByText('Swipeable Role').closest('tr')!
    // No pointer handlers should be on the row (no swipe).
    expect(row).not.toHaveAttribute('onpointerdown')

    // A tap selects the row.
    fireEvent.click(row)
    expect(onSelect).toHaveBeenCalledWith(APP)
  })
})

describe('Swipe affordance pills', () => {
  it('Shortlist: right-drag shows Pursue pill', () => {
    render(
      <ApplicationTable
        applications={[APP]}
        onSelect={vi.fn()}
        swipeActions={{
          left: { to: 'passed', label: 'Trash', polarity: 'negative' },
          right: { to: 'to_apply', label: 'Pursue', polarity: 'positive' },
        }}
      />,
      { wrapper: makeWrapper() },
    )

    const row = screen.getByText('Swipeable Role').closest('tr')!
    dragRow(row, 120)
    expect(screen.queryByText('Pursue')).not.toBeNull()
  })

  it('Shortlist: left-drag shows Trash pill', () => {
    render(
      <ApplicationTable
        applications={[APP]}
        onSelect={vi.fn()}
        swipeActions={{
          left: { to: 'passed', label: 'Trash', polarity: 'negative' },
          right: { to: 'to_apply', label: 'Pursue', polarity: 'positive' },
        }}
      />,
      { wrapper: makeWrapper() },
    )

    const row = screen.getByText('Swipeable Role').closest('tr')!
    dragRow(row, -120)
    expect(screen.queryByText('Trash')).not.toBeNull()
  })

  it('Trash: right-drag shows Un-trash pill', () => {
    render(
      <ApplicationTable
        applications={[APP_TRASHED]}
        onSelect={vi.fn()}
        swipeActions={{
          right: { to: 'remove', label: 'Un-trash', polarity: 'positive' },
        }}
      />,
      { wrapper: makeWrapper() },
    )

    const row = screen.getByText('Swipeable Role').closest('tr')!
    dragRow(row, 120)
    expect(screen.queryByText('Un-trash')).not.toBeNull()
  })

  it('Trash: left-drag shows no pill (no left action defined)', () => {
    render(
      <ApplicationTable
        applications={[APP_TRASHED]}
        onSelect={vi.fn()}
        swipeActions={{
          right: { to: 'remove', label: 'Un-trash', polarity: 'positive' },
        }}
      />,
      { wrapper: makeWrapper() },
    )

    const row = screen.getByText('Swipeable Role').closest('tr')!
    dragRow(row, -120)
    // No affordance pill should appear for left-drag on Trash surface
    expect(screen.queryByText('Un-trash')).toBeNull()
    expect(screen.queryByText('Pursue')).toBeNull()
  })
})
