import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AUSTRALIAN_JURISDICTIONS } from '../lib/jurisdictions.js'
import './HomePage.css'

const SUGGESTIONS = [
  'What ceiling height do we need in the bedrooms?',
  'What BAL rating applies to this lot and what does it change?',
  'Do the ensuite floors need to be fully waterproofed?',
  'Which conditions are still open before occupation?',
]

function getGreeting() {
  const hour = new Date().getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 17) return 'Good afternoon'
  return 'Good evening'
}

export default function HomePage({ onStartChat, defaultJurisdiction }) {
  const [question, setQuestion] = useState('')
  const [jurisdiction, setJurisdiction] = useState(defaultJurisdiction || '')
  const navigate = useNavigate()
  const fieldRef = useRef(null)

  function startChat(text) {
    const trimmed = text.trim()
    if (!trimmed || !jurisdiction) return

    const chatId = onStartChat(trimmed, jurisdiction)
    navigate(`/chat/${chatId}`, { state: { initialQuestion: trimmed, jurisdiction } })
  }

  function handleSubmit(event) {
    event.preventDefault()
    startChat(question)
  }

  function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      startChat(question)
    }
  }

  function handleInput(event) {
    setQuestion(event.target.value)

    const field = fieldRef.current
    if (field) {
      field.style.height = 'auto'
      field.style.height = `${field.scrollHeight}px`
    }
  }

  return (
    <main className="home-page">
      <div className="wash" aria-hidden="true" />

      <div className="home">
        <div className="orb" aria-hidden="true" />
        <h1 className="greet">{getGreeting()}</h1>
        <p className="greet-sub">
          Ask about a clause, a consent condition, or anything in your project documents.
        </p>

        <form className="composer-in big" onSubmit={handleSubmit}>
          <textarea
            ref={fieldRef}
            rows={1}
            autoFocus
            placeholder="Ask about a clause, a condition or an inspection — or have it drafted."
            value={question}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
          />
          <div className="tools">
            <label className="tool jurisdiction-picker">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                <path
                  d="M12 21s7-6.1 7-11.5A7 7 0 0 0 5 9.5C5 14.9 12 21 12 21Z"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinejoin="round"
                />
                <circle cx="12" cy="9.5" r="2.2" stroke="currentColor" strokeWidth="1.6" />
              </svg>
              <select
                value={jurisdiction}
                onChange={(event) => setJurisdiction(event.target.value)}
                aria-label="Jurisdiction for this chat"
              >
                <option value="" disabled>
                  Select state / territory
                </option>
                {AUSTRALIAN_JURISDICTIONS.map((item) => (
                  <option key={item.code} value={item.code}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="submit"
              className="send"
              aria-label="Ask"
              disabled={!question.trim() || !jurisdiction}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
                <path
                  d="M4.5 12h13m-5-5.5 5.5 5.5-5.5 5.5"
                  stroke="currentColor"
                  strokeWidth="1.9"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
          </div>
        </form>

        <div className="suggests">
          {SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              className="sug"
              onClick={() => startChat(suggestion)}
            >
              {suggestion}
            </button>
          ))}
        </div>

        <div className="home-foot">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
            <path
              d="M12 4.5 20.5 19h-17L12 4.5Z"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinejoin="round"
            />
            <path d="M12 10v4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            <circle cx="12" cy="16.6" r="0.9" fill="currentColor" />
          </svg>
          Answers cite the clause they came from. Check them before you build to them.
        </div>
      </div>
    </main>
  )
}
