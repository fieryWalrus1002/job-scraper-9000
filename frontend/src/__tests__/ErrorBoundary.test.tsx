import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { useState } from 'react'
import { ErrorBoundary } from '../components/ErrorBoundary'

function Boom({ message = 'kaboom' }: { message?: string }): never {
  throw new Error(message)
}

afterEach(() => vi.restoreAllMocks())

describe('ErrorBoundary', () => {
  it('renders children when nothing throws', () => {
    render(
      <ErrorBoundary>
        <div>healthy</div>
      </ErrorBoundary>,
    )
    expect(screen.getByText('healthy')).toBeInTheDocument()
  })

  it('shows the fallback with label and message when a child throws', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <ErrorBoundary label="Jobs">
        <Boom message="render exploded" />
      </ErrorBoundary>,
    )
    expect(screen.getByTestId('error-boundary-fallback')).toBeInTheDocument()
    expect(screen.getByText(/Something went wrong in Jobs/)).toBeInTheDocument()
    expect(screen.getByText('render exploded')).toBeInTheDocument()
  })

  it('recovers when "Try again" is clicked and the child no longer throws', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})

    function Toggler() {
      const [broken, setBroken] = useState(true)
      return (
        <ErrorBoundary
          fallback={(_error, reset) => (
            <button
              onClick={() => {
                setBroken(false)
                reset()
              }}
            >
              retry
            </button>
          )}
        >
          {broken ? <Boom /> : <div>recovered</div>}
        </ErrorBoundary>
      )
    }

    render(<Toggler />)
    fireEvent.click(screen.getByText('retry'))
    expect(screen.getByText('recovered')).toBeInTheDocument()
  })

  it('resets when resetKeys change (e.g. route navigation)', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})

    const { rerender } = render(
      <ErrorBoundary resetKeys={['/jobs']}>
        <Boom />
      </ErrorBoundary>,
    )
    expect(screen.getByTestId('error-boundary-fallback')).toBeInTheDocument()

    rerender(
      <ErrorBoundary resetKeys={['/settings']}>
        <div>different route</div>
      </ErrorBoundary>,
    )
    expect(screen.getByText('different route')).toBeInTheDocument()
    expect(screen.queryByTestId('error-boundary-fallback')).not.toBeInTheDocument()
  })
})
