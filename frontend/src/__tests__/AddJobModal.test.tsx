import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import AddJobModal from '../components/AddJobModal'

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
}

// Mirror the component's local-date helper so the default-date assertion is tz-safe.
function todayLocalISO(): string {
  const d = new Date()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd}`
}

vi.mock('../hooks/useApplications')

beforeEach(() => {
  vi.restoreAllMocks()
  // jsdom lacks scrollIntoView — Radix Select calls it on open
  Element.prototype.scrollIntoView = vi.fn()
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(new Response(JSON.stringify([]), { status: 200 })),
  )
})
afterEach(() => vi.unstubAllGlobals())

describe('AddJobModal', () => {
  it('defaults the posted date to today', async () => {
    const { useCreateManualJob } = await import('../hooks/useApplications')
    vi.mocked(useCreateManualJob).mockReturnValue({
      mutateAsync: vi.fn(),
      isPending: false,
    } as never)

    render(<AddJobModal onClose={vi.fn()} onSuccess={vi.fn()} />, { wrapper: makeWrapper() })

    const posted = screen.getByLabelText(/Posted date/) as HTMLInputElement
    expect(posted.value).toBe(todayLocalISO())
  })

  it('submits successfully with today as the posted date and fires onSuccess', async () => {
    const { useCreateManualJob } = await import('../hooks/useApplications')
    const mutateAsync = vi.fn().mockResolvedValue({ dedup_hash: 'manual-1' })
    vi.mocked(useCreateManualJob).mockReturnValue({
      mutateAsync,
      isPending: false,
    } as never)

    const onSuccess = vi.fn()
    const onClose = vi.fn()

    render(<AddJobModal onClose={onClose} onSuccess={onSuccess} />, {
      wrapper: makeWrapper(),
    })

    // getByLabelText exercises #322's label/control associations.
    fireEvent.change(screen.getByLabelText(/Title/), {
      target: { value: '  Staff Engineer  ' },
    })

    // Open the fit score select and pick 4.
    fireEvent.click(screen.getByLabelText(/Your fit score/))
    fireEvent.click(screen.getByText('4'))

    fireEvent.click(screen.getByRole('button', { name: 'Add job' }))

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1))

    expect(mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Staff Engineer',
        fit_score: 4,
        posted_at: todayLocalISO(),
      }),
    )
  })

  it('shows friendly message on 409 and does not call onSuccess', async () => {
    const { useCreateManualJob } = await import('../hooks/useApplications')
    vi.mocked(useCreateManualJob).mockReturnValue({
      mutateAsync: vi.fn().mockRejectedValue(new Error('409: Job already exists')),
      isPending: false,
    } as never)

    const onSuccess = vi.fn()

    render(<AddJobModal onClose={vi.fn()} onSuccess={onSuccess} />, {
      wrapper: makeWrapper(),
    })

    fireEvent.change(screen.getByLabelText(/Title/), {
      target: { value: 'Engineer' },
    })

    fireEvent.click(screen.getByLabelText(/Your fit score/))
    fireEvent.click(screen.getByText('4'))

    fireEvent.click(screen.getByRole('button', { name: 'Add job' }))

    await waitFor(() =>
      expect(screen.getByText('This job is already in the system.')).toBeInTheDocument(),
    )
    expect(onSuccess).not.toHaveBeenCalled()
  })

  it('shows validation error when fit score is not selected', async () => {
    const { useCreateManualJob } = await import('../hooks/useApplications')
    const mockMutateAsync = vi.fn()
    vi.mocked(useCreateManualJob).mockReturnValue({
      mutateAsync: mockMutateAsync,
      isPending: false,
    } as never)

    render(<AddJobModal onClose={vi.fn()} onSuccess={vi.fn()} />, {
      wrapper: makeWrapper(),
    })

    fireEvent.change(screen.getByLabelText(/Title/), {
      target: { value: 'Engineer' },
    })

    // Submit without picking a fit score
    fireEvent.click(screen.getByRole('button', { name: 'Add job' }))

    expect(screen.getByText('Score is required.')).toBeInTheDocument()
    expect(mockMutateAsync).not.toHaveBeenCalled()
  })
})
