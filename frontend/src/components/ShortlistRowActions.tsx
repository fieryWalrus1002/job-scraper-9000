import { useTriageAction } from '../hooks/useTriage'
import { QuickActions } from './ui/quick-actions'
import type { Application } from '../types'

/**
 * Row-level decision-queue actions for the Shortlist tab: a job here is always a
 * `maybe`, so both moves are a status PATCH — Pursue → `to_apply` (promotes into
 * Tracking), Trash → `passed`. Back-to-Jobs lives in the detail panel; the spec
 * keeps the row a pure two-choice queue. Both moves are undoable via the snackbar.
 */
export function ShortlistRowActions({ application }: { application: Application }) {
  const { triage, isPending } = useTriageAction()
  const dedupHash = application.dedup_hash
  const from = application.status

  return (
    <QuickActions
      aria-label="Shortlist actions"
      size="xs"
      actions={[
        {
          id: 'trash',
          label: 'Trash',
          variant: 'danger',
          disabled: isPending,
          onSelect: () => triage({ dedupHash, from, to: 'passed' }),
        },
        {
          id: 'pursue',
          label: 'Pursue',
          variant: 'success',
          disabled: isPending,
          onSelect: () => triage({ dedupHash, from, to: 'to_apply' }),
        },
      ]}
    />
  )
}
