import { useState } from 'react'
import type { FieldErrors } from '../../../api'
import { ApiValidationError } from '../../../api'
import { useSaveAlertThresholds } from '../../../hooks/useSettings'
import { Input } from '@/components/ui/input'
import { Section } from '../fields'

interface AlertThresholdsSectionProps {
  staleToApplyDays: number | null
  postInterviewNudgeDays: number | null
  inactivityDays: number | null
  hasSearchConfig: boolean
}

const DEFAULTS = {
  stale_to_apply_days: 3,
  post_interview_nudge_days: 7,
  inactivity_days: 14,
} as const

const LABELS: Record<keyof typeof DEFAULTS, string> = {
  stale_to_apply_days: 'Stale → To Apply (days)',
  post_interview_nudge_days: 'Post-Interview Nudge (days)',
  inactivity_days: 'Inactivity Alert (days)',
}

/**
 * Alert threshold settings for Upcoming Steps reminders.
 * Mirrors the pipeline_enabled toggle pattern (AccountSection) but with
 * editable numeric fields.
 */
export function AlertThresholdsSection({
  staleToApplyDays,
  postInterviewNudgeDays,
  inactivityDays,
  hasSearchConfig,
}: AlertThresholdsSectionProps) {
  const save = useSaveAlertThresholds()
  const [values, setValues] = useState({
    stale_to_apply_days: staleToApplyDays ?? DEFAULTS.stale_to_apply_days,
    post_interview_nudge_days: postInterviewNudgeDays ?? DEFAULTS.post_interview_nudge_days,
    inactivity_days: inactivityDays ?? DEFAULTS.inactivity_days,
  })
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const setField = (key: keyof typeof values, val: number) => {
    setValues((prev) => ({ ...prev, [key]: val }))
    // Clear field error on edit.
    if (fieldErrors[key]) {
      setFieldErrors((prev) => {
        const next = { ...prev }
        delete next[key]
        return next
      })
    }
  }

  const handleSave = async () => {
    setFieldErrors({})
    setSaveError(null)
    setSaved(false)
    try {
      await save.mutateAsync(values)
      setSaved(true)
    } catch (err) {
      if (err instanceof ApiValidationError) {
        setFieldErrors(err.fields)
      } else {
        setSaveError((err as Error).message)
      }
    }
  }

  return (
    <Section title="Alert thresholds">
      <p className="text-[12px] text-muted">
        Configure how many days of inactivity or staleness trigger upcoming step reminders.
      </p>

      <div className="grid grid-cols-3 gap-x-4">
        {Object.keys(LABELS).map((key) => {
          const k = key as keyof typeof DEFAULTS
          return (
            <Field key={k} label={LABELS[k]} error={fieldErrors[k]}>
              <Input
                type="number"
                min={1}
                value={values[k]}
                onChange={(e) => setField(k, Number(e.target.value))}
              />
            </Field>
          )
        })}
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          className="text-[12px] px-3 py-1.5 rounded-md bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
          disabled={!hasSearchConfig || save.isPending}
          onClick={handleSave}
        >
          {save.isPending ? 'Saving…' : saved ? 'Saved' : 'Save thresholds'}
        </button>
        {saved && <span className="text-[11px] text-score-high">Thresholds updated.</span>}
      </div>

      {!hasSearchConfig && (
        <p className="text-[11px] text-faint">
          Save your search targeting first; thresholds are tied to your search config.
        </p>
      )}
      {saveError && (
        <p className="text-[11px] text-score-low">Failed to update thresholds: {saveError}</p>
      )}
    </Section>
  )
}

function Field({
  label,
  error,
  children,
}: {
  label: string
  error?: string
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-[11px] font-medium text-faint uppercase tracking-wide">{label}</label>
      {children}
      {error && <span className="text-[11px] text-score-low">{error}</span>}
    </div>
  )
}
