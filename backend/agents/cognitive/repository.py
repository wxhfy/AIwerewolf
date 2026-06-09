"""Data access layer — loads strategy data from PostgreSQL.

Single Responsibility: database queries for strategy/profile data.
No game logic, no LLM calls — pure data access.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from backend.agents.cognitive.profiles import PROFILES
from backend.agents.cognitive.profiles import Profile
from backend.agents.cognitive.profiles import clone_profile
from backend.agents.cognitive.profiles import get_profiles

_ROLE_PROFILE_QUERY = """
    SELECT role, goal, speech_policy, vote_policy, skill_policy, risk_rules
    FROM role_strategy_cards
    WHERE status = 'active' AND version = 'v2'
"""


def load_profiles_from_db(conn_str: str = "") -> dict[str, Profile]:
    """Load role profiles from role_strategy_cards table.

    Falls back to hardcoded profiles if DB is unavailable.
    """
    try:
        profiles = {}
        for role, goal, speech, vote, skill, risk in _fetch_active_role_card_rows(conn_str):
            _parse_jsonb(speech)
            _parse_jsonb(vote)
            _parse_jsonb(skill)
            _parse_jsonb(risk)
            profiles[role] = _profile_from_role_card_row(role, goal)

        return profiles if profiles else get_profiles()

    except Exception:
        return get_profiles()


def load_profile_from_db(role: str, conn_str: str = "") -> Profile:
    """Load a single role profile from DB."""
    profiles = load_profiles_from_db(conn_str)
    return clone_profile(profiles.get(role, PROFILES.get(role, PROFILES["Villager"])))


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


def _profile_from_role_card_row(role: str, goal: str | None) -> Profile:
    base = clone_profile(PROFILES.get(role, PROFILES["Villager"]))
    return replace(base, goal=goal or base.goal, personality=list(base.personality))


def _parse_jsonb(value: Any) -> list[str]:
    """Parse a JSONB column value into a list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, ValueError):
            return []
    return []
