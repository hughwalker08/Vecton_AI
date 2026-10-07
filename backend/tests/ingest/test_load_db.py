"""
Tests for app.ingest.load_db -- the step that puts parsed chunk JSON into the
clause_chunks table.

No real database: upsert()/load() are exercised against a fake session, and
SessionLocal is monkeypatched. The compiled SQL isn't checked beyond "an
INSERT ... ON CONFLICT DO UPDATE was executed" -- that needs a real Postgres,
which tests/test_migrations.py's live round-trip covers for the schema.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.ingest import load_db

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _record(**overrides):
    base = {"id": "vol2-H1D4-1", "node_type": "subclause", "clause_id": "H1D4", "text": "Footings."}
    return {**base, **overrides}


# --- default_paths ------------------------------------------------------


def test_default_paths_prefers_the_embedded_file_when_it_exists(tmp_path):
    (tmp_path / "ncc_volume_two_chunks.embedded.json").write_text("[]")

    paths = load_db.default_paths(tmp_path)

    assert paths[0] == tmp_path / "ncc_volume_two_chunks.embedded.json"
    # No embedded file for the Housing Provisions -- falls back to the plain one.
    assert paths[1] == tmp_path / "abcb_housing_provisions_chunks.json"


# --- to_row -------------------------------------------------------------


def test_to_row_maps_the_core_fields_and_stamps_provenance():
    row = load_db.to_row(_record(heading="Footings", doc="NCC 2025 Volume Two"), "v1", NOW)

    assert row["id"] == "vol2-H1D4-1"
    assert row["clause_id"] == "H1D4"
    assert row["heading"] == "Footings"
    assert row["doc"] == "NCC 2025 Volume Two"
    assert row["dataset_version"] == "v1"
    assert row["retrieved_at"] == NOW


def test_to_row_renames_external_refs_to_standard_refs():
    refs = [{"standard": "AS 3786"}]

    assert load_db.to_row(_record(external_refs=refs), "v1", NOW)["standard_refs"] == refs


def test_to_row_defaults_node_type_and_empty_collections():
    row = load_db.to_row({"id": "x"}, "v1", NOW)

    assert row["node_type"] == "clause"
    assert row["hierarchy"] == []
    assert row["defined_terms"] == []
    assert row["cross_refs"] == []
    assert row["internal_refs"] == []
    assert row["standard_refs"] == []
    assert row["image_refs"] == []


def test_to_row_turns_a_missing_text_into_an_empty_string_not_null():
    # text is NOT NULL in the table -- None would fail the constraint.
    assert load_db.to_row({"id": "x", "text": None}, "v1", NOW)["text"] == ""
    assert load_db.to_row({"id": "x"}, "v1", NOW)["text"] == ""


def test_to_row_normalises_empty_applicability_lists_to_null():
    # Ingest writes [] for "no restriction"; the table means NULL. Left as [],
    # a `jurisdictions IS NULL OR 'NSW' = ANY(jurisdictions)` filter would
    # quietly exclude every unrestricted clause.
    row = load_db.to_row(
        _record(building_classes=[], jurisdictions=[], climate_zones=[]), "v1", NOW
    )

    assert row["building_classes"] is None
    assert row["jurisdictions"] is None
    assert row["climate_zones"] is None


def test_to_row_keeps_populated_applicability_lists():
    row = load_db.to_row(_record(jurisdictions=["NSW"], climate_zones=[5]), "v1", NOW)

    assert row["jurisdictions"] == ["NSW"]
    assert row["climate_zones"] == [5]


def test_to_row_carries_an_embedding_through_when_present():
    assert load_db.to_row(_record(embedding=[0.1, 0.2]), "v1", NOW)["embedding"] == [0.1, 0.2]
    assert load_db.to_row(_record(), "v1", NOW)["embedding"] is None


# --- read_records -------------------------------------------------------


def test_read_records_concatenates_every_file(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps([_record(id="1")]))
    b.write_text(json.dumps([_record(id="2"), _record(id="3")]))

    records = load_db.read_records([a, b])

    assert [r["id"] for r in records] == ["1", "2", "3"]


def test_read_records_raises_a_helpful_error_for_a_missing_file(tmp_path):
    with pytest.raises(load_db.LoadError, match="Run `python -m app.ingest.cli` first"):
        load_db.read_records([tmp_path / "missing.json"])


def test_read_records_raises_for_invalid_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")

    with pytest.raises(load_db.LoadError, match="not valid JSON"):
        load_db.read_records([bad])


def test_read_records_raises_when_the_file_is_not_a_list(tmp_path):
    obj = tmp_path / "obj.json"
    obj.write_text(json.dumps({"id": "1"}))

    with pytest.raises(load_db.LoadError, match="should contain a list"):
        load_db.read_records([obj])


# --- deduplicate --------------------------------------------------------


def test_deduplicate_keeps_the_last_row_for_a_shared_id():
    # Last wins: the one differing glossary entry's Volume Two copy has a
    # tracked-change artefact, so the Housing Provisions' clean copy (loaded
    # second) is the one to keep. See load_db's module docstring.
    rows = [{"id": "g1", "text": "greater thanat least"}, {"id": "g2", "text": "x"}, {"id": "g1", "text": "at least"}]

    deduped, dropped = load_db.deduplicate(rows)

    assert dropped == 1
    assert {r["id"]: r["text"] for r in deduped} == {"g1": "at least", "g2": "x"}


def test_deduplicate_with_no_duplicates_drops_nothing():
    rows = [{"id": "a"}, {"id": "b"}]

    deduped, dropped = load_db.deduplicate(rows)

    assert dropped == 0
    assert deduped == rows


# --- upsert -------------------------------------------------------------


class _FakeSession:
    def __init__(self):
        self.statements = []
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self.fail_on_execute = False

    def execute(self, statement):
        if self.fail_on_execute:
            raise RuntimeError("db exploded")
        self.statements.append(statement)
        return _FakeScalarResult(len(self.statements))

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value


def _rows(n):
    return [load_db.to_row(_record(id=f"id-{i}"), "v1", NOW) for i in range(n)]


def test_upsert_writes_in_batches_and_reports_progress():
    session = _FakeSession()
    progress = []

    written = load_db.upsert(session, _rows(5), batch_size=2, progress=progress.append)

    assert written == 5
    assert len(session.statements) == 3  # 2 + 2 + 1
    assert progress == ["  2/5 rows", "  4/5 rows", "  5/5 rows"]


def test_upsert_builds_an_insert_that_updates_on_id_conflict():
    session = _FakeSession()

    load_db.upsert(session, _rows(1), progress=lambda _msg: None)

    compiled = str(session.statements[0].compile())
    assert "INSERT INTO clause_chunks" in compiled
    assert "ON CONFLICT (id) DO UPDATE" in compiled


def test_upsert_with_no_rows_writes_nothing():
    session = _FakeSession()

    assert load_db.upsert(session, [], progress=lambda _msg: None) == 0
    assert session.statements == []


# --- load ---------------------------------------------------------------


def _write_corpus(tmp_path, records):
    path = tmp_path / "chunks.json"
    path.write_text(json.dumps(records))
    return path


def test_load_dry_run_reports_a_summary_without_touching_the_database(tmp_path, monkeypatch):
    path = _write_corpus(tmp_path, [_record(id="1"), _record(id="1"), _record(id="2", image_refs=["f.png"])])
    monkeypatch.setattr(load_db, "SessionLocal", lambda: pytest.fail("dry run must not open a session"))

    summary = load_db.load([path], "v1", dry_run=True, progress=lambda _msg: None)

    assert summary["records_read"] == 3
    assert summary["duplicates_collapsed"] == 1
    assert summary["rows_to_write"] == 2
    assert summary["rows_written"] == 0
    assert summary["figures_with_refs"] == 1
    assert summary["rows_in_table_after"] is None


def test_load_warns_when_no_row_has_an_embedding(tmp_path):
    path = _write_corpus(tmp_path, [_record()])
    messages = []

    summary = load_db.load([path], "v1", dry_run=True, progress=messages.append)

    assert summary["rows_with_embedding"] == 0
    assert any("lexical-only" in m for m in messages)


def test_load_notes_how_many_rows_carry_an_embedding(tmp_path):
    path = _write_corpus(tmp_path, [_record(id="1", embedding=[0.1]), _record(id="2")])
    messages = []

    summary = load_db.load([path], "v1", dry_run=True, progress=messages.append)

    assert summary["rows_with_embedding"] == 1
    assert any("1 carry an embedding" in m for m in messages)


def test_load_writes_commits_and_closes_the_session(tmp_path, monkeypatch):
    path = _write_corpus(tmp_path, [_record(id="1"), _record(id="2")])
    session = _FakeSession()
    monkeypatch.setattr(load_db, "SessionLocal", lambda: session)

    summary = load_db.load([path], "v1", progress=lambda _msg: None)

    assert summary["rows_written"] == 2
    assert summary["rows_in_table_after"] is not None
    assert session.committed
    assert session.closed
    assert not session.rolled_back


def test_load_with_truncate_clears_the_table_before_writing(tmp_path, monkeypatch):
    path = _write_corpus(tmp_path, [_record()])
    session = _FakeSession()
    monkeypatch.setattr(load_db, "SessionLocal", lambda: session)

    load_db.load([path], "v1", truncate=True, progress=lambda _msg: None)

    assert "DELETE FROM clause_chunks" in str(session.statements[0])


def test_load_rolls_back_and_closes_the_session_when_the_write_fails(tmp_path, monkeypatch):
    path = _write_corpus(tmp_path, [_record()])
    session = _FakeSession()
    session.fail_on_execute = True
    monkeypatch.setattr(load_db, "SessionLocal", lambda: session)

    with pytest.raises(RuntimeError, match="db exploded"):
        load_db.load([path], "v1", progress=lambda _msg: None)

    assert session.rolled_back
    assert session.closed
    assert not session.committed


# --- main (the CLI) -----------------------------------------------------


def test_main_returns_0_and_prints_a_summary_on_success(monkeypatch, tmp_path, capsys):
    summary = {
        "rows_written": 7, "rows_in_table_after": 9, "figures_with_refs": 2, "rows_with_embedding": 5,
    }
    monkeypatch.setattr(load_db, "load", lambda *a, **k: summary)

    code = load_db.main(["--files", str(tmp_path / "x.json")])

    out = capsys.readouterr().out
    assert code == 0
    assert "rows written : 7" in out
    assert "rows in table: 9" in out
    assert "with figures : 2" in out
    assert "with vectors : 5" in out


def test_main_omits_the_table_count_for_a_dry_run(monkeypatch, tmp_path, capsys):
    summary = {
        "rows_written": 0, "rows_in_table_after": None, "figures_with_refs": 0, "rows_with_embedding": 0,
    }
    monkeypatch.setattr(load_db, "load", lambda *a, **k: summary)

    assert load_db.main(["--files", str(tmp_path / "x.json"), "--dry-run"]) == 0
    assert "rows in table" not in capsys.readouterr().out


def test_main_passes_the_cli_flags_through_to_load(monkeypatch, tmp_path):
    seen = {}

    def _load(paths, **kwargs):
        seen["paths"] = paths
        seen.update(kwargs)
        return {"rows_written": 0, "rows_in_table_after": None, "figures_with_refs": 0, "rows_with_embedding": 0}

    monkeypatch.setattr(load_db, "load", _load)
    file = tmp_path / "x.json"

    load_db.main(["--files", str(file), "--dataset-version", "v9", "--truncate", "--dry-run"])

    assert seen["paths"] == [file]
    assert seen["dataset_version"] == "v9"
    assert seen["truncate"] is True
    assert seen["dry_run"] is True


def test_main_falls_back_to_the_default_paths_without_files(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(
        load_db, "load",
        lambda paths, **k: seen.setdefault("paths", paths)
        and {"rows_written": 0, "rows_in_table_after": None, "figures_with_refs": 0, "rows_with_embedding": 0},
    )

    load_db.main(["--out-dir", str(tmp_path)])

    assert seen["paths"] == load_db.default_paths(tmp_path)


def test_main_returns_1_for_a_load_error(monkeypatch, tmp_path, capsys):
    def _load(*a, **k):
        raise load_db.LoadError("file missing")

    monkeypatch.setattr(load_db, "load", _load)

    code = load_db.main(["--files", str(tmp_path / "x.json")])

    assert code == 1
    assert "Cannot load: file missing" in capsys.readouterr().err


def test_main_returns_2_for_an_unexpected_failure_and_points_at_database_url(monkeypatch, tmp_path, capsys):
    def _load(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(load_db, "load", _load)

    code = load_db.main(["--files", str(tmp_path / "x.json")])

    err = capsys.readouterr().err
    assert code == 2
    assert "Load failed: RuntimeError: connection refused" in err
    assert "DATABASE_URL" in err
