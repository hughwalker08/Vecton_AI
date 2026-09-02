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
    # One of: "bge-m3" (self-hosted) or "gemini" (API). TBD per project decisions doc.
    EMBEDDING_PROVIDER: str = "gemini"
    EMBEDDING_MODEL_NAME: str = "text-embedding-004"

    # --- LLM provider for generation ---
    LLM_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str = ""

    # --- Document parsing for user uploads ---
    # One of: "docling" (self-hosted) or "llamaparse" (external API - needs client sign-off)
    PDF_PARSER: str = "docling"
    LLAMAPARSE_API_KEY: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
