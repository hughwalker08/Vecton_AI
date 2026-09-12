// Thin API client stub for talking to the FastAPI backend.
// Not used yet — wire this up once ChatPage/UploadPage are implemented.

const BASE_URL = '/api'

export async function askQuestion(question) {
  const res = await fetch(`${BASE_URL}/chat/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })

  if (!res.ok) {
    // FastAPI's HTTPException body is {"detail": "..."} -- e.g. the 429
    // quota message from app/api/routes/chat.py. fetch() doesn't throw on
    // HTTP error statuses on its own, so without this the caller would
    // silently treat this error body as a normal ChatResponse.
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail || `Request failed (${res.status})`)
  }

  return res.json()
}

export async function uploadDocument(file) {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${BASE_URL}/upload/`, {
    method: 'POST',
    body: formData,
  })
  return res.json()
}
