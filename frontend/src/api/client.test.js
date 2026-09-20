import { afterEach, describe, expect, it, vi } from 'vitest'
import { askQuestion, uploadDocument } from './client.js'

function fakeResponse({ ok = true, status = 200, body = {} } = {}) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('askQuestion', () => {
  it('POSTs to /api/chat/ with the question, jurisdiction, and history as JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      fakeResponse({ body: { answer: 'Footings must comply with H1D4.', citations: [], abstained: false } })
    )
    vi.stubGlobal('fetch', fetchMock)

    await askQuestion('What are the footing requirements?', 'NSW')

    expect(fetchMock).toHaveBeenCalledWith('/api/chat/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question: 'What are the footing requirements?',
        jurisdiction: 'NSW',
        history: [],
      }),
    })
  })

  it('sends the given history verbatim when under the message cap', async () => {
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse({ body: { answer: 'ok', citations: [] } }))
    vi.stubGlobal('fetch', fetchMock)
    const history = [
      { role: 'user', text: 'What ceiling height do we need in bedrooms?' },
      { role: 'assistant', text: 'Minimum 2.4m per H1D4.' },
    ]

    await askQuestion('What about NSW?', 'NSW', { history })

    expect(JSON.parse(fetchMock.mock.calls[0][1].body).history).toEqual(history)
  })

  it('trims history to the most recent messages before sending', async () => {
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse({ body: { answer: 'ok', citations: [] } }))
    vi.stubGlobal('fetch', fetchMock)
    const history = Array.from({ length: 10 }, (_, i) => ({ role: 'user', text: `turn ${i}` }))

    await askQuestion('Q', 'NSW', { history })

    const sentHistory = JSON.parse(fetchMock.mock.calls[0][1].body).history
    expect(sentHistory).toHaveLength(6)
    expect(sentHistory[0].text).toBe('turn 4') // the 6 most recent, oldest first
    expect(sentHistory[5].text).toBe('turn 9')
  })

  it('resolves with the parsed JSON response on success', async () => {
    const body = { answer: 'An answer.', citations: [{ clause_id: 'H1D4' }], abstained: false }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(fakeResponse({ body })))

    await expect(askQuestion('Q', 'NSW')).resolves.toEqual(body)
  })

  it('throws the backend detail message when the response is not ok', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        fakeResponse({ ok: false, status: 429, body: { detail: 'Quota exceeded. Try again in about 30s.' } })
      )
    )

    await expect(askQuestion('Q', 'NSW')).rejects.toThrow('Quota exceeded. Try again in about 30s.')
  })

  it('falls back to a generic message when the error body has no detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: () => Promise.reject(new Error('not json')),
      })
    )

    await expect(askQuestion('Q', 'NSW')).rejects.toThrow('Request failed (500)')
  })

  it('includes the attachment fields when an attachment is given', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      fakeResponse({ body: { answer: 'An answer.', citations: [], abstained: false } })
    )
    vi.stubGlobal('fetch', fetchMock)

    await askQuestion('Does my plan comply?', 'NSW', {
      attachment: { name: 'site-plan.pdf', text: 'All footings are 300mm.' },
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/chat/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question: 'Does my plan comply?',
        jurisdiction: 'NSW',
        history: [],
        attachment_name: 'site-plan.pdf',
        attachment_text: 'All footings are 300mm.',
      }),
    })
  })

  it('omits attachment fields entirely when no attachment is given', async () => {
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse({ body: { answer: 'ok', citations: [], abstained: false } }))
    vi.stubGlobal('fetch', fetchMock)

    await askQuestion('Q', 'NSW')

    expect(fetchMock).toHaveBeenCalledWith('/api/chat/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: 'Q', jurisdiction: 'NSW', history: [] }),
    })
  })
})

describe('uploadDocument', () => {
  it('POSTs the file as multipart form data to /api/upload/', async () => {
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse({ body: { status: 'received' } }))
    vi.stubGlobal('fetch', fetchMock)
    const file = new File(['plan contents'], 'plan.pdf', { type: 'application/pdf' })

    await uploadDocument(file)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/upload/')
    expect(options.method).toBe('POST')
    expect(options.body).toBeInstanceOf(FormData)
    expect(options.body.get('file')).toBe(file)
  })

  it('resolves with the parsed JSON response', async () => {
    const body = { status: 'received', images_found: 0 }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(fakeResponse({ body })))

    await expect(uploadDocument(new File(['x'], 'a.pdf'))).resolves.toEqual(body)
  })

  it('throws the backend detail message when the response is not ok', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(fakeResponse({ ok: false, status: 400, body: { detail: 'Uploaded file is empty.' } }))
    )

    await expect(uploadDocument(new File([], 'empty.pdf'))).rejects.toThrow('Uploaded file is empty.')
  })

  it('falls back to a generic message when the error body has no detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 503, json: () => Promise.reject(new Error('not json')) })
    )

    await expect(uploadDocument(new File(['x'], 'a.pdf'))).rejects.toThrow('Upload failed (503)')
  })

  it('adds describe_images=false to the URL when image transcription is disabled', async () => {
    const fetchMock = vi.fn().mockResolvedValue(fakeResponse({ body: { status: 'received' } }))
    vi.stubGlobal('fetch', fetchMock)

    await uploadDocument(new File(['x'], 'a.pdf'), { describeImages: false })

    expect(fetchMock.mock.calls[0][0]).toBe('/api/upload/?describe_images=false')
  })
})
