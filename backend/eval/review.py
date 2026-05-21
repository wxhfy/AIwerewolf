from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from backend.engine.models import GameState


@dataclass
class ReviewArtifact:
    """Structured replay/review payload for downstream RAG systems."""

    game_id: str
    winner: str | None
    timeline: list[dict[str, Any]]
    daily_summaries: dict[int, list[str]]
    daily_summary_facts: dict[int, list[dict[str, Any]]]
    metadata: dict[str, Any] = field(default_factory=dict)


class ReviewProvider(Protocol):
    """Builds review artifacts from a completed game.

    GraphRAG can index these artifacts into graph nodes such as player, claim,
    vote edge, contradiction edge, and decisive event clusters.
    """

    def build_artifact(self, state: GameState) -> ReviewArtifact:
        ...


class GraphRAGReviewProvider:
    """Default review adapter for future GraphRAG ingestion.

    This class intentionally does not implement retrieval/indexing yet.
    It standardizes the export boundary so a later GraphRAG pipeline can
    consume stable replay artifacts without changing the core game engine.
    """

    def build_artifact(self, state: GameState) -> ReviewArtifact:
        return ReviewArtifact(
            game_id=state.id,
            winner=state.winner.value if state.winner else None,
            timeline=[event.to_dict() for event in state.events],
            daily_summaries=dict(state.daily_summaries),
            daily_summary_facts=dict(state.daily_summary_facts),
            metadata={
                "day": state.day,
                "phase": state.phase.value,
                "player_count": len(state.players),
                "alive_count": sum(1 for player in state.players if player.alive),
            },
        )
