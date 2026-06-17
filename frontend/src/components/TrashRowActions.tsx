import { useTriageAction } from '../hooks/useTriage'
import { QuickActions } from './ui/quick-actions'
import type { Application } from '../types'

/**
 * Row-level action for the Trash tab: Un-trash deletes the `user_applications`
 * row so the job falls back into the untriaged Jobs feed. Undo recreates the row
 * as `passed`, restoring its notes.
 */
export function TrashRowActions({ application }: { application: Application }) {
  const { triage, isPending } = useTriageAction()

  return (
    <QuickActions
      aria-label="Trash actions"
      size="xs"
      actions={[
        {
          id: 'untrash',
          label: 'Un-trash',
          variant: 'default',
          disabled: isPending,
          onSelect: () =>
            triage({
              dedupHash: application.dedup_hash,
              from: application.status,
              to: 'remove',
              restoreNotes: application.notes,
            }),
        },
      ]}
    />
  )
}
