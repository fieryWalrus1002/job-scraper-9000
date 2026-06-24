import { useSavePipelineEnabled } from '../../../hooks/useSettings'
import { useAuth } from '../../../hooks/useAuth'
import { Section } from '../fields'
import { AlertThresholdsSection } from './AlertThresholdsSection'

interface AccountSectionProps {
  pipelineEnabled: boolean | null
  hasSearchConfig: boolean
  staleToApplyDays: number | null
  postInterviewNudgeDays: number | null
  inactivityDays: number | null
}

/**
 * Account & Activity panel: signed-in context plus the self-service overnight
 * pipeline gate backed by app.user_search_configs.pipeline_enabled.
 */
export function AccountSection({
  pipelineEnabled,
  hasSearchConfig,
  staleToApplyDays,
  postInterviewNudgeDays,
  inactivityDays,
}: AccountSectionProps) {
  const { principal, isLoading } = useAuth()
  const savePipelineEnabled = useSavePipelineEnabled()
  const email = principal?.userDetails ?? null
  const checked = pipelineEnabled === true
  const isSaving = savePipelineEnabled.isPending

  return (
    <div className="flex flex-col gap-6">
      <Section title="Account">
        <div className="flex flex-col gap-1">
          <span className="text-[11px] text-faint uppercase tracking-wide">Signed in as</span>
          <span className="text-[13px] text-fg">
            {isLoading ? 'Loading…' : (email ?? 'Not signed in')}
          </span>
        </div>
      </Section>

      <Section title="Overnight pipeline">
        <p className="text-[12px] text-muted">
          Your search runs automatically each night, scraping and scoring new postings against your
          profile. Pausing the pipeline stops future overnight runs — it does not delete your
          settings or any jobs already scored.
        </p>

        <label
          className={`flex items-center justify-between gap-4 rounded-md border border-border bg-bg-elevated/30 px-3 py-2 ${
            hasSearchConfig ? 'cursor-pointer' : 'cursor-not-allowed opacity-70'
          }`}
        >
          <span className="flex flex-col gap-0.5">
            <span className="text-[13px] font-medium text-fg">Run overnight pipeline</span>
            <span className="text-[11px] text-muted">
              {hasSearchConfig
                ? checked
                  ? 'Enabled — future overnight runs will include your account.'
                  : 'Paused — future overnight runs will skip your account.'
                : 'Disabled until you save a search config.'}
            </span>
          </span>
          <input
            type="checkbox"
            role="switch"
            className="accent-primary size-4 shrink-0"
            checked={checked}
            disabled={!hasSearchConfig || isSaving}
            aria-label="Run overnight pipeline"
            onChange={(event) => {
              if (!hasSearchConfig) return
              savePipelineEnabled.mutate(event.target.checked)
            }}
          />
        </label>

        {!hasSearchConfig && (
          <p className="text-[11px] text-faint">
            Save your search targeting first; the toggle only updates an existing search config and
            will not create a partial config.
          </p>
        )}
        {savePipelineEnabled.isError && (
          <p className="text-[11px] text-score-low">
            Failed to update pipeline setting: {savePipelineEnabled.error.message}
          </p>
        )}
      </Section>

      <AlertThresholdsSection
        staleToApplyDays={staleToApplyDays}
        postInterviewNudgeDays={postInterviewNudgeDays}
        inactivityDays={inactivityDays}
        hasSearchConfig={hasSearchConfig}
      />
    </div>
  )
}
