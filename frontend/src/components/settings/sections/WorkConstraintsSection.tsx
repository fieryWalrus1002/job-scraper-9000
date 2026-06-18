import type { FieldErrors } from '../../../api'
import { SEARCH_EMPLOYMENT_TYPES, type SearchEmploymentType } from '../../../types'
import { Checkbox, Field, Section } from '../fields'
import type { Arrangement, ArrangementKey, SearchFormState } from '../searchFormState'

export function WorkConstraintsSection({
  form,
  setArrangement,
  toggleEmployment,
  fieldErrors,
}: {
  form: SearchFormState
  setArrangement: (key: ArrangementKey, patch: Partial<Arrangement>) => void
  toggleEmployment: (t: SearchEmploymentType, on: boolean) => void
  fieldErrors: FieldErrors
}) {
  const waError = fieldErrors['work_constraints.work_arrangements']
  const empError = fieldErrors['work_constraints.employment_types.acceptable']

  return (
    <Section title="Work constraints">
      <Field label="Employment types" required error={empError}>
        <div className="flex gap-4 pt-0.5">
          {SEARCH_EMPLOYMENT_TYPES.map((t) => (
            <Checkbox
              key={t}
              label={t}
              checked={form.employment_types.includes(t)}
              onChange={(on) => toggleEmployment(t, on)}
            />
          ))}
        </div>
      </Field>

      <Field label="Work arrangements" hint="At least one must be acceptable" error={waError}>
        <div className="flex flex-col gap-2 pt-0.5">
          <div className="grid grid-cols-[80px_repeat(3,1fr)] gap-x-3 text-[10px] text-faint uppercase tracking-wide">
            <span />
            <span>Acceptable</span>
            <span>Preferred</span>
            <span>Required</span>
          </div>
          {(['remote', 'hybrid', 'onsite'] as const).map((k) => (
            <div key={k} className="grid grid-cols-[80px_repeat(3,1fr)] gap-x-3 items-center">
              <span className="text-[12px] text-fg capitalize">{k}</span>
              <Checkbox
                label=""
                checked={form.arrangements[k].acceptable}
                onChange={(v) => setArrangement(k, { acceptable: v })}
              />
              <Checkbox
                label=""
                checked={form.arrangements[k].preferred}
                onChange={(v) => setArrangement(k, { preferred: v })}
              />
              <Checkbox
                label=""
                checked={form.arrangements[k].required}
                onChange={(v) => setArrangement(k, { required: v })}
              />
            </div>
          ))}
        </div>
      </Field>
    </Section>
  )
}
