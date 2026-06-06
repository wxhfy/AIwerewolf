"""Witch strategy card — potion management, save/poison timing."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

from backend.agents.cognitive.strategies.base import RoleStrategyCard
from backend.agents.cognitive.strategies.base import register_strategy


@register_strategy("witch")
@dataclass
class WitchStrategyCard(RoleStrategyCard):
    """Witch-specific strategy: potion conservation, identity concealment."""

    role: str = "Witch"

    claim_policy: str = "cautious"
    info_release_policy: str = "withhold"
    vote_leadership_threshold: float = 0.50
    vote_follow_threshold: float = 0.40
    risk_tolerance: float = 0.35
    information_seeking: float = 0.55

    # Potion strategy
    save_first_night: bool = True  # Use antidote on night 0
    save_threshold: float = 0.60  # Only save if target has >60% survival value
    poison_priority: list[str] = field(
        default_factory=lambda: [
            "likely_wolf",
            "contradiction_detected",
            "vote_leader_wolf",
            "silent_suspicious",
        ]
    )

    # Identity protection
    reveal_when_potions_used: bool = True  # Reveal after both potions used
    reveal_when_counter_claimed: bool = True
    poison_early: str = "conservative"  # conservative | aggressive

    def format_for_prompt(self) -> str:
        base = super().format_for_prompt()
        witch_lines = [
            "",
            "女巫专项策略:",
            f"  首夜救人: {'是' if self.save_first_night else '否'}",
            f"  救人阈值: 目标存活价值>{self.save_threshold:.0%}时救",
            f"  毒人优先级: {' → '.join(self.poison_priority)}",
            f"  身份暴露: {'两药用完后跳' if self.reveal_when_potions_used else '不主动暴露'}",
            f"  毒药用时: {'保守（确定狼人）' if self.poison_early == 'conservative' else '激进（疑似即可）'}",
            "",
            "注意事项:",
            "  - 解药和毒药各只能用一次",
            "  - 同一晚不能同时使用解药和毒药",
            "  - 首夜可以自救，之后不能自救",
        ]
        return base + "\n".join(witch_lines)
