import { useState, useEffect } from 'react'
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useSearchParams,
} from 'react-router-dom'
import { useJobs, PAGE_SIZE } from './hooks/useJobs'
import { useColumnConfig } from './hooks/useColumnConfig'
import { useApplications } from './hooks/useApplications'
import { useAuth } from './hooks/useAuth'
import { filtersFromParams, filtersToParams } from './lib/filters'
import type { Application, ApplicationStatus, Filters } from './types'
import { AppHeader, type FunnelPath } from './components/AppHeader'
import FilterPane from './components/FilterPane'
import JobTable from './components/JobTable'
import { JobDetailPanel, type JobDetailSurface } from './components/JobDetailPanel'
import SettingsPage from './components/SettingsPage'
import AddJobModal from './components/AddJobModal'
import { TriageApplicationTable } from './components/TriageApplicationTable'
import { TrackingBoard } from './components/TrackingBoard'
import { TRACKING_STATUSES } from './lib/trackingGroups'
import { ShortlistRowActions } from './components/ShortlistRowActions'
import { TrashRowActions } from './components/TrashRowActions'
import { cn } from './lib/utils'

const SHORTLIST_STATUSES: ApplicationStatus[] = ['maybe']
const TRASH_STATUSES: ApplicationStatus[] = ['passed']

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
  const [selectedJob, setSelectedJob] = useState<{
    hash: string
    path: string
    surface: JobDetailSurface
    applicationSnapshot?: Application
  } | null>(null)
  const [paneOpen, setPaneOpen] = useState(true)
  const [addJobOpen, setAddJobOpen] = useState(false)

  const [page, setPage] = useState(0)
  const { data, isLoading, isError, error } = useJobs(filters, page)

  // Clamp page when total shrinks (e.g. jobs deleted, reindexed) so we don't
  // sit on an empty page while results exist on earlier pages. Adjusting state
  // during render (guarded) is React's recommended pattern here — it re-renders
  // before paint, avoiding the cascading-render an effect would cause.
  if (data?.total && data.total > 0) {
    const maxPage = Math.ceil(data.total / PAGE_SIZE) - 1
    if (page > maxPage) setPage(maxPage)
  }

  const { visible, toggle } = useColumnConfig()
  const { data: applications } = useApplications()

  function setFilters(next: Filters, opts?: { replace?: boolean }) {
    // The debounced search path passes replace:true so settling keystrokes
    // don't each stack a browser-history entry.
    setUrlParams(filtersToParams(next), opts?.replace ? { replace: true } : undefined)
    setPage(0)
  }

  const currentPath = normalizePath(location.pathname)

  function selectCurrentJob(
    hash: string,
    surface: JobDetailSurface,
    applicationSnapshot?: Application,
  ) {
    setSelectedJob({ hash, path: currentPath, surface, applicationSnapshot })
  }

  const allApplications = Array.from(applications?.values() ?? [])
  const shortlistCount = countStatuses(allApplications, SHORTLIST_STATUSES)
  const trackingCount = countStatuses(allApplications, TRACKING_STATUSES)
  const trashCount = countStatuses(allApplications, TRASH_STATUSES)
  const jobsCount = data?.total

  const tabCounts: Record<FunnelPath, number | undefined> = {
    '/trash': trashCount,
    '/jobs': jobsCount,
    '/shortlist': shortlistCount,
    '/tracking': trackingCount,
  }

  return (
    <div className="flex flex-col h-svh overflow-hidden">
      <AppHeader email={email} counts={tabCounts} onAddJob={() => setAddJobOpen(true)} />

      <div className="flex-1 flex flex-row overflow-hidden">
        <Routes>
          <Route
            path="/jobs"
            element={
              <div
                className={cn(
                  'flex flex-row shrink-0 relative transition-[width] duration-200 ease',
                  paneOpen ? 'w-[224px]' : 'w-5',
                )}
              >
                <FilterPane
                  filters={filters}
                  onFiltersChange={setFilters}
                  visibleColumns={visible}
                  onToggleColumn={toggle}
                  total={jobsCount}
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
            }
          />
        </Routes>

        <div className="flex-1 flex flex-col overflow-hidden">
          <Routes>
            <Route
              path="/"
              element={<Navigate to={{ pathname: '/jobs', search: location.search }} replace />}
            />
            <Route
              path="/jobs"
              element={
                <>
                  {isLoading && (
                    <div className="py-12 text-center text-muted text-sm">Loading…</div>
                  )}
                  {isError && (
                    <div className="py-12 text-center text-score-low text-sm">
                      Failed to load jobs: {(error as Error).message}
                    </div>
                  )}
                  {!isLoading && !isError && (
                    <JobTable
                      items={data?.items ?? []}
                      visibleColumns={visible}
                      onSelect={(hash) => selectCurrentJob(hash, 'jobs')}
                      applications={applications}
                      page={page}
                      pageSize={PAGE_SIZE}
                      total={data?.total}
                      onPageChange={setPage}
                    />
                  )}
                </>
              }
            />
            <Route
              path="/shortlist"
              element={
                <TriageApplicationTable
                  statuses={SHORTLIST_STATUSES}
                  onSelect={(app) => selectCurrentJob(app.dedup_hash, 'shortlist', app)}
                  emptyMessage="No shortlisted jobs yet."
                  renderRowActions={(app) => <ShortlistRowActions application={app} />}
                />
              }
            />
            <Route
              path="/tracking"
              element={
                <TrackingBoard
                  onSelect={(app) => selectCurrentJob(app.dedup_hash, 'tracking', app)}
                />
              }
            />
            <Route
              path="/trash"
              element={
                <TriageApplicationTable
                  statuses={TRASH_STATUSES}
                  onSelect={(app) => selectCurrentJob(app.dedup_hash, 'trash', app)}
                  emptyMessage="Trash is empty."
                  renderRowActions={(app) => <TrashRowActions application={app} />}
                />
              }
            />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/jobs" replace />} />
          </Routes>
        </div>
      </div>

      {selectedJob?.path === currentPath && (
        <JobDetailPanel
          dedupHash={selectedJob.hash}
          onClose={() => setSelectedJob(null)}
          application={applications?.get(selectedJob.hash) ?? selectedJob.applicationSnapshot}
          surface={selectedJob.surface}
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

function normalizePath(pathname: string): string {
  return pathname.replace(/\/+$/, '') || '/'
}
