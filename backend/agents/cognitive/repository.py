"""Data access layer — loads strategy data from PostgreSQL.

Single Responsibility: database queries for strategy/profile data.
No game logic, no LLM calls — pure data access.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from backend.agents.cognitive.profiles import Profile
from backend.agents.cognitive.profiles import clone_profile
from backend.agents.cognitive.profiles import get_profile
from backend.agents.cognitive.profiles import get_profiles

_ROLE_PROFILE_QUERY = """
    SELECT role, goal
    FROM role_strategy_cards
    WHERE status = 'active' AND version = 'v2'
"""


def load_profiles_from_db(conn_str: str = "") -> dict[str, Profile]:
    """Load role profiles from role_strategy_cards table.

    Falls back to hardcoded profiles if DB is unavailable.
    """
    try:
        profiles = {}
        for row in _fetch_active_role_card_rows(conn_str):
            parsed = _role_goal_from_row(row)
            if parsed is None:
                continue
            role, goal = parsed
            profiles[role] = _profile_from_role_card_row(role, goal)

        return profiles if profiles else get_profiles()

    except Exception:
        return get_profiles()


def load_profile_from_db(role: str, conn_str: str = "") -> Profile:
    """Load a single role profile from DB."""
    profiles = load_profiles_from_db(conn_str)
    profile = profiles.get(role)
    return clone_profile(profile) if profile else get_profile(role)


def _fetch_active_role_card_rows(conn_str: str = "") -> list[tuple[Any, ...]]:
    import psycopg2

    conn = psycopg2.connect(conn_str or _default_db_url())
    try:
        cursor = conn.cursor()
        try:
            cursor.execute(_ROLE_PROFILE_QUERY)
            return cursor.fetchall()
        finally:
            cursor_close = getattr(cursor, "close", None)
            if callable(cursor_close):
                cursor_close()
    finally:
        conn.close()


def _default_db_url() -> str:
    from backend.db.database import DEFAULT_DB_URL

    return DEFAULT_DB_URL


def _role_goal_from_row(row: Any) -> tuple[str, str | None] | None:
    if isinstance(row, dict):
        role = str(row.get("role", "")).strip()
        return (role, row.get("goal")) if role else None
    if not row:
        return None
    return str(row[0]), row[1] if len(row) > 1 else None


def _profile_from_role_card_row(role: str, goal: str | None) -> Profile:
    base = get_profile(role)
    return replace(base, goal=goal or base.goal, personality=list(base.personality))
