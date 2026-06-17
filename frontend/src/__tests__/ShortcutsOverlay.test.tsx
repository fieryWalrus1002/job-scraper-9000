import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ShortcutsOverlay } from '../components/ShortcutsOverlay'

describe('ShortcutsOverlay', () => {
  it('lists the funnel shortcuts when open', () => {
    render(<ShortcutsOverlay open onOpenChange={vi.fn()} />)
    expect(screen.getByText('Keyboard shortcuts')).toBeInTheDocument()
    expect(screen.getByText('Jobs feed')).toBeInTheDocument()
    expect(screen.getByText('Job detail')).toBeInTheDocument()
    expect(screen.getByText('Move cursor down')).toBeInTheDocument()
    expect(screen.getByText('Pursue (Shortlist → Tracking)')).toBeInTheDocument()
  })

  it('renders nothing while closed', () => {
    render(<ShortcutsOverlay open={false} onOpenChange={vi.fn()} />)
    expect(screen.queryByText('Keyboard shortcuts')).not.toBeInTheDocument()
  })

  it('closes on `q`', () => {
    const onOpenChange = vi.fn()
    render(<ShortcutsOverlay open onOpenChange={onOpenChange} />)
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'q' })
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })
})
