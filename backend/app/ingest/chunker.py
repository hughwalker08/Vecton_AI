"""
Clause -> ChunkRecord list (v1.2 schema).

One chunk per `<subclause>` (matches how the NCC is actually cited, e.g.
"H1D4(2)"), plus:
- one `node_type="note"` chunk per `<callout>` (explanatory/notes/
  application/limitation/exemption boxes -- direct children of `clause`,
  `part`, `subtopic`, or `glossdef`, not nested inside a subclause),
- one extra `subclause`-shaped chunk per `<subclause-variation>` /
  `<clause-variation>` (state-specific replacement or inserted text --
  tagged with that variation's own `jurisdictions`).

Cross-reference handling (verified against the real v1.2 corpus, not
assumed -- see the project plan for the investigation):
- `<a href="#_GUID" type="...">` GUIDs are reliable now (unlike the old
  schema's stale hrefs) and resolve directly via the shared `guid_index`,
  built across BOTH loaded corpora -- no more fuzzy text-matching.
- A link is EXTERNAL when it carries `publishing-id` that differs from the
  owning corpus's own `publishing-id` (NOT a `scope` attribute -- that
  concept doesn't exist in this schema at all). `type="abcb-glossentry"`
  and `type="image-reference"` get their own structured handling
  (`defined_terms` / `image_refs`) regardless of local/external.
- Refs that resolve into a corpus we didn't load (Volume One/Three) simply
  get no `_target_guid` -- `chunk_id` stays null, exactly like before.
"""

from dataclasses import dataclass

from app.ingest.applicability import (
    extract_building_classes,
    extract_climate_zones,
    extract_jurisdiction,
)
from app.ingest.guid_index import resolve_guid
from app.ingest.hierarchy import ancestor_path
from app.ingest.records import ChunkRecord

_ROMAN = [(10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]

_CLAUSE_LIKE_TYPES = {"clause", "ncc-clause", "subclause", "part", "specification", "table-reference"}


def _to_roman(n: int) -> str:
    result = []
    for value, symbol in _ROMAN:
        while n >= value:
            result.append(symbol)
            n -= value
    return "".join(result)


def _marker(style, index: int, depth: int) -> str:
    if style == "alpha":
        return chr(ord("a") + index)
    if style == "numbered":
        return str(index + 1)
    return _to_roman(index + 1) if depth > 0 else str(index + 1)


def _equation_text(eq_el) -> str:
    """MathML's own <annotation> is an unreadable MathType binary blob --
    pull the readable operator/identifier/number tokens instead."""
    parts = [m.text for m in eq_el.iter("mi", "mn", "mo") if m.text]
    return "".join(parts) or "[equation]"


def _direct_text(el) -> str:
    """Text of `el` excluding nested <ol>/<ul>/<section> (rendered separately)."""
    fragments = [el.text or ""]
    for child in el:
        if child.tag in ("ol", "ul", "section"):
            if child.tail:
                fragments.append(child.tail)
            continue
        if child.tag in ("equation-inline", "equation-block"):
            fragments.append(_equation_text(child))
            if child.tail:
                fragments.append(child.tail)
            continue
        fragments.append("".join(child.itertext()))
        if child.tail:
            fragments.append(child.tail)
    text = "".join(fragments)
    return " ".join(text.split())


def _render_list(list_el, depth: int, lines: list) -> None:
    style = list_el.get("class")
    indent = "  " * depth
    for i, li in enumerate(list_el.findall("li")):
        marker = _marker(style, i, depth)
        text = _direct_text(li)
        lines.append(f"{indent}({marker}) {text}")
        for nested in li:
            if nested.tag in ("ol", "ul"):
                _render_list(nested, depth + 1, lines)


def _render_block_children(container_el, lines: list) -> None:
    for child in container_el:
        if child.tag == "p":
            text = _direct_text(child)
            if text:
                lines.append(text)
        elif child.tag in ("ol", "ul"):
            _render_list(child, 0, lines)
        elif child.tag == "section":
            title = child.findtext("title")
            if title:
                lines.append(f"{title}:")
            _render_block_children(child, lines)
        elif child.tag == "equation-block":
            lines.append(_equation_text(child))


def render_content(content_el) -> str:
    lines = []
    _render_block_children(content_el, lines)
    text = "\n".join(lines)
    num_prefix = content_el.findtext("num")
    if num_prefix and text:
        first, _, rest = text.partition("\n")
        sep = "" if num_prefix.endswith(" ") else " "
        first = f"{num_prefix}{sep}{first}"
        text = first if not rest else f"{first}\n{rest}"
    return text


@dataclass
class RefContext:
    guid_index: dict
    corpus: object  # the Corpus that owns the element currently being processed
    glossary_terms: dict  # element id -> canonical glossterm text (both corpora)


def extract_refs(container_el, ctx: RefContext):
    """Walk every <a href="#_GUID"> under `container_el`. Returns
    (cross_refs, defined_terms, image_refs, external_refs, internal_refs)."""
    cross_refs = []
    defined_terms = []
    image_refs = []
    external_refs = []
    internal_refs = []
    seen_terms = set()
    seen_images = set()

    for a in container_el.iter("a"):
        raw_text = "".join(a.itertext()).strip()
        href = a.get("href", "")
        if not raw_text or not href.startswith("#"):
            continue  # skip plain external http(s) links (e.g. www.abcb.gov.au)
        guid = href[1:]
        cross_refs.append(raw_text)

        a_type = a.get("type")
        link_pubid = a.get("publishing-id")
        is_external = bool(link_pubid) and link_pubid != ctx.corpus.publishing_id
        resolved = resolve_guid(
            guid, ctx.guid_index, ctx.corpus, target_publishing_id=link_pubid if is_external else None
        )

        if a_type == "abcb-glossentry":
            term = raw_text
            if resolved:
                _target_corpus, target_el = resolved
                term = ctx.glossary_terms.get(target_el.get("id"), raw_text)
            if term not in seen_terms:
                seen_terms.add(term)
                defined_terms.append(term)
            continue

        if a_type == "image-reference":
            if resolved:
                target_corpus, target_el = resolved
                target_guid = target_el.get("id")
                if target_guid not in seen_images:
                    img = target_el.find("img")
                    src = img.get("src") if img is not None else None
                    if src and (target_corpus.images_dir / src).exists():
                        seen_images.add(target_guid)
                        image_refs.append(
                            {
                                "image_id": target_guid.removeprefix("_"),
                                "filename": src,
                                "caption": raw_text,
                            }
                        )
            continue

        if is_external:
            entry = {"kind": link_pubid, "clause_id": raw_text, "raw_text": raw_text, "chunk_id": None}
            if resolved:
                target_corpus, target_el = resolved
                entry["_target_guid"] = target_el.get("id")
                entry["_target_corpus"] = target_corpus.name
                own_num = target_el.findtext("sptc") or target_el.get("num")
                if own_num and own_num.strip():
                    entry["clause_id"] = own_num.strip()
            external_refs.append(entry)
        elif a_type in _CLAUSE_LIKE_TYPES:
            entry = {"clause_id": raw_text, "chunk_id": None}
            if resolved:
                target_corpus, target_el = resolved
                entry["_target_guid"] = target_el.get("id")
                entry["_target_corpus"] = target_corpus.name
            internal_refs.append(entry)

    return cross_refs, defined_terms, image_refs, external_refs, internal_refs


def _make_chunk(
    *,
    node_type,
    element_id,
    clause_id,
    hierarchy,
    heading,
    corpus,
    text,
    refs,
    building_classes,
    climate_zones,
    jurisdictions,
):
    cross_refs, defined_terms, image_refs, external_refs, internal_refs = refs
    return ChunkRecord(
        id=element_id.removeprefix("_"),
        node_type=node_type,
        clause_id=clause_id,
        hierarchy=hierarchy,
        heading=heading,
        doc=corpus.doc_label,
        text=text,
        defined_terms=defined_terms,
        cross_refs=cross_refs,
        internal_refs=internal_refs,
        image_refs=image_refs,
        external_refs=external_refs,
        building_classes=building_classes,
        jurisdictions=jurisdictions,
        climate_zones=climate_zones,
    )


def build_clause_chunks(clause_el, corpus, ctx: RefContext, jurisdiction_override=None) -> list:
    """Handles a real `<clause>` AND a `<clause-variation>` (same shape:
    sptc, title, subclause/callout/nested clause-variation children)."""
    # A real <clause> carries sptc as a child element; a <clause-variation>
    # (no <sptc> child) carries the same information as an attribute instead.
    sptc = (clause_el.findtext("sptc") or clause_el.get("sptc") or "").strip() or None
    title = clause_el.findtext("title")
    building_classes = extract_building_classes(clause_el)
    climate_zones = extract_climate_zones(clause_el)
    base_path = ancestor_path(corpus.doc_label, clause_el)
    if sptc:
        base_path = base_path + [sptc]

    chunks = []

    for subclause in clause_el.findall("subclause"):
        chunks.append(
            _build_subclause_chunk(
                subclause, corpus, ctx, sptc, title, base_path, jurisdiction_override, building_classes, climate_zones
            )
        )
        for scv in subclause.findall("subclause-variation"):
            chunks.append(
                _build_subclause_chunk(
                    scv, corpus, ctx, sptc, title, base_path, scv.get("state") or jurisdiction_override,
                    building_classes, climate_zones,
                )
            )

    for scv in clause_el.findall("subclause-variation"):
        chunks.append(
            _build_subclause_chunk(
                scv, corpus, ctx, sptc, title, base_path, scv.get("state") or jurisdiction_override,
                building_classes, climate_zones,
            )
        )

    for callout in clause_el.findall("callout"):
        chunks.append(_build_callout_chunk(callout, corpus, ctx, sptc, base_path, jurisdiction_override))

    for cv in clause_el.findall("clause-variation"):
        chunks.extend(build_clause_chunks(cv, corpus, ctx, jurisdiction_override=cv.get("state")))

    if not chunks:
        # A <clause-variation> (e.g. type="DELETE"/"REPLACE") often carries its
        # own <content> directly rather than wrapping a <subclause> -- e.g. a
        # jurisdiction-specific "this clause has deliberately been left blank"
        # notice. Render that directly rather than discarding it as empty text.
        content = clause_el.find("content")
        text = render_content(content) if content is not None else ""
        refs = extract_refs(clause_el, ctx)
        chunks.append(
            _make_chunk(
                node_type="note" if jurisdiction_override else "clause",
                element_id=clause_el.get("id", ""),
                clause_id=sptc,
                hierarchy=base_path,
                heading=title,
                corpus=corpus,
                text=text,
                refs=refs,
                building_classes=building_classes,
                climate_zones=climate_zones,
                jurisdictions=jurisdiction_override and [jurisdiction_override],
            )
        )

    return chunks


def _build_subclause_chunk(
    subclause_el, corpus, ctx, sptc, title, base_path, jurisdiction_override, building_classes, climate_zones
):
    content = subclause_el.find("content")
    text = render_content(content) if content is not None else ""
    refs = extract_refs(subclause_el, ctx)
    num = (subclause_el.get("num") or "").strip()
    hierarchy = list(base_path)
    if num:
        hierarchy.append(f"{sptc}({num})" if sptc else num)
    jurisdictions = extract_jurisdiction(subclause_el) or (
        [jurisdiction_override] if jurisdiction_override else None
    )
    return _make_chunk(
        node_type="subclause",
        element_id=subclause_el.get("id", ""),
        clause_id=sptc,
        hierarchy=hierarchy,
        heading=subclause_el.get("title") or title,
        corpus=corpus,
        text=text,
        refs=refs,
        building_classes=building_classes,
        climate_zones=climate_zones,
        jurisdictions=jurisdictions,
    )


def _build_callout_chunk(callout_el, corpus, ctx, sptc, base_path, jurisdiction_override):
    content = callout_el.find("content")
    text = render_content(content) if content is not None else ""
    refs = extract_refs(callout_el, ctx)
    kind = callout_el.get("callout-type")
    return _make_chunk(
        node_type="note",
        element_id=callout_el.get("id", ""),
        clause_id=sptc,
        hierarchy=list(base_path),
        heading=f"Note ({kind})" if kind else "Note",
        corpus=corpus,
        text=text,
        refs=refs,
        building_classes=[],
        climate_zones=[],
        jurisdictions=[jurisdiction_override] if jurisdiction_override else None,
    )
