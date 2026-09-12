#!/usr/bin/env python3
"""
Embed every ingest chunk with Gemini and write the vectors back into the chunk
records, ready to load into the database in one pass.

For each input file (the two ingest outputs by default) this produces:

    <name>_chunks.json                     input, untouched
    <name>_chunks.embedded.json            output: every chunk + an "embedding"
    embeddings/<name>_chunks.jsonl         append-only progress log (resume state)

How the vector is stored
------------------------
Each chunk in the .embedded.json gets a new key:

    "embedding": [0.0123, -0.0456, ...]    # <DIM> floats, unit-norm
    "embedding_model": "gemini-embedding-2"
    "embedding_dim": 768

That is the "how it's meant to be done" bit: the vector rides along with the
chunk, so the DB loader just reads this file and inserts rows.

Resuming
--------
Progress is appended to embeddings/<name>_chunks.jsonl after every batch and
flushed immediately. Ctrl-C stops after the current batch (or loses only the
in-flight batch if it is mid-request). Re-running skips every chunk already in
the progress log -- the model is never called twice for the same chunk.

Running out of quota
--------------------
Set one key as GEMINI_API_KEY or several as GEMINI_API_KEYS=key1,key2,key3
(env var or backend/.env). On a 429 the script waits out a short per-minute
limit; on a long / repeated 429 (daily quota) it rotates to the next key. When
every key is exhausted it writes the merged output and exits 3 -- re-run later
(or with more keys) to finish.

Usage
-----
    python scripts/embed_chunks.py                     # both ingest files
    python scripts/embed_chunks.py --file app/ingest/output/ncc_volume_two_chunks.json
    python scripts/embed_chunks.py --with-heading      # embed "heading\n\ntext"
    python scripts/embed_chunks.py --rpm 90 --batch-size 20
    python scripts/embed_chunks.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BACKEND_DIR / "app" / "ingest" / "output"
DEFAULT_FILES = [
    OUTPUT_DIR / "ncc_volume_two_chunks.json",
    OUTPUT_DIR / "abcb_housing_provisions_chunks.json",
]

DEFAULT_MODEL = "gemini-embedding-2"
DEFAULT_DIM = 768          # must match the pgvector column / migration
DEFAULT_RPM = 90           # free tier is 100 requests/min; stay just under
DEFAULT_BATCH_SIZE = 20    # chunks per embed_content call

# A single 429 whose "retry in Ns" exceeds this is treated as a daily-quota
# exhaustion -> rotate to the next key rather than sleeping it out.
LONG_BACKOFF_THRESHOLD = 120.0
MAX_RETRIES_PER_BATCH = 6

EXIT_OK = 0
EXIT_INCOMPLETE = 3


# --------------------------------------------------------------------------
# tiny colour helpers (match scripts/describe_images.py)
# --------------------------------------------------------------------------

_COLOUR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOUR else text


def dim(t: str) -> str: return _c("2", t)
def bold(t: str) -> str: return _c("1", t)
def green(t: str) -> str: return _c("32", t)
def yellow(t: str) -> str: return _c("33", t)
def red(t: str) -> str: return _c("31", t)
def cyan(t: str) -> str: return _c("36", t)


# --------------------------------------------------------------------------
# API keys
# --------------------------------------------------------------------------

def load_keys() -> list[str]:
    """Every Gemini key we can use, in order. GEMINI_API_KEYS (comma-separated)
    wins over GEMINI_API_KEY; both env vars and backend/.env are consulted."""
    values: dict[str, str] = {}
    for name in ("GEMINI_API_KEYS", "GEMINI_API_KEY"):
        if os.environ.get(name):
            values[name] = os.environ[name]
    env_path = BACKEND_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            name, _, val = line.partition("=")
            name = name.strip()
            if name in ("GEMINI_API_KEYS", "GEMINI_API_KEY") and name not in values:
                values[name] = val.strip().strip("'\"")

    raw = values.get("GEMINI_API_KEYS") or values.get("GEMINI_API_KEY") or ""
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise SystemExit(
            "No API key found. Set GEMINI_API_KEY=... (or GEMINI_API_KEYS=k1,k2) "
            "in backend/.env or the environment."
        )
    # de-dupe, keep order
    seen: set[str] = set()
    return [k for k in keys if not (k in seen or seen.add(k))]


class KeyRing:
    """Holds the keys and which one is active. Rotating past the last raises."""

    def __init__(self, keys: list[str]):
        self._keys = keys
        self._i = 0
        self._configure()

    def _configure(self) -> None:
        import google.generativeai as genai
        genai.configure(api_key=self._keys[self._i])

    @property
    def label(self) -> str:
        return f"key {self._i + 1}/{len(self._keys)} (…{self._keys[self._i][-4:]})"

    def rotate(self) -> bool:
        """Move to the next key. Returns False if there isn't one."""
        if self._i + 1 >= len(self._keys):
            return False
        self._i += 1
        self._configure()
        return True


# --------------------------------------------------------------------------
# quota / error classification
# --------------------------------------------------------------------------

def retry_delay_seconds(exc: Exception) -> float | None:
    """Pull "Please retry in 19.5s" / retry_delay { seconds: 20 } out of a 429."""
    import re
    blob = str(exc)
    m = re.search(r"retry in\s+([\d.]+)", blob, re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", blob)
    if m:
        return float(m.group(1))
    return None


class QuotaExhausted(RuntimeError):
    """Every key has hit its quota; the run cannot continue right now."""


# --------------------------------------------------------------------------
# rate limiter
# --------------------------------------------------------------------------

class RateLimiter:
    """Spreads requests so we stay under `rpm` calls per minute. Each item in a
    batch is counted as one request (the free-tier metric counts them that way)."""

    def __init__(self, rpm: int):
        self._interval = 60.0 / max(1, rpm)
        self._next = time.monotonic()

    def wait_for(self, n_items: int) -> None:
        now = time.monotonic()
        if now < self._next:
            time.sleep(self._next - now)
            now = self._next
        self._next = now + n_items * self._interval


# --------------------------------------------------------------------------
# embedding
# --------------------------------------------------------------------------

def embed_batch(texts: list[str], model: str, out_dim: int, keyring: KeyRing,
                limiter: RateLimiter) -> list[list[float]]:
    """Embed a batch, handling rate limits, transient errors and key rotation.
    Raises QuotaExhausted when no key can serve the request."""
    import google.generativeai as genai
    from google.api_core.exceptions import (
        Aborted, DeadlineExceeded, InternalServerError, ResourceExhausted,
        ServiceUnavailable, TooManyRequests,
    )
    transient = (ServiceUnavailable, InternalServerError, DeadlineExceeded, Aborted)
    model_id = model if model.startswith("models/") else f"models/{model}"

    attempt = 0
    while True:
        attempt += 1
        limiter.wait_for(len(texts))
        try:
            resp = genai.embed_content(
                model=model_id,
                content=texts,
                task_type="retrieval_document",
                output_dimensionality=out_dim,
            )
            vectors = resp["embedding"]
            # single-item batches come back as a bare vector
            if vectors and isinstance(vectors[0], (int, float)):
                vectors = [vectors]
            return vectors

        except (ResourceExhausted, TooManyRequests) as exc:
            delay = retry_delay_seconds(exc)
            if delay is not None and delay <= LONG_BACKOFF_THRESHOLD and attempt <= MAX_RETRIES_PER_BATCH:
                wait = delay + random.uniform(1, 3)
                print(dim(f"    429 on {keyring.label} — waiting {wait:.0f}s (per-minute limit)"))
                time.sleep(wait)
                continue
            # long delay, or we've retried enough: this key is spent for now.
            print(yellow(f"    {keyring.label} quota exhausted"
                         + (f" (retry-in {delay:.0f}s)" if delay else "")))
            if keyring.rotate():
                print(cyan(f"    → switched to {keyring.label}"))
                attempt = 0
                continue
            raise QuotaExhausted("all keys exhausted") from exc

        except transient as exc:
            if attempt > MAX_RETRIES_PER_BATCH:
                raise
            wait = min(60.0, 2.0 ** attempt) + random.uniform(0, 1)
            print(dim(f"    {type(exc).__name__} — retry {attempt} in {wait:.0f}s"))
            time.sleep(wait)


# --------------------------------------------------------------------------
# per-file progress log
# --------------------------------------------------------------------------

def check_meta(progress_path: Path, args) -> Path:
    """Guard against resuming a log that was built with different settings
    (a different model / dim / content mode would mix incompatible vectors)."""
    meta_path = progress_path.with_suffix(".meta.json")
    current = {"model": args.model, "dim": args.dim, "with_heading": bool(args.with_heading)}
    if meta_path.exists():
        previous = json.loads(meta_path.read_text(encoding="utf-8"))
        if previous != current:
            raise SystemExit(
                f"{progress_path.name} was started with {previous} but you asked for "
                f"{current}.\nDelete {progress_path.parent}/{progress_path.stem}.* to start over, "
                f"or re-run with the original settings."
            )
    elif not args.dry_run:
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return meta_path


def load_done(progress_path: Path) -> dict[str, list[float]]:
    """chunk id -> vector, from a previous run."""
    done: dict[str, list[float]] = {}
    if not progress_path.exists():
        return done
    with progress_path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                done[rec["id"]] = rec["embedding"]
            except (json.JSONDecodeError, KeyError):
                print(yellow(f"  ! skipping malformed line {line_no} in {progress_path.name}"))
    return done


def load_done_from_embedded(out_path: Path, args) -> dict[str, list[float]]:
    """chunk id -> vector, recovered from a shared <name>.embedded.json.

    The .embedded.json is what gets committed and passed between team members;
    the .jsonl progress log is local and gitignored. So on a fresh clone this is
    the only record of what has already been embedded -- without it the script
    would re-embed (and re-pay for) every chunk.
    """
    done: dict[str, list[float]] = {}
    if not out_path.exists():
        return done
    chunks = json.loads(out_path.read_text(encoding="utf-8"))
    for chunk in chunks:
        vec = chunk.get("embedding")
        if not vec:
            continue
        model = chunk.get("embedding_model")
        edim = chunk.get("embedding_dim")
        if (model and model != args.model) or (edim and edim != args.dim):
            raise SystemExit(
                f"{out_path.name} already holds {model} @ {edim}-dim vectors, but you "
                f"asked for {args.model} @ {args.dim}. Use matching settings, or delete "
                f"{out_path.name} (and output/embeddings/{out_path.stem.replace('.embedded','')}.*) "
                f"to start over."
            )
        done[chunk["id"]] = vec
    return done


def content_for(chunk: dict, with_heading: bool) -> str:
    text = chunk.get("text") or ""
    heading = chunk.get("heading") or ""
    return f"{heading}\n\n{text}" if (with_heading and heading) else text


def write_embedded(input_path: Path, out_path: Path, vectors: dict[str, list[float]],
                   model: str, out_dim: int) -> int:
    """Merge vectors into the chunk records and write <name>.embedded.json.
    Written atomically so an interrupt can't leave a half file."""
    chunks = json.loads(input_path.read_text(encoding="utf-8"))
    n = 0
    for chunk in chunks:
        vec = vectors.get(chunk.get("id"))
        if vec is None:
            continue
        chunk["embedding"] = vec
        chunk["embedding_model"] = model
        chunk["embedding_dim"] = out_dim
        n += 1
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    tmp.replace(out_path)
    return n


# --------------------------------------------------------------------------
# per-file driver
# --------------------------------------------------------------------------

def process_file(input_path: Path, args, keyring: KeyRing, limiter: RateLimiter) -> tuple[int, int, bool]:
    """Returns (embedded_this_run, total_chunks, complete)."""
    stem = input_path.stem  # e.g. "ncc_volume_two_chunks"
    progress_path = input_path.parent / "embeddings" / f"{stem}.jsonl"
    out_path = input_path.parent / f"{stem}.embedded.json"
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    check_meta(progress_path, args)

    chunks = json.loads(input_path.read_text(encoding="utf-8"))
    done = load_done(progress_path)

    # Recover progress from a shared .embedded.json (see load_done_from_embedded).
    from_shared = load_done_from_embedded(out_path, args)
    recovered = 0
    if from_shared and not args.dry_run:
        with progress_path.open("a", encoding="utf-8") as fh:
            for cid, vec in from_shared.items():
                if cid not in done:
                    done[cid] = vec
                    fh.write(json.dumps({"id": cid, "embedding": vec}) + "\n")
                    recovered += 1
    else:
        for cid, vec in from_shared.items():
            done.setdefault(cid, vec)

    todo = [c for c in chunks
            if c.get("id") not in done and content_for(c, args.with_heading).strip()]
    skipped_empty = sum(1 for c in chunks if not content_for(c, args.with_heading).strip())
    full_todo_count = len(todo)

    print()
    print(bold(f"{input_path.name}"))
    print(f"  chunks        : {len(chunks)}")
    print(f"  already done  : {len(done)}"
          + (dim(f"  ({recovered} recovered from {out_path.name})") if recovered else ""))
    if skipped_empty:
        print(f"  no text       : {skipped_empty}  (skipped)")
    if args.limit is not None:
        todo = todo[:args.limit]
    print(f"  to embed      : {bold(str(len(todo)))}"
          + (dim(f"  (limited to {args.limit})") if args.limit is not None else ""))

    if args.dry_run:
        print(dim(f"  dry run — would write {out_path.name} + {progress_path.name}"))
        return 0, len(chunks), len(todo) == 0

    if not todo:
        # still (re)write the merged file so it reflects the full progress log
        if done:
            written = write_embedded(input_path, out_path, done, args.model, args.dim)
            print(green(f"  nothing to do — {written} vectors in {out_path.name}"))
        return 0, len(chunks), True

    embedded = 0
    complete = False
    started = time.monotonic()
    progress_fh = progress_path.open("a", encoding="utf-8")
    try:
        for i in range(0, len(todo), args.batch_size):
            batch = todo[i:i + args.batch_size]
            texts = [content_for(c, args.with_heading) for c in batch]

            vectors = embed_batch(texts, args.model, args.dim, keyring, limiter)
            if len(vectors) != len(batch):
                raise RuntimeError(
                    f"asked for {len(batch)} vectors, got {len(vectors)}"
                )

            for chunk, vec in zip(batch, vectors):
                vec = [round(float(x), 7) for x in vec]
                done[chunk["id"]] = vec
                progress_fh.write(json.dumps({"id": chunk["id"], "embedding": vec}) + "\n")
            progress_fh.flush()
            os.fsync(progress_fh.fileno())
            embedded += len(batch)

            elapsed = time.monotonic() - started
            rate = embedded / elapsed * 60 if elapsed else 0
            remaining = (len(todo) - embedded) / rate * 60 if rate else 0
            print(f"  {dim(f'[{embedded}/{len(todo)}]')} "
                  f"{green('embedded')} {batch[-1].get('clause_id') or batch[-1]['id'][:8]} "
                  f"{dim(f'· {rate:.0f}/min · ~{remaining/60:.0f} min left · {keyring.label}')}")

            if embedded % (args.batch_size * 20) == 0:
                write_embedded(input_path, out_path, done, args.model, args.dim)

        complete = (len(todo) == full_todo_count)
        if not complete:
            print(dim(f"  --limit reached; {full_todo_count - len(todo)} chunks still to embed"))

    except KeyboardInterrupt:
        print()
        print(yellow(f"  interrupted — {embedded} embedded this run, progress saved"))
    except QuotaExhausted:
        print()
        print(yellow(f"  stopping — every key is out of quota "
                     f"({embedded} embedded this run)"))
    finally:
        progress_fh.close()
        written = write_embedded(input_path, out_path, done, args.model, args.dim)
        print(dim(f"  wrote {written}/{len(chunks)} vectors → {out_path.name}"))

    return embedded, len(chunks), complete


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--file", type=Path, action="append", dest="files",
                   help="an ingest output JSON to embed (repeatable; default: both)")
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"embedding model (default: {DEFAULT_MODEL})")
    p.add_argument("--dim", type=int, default=DEFAULT_DIM,
                   help=f"output dimensionality (default: {DEFAULT_DIM})")
    p.add_argument("--with-heading", action="store_true",
                   help="embed 'heading\\n\\ntext' instead of the chunk text alone")
    p.add_argument("--rpm", type=int, default=DEFAULT_RPM,
                   help=f"target requests/min, counting batch items (default: {DEFAULT_RPM})")
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                   help=f"chunks per API call (default: {DEFAULT_BATCH_SIZE})")
    p.add_argument("--limit", type=int, default=None,
                   help="embed at most N chunks per file this run (trial runs)")
    p.add_argument("--dry-run", action="store_true", help="report what would happen, call nothing")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    files = args.files or DEFAULT_FILES
    files = [f if f.is_absolute() else (BACKEND_DIR / f) for f in files]
    missing = [f for f in files if not f.exists()]
    if missing:
        raise SystemExit("file(s) not found:\n  " + "\n  ".join(str(m) for m in missing))

    try:
        import google.generativeai  # noqa: F401
    except ImportError as exc:
        raise SystemExit("google-generativeai is not installed (pip install -r requirements.txt)") from exc

    keys = load_keys()
    print(bold("embed_chunks"))
    print(f"  model   : {args.model}   dim={args.dim}   task_type=retrieval_document")
    print(f"  content : {'heading + text' if args.with_heading else 'text only'}")
    print(f"  keys    : {len(keys)}")
    print(f"  rate    : {args.rpm}/min, batch {args.batch_size}")

    keyring = None if args.dry_run else KeyRing(keys)
    limiter = RateLimiter(args.rpm)

    total_embedded = 0
    all_complete = True
    for path in files:
        embedded, _total, complete = process_file(path, args, keyring, limiter)
        total_embedded += embedded
        all_complete &= complete

    print()
    if all_complete:
        print(green(bold(f"done — {total_embedded} chunks embedded this run")))
        print(dim("  load the .embedded.json files into the DB next"))
        return EXIT_OK
    print(yellow(bold(f"incomplete — {total_embedded} embedded this run")))
    print(dim("  re-run to resume (add keys to GEMINI_API_KEYS, or wait for quota reset)"))
    return EXIT_INCOMPLETE


if __name__ == "__main__":
    raise SystemExit(main())
