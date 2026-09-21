import { useEffect, useState } from 'react'
import { analyseDocument, flagFinding } from '../api/client.js'
import FolderBrowser from '../components/FolderBrowser.jsx'
import './UploadPage.css'
import SourcePanel from '../components/SourcePanel.jsx'

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
export function ComplianceCheck({ jurisdiction, files, folders = [] }) {
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
  return (
    <main className="upload-page">
      <div className="upload-pane">
        <div className="upload-head">
          <h1>Project files</h1>
          <p className="sub">
            Upload plans, certificates or reports — drawings inside them get read
            automatically.
          </p>
        </div>

        <FolderBrowser files={files} setFiles={setFiles} folders={folders} setFolders={setFolders} userId={userId} />

        <ComplianceCheck jurisdiction={jurisdiction} files={files} folders={folders} />
      </div>
    </main>
  )
}
