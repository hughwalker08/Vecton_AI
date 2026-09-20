import { useRef, useState } from 'react'
import { uploadDocument } from '../api/client.js'

// accept only filters the OS file picker -- it doesn't stop a drag-drop or a
// "Files of type: All" pick -- so the extension is checked again in code.
const ATTACHMENT_EXTENSIONS = ['.pdf', '.docx']

function hasSupportedExtension(file) {
  const name = file.name.toLowerCase()
  return ATTACHMENT_EXTENSIONS.some((ext) => name.endsWith(ext))
}

// Shared between HomePage (attach while starting a new chat) and ChatPage
// (attach as a follow-up in an existing one) so the extraction/validation
// behaviour can't drift between the two entry points.
export function useAttachment() {
  const [attachment, setAttachment] = useState(null)
  const inputRef = useRef(null)

  async function handleAttachmentChange(event) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return

    if (!hasSupportedExtension(file)) {
      setAttachment({
        name: file.name,
        status: 'error',
        detail: 'Only PDF or DOCX files can be attached.',
      })
      return
    }

    setAttachment({ name: file.name, status: 'uploading', detail: 'Reading document…' })

    try {
      const response = await uploadDocument(file, { describeImages: false })
      setAttachment({
        name: file.name,
        text: response.text_extraction,
        status: 'ready',
        detail: 'Attached',
      })
    } catch (error) {
      setAttachment({
        name: file.name,
        status: 'error',
        detail: error.message || 'Could not read this file.',
      })
    }
  }

  function removeAttachment() {
    setAttachment(null)
  }

  return { attachment, setAttachment, inputRef, handleAttachmentChange, removeAttachment }
}
