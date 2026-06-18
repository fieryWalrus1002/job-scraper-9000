import type { FieldErrors } from '../../../api'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Field, Section } from '../fields'
import type { SearchFormState, SetField } from '../searchFormState'

export function SearchTargetingSection({
  form,
  set,
  fieldErrors,
  isOnboarding,
}: {
  form: SearchFormState
  set: SetField
  fieldErrors: FieldErrors
  isOnboarding: boolean
}) {
  return (
    <Section title="Search targeting">
      {isOnboarding && (
        <div className="text-[12px] text-primary-hov bg-primary/10 border border-primary/25 rounded-md px-3 py-2.5">
          No search config yet — set your targets so the scraper knows what to pull.
        </div>
      )}

      <div className="grid grid-cols-2 gap-x-4 gap-y-4">
        <Field label="Display name" required error={fieldErrors['user.display_name']}>
          <Input value={form.display_name} onChange={(e) => set('display_name', e.target.value)} />
        </Field>
        <Field label="Email" required error={fieldErrors['user.email']}>
          <Input value={form.email} onChange={(e) => set('email', e.target.value)} />
        </Field>
        <Field label="Search profile name" required error={fieldErrors['search_profile.name']}>
          <Input value={form.profile_name} onChange={(e) => set('profile_name', e.target.value)} />
        </Field>
        <Field label="Search mode">
          <Select
            value={form.search_mode}
            onValueChange={(v) => set('search_mode', v as SearchFormState['search_mode'])}
          >
            <SelectTrigger className="w-full h-8 text-[13px] bg-bg-elevated border-border">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(['focused', 'balanced', 'broad'] as const).map((m) => (
                <SelectItem key={m} value={m}>
                  {m}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      </div>

      <div className="grid grid-cols-3 gap-x-4">
        <Field label="Home city">
          <Input value={form.home_city} onChange={(e) => set('home_city', e.target.value)} />
        </Field>
        <Field label="Home region">
          <Input value={form.home_region} onChange={(e) => set('home_region', e.target.value)} />
        </Field>
        <Field label="Home country">
          <Input value={form.home_country} onChange={(e) => set('home_country', e.target.value)} />
        </Field>
      </div>
    </Section>
  )
}
