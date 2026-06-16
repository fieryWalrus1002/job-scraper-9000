import { useState, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

export function Section({
  title,
  children,
  defaultOpen = true,
  badge,
}: {
  title: string
  children: ReactNode
  defaultOpen?: boolean
  badge?: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border-b border-border last:border-b-0">
      <button
        className="flex items-center justify-between w-full px-7 py-3.5 bg-transparent border-none text-fg text-[13px] font-medium cursor-pointer text-left hover:bg-hover/60 transition-colors group"
        onClick={() => setOpen((v) => !v)}
      >
        <span className="flex items-center gap-2.5">
          <svg
            width="10"
            height="10"
            viewBox="0 0 10 10"
            className={cn(
              'text-faint transition-transform duration-200 group-hover:text-muted',
              open && 'rotate-90',
            )}
            aria-hidden="true"
          >
            <path
              d="M3.5 2 L6.5 5 L3.5 8"
              stroke="currentColor"
              strokeWidth="1.5"
              fill="none"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          {title}
        </span>
        {badge && <span>{badge}</span>}
      </button>
      {open && <div className="px-7 pb-6 pt-2">{children}</div>}
    </div>
  )
}
