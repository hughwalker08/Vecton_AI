"""
Database session management (Postgres + pgvector via Supabase).

Skeleton only — no models/tables are defined yet. Once the clause chunk
schema is finalised (see planning doc: text, clause_id, hierarchy, heading,
doc, cross_refs, defined_terms, source_url, retrieved date, embedding),
add SQLAlchemy models under app/models and Alembic migrations here.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a DB session and closes it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
