import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import ProjectPage from './ProjectPage.jsx'

// ProjectPage writes project rename/delete directly to Supabase (matching
// FolderBrowser's own pattern) and FolderBrowser (rendered inside it) does
// the same for folders/documents -- stub every write so no real network
// call happens; none of these tests assert on what got persisted, just on
// the resulting UI/local-state behavior.
vi.mock('../lib/supabase.js', () => ({
  supabase: {
    from: vi.fn(() => ({
      insert: () => Promise.resolve({ error: null }),
      update: () => ({ eq: () => Promise.resolve({ error: null }) }),
      delete: () => ({ eq: () => Promise.resolve({ error: null }) }),
    })),
  },
}))

vi.mock('../api/client.js', () => ({
  uploadDocument: vi.fn(),
}))

function renderProjectPage(props = {}, { route = '/project/p1' } = {}) {
  const defaults = {
    projects: [{ id: 'p1', name: 'Wattle Court build' }],
    setProjects: vi.fn(),
    chats: [],
    onStartChat: vi.fn(),
    files: [],
    setFiles: vi.fn(),
    folders: [],
    setFolders: vi.fn(),
    defaultJurisdiction: 'NSW',
    userId: 'user-1',
  }

  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/" element={<div>home page</div>} />
        <Route path="/project/:projectId" element={<ProjectPage {...defaults} {...props} />} />
        <Route path="/chat/:chatId" element={<div>chat page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ProjectPage', () => {
  it('shows a "not found" message for an unknown project id', () => {
    renderProjectPage({ projects: [] })

    expect(screen.getByText('Project not found.')).toBeInTheDocument()
  })

  it('renders the project name and only its own chats', () => {
    renderProjectPage({
      chats: [
        { id: 'c1', title: 'Ceiling height question', projectId: 'p1' },
        { id: 'c2', title: 'Unrelated chat', projectId: null },
        { id: 'c3', title: 'Other project chat', projectId: 'p2' },
      ],
    })

    expect(screen.getByRole('heading', { name: /wattle court build/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Ceiling height question' })).toHaveAttribute(
      'href',
      '/chat/c1',
    )
    expect(screen.queryByText('Unrelated chat')).not.toBeInTheDocument()
    expect(screen.queryByText('Other project chat')).not.toBeInTheDocument()
  })

  it('shows only this project\'s files, not unfiled or other projects\' files', () => {
    renderProjectPage({
      files: [
        { id: 1, name: 'in-project.pdf', size: 1024, uploadedAt: new Date(), status: 'done', folderId: null, projectId: 'p1' },
        { id: 2, name: 'unfiled.pdf', size: 1024, uploadedAt: new Date(), status: 'done', folderId: null, projectId: null },
        { id: 3, name: 'other-project.pdf', size: 1024, uploadedAt: new Date(), status: 'done', folderId: null, projectId: 'p2' },
      ],
    })

    expect(screen.getByText('in-project.pdf')).toBeInTheDocument()
    expect(screen.queryByText('unfiled.pdf')).not.toBeInTheDocument()
    expect(screen.queryByText('other-project.pdf')).not.toBeInTheDocument()
  })

  it('starting a chat from the composer tags it with this project and navigates to it', () => {
    const onStartChat = vi.fn().mockReturnValue('new-chat-id')
    renderProjectPage({ onStartChat })

    fireEvent.change(screen.getByLabelText('Start a new chat in this project'), {
      target: { value: 'What ceiling height do we need?' },
    })
    fireEvent.submit(screen.getByLabelText('Start a new chat in this project').closest('form'))

    expect(onStartChat).toHaveBeenCalledWith('What ceiling height do we need?', 'NSW', 'p1')
    expect(screen.getByText('chat page')).toBeInTheDocument()
  })

  it('renames the project', () => {
    const setProjects = vi.fn()
    renderProjectPage({ setProjects })

    fireEvent.click(screen.getByRole('button', { name: 'Rename Wattle Court build' }))
    fireEvent.change(screen.getByLabelText('Rename project Wattle Court build'), {
      target: { value: '14 Wattle Court' },
    })
    fireEvent.submit(screen.getByLabelText('Rename project Wattle Court build').closest('form'))

    expect(setProjects).toHaveBeenCalled()
    const updater = setProjects.mock.calls[0][0]
    expect(updater([{ id: 'p1', name: 'Wattle Court build' }])).toEqual([
      { id: 'p1', name: '14 Wattle Court' },
    ])
  })

  it('deleting the project removes it and navigates home', () => {
    const setProjects = vi.fn()
    renderProjectPage({ setProjects })

    fireEvent.click(screen.getByRole('button', { name: 'Delete Wattle Court build' }))

    expect(setProjects).toHaveBeenCalled()
    const updater = setProjects.mock.calls[0][0]
    expect(updater([{ id: 'p1', name: 'Wattle Court build' }])).toEqual([])
  })
})
