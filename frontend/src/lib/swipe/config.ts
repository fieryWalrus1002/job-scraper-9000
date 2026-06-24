// Pointer types that may drive a swipe gesture.
export type PointerType = 'touch' | 'pen' | 'mouse'

/** Tuning knobs for the horizontal swipe gesture. */
export interface SwipeTuning {
  /** Horizontal travel (px) before a release commits — the "trigger line". */
  commitPx: number
  /** Dead zone (px): below this a press is a tap, not a swipe. The band
   *  [axisSlopPx, commitPx) is the back-off zone (follows finger, snaps home). */
  axisSlopPx: number
  /** How far past commit the card keeps visually sliding (rubber-band tail). */
  overshootPx: number
  overshootResistance: number
  /** Pointer types allowed to drive a swipe. */
  pointerTypes: ReadonlySet<PointerType>
}

export const DEFAULT_SWIPE_TUNING: SwipeTuning = {
  commitPx: 72,
  axisSlopPx: 8,
  overshootPx: 28,
  overshootResistance: 0.35,
  pointerTypes: new Set<PointerType>(['touch', 'pen', 'mouse']),
}
