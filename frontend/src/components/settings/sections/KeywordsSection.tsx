import { ListField, Section } from '../fields'
import type { SearchFormState, SetField } from '../searchFormState'

export function KeywordsSection({ form, set }: { form: SearchFormState; set: SetField }) {
  return (
    <Section title="Keywords">
      <ListField
        label="Required (any)"
        hint="One per line"
        value={form.kw_required_any}
        onChange={(v) => set('kw_required_any', v)}
      />
      <ListField
        label="Required (all)"
        hint="One per line"
        value={form.kw_required_all}
        onChange={(v) => set('kw_required_all', v)}
      />
      <ListField
        label="Preferred"
        hint="One per line"
        value={form.kw_preferred}
        onChange={(v) => set('kw_preferred', v)}
      />
      <ListField
        label="Excluded"
        hint="One per line"
        value={form.kw_excluded}
        onChange={(v) => set('kw_excluded', v)}
      />
    </Section>
  )
}
