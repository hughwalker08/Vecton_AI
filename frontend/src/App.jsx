import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar.jsx'
import HomePage from './pages/HomePage.jsx'
import ChatPage from './pages/ChatPage.jsx'
import UploadPage from './pages/UploadPage.jsx'
import LoginPage from './pages/LoginPage.jsx'
import OnboardingPage from './pages/OnboardingPage.jsx'
import { supabase } from './lib/supabase.js'
import { deriveChatTitle } from './lib/chatTitle.js'
import './theme.css'
import './App.css'

export default function App() {
  const [session, setSession] = useState(null)
  const [profile, setProfile] = useState(null)
  const [isAuthLoading, setIsAuthLoading] = useState(true)
  const [isProfileLoading, setIsProfileLoading] = useState(false)
  const [chats, setChats] = useState([])
  const [uploadedFiles, setUploadedFiles] = useState([])
  const [folders, setFolders] = useState([])

  function createChat(question, jurisdiction) {
    const id = crypto.randomUUID()
    const title = deriveChatTitle(question)

    // Optimistic only -- the actual `conversations` row is written by
    // ChatPage once the first message is sent (see its ensureConversation),
    // not here, so this id never gets orphaned by a row insert racing a
    // reload of the chats list below.
    setChats((currentChats) => [{ id, title, jurisdiction }, ...currentChats])

    return id
  }

  // Reloads the sidebar's chat list from Supabase (see migration 0007) so it
  // survives a refresh/new tab, instead of only ever holding what this tab's
  // createChat() has added since it loaded.
  useEffect(() => {
    async function loadChats() {
      if (!session?.user?.id) {
        setChats([])
        return
      }

      const { data, error } = await supabase
        .from('conversations')
        .select('id, title, jurisdiction')
        .order('updated_at', { ascending: false })

      if (error) {
        console.error(error)
        return
      }

      setChats(data ?? [])
    }

    loadChats()
  }, [session])

  // Same reload-on-session pattern as loadChats above (see migration 0009):
  // "Project files" and its folders previously lived only in this tab's
  // React state and reset on every refresh.
  useEffect(() => {
    async function loadDocuments() {
      if (!session?.user?.id) {
        setUploadedFiles([])
        setFolders([])
        return
      }

      const [foldersResult, documentsResult] = await Promise.all([
        supabase.from('folders').select('id, name').order('created_at', { ascending: true }),
        supabase
          .from('documents')
          .select('id, folder_id, name, size, status, detail, text, created_at')
          .order('created_at', { ascending: false }),
      ])

      if (foldersResult.error) console.error(foldersResult.error)
      if (documentsResult.error) console.error(documentsResult.error)

      setFolders(foldersResult.data ?? [])
      setUploadedFiles(
        (documentsResult.data ?? []).map((row) => ({
          id: row.id,
          folderId: row.folder_id,
          name: row.name,
          size: row.size,
          status: row.status,
          detail: row.detail,
          text: row.text,
          uploadedAt: new Date(row.created_at),
        })),
      )
    }

    loadDocuments()
  }, [session])

  useEffect(() => {
    async function loadSession() {
      const {
        data: { session },
      } = await supabase.auth.getSession()

      setSession(session)
      setIsAuthLoading(false)
    }

    loadSession()

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session)

      if (!session) {
        setProfile(null)
      }

      setIsAuthLoading(false)
    })

    return () => {
      subscription.unsubscribe()
    }
  }, [])

  useEffect(() => {
    async function loadProfile() {
      if (!session?.user?.id) {
        setProfile(null)
        return
      }

      setIsProfileLoading(true)

      const { data, error } = await supabase
        .from('user_profiles')
        .select('jurisdiction')
        .eq('id', session.user.id)
        .maybeSingle()

      if (error) {
        console.error(error)
      }

      setProfile(data)
      setIsProfileLoading(false)
    }

    loadProfile()
  }, [session])

  if (isAuthLoading || isProfileLoading) {
    return <div>Loading...</div>
  }

  if (!session) {
    return <LoginPage />
  }

  if (!profile) {
    return (
      <OnboardingPage
        userId={session.user.id}
        onComplete={(jurisdiction) => {
          setProfile({ jurisdiction })
        }}
      />
    )
  }

  return (
    <BrowserRouter>
      <div className="app-shell">
        <Sidebar chats={chats} files={uploadedFiles} userEmail={session.user?.email} />

        <div className="app-main">
          <Routes>
            <Route
              path="/"
              element={<HomePage onStartChat={createChat} defaultJurisdiction={profile.jurisdiction} />}
            />
            <Route
		path="/chat/:chatId"
		element={
		  <ChatPage
		    chats={chats}
		    defaultJurisdiction={profile.jurisdiction}
		    userId={session.user.id}
		  />
		}
	    />
            <Route
              path="/upload"
              element={
                <UploadPage
                  files={uploadedFiles}
                  setFiles={setUploadedFiles}
                  folders={folders}
                  setFolders={setFolders}
                  jurisdiction={profile.jurisdiction}
                  userId={session.user.id}
                />
              }
            />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  )
}