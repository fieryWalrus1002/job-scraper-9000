import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { SnackbarProvider } from '../components/ui/snackbar'
import { useTriageAction, type TriageMove } from '../hooks/useTriage'

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

function TriageProbe({ move }: { move: TriageMove }) {
  const { triage } = useTriageAction()
  return (
    <button type="button" onClick={() => triage(move)}>
      go
    </button>
  )
}

interface ParsedCall {
  url: string
  method: string
  body: Record<string, unknown> | undefined
}

function fetchCalls(): ParsedCall[] {
  const mock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
  return mock.mock.calls.map(([url, opts]) => ({
    url: String(url),
    method: (opts as RequestInit | undefined)?.method ?? 'GET',
    body: (opts as RequestInit | undefined)?.body
      ? JSON.parse((opts as RequestInit).body as string)
      : undefined,
  }))
}

beforeEach(() => {
  // Every triage endpoint just needs an ok response; mark/update read JSON back.
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ dedup_hash: 'hash-a' }), { status: 200 })),
  )
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

async function runMoveThenUndo(move: TriageMove) {
  render(<TriageProbe move={move} />, { wrapper: makeWrapper() })
  fireEvent.click(screen.getByText('go'))
  // Forward fired and the undo snackbar is on screen.
  await waitFor(() => expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument())
  const forward = [...fetchCalls()]
  fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
  await waitFor(() => expect(fetchCalls().length).toBeGreaterThan(forward.length))
  const inverse = fetchCalls().slice(forward.length)
  return { forward, inverse }
}

describe('useTriageAction undo', () => {
  it('Trash from Jobs (no row → passed): creates the row, undo deletes it', async () => {
    const { forward, inverse } = await runMoveThenUndo({
      dedupHash: 'hash-a',
      from: null,
      to: 'passed',
    })

    expect(forward).toContainEqual(
      expect.objectContaining({
        method: 'POST',
        url: expect.stringMatching(/\/api\/applications$/),
        body: expect.objectContaining({ status: 'passed' }),
      }),
    )
    expect(inverse).toContainEqual(
      expect.objectContaining({ method: 'DELETE', url: expect.stringMatching(/hash-a$/) }),
    )
  })

  it('Pursue (maybe → to_apply): patches forward, undo patches back to maybe', async () => {
    const { forward, inverse } = await runMoveThenUndo({
      dedupHash: 'hash-a',
      from: 'maybe',
      to: 'to_apply',
    })

    expect(forward).toContainEqual(
      expect.objectContaining({ method: 'PATCH', body: { status: 'to_apply' } }),
    )
    expect(inverse).toContainEqual(
      expect.objectContaining({ method: 'PATCH', body: { status: 'maybe' } }),
    )
  })

  it('Un-trash (passed → remove): deletes the row, undo recreates it with prior notes', async () => {
    const { forward, inverse } = await runMoveThenUndo({
      dedupHash: 'hash-a',
      from: 'passed',
      to: 'remove',
      restoreNotes: 'kept these notes',
    })

    expect(forward).toContainEqual(expect.objectContaining({ method: 'DELETE' }))
    expect(inverse).toContainEqual(
      expect.objectContaining({
        method: 'POST',
        body: expect.objectContaining({ status: 'passed', notes: 'kept these notes' }),
      }),
    )
  })

  it('shows the outcome message for the move', async () => {
    render(<TriageProbe move={{ dedupHash: 'hash-a', from: null, to: 'maybe' }} />, {
      wrapper: makeWrapper(),
    })
    fireEvent.click(screen.getByText('go'))
    await waitFor(() => expect(screen.getByText('Shortlisted')).toBeInTheDocument())
  })

  it('shows no undo affordance when the forward move fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(new Response('Bad Request', { status: 400, statusText: 'Bad Request' })),
    )
    vi.spyOn(console, 'error').mockImplementation(() => {}) // mutation logs loudly; keep test output clean

    render(<TriageProbe move={{ dedupHash: 'hash-a', from: null, to: 'passed' }} />, {
      wrapper: makeWrapper(),
    })
    fireEvent.click(screen.getByText('go'))

    await waitFor(() => expect(fetchCalls()).toHaveLength(1))
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument()
  })
})
