import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import SearchForm from '../components/settings/SearchForm'
import type { SearchConfigInput } from '../types'

function renderForm(props: React.ComponentProps<typeof SearchForm>) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <SearchForm {...props} />
    </QueryClientProvider>,
  )
}

const EXISTING: SearchConfigInput = {
  user: { display_name: 'Dev', email: 'dev@localhost', home_location: null },
  search_profile: { name: 'default', status: 'active', goal_summary: '', search_mode: 'balanced' },
  roles: {
    target_titles: { preferred: ['Software Engineer'], exploratory: [] },
    excluded_titles: ['Sales Engineer'],
  },
}

describe('SearchForm', () => {
  beforeEach(() => vi.unstubAllGlobals())

  it('shows onboarding state with no config', () => {
    renderForm({ initial: null, policies: null })
    expect(screen.getByText(/No search config yet/i)).toBeInTheDocument()
  })

  it('seeds from an existing config', () => {
    renderForm({ initial: EXISTING, policies: null })
    expect(screen.getByDisplayValue('Software Engineer')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Sales Engineer')).toBeInTheDocument()
    expect(screen.queryByText(/No search config yet/i)).not.toBeInTheDocument()
  })

  it('submits a well-formed payload and shows derived policies', async () => {
    let sentBody: SearchConfigInput | null = null
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, opts?: RequestInit) => {
        if (url.endsWith('/api/settings/search') && opts?.method === 'PUT') {
          sentBody = JSON.parse(opts.body as string) as SearchConfigInput
          return Promise.resolve(
            new Response(
              JSON.stringify({
                policies: { prefilter: { excluded_title_terms: ['Sales Engineer'] } },
                updated_at: '2026-06-11T00:00:00Z',
              }),
              { status: 200 },
            ),
          )
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      }),
    )

    renderForm({ initial: EXISTING, policies: null })
    fireEvent.click(screen.getByRole('button', { name: /Save search config/i }))

    await waitFor(() => expect(sentBody).not.toBeNull())
    // Newline-list fields and nested structure survive the round-trip.
    expect(sentBody!.roles.target_titles.preferred).toEqual(['Software Engineer'])
    expect(sentBody!.roles.excluded_titles).toEqual(['Sales Engineer'])
    expect(sentBody!.work_constraints!.work_arrangements!.remote!.acceptable).toBe(true)
    expect(sentBody!.scrape_preferences!.cadence).toBe('daily')

    // The server-derived policies render read-only.
    expect(await screen.findByText(/Derived policies/i)).toBeInTheDocument()
    expect(screen.getByText(/excluded_title_terms/)).toBeInTheDocument()
  })
})
