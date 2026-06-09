from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from time import time
from typing import Any
from uuid import uuid4


@dataclass
class RoomCreateRequest:
    name: str = "Demo Room"
    seed: int = 7
    player_count: int = 7
    agent_type: str = "llm"
    human_seat: int | None = None
    rule_pack_id: str = "wolfcha-default"
    llm_config: dict[str, Any] | None = None


@dataclass
class RoomRecord:
    id: str
    name: str
    seed: int
    player_count: int
    agent_type: str
    human_seat: int | None = None
    rule_pack_id: str = "wolfcha-default"
    llm_config: dict[str, Any] | None = None
    status: str = "idle"
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)
    current_game_id: str | None = None
    game_history: list[str] = field(default_factory=list)
    latest_snapshot: dict[str, Any] | None = None

    @classmethod
    def create(
        cls,
        name: str,
        seed: int,
        player_count: int,
        agent_type: str,
        human_seat: int | None = None,
        rule_pack_id: str = "wolfcha-default",
        llm_config: dict[str, Any] | None = None,
    ) -> RoomRecord:
        return cls(
            id=str(uuid4()),
            name=name,
            seed=seed,
            player_count=player_count,
            agent_type=agent_type,
            human_seat=human_seat,
            rule_pack_id=rule_pack_id,
            llm_config=llm_config,
        )

    def to_dict(self) -> dict[str, Any]:
        safe_llm = self._safe_llm_config()
        return {
            "id": self.id,
            "name": self.name,
            "seed": self.seed,
            "player_count": self.player_count,
            "agent_type": self.agent_type,
            "human_seat": self.human_seat,
            "rule_pack_id": self.rule_pack_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "current_game_id": self.current_game_id,
            "game_history": list(self.game_history),
            "latest_snapshot": self.latest_snapshot,
            "llm_configured": bool(self.llm_config and self.llm_config.get("api_key")),
            "llm_provider": safe_llm.get("provider"),
            "llm_model": safe_llm.get("model"),
            "llm_base_url": safe_llm.get("base_url"),
        }

    def _safe_llm_config(self) -> dict[str, str]:
        if not self.llm_config:
            return {}
        return {
            key: str(self.llm_config.get(key) or "")
            for key in ("provider", "model", "base_url")
            if self.llm_config.get(key)
        }
