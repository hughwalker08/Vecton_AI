import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import Markdown from './Markdown.jsx'

function renderText(text) {
  return render(<Markdown>{text}</Markdown>).container
}

describe('Markdown', () => {
  it('renders ### headings as headings, not literal hashes', () => {
    const container = renderText('### Balustrade Height Requirement\n\nApplies to decks.')

    expect(container.querySelector('h3')).toHaveTextContent('Balustrade Height Requirement')
    expect(container.textContent).not.toContain('###')
  })

  it('renders "* " and "- " bullets as list items', () => {
    const container = renderText('* First point\n* Second point\n\n- Third point')

    const items = container.querySelectorAll('li')
    expect(items).toHaveLength(3)
    expect(container.textContent).not.toMatch(/[*-] (First|Third) point/)
  })

  it('nests indented sub-points under their parent bullet', () => {
    const container = renderText(
      '- **Balustrade Height Requirement:**\n  - H2D16(1): at least 1 m\n  - H2D16(2): at least 865 mm on stairs',
    )

    const parent = container.querySelector('ul > li')
    expect(parent.querySelector('strong')).toHaveTextContent('Balustrade Height Requirement:')
    expect(parent.querySelectorAll('ul > li')).toHaveLength(2)
  })

  it('renders a GFM table with a header row', () => {
    const container = renderText(
      '| Clause | Result |\n| --- | --- |\n| H2D16(1) | Pass |\n| H2D16(2) | Fail |',
    )

    expect(container.querySelectorAll('th')).toHaveLength(2)
    expect(container.querySelectorAll('tbody tr')).toHaveLength(2)
    expect(container.querySelector('tbody td')).toHaveTextContent('H2D16(1)')
  })

  it('keeps clause numbers and other punctuation intact', () => {
    const container = renderText('See clause 3.9.2.3 (a) #2 and H1D4 *only* for Class 1a.')

    expect(container).toHaveTextContent('See clause 3.9.2.3 (a) #2 and H1D4 only for Class 1a.')
    expect(container.querySelector('em')).toHaveTextContent('only')
  })

  it('keeps a quoted clause\'s sub-clauses on separate lines', () => {
    const container = renderText(
      '> (b) The height must not be less than—\n>   (i) 1 m above the floor; or\n>   (ii) 865 mm above a landing.',
    )

    const quote = container.querySelector('blockquote')
    expect(quote.querySelectorAll('br')).toHaveLength(2)
    expect(quote).toHaveTextContent('(i) 1 m above the floor; or')
  })

  it('shows raw HTML as text instead of injecting it', () => {
    const container = renderText('<img src=x onerror="alert(1)"> text')

    expect(container.querySelector('img')).toBeNull()
  })

  it('opens links in a new tab', () => {
    const container = renderText('[ABCB](https://www.abcb.gov.au)')

    const link = container.querySelector('a')
    expect(link).toHaveAttribute('href', 'https://www.abcb.gov.au')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noreferrer')
  })
})
