import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import UploadPage from './UploadPage.jsx'

vi.mock('../api/client.js', () => ({
  uploadDocument: vi.fn(),
}))

// UploadPage persists documents/folders to Supabase (see migration 0009).
// None of these tests exercise persistence itself; this just keeps them
// from making real network calls, with every write resolving successfully.
vi.mock('../lib/supabase.js', () => ({
  supabase: {
    from: vi.fn(() => ({
      insert: () => Promise.resolve({ error: null }),
      update: () => ({ eq: () => Promise.resolve({ error: null }) }),
      delete: () => ({ eq: () => Promise.resolve({ error: null }) }),
    })),
  },
}))

import { uploadDocument } from '../api/client.js'

function renderUploadPage(files = [], { folders = [] } = {}) {
  const setFiles = vi.fn()
  const setFolders = vi.fn()
  const utils = render(
    <UploadPage
      files={files}
      setFiles={setFiles}
      folders={folders}
      setFolders={setFolders}
      userId="user-1"
    />,
  )
  return { ...utils, setFiles, setFolders }
}

// UploadPage manages its file list via the setFiles updater App.jsx owns;
// since setFiles is mocked here, these helpers replay what a real setState
// updater call would have produced, so a test can pass the result straight
// back in as the next render's `files` prop.
function applyUpdater(current, setFilesMock, callIndex = 0) {
  const updater = setFilesMock.mock.calls[callIndex][0]
  return updater(current)
}

const pdfFile = (name = 'plan.pdf') => new File(['%PDF-1.4'], name, { type: 'application/pdf' })

beforeEach(() => {
  uploadDocument.mockReset()
})

describe('UploadPage', () => {
  it('shows the empty state when no documents have been uploaded', () => {
    renderUploadPage([])

    expect(screen.getByText('No documents uploaded yet')).toBeInTheDocument()
    expect(screen.getByText('0')).toBeInTheDocument()
  })

  it('adds a dropped file to the list immediately as "uploading"', () => {
    uploadDocument.mockReturnValue(new Promise(() => {})) // never resolves in this test
    const { setFiles } = renderUploadPage([])

    fireEvent.drop(screen.getByRole('button', { name: 'Upload a document' }), {
      dataTransfer: { files: [pdfFile()] },
    })

    expect(setFiles).toHaveBeenCalled()
    const next = applyUpdater([], setFiles)
    expect(next).toHaveLength(1)
    expect(next[0]).toMatchObject({ name: 'plan.pdf', status: 'uploading', detail: 'Uploading…' })
    expect(uploadDocument).toHaveBeenCalledWith(next[0].file)
  })

  it('adds a file chosen via the file input', () => {
    uploadDocument.mockReturnValue(new Promise(() => {}))
    const { setFiles } = renderUploadPage([])
    const input = document.querySelector('input[type="file"]')

    fireEvent.change(input, { target: { files: [pdfFile('certificate.docx')] } })

    const next = applyUpdater([], setFiles)
    expect(next[0].name).toBe('certificate.docx')
  })

  it('marks a file as done once the upload resolves', async () => {
    uploadDocument.mockResolvedValue({ status: 'processed 1 image(s) from plan.pdf' })
    const { setFiles } = renderUploadPage([])

    fireEvent.drop(screen.getByRole('button', { name: 'Upload a document' }), { dataTransfer: { files: [pdfFile()] } })
    const uploading = applyUpdater([], setFiles, 0)

    await vi.waitFor(() => expect(setFiles).toHaveBeenCalledTimes(2))
    const done = applyUpdater(uploading, setFiles, 1)

    expect(done[0]).toMatchObject({
      status: 'done',
      detail: 'processed 1 image(s) from plan.pdf',
    })
  })

  it('stores the extracted text alongside a completed upload', async () => {
    uploadDocument.mockResolvedValue({
      status: 'processed 1 image(s) from plan.pdf',
      text_extraction: 'All footings are 300mm deep.',
    })
    const { setFiles } = renderUploadPage([])

    fireEvent.drop(screen.getByRole('button', { name: 'Upload a document' }), { dataTransfer: { files: [pdfFile()] } })
    const uploading = applyUpdater([], setFiles, 0)

    await vi.waitFor(() => expect(setFiles).toHaveBeenCalledTimes(2))
    const done = applyUpdater(uploading, setFiles, 1)

    expect(done[0].text).toBe('All footings are 300mm deep.')
  })

  it('marks a file as errored when the upload rejects', async () => {
    uploadDocument.mockRejectedValue(new Error('Uploaded file is empty.'))
    const { setFiles } = renderUploadPage([])

    fireEvent.drop(screen.getByRole('button', { name: 'Upload a document' }), { dataTransfer: { files: [pdfFile()] } })
    const uploading = applyUpdater([], setFiles, 0)

    await vi.waitFor(() => expect(setFiles).toHaveBeenCalledTimes(2))
    const errored = applyUpdater(uploading, setFiles, 1)

    expect(errored[0]).toMatchObject({ status: 'error', detail: 'Uploaded file is empty.' })
  })

  it('renders already-uploaded documents from the files prop', () => {
    renderUploadPage([
      { id: 1, name: 'plan.pdf', size: 204800, uploadedAt: new Date(), status: 'done', detail: 'processed' },
    ])

    // Scoped to the uploaded-files list: a "done" file's name also shows up
    // as an option in the Compliance Check section's document picker below,
    // so an unscoped query would match both.
    const list = document.querySelector('.list')
    expect(within(list).getByText('plan.pdf')).toBeInTheDocument()
    expect(within(list).getByText('processed')).toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument() // document count
  })

  it('removes a file from the list', () => {
    const { setFiles } = renderUploadPage([
      { id: 1, name: 'plan.pdf', size: 1024, uploadedAt: new Date(), status: 'done', detail: 'ok' },
    ])

    fireEvent.click(screen.getByRole('button', { name: 'Remove plan.pdf' }))

    expect(setFiles).toHaveBeenCalled()
    const next = applyUpdater(
      [{ id: 1, name: 'plan.pdf', size: 1024, uploadedAt: new Date(), status: 'done', detail: 'ok' }],
      setFiles,
    )
    expect(next).toHaveLength(0)
  })

  it('selecting an uploaded document fills the compliance-check text box with its extracted text', () => {
    renderUploadPage([
      {
        id: 1,
        name: 'plan.pdf',
        size: 1024,
        uploadedAt: new Date(),
        status: 'done',
        detail: 'processed',
        text: 'All footings are 300mm deep.',
      },
    ])

    fireEvent.change(screen.getByLabelText(/document \(optional\)/i), { target: { value: '1' } })

    expect(screen.getByLabelText('Document text')).toHaveValue('All footings are 300mm deep.')
  })

  it('does not clobber manually-typed text when the selected file extracted nothing', () => {
    renderUploadPage([
      {
        id: 1,
        name: 'scanned.pdf',
        size: 1024,
        uploadedAt: new Date(),
        status: 'done',
        detail: 'processed',
        text: '', // e.g. a scanned PDF with no text layer
      },
    ])

    fireEvent.change(screen.getByLabelText('Document text'), { target: { value: 'Manually typed text.' } })
    fireEvent.change(screen.getByLabelText(/document \(optional\)/i), { target: { value: '1' } })

    expect(screen.getByLabelText('Document text')).toHaveValue('Manually typed text.')
  })

  it('creates a folder via the "+ New folder" control', () => {
    const { setFolders } = renderUploadPage([])

    fireEvent.click(screen.getByRole('button', { name: '+ New folder' }))
    fireEvent.change(screen.getByLabelText('New folder name'), { target: { value: 'Site plans' } })
    fireEvent.submit(screen.getByLabelText('New folder name').closest('form'))

    expect(setFolders).toHaveBeenCalled()
    const next = applyUpdater([], setFolders)
    expect(next).toHaveLength(1)
    expect(next[0].name).toBe('Site plans')
  })

  it('moving a document to a folder updates its folderId', () => {
    const initial = [
      { id: 1, name: 'plan.pdf', size: 1024, uploadedAt: new Date(), status: 'done', detail: 'ok', folderId: null },
    ]
    const { setFiles } = renderUploadPage(initial, { folders: [{ id: 'f1', name: 'Site plans' }] })

    fireEvent.change(screen.getByLabelText('Move plan.pdf to a folder'), { target: { value: 'f1' } })

    expect(setFiles).toHaveBeenCalled()
    expect(applyUpdater(initial, setFiles)[0].folderId).toBe('f1')
  })

  it('filtering by a folder shows only that folder\'s documents', () => {
    renderUploadPage(
      [
        { id: 1, name: 'plan.pdf', size: 1024, uploadedAt: new Date(), status: 'done', detail: 'ok', folderId: 'f1' },
        { id: 2, name: 'report.pdf', size: 1024, uploadedAt: new Date(), status: 'done', detail: 'ok', folderId: null },
      ],
      { folders: [{ id: 'f1', name: 'Site plans' }] },
    )

    fireEvent.click(screen.getByRole('button', { name: 'Site plans' }))

    const list = document.querySelector('.list')
    expect(within(list).getByText('plan.pdf')).toBeInTheDocument()
    expect(within(list).queryByText('report.pdf')).not.toBeInTheDocument()
  })

  it('deleting a folder un-files its documents rather than deleting them', () => {
    const initialFiles = [
      { id: 1, name: 'plan.pdf', size: 1024, uploadedAt: new Date(), status: 'done', detail: 'ok', folderId: 'f1' },
    ]
    const initialFolders = [{ id: 'f1', name: 'Site plans' }]
    const { setFiles, setFolders } = renderUploadPage(initialFiles, { folders: initialFolders })

    fireEvent.click(screen.getByRole('button', { name: 'Site plans' })) // select it to reveal its actions
    fireEvent.click(screen.getByRole('button', { name: 'Delete Site plans' }))

    expect(applyUpdater(initialFolders, setFolders)).toHaveLength(0)
    expect(applyUpdater(initialFiles, setFiles)[0].folderId).toBeNull()
  })
})
