"""
Application settings, loaded from environment variables / .env file.

Copy .env.example to .env and fill in real values before running.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Vecton AI Construction Compliance Assistant"

    # Comma-separated origins allowed to call the API, e.g. "http://localhost:5173"
    CORS_ORIGINS: list[str] = ["*"]

    # --- Database (Supabase / Postgres + pgvector) ---
    DATABASE_URL: str = "postgresql://user:password@localhost:5432/vecton"

    # --- Embedding model ---
    # Decided: Gemini "gemini-embedding-2", 768-dim output. Must match whatever
    # model produced app/ingest/output/*.embedded.json (see the .meta.json next
    # to them, and scripts/embed_chunks.py) -- query and corpus vectors only
    # compare meaningfully when they come from the same model. The pgvector
    # column in models/clause_chunk.py must match EMBEDDING_DIM.
    EMBEDDING_PROVIDER: str = "gemini"
    EMBEDDING_MODEL_NAME: str = "gemini-embedding-2"
    EMBEDDING_DIM: int = 768

    # --- LLM provider for generation ---
    # Decided: Gemini.
    LLM_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str = ""
    # Optional: several teammates' keys, comma-separated, so the app rotates
    # to the next one when a key hits its rate limit or daily quota instead
    # of failing (see app/services/gemini_keys.py). Overrides GEMINI_API_KEY
    # when set. Real values belong in backend/.env (gitignored) or a Render
    # dashboard env var (render.yaml) -- never in git.
    GEMINI_API_KEYS: str = ""
    # gemini-2.5-flash was retired for new API keys (404 from Google as of
    # 2026-09); gemini-3.6-flash is Google's recommended direct replacement.
    LLM_MODEL_NAME: str = "gemini-3.6-flash"

    # --- Vision model for describing NCC/ABCB diagrams and figures ---
    # Used by services/image_description.py and scripts/describe_images.py.
    # Shares GEMINI_API_KEY above.
    VISION_MODEL_NAME: str = "gemini-2.5-flash"

    # --- Reranking: second pass over hybrid_search's fused candidates ---
    # Decided: BAAI/bge-reranker-base (cross-encoder), hosted via the Hugging
    # Face Inference router rather than run locally (avoids a torch/
    # transformers dependency in the backend). See app/services/retrieval.py.
    RERANKER_MODEL_NAME: str = "BAAI/bge-reranker-base"
    HF_API_TOKEN: str = ""

    # --- Document parsing for user uploads ---
    # Decided: "llamaparse" for PDF (external API - needs client sign-off).
    # DOCX is parsed locally via python-docx regardless of this setting.
    PDF_PARSER: str = "llamaparse"
    LLAMAPARSE_API_KEY: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def gemini_api_keys(self) -> list[str]:
        """All configured Gemini keys, in rotation order (de-duplicated).

        GEMINI_API_KEYS (comma-separated) wins over the single GEMINI_API_KEY
        when both are set.
        """
        raw = self.GEMINI_API_KEYS or self.GEMINI_API_KEY
        seen: set[str] = set()
        keys: list[str] = []
        for candidate in raw.split(","):
            candidate = candidate.strip()
            if candidate and candidate not in seen:
                seen.add(candidate)
                keys.append(candidate)
        return keys


settings = Settings()
