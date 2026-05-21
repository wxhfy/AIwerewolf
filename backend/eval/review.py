"""Advanced B: 评测+复盘 — multi-dimension evaluation and replay analysis.

Interfaces:
- ReviewArtifact: structured replay payload for downstream analysis
- RoleMetrics: per-role performance indicators
- GameMetrics: game-level statistics
- ReviewProvider: builds artifacts from completed games
- Leaderboard: compares agent versions/models across matches
- BadCaseDetector: identifies decisive mistakes for review
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

from backend.engine.models import GameState


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ReviewArtifact:
    """Structured replay payload for RAG indexing and review analysis."""

    game_id: str
    winner: str | None
    timeline: list[dict[str, Any]]
    daily_summaries: dict[int, list[str]]
    daily_summary_facts: dict[int, list[dict[str, Any]]]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RoleMetrics:
    """Per-role performance metrics (Advanced B scoring dimensions)."""

    role: str
    player_name: str
    # Survival
    alive_at_end: bool
    survival_rounds: int
    # Decision quality
    vote_precision: float  # fraction of votes that hit wolves
    useful_ability_uses: int  # number of ability uses that benefited own team
    total_ability_uses: int
    # Deception (wolves only)
    deception_score: float = 0.0  # how well wolf avoided suspicion
    # Notes
    mistakes: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)


@dataclass
class GameMetrics:
    """Game-level statistics for one match."""

    game_id: str
    winner: str | None
    total_days: int
    total_events: int
    wolf_elimination_rate: float  # wolves voted out / total wolves
    village_survival_rate: float  # villagers alive at end / total villagers
    info_efficiency: float  # useful info events / total events
    role_metrics: list[RoleMetrics] = field(default_factory=list)


@dataclass
class LeaderboardEntry:
    """One row in a model/version comparison table."""

    agent_id: str  # model name or version identifier
    role: str
    games_played: int
    wins: int
    win_rate: float
    avg_vote_precision: float
    avg_survival_rounds: float
    notes: str = ""


@dataclass
class BadCaseReport:
    """A detected mistake with improvement suggestions."""

    game_id: str
    day: int
    player_name: str
    role: str
    mistake_type: str  # "vote", "ability", "speech", "info_leak"
    description: str
    suggested_fix: str
    severity: str  # "critical", "major", "minor"


# ---------------------------------------------------------------------------
# Provider interfaces (Protocols for swappable implementations)
# ---------------------------------------------------------------------------


class ReviewProvider(Protocol):
    """Builds review artifacts from a completed game.

    GraphRAG can index these artifacts into graph nodes: player, claim,
    vote edge, contradiction edge, and decisive event clusters.
    """

    def build_artifact(self, state: GameState) -> ReviewArtifact: ...

    def compute_metrics(self, state: GameState) -> GameMetrics: ...

    def detect_bad_cases(self, state: GameState) -> list[BadCaseReport]: ...


class LeaderboardProvider(Protocol):
    """Maintains and queries a cross-game leaderboard."""

    def add_game(self, metrics: GameMetrics) -> None: ...

    def top_agents(self, role: str, limit: int = 10) -> list[LeaderboardEntry]: ...

    def compare_versions(self, version_a: str, version_b: str) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Default implementations
# ---------------------------------------------------------------------------


class GraphRAGReviewProvider:
    """Default review adapter for GraphRAG ingestion.

    Exports stable replay artifacts without changing the core engine.
    Future: integrate with GraphRAG retrieval, contradiction detection,
    and decisive event clustering.
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
                "alive_count": sum(1 for p in state.players if p.alive),
            },
        )

    def compute_metrics(self, state: GameState) -> GameMetrics:
        """Compute role-level and game-level metrics from a completed game."""
        role_metrics: list[RoleMetrics] = []
        for player in state.players:
            vote_hits = sum(
                1
                for event in state.events
                if event.type.value == "VOTE_CAST"
                and event.payload.get("voter_id") == player.id
                and event.payload.get("target_alignment") == "wolf"
            )
            vote_total = sum(
                1
                for event in state.events
                if event.type.value == "VOTE_CAST" and event.payload.get("voter_id") == player.id
            )
            role_metrics.append(
                RoleMetrics(
                    role=player.role.value,
                    player_name=player.name,
                    alive_at_end=player.alive,
                    survival_rounds=player.alive * state.day,
                    vote_precision=vote_hits / max(vote_total, 1),
                    useful_ability_uses=0,
                    total_ability_uses=0,
                )
            )

        return GameMetrics(
            game_id=state.id,
            winner=state.winner.value if state.winner else None,
            total_days=state.day,
            total_events=len(state.events),
            wolf_elimination_rate=sum(1 for p in state.players if p.role.value == "Werewolf" and not p.alive)
            / max(sum(1 for p in state.players if p.role.value == "Werewolf"), 1),
            village_survival_rate=sum(1 for p in state.players if p.alignment.value == "village" and p.alive)
            / max(sum(1 for p in state.players if p.alignment.value == "village"), 1),
            info_efficiency=sum(1 for e in state.events if e.type.value == "PRIVATE_INFO")
            / max(len(state.events), 1),
            role_metrics=role_metrics,
        )

    def detect_bad_cases(self, state: GameState) -> list[BadCaseReport]:
        """Detect obvious mistakes: voting for own team, unused abilities, etc."""
        reports: list[BadCaseReport] = []
        for event in state.events:
            if event.type.value == "VOTE_CAST":
                voter_id = event.payload.get("voter_id")
                target_id = event.payload.get("target_id")
                voter = state.player(voter_id)
                target = state.player(target_id) if target_id else None
                if voter and target and voter.alignment == target.alignment and voter.alignment.value == "wolf":
                    reports.append(
                        BadCaseReport(
                            game_id=state.id,
                            day=event.day,
                            player_name=voter.name,
                            role=voter.role.value,
                            mistake_type="vote",
                            description=f"{voter.name} voted for wolf teammate {target.name}",
                            suggested_fix="Coordinate votes among wolves to avoid cross-voting",
                            severity="major",
                        )
                    )
        return reports


class InMemoryLeaderboard:
    """Simple in-memory leaderboard for comparing agents across games."""

    def __init__(self) -> None:
        self.entries: dict[str, list[LeaderboardEntry]] = {}

    def add_game(self, metrics: GameMetrics) -> None:
        for rm in metrics.role_metrics:
            key = f"{rm.role}"
            entry = LeaderboardEntry(
                agent_id=metrics.game_id[:8],
                role=rm.role,
                games_played=1,
                wins=1 if metrics.winner == ("wolf" if rm.role == "Werewolf" else "village") else 0,
                win_rate=0.0,
                avg_vote_precision=rm.vote_precision,
                avg_survival_rounds=rm.survival_rounds,
            )
            self.entries.setdefault(key, []).append(entry)

    def top_agents(self, role: str, limit: int = 10) -> list[LeaderboardEntry]:
        entries = self.entries.get(role, [])
        return sorted(entries, key=lambda e: e.win_rate, reverse=True)[:limit]

    def compare_versions(self, version_a: str, version_b: str) -> dict[str, Any]:
        return {
            "version_a": version_a,
            "version_b": version_b,
            "status": "not_implemented",
            "message": "Version comparison requires batch replay infrastructure",
        }
