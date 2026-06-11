// Shared form components for the settings sections (profile + search).
// Non-component helpers (css consts, list helpers) live in formKit.ts.
import { labelCls, textareaCls } from './formKit'

export function Field({
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

export function ListField({
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

export function Checkbox({
  label,
  checked,
  onChange,
}: {
  label: string
  checked: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <label className="flex items-center gap-1.5 text-[12px] text-fg cursor-pointer select-none">
      <input
        type="checkbox"
        className="accent-primary size-3.5"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      {label}
    </label>
  )
}

/** A bordered group with an uppercase section heading. */
export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-[11px] font-semibold text-faint uppercase tracking-[0.1em] border-b border-border pb-1.5">
        {title}
      </h2>
      {children}
    </section>
  )
}
