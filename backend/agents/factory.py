from __future__ import annotations

from typing import Any

from backend.agents.base import Agent
from backend.agents.llm_agent import LLMAgent
from backend.engine.models import Player


def create_agents(players: list[Player], agent_config: dict[str, Any] | None = None) -> dict[str, Agent]:
    """Create LLM-backed agents for all players. Heuristic mode removed per user request."""
    config = agent_config or {}
    seed = int(config.get("seed", 7))
    return {
        player.id: LLMAgent(
            player.id,
            seed=seed + player.seat,
            provider=config.get("provider"),
            model=config.get("model"),
            temperature=float(config.get("temperature", 0.4)),
        )
        for player in players
    }
