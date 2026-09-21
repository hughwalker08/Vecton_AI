import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { askQuestion } from '../api/client.js'
import { useAttachment } from '../hooks/useAttachment.js'
import { supabase } from '../lib/supabase.js'
import { deriveChatTitle } from '../lib/chatTitle.js'
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

export default function ChatPage({ chats = [], defaultJurisdiction, userId }) {
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
  const navigate = useNavigate()
  const startedChatId = useRef(null)
  // Guards ensureConversation() (see sendMessage) so a chat with several
  // messages doesn't re-upsert its `conversations` row on every send --
  // set once per chatId, the first time a message for it is actually sent.
  const ensuredChatId = useRef(null)
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
  // Optional project this chat was started from (see App.jsx's createChat and
  // ProjectPage) -- null for a chat started outside any project, same as an
  // unfiled document has no folder.
  const projectId = chats.find((chat) => chat.id === chatId)?.projectId ?? null

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

  // Loads a revisited chat's messages from Supabase (see migration 0007) so
  // reopening one from the sidebar, or refreshing mid-chat, doesn't come back
  // empty. Skipped when `initialQuestion` is pending: that's a chat just
  // created on the home page, which has nothing to load yet and is about to
  // populate `messages` itself via the auto-send effect below -- fetching
  // here first would (at best) race it, and at worst briefly flash empty.
  useEffect(() => {
    if (location.state?.initialQuestion || !chatId) {
      return
    }

    let cancelled = false

    async function loadMessages() {
      const { data, error } = await supabase
        .from('messages')
        .select('id, role, text, citations, is_error, abstained')
        .eq('conversation_id', chatId)
        .order('created_at', { ascending: true })

      if (cancelled) return

      if (error) {
        console.error(error)
        return
      }

      ensuredChatId.current = chatId
      const loaded = (data ?? []).map((row) => ({
        id: row.id,
        role: row.role,
        text: row.text,
        citations: row.citations ?? [],
        isError: row.is_error,
        abstained: row.abstained,
      }))
      // Functional update, checked against the *current* messages rather
      // than whatever this closure captured at mount: if the user already
      // sent a message before this fetch resolved (a slow network, revisiting
      // a chat and typing immediately), don't stomp on it with a load that
      // was already stale the moment it landed.
      setMessages((current) => (current.length === 0 ? loaded : current))
    }

    loadMessages()

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatId])

  // Creates this chat's `conversations` row the first time it actually gets
  // a message (not when it's merely opened -- see App.jsx's createChat for
  // why the row doesn't exist yet at that point). `ignoreDuplicates` makes
  // this a no-op, not an overwrite, on every later message in the same chat
  // (also reached, harmlessly, on a chat loaded above: ensuredChatId is
  // already set there, so this is only ever a real insert once per chat).
  async function ensureConversation(firstQuestion) {
    if (ensuredChatId.current === chatId) return
    ensuredChatId.current = chatId

    const { error } = await supabase.from('conversations').upsert(
      { id: chatId, user_id: userId, title: deriveChatTitle(firstQuestion), jurisdiction, project_id: projectId },
      { onConflict: 'id', ignoreDuplicates: true },
    )

    if (error) console.error(error)
  }

  // Best-effort: chat still works this session even if a write fails (e.g.
  // offline), it just won't survive a refresh. Errors are logged, not
  // surfaced -- matches how the rest of this app treats Supabase writes
  // (see App.jsx's loadProfile/loadChats).
  function saveMessage(row) {
    supabase
      .from('messages')
      .insert({ conversation_id: chatId, user_id: userId, ...row })
      .then(({ error }) => {
        if (error) console.error(error)
      })
  }

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

    // Must resolve before saveMessage below: messages.conversation_id is a
    // foreign key into conversations, so the row has to exist first.
    await ensureConversation(trimmedQuestion)
    saveMessage({
      role: 'user',
      text: trimmedQuestion,
      attachment_name: activeAttachment?.status === 'ready' ? activeAttachment.name : null,
    })

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
      saveMessage({
        role: 'assistant',
        text: assistantMessage.text,
        citations: assistantMessage.citations.length ? assistantMessage.citations : null,
        abstained: assistantMessage.abstained,
      })
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
      saveMessage({ role: 'assistant', text: errorMessage.text, is_error: true })

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
  //
  // startedChatId alone isn't enough: it's a ref, so it resets to null on
  // any fresh page load of this URL, not just a genuine new chat -- but the
  // browser's own history state (what location.state reads from) survives a
  // reload. Without clearing it below, refreshing a chat right after
  // starting it (or the tab getting reloaded in the background, e.g. by the
  // dev server's HMR socket reconnecting) replays the first question and
  // regenerates the answer.
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
      navigate(location.pathname, { replace: true, state: {} })
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
