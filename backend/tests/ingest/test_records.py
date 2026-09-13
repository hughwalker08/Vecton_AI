from dataclasses import asdict

from app.ingest.records import ChunkRecord, CorpusReport, IngestReport


def test_chunk_record_to_dict_strips_private_ref_keys():
    chunk = ChunkRecord(
        id="c1",
        node_type="subclause",
        internal_refs=[
            {"clause_id": "H1D4", "chunk_id": "c2", "_target_guid": "_c2", "_target_corpus": "vol2"}
        ],
        external_refs=[
            {
                "kind": "housing",
                "clause_id": "10.8",
                "chunk_id": None,
                "_target_guid": "_h1",
                "_target_corpus": "housing",
            }
        ],
    )

    d = chunk.to_dict()

    assert d["internal_refs"] == [{"clause_id": "H1D4", "chunk_id": "c2"}]
    assert d["external_refs"] == [{"kind": "housing", "clause_id": "10.8", "chunk_id": None}]
    # non-ref fields pass through untouched
    assert d["id"] == "c1"
    assert d["node_type"] == "subclause"


def test_chunk_record_defaults():
    chunk = ChunkRecord(id="c1", node_type="clause")

    d = chunk.to_dict()

    assert d["hierarchy"] == []
    assert d["defined_terms"] == []
    assert d["jurisdictions"] is None
    assert d["clause_id"] is None
    assert d["applicability_note"] is None


def test_corpus_report_fields():
    # CorpusReport has no to_dict of its own (unlike ChunkRecord/IngestReport)
    # -- it's a plain dataclass, so asdict() is the generic equivalent.
    report = CorpusReport(
        doc_label="NCC 2025 Volume Two", chunks_by_node_type={"subclause": 10}, clauses_total=5
    )

    assert asdict(report) == {
        "doc_label": "NCC 2025 Volume Two",
        "chunks_by_node_type": {"subclause": 10},
        "clauses_total": 5,
    }


def test_ingest_report_to_dict_has_the_expected_shape():
    report = IngestReport()

    d = report.to_dict()

    assert d == {
        "corpora": {},
        "images_matched": 0,
        "images_unmatched": [],
        "figures_described": 0,
        "figures_undescribed": [],
        "standards_matched": 0,
        "standards_unmatched": [],
        "internal_refs_resolved": 0,
        "internal_refs_unresolved": 0,
        "external_refs_by_kind": {},
        "housing_bare_citations_found": 0,
        "housing_bare_citations_resolved": 0,
    }
