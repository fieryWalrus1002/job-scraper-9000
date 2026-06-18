import type { FieldErrors } from '../../../api'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Checkbox, Field, Section } from '../fields'
import type { SearchFormState, SetField } from '../searchFormState'

export function ScrapePreferencesSection({
  form,
  set,
  fieldErrors,
}: {
  form: SearchFormState
  set: SetField
  fieldErrors: FieldErrors
}) {
  return (
    <Section title="Scrape preferences">
      <div className="flex flex-col gap-2">
        <Checkbox
          label="Remote national searches"
          checked={form.include_remote_national}
          onChange={(v) => set('include_remote_national', v)}
        />
        <Checkbox
          label="Local searches"
          checked={form.include_local}
          onChange={(v) => set('include_local', v)}
        />
        <Checkbox
          label="Company board searches"
          checked={form.include_company_boards}
          onChange={(v) => set('include_company_boards', v)}
        />
        <Checkbox
          label="General job boards"
          checked={form.include_general_boards}
          onChange={(v) => set('include_general_boards', v)}
        />
      </div>
      <div className="grid grid-cols-3 gap-x-4">
        <Field
          label="Max results per task"
          error={fieldErrors['scrape_preferences.max_results_per_task']}
        >
          <Input
            type="number"
            value={form.max_results}
            onChange={(e) => set('max_results', Number(e.target.value))}
          />
        </Field>
        <Field label="Freshness (hours)" error={fieldErrors['scrape_preferences.freshness_hours']}>
          <Input
            type="number"
            value={form.freshness_hours}
            onChange={(e) => set('freshness_hours', Number(e.target.value))}
          />
        </Field>
        <Field label="Cadence">
          <Select
            value={form.cadence}
            onValueChange={(v) => set('cadence', v as SearchFormState['cadence'])}
          >
            <SelectTrigger className="w-full h-8 text-[13px] bg-bg-elevated border-border">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="daily">daily</SelectItem>
              <SelectItem value="weekly">weekly</SelectItem>
            </SelectContent>
          </Select>
        </Field>
      </div>
    </Section>
  )
}
