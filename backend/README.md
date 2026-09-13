# Backend — Vecton AI Construction Compliance Assistant

FastAPI backend. Skeleton only — no retrieval/generation logic implemented yet.

## Setup

```bash
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env      # then fill in DATABASE_URL, API keys, etc.
```

## Database migrations (Alembic)

Schema lives in `migrations/`. The DB URL is read from `.env`
(`DATABASE_URL`), not from `alembic.ini`.

```bash
alembic upgrade head        # apply all migrations
alembic downgrade -1        # roll back one
alembic revision -m "msg"   # new empty migration
alembic revision --autogenerate -m "msg"   # diff models vs DB (review the output!)
alembic upgrade head --sql  # print SQL instead of running it
```

Migrations:
- `0001_initial_schema` — `vector` extension + `clause_chunks` + HNSW cosine index.
- `0002_refs_applicability_node_type` — `node_type`; typed refs (`internal_refs`,
  `standard_refs`); applicability qualifiers (`building_classes`, `jurisdictions`,
  `climate_zones`, `applicability_note`) with GIN indexes.

Schema covers the client's citation requirements: specific clause id
(`clause_id`) + containment (`hierarchy`), source document (`doc`), verbatim
`text`, corpus-internal references vs Australian-Standard hand-offs (split
columns), and per-class / per-state / per-climate-zone applicability
(structured for filtering + `applicability_note` verbatim for the answer).

Supabase note: the direct host `db.<ref>.supabase.co` is IPv6-only. If your
network has no IPv6, use the **Session pooler** connection string
(`...pooler.supabase.com:5432`) from the dashboard as `DATABASE_URL`.
If you can't run Alembic at all, `alembic upgrade head --sql` prints the
statements to paste into the Supabase SQL Editor.

## Run

```bash
uvicorn app.main:app --reload
```

API docs will be available at http://localhost:8000/docs

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

Runs the suite under `tests/` and prints a coverage report (config in
`pyproject.toml`); also writes `coverage.xml` for CI. `ruff check app tests`
runs the linter.

`tests/test_migrations.py`'s chain-integrity checks always run; its
upgrade/downgrade round-trip test needs a real, **disposable** Postgres +
pgvector database (a CI service container, or a local throwaway one) --
point `TEST_DATABASE_URL` at it to run that test, otherwise it's skipped.
Never point it at a real dev database: the test migrates to head, then
back down to base again, dropping every table these migrations own.

## Structure

```
app/
  main.py            # FastAPI app + router registration
  core/config.py      # Settings, loaded from .env
  db/session.py       # SQLAlchemy engine/session (Postgres + pgvector)
  models/             # SQLAlchemy models (clause_chunk.py so far)
  schemas/            # (reserved for shared Pydantic schemas)
  services/           # embedding.py, retrieval.py, generation.py (stubs)
                      # image_description.py (implemented)
  api/routes/         # health.py, chat.py, upload.py
scripts/              # describe_images.py — batch NCC/ABCB figure transcription
data/images/          # drop NCC/ABCB figures here (gitignored)
data/image_descriptions/  # generated descriptions (gitignored)
migrations/           # Alembic: env.py + versions/ (0001 = initial schema)
alembic.ini           # Alembic config (DB URL comes from .env, not here)
```

## Image / diagram transcription

NCC and ABCB figures carry requirements that exist nowhere in the clause text
(riser heights, flashing details, decision trees). `scripts/describe_images.py`
sends each image to Gemini and writes a text description keyed by the image
path, so figures can be embedded and cited like any other chunk.

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env          # set GEMINI_API_KEY

# drop the figures into data/images/ (sub-folders encouraged), then:
python scripts/describe_images.py

# or point it at any folder(s) - searched recursively
python scripts/describe_images.py path/to/ncc_vol2 path/to/housing_provisions

python scripts/describe_images.py data/images --dry-run       # cost nothing, just list
python scripts/describe_images.py data/images --limit 5        # trial run
python scripts/describe_images.py data/images --model gemini-2.5-pro --workers 4
```

Output (default `data/image_descriptions/`):

| file | contents |
| --- | --- |
| `descriptions.jsonl` | one JSON record per image, written as each finishes: `image`, `file_name`, `description`, `model`, `prompt_version`, `chars`, `attempts`, `seconds`, `described_at` |
| `descriptions.json` | flat `{"ncc_vol2/part_11/figure_11_2_2.png": "..."}` map, rewritten at the end |
| `descriptions.errors.jsonl` | images that failed, with the error |

The `image` key is the path *relative to the input folder*, so same-named
figures in different parts don't collide.

While running it prints `[n/total]`, the image name, size and elapsed time, the
first few lines of each fresh description, a rate/ETA heartbeat every 10 images,
and the output paths at the end.

Notes:
- **Resume is the default** — a re-run skips images already in the output, so an
  interrupted or rate-limited job just needs the same command again.
  `--overwrite` re-does everything; `--retry-failed` retries only the failures.
- Retries use exponential backoff, with a much longer wait on HTTP 429 —
  free-tier Gemini is roughly 15 requests/min, so leave `--workers` at 1 there.
- The prompt lives in `app/services/image_description.py` and asks for verbatim
  transcription of every label, dimension and note rather than a prose summary,
  with an explicit instruction never to infer a value the figure doesn't show.
  Bump `PROMPT_VERSION` when editing it — it's recorded on every record, so you
  can tell which descriptions predate the change.
- Corpus figures ship as **SVG**, which no vision model reads directly. They are
  rasterised to PNG first (PyMuPDF, no native cairo needed) at 1600 px wide —
  rendering at native size makes the dimension text unreadable, and a misread
  digit is the worst failure this pipeline has.
- `describe_image()` (path) and `describe_image_bytes()` (bytes, no file needed)
  are both importable. The ingestion pipeline and the upload endpoint use them.

### Where descriptions are used

Two consumers, both wired up:

**1. Corpus ingestion — figure chunks.** Without a description, a figure chunk's
`text` is just its caption, which embeds to almost nothing: *"Figure 11.2.2:
Stair riser and going dimensions"* does not contain the riser height. The ingest
pipeline folds the transcription into `text` beneath the caption.

```bash
# generate once, per corpus (keyed by the filename in <img src="..."/>)
python scripts/describe_images.py ../ncc-2025-volume-two-v1.2/images     --out app/ingest/output/vol2_image_descriptions.jsonl

# ingest picks up app/ingest/output/{vol2,housing}_image_descriptions.jsonl
python -m app.ingest.cli
```

Ingest needs **no API key** — it reads the store if present and reports how many
matched figures still lack a description. Point it elsewhere with
`--image-descriptions <path…>`, or generate missing ones inline with
`--describe-missing-images` (that one does need a key, and costs a call per
figure). Stores are kept per corpus because Volume Two and the Housing
Provisions reuse figure filenames.

**2. User uploads — drawings inside submitted documents.** `POST /api/upload/`
extracts embedded images from a PDF or DOCX and transcribes each one, so a
submitted plan set's dimensions and annotations come back as text:

```
POST /api/upload/?describe_images=true&max_images=25
  -> { images_found, images_skipped, images_described, images_failed,
       truncated, images: [{ name, source, description, error }] }
```

DOCX images are read straight out of the zip (`word/media/`) with stdlib
`zipfile`; PDF images come from PyMuPDF, de-duplicated by xref so a logo
repeated on forty pages costs one call. Images below 8 KB or 200 px on the short
side are treated as decorative (letterheads, bullet glyphs) and skipped — they
carry no compliance content and would each cost an API call. One image failing
doesn't sink the upload; the error lands on that finding and the rest continue.

Text extraction from uploads is still **not** implemented — that half waits on
LlamaParse sign-off. The image half is independent of it.

## Decisions locked in

- **Embeddings:** Gemini `text-embedding-004` (768-dim) — `services/embedding.py`
- **Generation:** Gemini — `services/generation.py`
- **Diagram/image description:** Gemini vision (`VISION_MODEL_NAME`, default
  `gemini-2.5-flash`) — `services/image_description.py` + `scripts/describe_images.py`
- **PDF parsing:** LlamaParse (external API; needs client sign-off) — `services/`/`api/routes/upload.py`
- DOCX parsing stays local via `python-docx`
- **Image extraction from uploads:** PyMuPDF for PDF, stdlib `zipfile` for DOCX —
  `services/document_images.py`. PyMuPDF also rasterises corpus SVG figures.

## Not yet implemented

- Embedding (Gemini `text-embedding-004`) — provider decided, not wired up
- Hybrid retrieval + reranking
- LLM generation with citations (Gemini)
- Upload **text** parsing (LlamaParse for PDF, `python-docx` for DOCX) — not wired
  up. Upload **image** extraction and transcription *is* implemented.
- Document-to-requirement analysis
- Loading ingest output into Postgres — the pipeline writes JSON only, and no
  database has been provisioned yet (`DATABASE_URL` in `.env.example` is still a
  placeholder; there is no `.env` in the repo).
