import { useEffect, useRef, useState } from 'react'
import { analyseDocument, flagFinding, uploadDocument } from '../api/client.js'
import { supabase } from '../lib/supabase.js'
import './UploadPage.css'
import SourcePanel from '../components/SourcePanel.jsx'

const ACCEPTED_TYPES = '.pdf,.docx'

// Raw API values (note the underscore in needs_review) -> display labels.
const STATUSES = [
  { key: 'addressed', label: 'Addressed' },
  { key: 'missing', label: 'Missing' },
  { key: 'contradicted', label: 'Contradicted' },
  { key: 'needs_review', label: 'Needs review' },
]
const STATUS_LABEL = Object.fromEntries(STATUSES.map((s) => [s.key, s.label]))

const LOADING_MESSAGES = [
  'Retrieving relevant clauses…',
  'Classifying against requirements…',
  'Writing up findings…',
]

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

function FindingCard({ finding, query, onViewSource }) {
  const [flagOpen, setFlagOpen] = useState(false)
  const [corrected, setCorrected] = useState('')
  const [comment, setComment] = useState('')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [flagError, setFlagError] = useState('')

  async function submitFlag() {
    setSending(true)
    setFlagError('')
    try {
      await flagFinding({
        clause_id: finding.clause_id,
        doc: finding.doc,
        query,
        reported_status: finding.status,
        corrected_status: corrected || null,
        comment: comment.trim() || null,
      })
      setSent(true)
      setFlagOpen(false)
    } catch (error) {
      setFlagError(error.message || 'Could not send feedback.')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className={`item cc-finding cc-${finding.status}`}>
      <div className="body">
        <span className="nm cc-nm">
          <span className="cc-badge">{STATUS_LABEL[finding.status]}</span>
          {finding.clause_id}
          <span className="cc-doc">
            {finding.doc}
            {finding.heading ? ` · ${finding.heading}` : ''}
          </span>
        </span>

        <p className="cc-explain">{finding.explanation}</p>
        {finding.evidence && <blockquote className="cc-quote">{finding.evidence}</blockquote>}

        {finding.source_url && (
          <button type="button" className="cc-link" onClick={() => onViewSource(finding)}>
            View clause
          </button>
        )}

        {sent && <p className="cc-sent">Thanks. Your correction was sent.</p>}

        {flagOpen && (
          <div className="cc-flagform">
            <div className="cc-field">
              <label htmlFor={`cc-corr-${finding.clause_id}`}>Corrected status</label>
              <select
                id={`cc-corr-${finding.clause_id}`}
                value={corrected}
                onChange={(e) => setCorrected(e.target.value)}
              >
                <option value="">Not sure</option>
                {STATUSES.filter((s) => s.key !== finding.status).map((s) => (
                  <option key={s.key} value={s.key}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="cc-field">
              <label htmlFor={`cc-com-${finding.clause_id}`}>
                Comment <i>(optional)</i>
              </label>
              <input
                id={`cc-com-${finding.clause_id}`}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="What did we get wrong?"
              />
            </div>
            <button type="button" className="cc-send" disabled={sending} onClick={submitFlag}>
              {sending ? 'Sending…' : 'Send'}
            </button>
            {flagError && <p className="cc-error cc-flagform-error">{flagError}</p>}
          </div>
        )}
      </div>

      {!sent && (
        <button
          type="button"
          className="cc-flag"
          aria-expanded={flagOpen}
          aria-label={`Report a disagreement with ${finding.clause_id}`}
          onClick={() => setFlagOpen((open) => !open)}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
            <path
              d="M4 21V4m0 0h13l-2 4 2 4H4"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          Disagree
        </button>
      )}
    </div>
  )
}

// `jurisdiction` is the code chosen during onboarding (ACT, NSW, ... or empty).
function ComplianceCheck({ jurisdiction, files, folders = [] }) {
  const [query, setQuery] = useState('')
  const [documentText, setDocumentText] = useState('')

  const [loading, setLoading] = useState(false)
  const [messageIndex, setMessageIndex] = useState(0)
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState(null)

  const [selectedFileId, setSelectedFileId] = useState('')
  const [reportFile, setReportFile] = useState('')
  const [openSource, setOpenSource] = useState(null)
  const canSubmit = query.trim() && documentText.trim() && !loading

  const uploadedFiles = files.filter((f) => f.status === 'done')
  // If the chosen file was removed from the list, fall back to "none selected".
  const fileValue = uploadedFiles.some((f) => String(f.id) === selectedFileId)
    ? selectedFileId
    : ''

  // Grouped into <optgroup>s by folder, unfiled documents last -- a group
  // with nothing in it isn't shown at all.
  const fileGroups = [
    ...folders.map((folder) => ({
      key: folder.id,
      label: folder.name,
      files: uploadedFiles.filter((f) => f.folderId === folder.id),
    })),
    { key: 'unfiled', label: 'Unfiled', files: uploadedFiles.filter((f) => !f.folderId) },
  ].filter((group) => group.files.length > 0)

  // Cycle the status text while a request is in flight.
  useEffect(() => {
    if (!loading) return undefined
    setMessageIndex(0)
    const timer = setInterval(
      () => setMessageIndex((i) => (i + 1) % LOADING_MESSAGES.length),
      2500,
    )
    return () => clearInterval(timer)
  }, [loading])

  async function runCheck() {
    if (!canSubmit) return
    setLoading(true)
    setError('')
    setReport(null)
    setFilter(null)
    setReportFile(uploadedFiles.find((f) => String(f.id) === fileValue)?.name ?? '')
    try {
      const result = await analyseDocument({
        document_text: documentText.trim(),
        query: query.trim(),
        jurisdiction: jurisdiction || null,
      })
      setReport(result)
    } catch (err) {
      setError(err.message || 'The compliance check failed.')
    } finally {
      setLoading(false)
    }
  }

  function clearAll() {
    setQuery('')
    setDocumentText('')
    setSelectedFileId('')
    setReportFile('')
    setReport(null)
    setError('')
    setFilter(null)
    setOpenSource(null)
  }
  
  function viewSource(finding) {
    setOpenSource(finding)
  }

  const findings = report?.findings ?? []
  const visible = filter ? findings.filter((f) => f.status === filter) : findings

  return (
    <section className="cc" aria-labelledby="cc-title">
      <div className="cc-head">
        <h2 id="cc-title">Compliance Check</h2>
        <p className="sub">
          Get a construction-compliance overview of your document with specific clauses from NCC / ABCB.
        </p>
      </div>

      <form
        className="cc-form"
        onSubmit={(e) => {
          e.preventDefault()
          runCheck()
        }}
      >

        <div className="cc-field cc-textwrap">
          <label htmlFor="cc-file">
            Document <i>(optional)</i>
          </label>
          <select
            id="cc-file"
            value={fileValue}
            onChange={(e) => {
              const id = e.target.value
              setSelectedFileId(id)
              const file = uploadedFiles.find((f) => String(f.id) === id)
              // Only overwrite the textarea when the file actually extracted
              // something -- a scanned PDF with no text layer, for instance,
              // extracts to '' and should leave whatever's already typed alone.
              if (file?.text) {
                setDocumentText(file.text)
              }
            }}
            disabled={uploadedFiles.length === 0}
          >
            <option value="">
              {uploadedFiles.length === 0 ? 'No uploaded documents yet' : 'Select a document'}
            </option>
            {fileGroups.map((group) => (
              <optgroup key={group.key} label={group.label}>
                {group.files.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          <span className="cc-hint">
            Selecting a document fills in its extracted text below -- you can still edit it before
            running the check.
          </span>
        </div>

        <div className="cc-field cc-textwrap">
          <label htmlFor="cc-query">Document purpose?</label>
          <input
            id="cc-query"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. Class 1a dwelling stormwater drainage and smoke alarm requirements"
          />
          <span className="cc-hint">
            Helps locate clauses relevant to the document.
          </span>
        </div>

        <div className="cc-field cc-textwrap">
          <label htmlFor="cc-text">Document text</label>
          <textarea
            id="cc-text"
            value={documentText}
            onChange={(e) => setDocumentText(e.target.value)}
            placeholder="Select a document above, or paste in the text content of your document"
          />
        </div>

        <div className="cc-bar">
          <button type="submit" className="cc-send" disabled={!canSubmit}>
            Run compliance check
          </button>
          {loading && (
            <span className="cc-status" role="status">
              <span className="spin" />
              {LOADING_MESSAGES[messageIndex]}
            </span>
          )}
        </div>
      </form>

      {error && (
        <p className="cc-error" role="alert">
          {error}
        </p>
      )}

      {!report && !loading && !error && (
        <div className="empty">
          <p>No compliance check yet</p>
          <span>Add your document text and run a check. Findings will show up here.</span>
        </div>
      )}

      {report && findings.length === 0 && (
        <div className="empty">
          <p>No applicable clauses found</p>
          <span>Try describing the document differently.</span>
        </div>
      )}

      {report && findings.length > 0 && (
        <>
          {report && (
            <div className="cc-resultbar">
              <p className="cc-forfile">
                {reportFile ? (
                  <>
                    Findings for <b>{reportFile}</b>
                  </>
                ) : (
                  'Findings'
                )}
              </p>
              <button type="button" className="cc-clear" onClick={clearAll}>
                Clear
              </button>
            </div>
          )}
          <div className="cc-counts">
            {STATUSES.map((s) => (
              <button
                key={s.key}
                type="button"
                className={`cc-count cc-${s.key}`}
                aria-pressed={filter === s.key}
                onClick={() => setFilter(filter === s.key ? null : s.key)}
              >
                <b>{report.counts[s.key] ?? 0}</b>
                <span>{s.label}</span>
              </button>
            ))}
          </div>

          <div className="cc-list">
            {visible.map((finding, i) => (
              <FindingCard
                key={`${finding.clause_id}-${i}`}
                finding={finding}
                query={report.query}
                onViewSource={viewSource}
              />
            ))}
          </div>
        </>
      )}
      <SourcePanel citation={openSource} onClose={() => setOpenSource(null)} />
    </section>
  )
}

export default function UploadPage({ files, setFiles, folders = [], setFolders, jurisdiction, userId }) {
  const [isDragging, setIsDragging] = useState(false)
  // '' = All, 'unfiled' = no folder, else a folders.id.
  const [activeFolderId, setActiveFolderId] = useState('')
  const [isAddingFolder, setIsAddingFolder] = useState(false)
  const [newFolderName, setNewFolderName] = useState('')
  const [renamingFolderId, setRenamingFolderId] = useState(null)
  const [renameValue, setRenameValue] = useState('')
  const inputRef = useRef(null)

  function logIfError({ error }) {
    if (error) console.error(error)
  }

  function addFiles(fileList) {
    const incoming = Array.from(fileList || [])
    if (incoming.length === 0) return

    // A new file lands in the folder currently being viewed (Unfiled/All both
    // mean "no folder" here -- there's no meaningful folder to assign from
    // the All view either).
    const folderId = activeFolderId && activeFolderId !== 'unfiled' ? activeFolderId : null

    const records = incoming.map((file) => ({
      id: crypto.randomUUID(),
      file,
      name: file.name,
      size: file.size,
      uploadedAt: new Date(),
      status: 'uploading',
      detail: 'Uploading…',
      folderId,
    }))

    setFiles((current) => [...records, ...current])
    records.forEach((record) => {
      supabase
        .from('documents')
        .insert({
          id: record.id,
          user_id: userId,
          folder_id: record.folderId,
          name: record.name,
          size: record.size,
          status: 'uploading',
          detail: record.detail,
        })
        .then(logIfError)
      processUpload(record)
    })
  }

  async function processUpload(record) {
    try {
      const response = await uploadDocument(record.file)
      const update = { status: 'done', detail: response.status, text: response.text_extraction }

      setFiles((current) => current.map((f) => (f.id === record.id ? { ...f, ...update } : f)))
      supabase.from('documents').update(update).eq('id', record.id).then(logIfError)
    } catch (error) {
      const update = { status: 'error', detail: error.message || 'Upload failed.' }

      setFiles((current) => current.map((f) => (f.id === record.id ? { ...f, ...update } : f)))
      supabase.from('documents').update(update).eq('id', record.id).then(logIfError)
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
    supabase.from('documents').delete().eq('id', id).then(logIfError)
  }

  function moveFile(id, folderId) {
    setFiles((current) => current.map((f) => (f.id === id ? { ...f, folderId: folderId || null } : f)))
    supabase
      .from('documents')
      .update({ folder_id: folderId || null })
      .eq('id', id)
      .then(logIfError)
  }

  function addFolder() {
    const name = newFolderName.trim()
    if (!name) return
    const id = crypto.randomUUID()

    setFolders((current) => [...current, { id, name }])
    setIsAddingFolder(false)
    setNewFolderName('')
    supabase.from('folders').insert({ id, user_id: userId, name }).then(logIfError)
  }

  function renameFolder(id) {
    const name = renameValue.trim()
    setRenamingFolderId(null)
    if (!name) return

    setFolders((current) => current.map((f) => (f.id === id ? { ...f, name } : f)))
    supabase.from('folders').update({ name }).eq('id', id).then(logIfError)
  }

  function deleteFolder(id) {
    // Un-file its documents locally to match the DB's ON DELETE SET NULL,
    // rather than leaving them pointed at a folder that no longer exists.
    setFolders((current) => current.filter((f) => f.id !== id))
    setFiles((current) => current.map((f) => (f.folderId === id ? { ...f, folderId: null } : f)))
    if (activeFolderId === id) setActiveFolderId('')

    supabase.from('folders').delete().eq('id', id).then(logIfError)
  }

  const visibleFiles = files.filter((f) => {
    if (activeFolderId === '') return true
    if (activeFolderId === 'unfiled') return !f.folderId
    return f.folderId === activeFolderId
  })

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

        <div className="folder-bar" role="tablist" aria-label="Filter documents by folder">
          <button
            type="button"
            className="folder-pill"
            aria-pressed={activeFolderId === ''}
            onClick={() => setActiveFolderId('')}
          >
            All
          </button>
          <button
            type="button"
            className="folder-pill"
            aria-pressed={activeFolderId === 'unfiled'}
            onClick={() => setActiveFolderId('unfiled')}
          >
            Unfiled
          </button>

          {folders.map((folder) =>
            renamingFolderId === folder.id ? (
              <form
                key={folder.id}
                className="folder-rename"
                onSubmit={(e) => {
                  e.preventDefault()
                  renameFolder(folder.id)
                }}
              >
                <input
                  autoFocus
                  value={renameValue}
                  onChange={(e) => setRenameValue(e.target.value)}
                  onBlur={() => renameFolder(folder.id)}
                  aria-label={`Rename folder ${folder.name}`}
                />
              </form>
            ) : (
              <span className="folder-pill-wrap" key={folder.id}>
                <button
                  type="button"
                  className="folder-pill"
                  aria-pressed={activeFolderId === folder.id}
                  onClick={() => setActiveFolderId(folder.id)}
                >
                  {folder.name}
                </button>
                {activeFolderId === folder.id && (
                  <span className="folder-pill-actions">
                    <button
                      type="button"
                      aria-label={`Rename ${folder.name}`}
                      onClick={() => {
                        setRenamingFolderId(folder.id)
                        setRenameValue(folder.name)
                      }}
                    >
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
                        <path
                          d="M4 20l1-4L16 5l3 3L8 19l-4 1Z"
                          stroke="currentColor"
                          strokeWidth="1.8"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </button>
                    <button
                      type="button"
                      aria-label={`Delete ${folder.name}`}
                      onClick={() => deleteFolder(folder.id)}
                    >
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
                        <path d="M6 6l12 12M18 6 6 18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                      </svg>
                    </button>
                  </span>
                )}
              </span>
            ),
          )}

          {isAddingFolder ? (
            <form
              className="folder-new"
              onSubmit={(e) => {
                e.preventDefault()
                addFolder()
              }}
            >
              <input
                autoFocus
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                onBlur={() => (newFolderName.trim() ? addFolder() : setIsAddingFolder(false))}
                placeholder="Folder name"
                aria-label="New folder name"
              />
            </form>
          ) : (
            <button type="button" className="folder-add" onClick={() => setIsAddingFolder(true)}>
              + New folder
            </button>
          )}
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
          aria-label="Upload a document"
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
          {visibleFiles.length === 0 ? (
            <div className="empty">
              <p>{files.length === 0 ? 'No documents uploaded yet' : 'No documents in this folder'}</p>
              <span>
                {files.length === 0
                  ? 'Files you upload will show up here.'
                  : 'Upload a document while this folder is selected, or move one in.'}
              </span>
            </div>
          ) : (
            visibleFiles.map((record) => (
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

                <select
                  className="item-folder"
                  aria-label={`Move ${record.name} to a folder`}
                  value={record.folderId || ''}
                  onChange={(e) => moveFile(record.id, e.target.value || null)}
                  disabled={folders.length === 0}
                >
                  <option value="">Unfiled</option>
                  {folders.map((folder) => (
                    <option key={folder.id} value={folder.id}>
                      {folder.name}
                    </option>
                  ))}
                </select>

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

        <ComplianceCheck jurisdiction={jurisdiction} files={files} folders={folders} />
      </div>
    </main>
  )
}