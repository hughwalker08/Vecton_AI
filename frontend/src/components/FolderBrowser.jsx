import { useRef, useState } from 'react'
import { uploadDocument } from '../api/client.js'
import { supabase } from '../lib/supabase.js'
import '../pages/UploadPage.css'

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

// Small inline icons shared by the folder list/current-folder header below --
// kept tiny and un-styled beyond size so they inherit color from whatever
// button wraps them.
export function FolderIcon() {
  return (
    <svg className="folder-row-ico" width="17" height="17" viewBox="0 0 24 24" fill="none">
      <path
        d="M3.5 7.5A1.5 1.5 0 0 1 5 6h4l1.8 2H19a1.5 1.5 0 0 1 1.5 1.5v8A1.5 1.5 0 0 1 19 19H5a1.5 1.5 0 0 1-1.5-1.5v-10Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function PencilIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
      <path
        d="M4 20l1-4L16 5l3 3L8 19l-4 1Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function XIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
      <path d="M6 6l12 12M18 6 6 18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

function BackIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
      <path d="M14.5 5.5 8 12l6.5 6.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

// Folders-as-rows file browser (create/rename/delete folders, move files
// between them, drag/drop or browse to upload) -- shared by UploadPage (the
// global "Project files" page) and ProjectPage (scoped to one project).
//
// `projectId`, when given, tags every new folder/file created here with it
// (see migrations 0009/0010) so it shows up when a parent re-filters its
// `files`/`folders` lists down to that project. `files`/`folders` are
// expected to already be scoped to whatever this browser should show --
// UploadPage passes everything, ProjectPage pre-filters by project_id --
// but `setFiles`/`setFolders` must always be the top-level App.jsx setters,
// never a scoped copy, since a functional update's `current` always reads
// the real full state regardless of what filtered array was rendered.
export default function FolderBrowser({ files, setFiles, folders = [], setFolders, userId, projectId = null }) {
  const [isDragging, setIsDragging] = useState(false)
  // '' = root (folders + unfiled files), else a folders.id you've drilled into.
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

    // A new file lands in whichever folder is currently open -- root (no
    // folder open) means "no folder", same as an unfiled file.
    const folderId = activeFolderId || null

    const records = incoming.map((file) => ({
      id: crypto.randomUUID(),
      file,
      name: file.name,
      size: file.size,
      uploadedAt: new Date(),
      status: 'uploading',
      detail: 'Uploading…',
      folderId,
      projectId,
    }))

    setFiles((current) => [...records, ...current])
    records.forEach((record) => {
      supabase
        .from('documents')
        .insert({
          id: record.id,
          user_id: userId,
          folder_id: record.folderId,
          project_id: projectId,
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

    setFolders((current) => [...current, { id, name, projectId }])
    setIsAddingFolder(false)
    setNewFolderName('')
    supabase.from('folders').insert({ id, user_id: userId, project_id: projectId, name }).then(logIfError)
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

  // Root shows folders (as rows) plus whatever isn't filed into one; drilling
  // into a folder narrows this to just its own files -- see the folder-list
  // vs. folder-current split in the render below.
  const visibleFiles = files.filter((f) =>
    activeFolderId === '' ? !f.folderId : f.folderId === activeFolderId,
  )
  const currentFolder = folders.find((f) => f.id === activeFolderId)

  return (
    <>
      <div className="counts">
        <div className="count">
          <b>{files.length}</b>
          <span>file{files.length === 1 ? '' : 's'}</span>
        </div>
        <div className="count">
          <b>{folders.length}</b>
          <span>folder{folders.length === 1 ? '' : 's'}</span>
        </div>
      </div>

      {activeFolderId === '' ? (
        <div className="folder-list">
          {isAddingFolder ? (
            <form
              className="folder-row"
              onSubmit={(e) => {
                e.preventDefault()
                addFolder()
              }}
            >
              <FolderIcon />
              <input
                autoFocus
                className="folder-row-input"
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                onBlur={() => (newFolderName.trim() ? addFolder() : setIsAddingFolder(false))}
                placeholder="Folder name"
                aria-label="New folder name"
              />
            </form>
          ) : (
            <button type="button" className="folder-row folder-row-add" onClick={() => setIsAddingFolder(true)}>
              <FolderIcon />
              New folder
            </button>
          )}

          {folders.map((folder) => {
            const count = files.filter((f) => f.folderId === folder.id).length
            return renamingFolderId === folder.id ? (
              <form
                key={folder.id}
                className="folder-row"
                onSubmit={(e) => {
                  e.preventDefault()
                  renameFolder(folder.id)
                }}
              >
                <FolderIcon />
                <input
                  autoFocus
                  className="folder-row-input"
                  value={renameValue}
                  onChange={(e) => setRenameValue(e.target.value)}
                  onBlur={() => renameFolder(folder.id)}
                  aria-label={`Rename folder ${folder.name}`}
                />
              </form>
            ) : (
              <div className="folder-row" key={folder.id}>
                <button type="button" className="folder-row-main" onClick={() => setActiveFolderId(folder.id)}>
                  <FolderIcon />
                  <span className="folder-row-body">
                    <span className="folder-row-name">{folder.name}</span>
                    <span className="folder-row-count">
                      {count} file{count === 1 ? '' : 's'}
                    </span>
                  </span>
                </button>
                <span className="folder-row-actions">
                  <button
                    type="button"
                    aria-label={`Rename ${folder.name}`}
                    onClick={() => {
                      setRenamingFolderId(folder.id)
                      setRenameValue(folder.name)
                    }}
                  >
                    <PencilIcon />
                  </button>
                  <button
                    type="button"
                    aria-label={`Delete ${folder.name}`}
                    onClick={() => deleteFolder(folder.id)}
                  >
                    <XIcon />
                  </button>
                </span>
              </div>
            )
          })}
        </div>
      ) : (
        <div className="folder-current">
          <button type="button" className="folder-back" onClick={() => setActiveFolderId('')}>
            <BackIcon />
            All files
          </button>

          {renamingFolderId === activeFolderId ? (
            <form
              className="folder-row folder-current-rename"
              onSubmit={(e) => {
                e.preventDefault()
                renameFolder(activeFolderId)
              }}
            >
              <input
                autoFocus
                className="folder-row-input"
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
                onBlur={() => renameFolder(activeFolderId)}
                aria-label={`Rename folder ${currentFolder?.name}`}
              />
            </form>
          ) : (
            <span className="folder-current-name">
              {currentFolder?.name}
              <button
                type="button"
                aria-label={`Rename ${currentFolder?.name}`}
                onClick={() => {
                  setRenamingFolderId(activeFolderId)
                  setRenameValue(currentFolder?.name || '')
                }}
              >
                <PencilIcon />
              </button>
              <button
                type="button"
                aria-label={`Delete ${currentFolder?.name}`}
                onClick={() => deleteFolder(activeFolderId)}
              >
                <XIcon />
              </button>
            </span>
          )}
        </div>
      )}

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
            <p>
              {activeFolderId === ''
                ? files.length === 0
                  ? 'No documents uploaded yet'
                  : 'No unfiled documents'
                : 'No documents in this folder'}
            </p>
            <span>
              {activeFolderId === ''
                ? 'Files without a folder will show up here.'
                : 'Upload a document while viewing this folder, or move one in.'}
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
    </>
  )
}
