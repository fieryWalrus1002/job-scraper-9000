/** Posted date, monospaced; em dash when missing. */
export function PostedAtCell({ value }: { value: string | null }) {
  return <span className="text-muted font-mono text-[12px]">{value ?? '—'}</span>
}
