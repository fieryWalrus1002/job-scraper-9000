import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import JobTable from '../components/JobTable'
import type { Application, JobSummary } from '../types'

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

function renderJobTable(applications?: Map<string, Application>) {
  return render(
    <JobTable
      items={[JOB]}
      visibleColumns={new Set(['fit_score', 'title', 'company', 'location', 'posted_at'])}
      onSelect={vi.fn()}
      applications={applications}
      page={0}
      pageSize={50}
      total={1}
      onPageChange={vi.fn()}
    />,
    { wrapper: makeWrapper() },
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(new Response(JSON.stringify(APPLICATION), { status: 201 })),
  )
})

afterEach(() => vi.unstubAllGlobals())

const JOB: JobSummary = {
  dedup_hash: 'hash-a',
  source: 'linkedin',
  source_url: 'https://example.com/job',
  title: 'Example Role',
  company: 'Acme',
  location: 'Remote',
  posted_at: '2026-01-15',
  remote_classification: 'fully_remote',
  salary_min_usd: null,
  salary_max_usd: null,
  salary_period: null,
  fit_score: 4,
  confidence: 'high',
  score_rationale: 'Looks relevant.',
  failure_reason: null,
  scored_at: '2026-01-16T00:00:00Z',
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

describe('JobTable triage actions', () => {
  it('shows only Trash and Shortlist row actions and marks the selected status', async () => {
    renderJobTable()

    expect(screen.getByRole('button', { name: 'Trash' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Shortlist' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Maybe' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'To Apply' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Shortlist' }))

    await waitFor(() => expect(applicationPosts()).toHaveLength(1))
    expect(applicationPosts()[0]?.[1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({ dedup_hash: 'hash-a', status: 'maybe' }),
    })
  })

  it('limits the Jobs context menu to the same binary funnel actions', () => {
    renderJobTable(new Map([['hash-a', { ...APPLICATION, status: 'to_apply' }]]))

    const row = screen.getByText('Example Role').closest('tr')
    expect(row).not.toBeNull()
    fireEvent.contextMenu(row!)

    expect(screen.getAllByRole('button', { name: 'Trash' })).toHaveLength(2)
    expect(screen.getAllByRole('button', { name: 'Shortlist' })).toHaveLength(2)
    expect(screen.queryByRole('button', { name: 'To Apply' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Applied' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove tracking' })).not.toBeInTheDocument()
  })
})

function applicationPosts() {
  return vi
    .mocked(fetch)
    .mock.calls.filter(
      ([url, init]) => String(url) === '/api/applications' && init?.method === 'POST',
    )
}
