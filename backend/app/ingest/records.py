"""
Dataclasses shared across the ingest pipeline.

This phase only parses NCC 2025 Volume Two + the ABCB Housing Provisions
(v1.2 schema) into local JSON (see app.ingest.serialize) -- no database
writes, no embeddings. The ChunkRecord shape mirrors the eventual
`clause_chunks` DB columns so a later phase can load this JSON, embed
`text`, and upsert directly.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class ChunkRecord:
    id: str
    node_type: str
    clause_id: Optional[str] = None
    hierarchy: list = field(default_factory=list)
    heading: Optional[str] = None
    doc: str = ""
    text: str = ""
    defined_terms: list = field(default_factory=list)
    cross_refs: list = field(default_factory=list)
    internal_refs: list = field(default_factory=list)
    image_refs: list = field(default_factory=list)
    external_refs: list = field(default_factory=list)
    building_classes: list = field(default_factory=list)
    jurisdictions: Optional[list] = None
    climate_zones: list = field(default_factory=list)
    applicability_note: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        # internal_refs/external_refs carry a private "_target_guid"/
        # "_target_corpus" used by the shared post-pass to fill chunk_id --
        # strip before serializing.
        for key in ("internal_refs", "external_refs"):
            d[key] = [{k: v for k, v in item.items() if not k.startswith("_")} for item in d[key]]
        return d


@dataclass
class CorpusReport:
    doc_label: str = ""
    chunks_by_node_type: dict = field(default_factory=dict)
    clauses_total: int = 0


@dataclass
class IngestReport:
    corpora: dict = field(default_factory=dict)  # corpus name -> CorpusReport
    images_matched: int = 0
    images_unmatched: list = field(default_factory=list)
    standards_matched: int = 0
    standards_unmatched: list = field(default_factory=list)
    internal_refs_resolved: int = 0
    internal_refs_unresolved: int = 0
    external_refs_by_kind: dict = field(default_factory=dict)  # kind -> {"total": N, "resolved": N}
    housing_bare_citations_found: int = 0
    housing_bare_citations_resolved: int = 0

    def to_dict(self) -> dict:
        return asdict(self)
