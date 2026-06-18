import { useState } from 'react'
import { useSaveSearch } from '../../hooks/useSettings'
import { ApiValidationError, type FieldErrors } from '../../api'
import { type SearchConfigInput, type SearchEmploymentType } from '../../types'
import { Button } from '@/components/ui/button'
import {
  EMPTY,
  fromSearch,
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

  return (
    <form className="flex flex-col gap-6" onSubmit={handleSubmit}>
      <SearchTargetingSection
        form={form}
        set={set}
        fieldErrors={fieldErrors}
        isOnboarding={isOnboarding}
      />
      <RolesSection form={form} set={set} fieldErrors={fieldErrors} />
      <WorkConstraintsSection
        form={form}
        setArrangement={setArrangement}
        toggleEmployment={toggleEmployment}
        fieldErrors={fieldErrors}
      />
      <LocationsSection form={form} set={set} />
      <OrganizationsAndDomainsSection form={form} set={set} />
      <KeywordsSection form={form} set={set} />
      <ScrapePreferencesSection form={form} set={set} fieldErrors={fieldErrors} />
      <DerivedPoliciesSection policies={derivedPolicies} />

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
