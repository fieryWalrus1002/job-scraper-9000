import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { SnackbarProvider } from '../components/ui/snackbar'
import { JobDetailPanel } from '../components/JobDetailPanel'
import type { Application, JobDetail, JobSummary } from '../types'

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

beforeEach(() => {
  vi.restoreAllMocks()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/jobs/hash-a') {
        return new Response(JSON.stringify(JOB_DETAIL), { status: 200 })
      }
      if (url === '/api/eval/corrections/hash-a') {
        return new Response('Not found', { status: 404, statusText: 'Not Found' })
      }
      if (url === '/api/applications' && init?.method === 'POST') {
        return new Response(JSON.stringify(APPLICATION), { status: 201 })
      }
      if (url === '/api/applications/hash-a' && init?.method === 'PATCH') {
        return new Response(JSON.stringify(APPLICATION), { status: 200 })
      }
      if (url === '/api/applications/hash-a' && init?.method === 'DELETE') {
        return new Response(null, { status: 204 })
      }
      return new Response('Not found', { status: 404, statusText: 'Not Found' })
    }),
  )
})

afterEach(() => vi.unstubAllGlobals())

const JOB_DETAIL: JobDetail = {
  dedup_hash: 'hash-a',
  source: 'linkedin',
  source_job_id: 'source-1',
  source_url: 'https://example.com/job',
  title: 'Example Role',
  company: 'Acme',
  location: 'Remote',
  posted_at: '2026-01-15',
  description: 'A useful job description.',
  scraped_at: '2026-01-15T00:00:00Z',
  remote_classification: 'fully_remote',
  salary_min_usd: null,
  salary_max_usd: null,
  salary_period: null,
  fit_score: 4,
  confidence: 'high',
  score_rationale: 'Looks relevant.',
  ai_fit_detail: null,
  pipeline_metadata: {},
  run_id: 'run-1',
  scored_at: '2026-01-16T00:00:00Z',
  model: 'test-model',
  provider: 'test-provider',
  profile_version: 'v1',
  failure_reason: null,
  metadata: {},
  ingested_at: '2026-01-16T00:00:00Z',
}

const JOB_SUMMARY: JobSummary = {
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

  created_at: '2026-01-16T00:00:00Z',
  updated_at: '2026-01-16T00:00:00Z',
  title: 'Example Role',
  company: 'Acme',
}

describe('JobDetailPanel triage actions', () => {
  it('uses binary Trash and Shortlist header actions for the Jobs surface', async () => {
    render(<JobDetailPanel dedupHash="hash-a" onClose={vi.fn()} surface="jobs" />, {
      wrapper: makeWrapper(),
    })

    const toolbar = await screen.findByRole('toolbar', { name: 'Triage status' })
    expect(within(toolbar).getByRole('button', { name: /Trash/ })).toBeInTheDocument()
    expect(within(toolbar).getByRole('button', { name: /Shortlist/ })).toBeInTheDocument()
    expect(within(toolbar).queryByRole('button', { name: /Maybe/ })).not.toBeInTheDocument()
    expect(within(toolbar).queryByRole('button', { name: /To Apply/ })).not.toBeInTheDocument()

    fireEvent.click(within(toolbar).getByRole('button', { name: /Shortlist/ }))

    await waitFor(() => expect(applicationPosts()).toHaveLength(1))
    expect(applicationPosts()[0]?.[1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({ dedup_hash: 'hash-a', status: 'maybe' }),
    })
  })

  it('renders summary placeholder data immediately, before the detail fetch resolves', () => {
    // Detail fetch never settles; with a summary placeholder the panel must
    // still render the header content instantly instead of flashing "Loading…".
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {})),
    )

    render(
      <JobDetailPanel dedupHash="hash-a" onClose={vi.fn()} surface="jobs" summary={JOB_SUMMARY} />,
      { wrapper: makeWrapper() },
    )

    // Synchronous (no findBy/await): the placeholder is shown on first render.
    expect(screen.getByText('Example Role')).toBeInTheDocument()
    expect(screen.queryByText('Loading…')).not.toBeInTheDocument()
  })

  it('uses second-pass decision actions for the Shortlist surface', async () => {
    render(
      <JobDetailPanel
        dedupHash="hash-a"
        onClose={vi.fn()}
        application={APPLICATION}
        surface="shortlist"
      />,
      { wrapper: makeWrapper() },
    )

    const toolbar = await screen.findByRole('toolbar', { name: 'Triage status' })
    expect(within(toolbar).getByRole('button', { name: /Pursue/ })).toBeInTheDocument()
    expect(within(toolbar).getByRole('button', { name: /Trash/ })).toBeInTheDocument()
    expect(within(toolbar).getByRole('button', { name: /Back to Jobs/ })).toBeInTheDocument()
    const buttons = within(toolbar).getAllByRole('button')
    expect(buttons[0]).toHaveAccessibleName('Trash')
    expect(buttons[1]).toHaveAccessibleName('Back to Jobs')
    expect(buttons[2]).toHaveAccessibleName('Pursue')
    expect(within(toolbar).queryByRole('button', { name: /To Apply/ })).not.toBeInTheDocument()

    fireEvent.click(within(toolbar).getByRole('button', { name: /Pursue/ }))

    await waitFor(() => expect(applicationPatches()).toHaveLength(1))
    expect(applicationPatches()[0]?.[1]).toMatchObject({
      method: 'PATCH',
      body: JSON.stringify({ status: 'to_apply' }),
    })
  })

  it('puts application tracking first for the Tracking surface', async () => {
    render(
      <JobDetailPanel
        dedupHash="hash-a"
        onClose={vi.fn()}
        application={{ ...APPLICATION, status: 'to_apply' }}
        surface="tracking"
      />,
      { wrapper: makeWrapper() },
    )

    const toolbar = await screen.findByRole('toolbar', { name: 'Triage status' })
    expect(within(toolbar).getByRole('button', { name: /Back to Shortlist/ })).toBeInTheDocument()
    expect(within(toolbar).getByRole('button', { name: /Trash/ })).toBeInTheDocument()
    expect(within(toolbar).queryByRole('button', { name: 'Shortlist' })).not.toBeInTheDocument()

    expect(await screen.findByText('Status')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'To Apply' })).toBeInTheDocument()
  })

  it('uses recovery actions for the Trash surface', async () => {
    render(<JobDetailPanel dedupHash="hash-a" onClose={vi.fn()} surface="trash" />, {
      wrapper: makeWrapper(),
    })

    const toolbar = await screen.findByRole('toolbar', { name: 'Triage status' })
    expect(within(toolbar).getByRole('button', { name: /Restore to Jobs/ })).toBeInTheDocument()
    expect(within(toolbar).getByRole('button', { name: /Shortlist/ })).toBeInTheDocument()

    fireEvent.click(within(toolbar).getByRole('button', { name: /Restore to Jobs/ }))

    await waitFor(() => expect(applicationDeletes()).toHaveLength(1))
  })
})

function applicationPosts() {
  return vi
    .mocked(fetch)
    .mock.calls.filter(
      ([url, init]) => String(url) === '/api/applications' && init?.method === 'POST',
    )
}

function applicationPatches() {
  return vi
    .mocked(fetch)
    .mock.calls.filter(
      ([url, init]) => String(url) === '/api/applications/hash-a' && init?.method === 'PATCH',
    )
}

function applicationDeletes() {
  return vi
    .mocked(fetch)
    .mock.calls.filter(
      ([url, init]) => String(url) === '/api/applications/hash-a' && init?.method === 'DELETE',
    )
}
