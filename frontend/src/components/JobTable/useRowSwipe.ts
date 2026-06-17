import { useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'

// Pointer types that can drive a swipe. Mouse is included so we can try
// click-drag triage on the desktop; drop 'mouse' here to fall back to
// touch/pen-only (see #354 — we're trialing mouse-drag locally).
const SWIPE_POINTER_TYPES = new Set(['touch', 'pen', 'mouse'])

// Horizontal travel (px) needed to commit a swipe; below this the row snaps back.
const COMMIT_PX = 72
// Movement (px) before we lock onto an axis — under this a press is still a tap.
const AXIS_SLOP = 8
// How far past the commit point the row keeps visually sliding (rubber-band), so
// a long drag eases to a stop instead of yeeting the row across the screen.
const OVERSHOOT_PX = 28
const OVERSHOOT_RESISTANCE = 0.35

export type SwipeDirection = 'left' | 'right'

interface UseRowSwipeArgs {
  onCommit: (direction: SwipeDirection) => void
}

interface UseRowSwipeResult {
  /** Clamped/rubber-banded horizontal offset to translate the row by. 0 when idle. */
  offset: number
  /** 0→1 toward the commit threshold; drives the tint/affordance ramp. */
  progress: number
  /** True once the swipe is far enough that releasing will commit. */
  armed: boolean
  /** Which action the current drag is toward, or null when idle. */
  direction: SwipeDirection | null
  /** True while the row is animating (snap-back after release). */
  settling: boolean
  /** Spread onto the swipeable row element. */
  handlers: {
    onPointerDown: (e: ReactPointerEvent) => void
    onPointerMove: (e: ReactPointerEvent) => void
    onPointerUp: (e: ReactPointerEvent) => void
    onPointerCancel: (e: ReactPointerEvent) => void
  }
  /**
   * True immediately after a horizontal drag so the row's onClick can bail out
   * (a swipe shouldn't also open the detail panel). The row should read this and
   * reset it to false. Checked synchronously since click fires right after pointerup.
   */
  consumeClickSuppression: () => boolean
}

// Map raw finger travel to the row's visual offset: 1:1 up to the commit point,
// then a resisted tail that asymptotes near COMMIT_PX + OVERSHOOT_PX.
function dampOffset(dx: number): number {
  const sign = Math.sign(dx)
  const dist = Math.abs(dx)
  if (dist <= COMMIT_PX) return dx
  const extra =
    OVERSHOOT_PX * (1 - Math.exp(-((dist - COMMIT_PX) * OVERSHOOT_RESISTANCE) / OVERSHOOT_PX))
  return sign * (COMMIT_PX + extra)
}

/**
 * Hand-rolled horizontal swipe for a single table row. Locks to the horizontal
 * axis only after AXIS_SLOP so vertical scrolling still works, and ignores
 * pointer types we don't drive swipes with. A release past COMMIT_PX fires
 * onCommit; otherwise the row snaps home. No dependency, single axis — matches
 * the repo's keep-it-simple bias.
 */
export function useRowSwipe({ onCommit }: UseRowSwipeArgs): UseRowSwipeResult {
  const [dx, setDx] = useState(0)
  const [settling, setSettling] = useState(false)

  const start = useRef<{ x: number; y: number; pointerId: number } | null>(null)
  const axis = useRef<'none' | 'horizontal' | 'vertical'>('none')
  const suppressClick = useRef(false)
  // Mirror of dx read at release: a fast pointerup can fire before the state
  // update from the last move has re-rendered, so we commit off the ref.
  const dxRef = useRef(0)

  function reset() {
    start.current = null
    axis.current = 'none'
    dxRef.current = 0
    setDx(0)
  }

  function onPointerDown(e: ReactPointerEvent) {
    if (!SWIPE_POINTER_TYPES.has(e.pointerType)) return
    start.current = { x: e.clientX, y: e.clientY, pointerId: e.pointerId }
    axis.current = 'none'
    setSettling(false)
  }

  function onPointerMove(e: ReactPointerEvent) {
    const s = start.current
    if (!s || e.pointerId !== s.pointerId) return
    const moveX = e.clientX - s.x
    const moveY = e.clientY - s.y

    if (axis.current === 'none') {
      if (Math.abs(moveX) < AXIS_SLOP && Math.abs(moveY) < AXIS_SLOP) return
      axis.current = Math.abs(moveX) > Math.abs(moveY) ? 'horizontal' : 'vertical'
      if (axis.current === 'horizontal') {
        // Capture so we keep getting moves even if the pointer leaves the row,
        // and so the gesture can't be stolen mid-swipe. Guard: jsdom/older
        // browsers may not implement it.
        e.currentTarget.setPointerCapture?.(e.pointerId)
      }
    }

    if (axis.current === 'horizontal') {
      e.preventDefault() // block native scroll/text-selection while swiping
      dxRef.current = moveX
      setDx(moveX)
    }
  }

  function onPointerUp(e: ReactPointerEvent) {
    const s = start.current
    if (!s || e.pointerId !== s.pointerId) {
      reset()
      return
    }
    if (axis.current === 'horizontal') {
      suppressClick.current = true
      if (dxRef.current <= -COMMIT_PX) onCommit('left')
      else if (dxRef.current >= COMMIT_PX) onCommit('right')
    }
    setSettling(true) // animate the snap home (and the post-commit reset)
    reset()
  }

  function onPointerCancel() {
    setSettling(true)
    reset()
  }

  function consumeClickSuppression() {
    if (suppressClick.current) {
      suppressClick.current = false
      return true
    }
    return false
  }

  const direction: SwipeDirection | null = dx === 0 ? null : dx < 0 ? 'left' : 'right'
  const progress = Math.min(Math.abs(dx) / COMMIT_PX, 1)
  const armed = Math.abs(dx) >= COMMIT_PX

  return {
    offset: dampOffset(dx),
    progress,
    armed,
    direction,
    settling,
    handlers: { onPointerDown, onPointerMove, onPointerUp, onPointerCancel },
    consumeClickSuppression,
  }
}
