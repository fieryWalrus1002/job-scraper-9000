import type { Application, ApplicationStatus } from '../../../types'
import {
  useDeleteApplication,
  useMarkApplication,
  useUpdateApplication,
} from '../../../hooks/useApplications'
import type { DetailAction } from '../shared/DetailActionBar'

export function useApplicationDetailActions(
  dedupHash: string,
  application: Application | undefined,
) {
  const mark = useMarkApplication()
  const update = useUpdateApplication()
  const del = useDeleteApplication()
  const isPending = mark.isPending || update.isPending || del.isPending
  const currentStatus = application?.status ?? null

  function setStatus(status: ApplicationStatus) {
    if (application) {
      update.mutate({ dedupHash, update: { status } })
    } else {
      mark.mutate({ dedupHash, status })
    }
  }

  function removeTracking() {
    if (application) del.mutate(dedupHash)
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
      disabled: isPending || !application,
      variant,
      onSelect: removeTracking,
    }
  }

  return { isPending, statusAction, removeAction, setStatus, removeTracking }
}
