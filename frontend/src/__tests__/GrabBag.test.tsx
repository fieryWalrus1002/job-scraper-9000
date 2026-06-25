import { describe, it, expect, vi, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { GrabBagView } from '../components/GrabBagView'
import { SnackbarProvider } from '../components/ui/snackbar'
import type { JobSummary } from '../types'

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeWrapper(initialEntries?: string[]) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={initialEntries ?? ['/grab-bag']}>
        <SnackbarProvider>{children}</SnackbarProvider>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

function makeJobs(items: Partial<JobSummary>[]): JobSummary[] {
  return items.map((j, i) => ({
    dedup_hash: `hash-${i}`,
    source: 'indeed',
    source_url: null,
    title: j.title ?? `Job ${i}`,
    company: j.company ?? `Company ${i}`,
    location: j.location ?? null,
    posted_at: null,
    remote_classification: j.remote_classification ?? 'fully_remote',
    salary_min_usd: j.salary_min_usd ?? null,
    salary_max_usd: j.salary_max_usd ?? null,
    salary_period: null,
    fit_score: j.fit_score ?? 4,
    confidence: null,
    score_rationale: null,
    failure_reason: null,
    scored_at: null,
  }))
}

function batch(items: Partial<JobSummary>[], total = items.length) {
  return { total, limit: 20, offset: 0, items: makeJobs(items) }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status })
}

/**
 * Route `fetch` by URL + method instead of by call order.
 *
 * `GrabBagView` fires the applications query *and* the grab-bag query, and a
 * triage POST invalidates the applications query (a third call). A sequential
 * `mockResolvedValueOnce` chain therefore desyncs — the applications body gets
 * consumed as the grab-bag response and the view renders "caught up". Routing by
 * URL is order-independent.
 *
 * `grabbag` may be one batch or an array of batches handed out in succession (for
 * the reroll test). A triage POST mutates an internal map so the follow-up
 * applications GET reflects the new row and the card drops from the batch.
 */
function installFetch({
  grabbag,
  applications = [],
}: {
  grabbag: ReturnType<typeof batch> | ReturnType<typeof batch>[]
  applications?: { dedup_hash: string; status: string }[]
}) {
  const batches = Array.isArray(grabbag) ? [...grabbag] : [grabbag]
  const triaged = new Map(applications.map((a) => [a.dedup_hash, a]))

  const fetchMock = vi.fn((url: string | URL, init?: RequestInit) => {
    const u = String(url)
    const method = init?.method ?? 'GET'

    if (u.includes('mode=grabbag')) {
      const next = batches.length > 1 ? batches.shift()! : batches[0]
      return Promise.resolve(jsonResponse(next))
    }

    if (u.includes('/api/applications')) {
      if (method === 'POST') {
        const sent = JSON.parse(String(init?.body ?? '{}'))
        const row = {
          dedup_hash: sent.dedup_hash,
          status: sent.status,
          applied_at: null,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
          title: sent.title ?? '',
          company: sent.company ?? '',
          source_url: null,
          fit_score: sent.fit_score ?? null,
          latest_event: null,
        }
        triaged.set(sent.dedup_hash, row)
        return Promise.resolve(jsonResponse(row))
      }
      return Promise.resolve(jsonResponse([...triaged.values()]))
    }

    return Promise.resolve(jsonResponse({}))
  })

  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function apiCalls() {
  return vi.mocked(fetch).mock.calls
}

function grabBagCalls() {
  return apiCalls().filter(([url]) => String(url).includes('mode=grabbag'))
}

function applicationPosts() {
  return apiCalls().filter(
    ([url, init]) =>
      String(url).includes('/api/applications') &&
      (init as RequestInit | undefined)?.method === 'POST',
  )
}

function seedOf(url: unknown): string | null {
  return new URL(String(url), 'http://test').searchParams.get('seed')
}

function swipeCard(card: Element, deltaX: number) {
  const startX = 200
  const opts = { pointerId: 1, pointerType: 'touch', clientY: 100 }
  fireEvent.pointerDown(card, { ...opts, clientX: startX })
  fireEvent.pointerMove(card, { ...opts, clientX: startX + deltaX })
  fireEvent.pointerUp(card, { ...opts, clientX: startX + deltaX })
}

function cardFor(title: string): Element {
  return screen.getByText(title).closest('[class*="relative"]')!
}

// ── Tests ────────────────────────────────────────────────────────────────────

afterEach(() => vi.unstubAllGlobals())

describe('GrabBagView — render batch', () => {
  it('renders cards from a mocked mode=grabbag response', async () => {
    installFetch({
      grabbag: batch([
        { title: 'Senior Engineer', company: 'TechCo', fit_score: 5 },
        { title: 'Staff SWE', company: 'StartupX', fit_score: 4 },
      ]),
    })

    render(<GrabBagView onSelect={vi.fn()} />, { wrapper: makeWrapper() })

    await waitFor(() => expect(screen.getByText('Senior Engineer')).toBeInTheDocument())
    expect(screen.getByText('TechCo')).toBeInTheDocument()
    expect(screen.getByText('Staff SWE')).toBeInTheDocument()
    expect(screen.getByText('StartupX')).toBeInTheDocument()

    // The endpoint was hit with mode=grabbag and a seed.
    expect(grabBagCalls()).toHaveLength(1)
    const [url] = grabBagCalls()[0]
    expect(String(url)).toContain('mode=grabbag')
    expect(seedOf(url)).not.toBeNull()
  })
})

describe('GrabBagView — New batch reroll', () => {
  it('"New batch" changes the seed and refetches', async () => {
    installFetch({
      grabbag: [
        batch([{ title: 'Job A', company: 'Co A', fit_score: 4 }]),
        batch([{ title: 'Job B', company: 'Co B', fit_score: 3 }]),
      ],
    })

    render(<GrabBagView onSelect={vi.fn()} />, { wrapper: makeWrapper() })

    await waitFor(() => expect(screen.getByText('Job A')).toBeInTheDocument())

    fireEvent.click(screen.getByText('New batch'))

    await waitFor(() => expect(grabBagCalls()).toHaveLength(2), { timeout: 2000 })
    // Reroll picks a fresh seed.
    expect(seedOf(grabBagCalls()[1][0])).not.toBe(seedOf(grabBagCalls()[0][0]))

    await waitFor(() => expect(screen.getByText('Job B')).toBeInTheDocument(), { timeout: 2000 })
  })
})

describe('GrabBagView — swipe triage removes card', () => {
  it('a committed left swipe issues a passed triage and removes the card', async () => {
    installFetch({ grabbag: batch([{ title: 'Swipeable Job', company: 'SwipeCo', fit_score: 4 }]) })

    render(<GrabBagView onSelect={vi.fn()} />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Swipeable Job')).toBeInTheDocument())

    swipeCard(cardFor('Swipeable Job'), -120)

    await waitFor(() => expect(applicationPosts()).toHaveLength(1), { timeout: 2000 })
    const [, init] = applicationPosts()[0]
    expect((init as RequestInit).method).toBe('POST')
    expect(String((init as RequestInit).body)).toContain('passed')

    // The triaged card leaves the batch → caught-up state appears.
    await waitFor(() => expect(screen.queryByText('Swipeable Job')).toBeNull(), { timeout: 2000 })
  })

  it('a committed right swipe issues a shortlist (maybe) triage', async () => {
    installFetch({ grabbag: batch([{ title: 'Shortlist Job', company: 'ShortCo', fit_score: 5 }]) })

    render(<GrabBagView onSelect={vi.fn()} />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Shortlist Job')).toBeInTheDocument())

    swipeCard(cardFor('Shortlist Job'), 120)

    await waitFor(() => expect(applicationPosts()).toHaveLength(1), { timeout: 2000 })
    const [, init] = applicationPosts()[0]
    expect((init as RequestInit).method).toBe('POST')
    expect(String((init as RequestInit).body)).toContain('maybe')
  })
})

describe('GrabBagView — caught-up empty state', () => {
  it('renders "All caught up" when items is empty', async () => {
    installFetch({ grabbag: batch([], 0) })

    render(<GrabBagView onSelect={vi.fn()} />, { wrapper: makeWrapper() })

    await waitFor(() => expect(screen.getByText('All caught up!')).toBeInTheDocument())
    // "New batch" stays available so the user can reroll out of an empty bag.
    expect(screen.getByText('New batch')).toBeInTheDocument()
  })
})

describe('GrabBagView — swipe affordance pills', () => {
  it('right-drag shows the "Shortlist" pill', async () => {
    installFetch({ grabbag: batch([{ title: 'Pill Job', company: 'PillCo', fit_score: 4 }]) })

    render(<GrabBagView onSelect={vi.fn()} />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Pill Job')).toBeInTheDocument())

    const card = cardFor('Pill Job')
    const opts = { pointerId: 1, pointerType: 'touch', clientY: 100 }
    fireEvent.pointerDown(card, { ...opts, clientX: 200 })
    fireEvent.pointerMove(card, { ...opts, clientX: 320 })

    expect(screen.queryByText('Shortlist')).not.toBeNull()
  })

  it('left-drag shows the "Trash" pill', async () => {
    installFetch({ grabbag: batch([{ title: 'Pill Job', company: 'PillCo', fit_score: 4 }]) })

    render(<GrabBagView onSelect={vi.fn()} />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Pill Job')).toBeInTheDocument())

    const card = cardFor('Pill Job')
    const opts = { pointerId: 1, pointerType: 'touch', clientY: 100 }
    fireEvent.pointerDown(card, { ...opts, clientX: 200 })
    fireEvent.pointerMove(card, { ...opts, clientX: 80 })

    expect(screen.queryByText('Trash')).not.toBeNull()
  })
})

describe('GrabBagView — tap opens detail panel', () => {
  it('a tap (not a swipe) calls onSelect with the grabbag surface', async () => {
    installFetch({ grabbag: batch([{ title: 'Tap Job', company: 'TapCo', fit_score: 4 }]) })

    const onSelect = vi.fn()
    render(<GrabBagView onSelect={onSelect} />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByText('Tap Job')).toBeInTheDocument())

    fireEvent.click(cardFor('Tap Job'))

    expect(onSelect).toHaveBeenCalledWith(
      'hash-0',
      'grabbag',
      undefined,
      expect.objectContaining({ dedup_hash: 'hash-0', title: 'Tap Job' }),
    )
  })
})
