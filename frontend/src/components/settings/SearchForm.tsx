import { useEffect, useState } from 'react'
import { useSaveSearch } from '../../hooks/useSettings'
import { ApiValidationError, type FieldErrors } from '../../api'
import {
  type LinkedInExperienceCode,
  type SearchConfigInput,
  type SearchEmploymentType,
} from '../../types'
import { Button } from '@/components/ui/button'
import {
  EMPTY,
  fromSearch,
  normalizeLinkedInExperienceCodes,
  toSearch,
  type Arrangement,
  type ArrangementKey,
  type SearchFormState,
} from './searchFormState'
import { SearchTargetingSection } from './sections/SearchTargetingSection'
import { RolesSection } from './sections/RolesSection'
import { WorkConstraintsSection } from './sections/WorkConstraintsSection'
import { LocationsSection } from './sections/LocationsSection'
import { OrganizationsAndDomainsSection } from './sections/OrganizationsAndDomainsSection'
import { KeywordsSection } from './sections/KeywordsSection'
import { ScrapePreferencesSection } from './sections/ScrapePreferencesSection'
import { DerivedPoliciesSection } from './sections/DerivedPoliciesSection'
import type { SettingsSection } from './settingsSections'

export default function SearchForm({
  initial,
  policies,
  active,
  onDirtyChange,
}: {
  initial: SearchConfigInput | null
  policies: Record<string, unknown> | null
  /**
   * Which settings section is showing. The one search config spans two nav
   * sections, so the form stays mounted (preserving edits) and shows the
   * relevant group. `undefined` renders every group — the standalone mode the
   * unit tests exercise.
   */
  active?: SettingsSection
  /** Reports whether the form holds edits not yet saved (for the nav guard). */
  onDirtyChange?: (dirty: boolean) => void
}) {
  const save = useSaveSearch()

  const showTargeting = active === undefined || active === 'search-targeting'
  const showFilters = active === undefined || active === 'filters-policies'

  const [form, setForm] = useState<SearchFormState>(() => (initial ? fromSearch(initial) : EMPTY))
  // Serialized last-saved snapshot; the form is dirty while it diverges.
  const [baseline, setBaseline] = useState<string>(() => JSON.stringify(form))

  const dirty = JSON.stringify(form) !== baseline
  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange])
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

  function toggleLinkedInExperience(code: LinkedInExperienceCode, on: boolean) {
    setForm((f) => {
      const codes = on
        ? [...f.linkedin_experience_codes, code]
        : f.linkedin_experience_codes.filter((x) => x !== code)
      return {
        ...f,
        linkedin_experience_codes: normalizeLinkedInExperienceCodes(codes),
      }
    })
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
      setBaseline(JSON.stringify(form)) // saved snapshot is the new clean state
    } catch (err) {
      if (err instanceof ApiValidationError) {
        setFieldErrors(err.fields)
      } else {
        setSaveError(err instanceof Error ? err.message : String(err))
      }
    }
  }

  return (
    <form className="flex flex-col gap-6" onSubmit={handleSubmit}>
      {/* Search Targeting: what gets scraped. */}
      <div hidden={!showTargeting} className="flex flex-col gap-6">
        <SearchTargetingSection
          form={form}
          set={set}
          fieldErrors={fieldErrors}
          isOnboarding={isOnboarding}
        />
        <RolesSection form={form} set={set} fieldErrors={fieldErrors} />
        <LocationsSection form={form} set={set} />
        <OrganizationsAndDomainsSection form={form} set={set} />
        <KeywordsSection form={form} set={set} />
        <ScrapePreferencesSection
          form={form}
          set={set}
          toggleLinkedInExperience={toggleLinkedInExperience}
          fieldErrors={fieldErrors}
        />
      </div>

      {/* Filters & Policies: constraints applied before scoring. */}
      <div hidden={!showFilters} className="flex flex-col gap-6">
        <WorkConstraintsSection
          form={form}
          set={set}
          setArrangement={setArrangement}
          toggleEmployment={toggleEmployment}
          fieldErrors={fieldErrors}
        />
        <DerivedPoliciesSection policies={derivedPolicies} />
      </div>

      {/* One save persists the whole search config from either search tab. */}
      <div hidden={!showTargeting && !showFilters} className="flex flex-col gap-6">
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
      </div>
    </form>
  )
}
