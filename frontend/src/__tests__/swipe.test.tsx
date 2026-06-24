import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render } from '@testing-library/react'
import { useSwipe } from '../lib/swipe/useSwipe'

// ── Helpers ──────────────────────────────────────────────────────────────────

function swipeRow(row: HTMLElement, deltaX: number) {
  const startX = 200
  const opts = { pointerId: 1, pointerType: 'touch', clientY: 100 }
  fireEvent.pointerDown(row, { ...opts, clientX: startX })
  fireEvent.pointerMove(row, { ...opts, clientX: startX + deltaX })
  fireEvent.pointerUp(row, { ...opts, clientX: startX + deltaX })
}

function swipeTo(row: HTMLElement, deltaX: number) {
  const startX = 200
  const opts = { pointerId: 1, pointerType: 'touch', clientY: 100 }
  fireEvent.pointerDown(row, { ...opts, clientX: startX })
  fireEvent.pointerMove(row, { ...opts, clientX: startX + deltaX })
}

function releaseFrom(row: HTMLElement, deltaX: number) {
  const opts = { pointerId: 1, pointerType: 'touch', clientY: 100 }
  fireEvent.pointerUp(row, { ...opts, clientX: 200 + deltaX })
}

function cancelSwipe(row: HTMLElement) {
  fireEvent.pointerCancel(row, { pointerId: 1, pointerType: 'touch' })
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe('useSwipe tuning override', () => {
  it('commits at the overridden commitPx threshold, not the default', () => {
    const onCommit = vi.fn()
    const { container } = render(<TestSwipeTarget onCommit={onCommit} tuning={{ commitPx: 40 }} />)
    const row = container.querySelector('div')!

    // Default threshold is 72; with override of 40, a 50px swipe should commit.
    swipeRow(row, 50)
    expect(onCommit).toHaveBeenCalledWith('right')
  })

  it('does not commit below the overridden threshold', () => {
    const onCommit = vi.fn()
    const { container } = render(<TestSwipeTarget onCommit={onCommit} tuning={{ commitPx: 40 }} />)
    const row = container.querySelector('div')!

    swipeRow(row, 30)
    expect(onCommit).not.toHaveBeenCalled()
  })

  it('honors the default tuning when no override is provided', () => {
    const onCommit = vi.fn()
    const { container } = render(<TestSwipeTarget onCommit={onCommit} />)
    const row = container.querySelector('div')!

    // Default commitPx is 72; a 60px swipe should NOT commit.
    swipeRow(row, 60)
    expect(onCommit).not.toHaveBeenCalled()

    // A 80px swipe should commit.
    swipeRow(row, 80)
    expect(onCommit).toHaveBeenCalledWith('right')
  })
})

describe('useSwipe edge callbacks', () => {
  const callbacks = {
    onStart: vi.fn(),
    onArm: vi.fn(),
    onDisarm: vi.fn(),
    onSnapBack: vi.fn(),
    onCommit: vi.fn(),
  }

  beforeEach(() => {
    Object.values(callbacks).forEach((cb) => cb.mockClear())
  })

  it('fires onStart once when the gesture locks to horizontal axis', () => {
    const { container } = render(
      <TestSwipeTarget
        onCommit={callbacks.onCommit}
        onStart={callbacks.onStart}
        onArm={callbacks.onArm}
        onDisarm={callbacks.onDisarm}
        onSnapBack={callbacks.onSnapBack}
      />,
    )
    const row = container.querySelector('div')!

    swipeRow(row, 100)
    expect(callbacks.onStart).toHaveBeenCalledTimes(1)
    expect(callbacks.onStart).toHaveBeenCalledWith('right')
  })

  it('fires onArm once when crossing commitPx (not per move past it)', () => {
    const { container } = render(
      <TestSwipeTarget
        onCommit={callbacks.onCommit}
        onStart={callbacks.onStart}
        onArm={callbacks.onArm}
        onDisarm={callbacks.onDisarm}
        onSnapBack={callbacks.onSnapBack}
      />,
    )
    const row = container.querySelector('div')!

    // Move past commit threshold (72px) in multiple steps.
    swipeTo(row, 80)
    fireEvent.pointerMove(row, {
      pointerId: 1,
      pointerType: 'touch',
      clientY: 100,
      clientX: 280, // 80px from start
    })
    fireEvent.pointerMove(row, {
      pointerId: 1,
      pointerType: 'touch',
      clientY: 100,
      clientX: 300, // 100px from start — still past commit
    })

    expect(callbacks.onArm).toHaveBeenCalledTimes(1)
    expect(callbacks.onArm).toHaveBeenCalledWith('right')
  })

  it('fires onDisarm once when backing off below commitPx after arming', () => {
    const { container } = render(
      <TestSwipeTarget
        onCommit={callbacks.onCommit}
        onStart={callbacks.onStart}
        onArm={callbacks.onArm}
        onDisarm={callbacks.onDisarm}
        onSnapBack={callbacks.onSnapBack}
      />,
    )
    const row = container.querySelector('div')!

    // Move past commit (72px) → armed.
    swipeTo(row, 80)
    expect(callbacks.onArm).toHaveBeenCalledTimes(1)

    // Back off below commit.
    fireEvent.pointerMove(row, {
      pointerId: 1,
      pointerType: 'touch',
      clientY: 100,
      clientX: 260, // 60px from start — below commit
    })
    expect(callbacks.onDisarm).toHaveBeenCalledTimes(1)
  })

  it('fires onSnapBack on a sub-commit release', () => {
    const { container } = render(
      <TestSwipeTarget
        onCommit={callbacks.onCommit}
        onStart={callbacks.onStart}
        onArm={callbacks.onArm}
        onDisarm={callbacks.onDisarm}
        onSnapBack={callbacks.onSnapBack}
      />,
    )
    const row = container.querySelector('div')!

    swipeRow(row, 50) // below commit (72)
    expect(callbacks.onSnapBack).toHaveBeenCalledTimes(1)
    expect(callbacks.onCommit).not.toHaveBeenCalled()
  })

  it('fires onCommit on a past-commit release', () => {
    const { container } = render(
      <TestSwipeTarget
        onCommit={callbacks.onCommit}
        onStart={callbacks.onStart}
        onArm={callbacks.onArm}
        onDisarm={callbacks.onDisarm}
        onSnapBack={callbacks.onSnapBack}
      />,
    )
    const row = container.querySelector('div')!

    swipeRow(row, 100) // past commit (72)
    expect(callbacks.onCommit).toHaveBeenCalledTimes(1)
    expect(callbacks.onCommit).toHaveBeenCalledWith('right')
    expect(callbacks.onSnapBack).not.toHaveBeenCalled()
  })

  it('does NOT fire onSnapBack on cancel (even after arming)', () => {
    const { container } = render(
      <TestSwipeTarget
        onCommit={callbacks.onCommit}
        onStart={callbacks.onStart}
        onArm={callbacks.onArm}
        onDisarm={callbacks.onDisarm}
        onSnapBack={callbacks.onSnapBack}
      />,
    )
    const row = container.querySelector('div')!

    // Move past commit → armed.
    swipeTo(row, 100)
    expect(callbacks.onArm).toHaveBeenCalledTimes(1)

    // Cancel instead of release.
    cancelSwipe(row)
    expect(callbacks.onSnapBack).not.toHaveBeenCalled()
    expect(callbacks.onCommit).not.toHaveBeenCalled()
  })

  it('fires onArm/onDisarm multiple times across separate gesture cycles', () => {
    const { container } = render(
      <TestSwipeTarget
        onCommit={callbacks.onCommit}
        onStart={callbacks.onStart}
        onArm={callbacks.onArm}
        onDisarm={callbacks.onDisarm}
        onSnapBack={callbacks.onSnapBack}
      />,
    )
    const row = container.querySelector('div')!

    // First cycle: arm → disarm → release (snap back).
    swipeTo(row, 80) // arm
    fireEvent.pointerMove(row, { pointerId: 1, pointerType: 'touch', clientY: 100, clientX: 260 }) // disarm
    releaseFrom(row, 60) // snap back

    expect(callbacks.onArm).toHaveBeenCalledTimes(1)
    expect(callbacks.onDisarm).toHaveBeenCalledTimes(1)
    expect(callbacks.onSnapBack).toHaveBeenCalledTimes(1)

    // Second cycle: arm → release (commit).
    swipeRow(row, 100)
    expect(callbacks.onArm).toHaveBeenCalledTimes(2)
    expect(callbacks.onCommit).toHaveBeenCalledTimes(1)
  })
})

// ── Test target component ────────────────────────────────────────────────────

function TestSwipeTarget({
  onCommit,
  onStart,
  onArm,
  onDisarm,
  onSnapBack,
  tuning,
}: {
  onCommit: (dir: 'left' | 'right') => void
  onStart?: (dir: 'left' | 'right') => void
  onArm?: (dir: 'left' | 'right') => void
  onDisarm?: () => void
  onSnapBack?: () => void
  tuning?: Parameters<typeof useSwipe>[0]['tuning']
}) {
  const { handlers } = useSwipe({ onCommit, onStart, onArm, onDisarm, onSnapBack, tuning })
  return <div {...handlers} style={{ width: 400, height: 40, touchAction: 'pan-y' }} />
}
