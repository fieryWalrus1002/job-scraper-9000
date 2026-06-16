import { useState, useEffect } from 'react'
import { Navigate, NavLink, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useJobs } from './hooks/useJobs'
import { useColumnConfig } from './hooks/useColumnConfig'
import { useApplications } from './hooks/useApplications'
import { useAuth } from './hooks/useAuth'
import { filtersFromParams, filtersToParams } from './lib/filters'
import type { Application, ApplicationStatus, Filters, JobSummary } from './types'
import FilterPane from './components/FilterPane'
import JobTable from './components/JobTable'
import { JobDetailPanel } from './components/JobDetailPanel'
import SettingsPage from './components/SettingsPage'
import AddJobModal from './components/AddJobModal'
import { TriageApplicationTable } from './components/TriageApplicationTable'
import { Button } from './components/ui/button'
import { cn } from './lib/utils'

const SHORTLIST_STATUSES: ApplicationStatus[] = ['maybe']
const TRACKING_STATUSES: ApplicationStatus[] = [
  'to_apply',
  'applied',
  'screening',
  'interview',
  'offer',
  'rejected',
  'candidate_withdrew',
  'hired',
  'ghosted',
]
const TRASH_STATUSES: ApplicationStatus[] = ['passed']

type FunnelPath = '/trash' | '/jobs' | '/shortlist' | '/tracking'

const FUNNEL_TABS: { path: FunnelPath; label: string; muted?: boolean }[] = [
  { path: '/trash', label: 'Trash', muted: true },
  { path: '/jobs', label: 'Jobs' },
  { path: '/shortlist', label: 'Shortlist' },
  { path: '/tracking', label: 'Tracking' },
]

export default function App() {
  const { principal, isLoading: authLoading, isAuthenticated } = useAuth()

  useEffect(() => {
    if (!authLoading && !isAuthenticated && !import.meta.env.DEV) {
      window.location.assign('/.auth/login/aad?post_login_redirect_uri=/')
    }
  }, [authLoading, isAuthenticated])

  if (authLoading) {
    return <div className="flex h-svh items-center justify-center text-muted text-sm">Loading…</div>
  }

  if (!isAuthenticated) {
    return (
      <div
        data-testid="auth-redirect"
        className="flex h-svh items-center justify-center text-muted text-sm"
      >
        {import.meta.env.DEV
          ? 'Not authenticated — set VITE_AUTH_BYPASS=1 in frontend/.env.local'
          : 'Signing in…'}
      </div>
    )
  }

  return <AppShell email={principal!.userDetails} />
}

function AppShell({ email }: { email: string }) {
  const [urlParams, setUrlParams] = useSearchParams()
  const location = useLocation()
  const navigate = useNavigate()
  const filters = filtersFromParams(urlParams)
  const [search, setSearch] = useState('')
  const [selectedJob, setSelectedJob] = useState<{ hash: string; path: string } | null>(null)
  const [paneOpen, setPaneOpen] = useState(true)
  const [addJobOpen, setAddJobOpen] = useState(false)

  const { data, isLoading, isError, error } = useJobs(filters)
  const { visible, toggle } = useColumnConfig()
  const { data: applications } = useApplications()

  function setFilters(next: Filters) {
    setUrlParams(filtersToParams(next))
  }

  const currentPath = normalizePath(location.pathname)

  function selectCurrentJob(hash: string) {
    setSelectedJob({ hash, path: currentPath })
  }

  const allItems = data?.items ?? []
  const filteredItems = filterJobsBySearch(allItems, search)

  const allApplications = Array.from(applications?.values() ?? [])
  const shortlistCount = countStatuses(allApplications, SHORTLIST_STATUSES)
  const trackingCount = countStatuses(allApplications, TRACKING_STATUSES)
  const trashCount = countStatuses(allApplications, TRASH_STATUSES)
  const jobsCount = search ? filteredItems.length : data?.total

  const activeTotal =
    currentPath === '/trash'
      ? trashCount
      : currentPath === '/shortlist'
        ? shortlistCount
        : currentPath === '/tracking'
          ? trackingCount
          : jobsCount
  const showFilterPane = currentPath === '/jobs'

  const tabBtn =
    'group relative inline-flex items-center gap-2 h-8 px-3 border-none bg-transparent text-muted text-[13px] font-medium cursor-pointer rounded-md transition-all hover:text-fg hover:bg-hover/50 no-underline'
  const tabBtnActive =
    'text-fg bg-card border border-border shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]'
  const tabBtnMuted = 'text-faint hover:text-muted'
  const tabCount =
    'inline-flex items-center justify-center min-w-[20px] h-[18px] px-1.5 rounded text-[10.5px] font-mono tabular-nums font-medium ' +
    'bg-bg-elevated/80 text-faint border border-border/60 ' +
    'group-hover:text-muted group-hover:border-border transition-colors'
  const tabCountActive = 'text-primary-hov bg-primary/15 border-primary/30'

  return (
    <div className="flex flex-col h-svh overflow-hidden">
      <header className="flex items-center gap-6 px-5 h-[52px] border-b border-border shrink-0 bg-card/60 backdrop-blur-md">
        <div className="flex items-center gap-2.5">
          <div className="size-6 rounded-md bg-gradient-to-br from-primary to-primary-dim flex items-center justify-center shadow-[inset_0_1px_0_rgba(255,255,255,0.2),0_1px_4px_rgba(99,102,241,0.4)]">
            <span className="text-[11px] font-bold text-white tracking-tight">JS</span>
          </div>
          <span className="font-semibold text-[14px] text-fg whitespace-nowrap tracking-tight">
            Job Scraper <span className="text-muted font-normal">9000</span>
          </span>
        </div>
        <nav className="flex items-center gap-1.5" aria-label="Triage funnel">
          {FUNNEL_TABS.map((tab) => {
            const count =
              tab.path === '/trash'
                ? trashCount
                : tab.path === '/jobs'
                  ? jobsCount
                  : tab.path === '/shortlist'
                    ? shortlistCount
                    : trackingCount
            return (
              <NavLink
                key={tab.path}
                to={{ pathname: tab.path, search: tab.path === '/jobs' ? location.search : '' }}
                className={({ isActive }) =>
                  cn(tabBtn, tab.muted && tabBtnMuted, isActive && tabBtnActive)
                }
              >
                {({ isActive }) => (
                  <>
                    <span>{tab.label}</span>
                    {count != null && (count > 0 || tab.path !== '/trash') && (
                      <span className={cn(tabCount, isActive && tabCountActive)}>
                        {count.toLocaleString()}
                      </span>
                    )}
                  </>
                )}
              </NavLink>
            )
          })}
        </nav>
        <div className="flex-1" />
        <button
          type="button"
          className={cn(
            'bg-transparent border-none p-0 text-[12px] cursor-pointer transition-colors',
            currentPath === '/settings' ? 'text-fg' : 'text-muted hover:text-fg',
          )}
          onClick={() => navigate('/settings')}
        >
          Settings
        </button>
        <a
          href="/.auth/logout"
          className="text-[12px] text-muted hover:text-fg transition-colors"
          title="Sign out"
        >
          {email}
        </a>
        <Button onClick={() => setAddJobOpen(true)}>
          <span className="text-[15px] leading-none mr-0.5">+</span>
          Add job
        </Button>
      </header>

      <div className="flex-1 flex flex-row overflow-hidden">
        {showFilterPane && (
          <div
            className={cn(
              'flex flex-row shrink-0 relative transition-[width] duration-200 ease',
              paneOpen ? 'w-[224px]' : 'w-5',
            )}
          >
            <FilterPane
              filters={filters}
              search={search}
              onFiltersChange={setFilters}
              onSearchChange={setSearch}
              visibleColumns={visible}
              onToggleColumn={toggle}
              total={activeTotal}
              collapsed={!paneOpen}
            />
            <button
              className="absolute right-0 top-1/2 -translate-y-1/2 w-4 h-10 bg-card border border-border border-l-0 rounded-r-md text-faint text-xs cursor-pointer flex items-center justify-center z-10 p-0 hover:text-fg hover:bg-hover hover:border-border-strong transition-colors"
              onClick={() => setPaneOpen((v) => !v)}
              title={paneOpen ? 'Collapse filters' : 'Expand filters'}
              aria-label={paneOpen ? 'Collapse filters' : 'Expand filters'}
            >
              {paneOpen ? '‹' : '›'}
            </button>
          </div>
        )}

        <div className="flex-1 flex flex-col overflow-hidden">
          {currentPath === '/' && (
            <Navigate to={{ pathname: '/jobs', search: location.search }} replace />
          )}

          {currentPath === '/jobs' && (
            <>
              {isLoading && <div className="py-12 text-center text-muted text-sm">Loading…</div>}
              {isError && (
                <div className="py-12 text-center text-score-low text-sm">
                  Failed to load jobs: {(error as Error).message}
                </div>
              )}
              {!isLoading && !isError && (
                <JobTable
                  items={filteredItems}
                  visibleColumns={visible}
                  onSelect={selectCurrentJob}
                  applications={applications}
                />
              )}
            </>
          )}

          {currentPath === '/shortlist' && (
            <TriageApplicationTable
              statuses={SHORTLIST_STATUSES}
              onSelect={selectCurrentJob}
              emptyMessage="No shortlisted jobs yet."
            />
          )}

          {currentPath === '/tracking' && (
            <TriageApplicationTable
              statuses={TRACKING_STATUSES}
              onSelect={selectCurrentJob}
              emptyMessage="No tracking jobs yet."
            />
          )}

          {currentPath === '/trash' && (
            <TriageApplicationTable
              statuses={TRASH_STATUSES}
              onSelect={selectCurrentJob}
              emptyMessage="Trash is empty."
            />
          )}

          {currentPath === '/settings' && <SettingsPage />}

          {!['/', '/jobs', '/shortlist', '/tracking', '/trash', '/settings'].includes(
            currentPath,
          ) && <Navigate to="/jobs" replace />}
        </div>
      </div>

      {selectedJob?.path === currentPath && (
        <JobDetailPanel
          dedupHash={selectedJob.hash}
          onClose={() => setSelectedJob(null)}
          application={applications?.get(selectedJob.hash)}
        />
      )}

      {addJobOpen && (
        <AddJobModal
          onClose={() => setAddJobOpen(false)}
          onSuccess={() => {
            setAddJobOpen(false)
            navigate('/shortlist')
          }}
        />
      )}
    </div>
  )
}

function countStatuses(applications: Application[], statuses: ApplicationStatus[]): number {
  return applications.filter((app) => statuses.includes(app.status)).length
}

function filterJobsBySearch(items: JobSummary[], search: string): JobSummary[] {
  const needle = search.trim().toLowerCase()
  if (!needle) return items
  return items.filter((j) => {
    const hay = `${j.title ?? ''} ${j.company ?? ''} ${j.score_rationale ?? ''}`.toLowerCase()
    return hay.includes(needle)
  })
}

function normalizePath(pathname: string): string {
  return pathname.replace(/\/+$/, '') || '/'
}
