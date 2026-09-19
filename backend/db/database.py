from __future__ import annotations

import os
from contextlib import nullcontext
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy import event
from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from backend.llm.env import load_env_file

# Make sure .env is read before we look at DATABASE_URL.
load_env_file()

# PostgreSQL via DATABASE_URL env, fallback to local SQLite for dev
DATABASE_URL = os.getenv("DATABASE_URL", "")

if DATABASE_URL:
    # PostgreSQL (Supabase / cloud / local pg)
    SQLALCHEMY_DATABASE_URL = DATABASE_URL
    _pool_size = int(os.getenv("DB_POOL_SIZE", "10"))
    _max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "10"))
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=_pool_size,
        max_overflow=_max_overflow,
    )
else:
    # SQLite fallback for local development
    sqlite_path = os.getenv("AIWEREWOLF_SQLITE_PATH", "").strip()
    DB_PATH = (
        Path(sqlite_path).expanduser()
        if sqlite_path
        else Path(__file__).resolve().parent.parent.parent / "data" / "werewolf.db"
    )
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _normalize_psycopg2_url(url: str) -> str:
    if url.startswith("postgresql+"):
        return "postgresql://" + url.split("://", 1)[1]
    if url.startswith("postgres+"):
        return "postgres://" + url.split("://", 1)[1]
    return url


DEFAULT_DB_URL = _normalize_psycopg2_url(
    DATABASE_URL
    or os.getenv("AIWEREWOLF_DB_URL", "")
    or (
        ""
        if os.getenv("AIWEREWOLF_SKIP_DOTENV", "").lower() in {"1", "true", "yes", "on"}
        else "postgresql://werewolf:werewolf_dev_password@127.0.0.1:5433/werewolf"
    )
)

_db_initialized = False


def _ensure_event_stream_schema(connection: Connection | None = None) -> None:
    """Bridge existing local databases until Alembic becomes authoritative."""
    bind = connection or engine
    inspector = inspect(bind)
    if "game_snapshots" not in inspector.get_table_names():
        return
    snapshot_columns = {column["name"] for column in inspector.get_columns("game_snapshots")}
    owns_transaction = connection is None
    context = engine.begin() if owns_transaction else nullcontext(connection)
    with context as conn:
        added_seq = "seq" not in snapshot_columns
        if added_seq:
            conn.exec_driver_sql("ALTER TABLE game_snapshots ADD COLUMN seq INTEGER NOT NULL DEFAULT 0")
        # seq=0 is a valid initial snapshot. Backfill only when this migration
        # has just introduced the column and every historical row got default 0.
        if added_seq:
            if engine.dialect.name == "sqlite":
                conn.exec_driver_sql("UPDATE game_snapshots SET seq = rowid")
            else:
                conn.exec_driver_sql(
                    """
                    WITH ranked AS (
                        SELECT id, ROW_NUMBER() OVER (PARTITION BY game_id ORDER BY created_at, id) AS new_seq
                        FROM game_snapshots
                    )
                    UPDATE game_snapshots AS snapshot
                    SET seq = ranked.new_seq
                    FROM ranked
                    WHERE snapshot.id = ranked.id
                    """
                )
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_game_snapshots_game_seq ON game_snapshots (game_id, seq)"
        )
        conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_game_events_game_seq ON game_events (game_id, seq)")
def init_db() -> None:
    global _db_initialized
    if _db_initialized:
        return
    if os.getenv("REQUIRE_DB", "").lower() == "true":
        try:
            import psycopg2

            conn = psycopg2.connect(_normalize_psycopg2_url(DATABASE_URL), connect_timeout=5)
            conn.close()
        except Exception as e:
            raise RuntimeError(f"STRICT MODE: REQUIRE_DB=true but DB unavailable: {e}")
    from backend.db.models import Base

    if engine.dialect.name == "postgresql":
        # API and worker containers may boot together. PostgreSQL DDL is not
        # race-free under concurrent create_all calls, so serialize bootstrap.
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT pg_advisory_lock(hashtext('aiwerewolf_schema_migration'))")
            try:
                Base.metadata.create_all(bind=connection)
                _ensure_event_stream_schema(connection)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.exec_driver_sql("SELECT pg_advisory_unlock(hashtext('aiwerewolf_schema_migration'))")
                connection.commit()
    else:
        Base.metadata.create_all(bind=engine)
        _ensure_event_stream_schema()
    # Seed the persona library on first boot so games can sample from DB even
    # before any human ever adds a custom persona.
    try:
        from backend.db.persona_db import seed_personas

        seed_personas()
    except Exception:
        # Seeding is best-effort — never block startup on it.
        pass
    _db_initialized = True


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
