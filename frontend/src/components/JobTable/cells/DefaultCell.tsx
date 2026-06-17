/** Fallback renderer for plain string columns; em dash when empty. */
export function DefaultCell({ value }: { value: string | null }) {
  return value ? <span>{value}</span> : <span className="text-faint">—</span>
}
