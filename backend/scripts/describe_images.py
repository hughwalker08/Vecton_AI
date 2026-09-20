#!/usr/bin/env python3
"""
Batch-transcribe NCC 2025 Volume Two / ABCB Housing Provisions diagrams into
text descriptions, so figures can be embedded and cited alongside clause text.

Walks one or more image folders (recursively), sends each image to Gemini via
app/services/image_description.py, and writes one JSON record per image keyed
by the image's path.

Usage
-----
    # describe everything under the default drop folder (data/images/)
    python scripts/describe_images.py

    # one or more explicit folders
    python scripts/describe_images.py data/images/ncc_vol2 data/images/housing_provisions

    # see what would be processed without spending any API calls
    python scripts/describe_images.py data/images --dry-run

    # bigger job: better model, 4 in flight at once
    python scripts/describe_images.py data/images --model gemini-2.5-pro --workers 4

Output
------
`--out` (default data/image_descriptions/descriptions.jsonl) is written
incrementally, one JSON object per line, so an interrupted run loses nothing.
A companion `<name>.json` -- a plain {image path: description} map -- is written
at the end for easy consumption. Failures go to `<name>.errors.jsonl`.

Re-running skips images already present in the output (resume). Use --overwrite
to re-describe everything, or --retry-failed to retry only the previous
failures.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

# Allow running as `python scripts/describe_images.py` from anywhere.
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings  # noqa: E402
from app.services.image_description import (  # noqa: E402
    FALLBACK_PROMPT,
    PROMPT,
    PROMPT_VERSION,
    SUPPORTED_EXTENSIONS,
    ImageDescriptionError,
    build_model,
    describe_image,
)

DEFAULT_INPUT = BACKEND_DIR / "data" / "images"
DEFAULT_OUTPUT = BACKEND_DIR / "data" / "image_descriptions" / "descriptions.jsonl"

# ANSI colours, disabled when piping to a file or when NO_COLOR is set.
_COLOUR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOUR else text


def dim(t: str) -> str:
    return _c("2", t)


def bold(t: str) -> str:
    return _c("1", t)


def green(t: str) -> str:
    return _c("32", t)


def yellow(t: str) -> str:
    return _c("33", t)


def red(t: str) -> str:
    return _c("31", t)


def cyan(t: str) -> str:
    return _c("36", t)


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------

def find_images(roots: list[Path], extensions: set[str]) -> list[Path]:
    """Return every image file under `roots`, sorted and de-duplicated."""
    found: set[Path] = set()
    for root in roots:
        root = root.expanduser().resolve()
        if root.is_file():
            if root.suffix.lower() in extensions:
                found.add(root)
            continue
        if not root.is_dir():
            print(red(f"  ! input folder does not exist: {root}"), file=sys.stderr)
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in extensions:
                found.add(path.resolve())
    return sorted(found)


def label_for(path: Path, roots: list[Path]) -> str:
    """Key used in the output: the path relative to whichever root contains it.

    Keeping the sub-folder (e.g. "ncc_vol2/part_11/figure_11_2_2.png") means two
    figures with the same file name in different parts don't collide.
    """
    for root in roots:
        try:
            resolved = root.expanduser().resolve()
        except OSError:
            continue
        if resolved.is_dir():
            try:
                return path.relative_to(resolved).as_posix()
            except ValueError:
                continue
    return path.name


# --------------------------------------------------------------------------
# Output files
# --------------------------------------------------------------------------

def load_done(out_path: Path) -> dict[str, dict]:
    """Read already-described records from a previous run, keyed by image label."""
    if not out_path.exists():
        return {}
    done: dict[str, dict] = {}
    with out_path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                print(yellow(f"  ! skipping malformed line {line_no} in {out_path.name}"))
                continue
            if record.get("image") and record.get("description"):
                done[record["image"]] = record
    return done


def load_failed(errors_path: Path) -> set[str]:
    """Image labels that failed on a previous run."""
    if not errors_path.exists():
        return set()
    failed: set[str] = set()
    with errors_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                failed.add(json.loads(line)["image"])
            except (json.JSONDecodeError, KeyError):
                continue
    return failed


def rewrite_errors(errors_path: Path, succeeded: set[str]) -> int:
    """Tidy the errors file: one row per image, and drop anything now described.

    Every run appends, so without this a figure that keeps failing accumulates a
    row per run, and one that eventually succeeded would still look failed.
    Returns the number of images still outstanding.
    """
    if not errors_path.exists():
        return 0
    latest: dict[str, dict] = {}
    with errors_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            label = record.get("image")
            if label and label not in succeeded:
                latest[label] = record
    if not latest:
        errors_path.unlink(missing_ok=True)
        return 0
    with errors_path.open("w", encoding="utf-8") as fh:
        for _, record in sorted(latest.items()):
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(latest)


def write_index(out_path: Path, records: dict[str, dict]) -> Path:
    """Write the flat {image: description} map next to the JSONL."""
    index_path = out_path.with_suffix(".json")
    index = {label: rec["description"] for label, rec in sorted(records.items())}
    index_path.write_text(
        json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return index_path


# --------------------------------------------------------------------------
# Transcription with retries
# --------------------------------------------------------------------------

class QuotaExhausted(RuntimeError):
    """The provider's per-day quota is gone. Retrying cannot help today."""


def _is_daily_quota(exc: Exception) -> bool:
    """True for a per-DAY quota exhaustion, as opposed to per-minute throttling.

    The two arrive as the same HTTP 429, but they need opposite handling:
    per-minute throttling clears in seconds and is worth backing off for,
    while a spent daily allowance will reject every further request until the
    quota resets. Retrying the latter four times per image just burns the
    next day's budget too -- a free-tier run against a 20/day cap spent 56
    requests on retries to describe nothing.
    """
    blob = f"{type(exc).__name__} {exc}"
    return "PerDay" in blob or "per day" in blob.lower()


def _is_rate_limit(exc: Exception) -> bool:
    blob = f"{type(exc).__name__} {exc}".lower()
    return any(
        s in blob
        for s in ("429", "resource_exhausted", "resourceexhausted", "rate limit", "quota")
    )


def transcribe(path: Path, label: str, model, attempts: int, caption: str | None = None,
               caption_in_image: bool = False, prompt: str = PROMPT) -> dict:
    """Describe one image, retrying transient failures. Returns a result dict."""
    started = time.monotonic()
    last_error = ""
    made = 0

    for attempt in range(1, attempts + 1):
        made = attempt
        try:
            result = describe_image(path, model=model, caption=caption,
                                    caption_in_image=caption_in_image, prompt=prompt)
            return {
                "ok": True,
                "image": label,
                "file_name": path.name,
                "description": result.text,
                "model": result.model,
                "prompt_version": result.prompt_version,
                "prompt_variant": "fallback" if prompt is FALLBACK_PROMPT else "main",
                "caption": caption,
                "chars": len(result.text),
                "attempts": attempt,
                "seconds": round(time.monotonic() - started, 1),
                "described_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        except ImageDescriptionError as exc:
            # Empty file / too large / missing key -- retrying won't help.
            last_error = str(exc)
            break
        except Exception as exc:  # noqa: BLE001 - the SDK raises a wide variety
            last_error = f"{type(exc).__name__}: {exc}"
            if _is_daily_quota(exc):
                # Abort the whole run rather than burning the remaining
                # allowance one image at a time.
                raise QuotaExhausted(last_error) from exc
            if attempt == attempts:
                break
            # Rate limits need a much longer wait than a flaky connection.
            base = 20.0 if _is_rate_limit(exc) else 2.0
            delay = base * (2 ** (attempt - 1)) + random.uniform(0, 1)
            print(dim(f"      retry {attempt}/{attempts - 1} in {delay:.0f}s "
                      f"-- {last_error[:110]}"))
            time.sleep(delay)

    return {
        "ok": False,
        "image": label,
        "file_name": path.name,
        "error": last_error,
        "attempts": made,
        "seconds": round(time.monotonic() - started, 1),
        "failed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# --------------------------------------------------------------------------
# Progress reporting
# --------------------------------------------------------------------------

def preview(text: str, lines: int, width: int = 96) -> list[str]:
    """First few meaningful lines of a description, for the running log."""
    out: list[str] = []
    if lines <= 0:
        return out
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            # A heading alone says nothing, but it labels the line that follows.
            out.append(dim(stripped.lstrip("# ").strip() + ":"))
        else:
            out.append(stripped[:width] + ("..." if len(stripped) > width else ""))
        if len(out) >= lines:
            break
    # A trailing heading with no content under it just looks truncated.
    while out and out[-1].endswith(":"):
        out.pop()
    return out


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Transcribe NCC / ABCB diagrams into text descriptions using Gemini.",
    )
    p.add_argument(
        "inputs", nargs="*", type=Path, default=[DEFAULT_INPUT],
        help=f"image files or folders, searched recursively (default: {DEFAULT_INPUT})",
    )
    p.add_argument("-o", "--out", type=Path, default=DEFAULT_OUTPUT,
                   help=f"output .jsonl path (default: {DEFAULT_OUTPUT})")
    p.add_argument("--model", default=None,
                   help=f"Gemini model (default: {settings.VISION_MODEL_NAME}, "
                        f"from VISION_MODEL_NAME in .env)")
    p.add_argument("--workers", type=int, default=1,
                   help="images to process concurrently (default: 1; raise carefully, "
                        "free-tier Gemini allows roughly 15 requests/min)")
    p.add_argument("--attempts", type=int, default=4,
                   help="attempts per image before giving up (default: 4)")
    p.add_argument("--limit", type=int, default=None,
                   help="stop after N images (useful for a trial run)")
    p.add_argument("--ext", default=",".join(sorted(SUPPORTED_EXTENSIONS)),
                   help="comma-separated extensions to include")
    p.add_argument("--overwrite", action="store_true",
                   help="re-describe images already present in the output file")
    p.add_argument("--retry-failed", action="store_true",
                   help="process only the images that failed on the previous run")
    p.add_argument("--preview-lines", type=int, default=3,
                   help="lines of each fresh description to echo, 0 to disable (default: 3)")
    p.add_argument("--captions", type=Path, default=None,
                   help="JSON map of {image file name: caption}, e.g. the captions.json "
                        "written by scripts/extract_pdf_figures.py. The caption is passed "
                        "to the model as context and recorded on each output row.")
    p.add_argument("--fallback-prompt", action="store_true",
                   help="use the recitation-safe prompt variant: same headings and facts, "
                        "framed as recording technical data rather than transcribing text. "
                        "For figures the main prompt could not get past Gemini's copyright "
                        "filter (finish_reason 4). Pair with --retry-failed.")
    p.add_argument("--caption-in-image", action="store_true",
                   help="the caption is printed inside the image (true for crops from "
                        "scripts/extract_pdf_figures.py) -- tells the model to record it "
                        "under ## Figure rather than treat it as external context")
    p.add_argument("--dry-run", action="store_true",
                   help="list what would be processed; make no API calls")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    roots = [Path(p) for p in args.inputs]
    extensions = {
        e if e.startswith(".") else f".{e}"
        for e in (x.strip().lower() for x in args.ext.split(",")) if e
    }

    print()
    print(bold("NCC / ABCB image transcription"))
    print(f"  input   : {', '.join(str(r.expanduser()) for r in roots)}")
    print(f"  output  : {args.out}")
    print(f"  model   : {args.model or settings.VISION_MODEL_NAME}  (prompt v{PROMPT_VERSION})")
    print()

    images = find_images(roots, extensions)
    if not images:
        print(yellow("No images found."))
        print(dim("Drop the NCC 2025 Vol 2 / ABCB Housing Provisions figures into "
                  f"{DEFAULT_INPUT} (sub-folders are fine), or pass a folder as an argument."))
        return 1

    captions: dict[str, str] = {}
    if args.captions:
        if args.captions.exists():
            captions = json.loads(args.captions.read_text(encoding="utf-8"))
            print(f"  loaded {len(captions)} caption(s) from {args.captions}")
        else:
            print(yellow(f"  ! captions file not found: {args.captions}"))

    out_path = args.out.expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    errors_path = out_path.with_suffix(".errors.jsonl")

    done = {} if args.overwrite else load_done(out_path)
    previously_failed = load_failed(errors_path)

    queue: list[tuple[Path, str]] = []
    for path in images:
        label = label_for(path, roots)
        if args.retry_failed and label not in previously_failed:
            continue
        if label in done and not args.overwrite:
            continue
        queue.append((path, label))

    skipped = len(images) - len(queue)
    if args.limit is not None:
        queue = queue[: args.limit]

    print(f"  found {bold(str(len(images)))} images"
          + (dim(f" - {skipped} already described (skipping)") if skipped else "")
          + (dim(f" - limited to {args.limit}") if args.limit is not None else ""))
    print(f"  {bold(str(len(queue)))} to transcribe")
    print()

    if args.dry_run:
        for path, label in queue:
            print(dim(f"  would transcribe  {label}  ({path.stat().st_size / 1024:.0f} KB)"))
        print()
        print(f"Dry run -- no API calls made. Output would go to {cyan(str(out_path))}")
        return 0

    if not queue:
        print(green("Nothing to do -- every image already has a description."))
        print(f"  {cyan(str(out_path))}")
        return 0

    try:
        model = build_model(args.model)
    except ImageDescriptionError as exc:
        print(red(f"Cannot start: {exc}"), file=sys.stderr)
        return 2

    if args.overwrite:
        # Start clean so the file doesn't accumulate stale duplicate rows.
        out_path.unlink(missing_ok=True)
        errors_path.unlink(missing_ok=True)
        done = {}

    total = len(queue)
    succeeded = failed = 0
    quota_hit = False
    started = time.monotonic()
    pool: ThreadPoolExecutor | None = None

    out_fh = out_path.open("a", encoding="utf-8")
    err_fh = errors_path.open("a", encoding="utf-8")

    def run(item: tuple[Path, str]) -> dict:
        caption = captions.get(item[0].name) or captions.get(item[1])
        return transcribe(item[0], item[1], model, max(1, args.attempts), caption,
                          args.caption_in_image,
                          FALLBACK_PROMPT if args.fallback_prompt else PROMPT)

    try:
        if args.workers > 1:
            pool = ThreadPoolExecutor(max_workers=args.workers)
            results = pool.map(run, queue)
        else:
            results = (run(item) for item in queue)

        for i, result in enumerate(results, 1):
            label = result["image"]
            if result["ok"]:
                succeeded += 1
                record = {k: v for k, v in result.items() if k != "ok"}
                out_fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                out_fh.flush()
                done[label] = record
                stats = f"- {record['chars']} chars - {record['seconds']}s"
                print(f"{dim(f'[{i}/{total}]')} {green('OK')} {bold(label)} {dim(stats)}")
                for line in preview(record["description"], args.preview_lines):
                    print(f"      {line}")
            else:
                failed += 1
                record = {k: v for k, v in result.items() if k != "ok"}
                err_fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                err_fh.flush()
                print(f"{dim(f'[{i}/{total}]')} {red('FAILED')} {bold(label)} "
                      f"{red(record['error'][:150])}")

            # Periodic heartbeat so long runs report rate and time remaining.
            if i % 10 == 0 and i < total:
                elapsed = time.monotonic() - started
                rate = i / elapsed if elapsed else 0
                remaining = (total - i) / rate if rate else 0
                print(dim(f"  -- {i}/{total} done - {succeeded} ok, {failed} failed "
                          f"- {rate * 60:.1f}/min - ~{fmt_duration(remaining)} left "
                          f"- saving to {out_path.name}"))
    except QuotaExhausted as exc:
        print()
        print(red("Provider daily quota exhausted -- stopping the run."))
        print(dim(f"  {str(exc)[:200]}"))
        print(yellow(f"  {succeeded} description(s) saved this run. Re-run the same "
                     "command once the quota resets, or move the key to a paid tier; "
                     "resume will skip everything already done."))
        quota_hit = True
    except KeyboardInterrupt:
        print()
        print(yellow(f"Interrupted. {succeeded} description(s) already saved -- "
                     "re-run the same command to resume."))
    finally:
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)
        out_fh.close()
        err_fh.close()

    outstanding = rewrite_errors(errors_path, set(done))
    index_path = write_index(out_path, done)

    elapsed = time.monotonic() - started
    print()
    print(bold("Done."))
    print(f"  transcribed : {green(str(succeeded))} this run "
          f"- {len(done)} total in the output file")
    if outstanding:
        print(f"  failed      : {red(str(failed))} this run "
              f"- {outstanding} outstanding -> {errors_path}")
        print(dim("                re-run with --retry-failed to retry just these"))
    if quota_hit:
        print(f"  stopped     : {red('provider daily quota exhausted')}")
    print(f"  elapsed     : {fmt_duration(elapsed)}")
    print(f"  saved to    : {cyan(str(out_path))}   {dim('(one JSON record per line)')}")
    print(f"                {cyan(str(index_path))}   {dim('(flat image -> description map)')}")
    print()
    if quota_hit:
        return 3
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
