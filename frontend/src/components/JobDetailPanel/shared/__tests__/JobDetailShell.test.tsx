import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { JobDetailShell, JobDetailBody } from '../JobDetailShell'

function renderShell(onClose = vi.fn()) {
  render(
    <JobDetailShell onClose={onClose}>
      <JobDetailBody>body content</JobDetailBody>
    </JobDetailShell>,
  )
  return { onClose, dialog: screen.getByRole('dialog') }
}

describe('JobDetailShell keyboard', () => {
  it('quits the panel on `q`', () => {
    const { onClose, dialog } = renderShell()
    fireEvent.keyDown(dialog, { key: 'q' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('does not quit on `q` typed into a field, or with a modifier', () => {
    const { onClose, dialog } = renderShell()
    const input = document.createElement('input')
    dialog.appendChild(input)
    fireEvent.keyDown(input, { key: 'q' })
    fireEvent.keyDown(dialog, { key: 'q', metaKey: true })
    expect(onClose).not.toHaveBeenCalled()
  })
})
