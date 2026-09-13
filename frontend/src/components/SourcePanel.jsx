import './SourcePanel.css'

// Renders one retrieved Citation (see backend/app/api/routes/chat.py) as a
// readable clause card. Adapted from the "source" panel in
// design-mockups/compliance-rag-ui.html -- that mockup shows a paged PDF
// excerpt (page X of Y) since its data is fake; ours is clause-based, not
// page-based, so this shows the clause heading/text/applicability the
// backend actually retrieved instead of a page number.
export default function SourcePanel({ citation, onClose }) {
  const isOpen = Boolean(citation)

  const qualifiers = []
  if (citation?.building_classes?.length) {
    qualifiers.push(`building classes: ${citation.building_classes.join(', ')}`)
  }
  if (citation?.jurisdictions?.length) {
    qualifiers.push(`jurisdictions: ${citation.jurisdictions.join(', ')}`)
  }
  if (citation?.climate_zones?.length) {
    qualifiers.push(`climate zones: ${citation.climate_zones.join(', ')}`)
  }
  if (citation?.applicability_note) {
    qualifiers.push(citation.applicability_note)
  }

  return (
    <>
      <div className={`src-scrim ${isOpen ? 'on' : ''}`} onClick={onClose} />
      <aside className={`source ${isOpen ? 'open' : ''}`} aria-label="Cited source" aria-hidden={!isOpen}>
        {citation && (
          <>
            <div className="src-top">
              <button className="back" aria-label="Close source" onClick={onClose}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                  <path d="M6 6l12 12M18 6 6 18" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
                </svg>
              </button>
              <div className="src-title">{citation.doc}</div>
            </div>

            <div className="src-scroll">
              <div className="page">
                <p className="clause-no">{citation.clause_id}</p>
                {citation.heading && <p className="clause-ttl">{citation.heading}</p>}
                <div className="clause-body">
                  <p>{citation.text || 'No clause text was returned for this citation.'}</p>
                  {qualifiers.length > 0 && (
                    <p className="applicability">
                      <strong>Applicability: </strong>
                      {qualifiers.join('; ')}
                    </p>
                  )}
                </div>
              </div>

              <div className="src-foot">
                <span className="dot" />
                <span>
                  Cited passage · {citation.doc}
                  {citation.source_url && (
                    <>
                      {' · '}
                      <a href={citation.source_url} target="_blank" rel="noreferrer">
                        View original ↗
                      </a>
                    </>
                  )}
                </span>
              </div>
            </div>
          </>
        )}
      </aside>
    </>
  )
}
