import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import HomePage from './HomePage.jsx'

function renderHomePage({ defaultJurisdiction, onStartChat = vi.fn(() => 'chat-1') } = {}) {
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route
          path="/"
          element={<HomePage onStartChat={onStartChat} defaultJurisdiction={defaultJurisdiction} />}
        />
        {/* Just enough to prove navigate() actually fired, not merely that
            onStartChat was called. */}
        <Route path="/chat/:chatId" element={<div>Chat route rendered</div>} />
      </Routes>
    </MemoryRouter>
  )
  return { onStartChat }
}

describe('HomePage', () => {
  it('greets the user and shows the question composer', () => {
    renderHomePage()

    expect(screen.getByText(/good (morning|afternoon|evening)/i)).toBeInTheDocument()
    expect(
      screen.getByPlaceholderText(/ask about a clause, a condition or an inspection/i),
    ).toBeInTheDocument()
  })

  it('disables the send button until both a question and a jurisdiction are set', () => {
    renderHomePage()
    const field = screen.getByPlaceholderText(/ask about a clause/i)
    const sendButton = screen.getByRole('button', { name: 'Ask' })

    expect(sendButton).toBeDisabled()

    fireEvent.change(field, { target: { value: 'What ceiling height do we need?' } })
    expect(sendButton).toBeDisabled() // question alone isn't enough

    fireEvent.change(screen.getByLabelText('Jurisdiction for this chat'), {
      target: { value: 'NSW' },
    })
    expect(sendButton).toBeEnabled()
  })

  it('pre-fills the jurisdiction picker from defaultJurisdiction', () => {
    renderHomePage({ defaultJurisdiction: 'QLD' })

    expect(screen.getByLabelText('Jurisdiction for this chat')).toHaveValue('QLD')
  })

  it('submitting starts a chat and navigates to it with the question and jurisdiction', async () => {
    const onStartChat = vi.fn(() => 'chat-42')
    renderHomePage({ onStartChat })

    fireEvent.change(screen.getByPlaceholderText(/ask about a clause/i), {
      target: { value: 'What ceiling height do we need?' },
    })
    fireEvent.change(screen.getByLabelText('Jurisdiction for this chat'), {
      target: { value: 'NSW' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))

    expect(onStartChat).toHaveBeenCalledWith('What ceiling height do we need?', 'NSW')
    // onStartChat is now async (it persists the chat first -- see
    // App.jsx's createChat), so the navigation it triggers no longer
    // happens synchronously within the same click.
    expect(await screen.findByText('Chat route rendered')).toBeInTheDocument()
  })

  it('sends on Enter but not on Shift+Enter, and only once a jurisdiction is picked', () => {
    const onStartChat = vi.fn(() => 'chat-1')
    renderHomePage({ onStartChat })
    const field = screen.getByPlaceholderText(/ask about a clause/i)

    fireEvent.change(field, { target: { value: 'Q1' } })
    fireEvent.keyDown(field, { key: 'Enter', shiftKey: false })
    expect(onStartChat).not.toHaveBeenCalled() // no jurisdiction yet

    fireEvent.change(screen.getByLabelText('Jurisdiction for this chat'), {
      target: { value: 'VIC' },
    })
    fireEvent.keyDown(field, { key: 'Enter', shiftKey: true })
    expect(onStartChat).not.toHaveBeenCalled() // shift+enter never sends

    fireEvent.keyDown(field, { key: 'Enter', shiftKey: false })
    expect(onStartChat).toHaveBeenCalledWith('Q1', 'VIC')
  })

  it('clicking a suggestion starts a chat with that text, once a jurisdiction is set', () => {
    const onStartChat = vi.fn(() => 'chat-1')
    renderHomePage({ onStartChat, defaultJurisdiction: 'NSW' })

    fireEvent.click(
      screen.getByRole('button', { name: 'What ceiling height do we need in the bedrooms?' }),
    )

    expect(onStartChat).toHaveBeenCalledWith('What ceiling height do we need in the bedrooms?', 'NSW')
  })
})
