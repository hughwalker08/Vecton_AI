// Thin API client stub for talking to the FastAPI backend.
// Not used yet — wire this up once ChatPage/UploadPage are implemented.

const BASE_URL = '/api'

export async function askQuestion(question, jurisdiction) {
  const res = await fetch(`${BASE_URL}/chat/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question,
      jurisdiction,
    }),
  })

  if (!res.ok) {
    throw new Error(`Chat request failed: ${res.status}`)
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
