"""Tests for app.ingest.report -- the validation summary the ingest CLI prints."""

import json

from app.ingest.records import ChunkRecord, CorpusReport, IngestReport
from app.ingest.report import build_corpus_report, print_report, write_report_json


def _chunk(node_type, clause_id):
    return ChunkRecord(id=f"{node_type}-{clause_id}", node_type=node_type, clause_id=clause_id)


def test_build_corpus_report_counts_chunks_by_node_type_sorted():
    chunks = [
        _chunk("subclause", "H1D4"),
        _chunk("note", "H1D4"),
        _chunk("subclause", "H1D5"),
        _chunk("clause", "H1D4"),
    ]

    report = build_corpus_report("NCC 2025 Volume Two", chunks)

    assert report.doc_label == "NCC 2025 Volume Two"
    assert report.chunks_by_node_type == {"clause": 1, "note": 1, "subclause": 2}
    assert list(report.chunks_by_node_type) == sorted(report.chunks_by_node_type)


def test_build_corpus_report_counts_distinct_clause_ids_from_subclauses_and_notes_only():
    chunks = [
        _chunk("subclause", "H1D4"),
        _chunk("subclause", "H1D4"),  # repeat -- same clause, counted once
        _chunk("note", "H1D5"),
        _chunk("clause", "H9Z9"),  # wrong node_type, ignored
        _chunk("subclause", None),  # no clause_id, ignored
    ]

    assert build_corpus_report("doc", chunks).clauses_total == 2


def test_build_corpus_report_handles_no_chunks():
    report = build_corpus_report("doc", [])

    assert report.chunks_by_node_type == {}
    assert report.clauses_total == 0


def _full_report():
    return IngestReport(
        corpora={"vol2": CorpusReport(doc_label="NCC Vol 2", chunks_by_node_type={"subclause": 3}, clauses_total=2)},
        images_matched=4,
        images_unmatched=["a.png"],
        figures_described=3,
        figures_undescribed=["b.png"],
        standards_matched=5,
        standards_unmatched=["AS 9999"],
        internal_refs_resolved=7,
        internal_refs_unresolved=1,
        external_refs_by_kind={"standard": {"total": 6, "resolved": 5}},
        housing_bare_citations_found=2,
        housing_bare_citations_resolved=1,
    )


def test_print_report_shows_every_section(capsys):
    print_report(_full_report())
    out = capsys.readouterr().out

    assert "[vol2] NCC Vol 2 -- 2 distinct clause_ids" in out
    assert "subclause" in out
    assert "Images: 4 matched, 1 unmatched" in out
    assert "- a.png" in out
    assert "Figure descriptions: 3 of 4 matched figures" in out
    assert "1 matched figure(s) have no description" in out
    assert "- b.png" in out
    assert "Standards: 5 matched, 1 unmatched" in out
    assert "- AS 9999" in out
    assert "Internal refs: 7 resolved, 1 unresolved" in out
    assert "standard" in out and "6 / 5" in out
    assert "2 found, 1 resolved" in out


def test_print_report_skips_the_detail_lists_when_nothing_is_missing(capsys):
    clean = IngestReport(images_matched=2, figures_described=2, standards_matched=1)

    print_report(clean)
    out = capsys.readouterr().out

    assert "Images: 2 matched, 0 unmatched" in out
    assert "have no description" not in out
    assert "Generate them" not in out


def test_write_report_json_writes_the_report_and_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "dir" / "report.json"

    write_report_json(_full_report(), path)

    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["images_matched"] == 4
    assert written["corpora"]["vol2"]["clauses_total"] == 2
