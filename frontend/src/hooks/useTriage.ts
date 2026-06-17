import { useCallback } from 'react'
import { useDeleteApplication, useMarkApplication, useUpdateApplication } from './useApplications'
import { useSnackbar } from '../components/ui/snackbar'
import type { ApplicationStatus } from '../types'

/** Target of a triage move: a status, or `remove` to clear the row (back to Jobs). */
export type TriageTarget = ApplicationStatus | 'remove'

export interface TriageMove {
  dedupHash: string
  /** Prior status, or `null` when the job had no `user_applications` row (untriaged). */
  from: ApplicationStatus | null
  to: TriageTarget
  /** Snackbar message override; defaults to the outcome for `to` (see triageMessage). */
  label?: string
  /** Notes to restore if undo has to recreate a deleted row (e.g. un-trash). */
  restoreNotes?: string | null
}

/** Default snackbar message for a triage move, phrased as the resulting funnel position. */
export function triageMessage(to: TriageTarget): string {
  switch (to) {
    case 'remove':
      return 'Restored to Jobs'
    case 'passed':
      return 'Moved to Trash'
    case 'maybe':
      return 'Shortlisted'
    case 'to_apply':
      return 'Moved to Tracking'
    default:
      return 'Updated'
  }
}

/**
 * The funnel's single triage primitive. Every quick triage action — Trash,
 * Shortlist, Pursue, Un-trash — goes through here so it gets an undo snackbar for
 * free. Swipe gestures (#354) and the cross-tab reversibility escapes (#356) reuse
 * this same call.
 *
 * Undo is just the inverse move, derived mechanically from `from`/`to`:
 *   - created a row (from === null)        → delete it
 *   - deleted a row (to === 'remove')      → recreate it with the prior status/notes
 *   - patched the status                   → patch back to the prior status
 */
export function useTriageAction() {
  const mark = useMarkApplication()
  const update = useUpdateApplication()
  const del = useDeleteApplication()
  const { show } = useSnackbar()

  const apply = useCallback(
    (move: TriageMove) => {
      const { dedupHash, to, restoreNotes } = move
      if (to === 'remove') {
        del.mutate(dedupHash)
      } else if (move.from === null) {
        mark.mutate({ dedupHash, status: to })
      } else {
        update.mutate({ dedupHash, update: { status: to } })
      }

      const undo = () => {
        if (move.from === null) {
          del.mutate(dedupHash)
        } else if (to === 'remove') {
          mark.mutate({ dedupHash, status: move.from, notes: restoreNotes ?? undefined })
        } else {
          update.mutate({ dedupHash, update: { status: move.from } })
        }
      }

      show({ message: move.label ?? triageMessage(to), action: { label: 'Undo', onClick: undo } })
    },
    [mark, update, del, show],
  )

  const isPending = mark.isPending || update.isPending || del.isPending
  return { triage: apply, isPending }
}
