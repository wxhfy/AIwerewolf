"""Migrate historical games from local SQLite to PostgreSQL.

Why this exists:
    The project briefly stored data in SQLite (`data/werewolf.db`) before the
    `werewolf-pg` Docker container came up on 2026-05-21 17:16. The 34 early
    games captured before the switchover are still useful for retrospectives,
    so this script copies them into PG without touching anything that already
    lives in PG.

Behaviour:
    * Reads from data/werewolf.db using a separate SQLAlchemy engine.
    * Writes to the engine returned by ``backend.db.database`` (i.e. whatever
      DATABASE_URL points at; refuses to run if it resolves to SQLite to avoid
      copying onto itself).
    * Skips rows whose primary key already exists in PG (idempotent — safe to
      re-run).
    * Preserves original UUIDs and ``created_at`` timestamps so the merged
      history stays chronologically meaningful.
    * Backs up the source DB to ``data/werewolf.db.bak`` on success.

Run:
    python scripts/migrate_sqlite_to_pg.py [--dry-run] [--keep-bak]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy import inspect
from sqlalchemy import text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.db.database import engine as pg_engine  # noqa: E402
from backend.db.models import AgentDecision  # noqa: E402
from backend.db.models import Base  # noqa: E402
from backend.db.models import Evaluation  # noqa: E402
from backend.db.models import Game  # noqa: E402
from backend.db.models import GameEvent  # noqa: E402
from backend.db.models import GameSnapshot  # noqa: E402
from backend.db.models import Player  # noqa: E402
from backend.db.models import Vote  # noqa: E402

# Migration order matters: parents before children (FK).
MIGRATION_ORDER: tuple[type[Base], ...] = (
    Game,
    Player,
    GameEvent,
    AgentDecision,
    GameSnapshot,
    Vote,
    Evaluation,
)

SQLITE_PATH = ROOT / "data" / "werewolf.db"
SQLITE_URL = f"sqlite:///{SQLITE_PATH}"


def _existing_ids(pg_session: Session, model: type[Base]) -> set[str]:
    return {row[0] for row in pg_session.execute(text(f"SELECT id FROM {model.__tablename__}"))}


def _shared_columns(model: type[Base], sqlite_engine) -> list[str]:
    """Columns that exist in both the model and the SQLite table."""
    model_cols = {c.name for c in model.__table__.columns}
    sqlite_cols = {c["name"] for c in inspect(sqlite_engine).get_columns(model.__tablename__)}
    return sorted(model_cols & sqlite_cols)


def _copy_table(
    model: type[Base],
    sqlite_engine,
    pg_session: Session,
    dry_run: bool,
) -> tuple[int, int]:
    """Copy rows. Returns (inserted, skipped)."""
    existing = _existing_ids(pg_session, model)
    cols = _shared_columns(model, sqlite_engine)
    if not cols:
        return 0, 0
    select_sql = f"SELECT {', '.join(cols)} FROM {model.__tablename__}"

    inserted = skipped = 0
    with sqlite_engine.connect() as src_conn:
        for row in src_conn.execute(text(select_sql)).mappings():
            row_id = row["id"]
            if row_id in existing:
                skipped += 1
                continue
            if dry_run:
                inserted += 1
                continue
            # Fields absent in SQLite fall back to model defaults.
            pg_session.add(model(**dict(row)))
            inserted += 1
            existing.add(row_id)

    if not dry_run:
        pg_session.commit()
    return inserted, skipped


def migrate(dry_run: bool = False, keep_bak: bool = True) -> None:
    if not SQLITE_PATH.exists():
        print(f"[skip] {SQLITE_PATH} not found — nothing to migrate.")
        return

    if pg_engine.dialect.name != "postgresql":
        raise SystemExit(
            f"refuse to run: target engine is {pg_engine.dialect.name!r}, "
            f"expected postgresql. Set DATABASE_URL in .env first."
        )

    print(f"[source] {SQLITE_URL}")
    print(f"[target] {pg_engine.url}")
    print(f"[mode]   {'DRY RUN' if dry_run else 'WRITE'}\n")

    sqlite_engine = create_engine(SQLITE_URL)

    with Session(pg_engine) as dst:
        totals_in = totals_skip = 0
        for model in MIGRATION_ORDER:
            inserted, skipped = _copy_table(model, sqlite_engine, dst, dry_run=dry_run)
            print(f"  {model.__tablename__:<18} +{inserted:>5}  (skipped {skipped})")
            totals_in += inserted
            totals_skip += skipped

    print(f"\nTotal: inserted={totals_in}  skipped={totals_skip}")

    if dry_run or totals_in == 0:
        return

    bak = SQLITE_PATH.with_suffix(".db.bak")
    if keep_bak:
        shutil.copy2(SQLITE_PATH, bak)
        print(f"[backup] {bak}")
    else:
        print("[backup] skipped (--no-keep-bak)")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="report rows without writing")
    p.add_argument(
        "--no-keep-bak",
        dest="keep_bak",
        action="store_false",
        help="don't copy data/werewolf.db to .bak after migration",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    migrate(dry_run=args.dry_run, keep_bak=args.keep_bak)
