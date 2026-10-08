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
GROUPS = ("a", "b")

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


def split_groups(items: list[dict]) -> dict[str, list[dict]]:
    """Deal items alternately into the two groups.

    Alternating rather than halving keeps each reviewer's mix of corpora the
    same; a straight cut would hand one person every Volume Two figure.
    """
    return {
        "a": [it for i, it in enumerate(items) if i % 2 == 0],
        "b": [it for i, it in enumerate(items) if i % 2 == 1],
    }


def review_path(group: str) -> Path:
    return REVIEW_DIR / f"group-{group}.json"


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
    parser.add_argument("--group", choices=GROUPS, required=True, help="which half to review")
    parser.add_argument("--reviewer", default=None, help="name recorded in the output file")
    parser.add_argument("--port", type=int, default=8900)
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser")
    parser.add_argument("--summary", action="store_true",
                        help="print both groups' progress and exit, without serving")
    args = parser.parse_args(argv)

    items = load_all_items()
    groups = split_groups(items)

    if args.summary:
        print(f"\n{len(items)} figures total\n")
        for name in GROUPS:
            path = review_path(name)
            state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            results = state.get("results", {})
            done = sum(1 for r in results.values() if r.get("verdict"))
            bad = sum(1 for r in results.values() if r.get("verdict") == "incorrect")
            who = state.get("reviewer") or "unassigned"
            print(f"  group {name}: {len(groups[name])} figures, {done} reviewed, "
                  f"{bad} incorrect, reviewer: {who}")
            print(f"            {path}" + ("" if path.exists() else "  (not started)"))
        print()
        return 0

    group_items = groups[args.group]
    state = load_review(args.group, group_items, args.reviewer)
    write_review(args.group, state)   # make the file exist immediately

    handler = build_handler(args.group, group_items, state)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    url = f"http://127.0.0.1:{args.port}/"

    done = state.get("reviewed", 0)
    print()
    print(f"  Figure review - group {args.group.upper()}")
    print(f"    figures : {len(group_items)}  ({done} already reviewed)")
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
        print(f"  {with_state}/{len(group_items)} reviewed -> {review_path(args.group)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
