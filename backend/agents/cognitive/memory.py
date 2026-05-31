"""Agent memory — persists judgments and actions across rounds.

Single Responsibility: maintain the agent's working memory.
No LLM calls, no game logic — pure data management.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Judgment:
    """A judgment about a player."""
    target: str
    label: str       # "suspicious", "trustworthy", "wolf", "good"
    confidence: float  # 0-1
    reasoning: str
    day: int


@dataclass
class ActionRecord:
    """Record of an action taken."""
    action_type: str
    target: Optional[str]
    content: str
    reasoning: str
    day: int
    phase: str


class Memory:
    """Agent's working memory.

    Stores:
    - Judgments about players (updated each round)
    - Action history (what the agent did)
    - Role-specific state (seer checks, guard history, etc.)
    """

    def __init__(self, player_id: str, role: str):
        self.player_id = player_id
        self.role = role

        # Core memory
        self.judgments: List[Judgment] = []
        self.actions: List[ActionRecord] = []

        # Role-specific state
        self.role_state: Dict[str, Any] = {}

        # Current context
        self.day: int = 0
        self.phase: str = ""

    def update_round(self, day: int, phase: str) -> None:
        self.day = day
        self.phase = phase

    def add_judgment(self, target: str, label: str, confidence: float, reasoning: str) -> None:
        self.judgments.append(Judgment(
            target=target, label=label,
            confidence=confidence, reasoning=reasoning,
            day=self.day,
        ))

    def add_action(self, action_type: str, target: Optional[str], content: str, reasoning: str) -> None:
        self.actions.append(ActionRecord(
            action_type=action_type, target=target,
            content=content, reasoning=reasoning,
            day=self.day, phase=self.phase,
        ))

    def get_latest_judgment(self, player_name: str) -> Optional[Judgment]:
        for j in reversed(self.judgments):
            if j.target == player_name:
                return j
        return None

    def get_recent_actions(self, n: int = 5) -> List[ActionRecord]:
        return self.actions[-n:]

    def format_for_prompt(self) -> str:
        """Format memory into text for LLM consumption."""
        parts = []

        # Latest judgments per player
        latest: Dict[str, Judgment] = {}
        for j in self.judgments:
            if j.target not in latest or j.day > latest[j.target].day:
                latest[j.target] = j

        if latest:
            lines = ["=== 我的判断 ==="]
            for target, j in latest.items():
                lines.append(f"  {target}: {j.label}({j.confidence:.0%}) - {j.reasoning[:80]}")
            parts.append("\n".join(lines))

        # Role-specific state
        if self.role_state:
            lines = ["=== 角色状态 ==="]
            for k, v in self.role_state.items():
                if isinstance(v, list):
                    lines.append(f"  {k}: {', '.join(str(x) for x in v[-5:])}")
                else:
                    lines.append(f"  {k}: {v}")
            parts.append("\n".join(lines))

        # Recent actions
        recent = self.get_recent_actions(5)
        if recent:
            lines = ["=== 最近行动 ==="]
            for a in recent:
                lines.append(f"  D{a.day} [{a.phase}] {a.action_type}: {a.content[:60]}")
            parts.append("\n".join(lines))

        return "\n\n".join(parts)
