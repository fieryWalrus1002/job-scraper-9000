import { QuickActions, type QuickAction } from '@/components/ui/quick-actions'
import { useActionShortcuts } from './useActionShortcuts'

export type DetailAction = QuickAction

export function DetailActionBar({ actions }: { actions: DetailAction[] }) {
  useActionShortcuts(actions)
  return <QuickActions aria-label="Triage status" size="sm" actions={actions} />
}
