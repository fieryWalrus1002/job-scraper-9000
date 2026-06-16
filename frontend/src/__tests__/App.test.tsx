import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useLocation } from 'react-router-dom'
import App from '../App'
import * as auth from '../lib/auth'

function renderApp(initialEntries: string[] = ['/jobs']) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={initialEntries}>
        <LocationProbe />
        <App />
      </MemoryRouter>
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
    expect(screen.getByRole('link', { name: /Jobs/ })).toHaveAttribute('href', '/jobs')
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

  it('redirects root to jobs while preserving filters', async () => {
    vi.spyOn(auth, 'fetchPrincipal').mockResolvedValue({
      userId: 'u1',
      userDetails: 'test@example.com',
      userRoles: ['authenticated'],
    })

    renderApp(['/?min_score=4'])

    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent('/jobs?min_score=4'),
    )
  })

  it('redirects unknown paths to jobs', async () => {
    vi.spyOn(auth, 'fetchPrincipal').mockResolvedValue({
      userId: 'u1',
      userDetails: 'test@example.com',
      userRoles: ['authenticated'],
    })

    renderApp(['/not-a-real-route'])

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/jobs'))
  })
})
