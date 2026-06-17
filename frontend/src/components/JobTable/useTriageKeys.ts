import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { isEditableTarget } from '../../lib/keyboard'

interface UseTriageKeysArgs {
  /** Number of rows currently in the feed; the cursor clamps to this. */
  count: number
  /** Trash the row at `index` (left-swipe equivalent). */
  onTrash: (index: number) => void
  /** Shortlist the row at `index` (right-swipe equivalent). */
  onShortlist: (index: number) => void
  /** Open the detail panel for the row at `index`. */
  onOpen: (index: number) => void
}

interface UseTriageKeysResult {
  /** Row the keyboard cursor is on, or -1 while dormant (no key pressed yet). */
  focusedIndex: number
}

/**
 * Single-key keyboard triage on the Jobs feed (spec §6.5). Maintains a keyboard
 * "cursor" over the rows — `j`/`↓` and `k`/`↑` move it, `t` trashes, `s`
 * shortlists, `Enter` opens the detail panel — mirroring the swipe transitions
 * (#354) by driving the same triage primitive in the caller.
 *
 * The cursor starts dormant (-1) so mouse users see no change until they press a
 * nav key; action keys are no-ops until a row is focused.
 */
export function useTriageKeys({
  count,
  onTrash,
  onShortlist,
  onOpen,
}: UseTriageKeysArgs): UseTriageKeysResult {
  const [focusedIndex, setFocusedIndex] = useState(-1)

  // Clamp during render (React's guarded setState-in-render pattern, same as the
  // jobs page-clamp in App.tsx) so the cursor never points past the feed as
  // triaged rows drop out; collapsing to empty resets it to dormant (-1).
  if (focusedIndex > count - 1) {
    setFocusedIndex(count - 1)
  }

  // `focusedRef` is the synchronous source of truth the keydown handler reads and
  // writes, so a burst of keys (e.g. `j` then `t` in one tick) always acts on the
  // row the cursor just moved to — never a value stale-closured from React's
  // commit timing. The layout effect reconciles it with committed state (incl. the
  // render clamp above) before the next paint; `liveRef` carries the other inputs.
  const focusedRef = useRef(focusedIndex)
  const liveRef = useRef({ count, onTrash, onShortlist, onOpen })
  useLayoutEffect(() => {
    focusedRef.current = focusedIndex
    liveRef.current = { count, onTrash, onShortlist, onOpen }
  })

  useEffect(() => {
    function setFocused(next: number) {
      focusedRef.current = next
      setFocusedIndex(next)
    }
    function handleKey(e: KeyboardEvent) {
      // Leave browser/OS chords and text entry alone, and don't steal keys while
      // a modal (e.g. Add job) owns the screen.
      if (e.ctrlKey || e.metaKey || e.altKey) return
      if (isEditableTarget(e.target)) return
      if (document.querySelector('[role="dialog"]')) return

      const { count, onTrash, onShortlist, onOpen } = liveRef.current
      if (count === 0) return
      const i = focusedRef.current

      switch (e.key) {
        case 'j':
        case 'ArrowDown':
          e.preventDefault()
          setFocused(Math.min(i < 0 ? 0 : i + 1, count - 1))
          break
        case 'k':
        case 'ArrowUp':
          e.preventDefault()
          setFocused(Math.max(i < 0 ? 0 : i - 1, 0))
          break
        case 't':
          if (i >= 0) {
            e.preventDefault()
            onTrash(i)
          }
          break
        case 's':
          if (i >= 0) {
            e.preventDefault()
            onShortlist(i)
          }
          break
        case 'Enter':
          if (i >= 0) {
            e.preventDefault()
            onOpen(i)
          }
          break
      }
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [])

  return { focusedIndex }
}
