import { Section } from '../fields'

export function DerivedPoliciesSection({ policies }: { policies: Record<string, unknown> | null }) {
  if (!policies) return null
  return (
    <Section title="Derived policies (read-only)">
      <p className="text-[11px] text-muted -mt-1">
        Computed from your search config — the gates applied before scoring.
      </p>
      <pre className="text-[11px] font-mono text-muted bg-bg-elevated border border-border rounded-md p-3 overflow-x-auto">
        {JSON.stringify(policies, null, 2)}
      </pre>
    </Section>
  )
}
