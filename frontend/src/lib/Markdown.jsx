import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

// Renders a chat answer's Markdown (see backend/app/services/generation.py's
// system instruction for what the model is asked to produce). remark-gfm adds
// tables, e.g. a pass/fail row per clause. Raw HTML in the text is shown as
// text, never injected.
const components = {
  a: ({ node, ...props }) => <a {...props} target="_blank" rel="noreferrer" />,
  // Lets a wide table scroll inside the answer instead of widening the page.
  table: ({ node, ...props }) => (
    <div className="answer-table">
      <table {...props} />
    </div>
  ),
}

export default function Markdown({ children }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {children || ''}
    </ReactMarkdown>
  )
}
