import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ChatPage from './ChatPage.jsx'

vi.mock('../api/client.js', () => ({
  askQuestion: vi.fn(),
}))

import { askQuestion } from '../api/client.js'

function renderChatPage({ jurisdiction = 'NSW', route = '/chat/abc', state } = {}) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: route, state }]}>
      <Routes>
        {/* defaultJurisdiction, not a jurisdiction prop directly -- ChatPage
            resolves jurisdiction per-chat (from the chats list, falling
            back to route state, then this default). None of these tests
            pass a chats list or state.jurisdiction, so the default is what
            actually reaches askQuestion. */}
        <Route path="/chat/:chatId" element={<ChatPage defaultJurisdiction={jurisdiction} />} />
      </Routes>
    </MemoryRouter>
  )
}

beforeEach(() => {
  askQuestion.mockReset()
})

describe('ChatPage', () => {
  it('sends the typed question and renders the answer with citations, opening the source panel on click', async () => {
    askQuestion.mockResolvedValue({
      answer: 'Footings must comply with H1D4.',
      citations: [
        {
          clause_id: 'H1D4',
          doc: 'NCC 2025 Volume Two',
          source_url: null,
          heading: 'Footings',
          text: 'Footings must be designed to transfer loads to the ground.',
        },
      ],
      abstained: false,
    })
    renderChatPage()

    fireEvent.change(screen.getByLabelText('Construction compliance question'), {
      target: { value: 'What are the footing requirements?' },
    })
    fireEvent.submit(screen.getByLabelText('Construction compliance question').closest('form'))

    expect(await screen.findByText('What are the footing requirements?')).toBeInTheDocument()
    expect(await screen.findByText('Footings must comply with H1D4.')).toBeInTheDocument()
    // First message in this chat -- no prior turns to send yet.
    expect(askQuestion).toHaveBeenCalledWith('What are the footing requirements?', 'NSW', [])

    // Citations don't carry a source_url (nothing in the corpus populates
    // one yet -- see backend/app/models/clause_chunk.py), so they're
    // buttons that open the in-app source panel rather than links.
    const citationButton = screen.getByRole('button', { name: /H1D4/i })
    fireEvent.click(citationButton)

    expect(await screen.findByText('Footings')).toBeInTheDocument()
    expect(
      screen.getByText('Footings must be designed to transfer loads to the ground.'),
    ).toBeInTheDocument()
  })

  it('sends the message on Enter, but not on Shift+Enter', async () => {
    askQuestion.mockResolvedValue({ answer: 'An answer.', citations: [], abstained: false })
    renderChatPage()
    const field = screen.getByLabelText('Construction compliance question')

    fireEvent.change(field, { target: { value: 'Q1' } })
    fireEvent.keyDown(field, { key: 'Enter', shiftKey: true })

    expect(askQuestion).not.toHaveBeenCalled()

    fireEvent.keyDown(field, { key: 'Enter', shiftKey: false })

    await waitFor(() => expect(askQuestion).toHaveBeenCalledWith('Q1', 'NSW', []))
  })

  it('sends prior turns as history on a follow-up question, but not the one just asked', async () => {
    askQuestion
      .mockResolvedValueOnce({ answer: 'Minimum 2.4m per H1D4.', citations: [], abstained: false })
      .mockResolvedValueOnce({ answer: 'Also 2.4m in NSW.', citations: [], abstained: false })
    renderChatPage()
    const field = screen.getByLabelText('Construction compliance question')

    fireEvent.change(field, { target: { value: 'What ceiling height do we need in bedrooms?' } })
    fireEvent.submit(field.closest('form'))
    expect(await screen.findByText('Minimum 2.4m per H1D4.')).toBeInTheDocument()

    fireEvent.change(field, { target: { value: 'What about NSW?' } })
    fireEvent.submit(field.closest('form'))
    expect(await screen.findByText('Also 2.4m in NSW.')).toBeInTheDocument()

    expect(askQuestion).toHaveBeenLastCalledWith('What about NSW?', 'NSW', [
      { role: 'user', text: 'What ceiling height do we need in bedrooms?' },
      { role: 'assistant', text: 'Minimum 2.4m per H1D4.' },
    ])
  })

  it('does not replay a failed request as if the assistant had said it', async () => {
    askQuestion
      .mockRejectedValueOnce(new Error('Quota exceeded.'))
      .mockResolvedValueOnce({ answer: 'A real answer.', citations: [], abstained: false })
    renderChatPage()
    const field = screen.getByLabelText('Construction compliance question')

    fireEvent.change(field, { target: { value: 'Q1' } })
    fireEvent.submit(field.closest('form'))
    expect(await screen.findByText('Quota exceeded.')).toBeInTheDocument()

    fireEvent.change(field, { target: { value: 'Q2' } })
    fireEvent.submit(field.closest('form'))
    expect(await screen.findByText('A real answer.')).toBeInTheDocument()

    // Q1's error bubble is a UI-only failure notice, not a real assistant
    // turn -- it must not be replayed back to the model as history.
    expect(askQuestion).toHaveBeenLastCalledWith('Q2', 'NSW', [])
  })

  it('clears the input and shows a loading state while waiting for a reply', async () => {
    let resolveAnswer
    askQuestion.mockReturnValue(new Promise((resolve) => { resolveAnswer = resolve }))
    renderChatPage()
    const field = screen.getByLabelText('Construction compliance question')

    fireEvent.change(field, { target: { value: 'Q1' } })
    fireEvent.submit(field.closest('form'))

    expect(field).toHaveValue('')
    // The loading indicator cycles through stage text (retrieving ->
    // reranking -> generating) rather than a static "Thinking..." -- only
    // the first stage is visible this soon after submit.
    expect(await screen.findByText('Retrieving relevant clauses…')).toBeInTheDocument()

    resolveAnswer({ answer: 'Done.', citations: [], abstained: false })

    expect(await screen.findByText('Done.')).toBeInTheDocument()
    expect(screen.queryByText('Retrieving relevant clauses…')).not.toBeInTheDocument()
  })

  it('shows the abstain note when the backend abstains', async () => {
    askQuestion.mockResolvedValue({ answer: 'No source found.', citations: [], abstained: true })
    renderChatPage()

    fireEvent.change(screen.getByLabelText('Construction compliance question'), {
      target: { value: 'An unrelated question' },
    })
    fireEvent.submit(screen.getByLabelText('Construction compliance question').closest('form'))

    expect(await screen.findByText('No matching source was found for this question.')).toBeInTheDocument()
  })

  it('shows an error bubble when the request fails, without an abstain note', async () => {
    askQuestion.mockRejectedValue(new Error('Quota exceeded. Try again in about 30s.'))
    renderChatPage()

    fireEvent.change(screen.getByLabelText('Construction compliance question'), {
      target: { value: 'Q1' },
    })
    fireEvent.submit(screen.getByLabelText('Construction compliance question').closest('form'))

    expect(await screen.findByText('Quota exceeded. Try again in about 30s.')).toBeInTheDocument()
    expect(screen.queryByText('No matching source was found for this question.')).not.toBeInTheDocument()
  })

  it('automatically sends the initial question carried in route state', async () => {
    askQuestion.mockResolvedValue({ answer: 'Auto-sent answer.', citations: [], abstained: false })

    renderChatPage({ state: { initialQuestion: 'What ceiling height do we need?' } })

    expect(await screen.findByText('What ceiling height do we need?')).toBeInTheDocument()
    expect(await screen.findByText('Auto-sent answer.')).toBeInTheDocument()
    expect(askQuestion).toHaveBeenCalledTimes(1)
  })

  it('disables the send button while a question is empty or blank', () => {
    renderChatPage()
    const field = screen.getByLabelText('Construction compliance question')
    const sendButton = screen.getByRole('button', { name: /send/i })

    expect(sendButton).toBeDisabled()

    fireEvent.change(field, { target: { value: '   ' } })
    expect(sendButton).toBeDisabled()

    fireEvent.change(field, { target: { value: 'A real question' } })
    expect(sendButton).toBeEnabled()
  })
})
