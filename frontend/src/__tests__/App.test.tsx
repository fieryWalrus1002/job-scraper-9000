import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import App from '../App'
import * as auth from '../lib/auth'

function renderApp() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('App auth gate', () => {
  beforeEach(() => {
    // Mock window.location so navigation calls don't trigger JSDOM errors
    delete (window as unknown as Record<string, unknown>).location
    ;(window as unknown as Record<string, unknown>).location = { href: '', assign: vi.fn() }

    // Stub fetch for API calls made by other hooks inside App
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 }),
      ),
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
})
