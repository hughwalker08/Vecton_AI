<br />
<div align="center">

  <h2 align="center">Vecton AI — Construction Compliance Assistant 
  <br/> COMP3888_TH10_01</h2>

  <p align="center">
    A RAG (retreival augmented generative) AI-powered web application  developed specifically to answer questions about Australia's building rules using a knowledge base built from the official code (NCC Volume Two (Houses) and ABCB Housing Provisions), for the client Vecton AI as part of USYD's COMP3888 unit.
  </p>
  <br/>
</div>


<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#stack">Stack</a></li>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li><a href="#roadmap">Roadmap</a></li>
  </ol>
</details>



<!-- ABOUT THE PROJECT -->
## About The Project
The project aims to simplify the laborious process of going through NSW NCC, ABCB and other related compliance documents and requirements by providing a RAG AI Assistant service that aims to be reliable and trustworthy even in the high-stakes scenarios in which it is needed.
### Stack
- **Frontend:** React (Vite)
- **Backend:** FastAPI
- **Database:** Postgres + pgvector (via Supabase)
- **Embeddings:** Gemini `text-embedding-004` (768-dim)
- **Generation (LLM):** Gemini
- **Diagram/image description:** Gemini vision (`gemini-2.5-flash`)
- **PDF parsing:** LlamaParse 
- **Hosting:** Render

See [`backend/README.md`](backend/README.md) and [`frontend/README.md`](frontend/README.md) for full technical detail.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Built With
* [FastAPI](https://fastapi.tiangolo.com/)
* [React](https://react.dev/) + [Vite](https://vitejs.dev/)
* [PostgreSQL](https://www.postgresql.org/) +  [pgvector](https://github.com/pgvector/pgvector), via [Supabase](https://supabase.com/) (also Auth + Row-Level Security)
* [SQLAlchemy](https://www.sqlalchemy.org/) + [Alembic](https://alembic.sqlalchemy.org/)
* [Google Gemini API](https://ai.google.dev/) — embeddings, generation, vision
* [Hugging Face Inference](https://huggingface.co/docs/inference-providers) — cross-encoder reranking (`BAAI/bge-reranker-base`)
* [Render](https://render.com/) — hosting

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- GETTING STARTED -->
## Getting Started

To get a local copy up and running follow these simple example steps.

### Prerequisites

* Python 3.11+
* Node.js + npm

#### API and Project Codes Required
The following API and Project Codes need to go into the .env file
* A Supabase project (Postgres with the vector extension available)
* A Gemini API key (ai.google.dev) — a comma-separated pool of several teammates' keys is supported and recommended (see backend/README.md → "Multi-key Gemini rotation"), since the free tier's daily quota is easy to exhaust with one key
* A Hugging Face API token with "Inference Providers" permission (huggingface.co/settings/tokens)
* Supabase Auth's project URL + publishable key

### Installation
1. Clone the repo
    ```sh
    git clone https://github.sydney.edu.au/abai9699/COMP3888_TH10_01.git
    ```
2. Setup the Backend
    ```bash
    cd backend
    python -m venv venv && source venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env   # fill in the required API keys and URLs
    uvicorn app.main:app --reload
    ```
3. Setup the Frontend on a seperate terminal
    ```bash
    cd frontend
    npm install
    npm run dev
    ```

<p align="right">(<a href="#readme-top">back to top</a>)</p>




<!-- ROADMAP -->
## Roadmap

- [x] Parse NCC/ABCB XML corpus into clause-level chunks with metadata
- [x] Transcribe NCC/ABCB diagrams to text
- [x] Decide + wire up embedding model — Gemini `gemini-embedding-2`
- [x] Build hybrid retrieval (pgvector + Postgres full-text, fused with RRF) and a reranker (`BAAI/bge-reranker-base`)
- [x] Wire chat endpoint to retrieval + generation, with citations/abstention
- [x] Jurisdiction-aware retrieval and answers
- [x] Decide PDF parser (LlamaParse); implement upload pipeline — image
      extraction/transcription is live, text extraction is still pending sign-off
- [x] Document-to-requirement analysis engine (`POST /api/compliance/analyse`)
- [x] Frontend: chat UI with citation view
- [x] Deploy to Render (`render.yaml` blueprint)
- [X] Multi-turn conversation / chat history persistence
