import { useDeleteApplication } from '../hooks/useApplications'
import { QuickActions } from './ui/quick-actions'
import type { Application } from '../types'

/**
 * Row-level action for the Trash tab: Un-trash deletes the `user_applications`
 * row so the job falls back into the untriaged Jobs feed.
 */
export function TrashRowActions({ application }: { application: Application }) {
  const del = useDeleteApplication()
  const pending = del.isPending

  return (
    <QuickActions
      aria-label="Trash actions"
      size="xs"
      actions={[
        {
          id: 'untrash',
          label: 'Un-trash',
          variant: 'default',
          disabled: pending,
          onSelect: () => del.mutate(application.dedup_hash),
        },
      ]}
    />
  )
}
