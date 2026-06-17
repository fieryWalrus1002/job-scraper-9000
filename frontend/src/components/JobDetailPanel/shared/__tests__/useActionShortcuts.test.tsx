import { describe, it, expect, vi, afterEach } from 'vitest'
import { act, fireEvent, renderHook } from '@testing-library/react'
import { useActionShortcuts } from '../useActionShortcuts'
import type { DetailAction } from '../DetailActionBar'

function action(over: Partial<DetailAction> & Pick<DetailAction, 'id'>): DetailAction {
  return { label: over.id, onSelect: vi.fn(), ...over }
}

const press = (key: string, opts: KeyboardEventInit = {}, target?: Element) =>
  act(() => {
    fireEvent.keyDown(target ?? document.body, { key, ...opts })
  })

afterEach(() => {
  document.querySelectorAll('[data-shortcuts-overlay]').forEach((el) => el.remove())
  vi.restoreAllMocks()
})

describe('useActionShortcuts', () => {
  it('fires the action whose shortcut matches, case-insensitively', () => {
    const trash = action({ id: 'trash', shortcut: 'T' })
    const shortlist = action({ id: 'shortlist', shortcut: 'S' })
    renderHook(() => useActionShortcuts([trash, shortlist]))

    press('t')
    expect(trash.onSelect).toHaveBeenCalledTimes(1)
    expect(shortlist.onSelect).not.toHaveBeenCalled()

    press('S')
    expect(shortlist.onSelect).toHaveBeenCalledTimes(1)
  })

  it('ignores keys with no matching shortcut and disabled actions', () => {
    const pursue = action({ id: 'pursue', shortcut: 'P', disabled: true })
    renderHook(() => useActionShortcuts([pursue]))

    press('x') // no such shortcut
    press('p') // matches but disabled
    expect(pursue.onSelect).not.toHaveBeenCalled()
  })

  it('stands down for modifier chords and editable targets', () => {
    const trash = action({ id: 'trash', shortcut: 'T' })
    renderHook(() => useActionShortcuts([trash]))

    press('t', { ctrlKey: true })
    const input = document.createElement('input')
    document.body.appendChild(input)
    press('t', {}, input)
    expect(trash.onSelect).not.toHaveBeenCalled()
    input.remove()
  })

  it('stands down while the shortcuts reference overlay is open', () => {
    const trash = action({ id: 'trash', shortcut: 'T' })
    renderHook(() => useActionShortcuts([trash]))

    const overlay = document.createElement('div')
    overlay.setAttribute('data-shortcuts-overlay', '')
    document.body.appendChild(overlay)

    press('t')
    expect(trash.onSelect).not.toHaveBeenCalled()
  })
})
