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

  return (
    <div className="app">
      <header className="app-header">
        <span className="app-title">Job Scraper 9000</span>
        <nav className="tabs">
          <button className={`tab${tab === 'jobs' ? ' tab--active' : ''}`} onClick={() => setTab('jobs')}>
            Jobs{data ? ` (${displayTotal?.toLocaleString()})` : ''}
          </button>
          <button className={`tab${tab === 'workflow' ? ' tab--active' : ''}`} onClick={() => setTab('workflow')}>
            Workflow{trackedCount > 0 ? ` (${trackedCount})` : ''}
          </button>
          <button className={`tab${tab === 'summary' ? ' tab--active' : ''}`} onClick={() => setTab('summary')}>
            Summary
          </button>
        </nav>
        <button className="btn btn--sm" onClick={() => setAddJobOpen(true)}>+ Add job</button>
      </header>

      <div className="app-body">
        <div className={`filter-pane-wrapper${paneOpen ? '' : ' filter-pane-wrapper--collapsed'}`}>
          <FilterPane
            filters={filters}
            search={search}
            onFiltersChange={setFilters}
            onSearchChange={setSearch}
            visibleColumns={visible}
            onToggleColumn={toggle}
            total={displayTotal}
          />
          <button
            className="pane-toggle"
            onClick={() => setPaneOpen((v) => !v)}
            title={paneOpen ? 'Collapse filters' : 'Expand filters'}
          >
            {paneOpen ? '‹' : '›'}
          </button>
        </div>

        <div className="app-main">
          {tab === 'jobs' && (
            <>
              {isLoading && <div className="status-msg">Loading…</div>}
              {isError && (
                <div className="status-msg status-msg--error">
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
              {isLoading && <div className="status-msg">Loading…</div>}
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
