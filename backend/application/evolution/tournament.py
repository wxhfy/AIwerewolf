"""Isolated paired tournament tasks returning JSON artifacts, without DB writes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import fields
from typing import Any

from backend.agent_memory import ActorMemoryService
from backend.application.agents.harness_runtime import build_harness_runtime
from backend.engine.game import WerewolfGame
from backend.engine.models import Phase
from backend.eval.evolution import RoleStrategyCard
from backend.eval.review import GameMetrics
from backend.eval.review import MetricsCalculator
from backend.eval.review import PlayerScore


@dataclass(frozen=True)
class TournamentTask:
    task_id: str
    seed: int
    baseline: RoleStrategyCard
    candidate: RoleStrategyCard
    provider: str | None = None
    model: str | None = None
    player_count: int = 7
    max_days: int = 20


class _EventCounter:
    def __init__(self) -> None:
        self.count = 0

    def save(self, _request, events) -> None:
        self.count += len(events)


class TournamentWorker:
    """One pair per task, using identical seat/role/persona/model assignment.

    Each side has a fresh harness and in-memory memory service. No repository,
    promotion function, or live-game persistence callbacks enter a subtask.
    """

    def execute(self, task: TournamentTask) -> dict[str, Any]:
        baseline = self._play(task, task.baseline, "baseline")
        candidate = self._play(task, task.candidate, "candidate")
        if baseline.metadata["lineup_hash"] != candidate.metadata["lineup_hash"]:
            raise ValueError("Tournament pair has different seat/role/persona/model assignments")
        return {
            "schema_version": "paired-tournament-v1",
            "task_id": task.task_id,
            "seed": task.seed,
            "lineup_hash": baseline.metadata["lineup_hash"],
            "baseline": asdict(baseline),
            "candidate": asdict(candidate),
            "synthetic": bool(baseline.metadata["synthetic"] or candidate.metadata["synthetic"]),
        }

    def _play(self, task: TournamentTask, card: RoleStrategyCard, side: str) -> GameMetrics:
        bias = {key: list(getattr(card, key)) for key in ("speech_policy", "vote_policy", "skill_policy", "risk_rules")}
        # No callbacks: experiments must not create live match/outbox jobs.
        game = WerewolfGame(
            seed=task.seed,
            player_count=task.player_count,
            max_days=task.max_days,
            strategy_version=card.version,
            strategy_bias_by_role={card.role: bias},
            game_id=f"{task.task_id}:{side}",
        )
        config = {
            "type": "llm",
            "seed": task.seed,
            "strategy_version": card.version,
            "role_models": {card.role: {"strategy_bias": bias}},
        }
        if task.provider:
            config["provider"] = task.provider
        if task.model:
            config["model"] = task.model
        runtime = build_harness_runtime(game.state.players, config)
        runtime.memory = ActorMemoryService()
        runtime.event_repository = _EventCounter()
        game.attach_decision_runtime(runtime)
        assignments = [
            {"seat": p.seat, "provider": str(runtime.harnesses[p.id].planner.client.provider), "model": p.model_name}
            for p in sorted(game.state.players, key=lambda p: p.seat)
        ]
        lineup = [
            {"seat": p.seat, "role": p.role.value, "persona": p.persona, "model": p.model_name}
            for p in sorted(game.state.players, key=lambda p: p.seat)
        ]
        lineup_hash = hashlib.sha256(json.dumps([lineup, assignments], sort_keys=True).encode()).hexdigest()
        game.play()
        if game.state.phase != Phase.GAME_END:
            raise RuntimeError("Tournament did not reach GAME_END")
        metrics = MetricsCalculator().compute(game.state)
        decisions = game.state.decision_records
        invalid = sum(not d.is_valid for d in decisions)
        metadata = [dict((d.parsed_action or {}).get("metadata") or {}) for d in decisions]
        fallbacks = sum(
            bool(getattr(d, "fallback_used", False))
            or bool((d.parsed_action or {}).get("agent_fallback"))
            or any(bool(meta.get(key)) for key in ("fallback", "fallback_used", "safe_degradation_used"))
            for d, meta in zip(decisions, metadata)
        )
        attempted_leaks = sum(
            bool(
                {"wolf_private_perspective", "internal_score_disclosure"}.intersection(
                    meta.get("speech_policy_violations") or []
                )
            )
            for meta in metadata
        )
        synthetic = any(item["provider"] == "fake" or "fake" in item["model"].lower() for item in assignments)
        metrics.metadata.update(
            {
                "tournament_seed": task.seed,
                "target_role": card.role,
                "strategy_version": card.version,
                "lineup_hash": lineup_hash,
                "phase": game.state.phase.value,
                "runner_mode": "isolated_llm_engine",
                "synthetic": synthetic,
                "model_assignments": assignments,
                "invalid_action_count": invalid,
                "rule_violation_count": invalid,
                "invalid_action_rate": invalid / max(len(decisions), 1),
                "fallback_count": fallbacks,
                # Unknown attribution fails closed; all fallbacks are gate failures.
                "patch_caused_fallback_count": fallbacks,
                "info_leak_count": int(metrics.metadata.get("info_leak_count", 0)) + attempted_leaks,
                "strategy_bias_sections": sorted(k for k, v in bias.items() if v),
                "harness_event_count": runtime.event_repository.count,
            }
        )
        return metrics


def metric_from_artifact(payload: dict[str, Any]) -> GameMetrics:
    keys = {field.name for field in fields(PlayerScore)}
    return GameMetrics(
        game_id=payload["game_id"],
        winner=payload.get("winner"),
        total_days=int(payload.get("total_days", 0)),
        total_events=int(payload.get("total_events", 0)),
        wolf_elimination_rate=float(payload.get("wolf_elimination_rate", 0)),
        village_survival_rate=float(payload.get("village_survival_rate", 0)),
        info_efficiency=float(payload.get("info_efficiency", 0)),
        player_scores=[
            PlayerScore(**{k: v for k, v in score.items() if k in keys}) for score in payload["player_scores"]
        ],
        metadata=dict(payload.get("metadata") or {}),
    )


def card_with_patch(base: RoleStrategyCard, patch) -> RoleStrategyCard:
    from backend.eval.evolution import VersionManager

    manager = VersionManager([base])
    return manager.create_candidate(patch).card
