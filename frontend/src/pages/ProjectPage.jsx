import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { supabase } from '../lib/supabase.js'
import FolderBrowser, { PencilIcon, XIcon } from '../components/FolderBrowser.jsx'
import './ProjectPage.css'

// A project is an optional extra layer above chats and folders (see
// migration 0010) -- this page is the "combined view" for one: its own
// chats (start one right here) and its own folders/files (reusing
// FolderBrowser, scoped by project_id the same way UploadPage scopes it by
// nothing at all, i.e. everything).
export default function ProjectPage({
  projects,
  setProjects,
  chats,
  onStartChat,
  files,
  setFiles,
  folders,
  setFolders,
  defaultJurisdiction,
  userId,
}) {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const [isRenaming, setIsRenaming] = useState(false)
  const [renameValue, setRenameValue] = useState('')
  const [question, setQuestion] = useState('')

  const project = projects.find((p) => p.id === projectId)
  const projectChats = chats.filter((c) => c.projectId === projectId)
  const projectFiles = files.filter((f) => f.projectId === projectId)
  const projectFolders = folders.filter((f) => f.projectId === projectId)

  function logIfError({ error }) {
    if (error) console.error(error)
  }

  function renameProject() {
    const name = renameValue.trim()
    setIsRenaming(false)
    if (!name) return

    setProjects((current) => current.map((p) => (p.id === projectId ? { ...p, name } : p)))
    supabase.from('projects').update({ name }).eq('id', projectId).then(logIfError)
  }

  function deleteProject() {
    setProjects((current) => current.filter((p) => p.id !== projectId))
    supabase.from('projects').delete().eq('id', projectId).then(logIfError)
    navigate('/')
  }

  // Mirrors HomePage's startChat: create the chat (tagged with this project),
  // then navigate carrying the first question the same way HomePage does, so
  // ChatPage's existing auto-send effect sends it -- no separate "new empty
  // chat" code path to keep in sync with that one.
  function startChat(event) {
    event.preventDefault()
    const trimmed = question.trim()
    if (!trimmed) return

    const chatId = onStartChat(trimmed, defaultJurisdiction, projectId)
    navigate(`/chat/${chatId}`, { state: { initialQuestion: trimmed, jurisdiction: defaultJurisdiction } })
  }

  if (!project) {
    return (
      <main className="project-page">
        <div className="project-pane">
          <p className="project-missing">Project not found.</p>
          <Link to="/">Back home</Link>
        </div>
      </main>
    )
  }

  return (
    <main className="project-page">
      <div className="project-pane">
        <div className="project-head">
          {isRenaming ? (
            <form
              className="project-rename"
              onSubmit={(e) => {
                e.preventDefault()
                renameProject()
              }}
            >
              <input
                autoFocus
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
                onBlur={renameProject}
                aria-label={`Rename project ${project.name}`}
              />
            </form>
          ) : (
            <h1>
              {project.name}
              <button
                type="button"
                aria-label={`Rename ${project.name}`}
                onClick={() => {
                  setIsRenaming(true)
                  setRenameValue(project.name)
                }}
              >
                <PencilIcon />
              </button>
              <button type="button" aria-label={`Delete ${project.name}`} onClick={deleteProject}>
                <XIcon />
              </button>
            </h1>
          )}
        </div>

        <section className="project-section">
          <h2>Chats</h2>
          <form className="project-new-chat" onSubmit={startChat}>
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask a question to start a chat in this project…"
              aria-label="Start a new chat in this project"
            />
            <button type="submit" disabled={!question.trim()}>
              Start chat
            </button>
          </form>

          {projectChats.length === 0 ? (
            <p className="project-empty">No chats in this project yet.</p>
          ) : (
            <ul className="project-chat-list">
              {projectChats.map((chat) => (
                <li key={chat.id}>
                  <Link to={`/chat/${chat.id}`}>{chat.title}</Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="project-section">
          <h2>Files</h2>
          <FolderBrowser
            files={projectFiles}
            setFiles={setFiles}
            folders={projectFolders}
            setFolders={setFolders}
            userId={userId}
            projectId={projectId}
          />
        </section>
      </div>
    </main>
  )
}
