import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

const segmentedRootVariants = cva(
  'inline-flex items-center gap-0.5 rounded-md border border-border bg-card p-0.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.02)]',
  {
    variants: {
      size: {
        xs: 'h-7',
        sm: 'h-8',
        md: 'h-9',
      },
    },
    defaultVariants: { size: 'sm' },
  },
)

const segmentedItemVariants = cva(
  'relative inline-flex items-center justify-center gap-1.5 rounded-[5px] font-medium cursor-pointer transition-all outline-none whitespace-nowrap text-muted hover:text-fg focus-visible:ring-2 focus-visible:ring-primary/50 disabled:cursor-default disabled:opacity-40 data-[active=true]:bg-primary/15 data-[active=true]:text-primary-hov data-[active=true]:shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]',
  {
    variants: {
      size: {
        xs: 'h-6 px-2 text-[11px]',
        sm: 'h-7 px-2.5 text-xs',
        md: 'h-8 px-3 text-[13px]',
      },
    },
    defaultVariants: { size: 'sm' },
  },
)

export interface SegmentedOption<T extends string> {
  value: T
  label: React.ReactNode
  shortcut?: string
  title?: string
  disabled?: boolean
}

interface SegmentedControlProps<T extends string> extends VariantProps<
  typeof segmentedRootVariants
> {
  options: SegmentedOption<T>[]
  value: T | null | undefined
  onChange: (value: T) => void
  disabled?: boolean
  className?: string
  'aria-label': string
}

function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  disabled,
  size,
  className,
  ...rest
}: SegmentedControlProps<T>) {
  return (
    <div
      role="radiogroup"
      aria-label={rest['aria-label']}
      data-slot="segmented-control"
      className={cn(segmentedRootVariants({ size }), className)}
    >
      {options.map((opt) => {
        const active = opt.value === value
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={active}
            data-active={active}
            disabled={disabled || opt.disabled}
            title={opt.title}
            onClick={() => onChange(opt.value)}
            className={segmentedItemVariants({ size })}
          >
            <span>{opt.label}</span>
            {opt.shortcut && (
              <kbd
                aria-hidden
                className="hidden sm:inline-flex h-4 min-w-4 items-center justify-center rounded-sm border border-border/70 bg-bg/40 px-1 font-mono text-[9px] text-faint"
              >
                {opt.shortcut}
              </kbd>
            )}
          </button>
        )
      })}
    </div>
  )
}

export { SegmentedControl }
