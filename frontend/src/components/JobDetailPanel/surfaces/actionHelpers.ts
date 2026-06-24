import type { Application, ApplicationStatus } from '../../../types'
import { useTriageAction } from '../../../hooks/useTriage'
import type { DetailAction } from '../shared/DetailActionBar'

export function useApplicationDetailActions(
  dedupHash: string,
  application: Application | undefined,
  // Triaging from the detail panel is a decision: dismiss the panel afterward so
  // you land back on the feed (where the row has dropped out) ready for the next
  // job. Both the buttons and the keyboard shortcuts route through here, so the
  // two input paths stay in lockstep.
  onTriaged?: () => void,
) {
  const { triage, isPending } = useTriageAction()
  const currentStatus = application?.status ?? null

  function setStatus(status: ApplicationStatus) {
    triage({ dedupHash, from: currentStatus, to: status })
    onTriaged?.()
  }

  function removeTracking() {
    triage({ dedupHash, from: currentStatus, to: 'remove' })
    onTriaged?.()
  }

  function statusAction({
    id,
    label,
    status,
    shortcut,
    variant,
  }: {
    id?: string
    label: string
    status: ApplicationStatus
    shortcut?: string
    variant?: DetailAction['variant']
  }): DetailAction {
    return {
      id: id ?? status,
      label,
      shortcut,
      active: currentStatus === status,
      disabled: isPending,
      variant,
      onSelect: () => setStatus(status),
    }
  }

  function removeAction({
    id,
    label,
    shortcut,
    variant = 'default',
  }: {
    id: string
    label: string
    shortcut?: string
    variant?: DetailAction['variant']
  }): DetailAction {
    return {
      id,
      label,
      shortcut,
      disabled: isPending,
      variant,
      onSelect: removeTracking,
    }
  }

  return { isPending, statusAction, removeAction, setStatus, removeTracking }
}
