# Backend — Vecton AI Construction Compliance Assistant

FastAPI backend. Skeleton only — no retrieval/generation logic implemented yet.

## Setup

```bash
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env      # then fill in DATABASE_URL, API keys, etc.
```

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
```

## Not yet implemented

- XML ingestion of NCC/ABCB corpus into chunks
- Embedding (BGE-M3 vs Gemini — decision pending)
- Hybrid retrieval + reranking
- LLM generation with citations
- PDF/DOCX upload parsing (Docling vs LlamaParse — decision pending)
- Document-to-requirement analysis
