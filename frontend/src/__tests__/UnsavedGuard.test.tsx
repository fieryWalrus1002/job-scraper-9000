import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { UnsavedGuardProvider, useUnsavedGuard } from '../components/UnsavedGuard'

/** A tiny consumer: a checkbox arms the guard, a button requests navigation. */
function Harness({ proceed }: { proceed: () => void }) {
  const { setBlocked, requestNavigation } = useUnsavedGuard()
  return (
    <div>
      <label>
        <input type="checkbox" onChange={(e) => setBlocked(e.target.checked)} />
        block
      </label>
      <button onClick={() => requestNavigation(proceed)}>go</button>
    </div>
  )
}

function renderHarness(proceed: () => void) {
  return render(
    <UnsavedGuardProvider>
      <Harness proceed={proceed} />
    </UnsavedGuardProvider>,
  )
}

describe('UnsavedGuard', () => {
  it('navigates immediately when not blocked', () => {
    const proceed = vi.fn()
    renderHarness(proceed)
    fireEvent.click(screen.getByText('go'))
    expect(proceed).toHaveBeenCalledTimes(1)
    expect(screen.queryByText(/Discard unsaved changes/i)).not.toBeInTheDocument()
  })

  it('confirms before navigating when blocked, and proceeds on discard', () => {
    const proceed = vi.fn()
    renderHarness(proceed)
    fireEvent.click(screen.getByLabelText('block'))
    fireEvent.click(screen.getByText('go'))

    expect(screen.getByText(/Discard unsaved changes/i)).toBeInTheDocument()
    expect(proceed).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: /Discard changes/i }))
    expect(proceed).toHaveBeenCalledTimes(1)
  })

  it('cancels navigation on keep-editing', () => {
    const proceed = vi.fn()
    renderHarness(proceed)
    fireEvent.click(screen.getByLabelText('block'))
    fireEvent.click(screen.getByText('go'))
    fireEvent.click(screen.getByRole('button', { name: /Keep editing/i }))

    expect(proceed).not.toHaveBeenCalled()
    expect(screen.queryByText(/Discard unsaved changes/i)).not.toBeInTheDocument()
  })

  it('falls back to immediate navigation outside a provider', () => {
    const proceed = vi.fn()
    render(<Harness proceed={proceed} />)
    fireEvent.click(screen.getByText('go'))
    expect(proceed).toHaveBeenCalledTimes(1)
  })
})
