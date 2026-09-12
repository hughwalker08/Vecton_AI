import { createClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabaseKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY

// Dev-only stand-in for when frontend/.env has no real Supabase project
// configured. Lets the app render (as an already-authed, onboarded user)
// instead of crashing, so frontend-only work doesn't need real credentials.
// Set VITE_SUPABASE_URL / VITE_SUPABASE_PUBLISHABLE_KEY in frontend/.env to
// use the real client and test auth/onboarding for real.
function createMockClient() {
  console.warn(
    '[supabase] VITE_SUPABASE_URL / VITE_SUPABASE_PUBLISHABLE_KEY not set — ' +
      'using a mock client so the app can run without Supabase. ' +
      'Auth is stubbed out as a logged-in user; set real credentials in ' +
      'frontend/.env to test login/onboarding.',
  )

  const mockSession = {
    user: { id: 'local-dev-user', email: 'dev@example.com' },
  }

  const queryBuilder = {
    select() {
      return this
    },
    eq() {
      return this
    },
    async maybeSingle() {
      return { data: { jurisdiction: 'NSW' }, error: null }
    },
    async upsert() {
      return { data: null, error: null }
    },
  }

  return {
    auth: {
      async getSession() {
        return { data: { session: mockSession }, error: null }
      },
      onAuthStateChange() {
        return { data: { subscription: { unsubscribe() {} } } }
      },
      async signInWithOAuth() {
        return { error: null }
      },
      async signOut() {
        return { error: null }
      },
    },
    from() {
      return queryBuilder
    },
  }
}

export const supabase =
  supabaseUrl && supabaseKey ? createClient(supabaseUrl, supabaseKey) : createMockClient()
