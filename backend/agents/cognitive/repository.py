"""Data access layer — loads strategy data from PostgreSQL.

Single Responsibility: database queries for strategy/profile data.
No game logic, no LLM calls — pure data access.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from backend.agents.cognitive.profiles import Profile, PROFILES


def load_profiles_from_db(conn_str: str = "") -> Dict[str, Profile]:
    """Load role profiles from role_strategy_cards table.

    Falls back to hardcoded profiles if DB is unavailable.
    """
    try:
        import psycopg2
        conn = psycopg2.connect(conn_str or "postgresql://werewolf:wolf_secret_2026@127.0.0.1:5433/werewolf")
        c = conn.cursor()
        c.execute("""
            SELECT role, goal, speech_policy, vote_policy, skill_policy, risk_rules
            FROM role_strategy_cards
            WHERE status = 'active' AND version = 'v2'
        """)

        profiles = {}
        for role, goal, speech, vote, skill, risk in c.fetchall():
            speech_list = _parse_jsonb(speech)
            vote_list = _parse_jsonb(vote)
            skill_list = _parse_jsonb(skill)
            risk_list = _parse_jsonb(risk)

            # Build Profile from DB data
            base = PROFILES.get(role, PROFILES["Villager"])
            profiles[role] = Profile(
                role=base.role,
                goal=goal or base.goal,
                backstory=base.backstory,
                personality=base.personality,
                speech_style=base.speech_style,
                table_goal=base.table_goal,
                pressure_style=base.pressure_style,
                reveal_policy=base.reveal_policy,
                wolf_disguise=base.wolf_disguise,
                persona=base.persona,
                mind=base.mind,
            )

        conn.close()
        return profiles if profiles else PROFILES

    except Exception:
        return PROFILES


def load_profile_from_db(role: str, conn_str: str = "") -> Profile:
    """Load a single role profile from DB."""
    profiles = load_profiles_from_db(conn_str)
    return profiles.get(role, PROFILES.get(role, PROFILES["Villager"]))


def _parse_jsonb(value: Any) -> List[str]:
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
