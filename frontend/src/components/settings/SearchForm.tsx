import { useState } from 'react'
import { useSaveSearch } from '../../hooks/useSettings'
import { ApiValidationError, type FieldErrors } from '../../api'
import {
  SEARCH_EMPLOYMENT_TYPES,
  type SearchConfigInput,
  type SearchEmploymentType,
} from '../../types'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Checkbox, Field, ListField, Section } from './fields'
import { labelCls, linesToList, listToLines } from './formKit'

type Arrangement = { acceptable: boolean; preferred: boolean; required: boolean }
type ArrangementKey = 'remote' | 'hybrid' | 'onsite'
type LocRow = { city: string; region: string; country: string }

interface SearchFormState {
  display_name: string
  email: string
  home_city: string
  home_region: string
  home_country: string
  profile_name: string
  status: 'active' | 'paused'
  goal_summary: string
  search_mode: 'focused' | 'balanced' | 'broad'
  preferred_titles: string
  exploratory_titles: string
  excluded_titles: string
  employment_types: SearchEmploymentType[]
  arrangements: Record<ArrangementKey, Arrangement>
  acceptable_locations: LocRow[]
  excluded_locations: LocRow[]
  relocation_willing: boolean
  target_companies: string
  similar_to: string
  org_types: string
  domains_preferred: string
  domains_excluded: string
  kw_required_any: string
  kw_required_all: string
  kw_preferred: string
  kw_excluded: string
  include_remote_national: boolean
  include_local: boolean
  include_company_boards: boolean
  include_general_boards: boolean
  max_results: number
  freshness_hours: number
  cadence: 'daily' | 'weekly'
}

const ARR_DEFAULT: Arrangement = { acceptable: true, preferred: false, required: false }

const EMPTY: SearchFormState = {
  display_name: '',
  email: '',
  home_city: '',
  home_region: '',
  home_country: 'US',
  profile_name: '',
  status: 'active',
  goal_summary: '',
  search_mode: 'balanced',
  preferred_titles: '',
  exploratory_titles: '',
  excluded_titles: '',
  employment_types: ['fulltime'],
  arrangements: {
    remote: { ...ARR_DEFAULT },
    hybrid: { ...ARR_DEFAULT },
    onsite: { ...ARR_DEFAULT },
  },
  acceptable_locations: [],
  excluded_locations: [],
  relocation_willing: false,
  target_companies: '',
  similar_to: '',
  org_types: '',
  domains_preferred: '',
  domains_excluded: '',
  kw_required_any: '',
  kw_required_all: '',
  kw_preferred: '',
  kw_excluded: '',
  include_remote_national: true,
  include_local: true,
  include_company_boards: true,
  include_general_boards: true,
  max_results: 50,
  freshness_hours: 48,
  cadence: 'daily',
}

function arr(a: Arrangement | undefined): Arrangement {
  return { ...ARR_DEFAULT, ...(a ?? {}) }
}

function fromSearch(s: SearchConfigInput): SearchFormState {
  const wa = s.work_constraints?.work_arrangements ?? {}
  const locs = s.locations ?? {}
  return {
    display_name: s.user.display_name ?? '',
    email: s.user.email ?? '',
    home_city: s.user.home_location?.city ?? '',
    home_region: s.user.home_location?.region ?? '',
    home_country: s.user.home_location?.country ?? 'US',
    profile_name: s.search_profile.name ?? '',
    status: s.search_profile.status ?? 'active',
    goal_summary: s.search_profile.goal_summary ?? '',
    search_mode: s.search_profile.search_mode ?? 'balanced',
    preferred_titles: listToLines(s.roles.target_titles.preferred),
    exploratory_titles: listToLines(s.roles.target_titles.exploratory),
    excluded_titles: listToLines(s.roles.excluded_titles),
    employment_types: (s.work_constraints?.employment_types
      ?.acceptable as SearchEmploymentType[]) ?? ['fulltime'],
    arrangements: { remote: arr(wa.remote), hybrid: arr(wa.hybrid), onsite: arr(wa.onsite) },
    acceptable_locations: (locs.acceptable ?? []).map(toRow),
    excluded_locations: (locs.excluded ?? []).map(toRow),
    relocation_willing: locs.relocation?.willing ?? false,
    target_companies: listToLines(s.organizations?.target_companies),
    similar_to: listToLines(s.organizations?.similar_to),
    org_types: listToLines(s.organizations?.preferred_organization_types),
    domains_preferred: listToLines(s.industries_and_domains?.preferred),
    domains_excluded: listToLines(s.industries_and_domains?.excluded),
    kw_required_any: listToLines(s.keywords?.required_any),
    kw_required_all: listToLines(s.keywords?.required_all),
    kw_preferred: listToLines(s.keywords?.preferred),
    kw_excluded: listToLines(s.keywords?.excluded),
    include_remote_national: s.scrape_preferences?.include_remote_national_searches ?? true,
    include_local: s.scrape_preferences?.include_local_searches ?? true,
    include_company_boards: s.scrape_preferences?.include_company_board_searches ?? true,
    include_general_boards: s.scrape_preferences?.include_general_job_boards ?? true,
    max_results: s.scrape_preferences?.max_results_per_task ?? 50,
    freshness_hours: s.scrape_preferences?.freshness_hours ?? 48,
    cadence: s.scrape_preferences?.cadence ?? 'daily',
  }
}

const toRow = (l: { city: string; region: string; country?: string }): LocRow => ({
  city: l.city,
  region: l.region,
  country: l.country ?? 'US',
})

// Drop fully-blank rows; keep partial ones so server validation can flag them.
const cleanLocs = (rows: LocRow[]) =>
  rows
    .filter((r) => r.city.trim() || r.region.trim())
    .map((r) => ({
      city: r.city.trim(),
      region: r.region.trim(),
      country: r.country.trim() || 'US',
    }))

function toSearch(f: SearchFormState): SearchConfigInput {
  const home =
    f.home_city.trim() || f.home_region.trim()
      ? {
          city: f.home_city.trim(),
          region: f.home_region.trim(),
          country: f.home_country.trim() || 'US',
        }
      : null
  return {
    user: { display_name: f.display_name.trim(), email: f.email.trim(), home_location: home },
    search_profile: {
      name: f.profile_name.trim(),
      status: f.status,
      goal_summary: f.goal_summary.trim(),
      search_mode: f.search_mode,
    },
    roles: {
      target_titles: {
        preferred: linesToList(f.preferred_titles),
        exploratory: linesToList(f.exploratory_titles),
      },
      excluded_titles: linesToList(f.excluded_titles),
    },
    work_constraints: {
      employment_types: { acceptable: f.employment_types },
      work_arrangements: f.arrangements,
    },
    locations: {
      acceptable: cleanLocs(f.acceptable_locations),
      excluded: cleanLocs(f.excluded_locations),
      relocation: { willing: f.relocation_willing },
    },
    organizations: {
      target_companies: linesToList(f.target_companies),
      similar_to: linesToList(f.similar_to),
      preferred_organization_types: linesToList(f.org_types),
    },
    industries_and_domains: {
      preferred: linesToList(f.domains_preferred),
      excluded: linesToList(f.domains_excluded),
    },
    keywords: {
      required_any: linesToList(f.kw_required_any),
      required_all: linesToList(f.kw_required_all),
      preferred: linesToList(f.kw_preferred),
      excluded: linesToList(f.kw_excluded),
    },
    scrape_preferences: {
      include_remote_national_searches: f.include_remote_national,
      include_local_searches: f.include_local,
      include_company_board_searches: f.include_company_boards,
      include_general_job_boards: f.include_general_boards,
      max_results_per_task: f.max_results,
      freshness_hours: f.freshness_hours,
      cadence: f.cadence,
    },
  }
}

export default function SearchForm({
  initial,
  policies,
}: {
  initial: SearchConfigInput | null
  policies: Record<string, unknown> | null
}) {
  const save = useSaveSearch()

  const [form, setForm] = useState<SearchFormState>(() => (initial ? fromSearch(initial) : EMPTY))
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [derivedPolicies, setDerivedPolicies] = useState<Record<string, unknown> | null>(policies)

  const isOnboarding = !initial

  function set<K extends keyof SearchFormState>(key: K, value: SearchFormState[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  function setArrangement(key: ArrangementKey, patch: Partial<Arrangement>) {
    setForm((f) => ({
      ...f,
      arrangements: { ...f.arrangements, [key]: { ...f.arrangements[key], ...patch } },
    }))
  }

  function toggleEmployment(t: SearchEmploymentType, on: boolean) {
    setForm((f) => ({
      ...f,
      employment_types: on ? [...f.employment_types, t] : f.employment_types.filter((x) => x !== t),
    }))
  }

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setFieldErrors({})
    setSaveError(null)
    setSaved(false)
    try {
      const res = await save.mutateAsync(toSearch(form))
      setDerivedPolicies(res.policies)
      setSaved(true)
    } catch (err) {
      if (err instanceof ApiValidationError) {
        setFieldErrors(err.fields)
      } else {
        setSaveError(err instanceof Error ? err.message : String(err))
      }
    }
  }

  const waError = fieldErrors['work_constraints.work_arrangements']
  const empError = fieldErrors['work_constraints.employment_types.acceptable']

  return (
    <form className="flex flex-col gap-6" onSubmit={handleSubmit}>
      <Section title="Search targeting">
        {isOnboarding && (
          <div className="text-[12px] text-primary-hov bg-primary/10 border border-primary/25 rounded-md px-3 py-2.5">
            No search config yet — set your targets so the scraper knows what to pull.
          </div>
        )}

        <div className="grid grid-cols-2 gap-x-4 gap-y-4">
          <Field label="Display name" required error={fieldErrors['user.display_name']}>
            <Input
              value={form.display_name}
              onChange={(e) => set('display_name', e.target.value)}
            />
          </Field>
          <Field label="Email" required error={fieldErrors['user.email']}>
            <Input value={form.email} onChange={(e) => set('email', e.target.value)} />
          </Field>
          <Field label="Search profile name" required error={fieldErrors['search_profile.name']}>
            <Input
              value={form.profile_name}
              onChange={(e) => set('profile_name', e.target.value)}
            />
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
            <Input
              value={form.home_country}
              onChange={(e) => set('home_country', e.target.value)}
            />
          </Field>
        </div>
      </Section>

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

      <Section title="Locations">
        <LocationListEditor
          label="Acceptable locations"
          rows={form.acceptable_locations}
          onChange={(rows) => set('acceptable_locations', rows)}
        />
        <LocationListEditor
          label="Excluded locations"
          rows={form.excluded_locations}
          onChange={(rows) => set('excluded_locations', rows)}
        />
        <Checkbox
          label="Willing to relocate"
          checked={form.relocation_willing}
          onChange={(v) => set('relocation_willing', v)}
        />
      </Section>

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
          <Field
            label="Freshness (hours)"
            error={fieldErrors['scrape_preferences.freshness_hours']}
          >
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

      {derivedPolicies && (
        <Section title="Derived policies (read-only)">
          <p className="text-[11px] text-muted -mt-1">
            Computed from your search config — the gates applied before scoring.
          </p>
          <pre className="text-[11px] font-mono text-muted bg-bg-elevated border border-border rounded-md p-3 overflow-x-auto">
            {JSON.stringify(derivedPolicies, null, 2)}
          </pre>
        </Section>
      )}

      {saveError && (
        <div className="text-[12px] text-score-low bg-score-low/10 border border-score-low/20 rounded-md px-3 py-2">
          {saveError}
        </div>
      )}

      <div className="flex items-center justify-end gap-3">
        {saved && <span className="text-[11px] text-score-high">✓ Saved</span>}
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? 'Saving…' : 'Save search config'}
        </Button>
      </div>
    </form>
  )
}

function LocationListEditor({
  label,
  rows,
  onChange,
}: {
  label: string
  rows: LocRow[]
  onChange: (rows: LocRow[]) => void
}) {
  function update(i: number, patch: Partial<LocRow>) {
    onChange(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)))
  }
  function remove(i: number) {
    onChange(rows.filter((_, idx) => idx !== i))
  }
  function add() {
    onChange([...rows, { city: '', region: '', country: 'US' }])
  }

  return (
    <div className="flex flex-col gap-1.5">
      <label className={labelCls}>{label}</label>
      <div className="flex flex-col gap-2">
        {rows.map((r, i) => (
          <div key={i} className="grid grid-cols-[1fr_1fr_80px_auto] gap-2 items-center">
            <Input
              placeholder="City"
              value={r.city}
              onChange={(e) => update(i, { city: e.target.value })}
            />
            <Input
              placeholder="Region"
              value={r.region}
              onChange={(e) => update(i, { region: e.target.value })}
            />
            <Input
              placeholder="Country"
              value={r.country}
              onChange={(e) => update(i, { country: e.target.value })}
            />
            <button
              type="button"
              className="text-faint hover:text-score-low text-[16px] leading-none px-1.5"
              onClick={() => remove(i)}
              aria-label="Remove location"
            >
              ×
            </button>
          </div>
        ))}
        <button
          type="button"
          className="self-start text-[12px] text-primary-hov hover:text-primary"
          onClick={add}
        >
          + Add location
        </button>
      </div>
    </div>
  )
}
