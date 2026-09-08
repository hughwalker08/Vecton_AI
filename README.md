# Vecton AI — Construction Compliance Assistant (COMP3888_TH10_01)

Skeleton project scaffold. **No features are implemented yet** — this just
establishes the folder structure, tooling, and stub files so the team can
build directly on top of it.

## Stack

- **Frontend:** React (Vite)
- **Backend:** FastAPI
- **Database:** Postgres + pgvector (via Supabase)
- **Embeddings:** Gemini `text-embedding-004` (768-dim)
- **Generation (LLM):** Gemini
- **Diagram/image description:** Gemini vision (`gemini-2.5-flash`)
- **PDF parsing:** LlamaParse (external API — client sign-off required)
- **Hosting:** Render

## Structure

```
backend/    FastAPI app — see backend/README.md
frontend/   React app — see frontend/README.md
```

## Quick start

```bash
# Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in DATABASE_URL etc.
uvicorn app.main:app --reload

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

## Roadmap (per current planning doc)

- [ ] Parse NCC/ABCB XML corpus into clause-level chunks with metadata
- [x] Transcribe NCC/ABCB diagrams to text — `backend/scripts/describe_images.py`
- [x] Decide embedding model — **Gemini `text-embedding-004`** (768-dim); wire up `services/embedding.py`
- [ ] Build hybrid retrieval (vector + BM25 + RRF) and reranker
- [ ] Wire chat endpoint to retrieval + generation, with citations/abstention
- [x] Decide PDF parser — **LlamaParse**; implement upload pipeline
- [ ] Document-to-requirement analysis (findings: missing / contradicted / addressed / needs review)
- [ ] Frontend: chat UI with citation view, upload UI with findings display
- [ ] Deploy to Render
