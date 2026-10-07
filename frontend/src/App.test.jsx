import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App.jsx'

// App.jsx talks to Supabase on mount (session check, auth state listener,
// and a user_profiles lookup once signed in) -- the real client is stubbed
// out here rather than hitting the network. See src/lib/supabase.js for
// what it normally does.
vi.mock('./lib/supabase.js', () => ({
  supabase: {
    auth: {
      getSession: vi.fn(),
      onAuthStateChange: vi.fn().mockReturnValue({
        data: { subscription: { unsubscribe: vi.fn() } },
      }),
    },
    from: vi.fn(),
  },
}))

vi.mock('./api/client.js', () => ({
  askQuestion: vi.fn(),
  uploadDocument: vi.fn(),
}))

// Wraps the real OnboardingPage so a test can count how many times it was
// rendered (see the "never flashes onboarding" test) without changing what it
// renders for the tests that do want the real screen.
const onboardingRenders = vi.hoisted(() => ({ count: 0 }))
vi.mock('./pages/OnboardingPage.jsx', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    default: function CountedOnboardingPage(props) {
      onboardingRenders.count += 1
      return actual.default(props)
    },
  }
})

import { askQuestion, uploadDocument } from './api/client.js'
import { supabase } from './lib/supabase.js'

function mockSignedOut() {
  supabase.auth.getSession.mockResolvedValue({ data: { session: null } })
}

// Routes by table name so this one mock covers the user_profiles lookup
// (App.jsx's loadProfile) as well as the conversations/messages calls that
// fire once inside the real ChatPage a "start a chat" test navigates into
// (see ChatPage.jsx's ensureConversation/saveMessage/history-load), the
// folders/documents calls App.jsx's loadDocuments and the real UploadPage
// fire (see migration 0009), and projects (App.jsx's loadProjects, migration
// 0010) -- none of these tests seed prior chat/document/project history, so
// every read here always resolves empty.
function mockSignedIn({ jurisdiction = 'NSW', email = 'jordan@example.com' } = {}) {
  supabase.auth.getSession.mockResolvedValue({
    data: { session: { user: { id: 'user-1', email } } },
  })
  supabase.from.mockImplementation((table) => {
    if (table === 'user_profiles') {
      return {
        select: () => ({
          eq: () => ({
            maybeSingle: () =>
              Promise.resolve({
                data: jurisdiction ? { jurisdiction } : null,
                error: null,
              }),
          }),
        }),
      }
    }
    if (table === 'conversations') {
      return {
        select: () => ({ order: () => Promise.resolve({ data: [], error: null }) }),
        upsert: () => Promise.resolve({ error: null }),
      }
    }
    if (table === 'messages') {
      return {
        select: () => ({
          eq: () => ({ order: () => Promise.resolve({ data: [], error: null }) }),
        }),
        insert: () => Promise.resolve({ error: null }),
      }
    }
    if (table === 'folders') {
      return {
        select: () => ({ order: () => Promise.resolve({ data: [], error: null }) }),
        insert: () => Promise.resolve({ error: null }),
        update: () => ({ eq: () => Promise.resolve({ error: null }) }),
        delete: () => ({ eq: () => Promise.resolve({ error: null }) }),
      }
    }
    if (table === 'documents') {
      return {
        select: () => ({ order: () => Promise.resolve({ data: [], error: null }) }),
        insert: () => Promise.resolve({ error: null }),
        update: () => ({ eq: () => Promise.resolve({ error: null }) }),
        delete: () => ({ eq: () => Promise.resolve({ error: null }) }),
      }
    }
    if (table === 'projects') {
      return {
        select: () => ({ order: () => Promise.resolve({ data: [], error: null }) }),
        insert: () => Promise.resolve({ error: null }),
        update: () => ({ eq: () => Promise.resolve({ error: null }) }),
        delete: () => ({ eq: () => Promise.resolve({ error: null }) }),
      }
    }
    throw new Error(`mockSignedIn: unhandled supabase table "${table}"`)
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  onboardingRenders.count = 0
  supabase.auth.onAuthStateChange.mockReturnValue({
    data: { subscription: { unsubscribe: vi.fn() } },
  })
  // App wraps everything in a real BrowserRouter, which reads jsdom's actual
  // window.history -- that persists across tests in this file (jsdom's
  // window isn't recreated per-test), so a test that navigate()s with state
  // (e.g. "starting a chat from the home page") leaves the next render(<App
  // />) starting on that same leftover URL/state instead of "/". Reset it
  // before every test so each one starts from a clean address bar.
  window.history.pushState({}, '', '/')
})

describe('App', () => {
  it('renders the login page when there is no active session', async () => {
    mockSignedOut()

    render(<App />)

    expect(
      await screen.findByRole('heading', { name: /construction compliance assistant/i }),
    ).toBeInTheDocument()
  })

  // This used to be `it.skipIf(process.env.CI)`: it failed reliably on
  // GitHub's runner and only occasionally locally, and nothing explained why.
  // The cause was a real race in App.jsx -- for one render after sign-in,
  // profile was still null while the loading flag hadn't flipped, so the
  // onboarding screen rendered, then got replaced by "Loading...", and
  // findByRole could grab the heading just before it was detached. Fixed
  // (loading is now derived from whether this user's profile has resolved),
  // and covered directly by the render-count test below.
  it('renders onboarding when signed in but no jurisdiction is set yet', async () => {
    mockSignedIn({ jurisdiction: null })

    render(<App />)

    expect(
      await screen.findByRole('heading', { name: /select your state or territory/i }),
    ).toBeInTheDocument()
  })

  it('never renders the onboarding screen for a returning user while their profile loads', async () => {
    // The bug was a single intermediate render: session arrived, profile still
    // null, loading flag not yet set. Whether React commits that render to the
    // DOM is timing-dependent (that's why this used to fail only sometimes),
    // but whether it *renders* the component is not -- so count renders.
    mockSignedIn()

    render(<App />)
    expect(await screen.findByRole('link', { name: /new chat/i })).toBeInTheDocument()

    expect(onboardingRenders.count).toBe(0)
  })

  it('does not drop back to Loading (and unmount the app) when Supabase re-emits an auth event', async () => {
    // Supabase fires onAuthStateChange again with a *new* session object when
    // the tab regains focus. Re-running the profile lookup for it used to
    // swap the whole app -- router and open chat included -- for "Loading...".
    mockSignedIn()
    render(<App />)
    expect(await screen.findByRole('link', { name: /new chat/i })).toBeInTheDocument()
    const profileLookups = () =>
      supabase.from.mock.calls.filter(([table]) => table === 'user_profiles').length
    expect(profileLookups()).toBe(1)

    const emitAuthEvent = supabase.auth.onAuthStateChange.mock.calls[0][0]
    await act(async () => {
      emitAuthEvent('SIGNED_IN', { user: { id: 'user-1', email: 'jordan@example.com' } })
    })

    expect(screen.queryByText('Loading...')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /new chat/i })).toBeInTheDocument()
    expect(profileLookups()).toBe(1)
  })

  it('renders the home page, with the sidebar, once signed in with a profile', async () => {
    mockSignedIn()

    render(<App />)

    expect(await screen.findByRole('link', { name: /new chat/i })).toBeInTheDocument()
    expect(screen.getByText('jordan@example.com')).toBeInTheDocument()
    expect(screen.getByText(/good (morning|afternoon|evening)/i)).toBeInTheDocument()
  })

  it('starting a chat from the home page navigates to the chat page and asks the question', async () => {
    mockSignedIn()
    askQuestion.mockResolvedValue({ answer: 'Riser height is 190mm max.', citations: [], abstained: false })

    render(<App />)

    const field = await screen.findByPlaceholderText(/ask about a clause/i)
    fireEvent.change(field, { target: { value: 'What is the max riser height?' } })
    fireEvent.submit(field.closest('form'))

    expect(await screen.findByText('Riser height is 190mm max.')).toBeInTheDocument()
    // First message in a brand-new chat -- no prior turns and nothing attached yet.
    expect(askQuestion).toHaveBeenCalledWith('What is the max riser height?', 'NSW', {
      history: [],
      attachment: null,
    })
    // The question that started the chat also shows up as the new sidebar entry.
    expect(screen.getByRole('link', { name: 'What is the max riser height?' })).toBeInTheDocument()
  })

  it('attaching a document on the home page carries its text into the first chat message', async () => {
    mockSignedIn()
    uploadDocument.mockResolvedValue({ text_extraction: 'All footings are 300mm deep.' })
    askQuestion.mockResolvedValue({ answer: 'Looks compliant.', citations: [], abstained: false })

    render(<App />)

    const file = new File(['plan contents'], 'site-plan.pdf', { type: 'application/pdf' })
    fireEvent.change(await screen.findByLabelText('Choose a document to attach'), {
      target: { files: [file] },
    })
    expect(await screen.findByText('Attached')).toBeInTheDocument()

    const field = screen.getByPlaceholderText(/ask about a clause/i)
    fireEvent.change(field, { target: { value: 'Does my plan comply?' } })
    fireEvent.submit(field.closest('form'))

    expect(await screen.findByText('Looks compliant.')).toBeInTheDocument()
    expect(askQuestion).toHaveBeenCalledWith('Does my plan comply?', 'NSW', {
      history: [],
      attachment: { name: 'site-plan.pdf', text: 'All footings are 300mm deep.' },
    })
  })

  it('navigating to Upload documents shows the upload page', async () => {
    mockSignedIn()

    render(<App />)

    fireEvent.click(await screen.findByRole('link', { name: /upload documents/i }))

    expect(await screen.findByRole('heading', { name: 'Project files' })).toBeInTheDocument()
  })

  it('a document uploaded on the upload page also shows up in the sidebar', async () => {
    mockSignedIn()
    uploadDocument.mockResolvedValue({ status: 'processed 1 image(s) from plan.pdf' })

    render(<App />)

    fireEvent.click(await screen.findByRole('link', { name: /upload documents/i }))
    const file = new File(['%PDF-1.4'], 'plan.pdf', { type: 'application/pdf' })
    fireEvent.change(document.querySelector('input[type="file"]'), { target: { files: [file] } })

    // Sidebar's "Documents" section reads the same uploadedFiles state as
    // the upload page itself -- both should show the new file.
    expect(await screen.findAllByText('plan.pdf')).toHaveLength(2)
    expect(await screen.findByText('processed 1 image(s) from plan.pdf')).toBeInTheDocument()
  })
})
