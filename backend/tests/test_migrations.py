"""
Tests for the Alembic migration chain under backend/migrations/versions/.

Two tiers, per the testing plan:

  - Always runs (no database needed): walks the revision graph and checks
    it's a single, gapless, correctly-ordered chain, and that every version
    file actually imports (alembic.script.ScriptDirectory has to import
    each one to read its `revision`/`down_revision`, so just building it
    successfully already proves this).

  - Runs only when a real test database is reachable: applies every
    migration, then rolls them all back, against a genuinely disposable
    Postgres + pgvector instance -- a service container in CI, or a local
    throwaway database if you point TEST_DATABASE_URL at one. Skipped
    (not failed) when that isn't available, e.g. on a laptop with no
    Postgres installed.

    NEVER point TEST_DATABASE_URL at a real dev/shared database -- this
    upgrades to head and then downgrades all the way back to base,
    destroying every table these migrations own.

Migration 0004 links `user_profiles` to Supabase's own `auth.users` table
and reads `auth.uid()` in its RLS policies -- both provided by Supabase's
managed Postgres, not a vanilla one. A plain throwaway container (this is
exactly what CI will use) doesn't have them, so the DB fixture below stubs
just enough of `auth` to satisfy the migration's DDL. This was verified by
actually standing up a local Postgres 17 + pgvector instance and running
the full upgrade/downgrade cycle against it -- upgrading past 0004 failed
outright (`InvalidSchemaName: schema "auth" does not exist`, then
`UndefinedFunction: auth.uid()`) until both stubs were added.
"""

import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = BACKEND_DIR / "migrations" / "versions"


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def _script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(_alembic_config())


# ---------------------------------------------------------------------------
# Always runs: the revision graph itself, no database involved.
# ---------------------------------------------------------------------------


def test_migration_chain_has_exactly_one_head():
    """More than one head means a branch -- two migrations that both claim
    the same down_revision, which alembic can't linearly apply."""
    script = _script_directory()

    assert script.get_heads() == [script.get_current_head()]
    assert len(script.get_heads()) == 1


def test_migration_chain_is_gapless_and_matches_the_numbered_filenames():
    """Walking down_revision -> revision from base to head should visit
    every 000N file in order, with nothing missing and nothing branching
    off to the side."""
    script = _script_directory()

    revisions_oldest_first = [rev.revision for rev in reversed(list(script.walk_revisions()))]

    expected = sorted(p.stem.split("_", 1)[0] for p in MIGRATIONS_DIR.glob("0*.py"))

    assert revisions_oldest_first == expected


def test_every_migration_defines_upgrade_and_downgrade():
    """ScriptDirectory already had to successfully import every version
    file to build the graph above -- this additionally checks each one
    actually provides the two entry points alembic calls."""
    script = _script_directory()
    revisions = list(script.walk_revisions())

    assert len(revisions) == len(list(MIGRATIONS_DIR.glob("0*.py")))
    for rev in revisions:
        assert callable(getattr(rev.module, "upgrade", None)), rev.revision
        assert callable(getattr(rev.module, "downgrade", None)), rev.revision


# ---------------------------------------------------------------------------
# Runs only against a real, disposable database.
# ---------------------------------------------------------------------------


@pytest.fixture()
def migration_test_db(monkeypatch):
    """Points Settings.DATABASE_URL (and therefore migrations/env.py) at a
    throwaway Postgres + pgvector database for the duration of one test,
    stubbing just enough of Supabase's `auth` schema for migration 0004 to
    apply. Skips (doesn't fail) the test if TEST_DATABASE_URL isn't set or
    isn't reachable -- this is the "skipped on laptops without one" case
    from the testing plan.
    """
    db_url = os.environ.get("TEST_DATABASE_URL")
    if not db_url:
        pytest.skip(
            "TEST_DATABASE_URL not set -- skipping migration DB tests. Point it at a "
            "disposable Postgres + pgvector database to run these (never a real one: "
            "the test upgrades to head then downgrades all the way back to base)."
        )

    engine = sa.create_engine(db_url)
    try:
        with engine.connect() as conn:
            # Reset to a clean slate in case a previous interrupted run left
            # things half-migrated -- makes repeated local runs idempotent.
            conn.execute(sa.text("DROP TABLE IF EXISTS public.user_profiles CASCADE"))
            conn.execute(sa.text("DROP TABLE IF EXISTS public.clause_chunks CASCADE"))
            conn.execute(sa.text("DROP TABLE IF EXISTS public.alembic_version"))

            # Stub Supabase's auth schema (see module docstring) -- migration
            # 0001 creates the `vector` extension itself, so nothing needed there.
            conn.execute(sa.text("CREATE SCHEMA IF NOT EXISTS auth"))
            conn.execute(sa.text("CREATE TABLE IF NOT EXISTS auth.users (id uuid PRIMARY KEY)"))
            conn.execute(
                sa.text(
                    "CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid AS "
                    "$$ SELECT NULL::uuid $$ LANGUAGE sql STABLE"
                )
            )
            conn.commit()
    except sa.exc.OperationalError as exc:
        pytest.skip(f"TEST_DATABASE_URL is set but not reachable: {exc}")

    from app.core.config import settings

    monkeypatch.setattr(settings, "DATABASE_URL", db_url)
    return engine


def test_upgrade_to_head_then_downgrade_to_base_round_trips_cleanly(migration_test_db):
    engine = migration_test_db
    cfg = _alembic_config()
    inspector = sa.inspect(engine)

    command.upgrade(cfg, "head")
    inspector.clear_cache()
    tables = inspector.get_table_names(schema="public")
    assert "clause_chunks" in tables
    assert "user_profiles" in tables
    columns = {c["name"] for c in inspector.get_columns("clause_chunks", schema="public")}
    assert "text_tsv" in columns  # 0003
    assert "image_refs" in columns  # 0005

    command.downgrade(cfg, "base")
    inspector.clear_cache()
    tables = inspector.get_table_names(schema="public")
    assert "clause_chunks" not in tables
    assert "user_profiles" not in tables
