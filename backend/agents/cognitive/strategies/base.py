"""Base role strategy card and strategy memory.

Strategy cards are decision-layer configurations independent of MBTI/Persona.
They answer "what should I do" while profiles answer "how should I say it."
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field


@dataclass
class RoleStrategyCard:
    """Role strategy card: decision-layer configuration.

    Separated into rule-based (explicit, explainable, stable) and
    parameter-based (tunable, A/B testable) strategies.
    """

    role: str

    # === Rule-based strategies (explicit, explainable, stable) ===

    # Information strategy
    claim_policy: str = "honest"  # honest | cautious | aggressive
    info_release_policy: str = "timely"  # timely | withhold | selective

    # Vote strategy
    vote_leadership_threshold: float = 0.6
    vote_follow_threshold: float = 0.4
    split_vote_tolerance: float = 0.3

    # Skill strategy
    skill_conservation: float = 0.5  # 0=use freely, 1=hoard
    skill_target_priority: list[str] = field(default_factory=list)

    # Risk strategy
    risk_tolerance: float = 0.5  # 0=safe, 1=aggressive
    information_seeking: float = 0.5  # 0=passive, 1=actively probe

    # === Wolf-specific (None for village roles) ===
    bluff_timing_preference: str | None = None  # early | mid | late | reactive
    sacrifice_threshold: float | None = None  # when to bus a teammate

    def format_for_prompt(self) -> str:
        """Format strategy card as a prompt-injectable text block."""
        lines = [f"[{self.role} 策略卡]", ""]

        lines.append("信息策略:")
        lines.append(f"  身份声明: {self._claim_desc()}")
        lines.append(f"  信息释放: {self._info_release_desc()}")

        lines.append("投票策略:")
        lines.append(f"  主导投票阈值: {self.vote_leadership_threshold:.0%}")
        lines.append(f"  跟随投票阈值: {self.vote_follow_threshold:.0%}")

        lines.append("风险策略:")
        lines.append(f"  风险承受: {self.risk_tolerance:.0%}")
        lines.append(f"  信息探寻: {self.information_seeking:.0%}")

        if self.bluff_timing_preference:
            lines.append(f"  悍跳时机: {self.bluff_timing_preference}")
        if self.sacrifice_threshold is not None:
            lines.append(f"  卖队友阈值: {self.sacrifice_threshold:.0%}")

        return "\n".join(lines)

    def _claim_desc(self) -> str:
        mapping = {
            "honest": "如实报告（除非被威胁）",
            "cautious": "谨慎声明（观察局势后再决定）",
            "aggressive": "积极声明（第一时间亮身份）",
        }
        return mapping.get(self.claim_policy, self.claim_policy)

    def _info_release_desc(self) -> str:
        mapping = {
            "timely": "适时释放（关键信息及时公开）",
            "withhold": "保守（尽量保留信息）",
            "selective": "选择释放（只对信任对象透露）",
        }
        return mapping.get(self.info_release_policy, self.info_release_policy)


@dataclass
class StrategyMemory:
    """Cross-round persistent strategy state.

    Tracks the agent's tactical situation across rounds.
    Independent of MBTI/Persona — pure decision-layer state.
    """

    current_tactic: str = ""  # Current tactical approach
    suspicion_ranking: list[str] = field(default_factory=list)  # Most→least suspicious
    trusted_allies: list[str] = field(default_factory=list)  # Players believed village
    exposed_risk: float = 0.0  # Risk of role exposure (0-1)
    info_debt: list[str] = field(default_factory=list)  # Info owed to team
    last_claim: str | None = None  # Last public role claim
    stance_history: list[dict] = field(default_factory=list)  # Past stances

    def record_stance(self, target: str, stance: str, reason: str = "") -> None:
        """Record a stance toward a player for continuity tracking."""
        self.stance_history.append(
            {
                "target": target,
                "stance": stance,  # "suspect", "trust", "neutral"
                "reason": reason,
            }
        )
        if len(self.stance_history) > 20:
            self.stance_history = self.stance_history[-20:]

    def get_stance(self, target: str) -> str | None:
        """Get the most recent stance toward a player."""
        for entry in reversed(self.stance_history):
            if entry["target"] == target:
                return entry["stance"]
        return None


# Registry of strategy cards by role
_STRATEGY_REGISTRY: dict[str, type[RoleStrategyCard]] = {}


def register_strategy(role: str):
    """Decorator to register a strategy card class for a role."""

    def decorator(cls: type[RoleStrategyCard]):
        _STRATEGY_REGISTRY[role.lower()] = cls
        return cls

    return decorator


def get_strategy_card(role: str, **overrides) -> RoleStrategyCard:
    """Get the strategy card for a role, with optional parameter overrides."""
    from backend.agents.cognitive.strategies import GuardStrategyCard
    from backend.agents.cognitive.strategies import HunterStrategyCard
    from backend.agents.cognitive.strategies import SeerStrategyCard
    from backend.agents.cognitive.strategies import VillagerStrategyCard
    from backend.agents.cognitive.strategies import WerewolfStrategyCard
    from backend.agents.cognitive.strategies import WitchStrategyCard

    # Import triggers registration; explicit mapping as fallback
    mapping = {
        "seer": SeerStrategyCard,
        "witch": WitchStrategyCard,
        "hunter": HunterStrategyCard,
        "guard": GuardStrategyCard,
        "villager": VillagerStrategyCard,
        "werewolf": WerewolfStrategyCard,
        "whitewolfking": WerewolfStrategyCard,
        "idiot": VillagerStrategyCard,
    }

    cls = mapping.get(role.lower().replace("_", "").replace("-", ""), RoleStrategyCard)
    card = cls()
    for key, value in overrides.items():
        if hasattr(card, key):
            setattr(card, key, value)
    return card
