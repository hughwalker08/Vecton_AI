import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import Sidebar from './Sidebar.jsx'

function renderSidebar(props = {}, { route = '/' } = {}) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Sidebar {...props} />
    </MemoryRouter>
  )
}

describe('Sidebar', () => {
  it('renders the New chat and Upload documents links', () => {
    renderSidebar()

    expect(screen.getByRole('link', { name: /new chat/i })).toHaveAttribute('href', '/')
    expect(screen.getByRole('link', { name: /upload documents/i })).toHaveAttribute('href', '/upload')
  })

  it('shows "No questions yet" when there are no chats', () => {
    renderSidebar({ chats: [] })

    expect(screen.getByText('No questions yet')).toBeInTheDocument()
  })

  it('lists each chat as a link to its chat page', () => {
    renderSidebar({
      chats: [
        { id: 'abc', title: 'Ceiling height in bedrooms' },
        { id: 'def', title: 'BAL rating for this lot' },
      ],
    })

    expect(screen.getByRole('link', { name: 'Ceiling height in bedrooms' })).toHaveAttribute(
      'href', '/chat/abc'
    )
    expect(screen.getByRole('link', { name: 'BAL rating for this lot' })).toHaveAttribute(
      'href', '/chat/def'
    )
  })

  it('filters the chat list as the user types in the search box', () => {
    renderSidebar({
      chats: [
        { id: 'abc', title: 'Ceiling height in bedrooms' },
        { id: 'def', title: 'BAL rating for this lot' },
      ],
    })

    fireEvent.change(screen.getByPlaceholderText('Find a question'), {
      target: { value: 'BAL' },
    })

    expect(screen.queryByText('Ceiling height in bedrooms')).not.toBeInTheDocument()
    expect(screen.getByText('BAL rating for this lot')).toBeInTheDocument()
  })

  it('shows "Nothing matches your search" when the filter matches no chat', () => {
    renderSidebar({ chats: [{ id: 'abc', title: 'Ceiling height in bedrooms' }] })

    fireEvent.change(screen.getByPlaceholderText('Find a question'), {
      target: { value: 'nonexistent' },
    })

    expect(screen.getByText('Nothing matches your search')).toBeInTheDocument()
  })

  it("shows the user's initials and email", () => {
    renderSidebar({ userEmail: 'jordan@example.com' })

    expect(screen.getByText('JO')).toBeInTheDocument()
    expect(screen.getByText('jordan@example.com')).toBeInTheDocument()
  })

  it('falls back to "?" and "Signed in" with no email', () => {
    renderSidebar()

    expect(screen.getByText('?')).toBeInTheDocument()
    expect(screen.getByText('Signed in')).toBeInTheDocument()
  })

  it('opens the mobile menu when the hamburger button is clicked', () => {
    renderSidebar()
    // The toggle is mobile-only (Sidebar.css hides it above 940px, and
    // jsdom's default viewport is wider than that) -- it's still in the DOM
    // and its onClick fires the same regardless, so { hidden: true } finds
    // it without needing to fake a narrow viewport. It's the only button in
    // the sidebar, so role alone identifies it (its accessible name doesn't
    // resolve cleanly through the hidden-element name computation here).
    const toggle = screen.getByRole('button', { hidden: true })

    expect(toggle).toHaveAttribute('aria-label', 'Open menu')
    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(toggle)

    expect(toggle).toHaveAttribute('aria-expanded', 'true')
  })

  it('marks "New chat" as current when on the home route', () => {
    renderSidebar({}, { route: '/' })

    expect(screen.getByRole('link', { name: /new chat/i })).toHaveAttribute('aria-current', 'true')
    expect(screen.getByRole('link', { name: /upload documents/i })).toHaveAttribute('aria-current', 'false')
  })

  it('marks "Upload documents" as current when on the upload route', () => {
    renderSidebar({}, { route: '/upload' })

    expect(screen.getByRole('link', { name: /upload documents/i })).toHaveAttribute('aria-current', 'true')
  })
})
