import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useJobs } from './hooks/useJobs'
import { useColumnConfig } from './hooks/useColumnConfig'
import { useApplications } from './hooks/useApplications'
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

  const tabBtn = 'group relative px-3 py-1.5 border-none bg-transparent text-muted text-[13px] font-medium cursor-pointer rounded-md transition-all hover:text-fg'
  const tabBtnActive = 'text-fg bg-card border border-border shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]'
  const tabCount = 'ml-1.5 text-[11px] font-mono text-faint group-hover:text-muted transition-colors'
  const tabCountActive = 'text-primary-hov'

  return (
    <div className="flex flex-col h-svh overflow-hidden">
      <header className="flex items-center gap-5 px-5 h-[52px] border-b border-border shrink-0 bg-card/60 backdrop-blur-md">
        <div className="flex items-center gap-2">
          <div className="size-6 rounded-md bg-gradient-to-br from-primary to-primary-dim flex items-center justify-center shadow-[inset_0_1px_0_rgba(255,255,255,0.2),0_1px_4px_rgba(99,102,241,0.4)]">
            <span className="text-[11px] font-bold text-white tracking-tight">JS</span>
          </div>
          <span className="font-semibold text-[14px] text-fg whitespace-nowrap tracking-tight">Job Scraper <span className="text-muted font-normal">9000</span></span>
        </div>
        <nav className="flex gap-1 ml-2">
          <button className={cn(tabBtn, tab === 'jobs' && tabBtnActive)} onClick={() => setTab('jobs')}>
            Jobs
            {data && <span className={cn(tabCount, tab === 'jobs' && tabCountActive)}>{displayTotal?.toLocaleString()}</span>}
          </button>
          <button className={cn(tabBtn, tab === 'workflow' && tabBtnActive)} onClick={() => setTab('workflow')}>
            Workflow
            {trackedCount > 0 && <span className={cn(tabCount, tab === 'workflow' && tabCountActive)}>{trackedCount}</span>}
          </button>
          <button className={cn(tabBtn, tab === 'summary' && tabBtnActive)} onClick={() => setTab('summary')}>
            Summary
          </button>
        </nav>
        <div className="flex-1" />
        <Button onClick={() => setAddJobOpen(true)} size="sm">
          <span className="text-base leading-none">+</span> Add job
        </Button>
      </header>

      <div className="flex-1 flex flex-row overflow-hidden">
        <div className={cn('flex flex-row shrink-0 relative transition-[width] duration-200 ease', paneOpen ? 'w-[212px]' : 'w-5')}>
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
