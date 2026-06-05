import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Slot } from "radix-ui"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-md border border-transparent px-1.5 py-px text-[11px] font-semibold whitespace-nowrap leading-[18px] [&>svg]:pointer-events-none [&>svg]:size-3",
  {
    variants: {
      variant: {
        default: "bg-primary/15 text-primary-hov border-primary/25",
        secondary: "bg-card text-muted border-border",
        outline: "border-border text-muted",
        score_high: "bg-score-high/15 text-score-high border-score-high/25",
        score_mid:  "bg-score-mid/15 text-score-mid border-score-mid/25",
        score_low:  "bg-score-low/15 text-score-low border-score-low/25",
        remote:     "bg-remote/15 text-remote border-remote/25",
        local:      "bg-local/15 text-local border-local/25",
        travel:     "bg-travel/15 text-travel border-travel/25",
        muted:      "bg-transparent text-muted border-transparent",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "span"

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export { Badge, badgeVariants }
