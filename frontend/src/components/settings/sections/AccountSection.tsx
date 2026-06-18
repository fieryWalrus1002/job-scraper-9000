import { useAuth } from '../../../hooks/useAuth'
import { Section } from '../fields'

/**
 * Account & Activity panel. Phase 18 shell (#367): signed-in context plus
 * explanatory copy. The pipeline enable/disable toggle lands with its API in
 * #368; until then this just states where that control will live.
 */
export function AccountSection() {
  const { principal, isLoading } = useAuth()
  const email = principal?.userDetails ?? null

  return (
    <div className="flex flex-col gap-6">
      <Section title="Account">
        <div className="flex flex-col gap-1">
          <span className="text-[11px] text-faint uppercase tracking-wide">Signed in as</span>
          <span className="text-[13px] text-fg">
            {isLoading ? 'Loading…' : (email ?? 'Not signed in')}
          </span>
        </div>
      </Section>

      <Section title="Overnight pipeline">
        <p className="text-[12px] text-muted">
          Your search runs automatically each night, scraping and scoring new postings against your
          profile. Pausing the pipeline stops future overnight runs — it does not delete your
          settings or any jobs already scored.
        </p>
        <div className="text-[11px] text-faint border border-dashed border-border rounded-md px-3 py-2">
          The enable/disable toggle ships with its API in a follow-up (#368).
        </div>
      </Section>
    </div>
  )
}
