"""Memory system for the cognitive agent.

Provides structured memory that persists across rounds, tracking:
- What the agent has observed
- What judgments it has made
- What actions it has taken and their outcomes
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Judgment:
    """A judgment about a player or situation."""
    target: str  # player name or situation description
    judgment: str  # "suspicious", "trustworthy", "wolf", "good", etc.
    confidence: float  # 0-1
    reasoning: str
    day: int
    phase: str


@dataclass
class ActionRecord:
    """Record of an action taken by this agent."""
    action_type: str  # "speech", "vote", "night_action", etc.
    target: str | None
    content: str  # what was said or done
    reasoning: str
    day: int
    phase: str


@dataclass
class RoundSummary:
    """Summary of what happened in a round."""
    day: int
    phase: str
    key_events: list[str]
    my_judgments: list[Judgment]
    my_actions: list[ActionRecord]


class AgentMemory:
    """Structured memory for a cognitive agent.

    Unlike raw event logs, this memory is curated — the agent decides what
    to remember and what to forget. It tracks judgments, actions, and their
    outcomes to enable consistent reasoning across rounds.
    """

    def __init__(self, player_id: str, player_role: str):
        self.player_id = player_id
        self.player_role = player_role

        # Core memory
        self.judgments: list[Judgment] = []
        self.actions: list[ActionRecord] = []
        self.round_summaries: list[RoundSummary] = []

        # Role-specific memory
        self.role_memory: dict[str, Any] = {}
        # For seer: check history
        # For witch: potion usage
        # For guard: protection history
        # For wolf: kill targets, partner info

        # Current round context
        self.current_day: int = 0
        self.current_phase: str = ""

    def update_round(self, day: int, phase: str) -> None:
        """Update the current round context."""
        self.current_day = day
        self.current_phase = phase

    def add_judgment(
        self,
        target: str,
        judgment: str,
        confidence: float,
        reasoning: str,
    ) -> None:
        """Record a judgment about a player or situation."""
        self.judgments.append(Judgment(
            target=target,
            judgment=judgment,
            confidence=confidence,
            reasoning=reasoning,
            day=self.current_day,
            phase=self.current_phase,
        ))

    def add_action(
        self,
        action_type: str,
        target: str | None,
        content: str,
        reasoning: str,
    ) -> None:
        """Record an action taken."""
        self.actions.append(ActionRecord(
            action_type=action_type,
            target=target,
            content=content,
            reasoning=reasoning,
            day=self.current_day,
            phase=self.current_phase,
        ))

    def add_round_summary(self, key_events: list[str]) -> None:
        """Add a summary of the current round."""
        round_judgments = [
            j for j in self.judgments
            if j.day == self.current_day and j.phase == self.current_phase
        ]
        round_actions = [
            a for a in self.actions
            if a.day == self.current_day and a.phase == self.current_phase
        ]
        self.round_summaries.append(RoundSummary(
            day=self.current_day,
            phase=self.current_phase,
            key_events=key_events,
            my_judgments=round_judgments,
            my_actions=round_actions,
        ))

    def get_player_judgment(self, player_name: str) -> Judgment | None:
        """Get the most recent judgment about a player."""
        for j in reversed(self.judgments):
            if j.target == player_name:
                return j
        return None

    def get_my_recent_actions(self, n: int = 5) -> list[ActionRecord]:
        """Get my most recent actions."""
        return self.actions[-n:]

    def get_role_memory_text(self) -> str:
        """Format role-specific memory as text."""
        if not self.role_memory:
            return ""

        lines = ["=== 角色专属记忆 ==="]
        for key, val in self.role_memory.items():
            if isinstance(val, list):
                lines.append(f"  {key}:")
                for item in val[-5:]:  # last 5
                    lines.append(f"    - {item}")
            else:
                lines.append(f"  {key}: {val}")
        return "\n".join(lines)

    def get_judgment_text(self) -> str:
        """Format current judgments as text."""
        if not self.judgments:
            return ""

        # Get latest judgment per player
        latest: dict[str, Judgment] = {}
        for j in self.judgments:
            if j.target not in latest or j.day > latest[j.target].day:
                latest[j.target] = j

        lines = ["=== 我的判断记录 ==="]
        for target, j in latest.items():
            conf = f"{j.confidence:.0%}"
            lines.append(f"  {target}: {j.judgment}（置信度{conf}）- {j.reasoning}")
        return "\n".join(lines)

    def get_action_history_text(self) -> str:
        """Format recent action history as text."""
        recent = self.get_my_recent_actions(8)
        if not recent:
            return ""

        lines = ["=== 我最近的行动 ==="]
        for a in recent:
            lines.append(f"  D{a.day} [{a.phase}] {a.action_type}: {a.content[:100]}")
        return "\n".join(lines)

    def format_for_prompt(self) -> str:
        """Format all memory into a prompt-ready text."""
        parts = []
        role_mem = self.get_role_memory_text()
        if role_mem:
            parts.append(role_mem)
        judgment_text = self.get_judgment_text()
        if judgment_text:
            parts.append(judgment_text)
        action_text = self.get_action_history_text()
        if action_text:
            parts.append(action_text)
        return "\n\n".join(parts) if parts else ""
