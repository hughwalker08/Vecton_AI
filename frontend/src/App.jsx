import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar.jsx'
import HomePage from './pages/HomePage.jsx'
import ChatPage from './pages/ChatPage.jsx'
import UploadPage from './pages/UploadPage.jsx'
import LoginPage from './pages/LoginPage.jsx'
import OnboardingPage from './pages/OnboardingPage.jsx'
import { supabase } from './lib/supabase.js'
import * as chatStore from './lib/chats.js'
import './theme.css'
import './App.css'

export default function App() {
  const [session, setSession] = useState(null)
  const [profile, setProfile] = useState(null)
  const [isAuthLoading, setIsAuthLoading] = useState(true)
  const [isProfileLoading, setIsProfileLoading] = useState(false)
  const [chats, setChats] = useState([])
  const [uploadedFiles, setUploadedFiles] = useState([])

  // Persists the chat row before returning its id, so it exists by the time
  // ChatPage mounts and saves the first message into it (see ChatPage.jsx's
  // auto-send effect). Falls back to a client-only id on failure -- the
  // chat still works for this session, it just won't survive a refresh or
  // show up on another device, same as before this feature existed.
  async function createChat(question, jurisdiction) {
    const title = question.length > 60 ? `${question.slice(0, 57)}…` : question

    let id
    try {
      id = await chatStore.createChat(session.user.id, title, jurisdiction)
    } catch (error) {
      console.error('Could not save chat -- continuing locally only.', error)
      id = crypto.randomUUID()
    }

    setChats((currentChats) => [{ id, title, jurisdiction }, ...currentChats])

    return id
  }

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

  useEffect(() => {
    async function loadChats() {
      if (!session?.user?.id) {
        setChats([])
        return
      }

      try {
        setChats(await chatStore.listChats(session.user.id))
      } catch (error) {
        // Same stance as loadProfile() above: log it, don't block the app --
        // an empty sidebar list is a much smaller problem than the whole
        // app refusing to render because history couldn't be fetched.
        console.error(error)
      }
    }

    loadChats()
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
		element={<ChatPage chats={chats} defaultJurisdiction={profile.jurisdiction} />}
	    />
            <Route
              path="/upload"
              element={<UploadPage files={uploadedFiles} setFiles={setUploadedFiles} />}
            />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  )
}