import { ListField, Section } from '../fields'
import type { SearchFormState, SetField } from '../searchFormState'

export function OrganizationsAndDomainsSection({
  form,
  set,
}: {
  form: SearchFormState
  set: SetField
}) {
  return (
    <Section title="Organizations & domains">
      <ListField
        label="Target companies"
        hint="One per line"
        value={form.target_companies}
        onChange={(v) => set('target_companies', v)}
      />
      <ListField
        label="Similar to"
        hint="One per line"
        value={form.similar_to}
        onChange={(v) => set('similar_to', v)}
      />
      <ListField
        label="Preferred organization types"
        hint="One per line"
        value={form.org_types}
        onChange={(v) => set('org_types', v)}
      />
      <ListField
        label="Preferred domains"
        hint="One per line"
        value={form.domains_preferred}
        onChange={(v) => set('domains_preferred', v)}
      />
      <ListField
        label="Excluded domains"
        hint="One per line"
        value={form.domains_excluded}
        onChange={(v) => set('domains_excluded', v)}
      />
    </Section>
  )
}
