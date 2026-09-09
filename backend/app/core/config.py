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
    # Decided: Gemini "text-embedding-004", 768-dim output. The pgvector column
    # in models/clause_chunk.py must match this dimension.
    EMBEDDING_PROVIDER: str = "gemini"
    EMBEDDING_MODEL_NAME: str = "text-embedding-004"
    EMBEDDING_DIM: int = 768

    # --- LLM provider for generation ---
    # Decided: Gemini.
    LLM_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str = ""

    # --- Vision model for describing NCC/ABCB diagrams and figures ---
    # Used by services/image_description.py and scripts/describe_images.py.
    # Shares GEMINI_API_KEY above.
    VISION_MODEL_NAME: str = "gemini-2.5-flash"

    # --- Document parsing for user uploads ---
    # Decided: "llamaparse" for PDF (external API - needs client sign-off).
    # DOCX is parsed locally via python-docx regardless of this setting.
    PDF_PARSER: str = "llamaparse"
    LLAMAPARSE_API_KEY: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
