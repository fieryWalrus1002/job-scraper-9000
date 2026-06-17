/**
 * True when a keyboard event targets an element that owns text entry, so
 * single-key shortcuts must stand down rather than hijack the keystroke.
 */
export function isEditableTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable
}

/** Minimal shape shared by DOM and React keyboard events. */
interface KeyLike {
  key: string
  ctrlKey: boolean
  metaKey: boolean
  altKey: boolean
  target: EventTarget | null
}

/**
 * True for a bare `q` we should treat as "quit this panel" — the keyboard twin
 * of Escape. Stands down for modifier chords and text entry (so `q` still types).
 */
export function isQuitKey(e: KeyLike): boolean {
  if (e.key !== 'q' && e.key !== 'Q') return false
  if (e.ctrlKey || e.metaKey || e.altKey) return false
  return !isEditableTarget(e.target)
}
