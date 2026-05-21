"""Advanced C: 自进化 Agent — self-improving outer loop.

Interfaces:
- EvolutionRecord: tracks one self-improvement step
- StrategyVersion: versioned strategy configuration
- EvolutionHook: post-game self-improvement trigger
- ABComparison: A/B test results between strategy versions
- EvolutionLoop: orchestrates the "game→analyze→adjust→replay" cycle
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, Sequence

from backend.eval.review import BadCaseReport, GameMetrics, ReviewArtifact


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class EvolutionRecord:
    """Tracks one self-improvement step with full audit trail."""

    strategy_version: str
    parent_version: str | None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    observations: list[str] = field(default_factory=list)
    proposed_changes: list[str] = field(default_factory=list)
    applied_changes: list[str] = field(default_factory=list)
    replay_results: dict[str, Any] = field(default_factory=dict)
    promoted: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyVersion:
    """Versioned snapshot of agent strategies for rollback and A/B testing."""

    version: str
    role: str
    prompt_template: str
    role_profile: dict[str, str]
    playbook: dict[str, list[str]]
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    parent: str | None = None
    notes: str = ""


@dataclass
class ABComparison:
    """A/B test result between two strategy versions."""

    version_a: str
    version_b: str
    total_games: int
    a_wins: int
    b_wins: int
    a_metrics: list[GameMetrics] = field(default_factory=list)
    b_metrics: list[GameMetrics] = field(default_factory=list)
    winner: str | None = None  # "a", "b", or None (tie)
    confidence: float = 0.0  # statistical confidence (p-value)


# ---------------------------------------------------------------------------
# Provider interfaces
# ---------------------------------------------------------------------------


class EvolutionHook(Protocol):
    """Post-game self-improvement trigger.

    Intended loop:
    1. Ingest ReviewArtifact → get decisive mistakes and patterns
    2. Generate prompt/memory/policy deltas per role
    3. Version the updated strategy
    4. Replay against frozen baseline
    5. Promote only if metrics improve
    """

    def evolve(self, artifact: ReviewArtifact) -> EvolutionRecord: ...

    def rollback(self, target_version: str) -> StrategyVersion: ...

    def version_history(self) -> list[StrategyVersion]: ...


class EvolutionLoop(Protocol):
    """Orchestrates multi-game self-evolution cycles.

    Loop: game → analyze → adjust → replay → compare → promote/rollback
    """

    def run_cycle(self, num_games: int = 10) -> list[EvolutionRecord]: ...

    def ab_compare(self, version_a: str, version_b: str, num_games: int = 20) -> ABComparison: ...


# ---------------------------------------------------------------------------
# Default implementation
# ---------------------------------------------------------------------------


class HermesEvolutionHook:
    """Placeholder boundary for Hermes-style self-improving loop.

    Future implementation:
    1. Games export ReviewArtifact with full timelines
    2. GraphRAG extracts contradictions, failed reads, and strong lines
    3. LLM generates prompt/memory adjustments per role
    4. Adjusted agents replayed against frozen baseline in A/B test
    5. Promotion only if win rate improves with confidence > 95%
    """

    def __init__(self, strategy_version: str = "v0") -> None:
        self.strategy_version = strategy_version
        self._history: list[EvolutionRecord] = []
        self._versions: dict[str, StrategyVersion] = {}

    def evolve(self, artifact: ReviewArtifact) -> EvolutionRecord:
        observations = [
            f"Game {artifact.game_id} winner={artifact.winner}",
            f"Timeline events: {len(artifact.timeline)}",
            f"Daily summaries: {len(artifact.daily_summaries)}",
        ]
        proposed = [
            "1. Index contradiction edges (vote vs claim vs death) into GraphRAG",
            "2. Score role-specific mistakes → prompt/policy delta",
            "3. A/B replay updated vs frozen baseline (20 games)",
            "4. Promote only if win rate improves (p < 0.05)",
        ]
        record = EvolutionRecord(
            strategy_version=self.strategy_version,
            parent_version=None if not self._history else self._history[-1].strategy_version,
            observations=observations,
            proposed_changes=proposed,
            applied_changes=[],
            promoted=False,
            metadata={"mode": "interface_placeholder", "artifact_id": artifact.game_id},
        )
        self._history.append(record)
        return record

    def rollback(self, target_version: str) -> StrategyVersion:
        if target_version not in self._versions:
            raise KeyError(f"Version {target_version} not found in history")
        return self._versions[target_version]

    def version_history(self) -> list[StrategyVersion]:
        return list(self._versions.values())

    def save_version(self, sv: StrategyVersion) -> None:
        self._versions[sv.version] = sv
        if sv.version > self.strategy_version:
            self.strategy_version = sv.version


class SimpleEvolutionLoop:
    """Minimal evolution loop scaffolding.

    Intended for incremental implementation:
    - Batch game execution
    - Metrics aggregation
    - Strategy delta generation
    - A/B comparison with baseline
    """

    def __init__(self, hook: EvolutionHook) -> None:
        self.hook = hook
        self.records: list[EvolutionRecord] = []

    def run_cycle(self, num_games: int = 10) -> list[EvolutionRecord]:
        """Placeholder: run N games, evolve after each, collect records."""
        # In real implementation:
        # for i in range(num_games):
        #     state = run_game()
        #     artifact = review_provider.build_artifact(state)
        #     record = self.hook.evolve(artifact)
        #     self.records.append(record)
        return self.records

    def ab_compare(self, version_a: str, version_b: str, num_games: int = 20) -> ABComparison:
        """Placeholder: run A/B comparison between two strategy versions."""
        return ABComparison(
            version_a=version_a,
            version_b=version_b,
            total_games=num_games,
            a_wins=0,
            b_wins=0,
            winner=None,
            confidence=0.0,
        )
