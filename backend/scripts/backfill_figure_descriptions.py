#!/usr/bin/env python3
"""
Put the generated figure descriptions into `clause_chunks` in Supabase.

The 270 figure rows carry only their caption as `text` -- "Section of a
typical tile roof" -- so the drawings are effectively invisible to retrieval:
the chunk embeds to almost nothing and none of the dimensions are searchable.
This writes the transcription in underneath the caption, and re-embeds the row
so dense search sees the new content.

    python scripts/backfill_figure_descriptions.py --dry-run   # report, write nothing
    python scripts/backfill_figure_descriptions.py --apply

Matching
--------
The descriptions are keyed by the PNG cropped out of the source PDF
("figure-10.2.15a.png"), and the database rows by heading
("Figure 10.2.15a: Typical enclosed stepped down shower construction"). The
join key is the **figure number** parsed from each side, scoped to the
document -- Volume Two and the Housing Provisions both contain a "Figure 1"
and they are different drawings, so an unscoped join would cross-contaminate.

Transport
---------
Goes through Supabase's PostgREST API rather than SQLAlchemy, because the
project's `DATABASE_URL` is still a placeholder -- the direct database host
does not resolve and nobody has supplied the session-pooler password. The
REST credentials in `frontend/.env` work today. If you later set a real
DATABASE_URL, a SQLAlchemy version of `update_row` would be a drop-in.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

OUTPUT_DIR = BACKEND_DIR / "app" / "ingest" / "output"
SOURCES = {
    "NCC 2025 Volume Two": OUTPUT_DIR / "vol2_image_descriptions.jsonl",
    "ABCB Housing Provisions": OUTPUT_DIR / "housing_image_descriptions.jsonl",
}

# "figure-10.2.15a.png" -> "10.2.15a";  "Figure H1D4a (explanatory): ..." -> "H1D4a"
_FILE_NUMBER = re.compile(r"^figure-(.+?)\.png$", re.IGNORECASE)
_HEADING_NUMBER = re.compile(
    r"^figure\s+([A-Za-z0-9]+(?:[.\-][A-Za-z0-9]+)*)", re.IGNORECASE
)


def number_from_filename(name: str) -> str | None:
    match = _FILE_NUMBER.match(name)
    return match.group(1) if match else None


def number_from_heading(heading: str | None) -> str | None:
    match = _HEADING_NUMBER.match((heading or "").strip())
    return match.group(1).rstrip(":") if match else None


def load_credentials() -> tuple[str, str]:
    env = (REPO_ROOT / "frontend" / ".env").read_text(encoding="utf-8")
    url = re.search(r"VITE_SUPABASE_URL=(\S+)", env)
    key = re.search(r"VITE_SUPABASE_PUBLISHABLE_KEY=(\S+)", env)
    if not url or not key:
        raise SystemExit("VITE_SUPABASE_URL / VITE_SUPABASE_PUBLISHABLE_KEY not in frontend/.env")
    return url.group(1).rstrip("/"), key.group(1)


def request(url: str, key: str, path: str, method="GET", body=None, extra=None):
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if extra:
        headers.update(extra)
    req = urllib.request.Request(
        f"{url}{path}", method=method, headers=headers,
        data=json.dumps(body).encode() if body is not None else None,
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        payload = response.read().decode()
        return response.status, json.loads(payload) if payload.strip() else None


def fetch_figure_rows(url: str, key: str) -> list[dict]:
    """Every figure chunk, paged (PostgREST caps a response at 1000 rows)."""
    rows, offset = [], 0
    while True:
        status, page = request(
            url, key,
            f"/rest/v1/clause_chunks?node_type=eq.figure"
            f"&select=id,clause_id,heading,doc,text&order=id&offset={offset}&limit=500",
        )
        if not page:
            break
        rows.extend(page)
        if len(page) < 500:
            break
        offset += len(page)
    return rows


def compose_text(heading: str | None, description: str) -> str:
    """Caption first, transcription beneath.

    Mirrors app/ingest/image_descriptions.figure_text so a row written here
    and a row written by a full re-ingest look the same. Caption first keeps
    lexical search on the figure number working.
    """
    title = (heading or "").strip()
    # The heading is "Figure 10.2.15a: Typical ..."; the original text was just
    # the title part. Keep the caption line whole -- it is what readers cite.
    parts = [p for p in (title, description.strip()) if p]
    return "\n\n".join(parts)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write to the database")
    parser.add_argument("--dry-run", action="store_true", help="report only (default)")
    parser.add_argument("--embed", action="store_true",
                        help="also recompute the row's embedding. Without this the row's "
                             "text changes but its vector still reflects the old caption-only "
                             "text, so dense search will not find the new content.")
    parser.add_argument("--limit", type=int, default=None, help="stop after N rows")
    args = parser.parse_args(argv)

    if not args.apply:
        args.dry_run = True

    url, key = load_credentials()

    # --- load the generated descriptions, keyed by (doc, figure number) ---
    descriptions: dict[tuple[str, str], dict] = {}
    for doc, path in SOURCES.items():
        if not path.exists():
            print(f"Missing {path} -- run scripts/describe_images.py first", file=sys.stderr)
            return 1
        count = 0
        for line in path.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            number = number_from_filename(record["image"])
            if not number or not record.get("description"):
                continue
            descriptions[(doc, number)] = record
            count += 1
        print(f"  loaded {count:4d} description(s) for {doc}")

    print(f"  {len(descriptions)} description(s) total")
    print()

    rows = fetch_figure_rows(url, key)
    print(f"  {len(rows)} figure row(s) in clause_chunks")

    matched, unmatched_rows, already = [], [], 0
    for row in rows:
        number = number_from_heading(row.get("heading"))
        record = descriptions.get((row.get("doc"), number)) if number else None
        if record is None:
            unmatched_rows.append(row)
            continue
        if "## Description" in (row.get("text") or ""):
            already += 1
            continue
        matched.append((row, record))

    unused = set(descriptions) - {
        (r.get("doc"), number_from_heading(r.get("heading"))) for r in rows
    }

    print(f"  matched          : {len(matched)}")
    print(f"  already described: {already}")
    print(f"  rows unmatched   : {len(unmatched_rows)}")
    for row in unmatched_rows[:8]:
        print(f"      {row.get('doc','?')[:24]:24s} {str(row.get('heading'))[:60]}")
    print(f"  descriptions unused: {len(unused)}")
    for key_ in sorted(unused)[:8]:
        print(f"      {key_[0][:24]:24s} Figure {key_[1]}")
    print()

    if args.limit:
        matched = matched[: args.limit]

    if not args.apply:
        print(f"Dry run -- nothing written. {len(matched)} row(s) would be updated.")
        if matched:
            row, record = matched[0]
            print()
            print("Example update:")
            print(f"  id      : {row['id']}")
            print(f"  heading : {row['heading']}")
            print(f"  before  : {row['text'][:80]!r}")
            print(f"  after   : {compose_text(row['heading'], record['description'])[:160]!r} ...")
        return 0

    embed_text = None
    if args.embed:
        from app.services.embedding import embed_text as _embed
        embed_text = _embed

    updated = failed = 0
    started = time.monotonic()
    for index, (row, record) in enumerate(matched, 1):
        payload = {"text": compose_text(row["heading"], record["description"])}
        if embed_text is not None:
            try:
                payload["embedding"] = str(embed_text(payload["text"], task_type="RETRIEVAL_DOCUMENT"))
            except Exception as exc:  # noqa: BLE001 - provider faults
                print(f"  [{index}/{len(matched)}] embed FAILED {row['heading'][:48]}: {exc}")
                failed += 1
                continue
        try:
            request(url, key, f"/rest/v1/clause_chunks?id=eq.{row['id']}",
                    method="PATCH", body=payload, extra={"Prefer": "return=minimal"})
            updated += 1
        except urllib.error.HTTPError as exc:
            print(f"  [{index}/{len(matched)}] write FAILED {row['heading'][:48]}: "
                  f"{exc.code} {exc.read().decode()[:120]}")
            failed += 1
            continue
        if index % 25 == 0 or index == len(matched):
            rate = index / max(time.monotonic() - started, 1e-6) * 60
            print(f"  [{index}/{len(matched)}] {updated} updated, {failed} failed ({rate:.0f}/min)")

    print()
    print(f"Done. {updated} row(s) updated, {failed} failed.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
