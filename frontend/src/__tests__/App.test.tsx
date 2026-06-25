import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useLocation } from 'react-router-dom'
import App from '../App'
import * as auth from '../lib/auth'
import { SnackbarProvider } from '../components/ui/snackbar'

function renderApp(initialEntries: string[] = ['/jobs']) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <SnackbarProvider>
        <MemoryRouter initialEntries={initialEntries}>
          <LocationProbe />
          <App />
        </MemoryRouter>
      </SnackbarProvider>
    </QueryClientProvider>,
  )
}

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>
}

describe('App auth gate', () => {
  beforeEach(() => {
    // Mock window.location so navigation calls don't trigger JSDOM errors
    delete (window as unknown as Record<string, unknown>).location
    ;(window as unknown as Record<string, unknown>).location = { href: '', assign: vi.fn() }

    // Stub fetch for API calls made by hooks inside App.
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        const body = url.includes('/api/applications') ? [] : { items: [], total: 0 }
        return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
      }),
    )
  })

  it('shows dev message when unauthenticated (no redirect in dev)', async () => {
    vi.spyOn(auth, 'fetchPrincipal').mockResolvedValue(null)

    renderApp()

    expect(await screen.findByTestId('auth-redirect')).toBeInTheDocument()
    expect(screen.getByTestId('auth-redirect').textContent).toMatch(/VITE_AUTH_BYPASS/)
    // In dev mode the redirect must NOT fire — it causes a strobe loop in local dev
    expect(window.location.href).toBe('')
  })

  it('renders app with logged-in email when authenticated', async () => {
    vi.spyOn(auth, 'fetchPrincipal').mockResolvedValue({
      userId: 'u1',
      userDetails: 'test@example.com',
      userRoles: ['authenticated'],
    })

    renderApp()

    expect(await screen.findByText('test@example.com')).toBeInTheDocument()
    // Logout link should point to /.auth/logout
    const logoutLink = screen.getByText('test@example.com').closest('a')
    expect(logoutLink).toHaveAttribute('href', '/.auth/logout')
  })

  it('renders the four routed triage funnel tabs', async () => {
    vi.spyOn(auth, 'fetchPrincipal').mockResolvedValue({
      userId: 'u1',
      userDetails: 'test@example.com',
      userRoles: ['authenticated'],
    })

    renderApp(['/shortlist'])

    expect(await screen.findByRole('navigation', { name: 'Triage funnel' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Trash/ })).toHaveAttribute('href', '/trash')
    expect(screen.getByRole('link', { name: /Search \/ All jobs/ })).toHaveAttribute(
      'href',
      '/jobs',
    )
    expect(screen.getByRole('link', { name: /Shortlist/ })).toHaveAttribute('href', '/shortlist')
    expect(screen.getByRole('link', { name: /Tracking/ })).toHaveAttribute('href', '/tracking')
  })

  it('hides the full jobs filter pane outside the jobs route', async () => {
    vi.spyOn(auth, 'fetchPrincipal').mockResolvedValue({
      userId: 'u1',
      userDetails: 'test@example.com',
      userRoles: ['authenticated'],
    })

    renderApp(['/tracking'])

    expect(await screen.findByRole('navigation', { name: 'Triage funnel' })).toBeInTheDocument()
    expect(screen.queryByLabelText(/Collapse filters|Expand filters/)).not.toBeInTheDocument()
  })

  it('redirects root to grab-bag', async () => {
    vi.spyOn(auth, 'fetchPrincipal').mockResolvedValue({
      userId: 'u1',
      userDetails: 'test@example.com',
      userRoles: ['authenticated'],
    })

    renderApp(['/'])

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/grab-bag'))
  })

  it('preserves an incoming seed when redirecting root to grab-bag', async () => {
    vi.spyOn(auth, 'fetchPrincipal').mockResolvedValue({
      userId: 'u1',
      userDetails: 'test@example.com',
      userRoles: ['authenticated'],
    })

    renderApp(['/?seed=42'])

    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent('/grab-bag?seed=42'),
    )
  })

  it('passes the clicked application row into status-tab detail panels', async () => {
    vi.spyOn(auth, 'fetchPrincipal').mockResolvedValue({
      userId: 'u1',
      userDetails: 'test@example.com',
      userRoles: ['authenticated'],
    })

    const app = {
      dedup_hash: 'hash-a',
      status: 'maybe',
      applied_at: null,
      created_at: '2026-01-16T00:00:00Z',
      updated_at: '2026-01-16T00:00:00Z',
      title: 'Example Role',
      company: 'Acme',
      fit_score: 4,
      source_url: null,
    }
    const jobDetail = {
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

    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input)
        if (url === '/api/applications?status=maybe') {
          return Promise.resolve(new Response(JSON.stringify([app]), { status: 200 }))
        }
        if (url === '/api/applications') {
          return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }))
        }
        if (url === '/api/jobs/hash-a') {
          return Promise.resolve(new Response(JSON.stringify(jobDetail), { status: 200 }))
        }
        if (url === '/api/eval/corrections/hash-a') {
          return Promise.resolve(
            new Response('Not found', { status: 404, statusText: 'Not Found' }),
          )
        }
        if (url === '/api/applications/hash-a' && init?.method === 'PATCH') {
          return Promise.resolve(
            new Response(JSON.stringify({ ...app, status: 'to_apply' }), { status: 200 }),
          )
        }
        if (url.startsWith('/api/jobs?')) {
          return Promise.resolve(
            new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 }),
          )
        }
        return Promise.resolve(new Response('Not found', { status: 404, statusText: 'Not Found' }))
      }),
    )

    renderApp(['/shortlist'])

    fireEvent.click(await screen.findByText('Example Role'))
    const toolbar = await screen.findByRole('toolbar', { name: 'Triage status' })
    fireEvent.click(within(toolbar).getByRole('button', { name: /Pursue/ }))

    await waitFor(() => expect(applicationPatches()).toHaveLength(1))
    expect(applicationPatches()[0]?.[1]).toMatchObject({
      method: 'PATCH',
      body: JSON.stringify({ status: 'to_apply' }),
    })
  })

  it('hides already-triaged jobs from the Jobs feed', async () => {
    vi.spyOn(auth, 'fetchPrincipal').mockResolvedValue({
      userId: 'u1',
      userDetails: 'test@example.com',
      userRoles: ['authenticated'],
    })

    const summary = (dedup_hash: string, title: string) => ({
      dedup_hash,
      source: 'linkedin',
      source_url: 'https://example.com/job',
      title,
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
    })
    // hash-a is shortlisted (has an application row); the backend would already
    // exclude it on a fresh fetch, but the jobs query isn't refetched on triage
    // (#345), so the feed must filter it out client-side.
    const triagedApp = {
      dedup_hash: 'hash-a',
      status: 'maybe',
      applied_at: null,
      created_at: '2026-01-16T00:00:00Z',
      updated_at: '2026-01-16T00:00:00Z',
      title: 'Triaged Role',
      company: 'Acme',
    }

    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url === '/api/applications') {
          return Promise.resolve(new Response(JSON.stringify([triagedApp]), { status: 200 }))
        }
        if (url.startsWith('/api/jobs?')) {
          const items = [summary('hash-a', 'Triaged Role'), summary('hash-b', 'Untriaged Role')]
          return Promise.resolve(new Response(JSON.stringify({ items, total: 2 }), { status: 200 }))
        }
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }))
      }),
    )

    renderApp(['/jobs'])

    expect(await screen.findByText('Untriaged Role')).toBeInTheDocument()
    expect(screen.queryByText('Triaged Role')).not.toBeInTheDocument()
  })

  it('redirects unknown paths to grab-bag', async () => {
    vi.spyOn(auth, 'fetchPrincipal').mockResolvedValue({
      userId: 'u1',
      userDetails: 'test@example.com',
      userRoles: ['authenticated'],
    })

    renderApp(['/not-a-real-route'])

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/grab-bag'))
  })
})

function applicationPatches() {
  return vi
    .mocked(fetch)
    .mock.calls.filter(
      ([url, init]) => String(url) === '/api/applications/hash-a' && init?.method === 'PATCH',
    )
}
