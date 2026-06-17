import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { logMutationError } from '../lib/mutations'
import { MutationError } from '../components/JobDetailPanel/shared/MutationError'

afterEach(() => vi.restoreAllMocks())

describe('logMutationError', () => {
  it('returns a handler that logs the labelled error', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const err = new Error('boom')
    logMutationError('mark application')(err)
    expect(spy).toHaveBeenCalledWith('Mutation failed: mark application', err)
  })
})

describe('MutationError', () => {
  it('renders nothing when there is no error', () => {
    const { container } = render(<MutationError error={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders the message from an Error as an alert', () => {
    render(<MutationError error={new Error('Save failed')} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Save failed')
  })

  it('stringifies non-Error values', () => {
    render(<MutationError error="plain string failure" />)
    expect(screen.getByRole('alert')).toHaveTextContent('plain string failure')
  })
})
