from __future__ import annotations

from typing import Any

from backend.agents.base import Agent
from backend.agents.heuristic import HeuristicAgent
from backend.agents.human_agent import HumanAgent
from backend.agents.llm_agent import LLMAgent
from backend.engine.models import Player


def create_agents(players: list[Player], agent_config: dict[str, Any] | None = None) -> dict[str, Agent]:
    """Create the configured agents for each seat."""
    config = agent_config or {}
    seed = int(config.get("seed", 7))
    agent_type = str(config.get("type", "llm"))
    human_seat = int(config["human_seat"]) if config.get("human_seat") else None
    character_map = config.get("character_map") or {}
    agents: dict[str, Agent] = {}
    for player in players:
        character = character_map.get(player.id)
        if human_seat is not None and player.seat == human_seat:
            player.is_ai = False
            player.agent_type = "human"
            agents[player.id] = HumanAgent(player.id)
            continue
        player.is_ai = True
        player.agent_type = agent_type
        if agent_type == "heuristic":
            agents[player.id] = HeuristicAgent(player.id, seed=seed + player.seat, character=character)
        else:
            agents[player.id] = LLMAgent(
                player.id,
                seed=seed + player.seat,
                provider=config.get("provider"),
                model=config.get("model"),
                temperature=float(config.get("temperature", 0.4)),
                character=character,
            )
    return agents
