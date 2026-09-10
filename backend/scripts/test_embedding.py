#!/usr/bin/env python3
"""
Smoke test for Gemini embeddings.

Grabs one chunk from an ingest output file, sends its text to the Gemini
embedding model (gemini-embedding-2 by default), and prints the resulting
vector. Nothing is written anywhere -- this only exists to confirm the API
key, model name, and SDK all work end to end before the real embed-and-load
pipeline is built.

Note: text-embedding-004 has been retired from the Gemini API -- the current
models are gemini-embedding-2 / gemini-embedding-001, which default to 3072
dimensions and accept --dim to request fewer (Matryoshka truncation).

Standalone on purpose: the only dependency is `google-generativeai`, and the
API key is read straight from the environment or backend/.env, so this runs
without the rest of the app's dependencies installed.

Usage
-----
    # first chunk of the NCC Volume Two output
    python scripts/test_embedding.py

    # the ABCB Housing Provisions output instead, 5th chunk
    python scripts/test_embedding.py --file app/ingest/output/abcb_housing_provisions_chunks.json --index 4

    # a specific clause
    python scripts/test_embedding.py --clause-id H1D4

    # truncate the vector to 768 dims (Matryoshka)
    python scripts/test_embedding.py --dim 768

    # show every number in the vector, not just the head/tail
    python scripts/test_embedding.py --full
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_FILE = BACKEND_DIR / "app" / "ingest" / "output" / "ncc_volume_two_chunks.json"
DEFAULT_MODEL = "gemini-embedding-2"
# HNSW index (capped at 2000 dims). Pass --dim 0 to see the model's native 3072.
DEFAULT_DIM = 768


def api_key() -> str:
    """GEMINI_API_KEY from the environment, or parsed out of backend/.env."""
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    env_path = BACKEND_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("GEMINI_API_KEY=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit(
        "GEMINI_API_KEY is not set. Put it in backend/.env (GEMINI_API_KEY=...) "
        "or export it in your shell."
    )


def load_chunk(path: Path, index: int, clause_id: str | None) -> dict:
    chunks = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(chunks, list) or not chunks:
        raise SystemExit(f"{path} does not contain a non-empty JSON list of chunks")

    if clause_id:
        for chunk in chunks:
            if chunk.get("clause_id") == clause_id:
                return chunk
        raise SystemExit(f"no chunk with clause_id={clause_id!r} in {path.name}")

    if not -len(chunks) <= index < len(chunks):
        raise SystemExit(f"--index {index} out of range (file has {len(chunks)} chunks)")
    return chunks[index]


def embed(text: str, model: str, title: str | None, dim: int | None) -> list[float]:
    try:
        import google.generativeai as genai
    except ImportError as exc:
        raise SystemExit(
            "google-generativeai is not installed. Run: pip install google-generativeai"
        ) from exc

    genai.configure(api_key=api_key())
    # task_type matters: RETRIEVAL_DOCUMENT is what corpus chunks get embedded
    # as; a user's question would be embedded as RETRIEVAL_QUERY at search time.
    kwargs = {}
    if dim is not None:
        kwargs["output_dimensionality"] = dim
    result = genai.embed_content(
        model=model if model.startswith("models/") else f"models/{model}",
        content=text,
        task_type="retrieval_document",
        title=title or None,
        **kwargs,
    )
    return result["embedding"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--file", type=Path, default=DEFAULT_FILE,
                   help=f"ingest output JSON to pull a chunk from (default: {DEFAULT_FILE.relative_to(BACKEND_DIR)})")
    p.add_argument("--index", type=int, default=0,
                   help="which chunk in the file (default: 0; negatives count from the end)")
    p.add_argument("--clause-id", default=None,
                   help="pick the chunk with this clause_id instead of --index")
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help=f"Gemini embedding model (default: {DEFAULT_MODEL})")
    p.add_argument("--dim", type=int, default=DEFAULT_DIM,
                   help=f"request this many dimensions (default: {DEFAULT_DIM}; pass 0 for model native 3072)")
    p.add_argument("--with-heading", action="store_true",
                   help="embed 'heading\\n\\ntext' rather than the chunk text alone")
    p.add_argument("--full", action="store_true",
                   help="print all vector components, not just the first/last 8")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    path = args.file if args.file.is_absolute() else (BACKEND_DIR / args.file)
    if not path.exists():
        raise SystemExit(f"file not found: {path}")

    chunk = load_chunk(path, args.index, args.clause_id)
    heading = chunk.get("heading") or ""
    text = chunk.get("text") or ""
    if not text:
        raise SystemExit(f"chunk {chunk.get('id')} has no text to embed")

    dim = None if args.dim in (0, None) else args.dim
    use_heading = bool(args.with_heading and heading)
    content = f"{heading}\n\n{text}" if use_heading else text

    print(f"file        : {path.relative_to(BACKEND_DIR)}")
    print(f"chunk id    : {chunk.get('id')}")
    print(f"clause_id   : {chunk.get('clause_id')}   ({chunk.get('node_type')})")
    print(f"heading     : {heading!r}")
    print(f"doc         : {chunk.get('doc')}")
    print(f"model       : {args.model}   task_type=retrieval_document"
          + (f"   output_dimensionality={dim}" if dim else "   (native 3072)"))
    print(f"embedding   : {'heading + text' if use_heading else 'text only'}, {len(content)} chars")
    print()
    print("--- content being embedded " + "-" * 52)
    print(content if len(content) <= 1200 else content[:1200] + "\n...[truncated for display]")
    print("-" * 78)
    print()

    vector = embed(content, args.model, title=heading if use_heading else None, dim=dim)

    dim = len(vector)
    norm = math.sqrt(sum(v * v for v in vector))
    print(f"vector dim  : {dim}")
    print(f"L2 norm     : {norm:.6f}")
    print(f"min / max   : {min(vector):.6f} / {max(vector):.6f}")
    print()
    if args.full:
        print(vector)
    else:
        head = ", ".join(f"{v:+.6f}" for v in vector[:8])
        tail = ", ".join(f"{v:+.6f}" for v in vector[-8:])
        print(f"first 8     : [{head}, ...]")
        print(f"last 8      : [..., {tail}]")
        print()
        print("(pass --full to print all components)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
