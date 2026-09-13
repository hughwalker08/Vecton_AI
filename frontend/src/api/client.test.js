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
  it('POSTs to /api/chat/ with the question and jurisdiction as JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      fakeResponse({ body: { answer: 'Footings must comply with H1D4.', citations: [], abstained: false } })
    )
    vi.stubGlobal('fetch', fetchMock)

    await askQuestion('What are the footing requirements?', 'NSW')

    expect(fetchMock).toHaveBeenCalledWith('/api/chat/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: 'What are the footing requirements?', jurisdiction: 'NSW' }),
    })
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
})
