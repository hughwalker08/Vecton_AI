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
        <Route path="/chat/:chatId" element={<ChatPage jurisdiction={jurisdiction} />} />
      </Routes>
    </MemoryRouter>
  )
}

beforeEach(() => {
  askQuestion.mockReset()
})

describe('ChatPage', () => {
  it('sends the typed question and renders the answer with citations', async () => {
    askQuestion.mockResolvedValue({
      answer: 'Footings must comply with H1D4.',
      citations: [{ clause_id: 'H1D4', doc: 'NCC 2025 Volume Two', source_url: 'https://x/H1D4' }],
      abstained: false,
    })
    renderChatPage()

    fireEvent.change(screen.getByLabelText('Construction compliance question'), {
      target: { value: 'What are the footing requirements?' },
    })
    fireEvent.submit(screen.getByLabelText('Construction compliance question').closest('form'))

    expect(await screen.findByText('What are the footing requirements?')).toBeInTheDocument()
    expect(await screen.findByText('Footings must comply with H1D4.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /H1D4/i })).toHaveAttribute('href', 'https://x/H1D4')
    expect(askQuestion).toHaveBeenCalledWith('What are the footing requirements?', 'NSW')
  })

  it('sends the message on Enter, but not on Shift+Enter', async () => {
    askQuestion.mockResolvedValue({ answer: 'An answer.', citations: [], abstained: false })
    renderChatPage()
    const field = screen.getByLabelText('Construction compliance question')

    fireEvent.change(field, { target: { value: 'Q1' } })
    fireEvent.keyDown(field, { key: 'Enter', shiftKey: true })

    expect(askQuestion).not.toHaveBeenCalled()

    fireEvent.keyDown(field, { key: 'Enter', shiftKey: false })

    await waitFor(() => expect(askQuestion).toHaveBeenCalledWith('Q1', 'NSW'))
  })

  it('clears the input and shows a loading state while waiting for a reply', async () => {
    let resolveAnswer
    askQuestion.mockReturnValue(new Promise((resolve) => { resolveAnswer = resolve }))
    renderChatPage()
    const field = screen.getByLabelText('Construction compliance question')

    fireEvent.change(field, { target: { value: 'Q1' } })
    fireEvent.submit(field.closest('form'))

    expect(field).toHaveValue('')
    expect(await screen.findByText('Thinking…')).toBeInTheDocument()

    resolveAnswer({ answer: 'Done.', citations: [], abstained: false })

    expect(await screen.findByText('Done.')).toBeInTheDocument()
    expect(screen.queryByText('Thinking…')).not.toBeInTheDocument()
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
