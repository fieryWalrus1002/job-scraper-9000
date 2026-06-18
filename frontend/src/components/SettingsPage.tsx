import { useState } from 'react'
import { useSettings } from '../hooks/useSettings'
import type { CandidateProfileInput, SearchConfigInput } from '../types'
import ProfileForm from './settings/ProfileForm'
import SearchForm from './settings/SearchForm'
import { AccountSection } from './settings/sections/AccountSection'
import { SETTINGS_SECTIONS, type SettingsSection } from './settings/settingsSections'

export default function SettingsPage() {
  const { data, isLoading, isError, error } = useSettings()
  const [active, setActive] = useState<SettingsSection>('profile')

  if (isLoading) return <div className="p-6 text-muted text-sm">Loading…</div>
  if (isError)
    return (
      <div className="p-6 text-score-low text-sm">Failed to load settings: {error.message}</div>
    )

  const meta = SETTINGS_SECTIONS.find((s) => s.key === active)!

  return (
    <div className="p-6 overflow-y-auto">
      <div className="max-w-[920px] mx-auto flex flex-col gap-6">
        <div>
          <h1 className="text-[18px] font-semibold tracking-tight text-fg">Settings</h1>
          <p className="text-[12px] text-muted mt-1">
            Your profile and search config drive what gets scraped and how jobs are scored. Changes
            take effect at your next overnight run — they don't re-score existing jobs.
          </p>
        </div>

        <div className="flex gap-8 items-start">
          <nav className="flex flex-col gap-0.5 w-[180px] shrink-0" aria-label="Settings sections">
            {SETTINGS_SECTIONS.map((s) => (
              <button
                key={s.key}
                type="button"
                onClick={() => setActive(s.key)}
                aria-current={active === s.key ? 'page' : undefined}
                className={`text-left text-[13px] rounded-md px-3 py-1.5 transition-colors ${
                  active === s.key
                    ? 'bg-bg-elevated text-fg font-medium'
                    : 'text-muted hover:text-fg hover:bg-bg-elevated/50'
                }`}
              >
                {s.label}
              </button>
            ))}
          </nav>

          <div className="flex-1 min-w-0 flex flex-col gap-6">
            <div>
              <h2 className="text-[14px] font-semibold text-fg">{meta.label}</h2>
              <p className="text-[12px] text-muted mt-0.5">{meta.description}</p>
            </div>

            {/* Every panel stays mounted (toggled with `hidden`) so unsaved
                edits survive section switches. */}
            <div hidden={active !== 'profile'}>
              <ProfileForm
                key={`profile-${data?.profile_version ?? 'new'}`}
                initial={(data?.profile as CandidateProfileInput | null) ?? null}
                version={data?.profile_version ?? null}
              />
            </div>

            <SearchForm
              key={`search-${data?.search_updated_at ?? 'new'}`}
              initial={(data?.search as SearchConfigInput | null) ?? null}
              policies={(data?.policies as Record<string, unknown> | null) ?? null}
              active={active}
            />

            <div hidden={active !== 'account'}>
              <AccountSection />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
