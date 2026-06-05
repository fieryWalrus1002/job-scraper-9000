import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useJobs } from './hooks/useJobs'
import { useColumnConfig } from './hooks/useColumnConfig'
import { useApplications } from './hooks/useApplications'
import { useAuth } from './hooks/useAuth'
import { filtersFromParams, filtersToParams } from './lib/filters'
import type { Filters } from './types'
import FilterPane from './components/FilterPane'
import JobTable from './components/JobTable'
import JobDetailPanel from './components/JobDetailPanel'
import SummaryTab from './components/SummaryTab'
import WorkflowTab from './components/WorkflowTab/WorkflowTab'
import AddJobModal from './components/AddJobModal'
import { Button } from './components/ui/button'
import { cn } from './lib/utils'

export default function App() {
  const { principal, isLoading: authLoading, isAuthenticated } = useAuth()

  useEffect(() => {
    if (!authLoading && !isAuthenticated && !import.meta.env.DEV) {
      window.location.href = '/.auth/login/aad?post_login_redirect_uri=/'
    }
  }, [authLoading, isAuthenticated])

  if (authLoading) {
    return <div className="flex h-svh items-center justify-center text-muted text-sm">Loading…</div>
  }

  if (!isAuthenticated) {
    return (
      <div data-testid="auth-redirect" className="flex h-svh items-center justify-center text-muted text-sm">
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
  const tab = urlParams.get('tab') ?? 'jobs'
  const filters = filtersFromParams(urlParams)
  const [search, setSearch] = useState('')
  const [selectedHash, setSelectedHash] = useState<string | null>(null)
  const [paneOpen, setPaneOpen] = useState(true)
  const [addJobOpen, setAddJobOpen] = useState(false)

  const { data, isLoading, isError, error } = useJobs(filters)
  const { visible, toggle } = useColumnConfig()
  const { data: applications } = useApplications()

  function setFilters(next: Filters) {
    const p = filtersToParams(next)
    if (tab !== 'jobs') p.set('tab', tab)
    setUrlParams(p)
  }

  function setTab(t: string) {
    const p = filtersToParams(filters)
    if (t !== 'jobs') p.set('tab', t)
    setUrlParams(p)
  }

  const allItems = data?.items ?? []
  const filteredItems = search
    ? allItems.filter((j) => {
        const hay = `${j.title ?? ''} ${j.company ?? ''} ${j.score_rationale ?? ''}`.toLowerCase()
        return hay.includes(search.toLowerCase())
      })
    : allItems

  const displayTotal = search ? filteredItems.length : data?.total
  const trackedCount = applications?.size ?? 0

  const tabBtn =
    'group relative inline-flex items-center gap-2 h-8 px-3 border-none bg-transparent text-muted text-[13px] font-medium cursor-pointer rounded-md transition-all hover:text-fg hover:bg-hover/50'
  const tabBtnActive = 'text-fg bg-card border border-border shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]'
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
        <nav className="flex items-center gap-1.5">
          <button className={cn(tabBtn, tab === 'jobs' && tabBtnActive)} onClick={() => setTab('jobs')}>
            <span>Jobs</span>
            {data && (
              <span className={cn(tabCount, tab === 'jobs' && tabCountActive)}>
                {displayTotal?.toLocaleString()}
              </span>
            )}
          </button>
          <button className={cn(tabBtn, tab === 'workflow' && tabBtnActive)} onClick={() => setTab('workflow')}>
            <span>Workflow</span>
            {trackedCount > 0 && (
              <span className={cn(tabCount, tab === 'workflow' && tabCountActive)}>
                {trackedCount}
              </span>
            )}
          </button>
          <button className={cn(tabBtn, tab === 'summary' && tabBtnActive)} onClick={() => setTab('summary')}>
            <span>Summary</span>
          </button>
        </nav>
        <div className="flex-1" />
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
        <div className={cn('flex flex-row shrink-0 relative transition-[width] duration-200 ease', paneOpen ? 'w-[224px]' : 'w-5')}>
          <FilterPane
            filters={filters}
            search={search}
            onFiltersChange={setFilters}
            onSearchChange={setSearch}
            visibleColumns={visible}
            onToggleColumn={toggle}
            total={displayTotal}
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

        <div className="flex-1 flex flex-col overflow-hidden">
          {tab === 'jobs' && (
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
                  onSelect={setSelectedHash}
                  applications={applications}
                />
              )}
            </>
          )}

          {tab === 'workflow' && (
            <WorkflowTab onSelectJob={setSelectedHash} />
          )}

          {tab === 'summary' && (
            <>
              {isLoading && <div className="py-12 text-center text-muted text-sm">Loading…</div>}
              {!isLoading && !isError && <SummaryTab items={filteredItems} />}
            </>
          )}
        </div>
      </div>

      {selectedHash && (
        <JobDetailPanel
          dedupHash={selectedHash}
          onClose={() => setSelectedHash(null)}
          application={applications?.get(selectedHash)}
        />
      )}

      {addJobOpen && (
        <AddJobModal
          onClose={() => setAddJobOpen(false)}
          onSuccess={() => { setAddJobOpen(false); setTab('workflow') }}
        />
      )}
    </div>
  )
}
