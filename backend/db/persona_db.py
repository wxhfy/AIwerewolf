"""Persona library — DB seed + sampling.

Personas live in `personas` table so games can randomly draw a roster instead
of reusing the same eight names every match. Seeding is idempotent: on boot we
upsert the in-repo PERSONA_POOL so the table always has a baseline, but
anything previously added by an author / Track B tool is preserved.
"""

from __future__ import annotations

from random import Random
from typing import Any

from backend.agents.characters import PERSONA_POOL
from backend.agents.characters import _hydrate_persona
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


def create_persona(data: dict[str, Any]) -> dict[str, Any]:
    """Create a new persona in the DB. Raises ValueError on duplicate name."""
    db = SessionLocal()
    try:
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError("name is required")
        existing = db.query(PersonaRow).filter(PersonaRow.name == name).first()
        if existing:
            raise ValueError(f"Persona '{name}' already exists")
        row = PersonaRow(name=name, source="manual")
        _apply_persona_fields(row, data)
        db.add(row)
        db.commit()
        db.refresh(row)
        return _row_to_dict(row)
    finally:
        db.close()


def update_persona(name: str, data: dict[str, Any]) -> dict[str, Any]:
    """Update an existing persona. Raises KeyError if not found."""
    db = SessionLocal()
    try:
        row = db.query(PersonaRow).filter(PersonaRow.name == name).first()
        if row is None:
            raise KeyError(f"Persona '{name}' not found")
        _apply_persona_fields(row, data)
        # Regenerate system_prompt when core fields change
        entry = _row_to_dict(row)
        persona = _hydrate_persona(entry)
        row.system_prompt = persona.system_prompt
        db.commit()
        db.refresh(row)
        return _row_to_dict(row)
    finally:
        db.close()


def _apply_persona_fields(row: PersonaRow, data: dict[str, Any]) -> None:
    """Apply persona field values from a dict to a DB row."""
    for field_name in _PERSONA_FIELDS:
        if field_name in data:
            value = data[field_name]
            if field_name in ("voice_rules", "relationships", "trigger_topics"):
                value = list(value) if isinstance(value, (list, tuple)) else []
            setattr(row, field_name, value)
    # Non-field extras
    if "name" in data and data["name"] != row.name:
        row.name = str(data["name"]).strip()
    for scalar in (
        "mbti",
        "gender",
        "basic_info",
        "style_label",
        "vocabulary_style",
        "speech_length_habit",
        "reasoning_style",
        "social_habit",
        "humor_style",
        "pressure_style",
        "uncertainty_style",
        "mistake_pattern",
        "logic_style",
        "werewolf_experience",
        "system_prompt",
    ):
        if scalar in data:
            setattr(row, scalar, str(data[scalar] or ""))
    if "age" in data:
        try:
            row.age = int(data["age"])
        except (ValueError, TypeError):
            row.age = 0


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
