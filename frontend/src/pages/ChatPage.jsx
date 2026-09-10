import { useState } from 'react'
import { askQuestion } from '../api/client.js'
import './ChatPage.css'

export default function ChatPage() {
  const [question, setQuestion] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [citations, setCitations] = useState([])
  const [messages, setMessages] = useState([])

  async function handleSubmit(event) {
    event.preventDefault()

    const trimmedQuestion = question.trim()

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
      const response = await askQuestion(trimmedQuestion)

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
        text: 'Unable to contact the backend. Please try again. Lorem ipsum dolor sit amet consectetur adipisicing elit. Illum libero quis beatae qui. Et atque maxime dolore inventore velit omnis?',
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
