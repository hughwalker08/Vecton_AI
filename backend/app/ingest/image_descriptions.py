"""
Figure descriptions for the ingest pipeline.

A figure chunk's `text` would otherwise be just its title, which embeds to
almost nothing -- "Figure 11.2.2: Stair riser and going dimensions" does not
contain the riser height. Folding a transcription of the drawing into `text`
is what makes the figure retrievable.

The descriptions come from a store on disk, in the format written by
`scripts/describe_images.py`:

    python scripts/describe_images.py ../ncc-2025-volume-two-v1.2/images \\
        --out backend/app/ingest/output/vol2_image_descriptions.jsonl

Ingest reads that store and needs no API key. That separation is deliberate:
transcribing ~hundreds of figures is slow and metered, whereas ingest is run
repeatedly while parsing is tuned, and must stay fast and offline. Generating
missing descriptions inline is available via `describe_missing()`, but it is
opt-in rather than the default path.
"""

from __future__ import annotations

import json
from pathlib import Path


class DescriptionStore:
    """Image filename -> description text, loaded from a JSONL or JSON store.

    Lookups fall back to matching on the filename stem, so a store built from
    rasterised PNGs still resolves the corpus's `<img src="figure.svg"/>`.
    """

    def __init__(self, by_key: dict[str, str] | None = None):
        self._by_key: dict[str, str] = {}
        self._by_stem: dict[str, str] = {}
        for key, text in (by_key or {}).items():
            self.add(key, text)

    def add(self, key: str, text: str) -> None:
        name = Path(key).name
        self._by_key[name] = text
        self._by_stem.setdefault(Path(name).stem, text)

    def get(self, filename: str | None) -> str | None:
        if not filename:
            return None
        name = Path(filename).name
        return self._by_key.get(name) or self._by_stem.get(Path(name).stem)

    def __len__(self) -> int:
        return len(self._by_key)

    def __bool__(self) -> bool:
        return bool(self._by_key)


def load_store(*paths: Path) -> DescriptionStore:
    """Load one or more description stores, later paths winning on conflict.

    Accepts both formats `scripts/describe_images.py` writes: the canonical
    `.jsonl` (one record per line) and the flat `.json` index. A missing path
    is not an error -- ingest runs perfectly well with no descriptions, it
    just produces thinner figure chunks.
    """
    store = DescriptionStore()
    for path in paths:
        if not path or not Path(path).exists():
            continue
        path = Path(path)
        if path.suffix == ".jsonl":
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if record.get("image") and record.get("description"):
                        store.add(record["image"], record["description"])
        else:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                for key, text in data.items():
                    if isinstance(text, str) and text.strip():
                        store.add(key, text)
    return store


def describe_missing(
    store: DescriptionStore,
    images_dir: Path,
    filenames: list[str],
    out_path: Path,
    model=None,
    progress=print,
) -> int:
    """Transcribe figures not already in `store`, appending to `out_path`.

    Opt-in (`--describe-missing-images`). Appends in the same JSONL format
    `scripts/describe_images.py` writes, flushing per record, so an
    interrupted ingest still banks what it paid for.
    """
    from datetime import datetime, timezone

    from app.services.image_description import (
        PROMPT_VERSION,
        ImageDescriptionError,
        build_model,
        describe_image,
    )

    missing = [name for name in dict.fromkeys(filenames) if store.get(name) is None]
    if not missing:
        progress("All matched figures already have descriptions.")
        return 0

    handle = model if model is not None else build_model()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0

    progress(f"Describing {len(missing)} figure(s) with no stored description...")
    with out_path.open("a", encoding="utf-8") as fh:
        for i, name in enumerate(missing, 1):
            path = images_dir / name
            try:
                result = describe_image(path, model=handle)
            except (ImageDescriptionError, OSError) as exc:
                progress(f"  [{i}/{len(missing)}] FAILED {name}: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001 - provider/transport faults
                progress(f"  [{i}/{len(missing)}] FAILED {name}: {type(exc).__name__}: {exc}")
                continue

            store.add(name, result.text)
            fh.write(
                json.dumps(
                    {
                        "image": name,
                        "file_name": name,
                        "description": result.text,
                        "model": result.model,
                        "prompt_version": PROMPT_VERSION,
                        "chars": len(result.text),
                        "described_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            fh.flush()
            written += 1
            progress(f"  [{i}/{len(missing)}] OK {name} ({len(result.text)} chars)")

    progress(f"Wrote {written} new description(s) to {out_path}")
    return written


def figure_text(title: str | None, description: str | None) -> str:
    """Compose the embedded text for a figure chunk.

    Title first so lexical search on the figure number and caption keeps
    working, then the transcription beneath it.
    """
    parts = [p.strip() for p in (title, description) if p and p.strip()]
    return "\n\n".join(parts)
