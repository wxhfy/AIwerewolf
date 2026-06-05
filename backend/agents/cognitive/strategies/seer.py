"""Seer strategy card — rule-based + parameter-based strategies."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

from backend.agents.cognitive.strategies.base import RoleStrategyCard
from backend.agents.cognitive.strategies.base import register_strategy


@register_strategy("seer")
@dataclass
class SeerStrategyCard(RoleStrategyCard):
    """Seer-specific strategy: check priority, reveal timing, survival tactics."""

    role: str = "Seer"

    # Rule-based strategies
    claim_policy: str = "cautious"
    info_release_policy: str = "timely"
    vote_leadership_threshold: float = 0.55
    vote_follow_threshold: float = 0.35
    risk_tolerance: float = 0.40
    information_seeking: float = 0.80

    # === Seer-specific rule-based ===

    # When to reveal check results
    reveal_when_checked_wolf: bool = True  # Always reveal wolf checks
    reveal_when_counter_claimed: bool = True  # Reveal if someone else claims Seer
    reveal_when_self_at_risk_threshold: float = 0.65  # Reveal if likely to be voted

    # Check priority (ordered list of player types to check)
    check_priority: list[str] = field(
        default_factory=lambda: [
            "suspicious_speaker",
            "silent_player",
            "leadership_candidate",
            "confirmed_good",  # verify trust
        ]
    )

    # Information management
    keep_badge_flow_private_until_day: int = 2  # Don't reveal badge info early
    reveal_flow_on_death: bool = True  # Share all results in last words

    def format_for_prompt(self) -> str:
        base = super().format_for_prompt()
        seer_lines = [
            "",
            "预言家专项策略:",
            f"  查验到狼人: {'立即跳' if self.reveal_when_checked_wolf else '观察后跳'}",
            f"  被对跳时: {'立即亮身份' if self.reveal_when_counter_claimed else '谨慎应对'}",
            f"  面临出局风险>{self.reveal_when_self_at_risk_threshold:.0%}时: 跳身份",
            f"  查验优先级: {' → '.join(self.check_priority)}",
            f"  警徽流保密至第{self.keep_badge_flow_private_until_day}天",
            f"  遗言: {'分享所有查验结果' if self.reveal_flow_on_death else '保守'}",
        ]
        return base + "\n".join(seer_lines)
