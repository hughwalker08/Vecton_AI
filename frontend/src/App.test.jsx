import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import App from './App.jsx'

// Phase 0 scaffolding test: proves Vitest + React Testing Library are wired
// up correctly. Not a real feature test -- see the tests added alongside
// each page/component in later phases for real coverage.
//
// App.jsx talks to Supabase on mount (session check + auth state listener),
// so the real client is stubbed out here rather than hitting the network --
// see src/lib/supabase.js for what it normally does.
vi.mock('./lib/supabase.js', () => ({
  supabase: {
    auth: {
      getSession: vi.fn().mockResolvedValue({ data: { session: null } }),
      onAuthStateChange: vi.fn().mockReturnValue({
        data: { subscription: { unsubscribe: vi.fn() } },
      }),
    },
  },
}))

describe('App', () => {
  it('renders the login page when there is no active session', async () => {
    render(<App />)

    expect(
      await screen.findByRole('heading', { name: /construction compliance assistant/i }),
    ).toBeInTheDocument()
  })
})
