"""Persona library — DB seed + sampling.

Personas live in `personas` table so games can randomly draw a roster instead
of reusing the same eight names every match. Seeding is idempotent: on boot we
upsert the in-repo PERSONA_POOL so the table always has a baseline, but
anything previously added by an author / Track B tool is preserved.
"""

from __future__ import annotations

from random import Random
from typing import Any

from backend.agents.characters import PERSONA_POOL, build_system_prompt, _hydrate_persona
from backend.db.database import SessionLocal
from backend.db.models import Persona as PersonaRow


_PERSONA_FIELDS: tuple[str, ...] = (
    "mbti",
    "gender",
    "age",
    "basic_info",
    "style_label",
    "voice_rules",
    "relationships",
    "vocabulary_style",
    "speech_length_habit",
    "reasoning_style",
    "social_habit",
    "humor_style",
    "pressure_style",
    "uncertainty_style",
    "wolf_deception_style",
    "mistake_pattern",
    "logic_style",
    "trigger_topics",
    "werewolf_experience",
    "system_prompt",
)


def _row_to_dict(row: PersonaRow) -> dict[str, Any]:
    return {
        "name": row.name,
        "mbti": row.mbti or "",
        "gender": row.gender or "",
        "age": int(row.age or 0),
        "basic_info": row.basic_info or "",
        "style_label": row.style_label or "",
        "voice_rules": list(row.voice_rules or []),
        "relationships": list(row.relationships or []),
        "vocabulary_style": row.vocabulary_style or "",
        "speech_length_habit": row.speech_length_habit or "",
        "reasoning_style": row.reasoning_style or "",
        "social_habit": row.social_habit or "",
        "humor_style": row.humor_style or "",
        "pressure_style": row.pressure_style or "",
        "uncertainty_style": row.uncertainty_style or "",
        "wolf_deception_style": row.wolf_deception_style or "",
        "mistake_pattern": row.mistake_pattern or "",
        "logic_style": row.logic_style or "",
        "trigger_topics": list(row.trigger_topics or []),
        "werewolf_experience": row.werewolf_experience or "",
        "system_prompt": row.system_prompt or "",
    }


def _ensure_system_prompt(entry: dict) -> dict:
    """Make sure each persona dict carries a non-empty system_prompt."""
    if not entry.get("system_prompt"):
        persona = _hydrate_persona(entry)
        entry["system_prompt"] = persona.system_prompt
    return entry


def seed_personas() -> int:
    """Upsert the in-repo PERSONA_POOL into the personas table.

    Returns the number of rows newly inserted. Existing rows have blank fields
    filled in (including system_prompt), so once-edited personas survive
    future seeds.
    """
    db = SessionLocal()
    inserted = 0
    try:
        existing = {row.name: row for row in db.query(PersonaRow).all()}
        for entry in PERSONA_POOL:
            entry = _ensure_system_prompt(dict(entry))
            row = existing.get(entry["name"])
            if row is None:
                row = PersonaRow(name=entry["name"], source="wolfcha")
                db.add(row)
                inserted += 1
            for field_name in _PERSONA_FIELDS:
                current = getattr(row, field_name, None)
                if current in (None, "", [], 0):
                    setattr(row, field_name, entry.get(field_name, current))
        db.commit()
        return inserted
    finally:
        db.close()


def list_personas() -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        return [_row_to_dict(row) for row in db.query(PersonaRow).filter(PersonaRow.is_active.is_(True)).all()]
    finally:
        db.close()


def sample_personas(count: int, seed: int | None = None) -> list[dict[str, Any]]:
    """Randomly sample `count` distinct personas from the DB.

    Falls back to PERSONA_POOL when the table is empty (or smaller than the
    requested sample). The caller is responsible for hooking the sampled list
    into build_character_roster — that's where the player→persona mapping is
    established.
    """
    rng = Random(seed)
    available = list_personas()
    if len(available) < count:
        # Top up from PERSONA_POOL without duplicating by name.
        existing_names = {p["name"] for p in available}
        for entry in PERSONA_POOL:
            if entry["name"] in existing_names:
                continue
            available.append(entry)
            existing_names.add(entry["name"])
            if len(available) >= count:
                break
    if len(available) < count:
        # Still short — pad by reusing personas; happens only if PERSONA_POOL
        # itself is smaller than the table count, which we should never ship.
        while len(available) < count:
            available.append(rng.choice(available or PERSONA_POOL))
    rng.shuffle(available)
    return available[:count]
