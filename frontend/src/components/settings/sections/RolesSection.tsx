import type { FieldErrors } from '../../../api'
import { ListField, Section } from '../fields'
import type { SearchFormState, SetField } from '../searchFormState'

export function RolesSection({
  form,
  set,
  fieldErrors,
}: {
  form: SearchFormState
  set: SetField
  fieldErrors: FieldErrors
}) {
  return (
    <Section title="Roles">
      <ListField
        label="Preferred titles"
        required
        hint="One per line — these drive the scrape"
        error={fieldErrors['roles.target_titles.preferred']}
        value={form.preferred_titles}
        onChange={(v) => set('preferred_titles', v)}
      />
      <ListField
        label="Exploratory titles"
        hint="One per line"
        value={form.exploratory_titles}
        onChange={(v) => set('exploratory_titles', v)}
      />
      <ListField
        label="Excluded titles"
        hint="One per line — filtered out in prefilter"
        value={form.excluded_titles}
        onChange={(v) => set('excluded_titles', v)}
      />
    </Section>
  )
}
