from __future__ import annotations

import os
from typing import Any

from backend.application.analysis.reflection_engine import Reflector
from backend.application.analysis.reflection_engine import save_reflections_to_db
from backend.engine.models import GameEvent
from backend.engine.models import GameState
from backend.llm import create_client


def reflection_enabled() -> bool:
    value = os.getenv("COGNITIVE_ENABLE_REFLECTION", "").strip().lower()
    return value not in {"0", "false", "no", "off"}


def run_agent_reflections(state: GameState) -> int:
    """Rebuild per-agent reflection input from durable match projections."""
    if not reflection_enabled():
        return 0

    winner = state.winner.value if state.winner else None
    agent_states = [_build_agent_state(state, player.id, winner) for player in state.players if player.is_ai]
    if not agent_states:
        return 0

    results = Reflector(client=create_client()).reflect_game(state.id, agent_states)
    return save_reflections_to_db(results, state.id) if results else 0


def _build_agent_state(state: GameState, player_id: str, winner: str | None) -> dict[str, Any]:
    player = state.player(player_id)
    decisions = []
    for record in state.decision_records:
        if record.player_id != player_id:
            continue
        action = dict(record.parsed_action or {})
        decisions.append(
            {
                "action_type": action.get("action_type") or record.request or record.phase,
                "target": action.get("target_id") or action.get("target") or "",
                "speech": action.get("speech") or record.raw_output or "",
                "day": record.day,
                "phase": record.phase,
            }
        )

    visible_events = [
        _reflection_event(event)
        for event in state.events
        if event.visibility == "public" or player_id in event.visible_to
    ]
    return {
        "player_id": player.id,
        "player_name": player.name,
        "role": player.role.value,
        "persona": dict(player.persona or {}),
        "mind": {},
        "won": winner == player.alignment.value,
        "decisions": decisions[-30:],
        "game_events": visible_events[-40:],
    }


def _reflection_event(event: GameEvent) -> dict[str, Any]:
    payload = dict(event.payload or {})
    if event.type.value == "CHAT_MESSAGE":
        actor = payload.get("actor_name") or payload.get("speaker") or payload.get("actor_id") or ""
        description = f"{actor}: {str(payload.get('speech') or '')[:120]}"
    elif event.type.value == "VOTE_CAST":
        voter = payload.get("voter_name") or payload.get("voter_id") or ""
        target = payload.get("target_name") or payload.get("target_id") or ""
        description = f"{voter} voted for {target}"
    elif event.type.value == "PLAYER_DIED":
        name = payload.get("player_name") or payload.get("player_id") or ""
        description = f"{name} died ({payload.get('cause') or payload.get('reason') or 'unknown'})"
    else:
        description = str(payload)[:120]
    return {
        "type": event.type.value,
        "day": event.day,
        "phase": event.phase.value,
        "description": description,
    }
