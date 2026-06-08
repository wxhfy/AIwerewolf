from __future__ import annotations

import os
import random
from copy import deepcopy
from typing import Any

from backend.agents.base import Agent
from backend.agents.cognitive.factory import create_cognitive_agent_with_character
from backend.agents.cognitive.factory import create_llm_from_client
from backend.agents.human_agent import HumanAgent
from backend.engine.models import Player

_DEFAULT_DEEPSEEK_ANTHROPIC_BASE_URL = "https://api.deepseek.com/anthropic"


def _resolve_model_pool(config: dict[str, Any]) -> list[str]:
    """Parse model pool entries from config or env."""
    raw = config.get("model_pool")
    if raw is None:
        raw = os.getenv("MODEL_POOL", "") or os.getenv("DOUBAO_MODEL_POOL", "")
    if isinstance(raw, str):
        items = [m.strip() for m in raw.split(",") if m.strip()]
    elif isinstance(raw, (list, tuple)):
        items = [str(m).strip() for m in raw if str(m).strip()]
    else:
        items = []
    return items


def _resolve_pool_specs(config: dict[str, Any]) -> list[dict[str, str]]:
    """Build (provider, api_key, base_url, model) pool for multi-model assignment."""
    pool_entries = _resolve_model_pool(config)
    if not pool_entries:
        return []

    specs = []
    for entry in pool_entries:
        if ":" in entry:
            provider, model = entry.split(":", 1)
            provider = provider.strip()
            model = model.strip()
        else:
            provider = "dsv4flash"
            model = entry.strip()

        spec = _spec_for_provider(provider, model)
        if spec:
            specs.append(spec)

    return specs


def _spec_for_provider(provider: str, model: str) -> dict[str, str] | None:
    """Resolve (api_key, base_url) for a given provider and model."""
    if provider in {"fake", "fake_llm", "offline_llm"}:
        if os.getenv("_TEST_ALLOW_FAKE_LLM") != "true":
            return None  # fake provider is test-only — refuse in production
        return {
            "provider": "fake",
            "api_key": "",
            "base_url": "local://fake-llm",
            "model": model,
        }
    if provider == "doubao":
        api_key = os.getenv("DOUBAO_API_KEY", "").strip()
        base_url = os.getenv("DOUBAO_BASE_URL", "").strip()
    elif provider in ("dsv4flash", "ark"):
        api_key = os.getenv("DSV4FLASH_API_KEY", "").strip()
        base_url = os.getenv("DSV4FLASH_BASE_URL", "").strip()
    elif provider == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
    elif provider in {"mimo", "local_mimo"}:
        api_key = os.getenv("MIMO_API_KEY", "local").strip()
        base_url = os.getenv("MIMO_BASE_URL", "").strip()
    elif provider == "anthropic":
        api_key = (
            os.getenv("ANTHROPIC_AUTH_TOKEN", "").strip()
            or os.getenv("ANTHROPIC_API_KEY", "").strip()
            or os.getenv("DEEPSEEK_API_KEY", "").strip()
        )
        base_url = (
            os.getenv("ANTHROPIC_BASE_URL", "").strip()
            or os.getenv("DEEPSEEK_ANTHROPIC_BASE_URL", "").strip()
            or _DEFAULT_DEEPSEEK_ANTHROPIC_BASE_URL
        )
    elif provider in {"weapi", "weapi_pw"}:
        api_key = os.getenv("WEAPI_API_KEY", "").strip()
        base_url = os.getenv("WEAPI_BASE_URL", "https://weapi.pw").strip()
    else:
        api_key = os.getenv("DOUBAO_API_KEY", "").strip()
        base_url = os.getenv("DOUBAO_BASE_URL", "").strip()

    if not api_key or not base_url:
        return None

    return {
        "provider": "weapi" if provider == "weapi_pw" else provider,
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
    }


def _create_llm_runnable(
    provider: str | None,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
) -> Any:
    """Create a LangChain Runnable wrapping an LLM client for CognitiveAgent."""
    from backend.llm import create_client as create_llm_client

    client_kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
    }
    timeout_override = os.getenv("LLM_TIMEOUT_SECONDS", "").strip()
    if timeout_override:
        client_kwargs["timeout"] = max(0.1, float(timeout_override))
    max_retries_override = os.getenv("LLM_MAX_RETRIES", "").strip()
    if max_retries_override:
        client_kwargs["max_retries"] = max(0, int(max_retries_override))

    client = create_llm_client(
        provider=provider,
        **{key: value for key, value in client_kwargs.items() if value is not None},
    )
    if getattr(client, "available", True) is False:
        raise RuntimeError(
            f"LLM provider {getattr(client, 'provider', provider) or provider or 'default'} "
            "is unavailable. LLM-only games refuse heuristic fallback; configure an API key."
        )
    return create_llm_from_client(client)


def _normalize_agent_type(agent_type: str | None) -> str:
    normalized = str(agent_type or "llm").strip().lower()
    if normalized in {"llm", "cognitive"}:
        return "llm"
    if normalized == "heuristic":
        raise ValueError("heuristic agents are disabled for games; use agent_type=llm")
    raise ValueError(f"Unsupported agent_type={agent_type!r}; only llm is allowed for AI seats")


def _resolve_retrieval_policy(config: dict[str, Any]) -> str:
    """Resolve the default cognitive retrieval policy for game agents."""
    return str(
        config.get("retrieval_policy") or os.getenv("AIWEREWOLF_RETRIEVAL_POLICY", "") or "hybrid_role_mbti_global"
    ).strip()


def _has_explicit_llm_binding(config: dict[str, Any]) -> bool:
    """True when a player config pins its provider/model/client endpoint.

    A pinned provider must not be mixed with MODEL_POOL credentials. Otherwise
    the metadata can say "doubao" while requests are sent to another endpoint.
    """
    return any(config.get(key) for key in ("provider", "model", "api_key", "base_url"))


def create_agents(players: list[Player], agent_config: dict[str, Any] | None = None) -> dict[str, Agent]:
    """Create LLM-backed agents for each AI seat."""
    config = agent_config or {}
    seed = int(config.get("seed", 7))
    agent_type = _normalize_agent_type(str(config.get("type", "llm")))
    human_seat = int(config["human_seat"]) if config.get("human_seat") else None
    character_map = config.get("character_map") or {}
    role_models = config.get("role_models") or {}
    strategy_bias = config.get("strategy_bias") or {}
    default_retrieval_policy = _resolve_retrieval_policy(config)
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
        player_agent_type = _normalize_agent_type(str(player_config.get("type", agent_type)))
        player.agent_type = player_agent_type

        model_override = player_config.get("model")
        forced_provider = player_config.get("provider")
        api_key_override = player_config.get("api_key")
        base_url_override = player_config.get("base_url")

        if not _has_explicit_llm_binding(player_config) and pool_rng is not None and pool_specs:
            spec = pool_rng.choice(pool_specs)
            model_override = spec["model"]
            api_key_override = spec["api_key"]
            base_url_override = spec["base_url"]
            forced_provider = spec.get("provider", "dsv4flash")

        player.model_name = str(model_override or "")

        llm_runnable = _create_llm_runnable(
            provider=forced_provider,
            model=model_override if model_override else None,
            api_key=api_key_override if api_key_override else None,
            base_url=base_url_override if base_url_override else None,
        )

        agents[player.id] = create_cognitive_agent_with_character(
            player_id=player.id,
            role=player.role.value,
            llm=llm_runnable,
            player_name=player.name,
            player_seat=player.seat,
            character=character,
            strategy_bias=player_config.get("strategy_bias") or strategy_bias,
            retrieval_policy=str(player_config.get("retrieval_policy") or default_retrieval_policy),
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
