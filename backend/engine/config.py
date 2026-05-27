from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from backend.agents.factory import create_agents
from backend.engine.game import WerewolfGame
from backend.engine.models import Role
from backend.engine.rules import build_players, get_role_configuration


def load_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config must be a YAML mapping: {path}")
    return data


def game_from_config(path: str | Path) -> WerewolfGame:
    config = load_yaml(path)
    game_config = config.get("game", {})
    agent_config = config.get("agents", {})
    player_count = int(game_config.get("player_count", 0))
    roles_raw = game_config.get("roles", [])
    seed = agent_config.get("seed", 7)

    if roles_raw:
        roles = [Role(role) for role in roles_raw]
        players = build_players(roles, seed=seed)
    elif player_count and player_count in (7, 8, 9, 10, 11, 12):
        roles = get_role_configuration(player_count)
        players = build_players(roles, seed=seed)
    else:
        players = build_players(seed=seed)

    agents = create_agents(players, agent_config)
    return WerewolfGame(
        players=players,
        agents=agents,
        seed=seed,
        max_days=int(game_config.get("max_days", 8)),
        player_count=len(players),
    )
