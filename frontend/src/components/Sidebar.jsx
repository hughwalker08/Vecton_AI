import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import './Sidebar.css'

const DUMMY_CHATS = [
  { id: '1', title: 'Fire rating for external walls' },
  { id: '2', title: 'Stair handrail height requirements' },
  { id: '3', title: 'Waterproofing wet areas — NCC clauses' },
]

export default function Sidebar() {
  const { chatId: activeChatId } = useParams()
  const [isOpen, setIsOpen] = useState(false)

  function closeMenu() {
    setIsOpen(false)
  }

  return (
    <>
      <button
        className="sidebar-toggle"
        onClick={() => setIsOpen(true)}
        aria-label="Open menu"
        aria-expanded={isOpen}
      >
        <span className="hamburger-icon" />
      </button>

      {isOpen && <div className="sidebar-backdrop" onClick={closeMenu} />}

      <aside className={`sidebar ${isOpen ? 'sidebar-open' : ''}`}>
        <div className="sidebar-header">
          <span className="sidebar-brand">Vecton AI</span>
          <button
            className="sidebar-close"
            onClick={closeMenu}
            aria-label="Close menu"
          >
            ×
          </button>
        </div>

        <button className="new-chat-button" onClick={closeMenu}>
          + New chat
        </button>

        <nav className="chat-list">
          {DUMMY_CHATS.map((chat) => (
            <Link
              key={chat.id}
              to={`/chat/${chat.id}`}
              className={`chat-list-item ${chat.id === activeChatId ? 'active' : ''}`}
              onClick={closeMenu}
            >
              <span className="chat-list-item-title">{chat.title}</span>
            </Link>
          ))}
        </nav>

        <div className="sidebar-footer">
          <Link to="/upload" onClick={closeMenu}>
            Upload documents
          </Link>
        </div>
      </aside>
    </>
  )
}