from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from backend.engine.game import WerewolfGame
from backend.engine.models import Role
from backend.engine.rules import build_players


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
    roles = [Role(role) for role in game_config.get("roles", [])]
    seed = agent_config.get("seed", 7)
    players = build_players(roles, seed=seed) if roles else None
    return WerewolfGame(
        players=players,
        seed=seed,
        max_days=int(game_config.get("max_days", 8)),
    )
