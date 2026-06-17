import type { JobSummary } from '../../../types'

/** Title with an optional external link to the original posting. */
export function TitleCell({ job }: { job: JobSummary }) {
  return (
    <div className="flex items-center gap-1.5 min-w-0">
      <span className="overflow-hidden text-ellipsis whitespace-nowrap flex-1 min-w-0">
        {job.title ?? '—'}
      </span>
      {job.source_url && (
        <a
          className="shrink-0 text-[11px] text-muted no-underline opacity-60 leading-none hover:text-primary hover:opacity-100"
          href={job.source_url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          title="Open job posting"
          aria-label="Open job posting in a new tab"
        >
          ↗
        </a>
      )}
    </div>
  )
}
