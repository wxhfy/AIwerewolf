"""Agent memory — persists judgments and actions across rounds.

Integrates:
- Judgments about players (updated each round)
- Action history (what the agent did)
- Role-specific state (seer checks, guard history, etc.)
- Humanization profile (behavioral parameters from personality)
- Playbook notes (role-specific action strategies)

Single Responsibility: maintain the agent's working memory.
No LLM calls, no game logic — pure data management.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from backend.agents.cognitive.humanization import HumanizationProfile
from backend.agents.cognitive.planner import Planner
from backend.agents.cognitive.social_model import SocialModel


@dataclass
class Judgment:
    """A judgment about a player."""

    target: str
    label: str  # "suspicious", "trustworthy", "wolf", "good"
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
    - Humanization profile (behavioral parameters)
    - Playbook notes (role-specific strategy hints)
    """

    def __init__(
        self,
        player_id: str,
        role: str,
        humanization: Optional[HumanizationProfile] = None,
    ):
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

        # Humanization (behavioral parameters from personality)
        self.humanization = humanization

        # Social model (trust network and deception detection)
        self.social_model = SocialModel()

        # Planner (strategic intent for multi-turn planning)
        self.planner = Planner()

        # Playbook notes (role-specific strategy hints)
        self.playbook_notes: Dict[str, List[str]] = {}

        # Stance continuity
        self.last_vote_target: Optional[str] = None
        self.recent_openings: List[str] = []  # Avoid repeating the same opening

    # ---- Round lifecycle ----

    def update_round(self, day: int, phase: str) -> None:
        self.day = day
        self.phase = phase

    # ---- Judgments ----

    def add_judgment(self, target: str, label: str, confidence: float, reasoning: str) -> None:
        self.judgments.append(
            Judgment(
                target=target,
                label=label,
                confidence=confidence,
                reasoning=reasoning,
                day=self.day,
            )
        )

    def get_latest_judgment(self, player_name: str) -> Optional[Judgment]:
        for j in reversed(self.judgments):
            if j.target == player_name:
                return j
        return None

    def get_suspects(self) -> List[Judgment]:
        """Get current suspects (suspicious/wolf labels)."""
        return [j for j in self.judgments if j.label in ("suspicious", "wolf")]

    def get_trusted(self) -> List[Judgment]:
        """Get current trusted players (trustworthy/good labels)."""
        return [j for j in self.judgments if j.label in ("trustworthy", "good")]

    # ---- Actions ----

    def add_action(self, action_type: str, target: Optional[str], content: str, reasoning: str) -> None:
        self.actions.append(
            ActionRecord(
                action_type=action_type,
                target=target,
                content=content,
                reasoning=reasoning,
                day=self.day,
                phase=self.phase,
            )
        )
        if action_type == "vote" and target:
            self.last_vote_target = target

    def get_recent_actions(self, n: int = 5) -> List[ActionRecord]:
        return self.actions[-n:]

    def remember_opening(self, segments: List[str]) -> None:
        """Remember speech openings to avoid repetition."""
        if segments:
            first = segments[0][:40]
            self.recent_openings.append(first)
            if len(self.recent_openings) > 5:
                self.recent_openings = self.recent_openings[-5:]

    # ---- Playbook ----

    def set_playbook(self, playbook: Dict[str, List[str]]) -> None:
        """Set role-specific action playbook.

        Args:
            playbook: Dict with keys like 'public_debate', 'vote_logic',
                      'night_logic', 'reveal_logic'.
        """
        self.playbook_notes = playbook

    def get_playbook_hints(self, category: str) -> List[str]:
        """Get strategy hints for a specific category."""
        return self.playbook_notes.get(category, [])

    # ---- Formatting ----

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

        # Stance continuity
        stance_parts = []
        suspects = self.get_suspects()
        trusted = self.get_trusted()
        if suspects:
            names = ", ".join(j.target for j in suspects[:3])
            stance_parts.append(f"你之前怀疑过: {names}")
        if trusted:
            names = ", ".join(j.target for j in trusted[:3])
            stance_parts.append(f"你之前信任过: {names}")
        if self.last_vote_target:
            stance_parts.append(f"你上次投票了: {self.last_vote_target}")
        if stance_parts:
            parts.append("=== 立场 ===")
            parts.append("\n".join(stance_parts))

        # Recent actions
        recent = self.get_recent_actions(5)
        if recent:
            lines = ["=== 最近行动 ==="]
            for a in recent:
                lines.append(f"  D{a.day} [{a.phase}] {a.action_type}: {a.content[:60]}")
            parts.append("\n".join(lines))

        # Strategic intent (multi-turn planning)
        plan_info = self.planner.format_active_for_prompt(self.day, self.phase)
        if plan_info:
            parts.append(plan_info)

        # Social model (trust network)
        social_info = self.social_model.format_for_prompt(self.player_id)
        if social_info:
            parts.append("=== 信任网络 ===")
            parts.append(social_info)

        # Playbook hints (compact)
        if self.playbook_notes:
            hints = self.playbook_notes.get("public_debate", [])[:2]
            if hints:
                parts.append("=== 行动策略 ===")
                for h in hints:
                    parts.append(f"  - {h}")

        return "\n\n".join(parts)

    def format_stance_block(self) -> str:
        """Build a stance continuity block for prompt injection."""
        suspects = self.get_suspects()
        trusted = self.get_trusted()

        lines = ["【你之前的立场 - 不要无理由推翻】"]
        if suspects:
            names = ", ".join(j.target for j in suspects[:3])
            lines.append(f"你曾怀疑: {names}")
        if trusted:
            names = ", ".join(j.target for j in trusted[:3])
            lines.append(f"你曾信任: {names}")
        if self.last_vote_target:
            lines.append(f"你上次投了: {self.last_vote_target}")
        lines.append("如果新事实推翻了旧判断，可以明确改变立场；否则请保持连贯。")

        return "\n".join(lines) if len(lines) > 2 else ""
