import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { JobDescriptionSection } from './JobDescriptionSection'

describe('JobDescriptionSection', () => {
  it('renders markdown structure safely as React elements', () => {
    const { container } = render(
      <JobDescriptionSection
        description={[
          '## Key Responsibilities',
          '',
          '- Build Python services',
          '- Own production systems',
          '',
          '**Required:** TypeScript',
          '',
          '<script>alert("xss")</script>',
          '',
          '[Apply](https://example.com/apply)',
          '[Bad](javascript:alert(1))',
        ].join('\n')}
      />,
    )

    expect(
      screen.getByRole('heading', { name: 'Key Responsibilities', level: 2 }),
    ).toBeInTheDocument()

    const list = screen.getByRole('list')
    expect(within(list).getAllByRole('listitem')).toHaveLength(2)
    expect(within(list).getByText('Build Python services')).toBeInTheDocument()
    expect(within(list).getByText('Own production systems')).toBeInTheDocument()

    expect(screen.getByText('Required:')).toHaveClass('font-semibold')
    expect(screen.queryByText('<script>alert("xss")</script>')).not.toBeInTheDocument()
    expect(screen.queryByText('alert("xss")')).not.toBeInTheDocument()
    expect(container.querySelector('script')).not.toBeInTheDocument()
    expect(container.querySelector('a[href^="javascript:"]')).not.toBeInTheDocument()

    const link = screen.getByRole('link', { name: 'Apply' })
    expect(link).toHaveAttribute('href', 'https://example.com/apply')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noreferrer')
  })

  it('renders fallback copy for missing descriptions', () => {
    render(<JobDescriptionSection description="   " />)

    expect(screen.getByText('No description available.')).toBeInTheDocument()
  })
})
