// Thin API client stub for talking to the FastAPI backend.
// Not used yet — wire this up once ChatPage/UploadPage are implemented.

// In local dev, Vite's dev-server proxy forwards /api to the backend (see
// vite.config.js), so a relative path works. In production the frontend and
// backend are two separate Render services with different domains, so
// VITE_API_BASE_URL (set at build time) must point at the deployed backend,
// e.g. "https://vecton-backend.onrender.com/api".
const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

// `attachment`, when given, is { name, text } for a document attached to the
// chat (extracted client-side via uploadDocument() below, see ChatPage.jsx).
// Only added to the request body when present, so the shape of an ordinary
// question is unchanged.
export async function askQuestion(question, jurisdiction, attachment) {
  const body = { question, jurisdiction }
  if (attachment?.text) {
    body.attachment_name = attachment.name ?? null
    body.attachment_text = attachment.text
  }

  const res = await fetch(`${BASE_URL}/chat/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
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

// `describeImages: false` skips the vision-model transcription pass (see
// api/routes/upload.py) -- the chat-attach flow only needs the document's
// text, so there's no reason to pay for image transcription on every attach.
export async function uploadDocument(file, { describeImages = true } = {}) {
  const formData = new FormData()
  formData.append('file', file)
  const query = describeImages ? '' : '?describe_images=false'
  const res = await fetch(`${BASE_URL}/upload/${query}`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    // Same reasoning as askQuestion() above: FastAPI's error body is
    // {"detail": "..."} (bad file type, corrupt file, vision provider not
    // configured, etc.) and fetch() won't throw on its own for this.
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail || `Upload failed (${res.status})`)
  }

  return res.json()
}
