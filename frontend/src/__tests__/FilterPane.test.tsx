import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import FilterPane from '../components/FilterPane'
import { EMPTY_FILTERS } from '../lib/filters'

function renderPane(onFiltersChange = vi.fn()) {
  render(
    <FilterPane
      filters={EMPTY_FILTERS}
      onFiltersChange={onFiltersChange}
      visibleColumns={new Set()}
      onToggleColumn={vi.fn()}
      total={0}
    />,
  )
  return onFiltersChange
}

describe('FilterPane search debounce', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('updates the input immediately but defers the URL write until typing settles', () => {
    const onFiltersChange = renderPane()
    const input = screen.getByPlaceholderText('title, company…')

    fireEvent.change(input, { target: { value: 'eng' } })
    fireEvent.change(input, { target: { value: 'engineer' } })

    // Input is controlled locally and responds instantly.
    expect((input as HTMLInputElement).value).toBe('engineer')
    // But no commit has fired yet — debounce still pending.
    expect(onFiltersChange).not.toHaveBeenCalled()

    vi.advanceTimersByTime(280)

    // A single committed write with the final value, using replace (not push).
    expect(onFiltersChange).toHaveBeenCalledTimes(1)
    expect(onFiltersChange).toHaveBeenCalledWith(expect.objectContaining({ search: 'engineer' }), {
      replace: true,
    })
  })

  it('does not commit while keystrokes keep arriving inside the debounce window', () => {
    const onFiltersChange = renderPane()
    const input = screen.getByPlaceholderText('title, company…')

    fireEvent.change(input, { target: { value: 'e' } })
    vi.advanceTimersByTime(200)
    fireEvent.change(input, { target: { value: 'en' } })
    vi.advanceTimersByTime(200)
    expect(onFiltersChange).not.toHaveBeenCalled()

    vi.advanceTimersByTime(280)
    expect(onFiltersChange).toHaveBeenCalledTimes(1)
    expect(onFiltersChange).toHaveBeenCalledWith(expect.objectContaining({ search: 'en' }), {
      replace: true,
    })
  })
})
