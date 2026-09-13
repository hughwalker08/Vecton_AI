import { useEffect, useRef, useState } from 'react'
import { useLocation, useParams } from 'react-router-dom'
import { askQuestion } from '../api/client.js'
import './ChatPage.css'

export default function ChatPage({ jurisdiction }) {
  const [question, setQuestion] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [messages, setMessages] = useState([])
  const { chatId } = useParams()
  const location = useLocation()
  const startedChatId = useRef(null)
  const fieldRef = useRef(null)
  const scrollRef = useRef(null)

  async function sendMessage(trimmedQuestion) {
    if (!trimmedQuestion) {
      return
    }

    const newMessage = {
      id: Date.now(),
      role: 'user',
      text: trimmedQuestion,
    }

    setMessages((currentMessages) => [
      ...currentMessages,
      newMessage,
    ])

    setQuestion('')
    if (fieldRef.current) fieldRef.current.style.height = 'auto'
    setIsLoading(true)

    try {
      const response = await askQuestion(
	trimmedQuestion,
	jurisdiction,
      )

      const assistantMessage = {
        id: Date.now() + 1,
        role: 'assistant',
        text: response.answer,
        citations: response.citations ?? [],
        abstained: response.abstained ?? false,
      }

      setMessages((currentMessages) => [
        ...currentMessages,
        assistantMessage,
      ])
    } catch (error) {
      const errorMessage = {
        id: Date.now() + 1,
        role: 'assistant',
        text: 'Unable to contact the backend. Please try again.',
        citations: [],
        abstained: false,
        isError: true,
      }

      setMessages((currentMessages) => [
        ...currentMessages,
        errorMessage,
      ])

      console.error(error)
    } finally {
      setIsLoading(false)
    }
  }

  // A chat started from the home page arrives here with the question that
  // kicked it off — send it automatically instead of waiting for the user
  // to retype it. Guarded by chatId so it only fires once per new chat.
  useEffect(() => {
    const initialQuestion = location.state?.initialQuestion

    if (initialQuestion && startedChatId.current !== chatId) {
      startedChatId.current = chatId
      sendMessage(initialQuestion)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId, location.state])

  useEffect(() => {
    const scroller = scrollRef.current
    if (scroller) scroller.scrollTop = scroller.scrollHeight
  }, [messages, isLoading])

  function handleSubmit(event) {
    event.preventDefault()
    sendMessage(question.trim())
  }

  function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      sendMessage(question.trim())
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
    <main className="chat-page">
      <div className="chat-scroll" ref={scrollRef}>
        <div className="chat-pane">
          {messages.map((message) =>
            message.role === 'user' ? (
              <div className="ask-row" key={message.id}>
                <div className="ask">{message.text}</div>
              </div>
            ) : (
              <div className="answer-block" key={message.id}>
                <div className={`answer ${message.isError ? 'answer-error' : ''}`}>
                  <p>{message.text}</p>
                </div>

                {message.abstained && !message.isError && (
                  <div className="abstain-note">
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
                    No matching source was found for this question.
                  </div>
                )}

                {message.citations?.length > 0 && (
                  <div className="srcs">
                    <span className="k">Sources</span>
                    {message.citations.map((citation, index) =>
                      citation.source_url ? (
                        <a
                          key={`${citation.doc}-${citation.clause_id}-${index}`}
                          className="src-chip"
                          href={citation.source_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <i>{index + 1}</i>
                          {citation.doc}
                          {citation.clause_id ? ` · ${citation.clause_id}` : ''}
                        </a>
                      ) : (
                        <span
                          key={`${citation.doc}-${citation.clause_id}-${index}`}
                          className="src-chip"
                        >
                          <i>{index + 1}</i>
                          {citation.doc}
                          {citation.clause_id ? ` · ${citation.clause_id}` : ''}
                        </span>
                      ),
                    )}
                  </div>
                )}
              </div>
            ),
          )}

          {isLoading && (
            <div className="thought">
              <span className="spin" />
              Thinking…
            </div>
          )}
        </div>
      </div>

      <div className="composer">
        <form className={`composer-in ${isLoading ? 'busy' : ''}`} onSubmit={handleSubmit}>
          <textarea
            ref={fieldRef}
            rows={1}
            placeholder="Ask a follow-up, or start somewhere new."
            aria-label="Construction compliance question"
            value={question}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
          />
          <div className="tools">
            <button type="submit" className="send" aria-label="Send" disabled={isLoading || !question.trim()}>
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
      </div>
    </main>
  )
}
