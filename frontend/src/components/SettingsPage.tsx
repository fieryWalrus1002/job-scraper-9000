import { useSettings } from '../hooks/useSettings'
import type { CandidateProfileInput, SearchConfigInput } from '../types'
import ProfileForm from './settings/ProfileForm'
import SearchForm from './settings/SearchForm'

export default function SettingsPage() {
  const { data, isLoading, isError, error } = useSettings()

  if (isLoading) return <div className="p-6 text-muted text-sm">Loading…</div>
  if (isError)
    return (
      <div className="p-6 text-score-low text-sm">Failed to load settings: {error.message}</div>
    )

  return (
    <div className="p-6 overflow-y-auto">
      <div className="max-w-[720px] mx-auto flex flex-col gap-8">
        <div>
          <h1 className="text-[18px] font-semibold tracking-tight text-fg">Settings</h1>
          <p className="text-[12px] text-muted mt-1">
            Your profile and search config drive what gets scraped and how jobs are scored. Changes
            take effect at your next overnight run — they don't re-score existing jobs.
          </p>
        </div>

        {/* Remount each form when its loaded identity changes so the lazily
            initialized state re-seeds (avoids a setState-in-effect). */}
        <ProfileForm
          key={`profile-${data?.profile_version ?? 'new'}`}
          initial={(data?.profile as CandidateProfileInput | null) ?? null}
          version={data?.profile_version ?? null}
        />
        <SearchForm
          key={`search-${data?.search_updated_at ?? 'new'}`}
          initial={(data?.search as SearchConfigInput | null) ?? null}
          policies={(data?.policies as Record<string, unknown> | null) ?? null}
        />
      </div>
    </div>
  )
}
