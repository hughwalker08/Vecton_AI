import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Sidebar from './components/Sidebar.jsx'
import HomePage from './pages/HomePage.jsx'
import ChatPage from './pages/ChatPage.jsx'
import UploadPage from './pages/UploadPage.jsx'
import LoginPage from './pages/LoginPage.jsx'
import OnboardingPage from './pages/OnboardingPage.jsx'
import { supabase } from './lib/supabase.js'
import './theme.css'
import './App.css'

export default function App() {
  const [session, setSession] = useState(null)
  const [profile, setProfile] = useState(null)
  const [isAuthLoading, setIsAuthLoading] = useState(true)
  const [isProfileLoading, setIsProfileLoading] = useState(false)
  const [chats, setChats] = useState([])
  const [uploadedFiles, setUploadedFiles] = useState([])

  function createChat(question, jurisdiction) {
    const id = crypto.randomUUID()
    const title = question.length > 60 ? `${question.slice(0, 57)}…` : question

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