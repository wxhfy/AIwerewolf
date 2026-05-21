from __future__ import annotations

from typing import Any

from backend.agents.base import Agent
from backend.agents.heuristic import HeuristicAgent
from backend.agents.llm_agent import LLMAgent
from backend.engine.models import Player


def create_agents(players: list[Player], agent_config: dict[str, Any] | None = None) -> dict[str, Agent]:
    config = agent_config or {}
    agent_type = str(config.get("type", "heuristic")).lower()
    seed = int(config.get("seed", 7))

    if agent_type == "llm":
        return {
            player.id: LLMAgent(
                player.id,
                seed=seed + player.seat,
                provider=str(config["provider"]) if "provider" in config else None,
                model=config.get("model"),
                temperature=float(config.get("temperature", 0.4)),
            )
            for player in players
        }

    return {
        player.id: HeuristicAgent(player.id, seed=seed + player.seat)
        for player in players
    }
