from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Protocol

from backend.engine.models import GameState
from backend.engine.models import Role


@dataclass
class AgentConfigPatch:
    """Structured optimizer output for future multi-agent tuning systems."""

    role: Role | None = None
    prompt_delta: list[str] = field(default_factory=list)
    memory_delta: list[str] = field(default_factory=list)
    policy_delta: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OptimizationResult:
    optimizer_name: str
    strategy_version: str
    patches: list[AgentConfigPatch] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class MultiAgentOptimizer(Protocol):
    """Common extension boundary for future optimization schemes."""

    def optimize(self, games: list[GameState]) -> OptimizationResult: ...


class ReplayHeuristicOptimizer:
    """Stable placeholder interface for future optimizer implementations.

    Compatible future directions:
    - GraphRAG-guided replay tuning
    - Hermes-style self-evolution loops
    - Self-play policy iteration
    - Population-based prompt search
    - Role-specific memory tuning
    """

    def __init__(self, strategy_version: str = "v0") -> None:
        self.strategy_version = strategy_version

    def optimize(self, games: list[GameState]) -> OptimizationResult:
        return OptimizationResult(
            optimizer_name="ReplayHeuristicOptimizer",
            strategy_version=self.strategy_version,
            notes=[
                f"Observed {len(games)} games.",
                "No patch applied yet; this module exists to keep future optimizer integrations stable.",
            ],
            metadata={"mode": "placeholder"},
        )
