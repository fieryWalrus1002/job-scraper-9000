import { QuickActions, type QuickAction } from '@/components/ui/quick-actions'

export type DetailAction = QuickAction

export function DetailActionBar({ actions }: { actions: DetailAction[] }) {
  return <QuickActions aria-label="Triage status" size="sm" actions={actions} />
}
