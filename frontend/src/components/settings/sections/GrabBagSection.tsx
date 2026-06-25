import { useState } from 'react'
import type { FieldErrors } from '../../../api'
import { ApiValidationError } from '../../../api'
import { useSaveGrabBagSettings } from '../../../hooks/useSettings'
import { Input } from '@/components/ui/input'
import { Section } from '../fields'

interface GrabBagSectionProps {
  grabBagSize: number | null
  grabBagScoreFloor: number | null
  grabBagMaxAgeDays: number | null
  hasSearchConfig: boolean
}

// Mirror the backend column defaults (migration 0016).
const DEFAULTS = {
  grab_bag_size: 20,
  grab_bag_score_floor: 3,
} as const

const LABELS: Record<keyof typeof DEFAULTS, string> = {
  grab_bag_size: 'Batch size',
  grab_bag_score_floor: 'Score floor',
}

/**
 * Grab-bag settings: batch size (1–50), score floor (1–5), and optional
 * max posting age in days (blank = no limit).
 * Mirrors the alert-thresholds section pattern.
 */
export function GrabBagSection({
  grabBagSize,
  grabBagScoreFloor,
  grabBagMaxAgeDays,
  hasSearchConfig,
}: GrabBagSectionProps) {
  const save = useSaveGrabBagSettings()
  const [values, setValues] = useState({
    grab_bag_size: grabBagSize ?? DEFAULTS.grab_bag_size,
    grab_bag_score_floor: grabBagScoreFloor ?? DEFAULTS.grab_bag_score_floor,
  })
  const [maxAgeDays, setMaxAgeDays] = useState<number | null>(grabBagMaxAgeDays ?? null)
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  const setField = (key: keyof typeof values, val: number) => {
    setValues((prev) => ({ ...prev, [key]: val }))
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
      await save.mutateAsync({
        ...values,
        grab_bag_max_age_days: maxAgeDays,
      })
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
    <Section title="Grab bag">
      <p className="text-[12px] text-muted">
        Configure the grab-bag view: how many jobs per batch, the minimum fit score to surface, and
        an optional max posting age (blank = no limit).
      </p>

      <div className="grid grid-cols-2 gap-x-4">
        {Object.keys(LABELS).map((key) => {
          const k = key as keyof typeof DEFAULTS
          return (
            <Field key={k} label={LABELS[k]} error={fieldErrors[k]}>
              <Input
                type="number"
                min={k === 'grab_bag_size' ? 1 : 1}
                max={k === 'grab_bag_size' ? 50 : 5}
                value={values[k]}
                onChange={(e) => setField(k, Number(e.target.value))}
              />
            </Field>
          )
        })}

        <Field label="Max posting age (days)" error={fieldErrors.grab_bag_max_age_days}>
          <Input
            type="number"
            min={1}
            placeholder="No limit"
            value={maxAgeDays ?? ''}
            onChange={(e) => setMaxAgeDays(e.target.value === '' ? null : Number(e.target.value))}
          />
          <span className="text-[10px] text-muted">Blank = no age limit</span>
        </Field>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          className="text-[12px] px-3 py-1.5 rounded-md bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
          disabled={!hasSearchConfig || save.isPending}
          onClick={handleSave}
        >
          {save.isPending ? 'Saving…' : saved ? 'Saved' : 'Save grab-bag settings'}
        </button>
        {saved && <span className="text-[11px] text-score-high">Settings updated.</span>}
      </div>

      {!hasSearchConfig && (
        <p className="text-[11px] text-faint">
          Save your search targeting first; grab-bag settings are tied to your search config.
        </p>
      )}
      {saveError && (
        <p className="text-[11px] text-score-low">Failed to update grab-bag: {saveError}</p>
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
