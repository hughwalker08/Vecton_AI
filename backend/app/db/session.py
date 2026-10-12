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

# Every connection is held open and reused, never opened per request: a fresh
# one to the Supabase pooler (Seoul) costs a TCP + TLS + auth handshake across
# the Pacific from Render. SQLAlchemy's default (5 kept, 10 overflow) closes
# overflow connections as soon as they're returned, so each burst of
# concurrent users past 5 re-paid that handshake. Keeping all of them in the
# pool holds the same 15-connection ceiling (the session pooler's client
# limit on Supabase's smallest compute) while opening each one only once --
# measured: 5 bursts of 12 concurrent searches went from 40 handshakes to 12.
# The pool only grows to what concurrency actually needs. pool_recycle
# retires connections before the pooler's idle timeout can drop them;
# pool_pre_ping still catches any it dropped anyway.
engine = create_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=0,
    pool_recycle=300,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a DB session and closes it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
