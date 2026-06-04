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
    // Mock window.location so assignments don't trigger JSDOM navigation errors
    delete (window as unknown as Record<string, unknown>).location
    ;(window as unknown as Record<string, unknown>).location = { href: '' }

    // Stub fetch for API calls made by other hooks inside App
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 }),
      ),
    )
  })

  it('redirects to login when unauthenticated', async () => {
    vi.spyOn(auth, 'fetchPrincipal').mockResolvedValue(null)

    renderApp()

    expect(await screen.findByTestId('auth-redirect')).toBeInTheDocument()
    expect(window.location.href).toBe('/.auth/login/aad?post_login_redirect_uri=/')
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
