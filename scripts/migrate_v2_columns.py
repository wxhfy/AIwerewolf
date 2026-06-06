"""Run DB migration to add v2 columns for KnowledgeConfidence + DecisionTrace.

This adds the columns defined in the updated SQLAlchemy models to the
actual PostgreSQL database tables. Safe to re-run (uses IF NOT EXISTS).

Usage:
    python scripts/migrate_v2_columns.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from backend.db.database import SessionLocal
from backend.db.database import init_db

MIGRATIONS = {
    "strategy_knowledge_docs": [
        # L0-L4 Confidence Tier
        ("confidence_tier", "VARCHAR", "L3_strategic"),
        ("judge_agreement", "DOUBLE PRECISION", None),
        ("times_upvoted", "INTEGER", "0"),
        ("contradiction_count", "INTEGER", "0"),
        ("games_since_creation", "INTEGER", "0"),
        ("human_verdict", "VARCHAR", None),
        # Access Control
        ("visibility_scope", "VARCHAR", "'public'"),
        ("allowed_roles", "JSONB", None),
        ("deidentified", "BOOLEAN", "false"),
        ("contains_current_game_private_info", "BOOLEAN", "false"),
        # Applicability
        ("applicability_role", "VARCHAR", None),
        ("applicability_phase", "VARCHAR", None),
        ("min_players", "INTEGER", None),
        ("max_players", "INTEGER", None),
        ("required_public_facts", "JSONB", "'[]'"),
        ("forbidden_public_facts", "JSONB", "'[]'"),
        ("required_private_state", "JSONB", "'[]'"),
    ],
    "agent_decisions": [
        ("candidate_actions", "JSONB", None),
        ("visible_facts", "JSONB", None),
        ("confidence", "DOUBLE PRECISION", None),
        ("prompt_hash", "VARCHAR", None),
        ("cost_usd", "DOUBLE PRECISION", None),
        ("model_name", "VARCHAR", None),
        ("provider", "VARCHAR", None),
    ],
}


def main():
    init_db()
    db = SessionLocal()
    try:
        for table, columns in MIGRATIONS.items():
            print(f"\n=== {table} ===")
            for col_name, col_type, default_val in columns:
                default_clause = f" DEFAULT {default_val}" if default_val is not None else ""
                sql = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_name} {col_type}{default_clause}"
                try:
                    db.execute(text(sql))
                    db.commit()
                    print(f"  + {col_name} ({col_type})")
                except Exception as e:
                    db.rollback()
                    print(f"  ! {col_name}: {e}")

        print("\n=== Migration complete ===")

        # Verify
        for table in MIGRATIONS:
            result = db.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
                {"t": table},
            )
            cols = {row[0] for row in result.fetchall()}
            missing = [col[0] for col in MIGRATIONS[table] if col[0] not in cols]
            status = "OK" if not missing else f"MISSING: {missing}"
            print(f"  {table}: {len(cols)} columns — {status}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
