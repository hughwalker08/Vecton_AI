"""
One-off data fix: restore the 73 glossary definitions that were truncated at
ingest (the parser read only the first <content> block, dropping the (a)/(b)
list -- see app/ingest/glossary_parser.py).

Updates only `text` and `standard_refs` of glossary rows in clause_chunks, and
only where the stored text is an exact truncated prefix of the fixed text, so a
row someone has corrected by hand (e.g. "Hours of operation") is never
overwritten, and re-running after the fix is applied changes nothing. The old
values are saved to a JSON file first so the change can be reverted.

    cd backend && source .venv/bin/activate
    python scripts/fix_glossary_rows.py            # dry run: report only
    python scripts/fix_glossary_rows.py --apply    # write (all-or-nothing)

Restart the API afterwards: services/glossary.py caches definitions per process.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal  # noqa: E402
from app.models.clause_chunk import ClauseChunk  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parents[1] / "app" / "ingest" / "output"
BACKUP = REPO_ROOT / "backup-glossary-before-fix.json"


def glossary(records):
    return {r["id"]: r for r in records if r["node_type"] == "glossary"}


def main(apply: bool) -> int:
    new = {}
    for stem in ("ncc_volume_two_chunks", "abcb_housing_provisions_chunks"):
        for i, r in glossary(json.loads((OUT / f"{stem}.json").read_text(encoding="utf-8"))).items():
            new.setdefault(i, r)

    session = SessionLocal()
    try:
        rows = {
            str(r.id): r
            for r in session.query(ClauseChunk).filter(ClauseChunk.node_type == "glossary").all()
        }
        todo = [
            i for i, row in rows.items()
            if i in new and row.text != new[i]["text"] and new[i]["text"].startswith(row.text)
        ]
        differ = [i for i, row in rows.items() if i in new and row.text != new[i]["text"] and i not in todo]
        print(f"{len(todo)} glossary rows hold a truncated definition and would be updated")
        print(f"left alone (differ but are not a truncation): {[new[i]['heading'] for i in differ] or 'none'}")
        if not apply:
            print("Dry run only. Re-run with --apply to write.")
            return 0
        BACKUP.write_text(
            json.dumps(
                [{"id": i, "heading": new[i]["heading"], "old_text": rows[i].text, "old_standard_refs": rows[i].standard_refs} for i in todo],
                indent=2, default=str,
            ),
            encoding="utf-8",
        )
        print(f"Backup of old values written to {BACKUP}")
        updated = 0
        for i in todo:
            updated += (
                session.query(ClauseChunk)
                .filter(ClauseChunk.id == i, ClauseChunk.text == rows[i].text)
                .update({"text": new[i]["text"], "standard_refs": new[i].get("external_refs") or []}, synchronize_session=False)
            )
        if updated != len(todo):
            session.rollback()
            print(f"Rolled back: expected {len(todo)} updates, got {updated}")
            return 1
        session.commit()
        print(f"Updated {updated} rows.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main("--apply" in sys.argv))
