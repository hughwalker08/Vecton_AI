# Backend — Vecton AI Construction Compliance Assistant

FastAPI backend for a RAG assistant over the NCC 2025 Volume Two + ABCB
Housing Provisions. `/api/chat` answers a question with hybrid
retrieval (pgvector + Postgres full-text, fused, reranked) feeding a
citation-strict Gemini call; `/api/compliance/analyse` classifies an
already-extracted document's text against the clauses that apply to it;
`/api/upload` accepts a PDF/DOCX and transcribes any embedded drawings

## Setup

From the repo root, `make backend-install` (or `make setup` for backend +
frontend together) does the same thing — see the root `README.md`. Manually:

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
- `0003_fulltext_tsvector` — `text_tsv` generated column + GIN index (lexical
  half of hybrid retrieval).
- `0004_user_profiles` — `user_profiles`, linked to Supabase Auth, with RLS.
- `0005_image_refs` — `image_refs` on `clause_chunks` (figure citations).
- `0006_compliance_feedback` — `compliance_feedback`: a flat log for flagging a
  compliance_analysis finding as wrongly classified (see
  `app/services/compliance_analysis.py`).
- `0007_chat_history` — `chats` + `chat_messages`, linked to Supabase Auth,
  with RLS (same pattern as `0004`, not `0006`: this is per-user private
  data, managed directly by the frontend via the Supabase client -- see
  `frontend/src/lib/chats.js` -- rather than through an API route, since
  the backend has no per-user auth wired in).

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

`make backend` from the repo root, or:

```bash
uvicorn app.main:app --reload
```

API docs will be available at http://localhost:8000/docs

## Tests

`make lint` / `make backend-test` from the repo root, or:

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
  main.py              # FastAPI app + router registration
  core/config.py       # Settings, loaded from .env
  db/session.py        # SQLAlchemy engine/session (Postgres + pgvector)
  models/               # SQLAlchemy models (clause_chunk.py)
  ingest/               # NCC/ABCB XML -> chunk JSON parser (see app/ingest/cli.py)
  schemas/              # (reserved for shared Pydantic schemas)
  services/
    embedding.py         # Gemini embeddings (query + corpus)
    retrieval.py          # hybrid_search + rerank -> retrieve() (chat + compliance both use this)
    generation.py          # citation-strict Gemini call for /api/chat
    gemini_keys.py          # shared multi-key rotation (generation, embedding,
                            # compliance_analysis, image_description all go through it)
    compliance_analysis.py  # classifies document text against retrieve()'d clauses
    image_description.py    # Gemini vision transcription of a figure/drawing
    document_images.py       # extract embedded images from an uploaded PDF/DOCX
    document_captions.py     # match an extracted image to its caption/alt-text
  api/routes/            # health.py, chat.py, upload.py, compliance.py
scripts/
  embed_chunks.py       # batch-embeds app/ingest/output/*_chunks.json -> *.embedded.json
  load_chunks.py         # idempotent upsert of *.embedded.json into clause_chunks
  describe_images.py      # batch NCC/ABCB figure transcription (see below)
data/images/           # drop NCC/ABCB figures here (gitignored)
data/image_descriptions/  # generated descriptions (gitignored)
migrations/            # Alembic: env.py + versions/ (0001 = initial schema)
alembic.ini            # Alembic config (DB URL comes from .env, not here)
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

## Retrieval + generation (`/api/chat`)

`app.services.retrieval.retrieve(query, top_k, jurisdiction)` is the shared
entry point (also used by compliance analysis, below):

1. **Hybrid search** (`hybrid_search`) — one SQL statement, two CTEs: dense
   (pgvector cosine, `embedding <=> query_vector`) and lexical (Postgres
   full-text, `ts_rank_cd` over a `tsvector` column), fused with Reciprocal
   Rank Fusion (`SUM(1/(60+rank))` across both methods). `jurisdiction`, when
   given, filters both CTEs to national clauses (`jurisdictions IS NULL`)
   plus clauses naming that jurisdiction — clauses scoped to a different one
   are excluded before reranking ever sees them.
2. **Rerank** (`rerank`) — the fused candidates (30 by default) go through a
   cross-encoder second pass, `BAAI/bge-reranker-base` via the Hugging Face
   Inference router (`HF_API_TOKEN` required), batched into one request.
   Passages are truncated server-side (`truncation`/`max_length=512`) since
   some corpus chunks (whole Parts/Specifications) run well past the
   reranker's token limit.

`app.services.generation.generate_answer(question, chunks, jurisdiction)`
then builds a citation-strict prompt from the reranked chunks (clause ID,
document, verbatim text, applicability qualifiers, Standard hand-offs) and
calls Gemini (`temperature=0`, plain-text output — the chat UI renders raw
text, not Markdown). It refuses to answer without supporting context, treats
a truncated response (`MAX_TOKENS`) as a hard failure rather than serving a
cut-off legal quote, and raises `QuotaExceededError` (surfaced as HTTP 429)
when every configured Gemini key is out of quota.

`api/routes/chat.py` wires this together and abstains ("No source found")
when the top reranked candidate's score is below `MIN_RERANK_SCORE` — the
LLM is never called on an unsupported question.

## Multi-key Gemini rotation (`services/gemini_keys.py`)

`generation.py`, `embedding.py`, `compliance_analysis.py` and
`image_description.py` all call Gemini through `call_with_rotation()` rather
than a single client. Set `GEMINI_API_KEYS` (comma-separated, see
`.env.example`) to pool several teammates' free-tier keys — when one hits its
per-minute or daily quota, the shared rotator puts it on cooldown and moves
to the next key instead of failing the request. `GEMINI_API_KEY` (single key)
still works if that's all you have; `GEMINI_API_KEYS` overrides it when set.

## Compliance analysis (`/api/compliance`)

`POST /api/compliance/analyse` takes already-extracted document text plus a
`query` describing what the document is for (e.g. "Class 1a dwelling
stormwater drainage and smoke alarm requirements"), retrieves the applicable
clauses via the same `retrieve()` used by chat, and asks Gemini to classify
each one against the document in a single structured-output call:
`addressed` / `contradicted` / `missing` / `needs_review`. `POST`/`GET
/api/compliance/feedback` lets a reviewer flag a finding as wrongly
classified (logged to `compliance_feedback`, migration `0006`).

This endpoint takes text directly rather than a file, since upload text
extraction isn't wired up yet (see below) — once it is, `upload.py` becomes
the caller here instead of a manually-pasted `document_text`.

## Deployment (Render)

`render.yaml` (repo root) is a Render Blueprint defining two free-tier
services: this backend (`uvicorn app.main:app`) and the static frontend
build. Secrets (`DATABASE_URL`, `GEMINI_API_KEY`/`GEMINI_API_KEYS`,
`HF_API_TOKEN`, the frontend's Supabase vars) are `sync: false` — entered by
hand in the Render dashboard, never committed. `EMBEDDING_MODEL_NAME` is
pinned there deliberately: it must keep matching whatever model produced the
stored corpus embeddings (`gemini-embedding-2` — changing it without
re-embedding the corpus breaks retrieval).

## Decisions locked in

- **Embeddings:** Gemini `gemini-embedding-2` (768-dim) — `services/embedding.py`.
  Must match `app/ingest/output/*.embedded.json` (see `scripts/embed_chunks.py`
  and each file's `.meta.json`) — query and corpus vectors only compare
  meaningfully from the same model.
- **Generation:** Gemini `gemini-3.6-flash` — `services/generation.py`.
  (`gemini-2.5-flash` was retired for new API keys as of 2026-09; this is
  Google's recommended direct replacement.)
- **Reranking:** `BAAI/bge-reranker-base`, hosted via the Hugging Face
  Inference router rather than run locally, to avoid a torch/transformers
  dependency in the backend — `services/retrieval.py`.
- **Diagram/image description:** Gemini vision (`VISION_MODEL_NAME`, default
  `gemini-2.5-flash`) — `services/image_description.py` + `scripts/describe_images.py`
- **PDF parsing:** LlamaParse (external API; needs client sign-off) — `services/`/`api/routes/upload.py`
- DOCX parsing stays local via `python-docx`
- **Image extraction from uploads:** PyMuPDF for PDF, stdlib `zipfile` for DOCX —
  `services/document_images.py`. PyMuPDF also rasterises corpus SVG figures.