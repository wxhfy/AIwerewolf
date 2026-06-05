from __future__ import annotations

from typing import Any

from backend.engine.models import EventType
from backend.engine.models import GameEvent


def build_day_summary(events: list[GameEvent], day: int) -> tuple[list[str], list[dict[str, Any]]]:
    day_events = [event for event in events if event.day == day and event.visibility == "public"]
    bullets: list[str] = []
    facts: list[dict[str, Any]] = []

    for event in day_events:
        payload = event.payload
        if event.type == EventType.CHAT_MESSAGE:
            speech = str(payload.get("speech", "")).strip()
            actor_name = payload.get("actor_name", "Unknown")
            if speech:
                bullets.append(f"{actor_name}: {speech}")
                facts.append(
                    {
                        "type": "speech",
                        "day": day,
                        "speaker_name": actor_name,
                        "speaker_id": payload.get("actor_id"),
                        "content": speech,
                    }
                )
        elif event.type == EventType.VOTE_CAST:
            voter = payload.get("voter_name", "Unknown")
            target = payload.get("target_name", "Unknown")
            reasoning = str(payload.get("reasoning", "")).strip()
            line = f"{voter} voted for {target}"
            if reasoning:
                line += f" ({reasoning})"
            bullets.append(line)
            facts.append(
                {
                    "type": "vote",
                    "day": day,
                    "voter_name": voter,
                    "voter_id": payload.get("voter_id"),
                    "target_name": target,
                    "target_id": payload.get("target_id"),
                    "reasoning": reasoning,
                }
            )
        elif event.type == EventType.PLAYER_DIED:
            name = payload.get("player_name", "Unknown")
            reason = payload.get("reason", "unknown")
            bullets.append(f"{name} died by {reason}")
            facts.append(
                {
                    "type": "death",
                    "day": day,
                    "player_name": name,
                    "player_id": payload.get("player_id"),
                    "reason": reason,
                }
            )
        elif event.type == EventType.HUNTER_SHOT:
            hunter = payload.get("hunter_name", "Unknown")
            target = payload.get("target_name", "Unknown")
            bullets.append(f"{hunter} shot {target}")
            facts.append(
                {
                    "type": "hunter_shot",
                    "day": day,
                    "hunter_name": hunter,
                    "hunter_id": payload.get("hunter_id"),
                    "target_name": target,
                    "target_id": payload.get("target_id"),
                }
            )
        elif event.type == EventType.GAME_END:
            winner = payload.get("winner")
            reason = payload.get("reason", "")
            bullets.append(f"Game ended: {winner} ({reason})")
            facts.append({"type": "game_end", "day": day, "winner": winner, "reason": reason})

    return bullets, facts
