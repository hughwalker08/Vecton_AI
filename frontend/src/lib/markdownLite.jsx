// Minimal Markdown rendering for chat answers: **bold** (clause labels/
// headings), *italic* (emphasis/notes), and "- " bullet lists rendered as a
// real <ul>/<li> with an actual bullet, not a literal dash. Deliberately not
// a full Markdown implementation -- the model is asked for exactly this
// small subset (see backend/app/services/generation.py's system
// instruction), so this only needs to cover it, not arbitrary Markdown.

function renderInline(text, keyPrefix) {
  const pattern = /(\*\*(.+?)\*\*|\*(.+?)\*)/
  const parts = []
  let remaining = text
  let key = 0

  while (remaining) {
    const match = remaining.match(pattern)
    if (!match) {
      parts.push(remaining)
      break
    }

    const [whole, , bold, italic] = match
    if (match.index > 0) parts.push(remaining.slice(0, match.index))
    parts.push(
      bold !== undefined ? (
        <strong key={`${keyPrefix}-${key++}`}>{bold}</strong>
      ) : (
        <em key={`${keyPrefix}-${key++}`}>{italic}</em>
      ),
    )
    remaining = remaining.slice(match.index + whole.length)
  }

  return parts
}

// Returns an array of <p>/<ul> elements -- render directly as children,
// e.g. <div className="answer">{renderMarkdownLite(text)}</div>.
export function renderMarkdownLite(text) {
  const lines = (text || '').split('\n')
  const blocks = []
  let currentList = null
  let paragraphLines = []

  function flushParagraph(key) {
    if (paragraphLines.length === 0) return
    const joined = paragraphLines.join(' ')
    blocks.push(<p key={`p-${key}`}>{renderInline(joined, `p-${key}`)}</p>)
    paragraphLines = []
  }

  function flushList(key) {
    if (!currentList) return
    blocks.push(<ul key={`ul-${key}`}>{currentList}</ul>)
    currentList = null
  }

  lines.forEach((rawLine, i) => {
    const line = rawLine.trim()
    const bulletMatch = line.match(/^[-•]\s+(.*)/)

    if (bulletMatch) {
      flushParagraph(i)
      if (!currentList) currentList = []
      currentList.push(<li key={`li-${i}`}>{renderInline(bulletMatch[1], `li-${i}`)}</li>)
    } else if (line === '') {
      flushParagraph(i)
      flushList(i)
    } else {
      flushList(i)
      paragraphLines.push(line)
    }
  })

  flushParagraph('end')
  flushList('end')

  return blocks
}
