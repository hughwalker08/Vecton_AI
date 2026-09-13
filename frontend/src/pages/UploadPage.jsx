import { useRef, useState } from 'react'
import { uploadDocument } from '../api/client.js'
import './UploadPage.css'

const ACCEPTED_TYPES = '.pdf,.docx'

function formatBytes(bytes) {
  if (!bytes) return '0 KB'
  const units = ['B', 'KB', 'MB', 'GB']
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = bytes / 1024 ** exponent
  return `${exponent === 0 ? value : value.toFixed(1)} ${units[exponent]}`
}

function formatDate(date) {
  return date.toLocaleDateString('en-AU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

let nextId = 1

export default function UploadPage() {
  const [files, setFiles] = useState([])
  const [isDragging, setIsDragging] = useState(false)
  const inputRef = useRef(null)

  function addFiles(fileList) {
    const incoming = Array.from(fileList || [])
    if (incoming.length === 0) return

    const records = incoming.map((file) => ({
      id: nextId++,
      file,
      name: file.name,
      size: file.size,
      uploadedAt: new Date(),
      status: 'uploading',
      detail: 'Uploading…',
    }))

    setFiles((current) => [...records, ...current])
    records.forEach(processUpload)
  }

  async function processUpload(record) {
    try {
      const response = await uploadDocument(record.file)

      setFiles((current) =>
        current.map((f) =>
          f.id === record.id ? { ...f, status: 'done', detail: response.status } : f,
        ),
      )
    } catch (error) {
      setFiles((current) =>
        current.map((f) =>
          f.id === record.id
            ? { ...f, status: 'error', detail: error.message || 'Upload failed.' }
            : f,
        ),
      )
    }
  }

  function handleInputChange(event) {
    addFiles(event.target.files)
    event.target.value = ''
  }

  function handleDrop(event) {
    event.preventDefault()
    setIsDragging(false)
    addFiles(event.dataTransfer.files)
  }

  function removeFile(id) {
    setFiles((current) => current.filter((f) => f.id !== id))
  }

  return (
    <main className="upload-page">
      <div className="upload-pane">
        <div className="upload-head">
          <h1>Project files</h1>
          <p className="sub">
            Upload plans, certificates or reports — drawings inside them get read
            automatically.
          </p>
          <div className="counts">
            <div className="count">
              <b>{files.length}</b>
              <span>document{files.length === 1 ? '' : 's'}</span>
            </div>
          </div>
        </div>

        <div
          className={`dropzone ${isDragging ? 'over' : ''}`}
          onDragOver={(event) => {
            event.preventDefault()
            setIsDragging(true)
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              inputRef.current?.click()
            }
          }}
          role="button"
          tabIndex={0}
        >
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
            <path
              d="M12 19V6m0 0-5 5m5-5 5 5"
              stroke="currentColor"
              strokeWidth="1.7"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <path d="M4 19h16" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
          </svg>
          <p>
            Drag files here, or <span className="link">browse</span>
          </p>
          <span className="hint">PDF or DOCX</span>
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPTED_TYPES}
            multiple
            hidden
            onChange={handleInputChange}
          />
        </div>

        <div className="list">
          {files.length === 0 ? (
            <div className="empty">
              <p>No documents uploaded yet</p>
              <span>Files you upload in this session will show up here.</span>
            </div>
          ) : (
            files.map((record) => (
              <div className="item" key={record.id}>
                <svg className="ico" width="15" height="15" viewBox="0 0 24 24" fill="none">
                  <path
                    d="M6.5 3.5h7L18 8v12.5H6.5V3.5Z"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinejoin="round"
                  />
                  <path d="M13.2 3.6V8H18" stroke="currentColor" strokeWidth="1.6" />
                </svg>

                <span className="body">
                  <span className="nm">{record.name}</span>
                  <span className="mt">
                    {formatBytes(record.size)}
                    {' · '}
                    <span className={`status status-${record.status}`}>
                      {record.status === 'uploading' && <span className="spin" />}
                      {record.detail}
                    </span>
                  </span>
                </span>

                <span className="when">{formatDate(record.uploadedAt)}</span>

                <button
                  type="button"
                  className="remove"
                  aria-label={`Remove ${record.name}`}
                  onClick={() => removeFile(record.id)}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                    <path
                      d="M6 6l12 12M18 6 6 18"
                      stroke="currentColor"
                      strokeWidth="1.7"
                      strokeLinecap="round"
                    />
                  </svg>
                </button>
              </div>
            ))
          )}
        </div>
      </div>
    </main>
  )
}
