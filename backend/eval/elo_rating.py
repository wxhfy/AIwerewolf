"""Elo Rating System — per-role, per-persona, per-version dynamic ranking.

Reference: Foaster.ai (2025) Werewolf Benchmark + ART (2025) tournament Elo.

Standard Elo with multi-agent K-factor adjustment:
  K_adj = K / (n_players - 1)  — ART (Khan, arXiv:2512.00617, 2025)
  expected = 1 / (1 + 10 ** ((opponent - player) / 400))
  new_rating = old_rating + K_adj * (actual - expected)
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Dict
from typing import List


@dataclass
class EloEntry:
    """One entry in an Elo rating table."""

    key: str  # e.g., "Seer", "INTJ-Werewolf", "strategy_v2"
    rating: float = 1200.0
    games_played: int = 0
    wins: int = 0
    losses: int = 0
    rating_history: List[float] = field(default_factory=list)


class EloRating:
    """Multi-dimensional Elo rating system.

    Supports independent Elo tracks:
    - Per role (Seer, Werewolf, Witch, ...)
    - Per persona-role pair (INTJ-Werewolf, ENFP-Seer, ...)
    - Per strategy version (v1, v2, ...)
    - Per model (dsv4flash, gpt5, ...)
    """

    def __init__(self, K: float = 32.0, initial_rating: float = 1200.0):
        self.K = K
        self.initial_rating = initial_rating
        self._tracks: Dict[str, Dict[str, EloEntry]] = {
            "role": {},
            "persona_role": {},
            "strategy_version": {},
            "model": {},
        }

    def get_or_create(self, track: str, key: str) -> EloEntry:
        """Get or create an Elo entry for (track, key)."""
        if key not in self._tracks[track]:
            self._tracks[track][key] = EloEntry(key=key, rating=self.initial_rating)
        return self._tracks[track][key]

    def expected_score(self, rating_a: float, rating_b: float) -> float:
        """Expected score for player A against player B."""
        return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))

    def update_single(self, track: str, key: str, actual_score: float, opponents: List[str]) -> EloEntry:
        """Update Elo for one player against a set of opponents.

        Args:
            track: Rating track ("role", "persona_role", "strategy_version", "model").
            key: Player's key in this track.
            actual_score: 0-1 normalized performance score (process_score / 100).
            opponents: List of opponent keys in the same track.

        Returns:
            Updated EloEntry.
        """
        entry = self.get_or_create(track, key)
        if not opponents:
            return entry

        n = len(opponents)
        K_adj = self.K / max(1, n)  # ART multi-agent K-factor adjustment

        total_delta = 0.0
        for opp_key in opponents:
            opp = self.get_or_create(track, opp_key)
            expected = self.expected_score(entry.rating, opp.rating)
            total_delta += K_adj * (actual_score - expected)

        entry.rating = round(entry.rating + total_delta, 2)
        entry.games_played += 1
        if actual_score >= 0.5:
            entry.wins += 1
        else:
            entry.losses += 1
        entry.rating_history.append(entry.rating)

        return entry

    def update_game(self, player_scores: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, EloEntry]]:
        """Update all Elo tracks after one game.

        Args:
            player_scores: Dict of player_id -> {
                "role": str, "process_score": float, "persona_id": str,
                "persona_mbti": str, "strategy_version": str, "model": str,
            }

        Returns:
            Updated tracks dict.
        """
        players = list(player_scores.items())
        n = len(players)

        for pid, info in players:
            role = info.get("role", "unknown")
            persona_mbti = info.get("persona_mbti", "")
            persona_role = f"{persona_mbti}-{role}" if persona_mbti else role
            strategy_ver = info.get("strategy_version", "v1")
            model = info.get("model", "unknown")
            process_score = info.get("process_score", 50) / 100.0  # normalize

            # Per-role Elo
            opp_roles = [p[1].get("role", "unknown") for p in players if p[0] != pid]
            self.update_single("role", role, process_score, opp_roles)

            # Per-persona-role Elo
            opp_pr = [f"{p[1].get('persona_mbti', '')}-{p[1].get('role', 'unknown')}" for p in players if p[0] != pid]
            self.update_single("persona_role", persona_role, process_score, opp_pr)

            # Per-strategy-version Elo
            opp_sv = [p[1].get("strategy_version", "v1") for p in players if p[0] != pid]
            self.update_single("strategy_version", strategy_ver, process_score, opp_sv)

            # Per-model Elo
            opp_models = [p[1].get("model", "unknown") for p in players if p[0] != pid]
            self.update_single("model", model, process_score, opp_models)

        return self._tracks

    def get_leaderboard(self, track: str, sort_by: str = "rating") -> List[Dict[str, Any]]:
        """Get sorted leaderboard for a track."""
        entries = sorted(
            self._tracks[track].values(),
            key=lambda e: getattr(e, sort_by),
            reverse=True,
        )
        return [
            {
                "key": e.key,
                "rating": e.rating,
                "games": e.games_played,
                "wins": e.wins,
                "losses": e.losses,
                "win_rate": round(e.wins / max(1, e.games_played), 3),
            }
            for e in entries
            if e.games_played > 0
        ]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize all tracks to dict."""
        result = {}
        for track_name, entries in self._tracks.items():
            result[track_name] = {
                key: {
                    "rating": e.rating,
                    "games_played": e.games_played,
                    "wins": e.wins,
                    "losses": e.losses,
                    "rating_history": e.rating_history,
                }
                for key, e in entries.items()
                if e.games_played > 0
            }
        return result
