"""Strategic Intent Planner — lightweight multi-turn planning for werewolf agents.

Design principles:
- Social deduction is reactive, not plan-driven. Full GOAP/behavior trees are overkill.
- StrategicIntent is a "bookmark" — the agent declares an intent, the system reminds it.
- The LLM still decides whether to follow through. Rigid plan-following would be worse.
- Intents auto-resolve when conditions expire or the target phase passes.

Pattern:  Declare → Remember → Remind → Execute (or adapt/abandon)
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import List
from typing import Optional


@dataclass
class StrategicIntent:
    """A declared multi-turn strategic intention.

    Set by the agent during reasoning (via set_strategic_intent tool or
    DECISION metadata), consumed by prompt injection on subsequent turns.

    Example:
        StrategicIntent(
            objective="bluff_claim_seer",
            target_phase="DAY_SPEECH",
            conditions=["no other seer claim exists"],
            fallback="continue_deep_cover",
        )
    """

    objective: str  # e.g. "bluff_claim_seer", "frame_player_3"
    target_phase: str  # When to execute (DAY_SPEECH, NIGHT_WOLF_ACTION, etc.)
    declared_day: int = 0
    declared_phase: str = ""
    conditions: List[str] = field(default_factory=list)  # What must hold true
    condition_check_results: List[str] = field(default_factory=list)
    fallback: str = ""  # What to do if conditions fail
    resolved: bool = False
    resolution_note: str = ""  # "executed", "conditions_failed", "phase_passed", "abandoned"

    def is_active(self, current_day: int, current_phase: str) -> bool:
        """Check if this intent should be active in the current context."""
        if self.resolved:
            return False
        if current_day < self.declared_day:
            return False
        phase_match = self.target_phase in current_phase or current_phase in self.target_phase
        return phase_match

    def format_for_prompt(self) -> str:
        """Format intent for prompt injection."""
        lines = [
            f"目标: {self.objective}",
            f"设定于: D{self.declared_day} {self.declared_phase}",
            f"触发阶段: {self.target_phase}",
        ]
        if self.conditions:
            lines.append(f"前置条件: {', '.join(self.conditions)}")
        if self.fallback:
            lines.append(f"失败回退: {self.fallback}")
        if self.condition_check_results:
            lines.append(f"条件检查: {', '.join(self.condition_check_results)}")
        return "\n".join(lines)


class Planner:
    """Lightweight strategic planner for werewolf agents.

    Manages StrategicIntent lifecycle:
    - Declare: agent sets an intent during reasoning
    - Check: verify conditions when target phase arrives
    - Remind: inject active intents into prompts
    - Resolve: mark as done/abandoned

    Only one active intent at a time — keeps it simple and focused.
    """

    def __init__(self):
        self.intents: List[StrategicIntent] = []
        self._max_history = 5  # Keep only recent resolved intents

    def set_intent(
        self,
        objective: str,
        target_phase: str,
        day: int = 0,
        phase: str = "",
        conditions: Optional[List[str]] = None,
        fallback: str = "",
    ) -> StrategicIntent:
        """Declare a new strategic intent. Auto-resolves any previous active intent."""
        self._resolve_all_active("superseded by new intent", day, phase)

        intent = StrategicIntent(
            objective=objective,
            target_phase=target_phase,
            declared_day=day,
            declared_phase=phase,
            conditions=conditions or [],
            fallback=fallback,
        )
        self.intents.append(intent)
        return intent

    def get_active(self, current_day: int, current_phase: str) -> Optional[StrategicIntent]:
        """Get the currently active intent, if any."""
        for intent in self.intents:
            if intent.is_active(current_day, current_phase):
                return intent
        return None

    def check_and_resolve(
        self,
        current_day: int,
        current_phase: str,
        conditions_met: bool,
    ) -> Optional[StrategicIntent]:
        """Check active intent conditions and resolve if appropriate.

        Called at the start of each decision. If conditions are met, the intent
        stays active (LLM should follow through). If conditions failed, the intent
        is abandoned and the fallback is returned.
        """
        active = self.get_active(current_day, current_phase)
        if active is None:
            return None

        if conditions_met:
            return active  # Intent is valid, go ahead
        else:
            active.resolved = True
            active.resolution_note = "conditions_failed"
            return None  # Intent abandoned

    def mark_executed(self, current_day: int, current_phase: str):
        """Mark the active intent as successfully executed."""
        active = self.get_active(current_day, current_phase)
        if active:
            active.resolved = True
            active.resolution_note = "executed"
        self._trim_history()

    def mark_abandoned(self, reason: str, day: int, phase: str):
        """Abandon the active intent."""
        self._resolve_all_active(reason, day, phase)
        self._trim_history()

    def format_active_for_prompt(self, current_day: int, current_phase: str) -> str:
        """Format active intent as prompt text for injection."""
        active = self.get_active(current_day, current_phase)
        if active is None:
            return ""

        lines = ["=== 当前策略意图 ==="]
        lines.append(active.format_for_prompt())
        lines.append("")
        lines.append("你有已记录的策略意图。如果条件满足，按计划执行。如果局势已变，可以调整或放弃。")
        return "\n".join(lines)

    def _resolve_all_active(self, reason: str, day: int, phase: str):
        """Resolve all unresolved intents."""
        for intent in self.intents:
            if not intent.resolved:
                intent.resolved = True
                intent.resolution_note = reason

    def _trim_history(self):
        """Keep only the most recent resolved intents."""
        resolved = [i for i in self.intents if i.resolved]
        active = [i for i in self.intents if not i.resolved]
        if len(resolved) > self._max_history:
            resolved = resolved[-self._max_history :]
        self.intents = active + resolved
