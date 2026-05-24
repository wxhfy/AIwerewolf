from __future__ import annotations

from copy import deepcopy
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
    role_models = config.get("role_models") or {}
    agents: dict[str, Agent] = {}
    for player in players:
        character = character_map.get(player.id)
        if human_seat is not None and player.seat == human_seat:
            player.is_ai = False
            player.agent_type = "human"
            agents[player.id] = HumanAgent(player.id)
            continue
        player.is_ai = True
        player_config = _config_for_player(config, role_models, player)
        player_agent_type = str(player_config.get("type", agent_type))
        player.agent_type = player_agent_type
        if player_agent_type == "heuristic":
            agents[player.id] = HeuristicAgent(player.id, seed=seed + player.seat, character=character)
        else:
            model_override = player_config.get("model")
            player.model_name = str(model_override or "")
            agents[player.id] = LLMAgent(
                player.id,
                seed=seed + player.seat,
                provider=player_config.get("provider"),
                model=model_override if model_override else None,
                temperature=float(player_config.get("temperature", 0.4)),
                speech_temperature=float(player_config.get("speech_temperature", 1.1)),
                character=character,
            )
    return agents


def _config_for_player(
    config: dict[str, Any],
    role_models: dict[str, Any],
    player: Player,
) -> dict[str, Any]:
    player_config = deepcopy(config)
    player_config.pop("role_models", None)
    role_config = role_models.get(player.role.value) or role_models.get(player.role.name)
    if role_config:
        player_config.update(role_config)
    return player_config
