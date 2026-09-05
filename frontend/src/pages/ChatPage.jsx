import { useState } from 'react'
import './ChatPage.css'

export default function ChatPage() {
  const [question, setQuestion] = useState('')

  const [messages, setMessages] = useState([
    {
      id: 1,
      role: 'assistant',
      text: 'Ask a construction compliance question to begin.',
    },
  ])

  function handleSubmit(event) {
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
  }

  return (
    <main className="chat-page">
      <section className="chat-container">
        <header className="chat-header">
          <div>
            <p className="chat-eyebrow">Vecton AI</p>

            <h1>Construction Compliance Assistant</h1>

            <p className="chat-subtitle">
              Ask questions about construction requirements and review supporting sources.
            </p>
          </div>
        </header>

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
                <span className="message-label">
                  {message.role === 'user' ? 'You' : 'Assistant'}
                </span>

                <p>{message.text}</p>
              </div>
            ))}
          </section>

          <aside className="source-panel">
            <div className="source-panel-header">
              <h2>Sources</h2>
              <p>Supporting NCC references will appear here.</p>
            </div>

             <div className="source-card">
               <span className="source-type">Source preview</span>

               <h3>NCC reference</h3>

               <p className="source-clause">
                 Example clause
               </p>

               <p className="source-description">
                 Source content will appear here when retrieval results are connected to the frontend.
               </p>

               <button
                 type="button"
                 className="source-button"
               >
                 View source
               </button>
             </div>
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
          />

          <button
            type="submit"
            disabled={!question.trim()}
          >
            Send
          </button>
        </form>
      </section>
    </main>
  )
}
