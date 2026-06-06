"""Villager strategy card — analysis, voting, identifying contradictions."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

from backend.agents.cognitive.strategies.base import RoleStrategyCard
from backend.agents.cognitive.strategies.base import register_strategy


@register_strategy("villager")
@dataclass
class VillagerStrategyCard(RoleStrategyCard):
    """Villager-specific strategy: listening, analysis, contradiction detection."""

    role: str = "Villager"

    claim_policy: str = "honest"
    info_release_policy: str = "timely"
    vote_leadership_threshold: float = 0.40
    vote_follow_threshold: float = 0.50
    risk_tolerance: float = 0.35
    information_seeking: float = 0.65

    # Villager-specific
    analysis_depth: str = "moderate"  # shallow | moderate | deep
    contradiction_sensitivity: float = 0.70  # How sensitive to contradictions
    follow_leadership: float = 0.50  # Tendency to follow trusted leaders
    independent_vote: float = 0.60  # Tendency to vote independently

    # Analysis focus
    analysis_priorities: list[str] = field(
        default_factory=lambda: [
            "claim_contradictions",  # Multiple claims of same role
            "vote_patterns",  # Who votes with whom
            "speech_consistency",  # Stance changes across days
            "information_hiding",  # Who avoids sharing info
        ]
    )

    def format_for_prompt(self) -> str:
        base = super().format_for_prompt()
        villager_lines = [
            "",
            "村民专项策略:",
            f"  分析深度: {self._analysis_desc()}",
            f"  矛盾敏感度: {self.contradiction_sensitivity:.0%}",
            f"  跟票倾向: {self.follow_leadership:.0%}",
            f"  独立投票: {self.independent_vote:.0%}",
            f"  分析重点: {' → '.join(self.analysis_priorities)}",
            "",
            "注意事项:",
            "  - 村民没有特殊技能，靠发言和投票帮助好人阵营",
            "  - 重点识别矛盾：多人跳同一神职、立场摇摆、信息隐藏",
            "  - 勇敢归票但不盲从",
        ]
        return base + "\n".join(villager_lines)

    def _analysis_desc(self) -> str:
        mapping = {
            "shallow": "浅层（关注明显矛盾）",
            "moderate": "中等（分析发言+投票）",
            "deep": "深度（综合分析+策略推演）",
        }
        return mapping.get(self.analysis_depth, self.analysis_depth)
