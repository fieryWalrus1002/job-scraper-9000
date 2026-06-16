import type { JobDetail } from '../../../types'

export function DevMetadataSection({ jobData }: { jobData: JobDetail }) {
  return (
    <div className="flex flex-col gap-1.5">
      {[
        ['Dedup hash', jobData.dedup_hash],
        ['Model', jobData.model],
        ['Provider', jobData.provider],
        ['Profile version', jobData.profile_version],
        ['Run ID', jobData.run_id],
        ['Scored at', jobData.scored_at],
        ['Ingested at', jobData.ingested_at],
        ['Source', jobData.source],
        ['Source job ID', jobData.source_job_id],
      ].map(([label, value]) => (
        <div
          key={label}
          className="flex gap-3 text-[12px] py-1 border-b border-border/40 last:border-b-0"
        >
          <span className="w-[140px] shrink-0 text-muted">{label}</span>
          {value ? (
            <span
              className="text-fg font-mono break-all cursor-pointer hover:text-primary-hov transition-colors"
              title="Click to copy"
              onClick={() => {
                // Swallow rejection — clipboard can fail in insecure contexts
                // or when permission is denied; no unhandled-rejection noise.
                void navigator.clipboard?.writeText(String(value)).catch(() => {})
              }}
            >
              {value}
            </span>
          ) : (
            <span className="text-faint font-mono">—</span>
          )}
        </div>
      ))}
    </div>
  )
}
