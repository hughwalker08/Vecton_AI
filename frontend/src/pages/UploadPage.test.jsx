import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import UploadPage from './UploadPage.jsx'

// UploadPage is still a skeleton (see its own comment) -- not wired up to
// POST /api/upload/ yet, unlike ChatPage. This locks in that placeholder
// state; it should grow into a real interaction test (choosing a file,
// mocking uploadDocument, asserting on the findings shown) once the upload
// UI is actually built.
describe('UploadPage', () => {
  it('renders its not-yet-implemented placeholder', () => {
    render(<UploadPage />)

    expect(screen.getByRole('heading', { name: 'Upload Project Documents' })).toBeInTheDocument()
    expect(screen.getByText('Upload UI not implemented yet.')).toBeInTheDocument()
  })
})
