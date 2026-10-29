"""
Glossary lookup: attach NCC Schedule 1 definitions to the final prompt.

Glossary entries are kept out of retrieval entirely (see retrieval.py's
`node_type <> 'glossary'` filter). On their own they make poor search hits:
about 135 of the 493 are abbreviations or symbols whose text is a bare
phrase ("Alternating Current"), and they took reranker slots from real
clauses. A definition only matters once a clause that uses the term has
been retrieved, so they are looked up after retrieval instead:

  * from each final chunk's `defined_terms` -- the NCC's own
    `type="abcb-glossentry"` links, resolved to the canonical glossterm at
    ingest (see app/ingest/chunker.py's extract_refs), and
  * from the question itself, so "what counts as a habitable room?" still
    gets the definition even when no retrieved clause links to it.

The glossary is small (one row per entry, a few hundred KB), so it's read
from `clause_chunks` once per process and kept in memory.
"""

from __future__ import annotations

import logging
import re
import threading

from app.db.session import engine

logger = logging.getLogger(__name__)

# Definitions attached per prompt. Clauses that link terms average about two
# each, so ten chunks rarely need more; the cap bounds the worst case.
MAX_DEFINITIONS = 15

_GLOSSARY_SQL = """
    SELECT heading, text
    FROM clause_chunks
    WHERE node_type = 'glossary' AND heading IS NOT NULL
    ORDER BY id
"""

_lock = threading.Lock()
# term -> definition, or None until first loaded.
_terms: dict[str, str] | None = None
# Compiled question matchers, longest term first, built alongside _terms.
_patterns: list[tuple[str, re.Pattern]] = []


def _is_abbreviation(term: str) -> bool:
    """A symbol, short code or acronym: <= 3 characters, or containing an
    all-capitals word ("NATA", "FRL", "AS"). Anything else is ordinary
    wording, including multi-word terms that merely capitalise each word
    ("Accredited Testing Laboratory", "Performance Requirement")."""
    if len(term) <= 3:
        return True
    return any(len(word) > 1 and word.isupper() for word in re.findall(r"[A-Za-z0-9]+", term))


def _matcher(term: str) -> re.Pattern:
    """Whole-word pattern for spotting `term` in a question.

    Abbreviations and short symbols ("AS", "FRL", "mm") are matched
    case-sensitively, or "as" and "frl" would match ordinary words.
    Ordinary terms match in any case: people type "accredited testing
    laboratory" in lowercase, and the NCC capitalises it.
    """
    flags = 0 if _is_abbreviation(term) else re.IGNORECASE
    return re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", flags)


def _set_terms(terms: dict[str, str]) -> None:
    global _terms, _patterns
    _patterns = [
        (term, _matcher(term))
        for term in sorted(terms, key=len, reverse=True)
        # Single-character symbols ("C", "R") would match almost anything.
        if len(term) > 1
    ]
    _terms = terms


def load_terms() -> dict[str, str]:
    """The glossary as {term: definition}, read from the DB on first call.

    A failed load is logged and leaves the cache empty for this call only,
    so answers still go out (without definitions) and the next request
    tries again.
    """
    if _terms is not None:
        return _terms
    with _lock:
        if _terms is not None:
            return _terms
        from sqlalchemy import text as sql_text

        try:
            with engine.connect() as conn:
                rows = conn.execute(sql_text(_GLOSSARY_SQL)).all()
        except Exception:  # noqa: BLE001 - definitions are an extra, never fatal
            logger.exception("Could not load glossary definitions")
            return {}
        terms: dict[str, str] = {}
        for heading, definition in rows:
            terms.setdefault(heading.strip(), definition or "")
        _set_terms(terms)
        return terms


def definitions_for(chunks: list[dict], question: str = "") -> list[dict]:
    """Definitions for the terms `question` and `chunks` use, as
    [{"term", "definition"}], question matches first, then each chunk's
    `defined_terms` in relevance order. De-duplicated, capped at
    MAX_DEFINITIONS, and skipping any term with no glossary entry."""
    terms = load_terms()
    if not terms:
        return []

    wanted: list[str] = []
    if question:
        wanted.extend(term for term, pattern in _patterns if pattern.search(question))
    for chunk in chunks:
        wanted.extend(chunk.get("defined_terms") or [])

    seen: set[str] = set()
    definitions = []
    for term in wanted:
        definition = terms.get(term)
        if not definition or term in seen:
            continue
        seen.add(term)
        definitions.append({"term": term, "definition": definition})
        if len(definitions) >= MAX_DEFINITIONS:
            break
    return definitions


_QUOTES = re.compile(r"[\"'\u2018\u2019\u201c\u201d]")
# "... mean(s) [by|of|as] [a|an|the] <term>" / "definition of <term>" / "define <term>"
_CUE_BEFORE = re.compile(
    r"\b(?:means?|meant|meaning|definition|define|defined)\b(?:\s+(?:by|of|as|for))?\s+(?:an?|the)?\s*$",
    re.IGNORECASE,
)
# "what is [a|an|the] <term>" with the term ending the question
_WHAT_IS_BEFORE = re.compile(r"^\s*(?:what|which)\s+(?:is|are)\s+(?:an?|the)?\s*$", re.IGNORECASE)
# "<term> mean(s)" / "<term> stand(s) for" / "<term> defined"
_CUE_AFTER = re.compile(r"^\W*(?:means?|meaning|defined|stands?\s+for)\b", re.IGNORECASE)
# "the NCC mean(s) by ..." -- here the term is the subject of "mean", not what is being defined
_SUBJECT_OF_MEAN = re.compile(r"^\W*means?\s+(?:by|of)\b", re.IGNORECASE)


def definitions_for_request(question: str) -> list[dict]:
    """Definitions for the glossary terms `question` explicitly asks about.

    Used when retrieval found no clause strong enough to answer from: a
    definition request such as 'What does the NCC mean by an "accredited
    testing laboratory"?' can still be answered from the glossary, even when
    no clause discusses the term. Only a direct request counts ("mean by X",
    "definition of X", "X mean", "what is X?"): a glossary word that merely
    appears in an unrelated question ("What does clause H9Z7 of the NCC say?")
    must not turn a decline into an answer.
    """
    terms = load_terms()
    if not terms:
        return []
    found: list[str] = []
    for term, pattern in _patterns:
        for match in pattern.finditer(question):
            before = _QUOTES.sub("", question[: match.start()])
            after = _QUOTES.sub("", question[match.end():])
            asks = (
                _CUE_BEFORE.search(before)
                or (_CUE_AFTER.match(after) and not _SUBJECT_OF_MEAN.match(after))
                or (_WHAT_IS_BEFORE.match(before) and re.fullmatch(r"[\W_]*", after))
            )
            if asks and term not in found:
                found.append(term)
                break
    return [{"term": t, "definition": terms[t]} for t in found if terms.get(t)][:MAX_DEFINITIONS]
