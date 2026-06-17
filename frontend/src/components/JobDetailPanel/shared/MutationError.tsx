/**
 * Inline error banner for a failed mutation. Renders nothing unless an error is
 * present, so callers can pass `mutation.error` directly.
 */
export function MutationError({ error }: { error: unknown }) {
  if (!error) return null
  const message = error instanceof Error ? error.message : String(error)
  return (
    <div
      role="alert"
      className="rounded-md border border-score-low/40 bg-score-low/10 px-3 py-2 text-[12px] text-score-low"
    >
      {message}
    </div>
  )
}
