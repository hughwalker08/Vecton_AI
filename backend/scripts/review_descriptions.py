#!/usr/bin/env python3
"""
Manual review app for the generated NCC/ABCB figure descriptions.

Shows each figure next to its transcription and asks one question: is this
description right? A "correct" verdict is one keystroke; an "incorrect" one
has to say what is wrong, because a bare "incorrect" tells whoever fixes it
nothing.

    python scripts/review_descriptions.py --group a     # reviewer 1
    python scripts/review_descriptions.py --group b     # reviewer 2

Each opens a browser at http://127.0.0.1:8900 and writes results to
`data/review/group-<a|b>.json` after every single verdict -- there is no
"save" step to forget, and closing the tab loses nothing. Re-running resumes:
the app opens at the first figure that has no verdict yet.

Why a server rather than a plain file:// page
---------------------------------------------
The 270 figures are 39 MB, too much to inline, and a file:// page cannot
write to disk -- it could only offer a download the reviewer has to remember
to do, repeatedly, with no crash safety. This is ~60 lines of stdlib
http.server and removes that whole class of lost work.

The split
---------
All 270 figures sorted by (corpus, filename) and dealt alternately into two
groups: 135 each, and because it alternates rather than cuts in half, both
reviewers get the same mix of Volume Two and Housing Provisions figures
instead of one person getting every Volume Two drawing. The split is
deterministic, so re-running never reshuffles someone's workload.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

BACKEND_DIR = Path(__file__).resolve().parent.parent
APP_DIR = Path(__file__).resolve().parent / "review_app"
IMAGES_DIR = BACKEND_DIR / "data" / "images"
REVIEW_DIR = BACKEND_DIR / "data" / "review"
OUTPUT_DIR = BACKEND_DIR / "app" / "ingest" / "output"

CORPORA = {
    "vol2": ("NCC 2025 Volume Two", OUTPUT_DIR / "vol2_image_descriptions.jsonl"),
    "housing": ("ABCB Housing Provisions", OUTPUT_DIR / "housing_image_descriptions.jsonl"),
}
GROUPS = ("a", "b", "c")

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
}


def load_all_items() -> list[dict]:
    """Every figure that has both an image on disk and a description."""
    items: list[dict] = []
    missing_images = 0

    for corpus, (doc, path) in CORPORA.items():
        if not path.exists():
            raise SystemExit(
                f"{path} not found -- run scripts/describe_images.py first."
            )
        for line in path.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            name = record.get("image")
            if not name or not record.get("description"):
                continue
            if not (IMAGES_DIR / corpus / name).exists():
                missing_images += 1
                continue
            items.append(
                {
                    "key": f"{corpus}/{name}",
                    "corpus": corpus,
                    "doc": doc,
                    "file": name,
                    "image_url": f"images/{corpus}/{name}",
                    "caption": record.get("caption") or "",
                    "description": record["description"],
                    "model": (record.get("model") or "").replace("models/", ""),
                    "prompt_variant": record.get("prompt_variant"),
                    "chars": record.get("chars"),
                }
            )

    if missing_images:
        print(f"  ! {missing_images} description(s) had no image on disk and were skipped",
              file=sys.stderr)

    items.sort(key=lambda it: (it["corpus"], it["file"]))
    return items


def assignments_path() -> Path:
    return REVIEW_DIR / "assignments.json"


def review_path(group: str) -> Path:
    return REVIEW_DIR / f"group-{group}.json"


def load_pinned(valid_keys: set[str]) -> dict[str, str]:
    """Figure -> group, for every figure that already carries a verdict.

    Read from whatever `group-*.json` files are on this machine. A reviewed
    figure must never move: moving it would either lose the verdict or hand
    the same drawing to a second person.

    The review files are per-reviewer and are not committed, so this only
    sees the ones present locally -- `rebalance` warns about any group whose
    file is missing, because its verdicts cannot be honoured from here.
    """
    pinned: dict[str, str] = {}
    for path in sorted(REVIEW_DIR.glob("group-*.json")):
        group = path.stem.split("-", 1)[1]
        if group not in GROUPS:
            continue
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for key, entry in (state.get("results") or {}).items():
            if entry.get("verdict") and key in valid_keys:
                pinned[key] = group
    return pinned


def compute_assignments(items: list[dict], pinned: dict[str, str],
                        groups: tuple[str, ...]) -> dict[str, str]:
    """Spread every figure across `groups`, leaving reviewed ones where they are.

    Balanced per corpus rather than over the whole set: with 30 Volume Two
    and 240 Housing Provisions figures, dealing the combined list would let
    one reviewer end up with most of the Volume Two drawings. Each corpus is
    dealt separately so everyone sees roughly the same mix.

    Unreviewed figures go to whichever group is furthest below its share,
    with ties broken by group letter, so the result is deterministic -- the
    same inputs always produce the same assignment.
    """
    corpus_of = {it["key"]: it["corpus"] for it in items}
    assignments = {k: g for k, g in pinned.items() if k in corpus_of}

    for corpus in sorted({it["corpus"] for it in items}):
        keys = sorted(k for k, c in corpus_of.items() if c == corpus)
        held = {g: sum(1 for k in keys if assignments.get(k) == g) for g in groups}

        # Even shares, with any remainder going to the earliest groups.
        base, extra = divmod(len(keys), len(groups))
        target = {g: base + (1 if i < extra else 0) for i, g in enumerate(groups)}

        for key in keys:
            if key in assignments:
                continue
            # Largest shortfall first; ties by group order. Once every group
            # has met its target (possible when a group was already over it),
            # fall back to whoever holds the fewest.
            chosen = min(
                groups,
                key=lambda g: (-(target[g] - held[g]), groups.index(g)),
            )
            assignments[key] = chosen
            held[chosen] += 1

    return assignments


def load_assignments(items: list[dict]) -> dict[str, str]:
    """The stored assignment, extended if new figures have appeared.

    `assignments.json` is the shared source of truth and is committed, so all
    three reviewers agree on who has what. Regenerating it on the fly would
    let two machines disagree.
    """
    keys = {it["key"] for it in items}
    stored: dict[str, str] = {}
    path = assignments_path()
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        stored = {k: g for k, g in (data.get("assignments") or {}).items()
                  if k in keys and g in GROUPS}

    if len(stored) == len(keys):
        return stored

    # First run, or figures added since. Keep what is there, place the rest.
    pinned = dict(stored)
    pinned.update(load_pinned(keys))
    assignments = compute_assignments(items, pinned, GROUPS)
    write_assignments(items, assignments, note="auto-generated: no manifest, or new figures appeared")
    return assignments


def write_assignments(items: list[dict], assignments: dict[str, str], note: str = "") -> Path:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    counts: dict[str, dict[str, int]] = {}
    for it in items:
        group = assignments.get(it["key"])
        if group is None:
            continue
        bucket = counts.setdefault(group, {"total": 0})
        bucket["total"] += 1
        bucket[it["corpus"]] = bucket.get(it["corpus"], 0) + 1

    payload = {
        "groups": list(GROUPS),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": note,
        "total": len(items),
        "counts": {g: counts.get(g, {"total": 0}) for g in GROUPS},
        "assignments": dict(sorted(assignments.items())),
    }
    path = assignments_path()
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)
    return path


def group_items(items: list[dict], assignments: dict[str, str], group: str) -> list[dict]:
    return [it for it in items if assignments.get(it["key"]) == group]


def rebalance(items: list[dict]) -> int:
    """Recompute the split across all GROUPS, leaving reviewed figures put."""
    keys = {it["key"] for it in items}
    before = load_assignments(items) if assignments_path().exists() else {}
    pinned = load_pinned(keys)

    missing = [g for g in GROUPS if not review_path(g).exists()]
    assignments = compute_assignments(items, pinned, GROUPS)
    path = write_assignments(items, assignments, note=f"rebalanced across {len(GROUPS)} groups")

    print(f"\n  {len(items)} figures across {len(GROUPS)} groups")
    print(f"  {len(pinned)} already reviewed and pinned to their current group\n")
    print(f"    {'group':6s} {'figures':>8s} {'pinned':>7s} {'moved in':>9s}   corpus mix")
    for g in GROUPS:
        mine = [k for k, gg in assignments.items() if gg == g]
        held = sum(1 for k in mine if pinned.get(k) == g)
        moved = sum(1 for k in mine if before.get(k) not in (None, g))
        mix = {}
        for it in items:
            if assignments.get(it["key"]) == g:
                mix[it["corpus"]] = mix.get(it["corpus"], 0) + 1
        mix_text = ", ".join(f"{c} {n}" for c, n in sorted(mix.items()))
        print(f"    {g:6s} {len(mine):8d} {held:7d} {moved:9d}   {mix_text}")

    if missing:
        print(f"\n  ! No review file for group(s): {', '.join(missing)}")
        print("    Verdicts recorded on another machine cannot be seen from here, so")
        print("    they were NOT pinned. If that reviewer has started, copy their")
        print(f"    {REVIEW_DIR.name}/group-<x>.json here and re-run --rebalance.")

    print(f"\n  written: {path}")
    print("  Commit it so every reviewer works from the same split.\n")
    return 0


def load_review(group: str, group_items: list[dict], reviewer: str | None) -> dict:
    """Existing results for this group, or a fresh skeleton."""
    path = review_path(group)
    if path.exists():
        state = json.loads(path.read_text(encoding="utf-8"))
        state.setdefault("results", {})
    else:
        state = {
            "group": group,
            "reviewer": reviewer,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "updated_at": None,
            "results": {},
        }
    if reviewer:
        state["reviewer"] = reviewer
    state["total"] = len(group_items)
    return state


def write_review(group: str, state: dict) -> None:
    """Persist atomically: write a temp file, then replace.

    A half-written JSON file would cost the reviewer everything they had done
    so far, which is the one failure this tool must not have.
    """
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    results = state.get("results", {})
    state["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state["reviewed"] = sum(1 for r in results.values() if r.get("verdict"))
    state["correct"] = sum(1 for r in results.values() if r.get("verdict") == "correct")
    state["incorrect"] = sum(1 for r in results.values() if r.get("verdict") == "incorrect")

    path = review_path(group)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def build_handler(group: str, group_items: list[dict], state: dict):
    by_key = {it["key"]: it for it in group_items}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # keep the console for progress, not noise
            pass

        # ---- helpers -------------------------------------------------
        def _send(self, status, body: bytes, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status, payload):
            self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _file(self, path: Path):
            if not path.is_file():
                self._json(404, {"error": f"not found: {path.name}"})
                return
            self._send(200, path.read_bytes(),
                       _MIME.get(path.suffix.lower(), "application/octet-stream"))

        # ---- routes --------------------------------------------------
        def do_GET(self):
            route = unquote(urlparse(self.path).path)

            if route in ("/", "/index.html"):
                return self._file(APP_DIR / "index.html")

            if route == "/api/items":
                return self._json(200, {"group": group, "items": group_items})

            if route == "/api/review":
                with lock:
                    return self._json(200, state)

            if route.startswith("/images/"):
                parts = route[len("/images/"):].split("/")
                # Only the two known corpus folders, and no path traversal.
                if len(parts) != 2 or parts[0] not in CORPORA or "/" in parts[1] or ".." in parts[1]:
                    return self._json(400, {"error": "bad image path"})
                return self._file(IMAGES_DIR / parts[0] / parts[1])

            return self._json(404, {"error": "no such route"})

        def do_POST(self):
            route = unquote(urlparse(self.path).path)
            if route != "/api/review":
                return self._json(404, {"error": "no such route"})

            length = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                return self._json(400, {"error": f"bad JSON: {exc}"})

            key = payload.get("key")
            verdict = payload.get("verdict")
            issues = (payload.get("issues") or "").strip()

            if key not in by_key:
                return self._json(400, {"error": f"'{key}' is not in group {group}"})
            if verdict not in ("correct", "incorrect"):
                return self._json(400, {"error": "verdict must be 'correct' or 'incorrect'"})
            # Enforced here as well as in the browser: the whole point of an
            # "incorrect" verdict is the explanation that comes with it.
            if verdict == "incorrect" and not issues:
                return self._json(400, {"error": "an 'incorrect' verdict needs an explanation"})

            item = by_key[key]
            entry = {
                "verdict": verdict,
                "issues": issues,
                "caption": item["caption"],
                "corpus": item["corpus"],
                "doc": item["doc"],
                "model": item["model"],
                "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            with lock:
                state["results"][key] = entry
                write_review(group, state)
                done = state["reviewed"]

            print(f"  {done:3d}/{len(group_items)}  {verdict:9s} {key}"
                  + (f"  -- {issues[:60]}" if issues else ""))
            return self._json(200, {"entry": entry, "reviewed": done})

    return Handler


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--group", choices=GROUPS, help="which share to review")
    parser.add_argument("--reviewer", default=None, help="name recorded in the output file")
    parser.add_argument("--port", type=int, default=8900)
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser")
    parser.add_argument("--summary", action="store_true",
                        help="print every group's progress and exit, without serving")
    parser.add_argument("--rebalance", action="store_true",
                        help="recompute the split across all groups and rewrite "
                             "data/review/assignments.json. Figures that already have a "
                             "verdict stay in the group that reviewed them.")
    args = parser.parse_args(argv)

    items = load_all_items()

    if args.rebalance:
        return rebalance(items)

    assignments = load_assignments(items)

    if args.summary:
        print(f"\n{len(items)} figures total across {len(GROUPS)} groups\n")
        for name in GROUPS:
            mine = group_items(items, assignments, name)
            path = review_path(name)
            state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            results = state.get("results", {})
            done = sum(1 for r in results.values() if r.get("verdict"))
            bad = sum(1 for r in results.values() if r.get("verdict") == "incorrect")
            who = state.get("reviewer") or "unassigned"
            print(f"  group {name}: {len(mine)} figures, {done} reviewed, "
                  f"{bad} incorrect, reviewer: {who}")
            print(f"            {path}" + ("" if path.exists() else "  (not started)"))
        print()
        return 0

    if not args.group:
        parser.error("--group is required unless using --summary or --rebalance")

    mine = group_items(items, assignments, args.group)
    if not mine:
        print(f"Group {args.group} has no figures assigned. Run --rebalance first.",
              file=sys.stderr)
        return 1
    state = load_review(args.group, mine, args.reviewer)
    write_review(args.group, state)   # make the file exist immediately

    handler = build_handler(args.group, mine, state)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    url = f"http://127.0.0.1:{args.port}/"

    done = state.get("reviewed", 0)
    print()
    print(f"  Figure review - group {args.group.upper()}")
    print(f"    figures : {len(mine)}  ({done} already reviewed)")
    print(f"    saving  : {review_path(args.group)}")
    print(f"    open    : {url}")
    print()
    print("  Keys: 1=correct  2=incorrect  left/right=navigate  U=next unreviewed  Ctrl+Enter=save note")
    print("  Ctrl+C to stop. Every verdict is written to disk as you go.")
    print()

    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped.")
    finally:
        server.server_close()
        with_state = state.get("reviewed", 0)
        print(f"  {with_state}/{len(mine)} reviewed -> {review_path(args.group)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
