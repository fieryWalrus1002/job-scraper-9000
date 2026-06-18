// Shared state model + converters for the search settings form. The section
// components under settings/sections/ render slices of SearchFormState; the
// SearchForm orchestrator owns the state and wires these converters to the API.
import {
  DEFAULT_LINKEDIN_EXPERIENCE_CODES,
  LINKEDIN_EXPERIENCE_CODES,
  type LinkedInExperienceCode,
  type SearchConfigInput,
  type SearchEmploymentType,
  type SearchSalaryFloorK,
} from '../../types'
import { linesToList, listToLines } from './formKit'

export type Arrangement = { acceptable: boolean; preferred: boolean; required: boolean }
export type ArrangementKey = 'remote' | 'hybrid' | 'onsite'
export type LocRow = { city: string; region: string; country: string }

export interface SearchFormState {
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
  max_travel_days: number | null
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
  salary_floor_k: SearchSalaryFloorK | null
  linkedin_experience_codes: LinkedInExperienceCode[]
}

/** Generic single-field setter shared by every section component. */
export type SetField = <K extends keyof SearchFormState>(key: K, value: SearchFormState[K]) => void

const ARR_DEFAULT: Arrangement = { acceptable: true, preferred: false, required: false }

export function normalizeLinkedInExperienceCodes(
  codes: readonly LinkedInExperienceCode[],
): LinkedInExperienceCode[] {
  return LINKEDIN_EXPERIENCE_CODES.filter((code) => codes.includes(code))
}

export const EMPTY: SearchFormState = {
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
  max_travel_days: null,
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
  salary_floor_k: null,
  linkedin_experience_codes: normalizeLinkedInExperienceCodes(DEFAULT_LINKEDIN_EXPERIENCE_CODES),
}

function arr(a: Arrangement | undefined): Arrangement {
  return { ...ARR_DEFAULT, ...(a ?? {}) }
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

export function fromSearch(s: SearchConfigInput): SearchFormState {
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
    max_travel_days: s.work_constraints?.max_travel_days ?? null,
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
    salary_floor_k: s.scrape_preferences?.salary_floor_k ?? null,
    linkedin_experience_codes: normalizeLinkedInExperienceCodes(
      s.scrape_preferences?.linkedin_experience_codes ?? DEFAULT_LINKEDIN_EXPERIENCE_CODES,
    ),
  }
}

export function toSearch(f: SearchFormState): SearchConfigInput {
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
      max_travel_days: f.max_travel_days,
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
      salary_floor_k: f.salary_floor_k,
      linkedin_experience_codes: f.linkedin_experience_codes,
    },
  }
}
