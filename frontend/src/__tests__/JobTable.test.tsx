import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { SnackbarProvider } from '../components/ui/snackbar'
import JobTable from '../components/JobTable'
import { DEFAULT_SORT, type SortState } from '../lib/sort'
import type { Application, JobSummary } from '../types'

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

function renderJobTable(
  applications?: Map<string, Application>,
  overrides?: {
    items?: JobSummary[]
    page?: number
    total?: number
    sort?: SortState
    onSortChange?: (next: SortState) => void
    onSelect?: (hash: string) => void
  },
) {
  return render(
    <JobTable
      items={overrides?.items ?? [JOB]}
      visibleColumns={
        new Set(['fit_score', 'title', 'company', 'location', 'salary_min_usd', 'posted_at'])
      }
      onSelect={overrides?.onSelect ?? vi.fn()}
      applications={applications}
      page={overrides?.page ?? 0}
      pageSize={50}
      total={overrides?.total ?? 1}
      onPageChange={vi.fn()}
      sort={overrides?.sort ?? DEFAULT_SORT}
      onSortChange={overrides?.onSortChange ?? vi.fn()}
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

  it('ranks rows by absolute position across pages (page * pageSize + offset)', () => {
    // Server returns one page already ordered; the first row on page 1 is the
    // 51st overall result, so its rank must read 51 — not 1.
    renderJobTable(undefined, { items: [JOB], page: 1, total: 120 })

    const rankCell = screen.getByText('Example Role').closest('tr')?.querySelector('td')
    expect(rankCell?.textContent).toBe('51')
  })

  it('swipes a row left to Trash (passed) and right to Shortlist (maybe)', async () => {
    const { unmount } = renderJobTable()
    swipeRow(screen.getByText('Example Role').closest('tr')!, -120)
    await waitFor(() => expect(applicationPosts()).toHaveLength(1))
    expect(applicationPosts()[0]?.[1]).toMatchObject({
      body: JSON.stringify({ dedup_hash: 'hash-a', status: 'passed' }),
    })
    unmount()
    vi.mocked(fetch).mockClear()

    renderJobTable()
    swipeRow(screen.getByText('Example Role').closest('tr')!, 120)
    await waitFor(() => expect(applicationPosts()).toHaveLength(1))
    expect(applicationPosts()[0]?.[1]).toMatchObject({
      body: JSON.stringify({ dedup_hash: 'hash-a', status: 'maybe' }),
    })
  })

  it('does not triage when the drag stays under the commit threshold', () => {
    renderJobTable()
    swipeRow(screen.getByText('Example Role').closest('tr')!, -20)
    expect(applicationPosts()).toHaveLength(0)
  })

  it('opens the detail panel on a tap but not after a horizontal swipe', () => {
    const onSelect = vi.fn()
    renderJobTable(undefined, { onSelect })
    const row = () => screen.getByText('Example Role').closest('tr')!

    // A plain tap (no movement) selects the row.
    fireEvent.pointerDown(row(), { pointerId: 1, pointerType: 'touch', clientX: 100, clientY: 80 })
    fireEvent.pointerUp(row(), { pointerId: 1, pointerType: 'touch', clientX: 100, clientY: 80 })
    fireEvent.click(row())
    expect(onSelect).toHaveBeenCalledTimes(1)

    // A swipe should not also open the detail panel.
    onSelect.mockClear()
    swipeRow(row(), -120)
    fireEvent.click(row())
    expect(onSelect).not.toHaveBeenCalled()
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

describe('JobTable sorting', () => {
  it('selects a new sort column with its default direction (text → asc)', () => {
    const onSortChange = vi.fn()
    renderJobTable(undefined, { onSortChange })

    fireEvent.click(screen.getByText('Company'))

    expect(onSortChange).toHaveBeenCalledWith({ sort: 'company', order: 'asc' })
  })

  it('toggles direction when the active sort column is clicked again', () => {
    const onSortChange = vi.fn()
    renderJobTable(undefined, { sort: { sort: 'fit_score', order: 'desc' }, onSortChange })

    fireEvent.click(screen.getByText('Score'))

    expect(onSortChange).toHaveBeenCalledWith({ sort: 'fit_score', order: 'asc' })
  })

  it('marks the active sort column with aria-sort', () => {
    renderJobTable(undefined, { sort: { sort: 'company', order: 'asc' } })

    const companyHeader = screen.getByText('Company').closest('th')
    expect(companyHeader).toHaveAttribute('aria-sort', 'ascending')
    expect(screen.getByText('Score').closest('th')).not.toHaveAttribute('aria-sort')
  })

  it('renders a salary range in the Salary column', () => {
    const withSalary: JobSummary = { ...JOB, salary_min_usd: 120000, salary_max_usd: 160000 }
    renderJobTable(undefined, { items: [withSalary] })

    expect(screen.getByText('$120–160k')).toBeInTheDocument()
  })
})

describe('JobTable column resize cleanup', () => {
  it('removes the window mouseup listener if unmounted mid-resize', () => {
    const removeSpy = vi.spyOn(window, 'removeEventListener')
    const { container, unmount } = renderJobTable()

    const handle = container.querySelector('.col-resize-handle')
    expect(handle).not.toBeNull()
    // Begin a resize: this registers a window 'mouseup' listener that would
    // normally self-remove on release. We unmount before release instead.
    fireEvent.mouseDown(handle!)
    unmount()

    expect(removeSpy).toHaveBeenCalledWith('mouseup', expect.any(Function))
  })
})

function swipeRow(row: HTMLElement, deltaX: number) {
  const startX = 200
  const opts = { pointerId: 1, pointerType: 'touch', clientY: 100 }
  fireEvent.pointerDown(row, { ...opts, clientX: startX })
  fireEvent.pointerMove(row, { ...opts, clientX: startX + deltaX })
  fireEvent.pointerUp(row, { ...opts, clientX: startX + deltaX })
}

function applicationPosts() {
  return vi
    .mocked(fetch)
    .mock.calls.filter(
      ([url, init]) => String(url) === '/api/applications' && init?.method === 'POST',
    )
}
