import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import SettingsPage from '../components/SettingsPage'
import * as auth from '../lib/auth'

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <SettingsPage />
    </QueryClientProvider>,
  )
}

const ONBOARDING_SETTINGS = {
  profile: null,
  profile_version: null,
  profile_updated_at: null,
  search: null,
  policies: null,
  search_updated_at: null,
}

const CONFIGURED_SETTINGS = {
  ...ONBOARDING_SETTINGS,
  profile: {
    summary: 'Backend engineer with a decade of Python and data work.',
    level: 'senior software engineer',
    core_skills: ['python', 'postgres'],
  },
  profile_version: '2026-06-11.abcdef012345',
}

/** Route the global fetch mock by URL + method. */
function stubFetch(handlers: {
  getSettings: unknown
  putProfile?: { status: number; body: unknown }
}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, opts?: RequestInit) => {
      if (url.endsWith('/api/settings') && (!opts || opts.method === undefined)) {
        return Promise.resolve(new Response(JSON.stringify(handlers.getSettings), { status: 200 }))
      }
      if (url.endsWith('/api/settings/profile') && opts?.method === 'PUT') {
        const h = handlers.putProfile ?? {
          status: 200,
          body: { profile_version: '2026-06-11.newnewnewnew', updated_at: '2026-06-11T00:00:00Z' },
        }
        return Promise.resolve(new Response(JSON.stringify(h.body), { status: h.status }))
      }
      return Promise.reject(new Error(`unexpected fetch: ${opts?.method ?? 'GET'} ${url}`))
    }),
  )
}

describe('SettingsPage profile section', () => {
  beforeEach(() => vi.unstubAllGlobals())

  it('shows onboarding state when no profile exists', async () => {
    stubFetch({ getSettings: ONBOARDING_SETTINGS })
    renderPage()
    expect(await screen.findByText(/No profile yet/i)).toBeInTheDocument()
    expect(screen.getByText(/Not yet saved/i)).toBeInTheDocument()
  })

  it('seeds the form from an existing profile', async () => {
    stubFetch({ getSettings: CONFIGURED_SETTINGS })
    renderPage()
    expect(await screen.findByDisplayValue(/Backend engineer with a decade/i)).toBeInTheDocument()
    // Lists render newline-joined; core_skills seeds the textarea (testing-library
    // normalizes the newline to a space when matching display values).
    expect(screen.getByDisplayValue(/python postgres/)).toBeInTheDocument()
    expect(screen.getByText('2026-06-11.abcdef012345')).toBeInTheDocument()
    expect(screen.queryByText(/No profile yet/i)).not.toBeInTheDocument()
  })

  it('renders server 422 errors inline next to the field', async () => {
    stubFetch({
      getSettings: ONBOARDING_SETTINGS,
      putProfile: {
        status: 422,
        body: {
          detail: [
            {
              loc: ['body', 'summary'],
              msg: 'String should have at least 20 characters',
              type: 'string_too_short',
            },
          ],
        },
      },
    })
    renderPage()
    await screen.findByText(/No profile yet/i)
    fireEvent.click(screen.getByRole('button', { name: /Save profile/i }))
    expect(
      await screen.findByText(/String should have at least 20 characters/i),
    ).toBeInTheDocument()
  })

  it('shows the new version after a successful save', async () => {
    stubFetch({ getSettings: ONBOARDING_SETTINGS })
    renderPage()
    await screen.findByText(/No profile yet/i)
    fireEvent.click(screen.getByRole('button', { name: /Save profile/i }))
    await waitFor(() => expect(screen.getByText('2026-06-11.newnewnewnew')).toBeInTheDocument())
    expect(screen.getByText(/Saved/i)).toBeInTheDocument()
  })
})

describe('SettingsPage four-section nav', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('defaults to Profile; search sections are hidden until selected', async () => {
    stubFetch({ getSettings: ONBOARDING_SETTINGS })
    renderPage()
    await screen.findByText(/No profile yet/i)
    // role queries skip `hidden` panels — the search/filter headings exist in
    // the DOM but are not exposed while Profile is active.
    expect(screen.queryByRole('heading', { name: 'Search targeting' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Work constraints' })).not.toBeInTheDocument()
  })

  it('reveals targeting sections on Search Targeting', async () => {
    stubFetch({ getSettings: ONBOARDING_SETTINGS })
    renderPage()
    await screen.findByText(/No profile yet/i)
    fireEvent.click(screen.getByRole('button', { name: 'Search Targeting' }))
    expect(screen.getByRole('heading', { name: 'Search targeting' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Keywords' })).toBeInTheDocument()
    // Filters live under a different tab.
    expect(screen.queryByRole('heading', { name: 'Work constraints' })).not.toBeInTheDocument()
  })

  it('reveals filters + policy preview on Filters & Policies', async () => {
    stubFetch({ getSettings: ONBOARDING_SETTINGS })
    renderPage()
    await screen.findByText(/No profile yet/i)
    fireEvent.click(screen.getByRole('button', { name: 'Filters & Policies' }))
    expect(screen.getByRole('heading', { name: 'Work constraints' })).toBeInTheDocument()
    // One Save persists the whole search config from either search tab.
    expect(screen.getByRole('button', { name: /Save search config/i })).toBeInTheDocument()
  })

  it('shows signed-in account context on Account & Activity', async () => {
    vi.spyOn(auth, 'fetchPrincipal').mockResolvedValue({
      userId: 'u1',
      userDetails: 'me@example.com',
      userRoles: ['authenticated'],
    })
    stubFetch({ getSettings: ONBOARDING_SETTINGS })
    renderPage()
    await screen.findByText(/No profile yet/i)
    fireEvent.click(screen.getByRole('button', { name: 'Account & Activity' }))
    expect(await screen.findByText('me@example.com')).toBeInTheDocument()
    expect(screen.getByText(/stops future overnight runs/i)).toBeInTheDocument()
  })
})
