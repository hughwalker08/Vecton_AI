import { useEffect, useRef, useState } from 'react'
import { useLocation, useParams } from 'react-router-dom'
import { askQuestion } from '../api/client.js'
import './ChatPage.css'

export default function ChatPage({ jurisdiction }) {
  const [question, setQuestion] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [citations, setCitations] = useState([])
  const [messages, setMessages] = useState([])
  const { chatId } = useParams()
  const location = useLocation()
  const startedChatId = useRef(null)

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
      }

      setMessages((currentMessages) => [
        ...currentMessages,
        assistantMessage,
      ])

      setCitations(response.citations ?? [])
    } catch (error) {
      const errorMessage = {
        id: Date.now() + 1,
        role: 'assistant',
        text: error.message || 'Unable to contact the backend. Please try again.',
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

  function handleSubmit(event) {
    event.preventDefault()
    sendMessage(question.trim())
  }

  return (
    <main className="chat-page">
      <section className="chat-container">
        <div className="chat-content">
          <section className="conversation-panel">
            {messages.map((message) => (
              <div
                key={message.id}
                className={`message ${
                  message.role === 'user'
                    ? 'user-message'
                    : 'assistant-message'
                }`}
              >
                <p>{message.text}</p>
              </div>
            ))}
          
	    {isLoading && (
	      <div className="message assistant-message">
		<span className="message-label">Assistant</span>
		<p>Thinking...</p>
	      </div>
	    )}
          </section>

          <aside className="source-panel">
            <div className="source-panel-header">
              <h2>Sources</h2>
              <p>Supporting NCC references will appear here.</p>
            </div>

            {citations.length === 0 ? (
              <div className="source-card">
                <span className="source-type">No source</span>

                <h3>No citations returned</h3>

                <p className="source-description">
                  The current backend did not return any citations.
                </p>
              </div>
            ) : (
              citations.map((citation, index) => (
                <div
                  className="source-card"
                  key={`${citation.doc}-${citation.clause_id}-${index}`}
                >
                  <span className="source-type">
                    Citation {index + 1}
                  </span>

                  <h3>{citation.doc}</h3>

                  <p className="source-clause">
                    {citation.clause_id}
                  </p>

                  {citation.source_url ? (
                    <a
                      className="source-button"
                      href={citation.source_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      View source
                    </a>
                  ) : (
                    <p className="source-description">
                      No source URL available.
                    </p>
                  )}
                </div>
              ))
            )}

          </aside>
        </div>
        <form
          className="chat-input-area"
          onSubmit={handleSubmit}
        >
          <input
            type="text"
            placeholder="Ask a construction compliance question..."
            aria-label="Construction compliance question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
	    disabled={isLoading}
          />

          <button
            type="submit"
            disabled={isLoading || !question.trim()}
          >
            {isLoading ? 'Sending...' : 'Send'}
          </button>
        </form>
      </section>
    </main>
  )
}