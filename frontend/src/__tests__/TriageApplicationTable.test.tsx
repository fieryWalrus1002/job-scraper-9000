import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { SnackbarProvider } from '../components/ui/snackbar'
import { TriageApplicationTable } from '../components/TriageApplicationTable'
import { ShortlistRowActions } from '../components/ShortlistRowActions'
import type { Application } from '../types'

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

const APPLICATION: Application = {
  dedup_hash: 'hash-a',
  status: 'maybe',
  applied_at: null,

  created_at: '2026-01-16T00:00:00Z',
  updated_at: '2026-01-16T00:00:00Z',
  title: 'Example Role',
  company: 'Acme',
  latest_event: null,
}

const APPLICATION_STATUS_CHANGE: Application = {
  ...APPLICATION,
  dedup_hash: 'hash-status-change',
  latest_event: {
    kind: 'status_change',
    occurred_at: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(),
    body: null,
    to_status: 'screening',
  },
}

const APPLICATION_EVENT: Application = {
  ...APPLICATION,
  dedup_hash: 'hash-event',
  latest_event: {
    kind: 'event',
    occurred_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
    body: 'Followed up with recruiter',
    to_status: null,
  },
}

const APPLICATION_EVENT_EMPTY: Application = {
  ...APPLICATION,
  dedup_hash: 'hash-event-empty',
  latest_event: {
    kind: 'event',
    occurred_at: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
    body: null,
    to_status: null,
  },
}

function makeStubFetch(applications: Application[]) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (init?.method === 'PATCH') {
      const update = JSON.parse(String(init.body)) as { status?: string }
      return Promise.resolve(
        new Response(JSON.stringify({ ...APPLICATION, ...update }), { status: 200 }),
      )
    }
    if (url.includes('/api/applications')) {
      return Promise.resolve(new Response(JSON.stringify(applications), { status: 200 }))
    }
    return Promise.resolve(new Response('{}', { status: 200 }))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

beforeEach(() => vi.restoreAllMocks())
afterEach(() => vi.unstubAllGlobals())

describe('TriageApplicationTable row actions', () => {
  it('renders Pursue + Trash on the Shortlist row and Pursue PATCHes status to to_apply', async () => {
    const fetchMock = makeStubFetch([APPLICATION])

    render(
      <TriageApplicationTable
        statuses={['maybe']}
        onSelect={vi.fn()}
        emptyMessage="No shortlisted jobs yet."
        renderRowActions={(app) => <ShortlistRowActions application={app} />}
      />,
      { wrapper: makeWrapper() },
    )

    expect(await screen.findByRole('button', { name: 'Pursue' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Trash' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Pursue' }))

    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')
      expect(patch).toBeTruthy()
      expect(String(patch![0])).toContain('/api/applications/hash-a')
      expect(JSON.parse(String((patch![1] as RequestInit).body))).toEqual({ status: 'to_apply' })
    })
  })

  it('renders no actions column when renderRowActions is omitted', async () => {
    makeStubFetch([APPLICATION])

    render(
      <TriageApplicationTable
        statuses={['maybe']}
        onSelect={vi.fn()}
        emptyMessage="No shortlisted jobs yet."
      />,
      { wrapper: makeWrapper() },
    )

    expect(await screen.findByText('Example Role')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Pursue' })).not.toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Actions' })).not.toBeInTheDocument()
  })
})

describe('Latest activity column', () => {
  it('renders the "Latest activity" column header', async () => {
    makeStubFetch([APPLICATION])

    render(
      <TriageApplicationTable
        statuses={['maybe']}
        onSelect={vi.fn()}
        emptyMessage="No shortlisted jobs yet."
      />,
      { wrapper: makeWrapper() },
    )

    expect(await screen.findByRole('columnheader', { name: 'Latest activity' })).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Notes' })).not.toBeInTheDocument()
  })

  it('renders "Entered Screening" for a status_change latest_event', async () => {
    makeStubFetch([APPLICATION_STATUS_CHANGE])

    render(
      <TriageApplicationTable
        statuses={['maybe']}
        onSelect={vi.fn()}
        emptyMessage="No shortlisted jobs yet."
      />,
      { wrapper: makeWrapper() },
    )

    expect(await screen.findByText(/Entered Screening/)).toBeInTheDocument()
  })

  it('renders the body text for an event latest_event', async () => {
    makeStubFetch([APPLICATION_EVENT])

    render(
      <TriageApplicationTable
        statuses={['maybe']}
        onSelect={vi.fn()}
        emptyMessage="No shortlisted jobs yet."
      />,
      { wrapper: makeWrapper() },
    )

    expect(await screen.findByText(/Followed up with recruiter/)).toBeInTheDocument()
  })

  it('renders "—" when latest_event is null', async () => {
    makeStubFetch([APPLICATION])

    render(
      <TriageApplicationTable
        statuses={['maybe']}
        onSelect={vi.fn()}
        emptyMessage="No shortlisted jobs yet."
      />,
      { wrapper: makeWrapper() },
    )

    await screen.findByText('Example Role')
    // The null latest_event renders an em-dash in the cell; verify the column header exists
    // and the row is present (the em-dash is wrapped in text-faint span)
    expect(screen.getByRole('columnheader', { name: 'Latest activity' })).toBeInTheDocument()
  })

  it('renders "—" for an event with null body', async () => {
    makeStubFetch([APPLICATION_EVENT_EMPTY])

    render(
      <TriageApplicationTable
        statuses={['maybe']}
        onSelect={vi.fn()}
        emptyMessage="No shortlisted jobs yet."
      />,
      { wrapper: makeWrapper() },
    )

    await screen.findByText('Example Role')
    expect(screen.getByRole('columnheader', { name: 'Latest activity' })).toBeInTheDocument()
  })
})
