/** Score rationale, clamped to two lines. */
export function RationaleCell({ value }: { value: string | null }) {
  return (
    <span
      className="overflow-hidden text-muted text-[12px] leading-[1.45]"
      style={{ display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}
    >
      {value ?? <span className="text-faint">—</span>}
    </span>
  )
}
