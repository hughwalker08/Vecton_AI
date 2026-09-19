import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import SourcePanel from './SourcePanel.jsx'

const citation = {
  clause_id: 'H1D4',
  doc: 'NCC 2025 Volume Two',
  heading: 'Footings',
  text: 'Footings must be designed to transfer loads to the ground.',
  source_url: 'https://ncc.abcb.gov.au/H1D4',
  building_classes: ['1a', '10a'],
  jurisdictions: ['NSW'],
  climate_zones: [5, 6],
  applicability_note: 'Applies only to new construction.',
}

describe('SourcePanel', () => {
  it('renders closed, with no citation content, when citation is null', () => {
    render(<SourcePanel citation={null} onClose={vi.fn()} />)

    const aside = screen.getByLabelText('Cited source')
    expect(aside).toHaveAttribute('aria-hidden', 'true')
    expect(aside).not.toHaveClass('open')
    expect(screen.queryByText('H1D4')).not.toBeInTheDocument()
  })

  it('renders the citation details when open', () => {
    render(<SourcePanel citation={citation} onClose={vi.fn()} />)

    const aside = screen.getByLabelText('Cited source')
    expect(aside).toHaveAttribute('aria-hidden', 'false')
    expect(aside).toHaveClass('open')
    expect(screen.getByText('NCC 2025 Volume Two')).toBeInTheDocument()
    expect(screen.getByText('H1D4')).toBeInTheDocument()
    expect(screen.getByText('Footings')).toBeInTheDocument()
    expect(
      screen.getByText('Footings must be designed to transfer loads to the ground.'),
    ).toBeInTheDocument()
  })

  it('joins all applicability qualifiers together', () => {
    render(<SourcePanel citation={citation} onClose={vi.fn()} />)

    expect(
      screen.getByText(
        'building classes: 1a, 10a; jurisdictions: NSW; climate zones: 5, 6; Applies only to new construction.',
      ),
    ).toBeInTheDocument()
  })

  it('omits the applicability line entirely when there are no qualifiers', () => {
    render(
      <SourcePanel
        citation={{ clause_id: 'H1D4', doc: 'NCC 2025 Volume Two', text: 'Some clause text.' }}
        onClose={vi.fn()}
      />,
    )

    expect(screen.queryByText(/Applicability:/)).not.toBeInTheDocument()
  })

  it('falls back to a placeholder when the citation has no text', () => {
    render(
      <SourcePanel citation={{ clause_id: 'H1D4', doc: 'NCC 2025 Volume Two' }} onClose={vi.fn()} />,
    )

    expect(screen.getByText('No clause text was returned for this citation.')).toBeInTheDocument()
  })

  it('links to the source when source_url is present, and omits the link when it is not', () => {
    const { rerender } = render(<SourcePanel citation={citation} onClose={vi.fn()} />)

    expect(screen.getByRole('link', { name: /view original/i })).toHaveAttribute(
      'href',
      'https://ncc.abcb.gov.au/H1D4',
    )

    rerender(<SourcePanel citation={{ ...citation, source_url: null }} onClose={vi.fn()} />)

    expect(screen.queryByRole('link', { name: /view original/i })).not.toBeInTheDocument()
  })

  it('calls onClose when the back button is clicked', () => {
    const onClose = vi.fn()
    render(<SourcePanel citation={citation} onClose={onClose} />)

    fireEvent.click(screen.getByRole('button', { name: 'Close source' }))

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('calls onClose when the scrim behind the panel is clicked', () => {
    const onClose = vi.fn()
    const { container } = render(<SourcePanel citation={citation} onClose={onClose} />)

    fireEvent.click(container.querySelector('.src-scrim'))

    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
