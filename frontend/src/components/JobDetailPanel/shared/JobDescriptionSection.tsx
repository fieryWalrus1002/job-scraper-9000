export function JobDescriptionSection({ description }: { description: string | null }) {
  return (
    <div className="font-sans text-[13px] leading-[1.7] text-fg whitespace-pre-wrap break-words m-0 max-h-[420px] overflow-y-auto bg-bg border border-border rounded-md px-4 py-3.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.02)]">
      {description ?? <span className="text-faint">No description available.</span>}
    </div>
  )
}
