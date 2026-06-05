"""
Strategy Registry — unified lookup for strategy cards.

Parses configs/strategy_library.yaml and builds stable, queryable
StrategyCard objects with unique strategy_id per card.

Each card groups related tips from the YAML into a coherent strategy
that can be injected into Agent prompts and tracked in logs.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StrategyCard:
    """A named, versioned strategy card for a specific role or role group."""

    strategy_id: str
    strategy_name: str
    strategy_type: str
    applicable_roles: tuple[str, ...]
    version: str = "v1"
    source: str = "strategy_library.yaml"
    content: tuple[str, ...] = ()  # individual strategy tips
    risk_notes: tuple[str, ...] = ()
    # summary line for compact display in prompts
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "strategy_type": self.strategy_type,
            "applicable_roles": list(self.applicable_roles),
            "version": self.version,
            "source": self.source,
            "content": list(self.content),
            "risk_notes": list(self.risk_notes),
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# Strategy type taxonomy
# ---------------------------------------------------------------------------

STRATEGY_TYPES = {
    "info_release": "信息释放策略 — 何时/如何发布查验结果或身份信息",
    "resource_management": "资源管理策略 — 管理有限资源(药/子弹/守护次数)",
    "deception": "伪装欺骗策略 — 隐藏真实身份,伪装成其他角色",
    "vote_lead": "投票带队策略 — 引导投票方向,控制票型",
    "protection": "守护保护策略 — 选择保护目标,预判狼人攻击",
    "threat": "威慑策略 — 利用技能威慑影响他人行为",
    "logic_vote": "逻辑投票策略 — 基于逻辑推理的投票决策",
    "general": "通用策略 — 适用于所有角色的基础策略",
    "board_config": "板子配置",
    "game_theory": "博弈论视角策略",
    "pro_play": "职业赛事高级策略",
}


# ---------------------------------------------------------------------------
# Card builder
# ---------------------------------------------------------------------------


def _stable_id(prefix: str, name: str) -> str:
    """Generate a stable, human-readable strategy_id.

    Uses a short hash suffix for uniqueness while keeping the prefix meaningful.
    """
    digest = hashlib.blake2b(name.encode(), digest_size=4).hexdigest()
    return f"{prefix}_{digest}"


def _load_yaml(path: str = "configs/strategy_library.yaml") -> dict:
    """Load and return the raw strategy library YAML."""
    resolved = Path(path)
    if not resolved.exists():
        resolved = Path(__file__).parent.parent.parent / path
    with open(resolved, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _collect_tips(raw: dict, role: str, *keys: str) -> list[str]:
    """Collect tips from role>category paths, flattening lists."""
    tips: list[str] = []
    role_data = raw.get(role, {})
    for key in keys:
        entries = role_data.get(key, [])
        if isinstance(entries, list):
            tips.extend([e for e in entries if isinstance(e, str)])
    return tips


# ---------------------------------------------------------------------------
# Card definitions — explicit grouping from strategy_library.yaml
# ---------------------------------------------------------------------------


def _build_cards(raw: dict) -> list[StrategyCard]:
    cards: list[StrategyCard] = []

    # -- Seer -----------------------------------------------------------------
    seer_aggressive = _collect_tips(raw, "Seer", "core_strategy", "vote_strategy", "skill_strategy")
    seer_aggressive_risk = _collect_tips(raw, "Seer", "risk_rules")
    cards.append(
        StrategyCard(
            strategy_id="seer_aggressive_reveal_v1",
            strategy_name="激进信息释放",
            strategy_type="info_release",
            applicable_roles=("Seer",),
            version="v1",
            content=tuple(seer_aggressive),
            risk_notes=tuple(seer_aggressive_risk),
            summary="查验到狼人立即跳身份发布信息,报查验+留警徽流+聊心路历程,抢占信息主动权",
        )
    )

    seer_conservative = _collect_tips(raw, "Seer", "advanced")
    cards.append(
        StrategyCard(
            strategy_id="seer_conservative_hide_v1",
            strategy_name="保守信息隐藏",
            strategy_type="info_release",
            applicable_roles=("Seer",),
            version="v1",
            content=tuple(seer_conservative),
            risk_notes=(),
            summary="选择性发布查验结果,查验到好人先隐藏身份,查验到狼人在关键轮次发布",
        )
    )

    # -- Witch ----------------------------------------------------------------
    witch_save = _collect_tips(raw, "Witch", "core_strategy", "skill_strategy", "vote_strategy")
    witch_save_risk = _collect_tips(raw, "Witch", "risk_rules")
    cards.append(
        StrategyCard(
            strategy_id="witch_conservative_save_v1",
            strategy_name="保守用药",
            strategy_type="resource_management",
            applicable_roles=("Witch",),
            version="v1",
            content=tuple(witch_save),
            risk_notes=tuple(witch_save_risk),
            summary="解药留给关键身份,毒药仅用于确认狼人,第一夜谨慎用药,白天隐藏身份",
        )
    )

    witch_aggressive = _collect_tips(raw, "Witch", "advanced")
    cards.append(
        StrategyCard(
            strategy_id="witch_aggressive_poison_v1",
            strategy_name="激进用药",
            strategy_type="resource_management",
            applicable_roles=("Witch",),
            version="v1",
            content=tuple(witch_aggressive),
            risk_notes=(),
            summary="首夜双药同开获取最大收益,解药用完后公开身份引领方向",
        )
    )

    # -- Hunter ---------------------------------------------------------------
    hunter_tips = _collect_tips(raw, "Hunter", "core_strategy", "skill_strategy", "vote_strategy")
    hunter_risk = _collect_tips(raw, "Hunter", "risk_rules")
    cards.append(
        StrategyCard(
            strategy_id="hunter_restraint_v1",
            strategy_name="猎人不跳",
            strategy_type="threat",
            applicable_roles=("Hunter",),
            version="v1",
            content=tuple(hunter_tips),
            risk_notes=tuple(hunter_risk),
            summary="白天积极发言但不跳身份,出局时带刀首选预言家定位的狼,被毒时不能开枪",
        )
    )

    # -- Guard ----------------------------------------------------------------
    guard_tips = _collect_tips(raw, "Guard", "core_strategy", "skill_strategy", "vote_strategy")
    guard_risk = _collect_tips(raw, "Guard", "risk_rules")
    cards.append(
        StrategyCard(
            strategy_id="guard_key_role_protect_v1",
            strategy_name="关键神守",
            strategy_type="protection",
            applicable_roles=("Guard",),
            version="v1",
            content=tuple(guard_tips),
            risk_notes=tuple(guard_risk),
            summary="白天隐藏身份,优先守护预言家/女巫/猎人,禁止连续守同人,分析狼人攻击模式预判",
        )
    )

    # -- Werewolf -------------------------------------------------------------
    # Low-profile deception
    wolf_disguise = _collect_tips(raw, "Werewolf", "disguise", "read_players", "risk_rules")
    wolf_roles_deep = _collect_tips(raw, "Werewolf", "roles")
    cards.append(
        StrategyCard(
            strategy_id="werewolf_low_profile_deception_v1",
            strategy_name="低调深水伪装",
            strategy_type="deception",
            applicable_roles=("Werewolf", "WhiteWolfKing"),
            version="v1",
            content=tuple(wolf_disguise + wolf_roles_deep),
            risk_notes=(),
            summary="深水狼打法:低调存活,模仿平民发言,避免与队友过度互动,缓慢渗透获取信任",
        )
    )

    # Strong vote lead
    wolf_bluff = _collect_tips(raw, "Werewolf", "bluff", "control", "vote_strategy", "kill_priority")
    wolf_advanced = _collect_tips(raw, "Werewolf", "advanced")
    cards.append(
        StrategyCard(
            strategy_id="werewolf_strong_vote_lead_v1",
            strategy_name="悍跳带队冲锋",
            strategy_type="vote_lead",
            applicable_roles=("Werewolf", "WhiteWolfKing"),
            version="v1",
            content=tuple(wolf_bluff + wolf_advanced),
            risk_notes=(),
            summary="悍跳狼+冲锋狼体系:冒充预言家争夺警徽,引导好人内斗,统一冲票行动,自爆时机把握",
        )
    )

    # -- Villager -------------------------------------------------------------
    villager_tips = _collect_tips(raw, "Villager", "core_strategy", "speech_strategy")
    villager_advanced = _collect_tips(raw, "Villager", "advanced")
    cards.append(
        StrategyCard(
            strategy_id="villager_logic_vote_v1",
            strategy_name="逻辑分析投票",
            strategy_type="logic_vote",
            applicable_roles=("Villager", "Idiot"),
            version="v1",
            content=tuple(villager_tips + villager_advanced),
            risk_notes=(),
            summary="作为票型决定者,清晰表水+推理逻辑+关注票型一致性,阳光发言减少队友误投",
        )
    )

    # -- General strategies (role-agnostic) -----------------------------------
    gen_logic = _collect_tips(raw, "General", "logic")
    gen_speech = _collect_tips(raw, "General", "speech")
    gen_vote = _collect_tips(raw, "General", "vote")
    gen_psych = _collect_tips(raw, "General", "psychology")
    cards.append(
        StrategyCard(
            strategy_id="general_basic_logic_v1",
            strategy_name="通用基础逻辑",
            strategy_type="general",
            applicable_roles=(
                "Werewolf",
                "WhiteWolfKing",
                "Seer",
                "Witch",
                "Hunter",
                "Guard",
                "Villager",
                "Idiot",
            ),
            version="v1",
            content=tuple(gen_logic + gen_speech + gen_vote + gen_psych),
            risk_notes=(),
            summary="铁逻辑推理+发言信息量+投票立场一致+收益论+心理博弈基础,适用于所有角色",
        )
    )

    # -- GameTheory -----------------------------------------------------------
    gt_all = _collect_tips(raw, "GameTheory", "estimation", "attack_priority", "mixed_strategy")
    cards.append(
        StrategyCard(
            strategy_id="general_game_theory_v1",
            strategy_name="博弈论视角",
            strategy_type="game_theory",
            applicable_roles=(
                "Werewolf",
                "WhiteWolfKing",
                "Seer",
                "Witch",
                "Hunter",
                "Guard",
                "Villager",
                "Idiot",
            ),
            version="v1",
            content=tuple(gt_all),
            risk_notes=(),
            summary="子博弈估计+攻击优先级调整+混合策略(20%概率说谎),贝叶斯更新",
        )
    )

    # -- BoardConfigs ---------------------------------------------------------
    board_tips: list[str] = []
    board_data = raw.get("BoardConfigs", {})
    if isinstance(board_data, dict):
        for board_name, board_info in board_data.items():
            if isinstance(board_info, dict):
                desc = board_info.get("desc", "")
                config = board_info.get("config", "")
                board_tips.append(f"{board_name}: {desc} — 配置: {config}")
    if board_tips:
        cards.append(
            StrategyCard(
                strategy_id="board_configs_v1",
                strategy_name="板子配置参考",
                strategy_type="board_config",
                applicable_roles=(
                    "Werewolf",
                    "WhiteWolfKing",
                    "Seer",
                    "Witch",
                    "Hunter",
                    "Guard",
                    "Villager",
                    "Idiot",
                ),
                version="v1",
                content=tuple(board_tips),
                risk_notes=(),
                summary="常见板子配置(6人/9人/12人/狼王/白狼王/狼美人/双王)的角色分布参考",
            )
        )

    # -- VillageCoordination --------------------------------------------------
    vc_tips = _collect_tips(
        raw,
        "VillageCoordination",
        "seer_witch_guard",
        "village_voting",
        "information_sharing",
        "anti_wolf_tactics",
    )
    if vc_tips:
        cards.append(
            StrategyCard(
                strategy_id="village_coordination_v1",
                strategy_name="村民阵营协作",
                strategy_type="general",
                applicable_roles=("Villager", "Seer", "Witch", "Hunter", "Guard", "Idiot"),
                version="v1",
                content=tuple(vc_tips),
                risk_notes=(),
                summary="好人阵营协作策略: 神职协作链条、统一投票、信息共享、反焊跳识别",
            )
        )

    # -- ProPlay --------------------------------------------------------------
    pp_tips = _collect_tips(
        raw,
        "ProPlay",
        "wolf_god_tactics",
        "mianren_reading",
        "control_tactics",
        "counter_strategies",
    )
    if pp_tips:
        cards.append(
            StrategyCard(
                strategy_id="pro_play_advanced_v1",
                strategy_name="职业赛事高级技巧",
                strategy_type="pro_play",
                applicable_roles=(
                    "Werewolf",
                    "WhiteWolfKing",
                    "Seer",
                    "Witch",
                    "Hunter",
                    "Guard",
                    "Villager",
                    "Idiot",
                ),
                version="v1",
                content=tuple(pp_tips),
                risk_notes=(),
                summary="职业赛事高级策略: 狼神焊跳、状态抿人、控场技巧、反焊跳识别(面杀向)",
            )
        )

    return cards


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class StrategyRegistry:
    """Queryable registry of all strategy cards.

    Usage::

        registry = StrategyRegistry()
        card = registry.get("seer_aggressive_reveal_v1")
        seer_cards = registry.list_by_role("Seer")
    """

    def __init__(self, cards: list[StrategyCard] | None = None):
        if cards is None:
            raw = _load_yaml()
            cards = _build_cards(raw)
        self._cards: dict[str, StrategyCard] = {c.strategy_id: c for c in cards}
        self._by_role: dict[str, list[StrategyCard]] = {}
        for card in cards:
            for role in card.applicable_roles:
                self._by_role.setdefault(role, []).append(card)

    def get(self, strategy_id: str) -> StrategyCard:
        """Return a strategy card by id. Raises KeyError if not found."""
        if strategy_id not in self._cards:
            raise KeyError(f"Unknown strategy_id: {strategy_id!r}. Available: {sorted(self._cards.keys())}")
        return self._cards[strategy_id]

    def list_by_role(self, role: str) -> list[StrategyCard]:
        """List all strategy cards applicable to a given role."""
        return self._by_role.get(role, [])

    def list_all(self) -> list[StrategyCard]:
        """Return all registered strategy cards."""
        return list(self._cards.values())

    def list_by_type(self, strategy_type: str) -> list[StrategyCard]:
        """List all strategy cards of a given type."""
        return [c for c in self._cards.values() if c.strategy_type == strategy_type]

    def default_for_role(self, role: str) -> StrategyCard:
        """Return the default strategy for a role.

        Falls back to general_basic_logic_v1 if no role-specific card found.
        """
        cards = self.list_by_role(role)
        # Filter out general/game_theory — prefer role-specific
        role_specific = [c for c in cards if c.strategy_type not in ("general", "game_theory")]
        if role_specific:
            return role_specific[0]
        if cards:
            return cards[0]
        return self.get("general_basic_logic_v1")

    def __len__(self) -> int:
        return len(self._cards)

    def __contains__(self, strategy_id: str) -> bool:
        return strategy_id in self._cards


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_registry: StrategyRegistry | None = None


def get_strategy_registry() -> StrategyRegistry:
    """Return the module-level singleton StrategyRegistry, building on first call."""
    global _registry
    if _registry is None:
        _registry = StrategyRegistry()
    return _registry


# ---------------------------------------------------------------------------
# Audit / report helpers
# ---------------------------------------------------------------------------


def build_audit_report() -> str:
    """Build a markdown audit report of the strategy registry."""
    registry = get_strategy_registry()
    cards = registry.list_all()

    lines = [
        "# Strategy Registry Audit V8",
        "",
        f"**Total strategy cards**: {len(cards)}",
        "",
        "## By Role",
        "",
    ]

    roles = sorted(set(r for c in cards for r in c.applicable_roles))
    for role in roles:
        role_cards = registry.list_by_role(role)
        lines.append(f"### {role} ({len(role_cards)} cards)")
        for card in role_cards:
            lines.append(f"- **{card.strategy_id}** — {card.strategy_name} ({card.strategy_type})")
            lines.append(f"  - Tips: {len(card.content)}, Risks: {len(card.risk_notes)}")
            lines.append(f"  - Summary: {card.summary}")
        lines.append("")

    lines.append("## By Type")
    lines.append("")
    for stype, desc in STRATEGY_TYPES.items():
        typed = registry.list_by_type(stype)
        if typed:
            lines.append(f"### {stype} ({len(typed)} cards)")
            lines.append(f"{desc}")
            for card in typed:
                lines.append(f"- **{card.strategy_id}** → {', '.join(card.applicable_roles)}")
            lines.append("")

    lines.append("## Card Details")
    lines.append("")
    for card in sorted(cards, key=lambda c: c.strategy_id):
        lines.append(f"### {card.strategy_id}")
        lines.append(f"- Name: {card.strategy_name}")
        lines.append(f"- Type: {card.strategy_type}")
        lines.append(f"- Roles: {', '.join(card.applicable_roles)}")
        lines.append(f"- Version: {card.version}")
        lines.append(f"- Source: {card.source}")
        lines.append(f"- Tips: {len(card.content)}, Risks: {len(card.risk_notes)}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    registry = get_strategy_registry()
    print(f"StrategyRegistry loaded: {len(registry)} cards")
    for card in sorted(registry.list_all(), key=lambda c: c.strategy_id):
        print(
            f"  {card.strategy_id:45s} {card.strategy_name:20s} "
            f"type={card.strategy_type:22s} roles={','.join(card.applicable_roles)}"
        )
    print()

    # Write audit
    audit_path = Path("data/health/strategy_registry_audit_v8.md")
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(build_audit_report(), encoding="utf-8")
    print(f"Audit written to {audit_path}")
