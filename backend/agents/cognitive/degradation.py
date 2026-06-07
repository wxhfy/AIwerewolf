"""Heuristic degradation — role-based fallback decisions when LLM fails.

Matches PRD §3.3 degradation strategy:
- Strict mode: raise error (existing behavior)
- Non-strict mode: use heuristic rules per role

Each heuristic uses only public information available to the agent
(via PlayerView), maintaining information isolation.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from backend.engine.models import Alignment


@dataclass
class DegradationHeuristic:
    """Role-based heuristic fallback for LLM failures.

    Uses simple rule-based logic that matches PRD §3.3 degradation table.
    All heuristics respect information isolation — they only use data
    available in the agent's PlayerView, NOT the full GameState.
    """

    role: str
    alignment: str  # "village" or "wolf"

    def talk(self, player_view: dict | None = None) -> dict[str, Any]:
        """Generate a minimal heuristic speech.

        Returns a basic pass/observe speech that doesn't reveal information
        the agent shouldn't have.
        """
        speeches = {
            "villager": "我暂时没有特别的信息，先听听大家的发言。",
            "werewolf": "我跟前面的发言差不多，继续观察吧。",
            "seer": "今天信息还不太够，大家一起分析。",
            "witch": "先听听看，有需要我会表态。",
            "hunter": "我就一个普通村民，没什么特别的。",
            "guard": "先观察一轮，看看情况。",
        }
        return {
            "speech": speeches.get(self.role.lower(), "先听听大家的发言。"),
            "reasoning": f"[降级] LLM调用失败，{self.role}使用启发式发言。",
        }

    def vote(self, player_view: dict | None = None) -> dict[str, Any]:
        """Heuristic vote: villagers abstain, wolves follow majority.

        Falls back to abstaining when no clear target is available.
        """
        # Try to extract legal targets from player view
        legal_targets: list[str] = []
        if player_view:
            legal_targets = player_view.get("legal_targets", []) or []
            # If player_view has alive players list, use non-self targets
            alive = player_view.get("alive_players", []) or []
            if alive and not legal_targets:
                my_id = player_view.get("player_id", "")
                legal_targets = [
                    p.get("player_id", p.get("id", ""))
                    for p in alive
                    if p.get("player_id", p.get("id", "")) != my_id
                ]

        if not legal_targets:
            return {"vote_target": None, "reasoning": "[降级] 无合法目标，弃权。"}

        # Simple vote heuristic
        if self.alignment == "wolf":
            # Wolf: vote a random non-wolf (heuristic, no teammate info needed)
            target = random.choice(legal_targets)
            reason = "跟票观察。"
        else:
            # Villager: abstain (safest when uncertain)
            return {"vote_target": None, "reasoning": "[降级] 村民弃权，避免错误投票。"}

        return {"vote_target": target, "reasoning": f"[降级] {reason}"}

    def attack(self, player_view: dict | None = None) -> dict[str, Any]:
        """Heuristic wolf kill: target a random non-wolf legal target."""
        legal_targets: list[str] = []
        if player_view:
            legal_targets = player_view.get("legal_targets", []) or []
        if not legal_targets:
            return {"kill_target": None, "reasoning": "[降级] 无合法击杀目标。"}
        target = random.choice(legal_targets)
        return {
            "kill_target": target,
            "reasoning": f"[降级] 狼人启发式击杀，随机选择目标。",
        }

    def divine(self, player_view: dict | None = None) -> dict[str, Any]:
        """Heuristic seer check: check a random unchecked player."""
        legal_targets: list[str] = []
        if player_view:
            legal_targets = player_view.get("legal_targets", []) or []
        if not legal_targets:
            return {"check_target": None, "reasoning": "[降级] 无可查验目标。"}
        target = random.choice(legal_targets)
        return {
            "check_target": target,
            "reasoning": "[降级] 预言家启发式查验。",
        }

    def guard(self, player_view: dict | None = None) -> dict[str, Any]:
        """Heuristic guard: guard self if allowed, otherwise random."""
        legal_targets: list[str] = []
        if player_view:
            legal_targets = player_view.get("legal_targets", []) or []
        if not legal_targets:
            return {"guard_target": None, "reasoning": "[降级] 无合法守护目标。"}
        my_id = player_view.get("player_id", "") if player_view else ""
        # Guard self if legal (first night standard tactic)
        if my_id and my_id in legal_targets:
            return {
                "guard_target": my_id,
                "reasoning": "[降级] 守卫自守。",
            }
        target = random.choice(legal_targets)
        return {
            "guard_target": target,
            "reasoning": "[降级] 守卫启发式守护。",
        }

    def witch_act(self, player_view: dict | None = None) -> dict[str, Any]:
        """Heuristic witch: save on first night, poison never."""
        # Conservative fallback: never poison, save if first night
        return {
            "use_antidote": False,
            "use_poison": False,
            "poison_target": None,
            "reasoning": "[降级] 女巫保守策略，不盲目用药。",
        }


def get_degradation_heuristic(role: str, alignment: str = "village") -> DegradationHeuristic:
    """Factory for role-based degradation heuristics."""
    return DegradationHeuristic(role=role, alignment=alignment)
