from __future__ import annotations

import os
import random
from copy import deepcopy
from typing import Any

from backend.agent_harness import AgentHarness
from backend.agent_harness.contracts import DecisionRequest
from backend.agent_harness.contracts import HarnessResult
from backend.agent_memory import ActorMemoryService
from backend.agent_memory import SqlActorMemoryRepository
from backend.application.agents.harness_event_repository import SqlHarnessEventRepository
from backend.domains.werewolf.capabilities import build_capability_policy
from backend.domains.werewolf.capabilities import build_skill_registry
from backend.domains.werewolf.capabilities import build_tool_gateway
from backend.domains.werewolf.planner import LLMActionPlanner
from backend.engine.models import Player
from backend.llm import create_client


class RoutingHarnessRuntime:
    """Route actor-scoped requests to isolated per-seat harness instances."""

    def __init__(
        self,
        harnesses: dict[str, AgentHarness],
        profiles: dict[str, dict[str, Any]],
        definition_ids: dict[str, str],
        *,
        deadline_ms: int,
        memory: ActorMemoryService,
        event_repository: SqlHarnessEventRepository,
    ) -> None:
        self.harnesses = harnesses
        self.profiles = profiles
        self.definition_ids = definition_ids
        self.deadline_ms = deadline_ms
        self.memory = memory
        self.event_repository = event_repository

    def run(self, request: DecisionRequest) -> HarnessResult:
        try:
            harness = self.harnesses[request.actor.actor_id]
        except KeyError as exc:
            raise RuntimeError(f"No harness configured for actor {request.actor.actor_id}") from exc
        prepared = self.memory.prepare(request)
        result = harness.run(prepared)
        self.event_repository.save(prepared, result.events)
        self.memory.record_result(prepared, result)
        return result


def build_harness_runtime(players: list[Player], config: dict[str, Any]) -> RoutingHarnessRuntime:
    if str(config.get("type", "llm")).strip().lower() not in {"llm", "cognitive"}:
        raise ValueError("Only LLM-backed harness actors are supported")
    role_models = config.get("role_models") or {}
    pool = _model_pool(config)
    rng = random.Random(int(config.get("seed", 7)))
    harnesses: dict[str, AgentHarness] = {}
    profiles: dict[str, dict[str, Any]] = {}
    definition_ids: dict[str, str] = {}
    skills = build_skill_registry()
    tools = build_tool_gateway()
    policy = build_capability_policy()

    for player in players:
        player_config = deepcopy(config)
        player_config.pop("role_models", None)
        role_config = role_models.get(player.role.value) or role_models.get(player.role.name)
        if isinstance(role_config, dict):
            player_config.update(role_config)
        if pool and not any(player_config.get(key) for key in ("provider", "model", "api_key", "base_url")):
            provider, model = rng.choice(pool)
            player_config["provider"] = provider
            player_config["model"] = model

        client_kwargs = {
            key: player_config.get(key)
            for key in ("model", "api_key", "base_url", "timeout", "max_retries")
            if player_config.get(key) is not None
        }
        client = create_client(provider=player_config.get("provider"), **client_kwargs)
        if getattr(client, "available", True) is False:
            raise RuntimeError(
                f"LLM provider {getattr(client, 'provider', '') or player_config.get('provider') or 'default'} "
                "is unavailable; configure credentials before starting a match"
            )
        player.is_ai = True
        player.agent_type = "harness"
        player.model_name = str(getattr(client, "model", ""))
        harness_mode = str(player_config.get("harness_mode") or config.get("harness_mode") or "direct").lower()
        configured_tool_calling = player_config.get("tool_calling")
        if configured_tool_calling is None:
            configured_tool_calling = "xing4.0" in player.model_name.lower() or (
                harness_mode == "agentic"
                and str(getattr(client, "provider", "")).lower() in {"bigmodel", "siliconflow"}
            )
        client.supports_tool_calling = bool(configured_tool_calling)
        profiles[player.id] = {
            "display_name": player.name,
            "seat": player.seat,
            "role": player.role.value,
            "persona": player.persona,
            "strategy_bias": player_config.get("strategy_bias") or config.get("strategy_bias") or {},
            "strategy_version": player_config.get("strategy_version") or config.get("strategy_version") or "",
            "harness_mode": harness_mode,
        }
        definition_ids[player.id] = f"werewolf:{player.role.value}:{player.model_name or 'default'}"
        harnesses[player.id] = AgentHarness(
            LLMActionPlanner(client, temperature=float(player_config.get("temperature", 0.7))),
            skills=skills,
            tools=tools,
            policy=policy,
        )

    deadline_ms = int(float(config.get("deadline_ms") or os.getenv("AGENT_DECISION_DEADLINE_MS", "30000")))
    return RoutingHarnessRuntime(
        harnesses,
        profiles,
        definition_ids,
        deadline_ms=max(100, deadline_ms),
        memory=ActorMemoryService(SqlActorMemoryRepository()),
        event_repository=SqlHarnessEventRepository(),
    )


def _model_pool(config: dict[str, Any]) -> list[tuple[str, str]]:
    raw = config.get("model_pool")
    if raw is None:
        raw = os.getenv("MODEL_POOL", "") or os.getenv("DOUBAO_MODEL_POOL", "")
    entries = raw.split(",") if isinstance(raw, str) else list(raw or [])
    pool: list[tuple[str, str]] = []
    for item in entries:
        entry = str(item).strip()
        if not entry:
            continue
        if ":" in entry:
            provider, model = entry.split(":", 1)
        else:
            provider, model = "dsv4flash", entry
        pool.append((provider.strip(), model.strip()))
    return pool
