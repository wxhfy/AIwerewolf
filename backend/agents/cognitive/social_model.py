"""Social Model — trust network and deception detection for multi-agent play."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Dict
from typing import List


@dataclass
class TrustEdge:
    """Trust relationship between two players."""

    source: str  # who has this trust
    target: str  # who is trusted/distrusted
    score: float  # -1.0 (distrust) to 1.0 (trust)
    evidence: List[str] = field(default_factory=list)
    day: int = 0


@dataclass
class DeceptionSignal:
    """A signal that a player may be deceiving."""

    player_id: str
    signal_type: str  # "speech_vote_mismatch", "role_claim_change", "contradiction"
    description: str
    severity: float  # 0-1
    day: int = 0


class SocialModel:
    """Tracks trust relationships and deception signals across players."""

    def __init__(self):
        self.trust_edges: Dict[str, Dict[str, TrustEdge]] = {}
        self.deception_signals: List[DeceptionSignal] = []

    def update_trust(self, source: str, target: str, delta: float, evidence: str = "", day: int = 0):
        """Update trust score from source toward target."""
        if source not in self.trust_edges:
            self.trust_edges[source] = {}
        if target not in self.trust_edges[source]:
            self.trust_edges[source][target] = TrustEdge(source=source, target=target, score=0.0)

        edge = self.trust_edges[source][target]
        edge.score = max(-1.0, min(1.0, edge.score + delta))
        if evidence:
            edge.evidence.append(evidence)
        edge.day = day

    def get_trust(self, source: str, target: str) -> float:
        """Get trust score from source toward target. 0 if no edge."""
        return self.trust_edges.get(source, {}).get(target, TrustEdge(source=source, target=target, score=0.0)).score

    def get_trusted_players(self, source: str, threshold: float = 0.3) -> List[str]:
        """Get players trusted above threshold by source."""
        edges = self.trust_edges.get(source, {})
        return [t for t, e in edges.items() if e.score >= threshold]

    def get_distrusted_players(self, source: str, threshold: float = -0.3) -> List[str]:
        """Get players distrusted below threshold by source."""
        edges = self.trust_edges.get(source, {})
        return [t for t, e in edges.items() if e.score <= threshold]

    def add_deception_signal(self, signal: DeceptionSignal):
        """Record a deception signal."""
        self.deception_signals.append(signal)

    def get_deception_score(self, player_id: str) -> float:
        """Get aggregated deception score for a player. 0 = no signals, 1 = many strong signals."""
        signals = [s for s in self.deception_signals if s.player_id == player_id]
        if not signals:
            return 0.0
        return min(1.0, sum(s.severity for s in signals) / len(signals))

    def detect_speech_vote_mismatch(self, player_id: str, speech_target: str, vote_target: str, day: int = 0):
        """Detect if player said one thing but voted differently."""
        if speech_target and vote_target and speech_target != vote_target:
            self.add_deception_signal(
                DeceptionSignal(
                    player_id=player_id,
                    signal_type="speech_vote_mismatch",
                    description=f"发言指向{speech_target}但投票给了{vote_target}",
                    severity=0.4,
                    day=day,
                )
            )

    def format_for_prompt(self, player_id: str) -> str:
        """Format social model info for a player's prompt."""
        lines = []
        trusted = self.get_trusted_players(player_id)
        distrusted = self.get_distrusted_players(player_id)
        if trusted:
            lines.append(f"你信任的玩家: {', '.join(trusted)}")
        if distrusted:
            lines.append(f"你怀疑的玩家: {', '.join(distrusted)}")

        signals = [s for s in self.deception_signals if s.severity >= 0.3]
        if signals:
            lines.append("欺骗信号:")
            for s in signals[-3:]:  # last 3
                lines.append(f"  - {s.player_id}: {s.description} (严重度:{s.severity:.0%})")

        return "\n".join(lines) if lines else ""
