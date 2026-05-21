from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any
from uuid import uuid4


@dataclass
class RoomCreateRequest:
    name: str = "Demo Room"
    seed: int = 7
    player_count: int = 7
    agent_type: str = "heuristic"


@dataclass
class RoomRecord:
    id: str
    name: str
    seed: int
    player_count: int
    agent_type: str
    status: str = "idle"
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)
    current_game_id: str | None = None
    game_history: list[str] = field(default_factory=list)
    latest_snapshot: dict[str, Any] | None = None

    @classmethod
    def create(cls, name: str, seed: int, player_count: int, agent_type: str) -> "RoomRecord":
        return cls(
            id=str(uuid4()),
            name=name,
            seed=seed,
            player_count=player_count,
            agent_type=agent_type,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "seed": self.seed,
            "player_count": self.player_count,
            "agent_type": self.agent_type,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "current_game_id": self.current_game_id,
            "game_history": list(self.game_history),
            "latest_snapshot": self.latest_snapshot,
        }
