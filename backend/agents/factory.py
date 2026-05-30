from __future__ import annotations

import os
import random
from copy import deepcopy
from typing import Any

from backend.agents.base import Agent
from backend.agents.heuristic import HeuristicAgent
from backend.agents.human_agent import HumanAgent
from backend.agents.llm_agent import LLMAgent
from backend.engine.models import Player


def _resolve_model_pool(config: dict[str, Any]) -> list[str]:
    raw = config.get("model_pool")
    if raw is None:
        raw = os.getenv("DOUBAO_MODEL_POOL", "")
    if isinstance(raw, str):
        items = [m.strip() for m in raw.split(",") if m.strip()]
    elif isinstance(raw, (list, tuple)):
        items = [str(m).strip() for m in raw if str(m).strip()]
    else:
        items = []
    return items


def _resolve_pool_specs(config: dict[str, Any]) -> list[dict[str, str]]:
    """Build the (api_key, base_url, model) pool used to randomly assign each
    LLM player a backend.

    Pool entries come ONLY from DOUBAO_MODEL_POOL (or config.model_pool). All
    entries share the primary DOUBAO_API_KEY + DOUBAO_BASE_URL. The
    DOUBAO_FALLBACK_* env vars are kept as documentation for future
    retry-with-fallback logic but are NOT automatically appended to the pool
    — the user explicitly opts in by listing the fallback model in the pool
    and switching DOUBAO_API_KEY/BASE_URL.
    """
    primary_models = _resolve_model_pool(config)
    primary_key = os.getenv("DOUBAO_API_KEY", "").strip()
    primary_url = os.getenv("DOUBAO_BASE_URL", "").strip()
    if not (primary_key and primary_url):
        return []
    return [
        {"api_key": primary_key, "base_url": primary_url, "model": model}
        for model in primary_models
    ]


def create_agents(players: list[Player], agent_config: dict[str, Any] | None = None) -> dict[str, Agent]:
    """Create the configured agents for each seat."""
    config = agent_config or {}
    seed = int(config.get("seed", 7))
    agent_type = str(config.get("type", "llm"))
    human_seat = int(config["human_seat"]) if config.get("human_seat") else None
    character_map = config.get("character_map") or {}
    role_models = config.get("role_models") or {}
    strategy_bias = config.get("strategy_bias") or {}
    pool_specs = _resolve_pool_specs(config)
    pool_rng = random.Random(seed) if pool_specs else None
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
            agents[player.id] = HeuristicAgent(
                player.id,
                seed=seed + player.seat,
                character=character,
                strategy_bias=player_config.get("strategy_bias") or strategy_bias,
            )
        else:
            model_override = player_config.get("model")
            forced_provider = player_config.get("provider")
            api_key_override = player_config.get("api_key")
            base_url_override = player_config.get("base_url")
            if not model_override and pool_rng is not None and pool_specs:
                spec = pool_rng.choice(pool_specs)
                model_override = spec["model"]
                api_key_override = spec["api_key"]
                base_url_override = spec["base_url"]
                # Pool entries all sit behind the Ark gateway — pin provider
                # to skip create_client's substring auto-detect, which would
                # otherwise route aliases like "deepseek-v4-pro[1m]" to
                # api.deepseek.com.
                if not forced_provider:
                    forced_provider = "dsv4flash"
            player.model_name = str(model_override or "")
            agents[player.id] = LLMAgent(
                player.id,
                seed=seed + player.seat,
                provider=forced_provider,
                model=model_override if model_override else None,
                api_key=api_key_override if api_key_override else None,
                base_url=base_url_override if base_url_override else None,
                temperature=float(player_config.get("temperature", 0.4)),
                speech_temperature=float(player_config.get("speech_temperature", 1.1)),
                character=character,
                strategy_bias=player_config.get("strategy_bias") or strategy_bias,
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
