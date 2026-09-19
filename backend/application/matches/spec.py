from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from typing import Any

from backend.engine.game import WerewolfGame
from backend.engine.models import Alignment
from backend.engine.models import Player
from backend.engine.models import Role


@dataclass(frozen=True)
class MatchExecutionSpec:
    """Serializable input required to reproduce a prepared AI match roster."""

    match_id: str
    room_id: str
    seed: int
    player_count: int
    agent_type: str
    rule_pack_id: str
    phase_delay_ms: float
    players: list[dict[str, Any]]
    personas: list[dict[str, Any]]
    llm_config: dict[str, str]

    @classmethod
    def from_game(
        cls,
        game: WerewolfGame,
        *,
        room_id: str,
        seed: int,
        agent_type: str,
        rule_pack_id: str,
        phase_delay_ms: float = 0,
        llm_config: dict[str, Any] | None = None,
    ) -> MatchExecutionSpec:
        players = [
            {
                "id": player.id,
                "seat": player.seat,
                "name": player.name,
                "role": player.role.value,
                "alignment": player.alignment.value,
                "is_ai": player.is_ai,
                "agent_type": player.agent_type,
                "model_name": player.model_name,
                "prompt_version": player.prompt_version,
                "persona": dict(player.persona),
            }
            for player in game.state.players
        ]
        personas = [asdict(game.characters[player.id].persona) for player in game.state.players]
        safe_llm = {
            key: str(value).rstrip("/") if key == "base_url" else str(value)
            for key, value in (llm_config or {}).items()
            if key in {"provider", "model", "base_url"} and value
        }
        return cls(
            match_id=game.state.id,
            room_id=room_id,
            seed=seed,
            player_count=len(players),
            agent_type=agent_type,
            rule_pack_id=rule_pack_id,
            phase_delay_ms=phase_delay_ms,
            players=players,
            personas=personas,
            llm_config=safe_llm,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> MatchExecutionSpec:
        return cls(
            match_id=str(payload["match_id"]),
            room_id=str(payload["room_id"]),
            seed=int(payload.get("seed", 7)),
            player_count=int(payload.get("player_count", 10)),
            agent_type=str(payload.get("agent_type", "llm")),
            rule_pack_id=str(payload.get("rule_pack_id", "wolfcha-default")),
            phase_delay_ms=float(payload.get("phase_delay_ms", 0)),
            players=list(payload.get("players") or []),
            personas=list(payload.get("personas") or []),
            llm_config=dict(payload.get("llm_config") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def build_players(self) -> list[Player]:
        return [
            Player(
                id=str(item["id"]),
                seat=int(item["seat"]),
                name=str(item["name"]),
                role=Role(str(item["role"])),
                alignment=Alignment(str(item["alignment"])),
                is_ai=True,
                agent_type=str(item.get("agent_type") or self.agent_type),
                model_name=str(item.get("model_name") or ""),
                prompt_version=str(item.get("prompt_version") or "v1"),
                persona=dict(item.get("persona") or {}),
            )
            for item in self.players
        ]

    def agent_config(self) -> dict[str, Any]:
        return {
            "type": self.agent_type,
            "seed": self.seed,
            **self.llm_config,
        }
