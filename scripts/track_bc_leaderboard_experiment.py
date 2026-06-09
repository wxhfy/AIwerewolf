"""Track B/C evidence experiment for model and Agent-framework comparisons.

This runner is designed for academic evidence, not just operations smoke:

* Track B evidence: can the leaderboard separate models or Agent variants?
* Track C evidence: does the cognitive framework add measurable value over a
  basic LLM/ReAct-style baseline under the same seeds and model pool?

Examples:
    EXPERIMENT_MODEL_POOL="dsv4flash:deepseek-v4-flash" \
      python scripts/track_bc_leaderboard_experiment.py --axis framework --games 20

    EXPERIMENT_MODEL_POOL="doubao:${DOUBAO_ENDPOINT},dsv4flash:deepseek-v4-flash" \
      python scripts/track_bc_leaderboard_experiment.py --axis model --frameworks cognitive_full --games 20
"""

from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import os
import queue
import sys
import time
import traceback
from collections import Counter
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from datetime import timezone
from pathlib import Path
from random import Random
from statistics import mean
from typing import Any
from typing import Callable
from typing import Iterable
from typing import Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents.characters import PERSONA_POOL
from backend.agents.characters import build_character_roster
from backend.agents.cognitive.factory import create_cognitive_agent_with_character
from backend.agents.cognitive.factory import create_llm_from_client
from backend.engine.game import WerewolfGame
from backend.engine.rules import build_players
from backend.engine.rules import get_role_configuration
from backend.eval.review import GameMetrics
from backend.eval.review import LeaderboardAggregator
from backend.eval.review import MetricsCalculator
from backend.eval.review import PlayerScore
from backend.eval.review import export_leaderboard
from backend.llm import create_client
from backend.llm.env import load_env_file


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass(frozen=True)
class FrameworkSpec:
    name: str
    description: str
    env: dict[str, str]
    retrieval_policy: str


@dataclass
class GameRunResult:
    metric: GameMetrics
    player_model_labels: dict[str, str]
    record: dict[str, Any]


GameRunner = Callable[
    [int, int, int, Sequence[ModelSpec], FrameworkSpec, int],
    GameRunResult,
]

DEFAULT_GAMES_PER_FRAMEWORK = 10


class GameTimeoutError(TimeoutError):
    """Raised when a single game exceeds the configured experiment timeout."""


class SubprocessGameError(RuntimeError):
    """Error payload propagated from a subprocess game runner."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        super().__init__(str(payload.get("error") or "subprocess game failed"))

    @property
    def error_type(self) -> str:
        return str(self.payload.get("error_type") or "SubprocessGameError")

    @property
    def child_traceback(self) -> str:
        return str(self.payload.get("traceback") or "")


FRAMEWORKS: dict[str, FrameworkSpec] = {
    "basic_react": FrameworkSpec(
        name="basic_react",
        description=(
            "Basic LLM/ReAct-style baseline: no Track C strategy injection, "
            "no static anti-pattern guardrails, no post-game reflection."
        ),
        env={
            "COGNITIVE_ENABLE_TRACK_C": "0",
            "COGNITIVE_ENABLE_ANTI_PATTERNS": "0",
            "COGNITIVE_ENABLE_REFLECTION": "0",
            "AIWEREWOLF_RETRIEVAL_POLICY": "global_only",
        },
        retrieval_policy="global_only",
    ),
    "role_guarded_react": FrameworkSpec(
        name="role_guarded_react",
        description=(
            "Role-guarded ReAct agent: basic ReAct plus role-specific anti-pattern guardrails; "
            "Track C retrieval and post-game reflection disabled."
        ),
        env={
            "COGNITIVE_ENABLE_TRACK_C": "0",
            "COGNITIVE_ENABLE_ANTI_PATTERNS": "1",
            "COGNITIVE_ENABLE_REFLECTION": "0",
            "AIWEREWOLF_RETRIEVAL_POLICY": "global_only",
        },
        retrieval_policy="global_only",
    ),
    "anti_only": FrameworkSpec(
        name="anti_only",
        description=(
            "Backward-compatible alias of role_guarded_react: static role anti-pattern guardrails only; "
            "Track C strategy injection disabled."
        ),
        env={
            "COGNITIVE_ENABLE_TRACK_C": "0",
            "COGNITIVE_ENABLE_ANTI_PATTERNS": "1",
            "COGNITIVE_ENABLE_REFLECTION": "0",
            "AIWEREWOLF_RETRIEVAL_POLICY": "global_only",
        },
        retrieval_policy="global_only",
    ),
    "rag_react": FrameworkSpec(
        name="rag_react",
        description=(
            "RAG/ReAct agent: Track C strategy retrieval and prompt injection enabled; "
            "anti-pattern guardrails and reflection disabled."
        ),
        env={
            "COGNITIVE_ENABLE_TRACK_C": "1",
            "COGNITIVE_ENABLE_ANTI_PATTERNS": "0",
            "COGNITIVE_ENABLE_REFLECTION": "0",
            "AIWEREWOLF_RETRIEVAL_POLICY": "same_role_all_mbti",
        },
        retrieval_policy="same_role_all_mbti",
    ),
    "trackc_only": FrameworkSpec(
        name="trackc_only",
        description=(
            "Backward-compatible alias of rag_react: Track C strategy retrieval/injection enabled; "
            "static anti-pattern guardrails disabled."
        ),
        env={
            "COGNITIVE_ENABLE_TRACK_C": "1",
            "COGNITIVE_ENABLE_ANTI_PATTERNS": "0",
            "COGNITIVE_ENABLE_REFLECTION": "0",
            "AIWEREWOLF_RETRIEVAL_POLICY": "same_role_all_mbti",
        },
        retrieval_policy="same_role_all_mbti",
    ),
    "reflexion_react": FrameworkSpec(
        name="reflexion_react",
        description=(
            "Reflexion-style agent: post-game verbal reflection enabled to write future knowledge; "
            "runtime Track C retrieval and anti-pattern guardrails disabled."
        ),
        env={
            "COGNITIVE_ENABLE_TRACK_C": "0",
            "COGNITIVE_ENABLE_ANTI_PATTERNS": "0",
            "COGNITIVE_ENABLE_REFLECTION": "1",
            "AIWEREWOLF_RETRIEVAL_POLICY": "global_only",
        },
        retrieval_policy="global_only",
    ),
    "rag_reflexion": FrameworkSpec(
        name="rag_reflexion",
        description=(
            "RAG + Reflexion agent: runtime Track C retrieval plus post-game verbal reflection; "
            "static anti-pattern guardrails disabled."
        ),
        env={
            "COGNITIVE_ENABLE_TRACK_C": "1",
            "COGNITIVE_ENABLE_ANTI_PATTERNS": "0",
            "COGNITIVE_ENABLE_REFLECTION": "1",
            "AIWEREWOLF_RETRIEVAL_POLICY": "same_role_all_mbti",
        },
        retrieval_policy="same_role_all_mbti",
    ),
    "full_cognitive": FrameworkSpec(
        name="full_cognitive",
        description=(
            "Full cognitive agent: role guardrails, runtime Track C retrieval, and post-game reflection enabled."
        ),
        env={
            "COGNITIVE_ENABLE_TRACK_C": "1",
            "COGNITIVE_ENABLE_ANTI_PATTERNS": "1",
            "COGNITIVE_ENABLE_REFLECTION": "1",
            "AIWEREWOLF_RETRIEVAL_POLICY": "same_role_all_mbti",
        },
        retrieval_policy="same_role_all_mbti",
    ),
    "cognitive_full": FrameworkSpec(
        name="cognitive_full",
        description=(
            "Backward-compatible alias of full_cognitive: Track C strategy layer, anti-pattern guardrails, "
            "reflection enabled."
        ),
        env={
            "COGNITIVE_ENABLE_TRACK_C": "1",
            "COGNITIVE_ENABLE_ANTI_PATTERNS": "1",
            "COGNITIVE_ENABLE_REFLECTION": "1",
            "AIWEREWOLF_RETRIEVAL_POLICY": "same_role_all_mbti",
        },
        retrieval_policy="same_role_all_mbti",
    ),
}

FRAMEWORK_FAMILY_MAP: dict[str, dict[str, str]] = {
    "basic_react": {
        "paper_family": "ReAct",
        "comparison_role": "ordinary ReAct baseline",
        "reference": "https://arxiv.org/abs/2210.03629",
    },
    "role_guarded_react": {
        "paper_family": "Role-conditioned guarded agent",
        "comparison_role": "our role/anti-pattern Agent design",
        "reference": "internal role strategy and anti-pattern layer",
    },
    "anti_only": {
        "paper_family": "Role-conditioned guarded agent",
        "comparison_role": "backward-compatible alias of role_guarded_react",
        "reference": "internal role strategy and anti-pattern layer",
    },
    "rag_react": {
        "paper_family": "RAG/ReAct",
        "comparison_role": "Track C retrieval-only Agent design",
        "reference": "internal Track C strategy retrieval",
    },
    "trackc_only": {
        "paper_family": "RAG/ReAct",
        "comparison_role": "backward-compatible alias of rag_react",
        "reference": "internal Track C strategy retrieval",
    },
    "reflexion_react": {
        "paper_family": "Reflexion",
        "comparison_role": "post-game verbal reflection baseline",
        "reference": "https://arxiv.org/abs/2303.11366",
    },
    "rag_reflexion": {
        "paper_family": "RAG + Reflexion",
        "comparison_role": "retrieval plus outer-loop reflection without role guardrails",
        "reference": "https://arxiv.org/abs/2303.11366",
    },
    "full_cognitive": {
        "paper_family": "Role-guarded RAG + Reflexion",
        "comparison_role": "our complete Agent framework",
        "reference": "internal full cognitive stack",
    },
    "cognitive_full": {
        "paper_family": "Role-guarded RAG + Reflexion",
        "comparison_role": "backward-compatible alias of full_cognitive",
        "reference": "internal full cognitive stack",
    },
}


RUBRIC_WEIGHTS: dict[str, float] = {
    "single_agent": 20.0,
    "multi_agent": 20.0,
    "engineering": 30.0,
    "advanced_bc": 30.0,
}

RUBRIC_DIMENSIONS: dict[str, dict[str, Any]] = {
    "single_agent": {
        "weight": RUBRIC_WEIGHTS["single_agent"],
        "requirement": "Prompt/role strategy quality, decision traceability, role behavior differentiation.",
        "signals": [
            "avg_adjusted_final_score",
            "avg_vote_score",
            "avg_speech_score",
            "avg_skill_score",
            "core_role_coverage",
            "fallback/invalid health",
        ],
    },
    "multi_agent": {
        "weight": RUBRIC_WEIGHTS["multi_agent"],
        "requirement": "Context management, public/private state handling, skill coordination, social deduction.",
        "signals": [
            "macro_role_win_rate",
            "avg_vote_score",
            "avg_skill_score",
            "fallback/invalid health",
        ],
    },
    "engineering": {
        "weight": RUBRIC_WEIGHTS["engineering"],
        "requirement": "Complete game flow, strict isolation gate, observability, run completion and robustness.",
        "signals": [
            "condition_completion_rate",
            "fallback/invalid health",
            "role_distribution_audit",
            "seat_samples",
        ],
    },
    "advanced_bc": {
        "weight": RUBRIC_WEIGHTS["advanced_bc"],
        "requirement": "Track B review/leaderboard discrimination and Track C measurable evolution evidence.",
        "signals": [
            "Track B leaderboard position",
            "Track B can_distinguish",
            "knowledge_hit_rate",
            "paired score delta vs baseline",
            "bootstrap rank stability",
        ],
    },
}

CORE_RUBRIC_ROLES = {"Villager", "Werewolf", "Seer", "Witch", "Hunter"}


def str_to_bool(value: str | bool | None) -> bool:
    return str(value).strip().lower() not in {"", "0", "false", "no", "off", "none"}


@contextmanager
def patched_env(updates: dict[str, str]) -> Iterable[None]:
    old_values = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            os.environ[key] = value
        yield
    finally:
        for key, old_value in old_values.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def parse_model_specs(raw: str, *, default_provider: str | None = None) -> list[ModelSpec]:
    specs: list[ModelSpec] = []
    provider_default = (default_provider or os.getenv("LLM_PROVIDER", "") or "ark").strip().lower()
    for entry in [part.strip() for part in raw.split(",") if part.strip()]:
        if ":" in entry:
            provider, model = entry.split(":", 1)
            provider = provider.strip().lower()
            model = model.strip()
        else:
            provider = provider_default
            model = entry
        if provider and model:
            specs.append(ModelSpec(provider=provider, model=model))
    return specs


def resolve_model_specs(raw_models: str = "") -> list[ModelSpec]:
    raw = (
        raw_models.strip()
        or os.getenv("EXPERIMENT_MODEL_POOL", "").strip()
        or os.getenv("MODEL_POOL", "").strip()
        or os.getenv("DOUBAO_MODEL_POOL", "").strip()
    )
    if raw:
        return parse_model_specs(raw)

    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    if not provider:
        raise RuntimeError(
            "No model pool configured. Set EXPERIMENT_MODEL_POOL or MODEL_POOL, for example: "
            'EXPERIMENT_MODEL_POOL="dsv4flash:deepseek-v4-flash".'
        )
    candidates = {
        "anthropic": ["ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_MODEL", "DEEPSEEK_MODEL"],
        "doubao": ["DOUBAO_ENDPOINT", "DOUBAO_MODEL", "ANTHROPIC_MODEL"],
        "ark": ["ANTHROPIC_MODEL", "DSV4FLASH_MODEL", "DOUBAO_ENDPOINT", "DOUBAO_MODEL"],
        "dsv4flash": ["DSV4FLASH_MODEL"],
        "deepseek": ["DEEPSEEK_MODEL"],
        "weapi": ["WEAPI_MODEL"],
        "mimo": ["MIMO_MODEL"],
        "fake": ["FAKE_LLM_MODEL"],
    }
    for key in candidates.get(provider, []):
        model = os.getenv(key, "").strip()
        if model:
            return [ModelSpec(provider=provider, model=model)]
    raise RuntimeError(f"LLM_PROVIDER={provider!r} is set but no model env var was found.")


def validate_model_specs(specs: Sequence[ModelSpec], *, allow_fake: bool, skip_client_check: bool) -> None:
    if not specs:
        raise RuntimeError("At least one model is required.")
    fake_providers = {"fake", "fake_llm", "offline_llm"}
    if any(spec.provider in fake_providers for spec in specs) and not allow_fake:
        raise RuntimeError(
            "Fake/offline LLM is disabled for academic experiments. "
            "Use real Volcengine/Ark models, or pass --allow-fake only for CI smoke tests."
        )
    if skip_client_check:
        return
    for spec in specs:
        client = create_client(provider=spec.provider, model=spec.model)
        if getattr(client, "available", True) is False:
            raise RuntimeError(
                f"LLM client unavailable for {spec.label}. Check API key/base URL env vars before running."
            )


def resolve_frameworks(names: str) -> list[FrameworkSpec]:
    selected: list[FrameworkSpec] = []
    for raw_name in [part.strip() for part in names.split(",") if part.strip()]:
        if raw_name not in FRAMEWORKS:
            choices = ", ".join(sorted(FRAMEWORKS))
            raise RuntimeError(f"Unknown framework {raw_name!r}. Choices: {choices}")
        selected.append(FRAMEWORKS[raw_name])
    if not selected:
        raise RuntimeError("At least one framework is required.")
    return selected


def model_for_seat(specs: Sequence[ModelSpec], game_index: int, seat_index: int) -> ModelSpec:
    """Deterministic round-robin assignment for role/seat balance audits."""
    return specs[(game_index + seat_index) % len(specs)]


def sample_personas(count: int, seed: int | None) -> list[dict[str, Any]] | None:
    if not PERSONA_POOL:
        return None
    rng = Random(seed)
    pool = list(PERSONA_POOL)
    rng.shuffle(pool)
    if len(pool) >= count:
        return pool[:count]
    return [pool[index % len(pool)] for index in range(count)]


def run_llm_game(
    seed: int,
    player_count: int,
    max_days: int,
    model_specs: Sequence[ModelSpec],
    framework: FrameworkSpec,
    game_index: int,
) -> GameRunResult:
    roles = get_role_configuration(player_count)
    players = build_players(roles, seed=seed)
    sampled_personas = sample_personas(len(players), seed)
    if sampled_personas:
        for player, persona_data in zip(players, sampled_personas):
            player.name = str(persona_data.get("name") or player.name)
    characters = build_character_roster(players, seed=seed, sampled_personas=sampled_personas)
    agents = {}
    player_model_labels: dict[str, str] = {}

    with patched_env(framework.env):
        for seat_index, player in enumerate(players):
            spec = model_for_seat(model_specs, game_index, seat_index)
            player.model_name = spec.model
            player_model_labels[player.id] = spec.label
            client = create_client(provider=spec.provider, model=spec.model)
            if getattr(client, "available", True) is False:
                raise RuntimeError(f"LLM client unavailable for {spec.label}")
            agents[player.id] = create_cognitive_agent_with_character(
                player_id=player.id,
                role=player.role.value,
                llm=create_llm_from_client(client),
                player_name=player.name,
                player_seat=player.seat,
                character=characters[player.id],
                retrieval_policy=framework.retrieval_policy,
            )

        game = WerewolfGame(
            players=players,
            agents=agents,
            seed=seed,
            max_days=max_days,
            player_count=player_count,
            strategy_version=framework.name,
            sampled_personas=sampled_personas,
        )
        started = time.perf_counter()
        state = game.play()
        elapsed_s = round(time.perf_counter() - started, 3)

    metric = MetricsCalculator().compute(state)
    decision_summary = summarize_decision_records(state.decision_records)
    metric.metadata.update(
        {
            "strategy_version": framework.name,
            "agent_version": framework.name,
            "framework": framework.name,
            "seed": seed,
            "player_count": player_count,
            "model_pool": [spec.label for spec in model_specs],
            "player_model_labels": dict(player_model_labels),
            **decision_summary,
        }
    )
    record = {
        "seed": seed,
        "game_id": state.id,
        "framework": framework.name,
        "winner": enum_value(state.winner),
        "days": state.day,
        "events": len(state.events),
        "elapsed_s": elapsed_s,
        "player_count": player_count,
        "model_pool": [spec.label for spec in model_specs],
        "seat_assignments": [
            {
                "seat": player.seat,
                "player_id": player.id,
                "name": player.name,
                "role": player.role.value,
                "alignment": player.alignment.value,
                "model": player_model_labels[player.id],
            }
            for player in players
        ],
        **decision_summary,
    }
    return GameRunResult(metric=metric, player_model_labels=player_model_labels, record=record)


def enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def record_is_fallback(record: Any) -> bool:
    parsed = record.parsed_action if isinstance(getattr(record, "parsed_action", None), dict) else {}
    metadata = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else {}
    return (
        bool(metadata.get("fallback"))
        or bool(metadata.get("fallback_used"))
        or bool(parsed.get("agent_fallback"))
        or bool(getattr(record, "fallback_used", False))
        or str(metadata.get("source", "")).lower() == "fallback"
    )


def summarize_decision_records(records: Sequence[Any]) -> dict[str, Any]:
    decision_count = len(records)
    fallback_count = sum(1 for record in records if record_is_fallback(record))
    invalid_count = sum(1 for record in records if not bool(getattr(record, "is_valid", True)))
    retrieved_count = 0
    provider_counts: Counter[str] = Counter()
    model_counts: Counter[str] = Counter()
    for record in records:
        parsed = record.parsed_action if isinstance(getattr(record, "parsed_action", None), dict) else {}
        metadata = parsed.get("metadata") if isinstance(parsed.get("metadata"), dict) else {}
        if bool(parsed.get("retrieval_used")) or bool(metadata.get("retrieval_used")):
            retrieved_count += 1
        provider = str(metadata.get("provider") or getattr(record, "provider", "") or "").strip()
        model = str(metadata.get("model") or getattr(record, "model_name", "") or "").strip()
        if provider:
            provider_counts[provider] += 1
        if model:
            model_counts[model] += 1
    denom = max(decision_count, 1)
    return {
        "decision_count": decision_count,
        "fallback_count": fallback_count,
        "fallback_rate": round(fallback_count / denom, 6),
        "invalid_count": invalid_count,
        "invalid_action_rate": round(invalid_count / denom, 6),
        "retrieved_count": retrieved_count,
        "knowledge_hit_rate": round(retrieved_count / denom, 6),
        "provider_counts": dict(sorted(provider_counts.items())),
        "model_counts": dict(sorted(model_counts.items())),
    }


def split_metrics_by_player_group(
    metric: GameMetrics,
    player_to_group: dict[str, str],
    *,
    axis: str,
    seed: int,
    framework: str,
) -> list[GameMetrics]:
    buckets: dict[str, list[PlayerScore]] = defaultdict(list)
    for score in metric.player_scores:
        group = player_to_group.get(score.player_id)
        if group:
            buckets[group].append(score)

    derived: list[GameMetrics] = []
    for group, scores in sorted(buckets.items()):
        metadata = dict(metric.metadata)
        metadata.update(
            {
                "strategy_version": group,
                "agent_version": group,
                "experiment_axis": axis,
                "source_game_id": metric.game_id,
                "seed": seed,
                "framework": framework,
                "group_player_count": len(scores),
            }
        )
        derived.append(
            replace(
                metric,
                game_id=f"{metric.game_id}:{safe_key(group)}",
                player_scores=list(scores),
                metadata=metadata,
            )
        )
    return derived


def safe_key(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)[:120]


def metric_group_record(metric: GameMetrics) -> dict[str, Any]:
    scores = list(metric.player_scores)
    adjusted = [
        score.adjusted_final_score if score.adjusted_final_score is not None else score.final_score for score in scores
    ]
    wins = sum(1 for score in scores if score.camp_result_score >= 1.0)
    role_counts = Counter(score.role for score in scores)
    role_wins = Counter(score.role for score in scores if score.camp_result_score >= 1.0)
    alignment_counts = Counter(score.alignment for score in scores)
    group_key = str(metric.metadata.get("strategy_version") or metric.metadata.get("agent_version") or "v0")
    return {
        "seed": metric.metadata.get("seed"),
        "source_game_id": metric.metadata.get("source_game_id") or metric.game_id,
        "group_key": group_key,
        "framework": metric.metadata.get("framework", ""),
        "players": len(scores),
        "wins": wins,
        "win_rate": round(wins / max(len(scores), 1), 6),
        "avg_adjusted_final_score": round(mean(adjusted), 6) if adjusted else 0.0,
        "avg_final_score": round(mean([score.final_score for score in scores]), 6) if scores else 0.0,
        "avg_vote_score": round(mean([score.vote_score for score in scores]), 6) if scores else 0.0,
        "avg_speech_score": round(mean([score.speech_score for score in scores]), 6) if scores else 0.0,
        "avg_skill_score": round(mean([score.skill_score for score in scores]), 6) if scores else 0.0,
        "roles": dict(sorted(role_counts.items())),
        "role_wins": dict(sorted(role_wins.items())),
        "alignments": dict(sorted(alignment_counts.items())),
        "decision_count": metric.metadata.get("decision_count", 0),
        "fallback_count": metric.metadata.get("fallback_count", 0),
        "invalid_count": metric.metadata.get("invalid_count", 0),
        "knowledge_hit_rate": metric.metadata.get("knowledge_hit_rate", 0.0),
    }


def build_role_audit(group_records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    audit: dict[str, Any] = {}
    for group_key in sorted({str(record["group_key"]) for record in group_records}):
        role_counts: Counter[str] = Counter()
        alignment_counts: Counter[str] = Counter()
        seats = 0
        for record in group_records:
            if record["group_key"] != group_key:
                continue
            role_counts.update(record.get("roles", {}))
            alignment_counts.update(record.get("alignments", {}))
            seats += int(record.get("players", 0))
        audit[group_key] = {
            "seat_samples": seats,
            "roles": dict(sorted(role_counts.items())),
            "alignments": dict(sorted(alignment_counts.items())),
        }
    return audit


def build_role_win_rates(group_records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_group: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: {"samples": Counter(), "wins": Counter()})
    for record in group_records:
        group_key = str(record["group_key"])
        by_group[group_key]["samples"].update(record.get("roles", {}))
        by_group[group_key]["wins"].update(record.get("role_wins", {}))

    result: dict[str, Any] = {}
    for group_key, buckets in sorted(by_group.items()):
        role_rates: dict[str, Any] = {}
        samples = buckets["samples"]
        wins = buckets["wins"]
        for role in sorted(samples):
            n = int(samples[role])
            w = int(wins.get(role, 0))
            role_rates[role] = {"samples": n, "wins": w, "win_rate": round(w / max(n, 1), 6)}
        role_values = [value["win_rate"] for value in role_rates.values() if value["samples"] > 0]
        total_samples = sum(value["samples"] for value in role_rates.values())
        total_wins = sum(value["wins"] for value in role_rates.values())
        result[group_key] = {
            "macro_role_win_rate": round(mean(role_values), 6) if role_values else 0.0,
            "micro_role_win_rate": round(total_wins / max(total_samples, 1), 6),
            "role_win_rates": role_rates,
        }
    return result


def build_pairwise_delta(
    group_records: Sequence[dict[str, Any]], preferred_pair: tuple[str, str] | None
) -> dict[str, Any]:
    by_group: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    for record in group_records:
        seed = record.get("seed")
        if seed is None:
            continue
        by_group[str(record["group_key"])][int(seed)] = record

    groups = sorted(by_group)
    if len(groups) < 2:
        return {}
    if preferred_pair and preferred_pair[0] in by_group and preferred_pair[1] in by_group:
        baseline, candidate = preferred_pair
    else:
        baseline, candidate = groups[0], groups[-1]

    seeds = sorted(set(by_group[baseline]) & set(by_group[candidate]))
    if not seeds:
        return {"baseline": baseline, "candidate": candidate, "paired_seed_count": 0}

    score_deltas = [
        float(by_group[candidate][seed]["avg_adjusted_final_score"])
        - float(by_group[baseline][seed]["avg_adjusted_final_score"])
        for seed in seeds
    ]
    win_rate_deltas = [
        float(by_group[candidate][seed]["win_rate"]) - float(by_group[baseline][seed]["win_rate"]) for seed in seeds
    ]
    return {
        "baseline": baseline,
        "candidate": candidate,
        "paired_seed_count": len(seeds),
        "avg_adjusted_final_score_delta": round(mean(score_deltas), 6),
        "avg_win_rate_delta": round(mean(win_rate_deltas), 6),
        "positive_score_delta_seeds": sum(1 for delta in score_deltas if delta > 0),
        "positive_win_rate_delta_seeds": sum(1 for delta in win_rate_deltas if delta > 0),
    }


def percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    weight = pos - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def aggregate_records_for_bootstrap(records: Sequence[dict[str, Any]]) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["group_key"])].append(record)
    aggregated: dict[str, dict[str, float]] = {}
    for group_key, bucket in grouped.items():
        players = sum(float(record.get("players", 0)) for record in bucket)
        wins = sum(float(record.get("wins", 0)) for record in bucket)
        score_weight = sum(
            float(record.get("avg_adjusted_final_score", 0.0)) * float(record.get("players", 0)) for record in bucket
        )
        aggregated[group_key] = {
            "win_rate": wins / max(players, 1.0),
            "avg_adjusted_final_score": score_weight / max(players, 1.0),
            "seat_samples": players,
        }
    return aggregated


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def normalize_metric(values: dict[str, float], *, higher_is_better: bool = True) -> dict[str, float]:
    if not values:
        return {}
    min_value = min(values.values())
    max_value = max(values.values())
    if abs(max_value - min_value) < 1e-9:
        flat_score = 0.0 if abs(max_value) < 1e-9 else 1.0
        return dict.fromkeys(values, flat_score)
    normalized = {key: (value - min_value) / (max_value - min_value) for key, value in values.items()}
    if not higher_is_better:
        normalized = {key: 1.0 - value for key, value in normalized.items()}
    return {key: clamp(value) for key, value in normalized.items()}


def aggregate_group_rows(records: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["group_key"])].append(record)

    aggregated: dict[str, dict[str, Any]] = {}
    for group_key, bucket in sorted(grouped.items()):
        players = sum(float(record.get("players", 0)) for record in bucket)
        wins = sum(float(record.get("wins", 0)) for record in bucket)

        def weighted(field: str) -> float:
            return sum(float(record.get(field, 0.0)) * float(record.get("players", 0)) for record in bucket) / max(
                players, 1.0
            )

        roles: Counter[str] = Counter()
        role_wins: Counter[str] = Counter()
        alignments: Counter[str] = Counter()
        for record in bucket:
            roles.update(record.get("roles", {}))
            role_wins.update(record.get("role_wins", {}))
            alignments.update(record.get("alignments", {}))
        aggregated[group_key] = {
            "group_key": group_key,
            "framework": ",".join(
                sorted({str(record.get("framework") or "") for record in bucket if record.get("framework")})
            ),
            "row_count": len(bucket),
            "seed_count": len({record.get("seed") for record in bucket if record.get("seed") is not None}),
            "seat_samples": int(players),
            "wins": int(wins),
            "win_rate": round(wins / max(players, 1.0), 6),
            "avg_adjusted_final_score": round(weighted("avg_adjusted_final_score"), 6),
            "avg_final_score": round(weighted("avg_final_score"), 6),
            "avg_vote_score": round(weighted("avg_vote_score"), 6),
            "avg_speech_score": round(weighted("avg_speech_score"), 6),
            "avg_skill_score": round(weighted("avg_skill_score"), 6),
            "decision_count": int(sum(float(record.get("decision_count", 0)) for record in bucket)),
            "fallback_count": int(sum(float(record.get("fallback_count", 0)) for record in bucket)),
            "invalid_count": int(sum(float(record.get("invalid_count", 0)) for record in bucket)),
            "knowledge_hit_rate": round(weighted("knowledge_hit_rate"), 6),
            "roles": dict(sorted(roles.items())),
            "role_wins": dict(sorted(role_wins.items())),
            "alignments": dict(sorted(alignments.items())),
        }
    return aggregated


def core_role_coverage(roles: dict[str, Any]) -> float:
    present = {role for role, count in roles.items() if int(count) > 0}
    return len(CORE_RUBRIC_ROLES & present) / len(CORE_RUBRIC_ROLES)


def rubric_health_score(row: dict[str, Any]) -> float:
    decisions = max(float(row.get("decision_count", 0)), 1.0)
    fallback_rate = float(row.get("fallback_count", 0)) / decisions
    invalid_rate = float(row.get("invalid_count", 0)) / decisions
    return clamp(1.0 - fallback_rate - invalid_rate)


def mean_or_zero(values: Sequence[float]) -> float:
    return mean(values) if values else 0.0


def build_architecture_evidence_leaderboard(
    group_records: Sequence[dict[str, Any]],
    *,
    summary_context: dict[str, Any],
    leaderboard_payload: dict[str, Any],
) -> dict[str, Any]:
    """Build a presentation leaderboard organized by architecture evidence.

    This does not replace the Track B leaderboard. It maps experiment evidence
    into the project architecture dimensions: Agent, multi-agent, engineering,
    and B/C loop.
    """
    group_rows = aggregate_group_rows(group_records)
    if not group_rows:
        return {
            "weights": RUBRIC_WEIGHTS,
            "dimensions": RUBRIC_DIMENSIONS,
            "entries": [],
        }

    role_win_rates = summary_context.get("role_win_rates", {})
    bootstrap = summary_context.get("bootstrap_reliability", {})
    lb_summary = summary_context.get("leaderboard_summary", {})
    paired_delta = lb_summary.get("paired_delta") or {}
    leaderboard_entries = list(leaderboard_payload.get("entries", []))
    rank_by_key = {str(entry.get("key")): rank for rank, entry in enumerate(leaderboard_entries, start=1)}
    entry_count = max(len(leaderboard_entries), 1)

    adjusted_norm = normalize_metric({key: float(row["avg_adjusted_final_score"]) for key, row in group_rows.items()})
    vote_norm = normalize_metric({key: float(row["avg_vote_score"]) for key, row in group_rows.items()})
    speech_norm = normalize_metric({key: float(row["avg_speech_score"]) for key, row in group_rows.items()})
    skill_norm = normalize_metric({key: float(row["avg_skill_score"]) for key, row in group_rows.items()})
    win_norm = normalize_metric({key: float(row["win_rate"]) for key, row in group_rows.items()})
    knowledge_norm = normalize_metric({key: float(row["knowledge_hit_rate"]) for key, row in group_rows.items()})
    macro_role_values = {key: float(role_win_rates.get(key, {}).get("macro_role_win_rate", 0.0)) for key in group_rows}
    macro_role_norm = normalize_metric(macro_role_values)

    candidate_key = str(paired_delta.get("candidate", ""))
    baseline_key = str(paired_delta.get("baseline", ""))
    score_delta = float(paired_delta.get("avg_adjusted_final_score_delta", 0.0) or 0.0)
    win_delta = float(paired_delta.get("avg_win_rate_delta", 0.0) or 0.0)
    positive_seed_ratio = 0.0
    paired_count = int(paired_delta.get("paired_seed_count", 0) or 0)
    if paired_count:
        positive_seed_ratio = float(paired_delta.get("positive_score_delta_seeds", 0) or 0) / paired_count

    top_by_score = bootstrap.get("rank_stability_by_adjusted_score", {})
    top_by_win = bootstrap.get("rank_stability_by_win_rate", {})
    condition_count = max(int(summary_context.get("games_per_framework", 0) or 0), 1)
    completed_by_framework = Counter(
        str(record.get("framework") or "") for record in summary_context.get("raw_records", [])
    )
    failure_by_framework = Counter(str(item.get("framework") or "") for item in summary_context.get("failures", []))

    entries: list[dict[str, Any]] = []
    for group_key, row in group_rows.items():
        framework_name = (
            group_key[len("framework:") :] if group_key.startswith("framework:") else row.get("framework", "")
        )
        completed = completed_by_framework.get(framework_name, 0)
        failed = failure_by_framework.get(framework_name, 0)
        if not completed and not failed:
            completed = int(row.get("seed_count", 0))
        external_failure_rate = failed / max(completed + failed, condition_count, 1)
        attempt_completion_rate = completed / max(completed + failed, condition_count, 1)
        completion_rate = 1.0 if completed else 0.0
        health = rubric_health_score(row)
        role_coverage = core_role_coverage(row.get("roles", {}))
        rank_score = 1.0
        if group_key in rank_by_key and entry_count > 1:
            rank_score = 1.0 - ((rank_by_key[group_key] - 1) / (entry_count - 1))

        candidate_delta_score = 0.5
        if group_key == candidate_key:
            candidate_delta_score = clamp(0.5 + score_delta / 20.0 + win_delta / 2.0 + 0.25 * positive_seed_ratio)
        elif group_key == baseline_key:
            candidate_delta_score = clamp(0.5 - score_delta / 20.0 - win_delta / 2.0)

        reliability_score = mean_or_zero(
            [
                float(top_by_score.get(group_key, 0.0)),
                float(top_by_win.get(group_key, 0.0)),
            ]
        )
        if not bootstrap.get("iterations"):
            reliability_score = 0.5

        track_b_signal = mean_or_zero(
            [
                rank_score,
                adjusted_norm.get(group_key, 0.0),
                1.0 if lb_summary.get("can_distinguish") else 0.0,
                reliability_score,
            ]
        )
        track_c_signal = mean_or_zero(
            [
                knowledge_norm.get(group_key, 0.0),
                candidate_delta_score,
            ]
        )

        single_agent_raw = mean_or_zero(
            [
                adjusted_norm.get(group_key, 0.0),
                vote_norm.get(group_key, 0.0),
                speech_norm.get(group_key, 0.0),
                skill_norm.get(group_key, 0.0),
                role_coverage,
                health,
            ]
        )
        multi_agent_raw = mean_or_zero(
            [
                macro_role_norm.get(group_key, 0.0),
                win_norm.get(group_key, 0.0),
                vote_norm.get(group_key, 0.0),
                skill_norm.get(group_key, 0.0),
                health,
            ]
        )
        engineering_raw = mean_or_zero(
            [
                health,
                role_coverage,
                1.0 if row.get("seat_samples", 0) > 0 else 0.0,
            ]
        )
        advanced_raw = mean_or_zero(
            [
                track_b_signal,
                track_c_signal,
                reliability_score,
                health,
            ]
        )

        dimensions = {
            "single_agent": round(single_agent_raw * RUBRIC_WEIGHTS["single_agent"], 4),
            "multi_agent": round(multi_agent_raw * RUBRIC_WEIGHTS["multi_agent"], 4),
            "engineering": round(engineering_raw * RUBRIC_WEIGHTS["engineering"], 4),
            "advanced_bc": round(advanced_raw * RUBRIC_WEIGHTS["advanced_bc"], 4),
        }
        total_score = round(sum(dimensions.values()), 4)
        entries.append(
            {
                "rank": 0,
                "group_key": group_key,
                "framework": framework_name,
                "rubric_total_score": total_score,
                "rubric_dimensions": dimensions,
                "raw_dimension_scores": {
                    "single_agent": round(single_agent_raw, 6),
                    "multi_agent": round(multi_agent_raw, 6),
                    "engineering": round(engineering_raw, 6),
                    "advanced_bc": round(advanced_raw, 6),
                },
                "evidence_signals": {
                    "win_rate": row["win_rate"],
                    "avg_adjusted_final_score": row["avg_adjusted_final_score"],
                    "macro_role_win_rate": macro_role_values.get(group_key, 0.0),
                    "knowledge_hit_rate": row["knowledge_hit_rate"],
                    "fallback_count": row["fallback_count"],
                    "invalid_count": row["invalid_count"],
                    "external_failed_games": failed,
                    "external_failure_rate": round(external_failure_rate, 6),
                    "attempt_completion_rate": round(attempt_completion_rate, 6),
                    "completion_rate": round(completion_rate, 6),
                    "core_role_coverage": round(role_coverage, 6),
                    "track_b_rank_score": round(rank_score, 6),
                    "track_b_can_distinguish": bool(lb_summary.get("can_distinguish")),
                    "paired_candidate_delta_score": round(candidate_delta_score, 6),
                    "bootstrap_reliability_score": round(reliability_score, 6),
                    "seat_samples": row["seat_samples"],
                    "roles": row["roles"],
                },
            }
        )

    entries.sort(
        key=lambda item: (
            item["rubric_total_score"],
            item["rubric_dimensions"]["advanced_bc"],
            item["evidence_signals"]["avg_adjusted_final_score"],
        ),
        reverse=True,
    )
    for rank, entry in enumerate(entries, start=1):
        entry["rank"] = rank

    return {
        "weights": RUBRIC_WEIGHTS,
        "dimensions": RUBRIC_DIMENSIONS,
        "scoring_note": (
            "Presentation leaderboard aligned with REQUIREMENTS.md. It normalizes available experiment "
            "signals within the current run and should be reported together with raw Track B metrics."
        ),
        "entries": entries,
    }


def build_bootstrap_reliability(
    group_records: Sequence[dict[str, Any]],
    *,
    iterations: int = 1000,
    seed: int = 20260608,
) -> dict[str, Any]:
    """Bootstrap group-level rows for CIs and rank stability.

    This is a report-level reliability diagnostic. It does not change Track B
    scores; it estimates whether observed differences survive seed resampling.
    """
    seeds = sorted({int(record["seed"]) for record in group_records if record.get("seed") is not None})
    groups = sorted({str(record["group_key"]) for record in group_records})
    if len(seeds) < 2 or len(groups) < 2:
        return {
            "method": "seed_bootstrap",
            "iterations": 0,
            "reason": "need at least two seeds and two groups",
        }

    records_by_seed: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for record in group_records:
        if record.get("seed") is not None:
            records_by_seed[int(record["seed"])].append(record)

    rng = Random(seed)
    win_samples: dict[str, list[float]] = defaultdict(list)
    score_samples: dict[str, list[float]] = defaultdict(list)
    top_counts: Counter[str] = Counter()
    score_top_counts: Counter[str] = Counter()

    for _ in range(iterations):
        sampled_records: list[dict[str, Any]] = []
        for sampled_seed in (rng.choice(seeds) for _ in seeds):
            sampled_records.extend(records_by_seed[sampled_seed])
        aggregated = aggregate_records_for_bootstrap(sampled_records)
        if len(aggregated) < 2:
            continue
        for group_key, values in aggregated.items():
            win_samples[group_key].append(values["win_rate"])
            score_samples[group_key].append(values["avg_adjusted_final_score"])
        top_counts[
            max(aggregated.items(), key=lambda item: (item[1]["win_rate"], item[1]["avg_adjusted_final_score"]))[0]
        ] += 1
        score_top_counts[max(aggregated.items(), key=lambda item: item[1]["avg_adjusted_final_score"])[0]] += 1

    completed = max(sum(top_counts.values()), 1)
    intervals: dict[str, Any] = {}
    for group_key in groups:
        intervals[group_key] = {
            "win_rate_ci95": [
                round(percentile(win_samples[group_key], 0.025), 6),
                round(percentile(win_samples[group_key], 0.975), 6),
            ],
            "avg_adjusted_final_score_ci95": [
                round(percentile(score_samples[group_key], 0.025), 6),
                round(percentile(score_samples[group_key], 0.975), 6),
            ],
        }

    return {
        "method": "seed_bootstrap",
        "iterations": completed,
        "seed_count": len(seeds),
        "group_count": len(groups),
        "rank_stability_by_win_rate": {
            group_key: round(count / completed, 6) for group_key, count in sorted(top_counts.items())
        },
        "rank_stability_by_adjusted_score": {
            group_key: round(count / completed, 6) for group_key, count in sorted(score_top_counts.items())
        },
        "confidence_intervals": intervals,
    }


def summarize_leaderboard(
    leaderboard_payload: dict[str, Any],
    group_records: Sequence[dict[str, Any]],
    *,
    preferred_pair: tuple[str, str] | None,
) -> dict[str, Any]:
    entries = list(leaderboard_payload.get("entries", []))
    if not entries:
        return {"entries": 0, "can_distinguish": False}
    top = entries[0]
    bottom = entries[-1]
    win_rates = [float(entry.get("win_rate", 0.0)) for entry in entries]
    adjusted_scores = [float(entry.get("avg_adjusted_final_score", 0.0)) for entry in entries]
    win_rate_spread = max(win_rates) - min(win_rates)
    score_spread = max(adjusted_scores) - min(adjusted_scores)
    return {
        "entries": len(entries),
        "top_key": top.get("key"),
        "bottom_key": bottom.get("key"),
        "win_rate_spread": round(win_rate_spread, 6),
        "avg_adjusted_final_score_spread": round(score_spread, 6),
        "can_distinguish": len(entries) >= 2 and (abs(win_rate_spread) > 0 or abs(score_spread) > 0),
        "paired_delta": build_pairwise_delta(group_records, preferred_pair),
    }


def group_key_for_model(label: str) -> str:
    return f"model:{label}"


def group_key_for_framework(name: str) -> str:
    return f"framework:{name}"


def group_key_for_combined(framework: str, model_label: str) -> str:
    return f"framework:{framework}|model:{model_label}"


def run_experiment(
    *,
    axis: str,
    model_specs: Sequence[ModelSpec],
    frameworks: Sequence[FrameworkSpec],
    games: int,
    start_seed: int,
    player_count: int,
    max_days: int,
    output_dir: Path,
    runner: GameRunner = run_llm_game,
    game_timeout_s: int = 0,
) -> dict[str, Any]:
    if games <= 0:
        raise RuntimeError("--games must be positive.")
    if axis == "model" and len(model_specs) < 2:
        raise RuntimeError("--axis model requires at least two models in the pool.")
    if axis == "model" and len(frameworks) != 1:
        raise RuntimeError("--axis model uses exactly one framework; pass --frameworks cognitive_full.")

    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat()
    raw_game_records: list[dict[str, Any]] = []
    group_records: list[dict[str, Any]] = []
    metrics_for_leaderboard: list[GameMetrics] = []
    failures: list[dict[str, Any]] = []
    write_jsonl(output_dir / "game_runs.jsonl", [])
    write_jsonl(output_dir / "failures.jsonl", [])
    write_group_csv(output_dir / "group_results.csv", [])
    write_partial_summary(
        output_dir,
        started_at=started_at,
        axis=axis,
        games=games,
        start_seed=start_seed,
        player_count=player_count,
        max_days=max_days,
        game_timeout_s=game_timeout_s,
        model_specs=model_specs,
        frameworks=frameworks,
        raw_game_records=raw_game_records,
        failures=failures,
    )

    for framework in frameworks:
        for game_index in range(games):
            seed = start_seed + game_index
            print(f"[{axis}] framework={framework.name} seed={seed} ({game_index + 1}/{games})")
            run_started = time.perf_counter()
            try:
                result = run_game_with_optional_timeout(
                    seed,
                    player_count,
                    max_days,
                    model_specs,
                    framework,
                    game_index,
                    runner=runner,
                    timeout_s=game_timeout_s,
                )
            except Exception as exc:
                traceback.print_exc()
                failure = build_failure_record(
                    exc,
                    framework=framework.name,
                    seed=seed,
                    game_index=game_index,
                    elapsed_s=round(time.perf_counter() - run_started, 3),
                    timeout_s=game_timeout_s,
                )
                failures.append(failure)
                append_jsonl(output_dir / "failures.jsonl", failure)
                write_partial_summary(
                    output_dir,
                    started_at=started_at,
                    axis=axis,
                    games=games,
                    start_seed=start_seed,
                    player_count=player_count,
                    max_days=max_days,
                    game_timeout_s=game_timeout_s,
                    model_specs=model_specs,
                    frameworks=frameworks,
                    raw_game_records=raw_game_records,
                    failures=failures,
                )
                continue

            raw_record = dict(result.record)
            raw_record["axis"] = axis
            raw_game_records.append(raw_record)
            append_jsonl(output_dir / "game_runs.jsonl", raw_record)

            if axis == "framework":
                metric = result.metric
                key = group_key_for_framework(framework.name)
                metric.metadata.update(
                    {
                        "strategy_version": key,
                        "agent_version": key,
                        "experiment_axis": axis,
                        "seed": seed,
                        "framework": framework.name,
                    }
                )
                metrics_for_leaderboard.append(metric)
                group_records.append(metric_group_record(metric))
            elif axis == "model":
                player_to_group = {
                    player_id: group_key_for_model(model_label)
                    for player_id, model_label in result.player_model_labels.items()
                }
                for metric in split_metrics_by_player_group(
                    result.metric,
                    player_to_group,
                    axis=axis,
                    seed=seed,
                    framework=framework.name,
                ):
                    metrics_for_leaderboard.append(metric)
                    group_records.append(metric_group_record(metric))
            elif axis == "combined":
                player_to_group = {
                    player_id: group_key_for_combined(framework.name, model_label)
                    for player_id, model_label in result.player_model_labels.items()
                }
                for metric in split_metrics_by_player_group(
                    result.metric,
                    player_to_group,
                    axis=axis,
                    seed=seed,
                    framework=framework.name,
                ):
                    metrics_for_leaderboard.append(metric)
                    group_records.append(metric_group_record(metric))
            else:
                raise RuntimeError(f"Unsupported axis: {axis}")
            write_group_csv(output_dir / "group_results.csv", group_records)
            write_partial_summary(
                output_dir,
                started_at=started_at,
                axis=axis,
                games=games,
                start_seed=start_seed,
                player_count=player_count,
                max_days=max_days,
                game_timeout_s=game_timeout_s,
                model_specs=model_specs,
                frameworks=frameworks,
                raw_game_records=raw_game_records,
                failures=failures,
            )

    leaderboard = LeaderboardAggregator().aggregate_version(metrics_for_leaderboard)
    leaderboard.metadata.update(
        {
            "axis": axis,
            "started_at": started_at,
            "completed_raw_games": len(raw_game_records),
            "failed_games": len(failures),
            "player_count": player_count,
            "games_per_framework": games,
            "game_timeout_s": game_timeout_s,
            "model_pool": [spec.label for spec in model_specs],
            "frameworks": [framework.name for framework in frameworks],
            "unit_note": "version rows are grouped player-score samples; model/combined axes split each game by seat model.",
        }
    )
    leaderboard_payload = export_leaderboard(leaderboard, output_dir / "leaderboard.json")

    preferred_pair = None
    basic_key = group_key_for_framework("basic_react")
    full_key = (
        group_key_for_framework("full_cognitive")
        if any(record["group_key"] == group_key_for_framework("full_cognitive") for record in group_records)
        else group_key_for_framework("cognitive_full")
    )
    if axis == "framework" and basic_key in {record["group_key"] for record in group_records}:
        preferred_pair = (basic_key, full_key)

    summary = {
        "started_at": started_at,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "axis": axis,
        "games_per_framework": games,
        "start_seed": start_seed,
        "seeds": list(range(start_seed, start_seed + games)),
        "player_count": player_count,
        "max_days": max_days,
        "game_timeout_s": game_timeout_s,
        "model_pool": [spec.label for spec in model_specs],
        "frameworks": [
            {
                "name": framework.name,
                "description": framework.description,
                "env": dict(framework.env),
                "agent_framework_family": FRAMEWORK_FAMILY_MAP.get(framework.name, {}),
            }
            for framework in frameworks
        ],
        "agent_framework_families": {
            framework.name: FRAMEWORK_FAMILY_MAP.get(framework.name, {}) for framework in frameworks
        },
        "completed_raw_games": len(raw_game_records),
        "failed_games": len(failures),
        "attempted_games": len(raw_game_records) + len(failures),
        "failure_types": dict(sorted(Counter(str(item.get("error_type") or "unknown") for item in failures).items())),
        "leaderboard_summary": summarize_leaderboard(
            leaderboard_payload,
            group_records,
            preferred_pair=preferred_pair,
        ),
        "role_distribution_audit": build_role_audit(group_records),
        "role_win_rates": build_role_win_rates(group_records),
        "bootstrap_reliability": build_bootstrap_reliability(group_records),
        "failures": failures,
        "raw_records": raw_game_records,
        "outputs": {
            "leaderboard_json": str(output_dir / "leaderboard.json"),
            "architecture_evidence_leaderboard_json": str(output_dir / "architecture_evidence_leaderboard.json"),
            "architecture_evidence_leaderboard_csv": str(output_dir / "architecture_evidence_leaderboard.csv"),
            "summary_json": str(output_dir / "summary.json"),
            "partial_summary_json": str(output_dir / "partial_summary.json"),
            "group_results_csv": str(output_dir / "group_results.csv"),
            "game_runs_jsonl": str(output_dir / "game_runs.jsonl"),
            "failures_jsonl": str(output_dir / "failures.jsonl"),
            "academic_report_md": str(output_dir / "academic_report.md"),
        },
    }
    summary["architecture_evidence_leaderboard"] = build_architecture_evidence_leaderboard(
        group_records,
        summary_context=summary,
        leaderboard_payload=leaderboard_payload,
    )

    write_jsonl(output_dir / "game_runs.jsonl", raw_game_records)
    write_jsonl(output_dir / "failures.jsonl", failures)
    write_group_csv(output_dir / "group_results.csv", group_records)
    (output_dir / "architecture_evidence_leaderboard.json").write_text(
        json.dumps(summary["architecture_evidence_leaderboard"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_rubric_csv(output_dir / "architecture_evidence_leaderboard.csv", summary["architecture_evidence_leaderboard"])
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "academic_report.md").write_text(
        render_academic_report(summary, leaderboard_payload, group_records),
        encoding="utf-8",
    )
    return summary


def write_jsonl(path: Path, records: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _run_llm_game_worker(
    result_queue: Any,
    seed: int,
    player_count: int,
    max_days: int,
    model_specs: Sequence[ModelSpec],
    framework: FrameworkSpec,
    game_index: int,
) -> None:
    try:
        result = run_llm_game(seed, player_count, max_days, list(model_specs), framework, game_index)
        result_queue.put({"ok": True, "result": result})
    except BaseException as exc:
        result_queue.put(
            {
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(limit=12),
            }
        )


def run_game_with_optional_timeout(
    seed: int,
    player_count: int,
    max_days: int,
    model_specs: Sequence[ModelSpec],
    framework: FrameworkSpec,
    game_index: int,
    *,
    runner: GameRunner,
    timeout_s: int,
) -> GameRunResult:
    if timeout_s <= 0 or runner is not run_llm_game:
        return runner(seed, player_count, max_days, model_specs, framework, game_index)

    context_name = "fork" if "fork" in mp.get_all_start_methods() else "spawn"
    ctx = mp.get_context(context_name)
    result_queue = ctx.Queue(maxsize=1)
    proc = ctx.Process(
        target=_run_llm_game_worker,
        args=(result_queue, seed, player_count, max_days, list(model_specs), framework, game_index),
    )
    proc.start()
    proc.join(timeout_s)
    if proc.is_alive():
        proc.terminate()
        proc.join(5)
        if proc.is_alive():
            proc.kill()
            proc.join(5)
        raise GameTimeoutError(
            f"game timed out after {timeout_s}s (framework={framework.name}, seed={seed}, exitcode={proc.exitcode})"
        )

    try:
        payload = result_queue.get_nowait()
    except queue.Empty as exc:
        raise SubprocessGameError(
            {
                "error_type": "ChildProcessError",
                "error": f"game subprocess exited without result (exitcode={proc.exitcode})",
                "traceback": "",
            }
        ) from exc
    finally:
        result_queue.close()
        result_queue.join_thread()

    if payload.get("ok"):
        result = payload.get("result")
        if isinstance(result, GameRunResult):
            return result
        raise SubprocessGameError(
            {
                "error_type": "ChildProcessError",
                "error": f"game subprocess returned unexpected payload type: {type(result).__name__}",
                "traceback": "",
            }
        )
    raise SubprocessGameError(payload)


def build_failure_record(
    exc: Exception,
    *,
    framework: str,
    seed: int,
    game_index: int,
    elapsed_s: float,
    timeout_s: int,
) -> dict[str, Any]:
    if isinstance(exc, SubprocessGameError):
        error_type = exc.error_type
        error = str(exc)
        tb = exc.child_traceback
    else:
        error_type = type(exc).__name__
        error = str(exc)
        tb = traceback.format_exc(limit=8)
    return {
        "framework": framework,
        "seed": seed,
        "game_index": game_index,
        "error_type": error_type,
        "error": error,
        "traceback": tb,
        "elapsed_s": elapsed_s,
        "timeout_s": timeout_s,
        "external_failure": True,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


def write_partial_summary(
    output_dir: Path,
    *,
    started_at: str,
    axis: str,
    games: int,
    start_seed: int,
    player_count: int,
    max_days: int,
    game_timeout_s: int,
    model_specs: Sequence[ModelSpec],
    frameworks: Sequence[FrameworkSpec],
    raw_game_records: Sequence[dict[str, Any]],
    failures: Sequence[dict[str, Any]],
) -> None:
    payload = {
        "run_status": "partial",
        "started_at": started_at,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "axis": axis,
        "games_per_framework": games,
        "start_seed": start_seed,
        "seeds": list(range(start_seed, start_seed + games)),
        "player_count": player_count,
        "max_days": max_days,
        "game_timeout_s": game_timeout_s,
        "model_pool": [spec.label for spec in model_specs],
        "frameworks": [{"name": framework.name} for framework in frameworks],
        "completed_raw_games": len(raw_game_records),
        "failed_games": len(failures),
        "attempted_games": len(raw_game_records) + len(failures),
        "failure_types": dict(sorted(Counter(str(item.get("error_type") or "unknown") for item in failures).items())),
        "latest_failures": list(failures)[-10:],
        "outputs": {
            "game_runs_jsonl": str(output_dir / "game_runs.jsonl"),
            "failures_jsonl": str(output_dir / "failures.jsonl"),
            "group_results_csv": str(output_dir / "group_results.csv"),
            "summary_json": str(output_dir / "summary.json"),
        },
    }
    (output_dir / "partial_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_group_csv(path: Path, records: Sequence[dict[str, Any]]) -> None:
    fieldnames = [
        "seed",
        "source_game_id",
        "group_key",
        "framework",
        "players",
        "wins",
        "win_rate",
        "avg_adjusted_final_score",
        "avg_final_score",
        "avg_vote_score",
        "avg_speech_score",
        "avg_skill_score",
        "decision_count",
        "fallback_count",
        "invalid_count",
        "knowledge_hit_rate",
        "roles",
        "role_wins",
        "alignments",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            row = dict(record)
            row["roles"] = json.dumps(row.get("roles", {}), ensure_ascii=False, sort_keys=True)
            row["role_wins"] = json.dumps(row.get("role_wins", {}), ensure_ascii=False, sort_keys=True)
            row["alignments"] = json.dumps(row.get("alignments", {}), ensure_ascii=False, sort_keys=True)
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def write_rubric_csv(path: Path, payload: dict[str, Any]) -> None:
    fieldnames = [
        "rank",
        "group_key",
        "framework",
        "rubric_total_score",
        "single_agent",
        "multi_agent",
        "engineering",
        "advanced_bc",
        "win_rate",
        "avg_adjusted_final_score",
        "macro_role_win_rate",
        "knowledge_hit_rate",
        "completion_rate",
        "attempt_completion_rate",
        "external_failed_games",
        "external_failure_rate",
        "fallback_count",
        "invalid_count",
        "core_role_coverage",
        "track_b_rank_score",
        "paired_candidate_delta_score",
        "bootstrap_reliability_score",
        "seat_samples",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for entry in payload.get("entries", []):
            dims = entry.get("rubric_dimensions", {})
            signals = entry.get("evidence_signals", {})
            row = {
                "rank": entry.get("rank"),
                "group_key": entry.get("group_key"),
                "framework": entry.get("framework"),
                "rubric_total_score": entry.get("rubric_total_score"),
                "single_agent": dims.get("single_agent"),
                "multi_agent": dims.get("multi_agent"),
                "engineering": dims.get("engineering"),
                "advanced_bc": dims.get("advanced_bc"),
                "win_rate": signals.get("win_rate"),
                "avg_adjusted_final_score": signals.get("avg_adjusted_final_score"),
                "macro_role_win_rate": signals.get("macro_role_win_rate"),
                "knowledge_hit_rate": signals.get("knowledge_hit_rate"),
                "completion_rate": signals.get("completion_rate"),
                "attempt_completion_rate": signals.get("attempt_completion_rate"),
                "external_failed_games": signals.get("external_failed_games"),
                "external_failure_rate": signals.get("external_failure_rate"),
                "fallback_count": signals.get("fallback_count"),
                "invalid_count": signals.get("invalid_count"),
                "core_role_coverage": signals.get("core_role_coverage"),
                "track_b_rank_score": signals.get("track_b_rank_score"),
                "paired_candidate_delta_score": signals.get("paired_candidate_delta_score"),
                "bootstrap_reliability_score": signals.get("bootstrap_reliability_score"),
                "seat_samples": signals.get("seat_samples"),
            }
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def render_academic_report(
    summary: dict[str, Any],
    leaderboard_payload: dict[str, Any],
    group_records: Sequence[dict[str, Any]],
) -> str:
    lines = [
        "# Track B/C 学术实验报告",
        "",
        "## 研究问题",
        "",
        "- RQ1: Track B leaderboard 是否能区分不同模型或不同 Agent 框架的表现差异？",
        "- RQ2: Track C 策略回流/认知增强是否相对 basic LLM/ReAct baseline 提供非冗余增益？",
        "",
        "## 实验设置",
        "",
        f"- Axis: `{summary['axis']}`",
        f"- Games per framework: `{summary['games_per_framework']}`",
        f"- Seeds: `{summary['seeds'][0]}` to `{summary['seeds'][-1]}`",
        f"- Player count: `{summary['player_count']}`",
        f"- Max days: `{summary['max_days']}`",
        f"- Model pool: `{', '.join(summary['model_pool'])}`",
        f"- Completed raw games: `{summary['completed_raw_games']}`",
        f"- Failed games: `{summary['failed_games']}`",
        "- Scoring note: whole-game run failures such as API/key/subprocess errors are excluded from Agent scores; "
        "they are reported only as external run-health signals.",
        "",
        "## Agent Framework 对照矩阵",
        "",
        "| Framework | Paper-family mapping | Role in comparison | Enabled modules |",
        "|---|---|---|---|",
    ]
    for framework in summary.get("frameworks", []):
        family = framework.get("agent_framework_family", {})
        env = framework.get("env", {})
        enabled = []
        if env.get("COGNITIVE_ENABLE_ANTI_PATTERNS") == "1":
            enabled.append("role/anti-pattern")
        if env.get("COGNITIVE_ENABLE_TRACK_C") == "1":
            enabled.append("Track C retrieval")
        if env.get("COGNITIVE_ENABLE_REFLECTION") == "1":
            enabled.append("reflection")
        if not enabled:
            enabled.append("none")
        lines.append(
            "| "
            f"`{framework.get('name')}` | {family.get('paper_family', '')} | "
            f"{family.get('comparison_role', '')} | {', '.join(enabled)} |"
        )

    lines.extend(
        [
            "",
            "## Track B Leaderboard",
            "",
            "| Rank | Key | Seat Samples | Win Rate | Avg Adjusted Score | Vote | Speech | Skill | Critical Mistakes |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for rank, entry in enumerate(leaderboard_payload.get("entries", []), start=1):
        lines.append(
            "| "
            f"{rank} | `{entry['key']}` | {entry['games_played']} | {entry['win_rate']:.3f} | "
            f"{entry['avg_adjusted_final_score']:.2f} | {entry['avg_vote_score']:.2f} | "
            f"{entry['avg_speech_score']:.2f} | {entry['avg_skill_score']:.2f} | "
            f"{entry['critical_mistakes']} |"
        )

    rubric = summary.get("architecture_evidence_leaderboard", {})
    lines.extend(
        [
            "",
            "## Architecture Evidence Leaderboard（按架构证据映射）",
            "",
            "该表把同一组实验信号映射到项目架构证据："
            "Agent 决策、多 Agent 协作、工程闭环、复盘与知识回流。"
            "它用于展示架构优势，不替代上方 Track B 原始指标。",
            "整局失败/API 错误不进入该表主分，只在 Evidence 中作为 external_fail 单独报告。",
            "",
            "| Rank | Key | Total | Single Agent /20 | Multi-Agent /20 | Engineering /30 | Track B/C /30 | Evidence |",
            "|---:|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for entry in rubric.get("entries", []):
        dims = entry.get("rubric_dimensions", {})
        signals = entry.get("evidence_signals", {})
        evidence = (
            f"score={signals.get('avg_adjusted_final_score')}, "
            f"win={signals.get('win_rate')}, "
            f"macro_role={signals.get('macro_role_win_rate')}, "
            f"hit={signals.get('knowledge_hit_rate')}, "
            f"external_fail={signals.get('external_failure_rate')}, "
            f"fallback={signals.get('fallback_count')}, invalid={signals.get('invalid_count')}"
        )
        lines.append(
            "| "
            f"{entry.get('rank')} | `{entry.get('group_key')}` | {entry.get('rubric_total_score'):.2f} | "
            f"{dims.get('single_agent', 0.0):.2f} | {dims.get('multi_agent', 0.0):.2f} | "
            f"{dims.get('engineering', 0.0):.2f} | {dims.get('advanced_bc', 0.0):.2f} | "
            f"{evidence} |"
        )

    lb = summary["leaderboard_summary"]
    lines.extend(
        [
            "",
            "## 区分度结论",
            "",
            f"- Top key: `{lb.get('top_key')}`",
            f"- Bottom key: `{lb.get('bottom_key')}`",
            f"- Win-rate spread: `{lb.get('win_rate_spread')}`",
            f"- Avg adjusted score spread: `{lb.get('avg_adjusted_final_score_spread')}`",
            f"- Track B can distinguish in this run: `{lb.get('can_distinguish')}`",
        ]
    )

    paired = lb.get("paired_delta") or {}
    if paired:
        lines.extend(
            [
                "",
                "## Paired Seed Delta",
                "",
                f"- Baseline: `{paired.get('baseline')}`",
                f"- Candidate: `{paired.get('candidate')}`",
                f"- Paired seed count: `{paired.get('paired_seed_count')}`",
                f"- Avg adjusted score delta: `{paired.get('avg_adjusted_final_score_delta')}`",
                f"- Avg win-rate delta: `{paired.get('avg_win_rate_delta')}`",
                f"- Positive score-delta seeds: `{paired.get('positive_score_delta_seeds')}`",
                f"- Positive win-rate-delta seeds: `{paired.get('positive_win_rate_delta_seeds')}`",
            ]
        )

    if summary["axis"] == "framework":
        lines.extend(
            [
                "",
                "## Track C 非冗余性说明",
                "",
                "本实验在相同 seeds、相同角色配置和相同模型池下比较 Agent 框架。"
                "`basic_react` 保留 LLM 决策能力，但关闭 Track C 策略注入、反模式提示和赛后反思；"
                "`full_cognitive`/`cognitive_full` 启用完整框架。若 paired delta 或 leaderboard 排名显示稳定增益，"
                "则说明 Track C/认知层提供了基础 LLM 推理之外的增量价值，而不是冗余 UI 或冗余工程模块。",
            ]
        )

    lines.extend(["", "## 角色分布审计", ""])
    for group_key, audit in summary["role_distribution_audit"].items():
        lines.append(
            f"- `{group_key}`: seat_samples={audit['seat_samples']}, "
            f"roles={json.dumps(audit['roles'], ensure_ascii=False, sort_keys=True)}, "
            f"alignments={json.dumps(audit['alignments'], ensure_ascii=False, sort_keys=True)}"
        )

    lines.extend(["", "## Role-Wise Win Rates", ""])
    for group_key, rates in summary.get("role_win_rates", {}).items():
        lines.append(
            f"- `{group_key}`: macro={rates.get('macro_role_win_rate')}, "
            f"micro={rates.get('micro_role_win_rate')}, "
            f"roles={json.dumps(rates.get('role_win_rates', {}), ensure_ascii=False, sort_keys=True)}"
        )

    reliability = summary.get("bootstrap_reliability", {})
    lines.extend(["", "## Bootstrap Reliability", ""])
    if reliability.get("iterations", 0):
        lines.extend(
            [
                f"- Method: `{reliability.get('method')}`",
                f"- Iterations: `{reliability.get('iterations')}`",
                f"- Rank stability by win rate: "
                f"`{json.dumps(reliability.get('rank_stability_by_win_rate', {}), ensure_ascii=False, sort_keys=True)}`",
                f"- Rank stability by adjusted score: "
                f"`{json.dumps(reliability.get('rank_stability_by_adjusted_score', {}), ensure_ascii=False, sort_keys=True)}`",
                f"- Confidence intervals: "
                f"`{json.dumps(reliability.get('confidence_intervals', {}), ensure_ascii=False, sort_keys=True)}`",
            ]
        )
    else:
        lines.append(f"- Not enough seeds/groups for bootstrap: `{reliability.get('reason', 'unknown')}`")

    lines.extend(
        [
            "",
            "## 有效性威胁",
            "",
            "- 小样本只能作为 smoke/趋势证据；正式报告建议每个条件至少 20 个 seeds。",
            "- 如果模型池包含多个模型，framework 轴结果表示在该模型池上的平均框架效应。",
            "- model/combined 轴按玩家座位拆分 Track B 分数，因此 `games_played` 表示座位样本数，不是原始局数。",
            "- 真实 LLM 实验应保持 fallback_count=0 或在报告中单独解释 fallback 对结果的影响。",
            "",
            f"_Generated at {summary['generated_at']}._",
        ]
    )
    if group_records:
        lines.extend(["", f"Group-level rows: `{len(group_records)}`"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--axis", choices=["model", "framework", "combined"], default="framework")
    parser.add_argument("--models", default="", help="Comma-separated provider:model list. Overrides env model pools.")
    parser.add_argument(
        "--frameworks",
        default="basic_react,role_guarded_react,rag_react,reflexion_react,rag_reflexion,full_cognitive",
        help=(
            "Comma-separated framework names. Use full_cognitive or cognitive_full for --axis model. "
            "Backward-compatible names anti_only, trackc_only, cognitive_full remain supported."
        ),
    )
    parser.add_argument(
        "--games",
        type=int,
        default=DEFAULT_GAMES_PER_FRAMEWORK,
        help="Games per framework condition (minimum 5 recommended for statistical power).",
    )
    parser.add_argument("--start-seed", type=int, default=1001)
    parser.add_argument("--player-count", type=int, default=7)
    parser.add_argument("--max-days", type=int, default=20)
    parser.add_argument("--output-dir", default="outputs/track_bc_leaderboard")
    parser.add_argument(
        "--game-timeout-s",
        type=int,
        default=0,
        help="Per-game subprocess timeout for the default real LLM runner. 0 disables subprocess timeout.",
    )
    parser.add_argument("--allow-fake", action="store_true", default=str_to_bool(os.getenv("ALLOW_OFFLINE_FAKE_LLM")))
    parser.add_argument("--skip-client-check", action="store_true")
    parser.add_argument("--strict-fallback", default="true")
    args = parser.parse_args()

    load_env_file()
    os.environ["AIWEREWOLF_STRICT_MODE"] = "true" if str_to_bool(args.strict_fallback) else "false"

    model_specs = resolve_model_specs(args.models)
    validate_model_specs(model_specs, allow_fake=args.allow_fake, skip_client_check=args.skip_client_check)
    frameworks = resolve_frameworks(args.frameworks)

    if args.axis == "model" and len(frameworks) != 1:
        raise SystemExit("--axis model should use exactly one framework, for example --frameworks cognitive_full.")

    output_dir = Path(args.output_dir)
    started = time.perf_counter()
    summary = run_experiment(
        axis=args.axis,
        model_specs=model_specs,
        frameworks=frameworks,
        games=args.games,
        start_seed=args.start_seed,
        player_count=args.player_count,
        max_days=args.max_days,
        output_dir=output_dir,
        game_timeout_s=args.game_timeout_s,
    )
    elapsed_s = time.perf_counter() - started

    print()
    print("Track B/C experiment complete")
    print(f"  elapsed_s={elapsed_s:.1f}")
    print(f"  completed_raw_games={summary['completed_raw_games']}")
    print(f"  failed_games={summary['failed_games']}")
    print(f"  leaderboard={output_dir / 'leaderboard.json'}")
    print(f"  report={output_dir / 'academic_report.md'}")
    return 0 if summary["failed_games"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
