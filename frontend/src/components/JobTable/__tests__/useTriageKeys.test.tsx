import { describe, it, expect, vi, afterEach } from 'vitest'
import { act, fireEvent, renderHook } from '@testing-library/react'
import { useTriageKeys } from '../useTriageKeys'

function setup(count = 3) {
  const onTrash = vi.fn()
  const onShortlist = vi.fn()
  const onOpen = vi.fn()
  const view = renderHook(({ count }) => useTriageKeys({ count, onTrash, onShortlist, onOpen }), {
    initialProps: { count },
  })
  return { ...view, onTrash, onShortlist, onOpen }
}

const press = (key: string, target?: Element) =>
  act(() => {
    fireEvent.keyDown(target ?? document.body, { key })
  })

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useTriageKeys', () => {
  it('starts dormant and action keys are no-ops until a row is focused', () => {
    const { result, onTrash, onShortlist } = setup()
    expect(result.current.focusedIndex).toBe(-1)

    press('t')
    press('s')
    expect(onTrash).not.toHaveBeenCalled()
    expect(onShortlist).not.toHaveBeenCalled()
    expect(result.current.focusedIndex).toBe(-1)
  })

  it('moves the cursor with j/k and arrows, clamped to the ends', () => {
    const { result } = setup(3)

    press('ArrowDown') // -1 -> 0
    expect(result.current.focusedIndex).toBe(0)
    press('j') // 0 -> 1
    press('j') // 1 -> 2
    press('j') // clamps at last row
    expect(result.current.focusedIndex).toBe(2)

    press('k') // 2 -> 1
    press('ArrowUp') // 1 -> 0
    press('k') // clamps at 0
    expect(result.current.focusedIndex).toBe(0)
  })

  it('trashes / shortlists / opens the focused row', () => {
    const { onTrash, onShortlist, onOpen } = setup()

    press('ArrowDown') // focus row 0
    press('j') // focus row 1
    press('t')
    press('s')
    press('Enter')

    expect(onTrash).toHaveBeenCalledWith(1)
    expect(onShortlist).toHaveBeenCalledWith(1)
    expect(onOpen).toHaveBeenCalledWith(1)
  })

  it('acts on the latest cursor when nav + action fire back-to-back', () => {
    // All three keys dispatch inside one act() — i.e. before a re-subscribing
    // effect could refresh the closure. The handler must still trash row 1, not
    // the dormant/previous cursor. Guards the stale-closure regression.
    const { onTrash } = setup()
    act(() => {
      fireEvent.keyDown(document.body, { key: 'ArrowDown' }) // -> 0
      fireEvent.keyDown(document.body, { key: 'j' }) // -> 1
      fireEvent.keyDown(document.body, { key: 't' }) // act on 1
    })
    expect(onTrash).toHaveBeenCalledWith(1)
  })

  it('keeps the cursor on the row that slides up as the feed shrinks', () => {
    const { result, rerender } = setup(3)
    press('ArrowDown')
    press('j') // focus row 1
    expect(result.current.focusedIndex).toBe(1)

    rerender({ count: 2 }) // row dropped out; cursor still valid
    expect(result.current.focusedIndex).toBe(1)

    rerender({ count: 1 }) // now out of range; snaps to last row
    expect(result.current.focusedIndex).toBe(0)
  })

  it('ignores keystrokes from editable targets', () => {
    const { result, onTrash } = setup()
    const input = document.createElement('input')
    document.body.appendChild(input)

    press('ArrowDown', input)
    press('t', input)
    expect(result.current.focusedIndex).toBe(-1)
    expect(onTrash).not.toHaveBeenCalled()

    input.remove()
  })

  it('does not steal keys while a modal dialog is open', () => {
    const { result, onTrash } = setup()
    press('ArrowDown') // focus row 0

    const dialog = document.createElement('div')
    dialog.setAttribute('role', 'dialog')
    document.body.appendChild(dialog)

    press('t')
    press('j')
    expect(onTrash).not.toHaveBeenCalled()
    expect(result.current.focusedIndex).toBe(0)

    dialog.remove()
  })
})
