import { useEffect } from 'react'
import { isEditableTarget } from '@/lib/keyboard'
import type { DetailAction } from './DetailActionBar'

/**
 * Wires the single-key shortcuts a detail surface already advertises on its
 * action chips (e.g. `T` trash, `S` shortlist, `P` pursue) to the matching
 * action. Each surface passes only the actions that make sense there, so the
 * live shortcut set is automatically scoped to the tab you're on.
 *
 * Mounted inside {@link DetailActionBar}, which only exists while a job detail is
 * open, so the listener's lifetime is the panel's. A press matches an action's
 * `shortcut` case-insensitively and fires it unless that action is disabled
 * (e.g. a mutation in flight). It stands down while text entry or the shortcuts
 * reference overlay is on top.
 */
export function useActionShortcuts(actions: DetailAction[]) {
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.ctrlKey || e.metaKey || e.altKey) return
      if (isEditableTarget(e.target)) return
      // The `?` reference overlay sits above the panel; don't fire underneath it.
      if (document.querySelector('[data-shortcuts-overlay]')) return

      const key = e.key.toLowerCase()
      const action = actions.find((a) => a.shortcut?.toLowerCase() === key && !a.disabled)
      if (action) {
        e.preventDefault()
        action.onSelect()
      }
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [actions])
}
