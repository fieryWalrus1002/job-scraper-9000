import { useEffect } from 'react'
import { useUpcomingSteps } from '../hooks/useApplications'
import type {
  InactivityAlertOut,
  PostApplicationAlertOut,
  PostInterviewAlertOut,
  StaleToApplyAlertOut,
} from '../types'
import { Badge } from './ui/badge'

const KIND_CONFIG: Record<
  string,
  { label: string; badgeVariant: 'score_high' | 'score_mid' | 'score_low' }
> = {
  stale_to_apply: { label: 'Stale to-apply', badgeVariant: 'score_mid' },
  post_interview: { label: 'Post-interview', badgeVariant: 'score_low' },
  inactivity: { label: 'Inactivity', badgeVariant: 'score_low' },
  post_application: { label: 'Follow-up', badgeVariant: 'score_mid' },
}

type AlertKind =
  | StaleToApplyAlertOut
  | PostInterviewAlertOut
  | InactivityAlertOut
  | PostApplicationAlertOut

/**
 * Upcoming Steps pane — renders at the top of the Tracking page.
 *
 * Degrades quietly: hidden while loading or on error, hidden when there are
 * no alerts. Never blocks the board from rendering. The error is hidden from
 * the user but still logged loudly (per the repo's log-well rule) since the
 * pane swallows it visually.
 */
export function UpcomingStepsPane() {
  const { data, isLoading, isError, error } = useUpcomingSteps()

  // The pane hides its own failures from the UI, so log them — otherwise a
  // failing /api/upcoming-steps would vanish with no diagnostic trace.
  useEffect(() => {
    if (isError) console.error('Upcoming Steps query failed:', error)
  }, [isError, error])

  // Degrade quietly — never block the board.
  if (isLoading || isError) return null

  const alerts = data?.alerts ?? []
  if (alerts.length === 0) return null

  return (
    <div className="border-b border-border">
      <div className="px-5 py-3">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-[13px] font-medium text-fg">Upcoming Steps</span>
        </div>
        <ul className="space-y-1.5">
          {alerts.map((alert: AlertKind, idx) => (
            <li key={idx} className="flex items-start gap-2">
              <Badge variant={KIND_CONFIG[alert.kind]?.badgeVariant ?? 'muted'}>
                {KIND_CONFIG[alert.kind]?.label ?? alert.kind}
              </Badge>
              <span className="text-[13px] text-muted">{alert.message}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
