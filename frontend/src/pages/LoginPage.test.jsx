import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import LoginPage from './LoginPage.jsx'

vi.mock('../lib/supabase.js', () => ({
  supabase: { auth: { signInWithOAuth: vi.fn() } },
}))

import { supabase } from '../lib/supabase.js'

beforeEach(() => {
  supabase.auth.signInWithOAuth.mockReset()
})

describe('LoginPage', () => {
  it('renders the brand, heading, and sign-in button', () => {
    render(<LoginPage />)

    expect(screen.getByRole('heading', { name: 'Construction Compliance Assistant' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Continue with Google' })).toBeInTheDocument()
  })

  it('starts Google sign-in with the current origin as the redirect', async () => {
    supabase.auth.signInWithOAuth.mockResolvedValue({ error: null })
    render(<LoginPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Continue with Google' }))

    expect(supabase.auth.signInWithOAuth).toHaveBeenCalledWith({
      provider: 'google',
      options: { redirectTo: window.location.origin },
    })
  })

  it('shows a loading label and disables the button while signing in', async () => {
    let resolveSignIn
    supabase.auth.signInWithOAuth.mockReturnValue(new Promise((resolve) => { resolveSignIn = resolve }))
    render(<LoginPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Continue with Google' }))

    const button = await screen.findByRole('button', { name: 'Signing in…' })
    expect(button).toBeDisabled()

    resolveSignIn({ error: null })
  })

  it('shows an error and re-enables the button when Supabase returns an error', async () => {
    supabase.auth.signInWithOAuth.mockResolvedValue({ error: new Error('provider unavailable') })
    render(<LoginPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Continue with Google' }))

    expect(await screen.findByText('Unable to sign in with Google. Please try again.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Continue with Google' })).toBeEnabled()
  })

  it('shows an error when the sign-in call itself rejects', async () => {
    supabase.auth.signInWithOAuth.mockRejectedValue(new Error('network error'))
    render(<LoginPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Continue with Google' }))

    expect(await screen.findByText('Unable to sign in with Google. Please try again.')).toBeInTheDocument()
  })
})
