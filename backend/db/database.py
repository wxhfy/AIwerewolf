from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
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
    or "postgresql://werewolf:werewolf_dev_password@127.0.0.1:5433/werewolf"
)

_db_initialized = False


def init_db() -> None:
    global _db_initialized
    if _db_initialized:
        return
    if os.getenv("REQUIRE_DB", "").lower() == "true":
        try:
            import psycopg2

            conn = psycopg2.connect(DATABASE_URL, connect_timeout=5)
            conn.close()
        except Exception as e:
            raise RuntimeError(f"STRICT MODE: REQUIRE_DB=true but DB unavailable: {e}")
    from backend.db.models import Base

    Base.metadata.create_all(bind=engine)
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
