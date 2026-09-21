import { useMemo, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { supabase } from '../lib/supabase.js'
import './Sidebar.css'

function getInitials(email) {
  if (!email) return '?'
  const name = email.split('@')[0]
  return name.slice(0, 2).toUpperCase()
}

export default function Sidebar({ chats = [], files = [], projects = [], onCreateProject, userEmail }) {
  const { chatId: activeChatId, projectId: activeProjectId } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const [isOpen, setIsOpen] = useState(false)
  const [filter, setFilter] = useState('')
  // 'ask' = the existing Documents/Earlier-questions tree; 'projects' = the
  // optional grouping layer above chats/folders (migration 0010).
  const [activeTab, setActiveTab] = useState('ask')
  const [isAddingProject, setIsAddingProject] = useState(false)
  const [newProjectName, setNewProjectName] = useState('')

  function toggleMenu() {
    setIsOpen(!isOpen)
  }

  function closeMenu() {
    setIsOpen(false)
  }

  async function handleSignOut() {
    // App.jsx's supabase.auth.onAuthStateChange listener clears session/
    // profile and swaps back to LoginPage once this resolves -- no local
    // state to reset here.
    await supabase.auth.signOut()
  }

  function submitNewProject() {
    const name = newProjectName.trim()
    setIsAddingProject(false)
    if (!name) return

    const id = onCreateProject?.(name)
    setNewProjectName('')
    if (id) {
      navigate(`/project/${id}`)
      closeMenu()
    }
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

          <div className="nav-tabs" role="tablist" aria-label="Sidebar view">
            <button
              type="button"
              className="nav-tab"
              role="tab"
              aria-selected={activeTab === 'ask'}
              onClick={() => setActiveTab('ask')}
            >
              Ask
            </button>
            <button
              type="button"
              className="nav-tab"
              role="tab"
              aria-selected={activeTab === 'projects'}
              onClick={() => setActiveTab('projects')}
            >
              Projects
            </button>
          </div>

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
          {activeTab === 'ask' ? (
            <>
              <div className="tree-label">Documents</div>
              {files.length === 0 ? (
                <p className="tree-empty">No documents yet</p>
              ) : (
                files.map((doc) => (
                  <Link
                    key={doc.id}
                    to="/upload"
                    className={`recent doc ${doc.status === 'error' ? 'doc-error' : ''}`}
                    title={doc.name}
                    onClick={closeMenu}
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                      <path
                        d="M6.5 3.5h7L18 8v12.5H6.5V3.5Z"
                        stroke="currentColor"
                        strokeWidth="1.6"
                        strokeLinejoin="round"
                      />
                      <path d="M13.2 3.6V8H18" stroke="currentColor" strokeWidth="1.6" />
                    </svg>
                    <span className="doc-name">{doc.name}</span>
                  </Link>
                ))
              )}

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
            </>
          ) : (
            <>
              <div className="tree-label">Projects</div>
              {isAddingProject ? (
                <form
                  className="recent project-new"
                  onSubmit={(event) => {
                    event.preventDefault()
                    submitNewProject()
                  }}
                >
                  <input
                    autoFocus
                    value={newProjectName}
                    onChange={(event) => setNewProjectName(event.target.value)}
                    onBlur={submitNewProject}
                    placeholder="Project name"
                    aria-label="New project name"
                  />
                </form>
              ) : (
                <button type="button" className="recent project-add" onClick={() => setIsAddingProject(true)}>
                  + New project
                </button>
              )}

              {projects.length === 0 ? (
                <p className="tree-empty">No projects yet</p>
              ) : (
                projects.map((project) => (
                  <Link
                    key={project.id}
                    to={`/project/${project.id}`}
                    className="recent"
                    aria-current={project.id === activeProjectId}
                    title={project.name}
                    onClick={closeMenu}
                  >
                    {project.name}
                  </Link>
                ))
              )}
            </>
          )}
        </nav>

        <div className="nav-foot">
          <div className="avatar">{getInitials(userEmail)}</div>
          <div className="who-role">
            <div className="who">{userEmail || 'Signed in'}</div>
            <div className="role">Compliance assistant</div>
          </div>
          <button
            type="button"
            className="sign-out"
            onClick={handleSignOut}
            aria-label="Sign out"
            title="Sign out"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path
                d="M15 4.5H7.5A1.5 1.5 0 0 0 6 6v12a1.5 1.5 0 0 0 1.5 1.5H15"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M10.5 12h9m0 0-3-3m3 3-3 3"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </div>
      </aside>
    </>
  )
}
