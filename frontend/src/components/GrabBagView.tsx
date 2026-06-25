import { useCallback, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ArrowRight, Trash2, RefreshCw } from 'lucide-react'
import { useGrabBag } from '../hooks/useGrabBag'
import { useApplications } from '../hooks/useApplications'
import { GrabBagCard } from './GrabBagCard'
import { useTriageKeys } from './JobTable/useTriageKeys'
import { useTriageAction } from '../hooks/useTriage'
import type { JobSummary } from '../types'
import type { JobDetailSurface } from './JobDetailPanel'
import { Button } from './ui/button'

/**
 * Generate a random 32-bit signed positive seed for grab-bag sampling.
 */
function generateSeed(): number {
  return Math.floor(Math.random() * 2_147_483_647)
}

interface Props {
  onSelect: (
    hash: string,
    surface: JobDetailSurface,
    applicationSnapshot?: unknown,
    summary?: JobSummary,
  ) => void
}

/**
 * Grab-bag triage surface. Shows a seeded batch of swipeable cards from
 * `GET /jobs?mode=grabbag`. Seed lives in the URL (`?seed=…`) so refresh
 * returns the same batch. "New batch" generates a fresh seed and refetches.
 *
 * Triage uses the existing applications mutation — a committed card leaves
 * the batch client-side (filtered against the applications map). An exhausted
 * pool renders an explicit "all caught up" state.
 */
export function GrabBagView({ onSelect }: Props) {
  const [urlParams, setUrlParams] = useSearchParams()
  const { data: applications } = useApplications()

  // Read seed from URL; generate one when absent OR malformed. A hand-edited
  // `?seed=abc` parses to NaN, which would otherwise be sent as `seed=NaN` and
  // wedge the query — treat any non-integer/negative seed as absent and reroll.
  const urlSeed = urlParams.get('seed')
  const parsedSeed = urlSeed !== null ? Number(urlSeed) : NaN
  const seedIsValid = Number.isInteger(parsedSeed) && parsedSeed >= 0
  const seed = seedIsValid ? parsedSeed : generateSeed()

  // Write the seed to the URL on mount when it was generated (absent/invalid),
  // so refresh is stable and a garbage seed self-heals to a valid one.
  useEffect(() => {
    if (!seedIsValid) {
      setUrlParams({ seed: String(seed) }, { replace: true })
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps -- only run once on mount

  const { data, isLoading, isError, error } = useGrabBag(seed)

  // Filter out triaged jobs client-side (mirrors `untriagedJobs` in App.tsx).
  const visibleJobs = (data?.items ?? []).filter((j) => !applications?.has(j.dedup_hash))
  const isCaughtUp = !isLoading && !isError && visibleJobs.length === 0

  // Triage a job by creating an application row (from: null → to: status).
  // The applications mutation invalidates the applications query, which triggers
  // a re-render and filters the triaged card out of visibleJobs.
  const { triage } = useTriageAction()
  const triageJob = useCallback(
    (job: JobSummary, to: 'passed' | 'maybe') => {
      triage({ dedupHash: job.dedup_hash, from: null, to })
    },
    [triage],
  )

  // "New batch": generate a fresh seed, write it to URL (replace), and refetch.
  const handleNewBatch = useCallback(() => {
    const newSeed = generateSeed()
    setUrlParams({ seed: String(newSeed) }, { replace: true })
  }, [setUrlParams])

  // Keyboard triage via useTriageKeys.
  const handleTrash = useCallback(
    (index: number) => {
      const job = visibleJobs[index]
      if (!job) return
      triageJob(job, 'passed')
    },
    [visibleJobs, triageJob],
  )

  const handleShortlist = useCallback(
    (index: number) => {
      const job = visibleJobs[index]
      if (!job) return
      triageJob(job, 'maybe')
    },
    [visibleJobs, triageJob],
  )

  const handleOpen = useCallback(
    (index: number) => {
      const job = visibleJobs[index]
      if (!job) return
      onSelect(job.dedup_hash, 'grabbag', undefined, job)
    },
    [visibleJobs, onSelect],
  )

  const { focusedIndex } = useTriageKeys({
    count: visibleJobs.length,
    onTrash: handleTrash,
    onShortlist: handleShortlist,
    onOpen: handleOpen,
  })

  // Swipe action mapping: left → trash (passed), right → shortlist (maybe).
  const swipeActions = {
    left: { to: 'passed' as const, label: 'Trash', polarity: 'negative' as const, icon: Trash2 },
    right: {
      to: 'maybe' as const,
      label: 'Shortlist',
      polarity: 'positive' as const,
      icon: ArrowRight,
    },
  }

  if (isLoading) return <EmptyState message="Loading…" sub="" />
  if (isError) {
    return <EmptyState message="Failed to load grab bag" sub={(error as Error).message} error />
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Top bar: batch info + New batch button */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-border shrink-0">
        <div className="text-[13px] text-muted">
          {data?.total != null && (
            <span>
              {visibleJobs.length} of {data.total} jobs
            </span>
          )}
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleNewBatch}
          className="text-[12px] gap-1.5"
        >
          <RefreshCw className="size-3" />
          New batch
        </Button>
      </div>

      {/* Card grid */}
      <div className="flex-1 overflow-auto p-4">
        {isCaughtUp ? (
          <EmptyState
            message="All caught up!"
            sub="No more jobs in the pool. Run a new scrape or adjust your filters."
          />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 max-w-5xl mx-auto">
            {visibleJobs.map((job, i) => (
              <GrabBagCard
                key={job.dedup_hash}
                job={job}
                actions={swipeActions}
                onSelect={(j) => onSelect(j.dedup_hash, 'grabbag', undefined, j)}
                isFocused={i === focusedIndex}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function EmptyState({
  message,
  sub,
  error: isError,
}: {
  message: string
  sub: string
  error?: boolean
}) {
  return (
    <div className="flex-1 flex items-center justify-center py-20 text-center">
      <div>
        <div className={isError ? 'text-sm text-score-low' : 'text-muted text-sm'}>{message}</div>
        {sub && <div className="text-faint text-xs mt-1.5">{sub}</div>}
      </div>
    </div>
  )
}
