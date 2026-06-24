import { useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import { DEFAULT_SWIPE_TUNING, type SwipeTuning } from './config'

/** Direction the user is swiping toward. */
export type SwipeDirection = 'left' | 'right'

/** Arguments for the useSwipe hook. */
export interface UseSwipeArgs {
  /** Called when the gesture commits (release past the commit threshold). */
  onCommit: (direction: SwipeDirection) => void
  /** One-shot: fires once when the gesture locks to the horizontal axis. */
  onStart?: (direction: SwipeDirection) => void
  /** One-shot: fires once when |dx| crosses commitPx upward (becomes armed). */
  onArm?: (direction: SwipeDirection) => void
  /** One-shot: fires once when |dx| crosses back below commitPx after arming. */
  onDisarm?: () => void
  /** One-shot: fires on release when horizontal but NOT committed (snap home). */
  onSnapBack?: () => void
  /** Override default tuning values. */
  tuning?: Partial<SwipeTuning>
}

/** Values returned by the useSwipe hook. */
export interface UseSwipeResult {
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
function dampOffset(dx: number, tuning: SwipeTuning): number {
  const sign = Math.sign(dx)
  const dist = Math.abs(dx)
  if (dist <= tuning.commitPx) return dx
  const extra =
    tuning.overshootPx *
    (1 - Math.exp(-((dist - tuning.commitPx) * tuning.overshootResistance) / tuning.overshootPx))
  return sign * (tuning.commitPx + extra)
}

/**
 * Hand-rolled horizontal swipe for any swipeable surface. Locks to the horizontal
 * axis only after axisSlop so vertical scrolling still works, and ignores pointer
 * types not in the tuning set. A release past commitPx fires onCommit; otherwise
 * the row snaps home. Emits one-shot lifecycle edge callbacks (onStart, onArm,
 * onDisarm, onSnapBack) that a later effects layer can subscribe to.
 */
export function useSwipe({
  onCommit,
  onStart,
  onArm,
  onDisarm,
  onSnapBack,
  tuning: tuningOverride,
}: UseSwipeArgs): UseSwipeResult {
  const tuning = { ...DEFAULT_SWIPE_TUNING, ...tuningOverride }

  const [dx, setDx] = useState(0)
  const [settling, setSettling] = useState(false)

  const start = useRef<{ x: number; y: number; pointerId: number } | null>(null)
  const axis = useRef<'none' | 'horizontal' | 'vertical'>('none')
  const suppressClick = useRef(false)
  // Mirror of dx read at release: a fast pointerup can fire before the state
  // update from the last move has re-rendered, so we commit off the ref.
  const dxRef = useRef(0)
  // One-shot edge tracking.
  const armedRef = useRef(false)
  const startedRef = useRef(false)

  function reset() {
    start.current = null
    axis.current = 'none'
    dxRef.current = 0
    armedRef.current = false
    startedRef.current = false
    setDx(0)
  }

  function onPointerDown(e: ReactPointerEvent) {
    if (!tuning.pointerTypes.has(e.pointerType as never)) return
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
      if (Math.abs(moveX) < tuning.axisSlopPx && Math.abs(moveY) < tuning.axisSlopPx) return
      axis.current = Math.abs(moveX) > Math.abs(moveY) ? 'horizontal' : 'vertical'
      if (axis.current === 'horizontal') {
        // Capture so we keep getting moves even if the pointer leaves the row,
        // and so the gesture can't be stolen mid-swipe. Guard: jsdom/older
        // browsers may not implement it.
        e.currentTarget.setPointerCapture?.(e.pointerId)
        const dir: SwipeDirection = moveX < 0 ? 'left' : 'right'
        if (!startedRef.current) {
          startedRef.current = true
          onStart?.(dir)
        }
      }
    }

    if (axis.current === 'horizontal') {
      e.preventDefault() // block native scroll/text-selection while swiping
      dxRef.current = moveX
      setDx(moveX)

      const armedNow = Math.abs(moveX) >= tuning.commitPx
      if (armedNow && !armedRef.current) {
        armedRef.current = true
        const dir: SwipeDirection = moveX < 0 ? 'left' : 'right'
        onArm?.(dir)
      } else if (!armedNow && armedRef.current) {
        armedRef.current = false
        onDisarm?.()
      }
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
      if (dxRef.current <= -tuning.commitPx) {
        onCommit('left')
      } else if (dxRef.current >= tuning.commitPx) {
        onCommit('right')
      } else {
        onSnapBack?.()
      }
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
  const progress = Math.min(Math.abs(dx) / tuning.commitPx, 1)
  const armed = Math.abs(dx) >= tuning.commitPx

  return {
    offset: dampOffset(dx, tuning),
    progress,
    armed,
    direction,
    settling,
    handlers: { onPointerDown, onPointerMove, onPointerUp, onPointerCancel },
    consumeClickSuppression,
  }
}
