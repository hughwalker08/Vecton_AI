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
  services/           # embedding.py, retrieval.py, generation.py — all stubs
  api/routes/         # health.py, chat.py, upload.py
migrations/           # Alembic: env.py + versions/ (0001 = initial schema)
alembic.ini           # Alembic config (DB URL comes from .env, not here)
```

## Decisions locked in

- **Embeddings:** Gemini `text-embedding-004` (768-dim) — `services/embedding.py`
- **Generation:** Gemini — `services/generation.py`
- **PDF parsing:** LlamaParse (external API; needs client sign-off) — `services/`/`api/routes/upload.py`
- DOCX parsing stays local via `python-docx`

## Not yet implemented

- XML ingestion of NCC/ABCB corpus into chunks
- Embedding (Gemini `text-embedding-004`) — provider decided, not wired up
- Hybrid retrieval + reranking
- LLM generation with citations (Gemini)
- PDF/DOCX upload parsing (LlamaParse for PDF, `python-docx` for DOCX) — not wired up
- Document-to-requirement analysis
