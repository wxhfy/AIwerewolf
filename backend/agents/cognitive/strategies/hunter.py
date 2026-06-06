"""Hunter strategy card — shoot timing and target selection."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

from backend.agents.cognitive.strategies.base import RoleStrategyCard
from backend.agents.cognitive.strategies.base import register_strategy


@register_strategy("hunter")
@dataclass
class HunterStrategyCard(RoleStrategyCard):
    """Hunter-specific strategy: shoot timing, target selection."""

    role: str = "Hunter"

    claim_policy: str = "honest"
    info_release_policy: str = "timely"
    vote_leadership_threshold: float = 0.65
    vote_follow_threshold: float = 0.30
    risk_tolerance: float = 0.70
    information_seeking: float = 0.40

    # Shoot strategy
    shoot_when_obvious_wolf: bool = True  # Shoot if target is clearly wolf
    shoot_when_framed: bool = False  # Don't shoot if being framed
    hold_when_uncertain: bool = True  # Hold shot if unsure (<60% confidence)
    shoot_confidence_threshold: float = 0.60

    # Target priority
    shoot_priority: list[str] = field(
        default_factory=lambda: [
            "confirmed_wolf",
            "contradiction_detected",
            "vote_misled_good",
            "wolf_claim_contradicted",
        ]
    )

    # Identity
    reveal_early: bool = False  # Don't reveal unless necessary
    reveal_on_death: bool = True

    def format_for_prompt(self) -> str:
        base = super().format_for_prompt()
        hunter_lines = [
            "",
            "猎人专项策略:",
            f"  开枪时机: 目标置信>{self.shoot_confidence_threshold:.0%}时开枪",
            f"  明显狼人: {'必开' if self.shoot_when_obvious_wolf else '谨慎'}",
            f"  被抗推时: {'不开枪（避免被狼队利用）' if not self.shoot_when_framed else '可以开'}",
            f"  不确定时: {'不开枪' if self.hold_when_uncertain else '可以开'}",
            f"  开枪优先级: {' → '.join(self.shoot_priority)}",
            f"  身份暴露: {'死亡时展示' if self.reveal_on_death else '隐藏'}",
            "",
            "注意事项:",
            "  - 被毒杀不能开枪",
            "  - 被白狼王炸死不能开枪",
            "  - 开枪后会展示猎人身份",
        ]
        return base + "\n".join(hunter_lines)
