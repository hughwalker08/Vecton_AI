import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import UploadPage from './UploadPage.jsx'

vi.mock('../api/client.js', () => ({
  uploadDocument: vi.fn(),
}))

import { uploadDocument } from '../api/client.js'

function renderUploadPage(files = []) {
  const setFiles = vi.fn()
  const utils = render(<UploadPage files={files} setFiles={setFiles} />)
  return { ...utils, setFiles }
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

    fireEvent.drop(screen.getByRole('button'), {
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

    fireEvent.drop(screen.getByRole('button'), { dataTransfer: { files: [pdfFile()] } })
    const uploading = applyUpdater([], setFiles, 0)

    await vi.waitFor(() => expect(setFiles).toHaveBeenCalledTimes(2))
    const done = applyUpdater(uploading, setFiles, 1)

    expect(done[0]).toMatchObject({
      status: 'done',
      detail: 'processed 1 image(s) from plan.pdf',
    })
  })

  it('marks a file as errored when the upload rejects', async () => {
    uploadDocument.mockRejectedValue(new Error('Uploaded file is empty.'))
    const { setFiles } = renderUploadPage([])

    fireEvent.drop(screen.getByRole('button'), { dataTransfer: { files: [pdfFile()] } })
    const uploading = applyUpdater([], setFiles, 0)

    await vi.waitFor(() => expect(setFiles).toHaveBeenCalledTimes(2))
    const errored = applyUpdater(uploading, setFiles, 1)

    expect(errored[0]).toMatchObject({ status: 'error', detail: 'Uploaded file is empty.' })
  })

  it('renders already-uploaded documents from the files prop', () => {
    renderUploadPage([
      { id: 1, name: 'plan.pdf', size: 204800, uploadedAt: new Date(), status: 'done', detail: 'processed' },
    ])

    expect(screen.getByText('plan.pdf')).toBeInTheDocument()
    expect(screen.getByText('processed')).toBeInTheDocument()
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
})
