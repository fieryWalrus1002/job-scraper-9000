import { useEffect, useState } from 'react'
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

  // Re-subscribed when count/focus/callbacks change so the handler always closes
  // over live values (no stale closure); attaching one document listener is cheap.
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      // Leave browser/OS chords and text entry alone, and don't steal keys while
      // a modal (e.g. Add job) owns the screen.
      if (e.ctrlKey || e.metaKey || e.altKey) return
      if (isEditableTarget(e.target)) return
      if (document.querySelector('[role="dialog"]')) return
      if (count === 0) return

      switch (e.key) {
        case 'j':
        case 'ArrowDown':
          e.preventDefault()
          setFocusedIndex((i) => Math.min(i < 0 ? 0 : i + 1, count - 1))
          break
        case 'k':
        case 'ArrowUp':
          e.preventDefault()
          setFocusedIndex((i) => Math.max(i < 0 ? 0 : i - 1, 0))
          break
        case 't':
          if (focusedIndex >= 0) {
            e.preventDefault()
            onTrash(focusedIndex)
          }
          break
        case 's':
          if (focusedIndex >= 0) {
            e.preventDefault()
            onShortlist(focusedIndex)
          }
          break
        case 'Enter':
          if (focusedIndex >= 0) {
            e.preventDefault()
            onOpen(focusedIndex)
          }
          break
      }
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [count, focusedIndex, onTrash, onShortlist, onOpen])

  return { focusedIndex }
}
