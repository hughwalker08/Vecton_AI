import { useState } from 'react'
import { supabase } from '../lib/supabase.js'
import './LoginPage.css'

export default function LoginPage() {
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleGoogleLogin() {
    setIsLoading(true)
    setError('')

    try {
      const { error: authError } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo: window.location.origin,
        },
      })

      if (authError) {
        throw authError
      }
    } catch (err) {
      console.error(err)
      setError('Unable to sign in with Google. Please try again.')
      setIsLoading(false)
    }
  }

  return (
    <main className="login-page">
      <div className="login-card">
        <div className="login-brand">
          Vecton <span className="accent">AI</span>
        </div>

        <h1>Construction Compliance Assistant</h1>

        <p className="login-description">
          Sign in to access construction compliance information for your
          Australian state or region.
        </p>

        <button
          className="google-login-button"
          type="button"
          onClick={handleGoogleLogin}
          disabled={isLoading}
        >
          {isLoading ? 'Signing in…' : 'Continue with Google'}
        </button>

        {error && <p className="login-error">{error}</p>}
      </div>
    </main>
  )
}