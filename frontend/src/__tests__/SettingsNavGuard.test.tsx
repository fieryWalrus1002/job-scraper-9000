import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AppHeader } from '../components/AppHeader'
import SettingsPage from '../components/SettingsPage'
import { UnsavedGuardProvider } from '../components/UnsavedGuard'

const ONBOARDING = {
  profile: null,
  profile_version: null,
  profile_updated_at: null,
  search: null,
  policies: null,
  search_updated_at: null,
}

function stubSettings() {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) =>
      url.endsWith('/api/settings')
        ? Promise.resolve(new Response(JSON.stringify(ONBOARDING), { status: 200 }))
        : Promise.reject(new Error(`unexpected fetch: ${url}`)),
    ),
  )
}

function renderApp() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/settings']}>
        <UnsavedGuardProvider>
          <AppHeader
            email="me@example.com"
            counts={{ '/jobs': 0, '/shortlist': 0, '/tracking': 0, '/trash': 0 }}
            onAddJob={() => {}}
            onShowShortcuts={() => {}}
          />
          <Routes>
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/jobs" element={<div>JOBS PAGE</div>} />
          </Routes>
        </UnsavedGuardProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('settings unsaved-changes nav guard', () => {
  beforeEach(() => vi.unstubAllGlobals())

  async function editSummary() {
    stubSettings()
    renderApp()
    const summary = await screen.findByPlaceholderText(/who you are as a candidate/i)
    fireEvent.change(summary, { target: { value: 'A real edit to the summary field.' } })
  }

  it('leaves immediately when there are no unsaved edits', async () => {
    stubSettings()
    renderApp()
    await screen.findByPlaceholderText(/who you are as a candidate/i)
    fireEvent.click(screen.getByRole('link', { name: /Jobs/i }))
    expect(await screen.findByText('JOBS PAGE')).toBeInTheDocument()
  })

  it('confirms before leaving when edits are unsaved, then discards and navigates', async () => {
    await editSummary()
    fireEvent.click(screen.getByRole('link', { name: /Jobs/i }))

    expect(await screen.findByText(/Discard unsaved changes/i)).toBeInTheDocument()
    expect(screen.queryByText('JOBS PAGE')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Discard changes/i }))
    expect(await screen.findByText('JOBS PAGE')).toBeInTheDocument()
  })

  it('stays on settings when the user keeps editing', async () => {
    await editSummary()
    fireEvent.click(screen.getByRole('link', { name: /Jobs/i }))
    fireEvent.click(await screen.findByRole('button', { name: /Keep editing/i }))

    expect(screen.queryByText('JOBS PAGE')).not.toBeInTheDocument()
    // Still on settings with the edit intact.
    expect(screen.getByDisplayValue('A real edit to the summary field.')).toBeInTheDocument()
  })
})
