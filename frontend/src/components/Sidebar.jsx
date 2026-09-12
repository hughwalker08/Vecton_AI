import { useMemo, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import './Sidebar.css'

function getInitials(email) {
  if (!email) return '?'
  const name = email.split('@')[0]
  return name.slice(0, 2).toUpperCase()
}

export default function Sidebar({ chats = [], userEmail }) {
  const { chatId: activeChatId } = useParams()
  const location = useLocation()
  const [isOpen, setIsOpen] = useState(false)
  const [filter, setFilter] = useState('')

  function toggleMenu() {
    setIsOpen(!isOpen)
  }

  function closeMenu() {
    setIsOpen(false)
  }

  const filteredChats = useMemo(() => {
    const query = filter.trim().toLowerCase()
    if (!query) return chats
    return chats.filter((chat) => chat.title.toLowerCase().includes(query))
  }, [chats, filter])

  const isHome = location.pathname === '/'
  const isUpload = location.pathname.startsWith('/upload')

  return (
    <>
      <button
        className="sidebar-toggle"
        onClick={toggleMenu}
        aria-label="Open menu"
        aria-expanded={isOpen}
      >
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none">
          <path
            d="M4 7h16M4 12h16M4 17h16"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinecap="round"
          />
        </svg>
      </button>

      {isOpen && <div className="scrim on" onClick={closeMenu} />}

      <aside className={`nav ${isOpen ? 'open' : ''}`}>
        <div className="nav-head">
          <div className="brand">
            <svg className="mark" viewBox="0 0 32 32" fill="none" aria-hidden="true">
              <path d="M5 5h7l6 13-3.5 7z" fill="var(--accent)" opacity=".55" />
              <path d="M20 5h7L16 29h-6z" fill="var(--accent)" />
            </svg>
            <b>
              Vecton <span>AI</span>
            </b>
          </div>

          <label className="search">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
              <circle cx="11" cy="11" r="6.5" stroke="currentColor" strokeWidth="1.7" />
              <path d="m16 16 4 4" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
            </svg>
            <input
              placeholder="Find a question"
              autoComplete="off"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
            />
          </label>

          <div className="nav-list">
            <Link
              to="/"
              className="nav-item"
              aria-current={isHome}
              onClick={() => {
                setFilter('')
                closeMenu()
              }}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
              New chat
            </Link>
            <Link
              to="/upload"
              className="nav-item"
              aria-current={isUpload}
              onClick={closeMenu}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path
                  d="M3.5 7.5A1.5 1.5 0 0 1 5 6h4l1.8 2H19a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5v-10Z"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinejoin="round"
                />
              </svg>
              Upload documents
            </Link>
          </div>
        </div>

        <nav className="tree">
          <div className="tree-label">Earlier questions</div>
          {filteredChats.length === 0 ? (
            <p className="tree-empty">
              {chats.length === 0 ? 'No questions yet' : 'Nothing matches your search'}
            </p>
          ) : (
            filteredChats.map((chat) => (
              <Link
                key={chat.id}
                to={`/chat/${chat.id}`}
                className="recent"
                aria-current={chat.id === activeChatId}
                title={chat.title}
                onClick={closeMenu}
              >
                {chat.title}
              </Link>
            ))
          )}
        </nav>

        <div className="nav-foot">
          <div className="avatar">{getInitials(userEmail)}</div>
          <div>
            <div className="who">{userEmail || 'Signed in'}</div>
            <div className="role">Compliance assistant</div>
          </div>
        </div>
      </aside>
    </>
  )
}
