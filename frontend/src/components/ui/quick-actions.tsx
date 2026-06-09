import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

const quickActionVariants = cva(
  "inline-flex items-center justify-center gap-1.5 rounded-md border font-medium whitespace-nowrap cursor-pointer transition-all outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-2 focus-visible:ring-offset-bg disabled:pointer-events-none disabled:opacity-40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
  {
    variants: {
      variant: {
        default:
          'bg-card border-border text-muted hover:border-border-strong hover:text-fg data-[active=true]:bg-primary/15 data-[active=true]:border-primary/40 data-[active=true]:text-primary-hov',
        success:
          'bg-card border-border text-muted hover:border-score-high/50 hover:text-score-high data-[active=true]:bg-score-high/15 data-[active=true]:border-score-high/40 data-[active=true]:text-score-high',
        danger:
          'bg-card border-border text-muted hover:border-score-low/50 hover:text-score-low data-[active=true]:bg-score-low/15 data-[active=true]:border-score-low/40 data-[active=true]:text-score-low',
        warn: 'bg-card border-border text-muted hover:border-score-mid/50 hover:text-score-mid data-[active=true]:bg-score-mid/15 data-[active=true]:border-score-mid/40 data-[active=true]:text-score-mid',
      },
      size: {
        xs: 'h-6 px-2 text-[11px]',
        sm: 'h-7 px-2.5 text-xs',
        md: 'h-8 px-3 text-[13px]',
      },
    },
    defaultVariants: { variant: 'default', size: 'sm' },
  },
)

export interface QuickAction {
  id: string
  label: React.ReactNode
  icon?: React.ReactNode
  shortcut?: string
  active?: boolean
  disabled?: boolean
  onSelect: () => void
  variant?: VariantProps<typeof quickActionVariants>['variant']
  title?: string
}

interface QuickActionsProps extends VariantProps<typeof quickActionVariants> {
  actions: QuickAction[]
  className?: string
  'aria-label': string
}

function QuickActions({ actions, size, className, ...rest }: QuickActionsProps) {
  return (
    <div
      role="toolbar"
      aria-label={rest['aria-label']}
      data-slot="quick-actions"
      className={cn('inline-flex items-center gap-1.5', className)}
    >
      {actions.map((a) => (
        <button
          key={a.id}
          type="button"
          data-active={!!a.active}
          aria-pressed={!!a.active}
          disabled={a.disabled}
          title={a.title}
          onClick={a.onSelect}
          className={quickActionVariants({ variant: a.variant ?? 'default', size })}
        >
          {a.icon}
          <span>{a.label}</span>
          {a.shortcut && (
            <kbd
              aria-hidden
              className="hidden sm:inline-flex h-4 min-w-4 items-center justify-center rounded-sm border border-border/70 bg-bg/40 px-1 font-mono text-[9px] text-faint"
            >
              {a.shortcut}
            </kbd>
          )}
        </button>
      ))}
    </div>
  )
}

export { QuickActions }
