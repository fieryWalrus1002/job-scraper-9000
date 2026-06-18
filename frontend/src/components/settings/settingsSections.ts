/** The four Phase 18 settings sections (#367). One `/settings` route drives
 * these via internal nav state. `SearchForm` spans two of them
 * (search-targeting + filters-policies) since both edit the one search config
 * saved through a single endpoint. */
export type SettingsSection = 'profile' | 'search-targeting' | 'filters-policies' | 'account'

export const SETTINGS_SECTIONS: {
  key: SettingsSection
  label: string
  description: string
}[] = [
  {
    key: 'profile',
    label: 'Profile',
    description: 'The candidate profile your jobs are scored against.',
  },
  {
    key: 'search-targeting',
    label: 'Search Targeting',
    description: 'What gets scraped: titles, locations, organizations, keywords, and cadence.',
  },
  {
    key: 'filters-policies',
    label: 'Filters & Policies',
    description: 'Constraints applied before scoring, plus the derived policy preview.',
  },
  {
    key: 'account',
    label: 'Account & Activity',
    description: 'Your account and the overnight pipeline.',
  },
]
