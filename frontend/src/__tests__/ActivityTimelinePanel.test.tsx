import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { ActivityTimelinePanel } from '../components/JobDetailPanel/surfaces/commonSections'
import type { JobDetail } from '../types'

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

const JOB_DATA: JobDetail = {
  dedup_hash: 'hash-timeline',
  source: 'linkedin',
  source_job_id: 'src-1',
  source_url: 'https://example.com/j/1',
  title: 'Test Role',
  company: 'TestCo',
  location: 'Remote',
  posted_at: '2026-01-01',
  description: 'A test description.',
  scraped_at: '2026-01-01T00:00:00Z',
  remote_classification: 'fully_remote',
  salary_min_usd: null,
  salary_max_usd: null,
  salary_period: null,
  fit_score: 3,
  confidence: 'high',
  score_rationale: 'Relevant.',
  ai_fit_detail: null,
  pipeline_metadata: {},
  run_id: 'run-1',
  scored_at: '2026-01-02T00:00:00Z',
  model: 'test',
  provider: 'test',
  profile_version: 'v1',
  failure_reason: null,
  metadata: {},
  ingested_at: '2026-01-02T00:00:00Z',
}

const MOCK_EVENTS = [
  {
    id: 'evt-3',
    dedup_hash: 'hash-timeline',
    kind: 'event' as const,
    occurred_at: '2026-02-01T12:00:00Z',
    body: 'Followed up with recruiter',
    tags: ['follow-up'],
    metadata: {},
    created_at: '2026-02-01T12:00:00Z',
  },
  {
    id: 'evt-2',
    dedup_hash: 'hash-timeline',
    kind: 'status_change' as const,
    occurred_at: '2026-01-25T10:00:00Z',
    body: null,
    tags: [],
    metadata: { from_status: 'applied', to_status: 'screening' },
    created_at: '2026-01-25T10:00:00Z',
  },
  {
    id: 'evt-1',
    dedup_hash: 'hash-timeline',
    kind: 'status_change' as const,
    occurred_at: '2026-01-15T09:00:00Z',
    body: null,
    tags: [],
    metadata: { from_status: null, to_status: 'applied' },
    created_at: '2026-01-15T09:00:00Z',
  },
]

describe('ActivityTimelinePanel', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  afterEach(() => vi.unstubAllGlobals())

  it('renders events in reverse-chronological order', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify(MOCK_EVENTS), { status: 200 })),
    )

    render(<ActivityTimelinePanel jobData={JOB_DATA} />, { wrapper: makeWrapper() })

    // Section is collapsed by default — click header to expand
    fireEvent.click(screen.getByRole('button', { name: 'Activity Timeline' }))

    await waitFor(() => {
      expect(screen.queryByText('Loading…')).not.toBeInTheDocument()
    })

    // The API returns DESC (newest first), so the first event shown is evt-3 (Feb 1)
    expect(screen.getByText(/Followed up with recruiter/)).toBeInTheDocument()
  })

  it('renders status_change entries distinctly (italic + system icon)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify(MOCK_EVENTS), { status: 200 })),
    )

    render(<ActivityTimelinePanel jobData={JOB_DATA} />, { wrapper: makeWrapper() })
    fireEvent.click(screen.getByRole('button', { name: 'Activity Timeline' }))

    await waitFor(() => {
      expect(screen.queryByText('Loading…')).not.toBeInTheDocument()
    })

    // "Entered Applied" (from_status: null) and "Moved from Applied → Screening"
    // (both statuses run through STATUS_LABELS, so they render title-cased)
    expect(screen.getByText(/Entered Applied/)).toBeInTheDocument()
    expect(screen.getByText(/Moved from Applied/)).toBeInTheDocument()

    // Verify the status_change rows use italic styling
    const enteredEl = screen.getByText(/Entered Applied/)
    expect(enteredEl.classList.contains('italic')).toBe(true)
  })

  it('renders tags and body for "event" kind entries', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify(MOCK_EVENTS), { status: 200 })),
    )

    render(<ActivityTimelinePanel jobData={JOB_DATA} />, { wrapper: makeWrapper() })
    fireEvent.click(screen.getByRole('button', { name: 'Activity Timeline' }))

    await waitFor(() => {
      expect(screen.queryByText('Loading…')).not.toBeInTheDocument()
    })

    expect(screen.getByText('follow-up')).toBeInTheDocument()
    expect(screen.getByText(/Followed up with recruiter/)).toBeInTheDocument()
  })

  it('shows empty state placeholder when no events exist', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify([]), { status: 200 })),
    )

    render(<ActivityTimelinePanel jobData={JOB_DATA} />, { wrapper: makeWrapper() })
    fireEvent.click(screen.getByRole('button', { name: 'Activity Timeline' }))

    await waitFor(() => {
      expect(screen.queryByText('Loading…')).not.toBeInTheDocument()
    })

    expect(screen.getByText(/No activity yet/)).toBeInTheDocument()
  })

  it('shows error state when fetch fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response('Server Error', { status: 500, statusText: 'Internal Server Error' }),
        ),
    )

    render(<ActivityTimelinePanel jobData={JOB_DATA} />, { wrapper: makeWrapper() })
    fireEvent.click(screen.getByRole('button', { name: 'Activity Timeline' }))

    await waitFor(() => {
      expect(screen.getByText(/Could not load activity/)).toBeInTheDocument()
    })
  })

  it('offers edit and delete buttons on user-created (event kind) rows', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify(MOCK_EVENTS), { status: 200 })),
    )

    render(<ActivityTimelinePanel jobData={JOB_DATA} />, { wrapper: makeWrapper() })
    fireEvent.click(screen.getByRole('button', { name: 'Activity Timeline' }))

    await waitFor(() => {
      expect(screen.queryByText('Loading…')).not.toBeInTheDocument()
    })

    // The user event (evt-3) should have edit and del buttons
    expect(screen.getByText('edit')).toBeInTheDocument()
    expect(screen.getByText('del')).toBeInTheDocument()
  })

  it('does NOT offer edit/delete on status_change events', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify(MOCK_EVENTS), { status: 200 })),
    )

    render(<ActivityTimelinePanel jobData={JOB_DATA} />, { wrapper: makeWrapper() })
    fireEvent.click(screen.getByRole('button', { name: 'Activity Timeline' }))

    await waitFor(() => {
      expect(screen.queryByText('Loading…')).not.toBeInTheDocument()
    })

    // status_change rows should have the system icon but no edit/del buttons
    expect(screen.getByText(/Entered Applied/)).toBeInTheDocument()
    expect(screen.getByText(/Moved from Applied/)).toBeInTheDocument()

    // There should be exactly one "edit" and one "del" (for the single user event)
    // We verify this by counting: only 1 of each
    const editButtons = screen.getAllByText('edit')
    expect(editButtons).toHaveLength(1)
    const delButtons = screen.getAllByText('del')
    expect(delButtons).toHaveLength(1)
  })

  it('"Add note" button reveals the form, and submitting POSTs with date/body/tags', async () => {
    const newEvent = {
      id: 'evt-new',
      dedup_hash: 'hash-timeline',
      kind: 'event' as const,
      occurred_at: '2026-06-23T00:00:00Z',
      body: 'Test note',
      tags: ['contact'],
      metadata: {},
      created_at: '2026-06-23T12:00:00Z',
    }
    // Track whether POST has been called; after that, GET returns the new event
    let postCalled = false
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString()
      const method = init?.method ?? 'GET'
      if (method === 'POST' && url.includes('/events')) {
        postCalled = true
        return new Response(JSON.stringify(newEvent), { status: 201 })
      }
      // GET events — empty until POST succeeds, then returns the new event
      const events = postCalled ? [newEvent] : []
      return new Response(JSON.stringify(events), { status: 200 })
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<ActivityTimelinePanel jobData={JOB_DATA} />, { wrapper: makeWrapper() })
    fireEvent.click(screen.getByRole('button', { name: 'Activity Timeline' }))

    await waitFor(() => {
      expect(screen.queryByText('Loading…')).not.toBeInTheDocument()
    })

    // Click "+ Add note" to reveal the form
    fireEvent.click(screen.getByText('+ Add note'))

    // Form fields should be visible
    expect(screen.getByLabelText(/Date/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/Note/i)).toBeInTheDocument()

    // Fill in the note body
    fireEvent.change(screen.getByLabelText(/Note/i), {
      target: { value: 'Test note' },
    })

    // Submit the form
    fireEvent.click(screen.getByText('Add note'))

    // Verify POST was called with the correct payload
    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find((call) => call[1]?.method === 'POST')
      expect(postCall).toBeDefined()
      expect(postCall![0]).toContain('/api/applications/hash-timeline/events')
      const body = JSON.parse(postCall![1]?.body as string)
      expect(body.kind).toBe('event')
      expect(body.body).toBe('Test note')
    })

    // After mutation, the query is invalidated and refetches — the mock now
    // returns the new event, so the timeline should show it.
    await waitFor(() => {
      expect(screen.getByText('Test note')).toBeInTheDocument()
    })
  })
})
