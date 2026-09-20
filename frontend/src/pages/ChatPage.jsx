import { useEffect, useRef, useState } from 'react'
import { useLocation, useParams } from 'react-router-dom'
import { askQuestion } from '../api/client.js'
import { useAttachment } from '../hooks/useAttachment.js'
import SourcePanel from '../components/SourcePanel.jsx'
import './ChatPage.css'

// Each chat request chains several backend calls (embed -> hybrid search ->
// rerank -> generate) that can together take 10+ seconds, with the rerank
// step in particular prone to cold-start delay on Hugging Face's free
// Inference API. A static "Thinking..." reads as stuck at that latency, so
// cycle through what's actually happening instead. This is a client-side
// approximation (the backend returns one response, not per-stage events) --
// timings are tuned to roughly track the real pipeline, not measured live.
const LOADING_STAGES = [
  'Retrieving relevant clauses…',
  'Reranking results…',
  'Generating your answer…',
]
const LOADING_STAGE_INTERVAL_MS = 2500

export default function ChatPage({ chats = [], defaultJurisdiction }) {
  const [question, setQuestion] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [loadingStage, setLoadingStage] = useState(0)
  const [messages, setMessages] = useState([])
  const [openCitation, setOpenCitation] = useState(null)
  // { name, text, status: 'uploading' | 'ready' | 'error', detail }. Resent
  // on every message in this chat (see sendMessage) rather than persisted
  // server-side -- see the chat-attachment plan. May start out already
  // populated if the user attached a file on the home page before this chat
  // existed (see the auto-send effect below, which carries it over).
  const {
    attachment,
    setAttachment,
    inputRef: attachmentInputRef,
    handleAttachmentChange,
    removeAttachment,
  } = useAttachment()
  const { chatId } = useParams()
  const location = useLocation()
  const startedChatId = useRef(null)
  const fieldRef = useRef(null)
  const scrollRef = useRef(null)

  // Each chat picks its jurisdiction once, in the home page composer, when
  // it's created (see App.jsx's createChat / HomePage.jsx) -- not a global
  // per-user default. location.state carries it on the very first render
  // right after creation, before the chats list has necessarily re-rendered
  // with the new entry; the chats-list lookup is what a revisited chat
  // (opened from the sidebar, no location.state) resolves from.
  const jurisdiction =
    chats.find((chat) => chat.id === chatId)?.jurisdiction ||
    location.state?.jurisdiction ||
    defaultJurisdiction

  useEffect(() => {
    if (!isLoading) {
      setLoadingStage(0)
      return
    }

    const interval = setInterval(() => {
      setLoadingStage((stage) => Math.min(stage + 1, LOADING_STAGES.length - 1))
    }, LOADING_STAGE_INTERVAL_MS)

    return () => clearInterval(interval)
  }, [isLoading])

  // `attachmentOverride`, when passed, is used instead of the `attachment`
  // state -- needed because the very first message of a chat started from
  // the home page fires from an effect that also just called setAttachment
  // for it (see the auto-send effect below), and that update isn't visible
  // in this closure yet. Every other call site (typing + Enter/submit) omits
  // it and just uses whatever's currently attached.
  async function sendMessage(trimmedQuestion, attachmentOverride) {
    if (!trimmedQuestion) {
      return
    }
    const activeAttachment = attachmentOverride !== undefined ? attachmentOverride : attachment

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
    setOpenCitation(null)
    setIsLoading(true)

    // Prior turns only -- newMessage (the question just asked) isn't in
    // `messages` yet (setMessages above hasn't committed within this closure),
    // and it's sent separately as the actual question anyway. Built by
    // pairing each user message with the reply right after it: a pair is
    // only included when that reply is a real answer, not an error bubble.
    // Dropping just the error and keeping the orphaned question would send
    // Gemini two consecutive "user" turns with nothing between them, which
    // breaks the strict user/model alternation its multi-turn API expects.
    const history = []
    for (let i = 0; i < messages.length - 1; i += 2) {
      const userTurn = messages[i]
      const replyTurn = messages[i + 1]
      if (userTurn?.role === 'user' && replyTurn?.role === 'assistant' && !replyTurn.isError) {
        history.push({ role: 'user', text: userTurn.text })
        history.push({ role: 'assistant', text: replyTurn.text })
      }
    }

    try {
      const response = await askQuestion(trimmedQuestion, jurisdiction, {
        history,
        attachment:
          activeAttachment?.status === 'ready'
            ? { name: activeAttachment.name, text: activeAttachment.text }
            : null,
      })

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
        text: error.message || 'Unable to contact the backend. Please try again.',
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
  // to retype it. Guarded by chatId so it only fires once per new chat. A
  // document attached on the home page (see HomePage.jsx) rides along the
  // same way, as { name, text } rather than the full attachment record.
  useEffect(() => {
    const initialQuestion = location.state?.initialQuestion
    const initialAttachment = location.state?.attachment

    if (initialQuestion && startedChatId.current !== chatId) {
      startedChatId.current = chatId
      const carriedAttachment = initialAttachment
        ? { ...initialAttachment, status: 'ready', detail: 'Attached' }
        : null
      if (carriedAttachment) setAttachment(carriedAttachment)
      sendMessage(initialQuestion, carriedAttachment)
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
                    {message.citations.map((citation, index) => (
                      <button
                        key={`${citation.doc}-${citation.clause_id}-${index}`}
                        type="button"
                        className="src-chip"
                        onClick={() => setOpenCitation(citation)}
                      >
                        <i>{index + 1}</i>
                        {citation.doc}
                        {citation.clause_id ? ` · ${citation.clause_id}` : ''}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ),
          )}

          {isLoading && (
            <div className="thought">
              <span className="spin" />
              {LOADING_STAGES[loadingStage]}
            </div>
          )}
        </div>
      </div>

      <div className="composer">
        {attachment && (
          <div className={`attachment-chip ${attachment.status === 'error' ? 'attachment-error' : ''}`}>
            {attachment.status === 'uploading' && <span className="spin" />}
            <span className="attachment-name">{attachment.name}</span>
            <span className="attachment-detail">{attachment.detail}</span>
            <button
              type="button"
              className="attachment-remove"
              aria-label={`Remove ${attachment.name}`}
              onClick={removeAttachment}
            >
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
                <path d="M6 6l12 12M18 6 6 18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </button>
          </div>
        )}

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
            <button
              type="button"
              className="attach"
              aria-label="Attach a PDF or DOCX document"
              onClick={() => attachmentInputRef.current?.click()}
              disabled={isLoading || attachment?.status === 'uploading'}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path
                  d="M8 12.5V7a4 4 0 1 1 8 0v9.5a2.5 2.5 0 0 1-5 0V8.5"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
            <input
              ref={attachmentInputRef}
              type="file"
              aria-label="Choose a document to attach"
              accept=".pdf,.docx"
              hidden
              onChange={handleAttachmentChange}
            />
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

      <SourcePanel citation={openCitation} onClose={() => setOpenCitation(null)} />
    </main>
  )
}
