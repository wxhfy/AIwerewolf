"""Guard strategy card — protection timing and target selection."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

from backend.agents.cognitive.strategies.base import RoleStrategyCard
from backend.agents.cognitive.strategies.base import register_strategy


@register_strategy("guard")
@dataclass
class GuardStrategyCard(RoleStrategyCard):
    """Guard-specific strategy: protection target selection, self-protection timing."""

    role: str = "Guard"

    claim_policy: str = "cautious"
    info_release_policy: str = "withhold"
    vote_leadership_threshold: float = 0.50
    vote_follow_threshold: float = 0.40
    risk_tolerance: float = 0.30
    information_seeking: float = 0.45

    # Guard strategy
    protect_priority: list[str] = field(
        default_factory=lambda: [
            "claimed_seer",
            "suspected_witch",
            "leadership_player",
            "self",  # self-protection when exposed
        ]
    )

    protect_seer_night_0: bool = True  # Guard Seer on first night
    self_protect_threshold: float = 0.70  # Self-guard when >70% at risk
    consecutive_forbidden: bool = True  # Cannot guard same target consecutively

    # Identity protection
    reveal_when_guarded_seer: bool = False  # Don't reveal even if guarded Seer
    reveal_when_counter_claimed: bool = True

    def format_for_prompt(self) -> str:
        base = super().format_for_prompt()
        guard_lines = [
            "",
            "守卫专项策略:",
            f"  首夜守护: {'预言家' if self.protect_seer_night_0 else '灵活选择'}",
            f"  守护优先级: {' → '.join(self.protect_priority)}",
            f"  自守阈值: 面临>{self.self_protect_threshold:.0%}风险时自守",
            f"  连续守护: {'禁止' if self.consecutive_forbidden else '允许'}",
            f"  身份暴露: {'被对跳时跳' if self.reveal_when_counter_claimed else '隐藏到底'}",
            "",
            "注意事项:",
            "  - 不能连续两晚守护同一人",
            "  - 可以自守但不能连续自守",
            "  - 同守同救（守卫+女巫同时保护）会导致死亡",
        ]
        return base + "\n".join(guard_lines)
