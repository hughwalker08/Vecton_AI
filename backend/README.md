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
- `describe_image()` is importable, so the XML ingestion pipeline can call it
  directly once figures are matched to clauses.

## Decisions locked in

- **Embeddings:** Gemini `text-embedding-004` (768-dim) — `services/embedding.py`
- **Generation:** Gemini — `services/generation.py`
- **Diagram/image description:** Gemini vision (`VISION_MODEL_NAME`, default
  `gemini-2.5-flash`) — `services/image_description.py` + `scripts/describe_images.py`
- **PDF parsing:** LlamaParse (external API; needs client sign-off) — `services/`/`api/routes/upload.py`
- DOCX parsing stays local via `python-docx`

## Not yet implemented

- XML ingestion of NCC/ABCB corpus into chunks
- Embedding (Gemini `text-embedding-004`) — provider decided, not wired up
- Hybrid retrieval + reranking
- LLM generation with citations (Gemini)
- PDF/DOCX upload parsing (LlamaParse for PDF, `python-docx` for DOCX) — not wired up
- Document-to-requirement analysis
