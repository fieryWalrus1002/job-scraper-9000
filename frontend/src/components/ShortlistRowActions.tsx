import { useUpdateApplication } from '../hooks/useApplications'
import { QuickActions } from './ui/quick-actions'
import type { Application } from '../types'

/**
 * Row-level decision-queue actions for the Shortlist tab: a job here is always a
 * `maybe`, so both moves are a status PATCH — Pursue → `to_apply` (promotes into
 * Tracking), Trash → `passed`. Back-to-Jobs lives in the detail panel; the spec
 * keeps the row a pure two-choice queue.
 */
export function ShortlistRowActions({ application }: { application: Application }) {
  const update = useUpdateApplication()
  const pending = update.isPending

  return (
    <QuickActions
      aria-label="Shortlist actions"
      size="xs"
      actions={[
        {
          id: 'trash',
          label: 'Trash',
          variant: 'danger',
          disabled: pending,
          onSelect: () =>
            update.mutate({ dedupHash: application.dedup_hash, update: { status: 'passed' } }),
        },
        {
          id: 'pursue',
          label: 'Pursue',
          variant: 'success',
          disabled: pending,
          onSelect: () =>
            update.mutate({ dedupHash: application.dedup_hash, update: { status: 'to_apply' } }),
        },
      ]}
    />
  )
}
