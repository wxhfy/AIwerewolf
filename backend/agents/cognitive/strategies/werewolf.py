"""Werewolf strategy card — infiltration, bluffing, coordination."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

from backend.agents.cognitive.strategies.base import RoleStrategyCard
from backend.agents.cognitive.strategies.base import register_strategy


@register_strategy("werewolf")
@dataclass
class WerewolfStrategyCard(RoleStrategyCard):
    """Werewolf-specific strategy: infiltration, bluff, kill coordination."""

    role: str = "Werewolf"

    # Rule-based strategies
    claim_policy: str = "cautious"
    info_release_policy: str = "withhold"
    vote_leadership_threshold: float = 0.45
    vote_follow_threshold: float = 0.30
    risk_tolerance: float = 0.55
    information_seeking: float = 0.60

    # === Wolf-specific ===
    bluff_timing_preference: str = "mid"  # Jump claim in mid-game
    sacrifice_threshold: float = 0.70  # Bus teammate if they're >70% exposed

    # Kill strategy
    kill_priority: list[str] = field(
        default_factory=lambda: [
            "claimed_seer",
            "confirmed_good",
            "leadership_player",
            "silent_analyst",
        ]
    )

    # Coordination tactics
    primary_tactic: str = "deep_cover"  # deep_cover | lead_bluffer | vote_pusher
    narrative_consistency: float = 0.80  # How strictly to follow team narrative
    fake_claim_role: str = "Villager"  # Default fake claim

    def format_for_prompt(self) -> str:
        base = super().format_for_prompt()
        wolf_lines = [
            "",
            "狼人专项策略:",
            f"  主要战术: {self._tactic_desc()}",
            f"  刀人优先级: {' → '.join(self.kill_priority)}",
            f"  悍跳时机: {self.bluff_timing_preference}",
            f"  卖队友阈值: {self.sacrifice_threshold:.0%}",
            f"  口径一致性: {self.narrative_consistency:.0%}",
            f"  默认伪装身份: {self.fake_claim_role}",
            "",
            "注意事项:",
            "  - 不能查看其他玩家的真实身份",
            "  - 刀人判断只能基于公开发言、投票和信念推断",
            "  - 与队友保持战术协调但避免发言完全一致",
        ]
        return base + "\n".join(wolf_lines)

    def _tactic_desc(self) -> str:
        mapping = {
            "deep_cover": "深水倒钩（融入好人阵营，低调隐藏）",
            "lead_bluffer": "悍跳狼（主动跳神职，控场引导）",
            "vote_pusher": "冲票狼（组织投票，制造抗推）",
            "silent": "潜水狼（少说话，避免被注意）",
        }
        return mapping.get(self.primary_tactic, self.primary_tactic)
