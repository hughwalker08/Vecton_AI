import { Link, useParams } from 'react-router-dom'
import './Sidebar.css'

const DUMMY_CHATS = [
  { id: '1', title: 'Fire rating for external walls' },
  { id: '2', title: 'Stair handrail height requirements' },
  { id: '3', title: 'Waterproofing wet areas — NCC clauses' },
]

export default function Sidebar() {
  const { chatId: activeChatId } = useParams()

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <span className="sidebar-brand">Vecton AI</span>
      </div>

      <button className="new-chat-button">+ New chat</button>

      <nav className="chat-list">
        {DUMMY_CHATS.map((chat) => (
          <Link
            key={chat.id}
            to={`/chat/${chat.id}`}
            className={`chat-list-item ${chat.id === activeChatId ? 'active' : ''}`}
          >
            <span className="chat-list-item-title">{chat.title}</span>
          </Link>
        ))}
      </nav>

      <div className="sidebar-footer">
        <Link to="/upload">Upload documents</Link>
      </div>
    </aside>
  )
}
