import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderMarkdownLite } from './markdownLite.jsx'

function renderText(text) {
  return render(<div>{renderMarkdownLite(text)}</div>).container
}

describe('renderMarkdownLite', () => {
  it('renders **bold** as <strong>', () => {
    const container = renderText('**Clause H1D4** applies here.')

    const strong = container.querySelector('strong')
    expect(strong).toHaveTextContent('Clause H1D4')
    expect(container).toHaveTextContent('Clause H1D4 applies here.')
  })

  it('renders *italic* as <em>', () => {
    const container = renderText('This is *only* a note.')

    expect(container.querySelector('em')).toHaveTextContent('only')
  })

  it('renders "- " bullet lines as a real list, not a literal dash', () => {
    const container = renderText('- First point\n- Second point')

    const items = container.querySelectorAll('li')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent('First point')
    expect(items[1]).toHaveTextContent('Second point')
    expect(container.textContent).not.toContain('- First point')
  })

  it('separates blank-line paragraphs into distinct <p> elements', () => {
    const container = renderText('First paragraph.\n\nSecond paragraph.')

    const paragraphs = container.querySelectorAll('p')
    expect(paragraphs).toHaveLength(2)
    expect(paragraphs[0]).toHaveTextContent('First paragraph.')
    expect(paragraphs[1]).toHaveTextContent('Second paragraph.')
  })

  it('handles a heading, bullets, and prose together', () => {
    const container = renderText(
      '**Major Scam Trends:**\n- Investment Scams: rose 145%.\n- Jobs Scams: rose 245%.\n\nOverall volumes grew.',
    )

    expect(container.querySelector('strong')).toHaveTextContent('Major Scam Trends:')
    expect(container.querySelectorAll('li')).toHaveLength(2)
    // The bold heading line is its own paragraph (flushed before the bullet
    // list starts), plus "Overall volumes grew." after it -- two, not one.
    expect(container.querySelectorAll('p')).toHaveLength(2)
  })
})
