import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ComplianceCheck } from './UploadPage.jsx'

// The compliance-check half of the upload page: paste or pick a document,
// run it against the NCC/ABCB clauses that apply, review findings, and flag
// one as wrongly classified. UploadPage.test.jsx covers the file-list half.
vi.mock('../api/client.js', () => ({
  analyseDocument: vi.fn(),
  flagFinding: vi.fn(),
  uploadDocument: vi.fn(),
}))

// FolderBrowser (not rendered here, but imported by UploadPage.jsx) pulls in
// the real Supabase client, which throws at import without env vars.
vi.mock('../lib/supabase.js', () => ({ supabase: { from: vi.fn() } }))

import { analyseDocument, flagFinding } from '../api/client.js'

const finding = (overrides = {}) => ({
  clause_id: 'H1D4',
  doc: 'NCC 2025 Volume Two',
  heading: 'Footings',
  status: 'addressed',
  explanation: 'Footing depth is specified.',
  evidence: 'Footings: 600mm deep.',
  source_url: null,
  text: 'Footings must be designed to support the loads.',
  ...overrides,
})

const report = (findings, overrides = {}) => ({
  query: 'footing requirements',
  findings,
  counts: { addressed: 0, missing: 0, contradicted: 0, needs_review: 0 },
  ...overrides,
})

const doc = (overrides = {}) => ({
  id: 1,
  name: 'plan.pdf',
  status: 'done',
  text: 'Footings: 600mm deep.',
  folderId: null,
  ...overrides,
})

function renderCheck(props = {}) {
  return render(<ComplianceCheck jurisdiction="NSW" files={[]} {...props} />)
}

function fillAndRun({ query = 'footing requirements', text = 'Footings: 600mm deep.' } = {}) {
  fireEvent.change(screen.getByLabelText('Document purpose?'), { target: { value: query } })
  fireEvent.change(screen.getByLabelText('Document text'), { target: { value: text } })
  fireEvent.click(screen.getByRole('button', { name: 'Run compliance check' }))
}

beforeEach(() => {
  analyseDocument.mockReset()
  flagFinding.mockReset()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('ComplianceCheck — running a check', () => {
  it('starts on an empty state with the run button disabled', () => {
    renderCheck()

    expect(screen.getByText('No compliance check yet')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run compliance check' })).toBeDisabled()
  })

  it('needs both a purpose and some document text before it can run', () => {
    renderCheck()
    const run = screen.getByRole('button', { name: 'Run compliance check' })

    fireEvent.change(screen.getByLabelText('Document purpose?'), { target: { value: 'footings' } })
    expect(run).toBeDisabled()

    fireEvent.change(screen.getByLabelText('Document text'), { target: { value: '   ' } })
    expect(run).toBeDisabled() // whitespace-only text doesn't count

    fireEvent.change(screen.getByLabelText('Document text'), { target: { value: 'Footings: 600mm' } })
    expect(run).toBeEnabled()
  })

  it('sends the trimmed text, trimmed purpose and the jurisdiction to the backend', async () => {
    analyseDocument.mockResolvedValue(report([finding()], { counts: { addressed: 1 } }))
    renderCheck({ jurisdiction: 'QLD' })

    fillAndRun({ query: '  footing requirements  ', text: '  Footings: 600mm deep.  ' })

    expect(await screen.findByText('Footing depth is specified.')).toBeInTheDocument()
    expect(analyseDocument).toHaveBeenCalledWith({
      document_text: 'Footings: 600mm deep.',
      query: 'footing requirements',
      jurisdiction: 'QLD',
    })
  })

  it('sends a null jurisdiction when none was chosen', async () => {
    analyseDocument.mockResolvedValue(report([finding()], { counts: { addressed: 1 } }))
    renderCheck({ jurisdiction: '' })

    fillAndRun()

    await screen.findByText('Footing depth is specified.')
    expect(analyseDocument.mock.calls[0][0].jurisdiction).toBeNull()
  })

  it('shows each finding with its status, clause, document, heading, explanation and evidence', async () => {
    analyseDocument.mockResolvedValue(report([finding()], { counts: { addressed: 1 } }))
    renderCheck()

    fillAndRun()

    expect(await screen.findByText('Footing depth is specified.')).toBeInTheDocument()
    const card = screen.getByText('Footing depth is specified.').closest('.cc-finding')
    expect(within(card).getByText('Addressed')).toBeInTheDocument()
    expect(within(card).getByText('H1D4')).toBeInTheDocument()
    expect(within(card).getByText(/NCC 2025 Volume Two · Footings/)).toBeInTheDocument()
    expect(within(card).getByText('Footings: 600mm deep.')).toBeInTheDocument()
    expect(screen.getByText('Findings')).toBeInTheDocument() // no document picked
  })

  it('omits the heading suffix and evidence quote when a finding has neither', async () => {
    analyseDocument.mockResolvedValue(
      report([finding({ heading: null, evidence: null, status: 'missing' })], { counts: { missing: 1 } }),
    )
    renderCheck()

    fillAndRun()

    const card = (await screen.findByText('Footing depth is specified.')).closest('.cc-finding')
    expect(within(card).queryByText(/·/)).not.toBeInTheDocument()
    expect(card.querySelector('blockquote')).toBeNull()
  })

  it('says so when no applicable clauses are found', async () => {
    analyseDocument.mockResolvedValue(report([]))
    renderCheck()

    fillAndRun()

    expect(await screen.findByText('No applicable clauses found')).toBeInTheDocument()
    expect(screen.queryByText('No compliance check yet')).not.toBeInTheDocument()
  })

  it('shows the backend error message when the check fails', async () => {
    analyseDocument.mockRejectedValue(new Error('Gemini quota exceeded. Try again in about 30s.'))
    renderCheck()

    fillAndRun()

    expect(await screen.findByRole('alert')).toHaveTextContent('Gemini quota exceeded. Try again in about 30s.')
    expect(screen.queryByText('No compliance check yet')).not.toBeInTheDocument()
  })

  it('falls back to a generic message when the error carries no message', async () => {
    analyseDocument.mockRejectedValue(new Error(''))
    renderCheck()

    fillAndRun()

    expect(await screen.findByRole('alert')).toHaveTextContent('The compliance check failed.')
  })

  it('shows a progress message while checking, and cycles through the stages', async () => {
    vi.useFakeTimers()
    analyseDocument.mockReturnValue(new Promise(() => {})) // never resolves
    renderCheck()

    fillAndRun()

    const status = () => screen.getByRole('status')
    expect(status()).toHaveTextContent('Retrieving relevant clauses…')
    expect(screen.getByRole('button', { name: 'Run compliance check' })).toBeDisabled()

    act(() => vi.advanceTimersByTime(2500))
    expect(status()).toHaveTextContent('Classifying against requirements…')
    act(() => vi.advanceTimersByTime(2500))
    expect(status()).toHaveTextContent('Writing up findings…')
    act(() => vi.advanceTimersByTime(2500))
    expect(status()).toHaveTextContent('Retrieving relevant clauses…') // wraps round
  })
})

describe('ComplianceCheck — reviewing findings', () => {
  const mixed = report(
    [
      finding({ clause_id: 'A1', status: 'addressed', explanation: 'addressed one' }),
      finding({ clause_id: 'B2', status: 'missing', explanation: 'missing one' }),
      finding({ clause_id: 'C3', status: 'missing', explanation: 'missing two' }),
    ],
    { counts: { addressed: 1, missing: 2 } },
  )

  async function renderWithResults() {
    analyseDocument.mockResolvedValue(mixed)
    renderCheck()
    fillAndRun()
    await screen.findByText('addressed one')
  }

  // The count buttons share their label text with the finding badges, so
  // address them by their status class rather than by text.
  const countButton = (key) => document.querySelector(`.cc-count.cc-${key}`)

  it('shows a count for every status, defaulting absent ones to zero', async () => {
    await renderWithResults()

    const counts = Object.fromEntries(
      ['addressed', 'missing', 'contradicted', 'needs_review'].map((key) => [
        key,
        countButton(key).querySelector('b').textContent,
      ]),
    )
    expect(counts).toEqual({ addressed: '1', missing: '2', contradicted: '0', needs_review: '0' })
  })

  it('filters the list to one status when its count is clicked, and back again', async () => {
    await renderWithResults()
    const missingFilter = countButton('missing')

    fireEvent.click(missingFilter)

    expect(missingFilter).toHaveAttribute('aria-pressed', 'true')
    expect(screen.queryByText('addressed one')).not.toBeInTheDocument()
    expect(screen.getByText('missing one')).toBeInTheDocument()
    expect(screen.getByText('missing two')).toBeInTheDocument()

    fireEvent.click(missingFilter)

    expect(missingFilter).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByText('addressed one')).toBeInTheDocument()
  })

  it('Clear wipes the form and the results', async () => {
    await renderWithResults()

    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))

    expect(screen.getByLabelText('Document purpose?')).toHaveValue('')
    expect(screen.getByLabelText('Document text')).toHaveValue('')
    expect(screen.getByText('No compliance check yet')).toBeInTheDocument()
    expect(screen.queryByText('addressed one')).not.toBeInTheDocument()
  })

  it('opens the cited clause in the source panel via "View clause", only when there is a source_url', async () => {
    analyseDocument.mockResolvedValue(
      report(
        [
          finding({ clause_id: 'WITH', source_url: 'https://ncc.abcb.gov.au/H1D4', explanation: 'has a link' }),
          finding({ clause_id: 'WITHOUT', source_url: null, explanation: 'has none' }),
        ],
        { counts: { addressed: 2 } },
      ),
    )
    renderCheck()
    fillAndRun()
    await screen.findByText('has a link')

    expect(screen.getAllByRole('button', { name: 'View clause' })).toHaveLength(1)
    const panel = screen.getByLabelText('Cited source')
    expect(panel).toHaveAttribute('aria-hidden', 'true')

    fireEvent.click(screen.getByRole('button', { name: 'View clause' }))

    expect(panel).toHaveAttribute('aria-hidden', 'false')
    expect(within(panel).getByText('Footings must be designed to support the loads.')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Close source' }))
    expect(panel).toHaveAttribute('aria-hidden', 'true')
  })
})

describe('ComplianceCheck — picking an uploaded document', () => {
  it('is disabled with a hint when nothing has been uploaded', () => {
    renderCheck({ files: [] })

    const select = screen.getByLabelText('Document (optional)')
    expect(select).toBeDisabled()
    expect(within(select).getByText('No uploaded documents yet')).toBeInTheDocument()
  })

  it('only offers documents that finished uploading', () => {
    renderCheck({
      files: [doc({ id: 1, name: 'done.pdf' }), doc({ id: 2, name: 'busy.pdf', status: 'uploading' })],
    })

    const select = screen.getByLabelText('Document (optional)')
    expect(within(select).getByText('done.pdf')).toBeInTheDocument()
    expect(within(select).queryByText('busy.pdf')).not.toBeInTheDocument()
  })

  it('groups documents by folder, with unfiled ones last and empty folders hidden', () => {
    renderCheck({
      folders: [
        { id: 'f1', name: 'Structural' },
        { id: 'f2', name: 'Empty folder' },
      ],
      files: [
        doc({ id: 1, name: 'loose.pdf', folderId: null }),
        doc({ id: 2, name: 'footings.pdf', folderId: 'f1' }),
      ],
    })

    const groups = [...screen.getByLabelText('Document (optional)').querySelectorAll('optgroup')]

    expect(groups.map((g) => g.label)).toEqual(['Structural', 'Unfiled'])
    expect(within(groups[0]).getByText('footings.pdf')).toBeInTheDocument()
    expect(within(groups[1]).getByText('loose.pdf')).toBeInTheDocument()
  })

  it('fills the text box with the document\'s text, and names it in the results', async () => {
    analyseDocument.mockResolvedValue(report([finding()], { counts: { addressed: 1 } }))
    renderCheck({ files: [doc({ id: 7, name: 'site-plan.pdf', text: 'All footings are 300mm.' })] })

    fireEvent.change(screen.getByLabelText('Document (optional)'), { target: { value: '7' } })

    expect(screen.getByLabelText('Document text')).toHaveValue('All footings are 300mm.')

    fireEvent.change(screen.getByLabelText('Document purpose?'), { target: { value: 'footings' } })
    fireEvent.click(screen.getByRole('button', { name: 'Run compliance check' }))

    expect(await screen.findByText('site-plan.pdf')).toBeInTheDocument()
  })

  it('falls back to "none selected" when the chosen document is removed', () => {
    const files = [doc({ id: 7, name: 'site-plan.pdf' })]
    const { rerender } = renderCheck({ files })
    fireEvent.change(screen.getByLabelText('Document (optional)'), { target: { value: '7' } })
    expect(screen.getByLabelText('Document (optional)')).toHaveValue('7')

    rerender(<ComplianceCheck jurisdiction="NSW" files={[]} />)

    expect(screen.getByLabelText('Document (optional)')).toHaveValue('')
  })
})

describe('ComplianceCheck — flagging a finding as wrong', () => {
  async function renderOneFinding() {
    analyseDocument.mockResolvedValue(report([finding({ status: 'missing' })], { counts: { missing: 1 } }))
    renderCheck()
    fillAndRun()
    await screen.findByText('Footing depth is specified.')
  }

  const openForm = () => fireEvent.click(screen.getByRole('button', { name: 'Report a disagreement with H1D4' }))

  it('opens and closes the feedback form from the Disagree button', async () => {
    await renderOneFinding()
    const button = screen.getByRole('button', { name: 'Report a disagreement with H1D4' })
    expect(button).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByLabelText('Corrected status')).toBeInTheDocument()

    fireEvent.click(button)
    expect(screen.queryByLabelText('Corrected status')).not.toBeInTheDocument()
  })

  it("offers every status except the one the finding already has", async () => {
    await renderOneFinding()

    openForm()

    const options = [...screen.getByLabelText('Corrected status').querySelectorAll('option')].map((o) => o.textContent)
    expect(options).toEqual(['Not sure', 'Addressed', 'Contradicted', 'Needs review'])
  })

  it('sends the correction with the original status and the query, then thanks the user', async () => {
    flagFinding.mockResolvedValue({})
    await renderOneFinding()
    openForm()

    fireEvent.change(screen.getByLabelText('Corrected status'), { target: { value: 'addressed' } })
    fireEvent.change(screen.getByLabelText(/^Comment/), { target: { value: '  It does mention it.  ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('Thanks. Your correction was sent.')).toBeInTheDocument()
    expect(flagFinding).toHaveBeenCalledWith({
      clause_id: 'H1D4',
      doc: 'NCC 2025 Volume Two',
      query: 'footing requirements',
      reported_status: 'missing',
      corrected_status: 'addressed',
      comment: 'It does mention it.',
    })
    // One report per finding: the button and form are gone afterwards.
    expect(screen.queryByRole('button', { name: /Report a disagreement/ })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Corrected status')).not.toBeInTheDocument()
  })

  it('sends nulls for "Not sure" and a blank comment', async () => {
    flagFinding.mockResolvedValue({})
    await renderOneFinding()
    openForm()

    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    await screen.findByText('Thanks. Your correction was sent.')
    expect(flagFinding.mock.calls[0][0]).toMatchObject({ corrected_status: null, comment: null })
  })

  it('shows the error and keeps the form open when sending fails', async () => {
    flagFinding.mockRejectedValue(new Error('Could not send feedback (500)'))
    await renderOneFinding()
    openForm()

    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('Could not send feedback (500)')).toBeInTheDocument()
    expect(screen.getByLabelText('Corrected status')).toBeInTheDocument()
    expect(screen.queryByText('Thanks. Your correction was sent.')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled() // can retry
  })

  it('falls back to a generic message when the error has none', async () => {
    flagFinding.mockRejectedValue(new Error(''))
    await renderOneFinding()
    openForm()

    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('Could not send feedback.')).toBeInTheDocument()
  })

  it('disables Send while the request is in flight', async () => {
    flagFinding.mockReturnValue(new Promise(() => {}))
    await renderOneFinding()
    openForm()

    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByRole('button', { name: 'Sending…' })).toBeDisabled()
  })
})
