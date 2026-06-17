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
  notes: null,
  created_at: '2026-01-16T00:00:00Z',
  updated_at: '2026-01-16T00:00:00Z',
  title: 'Example Role',
  company: 'Acme',
}

// Routes the application-list GET to the maybe bucket and echoes PATCHes back.
function stubFetch() {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (init?.method === 'PATCH') {
      const update = JSON.parse(String(init.body)) as { status?: string }
      return Promise.resolve(
        new Response(JSON.stringify({ ...APPLICATION, ...update }), { status: 200 }),
      )
    }
    if (url.includes('/api/applications')) {
      return Promise.resolve(new Response(JSON.stringify([APPLICATION]), { status: 200 }))
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
    const fetchMock = stubFetch()

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
    stubFetch()

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
