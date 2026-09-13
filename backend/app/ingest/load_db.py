"""
Load the ingest pipeline's chunk JSON into the `clause_chunks` table.

`app.ingest.cli` parses the corpus to local JSON and stops there. This is the
step that puts those chunks in Postgres, where retrieval can reach them.

    python -m app.ingest.load_db                    # load app/ingest/output/*.json
    python -m app.ingest.load_db --dry-run          # validate + report, touch nothing
    python -m app.ingest.load_db --truncate         # clear the table first

Embeddings come along for the ride. `scripts/embed_chunks.py` writes
`<name>_chunks.embedded.json` next to the plain `<name>_chunks.json`; this
loader prefers the embedded file when it exists, so the `embedding` column is
populated in the same pass and `retrieval.hybrid_search`'s dense CTE has
vectors to search. Without it that CTE matches nothing (it filters on
`embedding IS NOT NULL`) and retrieval silently degrades to lexical-only.

Two things about the source data drive the design:

  * **508 ids appear in both corpus files.** The glossary (493 entries) and a
    handful of shared tables and figures are emitted into each corpus's JSON.
    They are the same node, so the loader de-duplicates by id rather than
    treating it as corruption. 507 of the 508 pairs are byte-identical; the
    one that differs is a glossary entry whose Volume Two copy carries a
    tracked-change artefact ("greater thanat least"), so **last wins** is the
    better default -- it keeps the Housing Provisions' clean copy.

  * De-duplication must happen in Python, not just via ON CONFLICT. Postgres
    rejects a single INSERT ... ON CONFLICT DO UPDATE that touches the same
    row twice ("cannot affect row a second time"), so a batch containing both
    copies of a glossary entry would error out.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.db.session import SessionLocal
from app.models.clause_chunk import ClauseChunk

DEFAULT_OUT_DIR = Path(__file__).parent / "output"
CORPUS_STEMS = ("ncc_volume_two_chunks", "abcb_housing_provisions_chunks")


def default_paths(out_dir: Path) -> list[Path]:
    """One path per corpus, preferring the embedded file when it exists.

    scripts/embed_chunks.py writes `<stem>.embedded.json` alongside
    `<stem>.json`; the embedded file is a superset (every original field plus
    `embedding`), so preferring it is always the better choice.
    """
    paths = []
    for stem in CORPUS_STEMS:
        embedded = out_dir / f"{stem}.embedded.json"
        paths.append(embedded if embedded.exists() else out_dir / f"{stem}.json")
    return paths

# Columns the loader writes. `embedding` is left NULL (see module docstring)
# and `text_tsv` is a generated column -- writing to it is an error.
LOADED_COLUMNS = (
    "id", "node_type", "clause_id", "heading", "doc", "hierarchy", "text",
    "defined_terms", "cross_refs", "internal_refs", "standard_refs", "image_refs",
    "building_classes", "jurisdictions", "climate_zones", "applicability_note",
    "dataset_version", "retrieved_at", "embedding",
)

# NULL on an applicability column means "no restriction on this axis" (see
# models/clause_chunk.py). Ingest writes [] for the same thing, so normalise,
# or a filter like `WHERE jurisdictions IS NULL OR 'NSW' = ANY(jurisdictions)`
# would quietly exclude every unrestricted clause.
APPLICABILITY_COLUMNS = ("building_classes", "jurisdictions", "climate_zones")


class LoadError(RuntimeError):
    """Raised when the source JSON cannot be loaded."""


def to_row(record: dict, dataset_version: str, retrieved_at: datetime) -> dict:
    """Map one ingest JSON record onto `clause_chunks` columns."""
    row = {
        "id": record["id"],
        "node_type": record.get("node_type") or "clause",
        "clause_id": record.get("clause_id"),
        "heading": record.get("heading"),
        "doc": record.get("doc"),
        "hierarchy": record.get("hierarchy") or [],
        # text is NOT NULL. Two chunks (a captionless figure and a table) carry
        # an empty string, which is fine -- but None would fail the constraint.
        "text": record.get("text") or "",
        "defined_terms": record.get("defined_terms") or [],
        "cross_refs": record.get("cross_refs") or [],
        "internal_refs": record.get("internal_refs") or [],
        # Ingest calls this external_refs; the column is standard_refs.
        "standard_refs": record.get("external_refs") or [],
        "image_refs": record.get("image_refs") or [],
        "building_classes": record.get("building_classes"),
        "jurisdictions": record.get("jurisdictions"),
        "climate_zones": record.get("climate_zones"),
        "applicability_note": record.get("applicability_note"),
        "dataset_version": dataset_version,
        "retrieved_at": retrieved_at,
        # Present only in a *.embedded.json; None leaves the column NULL, which
        # the dense CTE filters out rather than erroring.
        "embedding": record.get("embedding"),
    }
    for column in APPLICABILITY_COLUMNS:
        if not row[column]:
            row[column] = None
    return row


def read_records(paths: list[Path]) -> list[dict]:
    """Read every chunk record from the given JSON files."""
    records: list[dict] = []
    for path in paths:
        if not path.exists():
            raise LoadError(
                f"{path} not found. Run `python -m app.ingest.cli` first to parse "
                f"the corpus into JSON."
            )
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise LoadError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(data, list):
            raise LoadError(f"{path} should contain a list of chunks")
        records.extend(data)
    return records


def deduplicate(rows: list[dict]) -> tuple[list[dict], int]:
    """Collapse rows sharing an id, last one winning. Returns (rows, dropped)."""
    by_id: dict[str, dict] = {}
    for row in rows:
        by_id[row["id"]] = row
    return list(by_id.values()), len(rows) - len(by_id)


def upsert(session, rows: list[dict], batch_size: int = 500, progress=print) -> int:
    """Insert rows, updating any that already exist. Returns rows written.

    Upsert rather than plain insert so a re-run after a corpus re-parse
    refreshes the table in place instead of failing on the primary key.
    """
    written = 0
    updatable = [c for c in LOADED_COLUMNS if c != "id"]

    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        statement = insert(ClauseChunk.__table__).values(batch)
        statement = statement.on_conflict_do_update(
            index_elements=["id"],
            set_={c: statement.excluded[c] for c in updatable},
        )
        session.execute(statement)
        written += len(batch)
        progress(f"  {written}/{len(rows)} rows")

    return written


def load(
    paths: list[Path],
    dataset_version: str,
    truncate: bool = False,
    dry_run: bool = False,
    progress=print,
) -> dict:
    """Read the JSON, map it, and write it to clause_chunks."""
    records = read_records(paths)
    retrieved_at = datetime.now(timezone.utc)
    rows = [to_row(r, dataset_version, retrieved_at) for r in records]
    rows, duplicates = deduplicate(rows)

    summary = {
        "records_read": len(records),
        "duplicates_collapsed": duplicates,
        "rows_to_write": len(rows),
        "rows_written": 0,
        "figures_with_refs": sum(1 for r in rows if r["image_refs"]),
        "rows_with_embedding": sum(1 for r in rows if r["embedding"]),
        "rows_in_table_after": None,
    }

    progress(f"  read {summary['records_read']} records from {len(paths)} file(s)")
    if duplicates:
        progress(f"  collapsed {duplicates} shared id(s) -- glossary/tables in both corpora")
    embedded = summary["rows_with_embedding"]
    progress(f"  {summary['rows_to_write']} unique rows to write")
    if embedded:
        progress(f"  {embedded} carry an embedding (dense retrieval will work)")
    else:
        progress("  no embeddings found -- run scripts/embed_chunks.py first, "
                 "or retrieval stays lexical-only")

    if dry_run:
        progress("  dry run -- nothing written")
        return summary

    session = SessionLocal()
    try:
        if truncate:
            progress("  truncating clause_chunks")
            session.execute(ClauseChunk.__table__.delete())
        summary["rows_written"] = upsert(session, rows, progress=progress)
        session.commit()
        summary["rows_in_table_after"] = session.execute(
            select(func.count()).select_from(ClauseChunk.__table__)
        ).scalar_one()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    parser.add_argument(
        "--out-dir", type=Path, default=DEFAULT_OUT_DIR,
        help=f"directory holding the ingest JSON (default: {DEFAULT_OUT_DIR}). "
             f"Uses <corpus>.embedded.json when present, else <corpus>.json.",
    )
    parser.add_argument(
        "--files", type=Path, nargs="*", default=None,
        help="explicit JSON files, instead of the two defaults under --out-dir",
    )
    parser.add_argument(
        "--dataset-version", default="ncc-2025-v1.2",
        help="stamped on every row for provenance (default: ncc-2025-v1.2)",
    )
    parser.add_argument("--truncate", action="store_true",
                        help="delete every existing row before loading")
    parser.add_argument("--dry-run", action="store_true",
                        help="read and validate the JSON, write nothing")
    args = parser.parse_args(argv)

    paths = args.files or default_paths(args.out_dir)

    print()
    print("Loading corpus chunks into clause_chunks")
    for path in paths:
        print(f"  source: {path}")
    print()

    try:
        summary = load(
            paths,
            dataset_version=args.dataset_version,
            truncate=args.truncate,
            dry_run=args.dry_run,
        )
    except LoadError as exc:
        print(f"Cannot load: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - DB connectivity, constraints, etc.
        print(f"Load failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("Check DATABASE_URL in backend/.env and that `alembic upgrade head` has run.",
              file=sys.stderr)
        return 2

    print()
    print("Done.")
    print(f"  rows written : {summary['rows_written']}")
    if summary["rows_in_table_after"] is not None:
        print(f"  rows in table: {summary['rows_in_table_after']}")
    print(f"  with figures : {summary['figures_with_refs']}")
    print(f"  with vectors : {summary['rows_with_embedding']}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
