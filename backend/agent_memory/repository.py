from __future__ import annotations

from backend.agent_memory.models import ActorMemoryState
from backend.db.database import SessionLocal
from backend.db.models import ActorMemory


class SqlActorMemoryRepository:
    """Persist one compact cognitive state per actor and match."""

    def load(self, episode_id: str, actor_id: str) -> ActorMemoryState | None:
        with SessionLocal() as db:
            row = (
                db.query(ActorMemory)
                .filter(ActorMemory.game_id == episode_id, ActorMemory.player_id == actor_id)
                .first()
            )
            if row is None:
                return None
            return ActorMemoryState.from_dict(dict(row.state or {}))

    def save(self, state: ActorMemoryState) -> None:
        with SessionLocal.begin() as db:
            row = (
                db.query(ActorMemory)
                .filter(ActorMemory.game_id == state.episode_id, ActorMemory.player_id == state.actor_id)
                .first()
            )
            if row is None:
                row = ActorMemory(game_id=state.episode_id, player_id=state.actor_id)
                db.add(row)
            row.version = state.version
            row.last_event_seq = state.last_event_seq
            row.state = state.to_dict()
