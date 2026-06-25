import type { ComponentType } from 'react'

interface SwipeAffordanceProps {
  direction: 'left' | 'right'
  progress: number
  armed: boolean
  offset: number
  label: string
  /** Optional decorative glyph; the label alone is enough if a surface omits it. */
  icon?: ComponentType<{ className?: string }>
  color: string
}

/**
 * The action affordance revealed in the gap a swipe opens up. It lives inside
 * the swipeable row but counter-translates by the row's offset so it stays
 * pinned at the table edge — i.e. it appears to sit still while the row
 * slides off it. Fades/scales in with progress and flips to a solid "armed"
 * fill once releasing would commit.
 */
export function SwipeAffordance({
  direction,
  progress,
  armed,
  offset,
  label,
  icon: Icon,
  color,
}: SwipeAffordanceProps) {
  return (
    <span
      aria-hidden
      className="pointer-events-none absolute top-1/2 z-20 flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold whitespace-nowrap"
      style={{
        [direction === 'left' ? 'right' : 'left']: 12,
        transform: `translateY(-50%) translateX(${-offset}px) scale(${0.85 + progress * 0.15})`,
        opacity: Math.min(progress * 1.5, 1),
        color: armed ? '#fff' : color,
        backgroundColor: armed ? color : `color-mix(in oklab, ${color} 16%, transparent)`,
      }}
    >
      {Icon && <Icon className="size-3.5" />}
      {label}
    </span>
  )
}
