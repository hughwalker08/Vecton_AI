import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Sidebar from './components/Sidebar.jsx'
import ChatPage from './pages/ChatPage.jsx'
import UploadPage from './pages/UploadPage.jsx'
import LoginPage from './pages/LoginPage.jsx'
import OnboardingPage from './pages/OnboardingPage.jsx'
import { supabase } from './lib/supabase.js'
import './App.css'

export default function App() {
  const [session, setSession] = useState(null)
  const [profile, setProfile] = useState(null)
  const [isAuthLoading, setIsAuthLoading] = useState(true)
  const [isProfileLoading, setIsProfileLoading] = useState(false)

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
        {/* <Sidebar /> */}

        <div className="app-main">
          <Routes>
            <Route path="/" element={<Navigate to="/chat/1" replace />} />
            <Route
		path="/chat/:chatId"
		element={<ChatPage jurisdiction={profile.jurisdiction} />}
	    />
            <Route path="/upload" element={<UploadPage />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  )
}