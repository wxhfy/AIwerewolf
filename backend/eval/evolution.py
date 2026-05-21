from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from backend.eval.review import ReviewArtifact


@dataclass
class EvolutionRecord:
    """Tracks a future self-improvement step."""

    strategy_version: str
    observations: list[str] = field(default_factory=list)
    proposed_changes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class EvolutionHook(Protocol):
    """Post-game self-improvement hook."""

    def evolve(self, artifact: ReviewArtifact) -> EvolutionRecord:
        ...


class HermesEvolutionHook:
    """Placeholder boundary for a Hermes-style self-improving outer loop.

    Intended future loop:
    1. Ingest ReviewArtifact
    2. Ask GraphRAG for decisive contradictions, failed reads, and good lines
    3. Produce prompt/memory/strategy deltas
    4. Version and replay against a baseline
    """

    def __init__(self, strategy_version: str = "v0") -> None:
        self.strategy_version = strategy_version

    def evolve(self, artifact: ReviewArtifact) -> EvolutionRecord:
        observations = [
            f"Game {artifact.game_id} ended with winner={artifact.winner}",
            f"Timeline events indexed: {len(artifact.timeline)}",
            f"Daily summaries available: {len(artifact.daily_summaries)}",
        ]
        proposed_changes = [
            "Integrate contradiction edges from votes, claims, and deaths into GraphRAG.",
            "Score role-specific mistakes and convert them into prompt or memory adjustments.",
            "Replay updated agents against a frozen baseline before promotion.",
        ]
        return EvolutionRecord(
            strategy_version=self.strategy_version,
            observations=observations,
            proposed_changes=proposed_changes,
            metadata={"mode": "placeholder"},
        )
