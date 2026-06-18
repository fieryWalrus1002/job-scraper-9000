import type { FieldErrors } from '../../../api'
import {
  LINKEDIN_EXPERIENCE_LABELS,
  SEARCH_SALARY_FLOORS_K,
  type LinkedInExperienceCode,
} from '../../../types'
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
  toggleLinkedInExperience,
  fieldErrors,
}: {
  form: SearchFormState
  set: SetField
  toggleLinkedInExperience: (code: LinkedInExperienceCode, on: boolean) => void
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

      <div className="grid grid-cols-2 gap-x-4 gap-y-4">
        <Field label="Salary floor" error={fieldErrors['scrape_preferences.salary_floor_k']}>
          <Select
            value={form.salary_floor_k === null ? 'any' : String(form.salary_floor_k)}
            onValueChange={(v) =>
              set(
                'salary_floor_k',
                v === 'any' ? null : (Number(v) as SearchFormState['salary_floor_k']),
              )
            }
          >
            <SelectTrigger className="w-full h-8 text-[13px] bg-bg-elevated border-border">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="any">Any</SelectItem>
              {SEARCH_SALARY_FLOORS_K.map((floor) => (
                <SelectItem key={floor} value={String(floor)}>
                  ${floor}k+
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        <Field
          label="LinkedIn experience levels"
          hint="Defaults to entry through director"
          error={fieldErrors['scrape_preferences.linkedin_experience_codes']}
        >
          <div className="grid grid-cols-2 gap-x-4 gap-y-2 pt-0.5">
            {Object.entries(LINKEDIN_EXPERIENCE_LABELS).map(([code, label]) => (
              <Checkbox
                key={code}
                label={label}
                checked={form.linkedin_experience_codes.includes(code as LinkedInExperienceCode)}
                onChange={(on) => toggleLinkedInExperience(code as LinkedInExperienceCode, on)}
              />
            ))}
          </div>
        </Field>
      </div>
    </Section>
  )
}
