import { useState } from 'react'
import { useSettings, useSaveProfile } from '../hooks/useSettings'
import { ApiValidationError, type FieldErrors } from '../api'
import type { CandidateProfileInput } from '../types'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'

const labelCls = 'text-[10px] font-semibold text-muted uppercase tracking-[0.08em]'
const textareaCls =
  'w-full resize-y bg-bg-elevated border border-border rounded-md text-fg text-[13px] leading-[1.55] px-2.5 py-2 outline-none ' +
  'placeholder:text-faint hover:border-border-strong ' +
  'focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/25 ' +
  'transition-[color,border-color,box-shadow]'

// The profile payload is a list-heavy human format; the form edits each list as
// newline-separated text (one item per line), mirroring how the YAML template
// reads. split/join keep the round-trip lossless apart from blank lines.
const linesToList = (text: string): string[] =>
  text
    .split('\n')
    .map((l) => l.trim())
    .filter(Boolean)
const listToLines = (list: string[] | undefined): string => (list ?? []).join('\n')

interface FormState {
  summary: string
  level: string
  education: string
  core_skills: string
  adjacent_skills: string
  growth_skills: string
  preferred_domains: string
  avoided_domains: string
  hard: string
  soft: string
  scoring_notes: string
}

const EMPTY: FormState = {
  summary: '',
  level: '',
  education: '',
  core_skills: '',
  adjacent_skills: '',
  growth_skills: '',
  preferred_domains: '',
  avoided_domains: '',
  hard: '',
  soft: '',
  scoring_notes: '',
}

function fromProfile(p: CandidateProfileInput): FormState {
  return {
    summary: p.summary ?? '',
    level: p.level ?? '',
    education: listToLines(p.education),
    core_skills: listToLines(p.core_skills),
    adjacent_skills: listToLines(p.adjacent_skills),
    growth_skills: listToLines(p.growth_skills),
    preferred_domains: listToLines(p.preferred_domains),
    avoided_domains: listToLines(p.avoided_domains),
    hard: listToLines(p.constraints?.hard),
    soft: listToLines(p.constraints?.soft),
    scoring_notes: p.scoring_notes ?? '',
  }
}

function toProfile(f: FormState): CandidateProfileInput {
  return {
    summary: f.summary.trim(),
    level: f.level.trim(),
    education: linesToList(f.education),
    core_skills: linesToList(f.core_skills),
    adjacent_skills: linesToList(f.adjacent_skills),
    growth_skills: linesToList(f.growth_skills),
    preferred_domains: linesToList(f.preferred_domains),
    avoided_domains: linesToList(f.avoided_domains),
    constraints: { hard: linesToList(f.hard), soft: linesToList(f.soft) },
    scoring_notes: f.scoring_notes.trim() || null,
  }
}

export default function SettingsPage() {
  const { data, isLoading, isError, error } = useSettings()

  if (isLoading) return <div className="p-6 text-muted text-sm">Loading…</div>
  if (isError)
    return (
      <div className="p-6 text-score-low text-sm">Failed to load settings: {error.message}</div>
    )

  // Remount the form when the loaded profile identity changes so its lazily
  // initialized state re-seeds (avoids a setState-in-effect to sync props).
  return (
    <ProfileForm
      key={data?.profile_version ?? 'onboarding'}
      initial={(data?.profile as CandidateProfileInput | null) ?? null}
      version={data?.profile_version ?? null}
    />
  )
}

function ProfileForm({
  initial,
  version,
}: {
  initial: CandidateProfileInput | null
  version: string | null
}) {
  const save = useSaveProfile()

  const [form, setForm] = useState<FormState>(() => (initial ? fromProfile(initial) : EMPTY))
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})
  const [saveError, setSaveError] = useState<string | null>(null)
  const [savedVersion, setSavedVersion] = useState<string | null>(null)

  const isOnboarding = !initial
  const currentVersion = savedVersion ?? version

  function set<K extends keyof FormState>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setFieldErrors({})
    setSaveError(null)
    setSavedVersion(null)
    try {
      const res = await save.mutateAsync(toProfile(form))
      setSavedVersion(res.profile_version)
    } catch (err) {
      if (err instanceof ApiValidationError) {
        setFieldErrors(err.fields)
      } else {
        setSaveError(err instanceof Error ? err.message : String(err))
      }
    }
  }

  return (
    <div className="p-6 overflow-y-auto">
      <div className="max-w-[720px] mx-auto flex flex-col gap-5">
        <div>
          <h1 className="text-[18px] font-semibold tracking-tight text-fg">Settings</h1>
          <p className="text-[12px] text-muted mt-1">
            Your candidate profile drives how jobs are scored. Changes take effect at your next
            overnight run — they don't re-score existing jobs.
          </p>
        </div>

        {isOnboarding && (
          <div className="text-[12px] text-primary-hov bg-primary/10 border border-primary/25 rounded-md px-3 py-2.5">
            No profile yet — fill this in and your feed gets real jobs after the next run.
          </div>
        )}

        <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
          <Field label="Summary" required error={fieldErrors['summary']}>
            <textarea
              className={textareaCls}
              style={{ minHeight: 90 }}
              placeholder="A few sentences on who you are as a candidate."
              value={form.summary}
              onChange={(e) => set('summary', e.target.value)}
            />
          </Field>

          <Field label="Level" required error={fieldErrors['level']}>
            <Input
              placeholder="e.g. Senior software engineer (8+ years)"
              value={form.level}
              onChange={(e) => set('level', e.target.value)}
            />
          </Field>

          <ListField
            label="Core skills"
            required
            hint="One per line"
            error={fieldErrors['core_skills']}
            value={form.core_skills}
            onChange={(v) => set('core_skills', v)}
          />
          <ListField
            label="Adjacent skills"
            hint="One per line"
            error={fieldErrors['adjacent_skills']}
            value={form.adjacent_skills}
            onChange={(v) => set('adjacent_skills', v)}
          />
          <ListField
            label="Growth skills"
            hint="One per line"
            error={fieldErrors['growth_skills']}
            value={form.growth_skills}
            onChange={(v) => set('growth_skills', v)}
          />
          <ListField
            label="Education"
            hint="One per line"
            error={fieldErrors['education']}
            value={form.education}
            onChange={(v) => set('education', v)}
          />
          <ListField
            label="Preferred domains"
            hint="One per line"
            error={fieldErrors['preferred_domains']}
            value={form.preferred_domains}
            onChange={(v) => set('preferred_domains', v)}
          />
          <ListField
            label="Avoided domains"
            hint="One per line"
            error={fieldErrors['avoided_domains']}
            value={form.avoided_domains}
            onChange={(v) => set('avoided_domains', v)}
          />
          <ListField
            label="Hard constraints"
            hint="Must-haves, one per line"
            error={fieldErrors['constraints.hard']}
            value={form.hard}
            onChange={(v) => set('hard', v)}
          />
          <ListField
            label="Soft preferences"
            hint="Nice-to-haves, one per line"
            error={fieldErrors['constraints.soft']}
            value={form.soft}
            onChange={(v) => set('soft', v)}
          />

          <Field label="Scoring notes" hint="Optional" error={fieldErrors['scoring_notes']}>
            <textarea
              className={textareaCls}
              style={{ minHeight: 60 }}
              placeholder="Anything else that should inform scoring."
              value={form.scoring_notes}
              onChange={(e) => set('scoring_notes', e.target.value)}
            />
          </Field>

          {saveError && (
            <div className="text-[12px] text-score-low bg-score-low/10 border border-score-low/20 rounded-md px-3 py-2">
              {saveError}
            </div>
          )}

          <div className="flex items-center justify-between gap-3 pt-3 border-t border-border">
            <div className="text-[11px] text-faint">
              {currentVersion ? (
                <>
                  Profile version <span className="font-mono text-muted">{currentVersion}</span>
                </>
              ) : (
                'Not yet saved'
              )}
              {savedVersion && <span className="text-score-high ml-2">✓ Saved</span>}
            </div>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? 'Saving…' : 'Save profile'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

function Field({
  label,
  required,
  hint,
  error,
  children,
}: {
  label: string
  required?: boolean
  hint?: string
  error?: string
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className={labelCls}>
        {label}
        {required && <span className="text-score-low normal-case"> *</span>}
        {hint && <span className="text-faint normal-case font-normal ml-1.5">{hint}</span>}
      </label>
      {children}
      {error && <span className="text-[11px] text-score-low">{error}</span>}
    </div>
  )
}

function ListField({
  label,
  required,
  hint,
  error,
  value,
  onChange,
}: {
  label: string
  required?: boolean
  hint?: string
  error?: string
  value: string
  onChange: (v: string) => void
}) {
  return (
    <Field label={label} required={required} hint={hint} error={error}>
      <textarea
        className={textareaCls}
        style={{ minHeight: 64 }}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </Field>
  )
}
