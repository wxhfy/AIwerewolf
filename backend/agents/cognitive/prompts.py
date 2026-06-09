"""Prompt builder — constructs system and user prompts for each phase.

Upgraded to wolfcha-style quality: rich game context, personality-aware speech
guidance, structured reasoning, and role-specific strategy injection.

Single Responsibility: translate game state + character + memory into prompts.
No LLM calls, no game logic — pure string construction.
"""

from __future__ import annotations

from typing import Optional

from backend.agents.cognitive.memory import Memory
from backend.agents.cognitive.observe import Observation
from backend.agents.cognitive.observe import format_observation
from backend.agents.cognitive.profiles import Profile
from backend.agents.cognitive.profiles import get_profile

# ============================================================
# System Prompt
# ============================================================


def build_system_prompt(role: str, profile: Optional[Profile] = None) -> str:
    """Build the system prompt from Profile.to_system_intro().

    Built ONCE at agent initialization and reused for all LLM calls.
    """
    p = profile or get_profile(role)
    return p.to_system_intro()


# ============================================================
# Game Context (wolfcha-style YAML-like)
# ============================================================


def build_game_context(obs: Observation) -> str:
    """Build a rich, structured game context block (wolfcha-style)."""
    alive_list = ", ".join(f"{p.seat}号:{p.name}" for p in obs.alive)
    dead_list = ", ".join(f"{p.seat}号:{p.name}" for p in obs.dead) or "无"
    sheriff = _find_sheriff_from_obs(obs)

    lines = [
        "【游戏状态】",
        f"天: {obs.day}  |  阶段: {obs.phase}  |  存活: {len(obs.alive)}/{len(obs.alive) + len(obs.dead)}",
        f"你的身份: {obs.player_role}  |  你的座位: {obs.player_seat}号:{obs.player_name}",
        f"警长: {sheriff}",
        f"存活玩家: {alive_list}",
        f"死亡玩家: {dead_list}",
    ]

    # Rules reminder
    lines.append("")
    lines.append("【规则摘要】")
    lines.append("投票放逐狼人。预言家每晚查验一人。女巫有解药+毒药各一。")
    lines.append("猎人死亡可开枪。守卫每晚守护一人（不能连守）。")

    return "\n".join(lines)


def _find_sheriff_from_obs(obs: Observation) -> str:
    """Find the sheriff/badge holder from observation."""
    for claim in obs.role_claims:
        if "警长" in claim.context or "badge" in claim.context.lower():
            return f"{claim.seat}号:{claim.player_name}"
    return "无"


# ============================================================
# Stage 1: Observe
# ============================================================


def build_observe_prompt(obs: Observation) -> str:
    """Build prompt for the observation stage: extract key signals.

    Now includes rich game context + contradiction hints + voting patterns.
    """
    game_ctx = build_game_context(obs)
    obs_text = format_observation(obs)

    parts = [game_ctx, "", obs_text]

    if obs.belief_summary:
        parts.extend(["", obs.belief_summary])

    parts.extend(
        [
            "",
            "请用 3-5 句话总结当前局势最重要的观察。",
            "包括：关键信号、矛盾点、信息差、可疑模式。",
            "只描述事实和推断依据，不做最终判断。",
        ]
    )
    return "\n".join(parts)


# ============================================================
# Stage 2: Think
# ============================================================


def build_think_prompt(
    obs: Observation,
    memory: Memory,
    strategy_text: str = "",
    strategy_bias_text: str = "",
) -> str:
    """Build prompt for the thinking stage: analyze with full context.

    Injects: observation + memory (incl. humanization) + strategy knowledge +
    strategy bias. Gameplay advice must enter through strategy_text/bias only.
    """
    game_ctx = build_game_context(obs)
    memory_text = memory.format_for_prompt()

    parts = [game_ctx]

    if memory_text:
        parts.extend(["", memory_text])

    if obs.belief_summary:
        parts.extend(["", obs.belief_summary])

    if strategy_text:
        parts.extend(["", strategy_text])

    if strategy_bias_text:
        parts.extend(["", strategy_bias_text])

    parts.extend(
        [
            "",
            "【推理任务】",
            "请基于以上信息进行分析：",
            "1. 当前局势的关键矛盾是什么？有哪些信息差？",
            "2. 逐一点评每个存活玩家：发言逻辑、投票行为、角色声称是否可信",
            "3. 综合判断：最怀疑谁（按嫌疑度排序 top-2），最信任谁",
            "4. 结合你的角色能力和私有信息边界，说明哪些信息是事实，哪些只是推断。",
            "5. 检查你的分析没有越过当前角色的信息边界。",
            "",
            "用 4-6 句话总结，要具体点名人名，不能泛泛而谈。",
        ]
    )
    return "\n".join(parts)


# ============================================================
# Stage 3a: Speech
# ============================================================


def build_speech_prompt(
    obs: Observation,
    think_result: str,
    memory: Memory,
    is_first_speaker: bool = False,
    is_last_words: bool = False,
) -> str:
    """Build prompt for generating a speech — wolfcha-style quality.

    Includes: game context, analysis, personality guardrails,
    anti-repeat rules, and output format constraints.
    """
    game_ctx = build_game_context(obs)
    obs_text = format_observation(obs)

    # Phase-specific task
    task_line = _build_speech_task(obs.phase, is_first_speaker, is_last_words)

    # Style guardrails
    style = _build_speech_style_guardrails()

    # Anti-repeat
    anti_repeat = ""
    if memory.recent_openings:
        openings = "、".join(f'"{o[:30]}..."' for o in memory.recent_openings[-3:])
        anti_repeat = f"\n\n【禁止重复开头】你最近的开场白: {openings}\n本次发言不要用相同方式开场。"

    # Multi-bubble guidance
    h = memory.humanization
    min_seg = h.speech_min_segments if h else 2
    max_seg = h.speech_max_segments if h else 3

    parts = [
        game_ctx,
        "",
        obs_text,
        "",
        f"=== 分析结论 ===\n{think_result}",
        "",
        task_line,
        "",
        style,
        anti_repeat,
        "",
        "【输出格式】",
        f"返回 JSON 字符串数组，{min_seg}-{max_seg} 条消息气泡，每条 1-2 句。",
        '格式: ["第一条消息", "第二条消息"]',
        "",
        "像真人聊天一样说话。可以从上一个人发言的观点切入，表示认同或质疑。",
        "至少点名 1 位玩家。尽量挂住 1 条真实的桌面事实。",
        "直接输出 JSON 数组，不要额外解释。",
    ]

    return "\n".join(parts)


def _build_speech_task(phase: str, is_first: bool, is_last_words: bool) -> str:
    """Build phase-appropriate task description for speech."""
    if is_last_words:
        return "【遗言】你已经出局，发表遗言。只能引用自己真实可见的信息和公开事实。"
    if "BADGE" in str(phase):
        return "【警徽竞选发言】当前是警徽相关发言阶段。围绕你的可见信息、角色边界和当前判断表达。"
    if "PK" in str(phase):
        return "【PK发言】场上已有少数焦点位。回应与你相关的公开质疑，保持事实和推断分离。"
    if is_first:
        return "【首个发言】第一个发言。基于当前已经公开的信息表达你的初始观察。"
    return "【白天发言】从上一个发言者的观点切入，认同、质疑、补充都可以。不需要面面俱到，只说此刻最在意的一点。"


def _build_speech_style_guardrails() -> str:
    """Build style guardrails for natural speech."""
    return (
        "【发言风格要求】\n"
        "- 用「X号」称呼玩家。绝对不要说「请X号发言」「过」「下一位」——你不是主持人。\n"
        "- 语气像真人聊天，可以有语气词、停顿、反问。不要写成总结报告。\n"
        "- 允许保留判断，但保留判断也要说明你接下来重点听谁、盯谁。\n"
        "- 不要虚构自己'听出来''看出来'的场外细节，也不要写成剧本旁白。\n"
        "- 这是线上打字局，你看不到表情、眼神、手势、语速。"
    )


# ============================================================
# Stage 3b: Vote
# ============================================================


def build_vote_prompt(obs: Observation, think_result: str) -> str:
    """Build prompt for generating a vote."""
    game_ctx = build_game_context(obs)
    alive_names = ", ".join(f"{p.seat}号:{p.name}" for p in obs.alive)

    return "\n".join(
        [
            game_ctx,
            "",
            f"=== 分析结论 ===\n{think_result}",
            "",
            f"【投票】可投: {alive_names}",
            "请选择你要投票放逐的玩家。输出 JSON：",
            '{"reasoning": "投票理由（1-2句，引用具体发言或行为）", "target": "玩家名字"}',
        ]
    )


# ============================================================
# Stage 3c: Night Action
# ============================================================


def build_night_prompt(obs: Observation, think_result: str, extra: str = "") -> str:
    """Build prompt for a night action."""
    game_ctx = build_game_context(obs)
    alive_names = ", ".join(f"{p.seat}号:{p.name}" for p in obs.alive)

    parts = [game_ctx]

    if extra:
        parts.extend(["", f"=== 附加信息 ===\n{extra}"])

    parts.extend(
        [
            "",
            f"=== 分析结论 ===\n{think_result}",
            "",
            f"【夜晚行动】可选目标: {alive_names}",
            "请选择目标。输出 JSON：",
            '{"reasoning": "选择理由（1-2句，结合可见信息和角色能力）", "target": "玩家名字"}',
        ]
    )

    return "\n".join(parts)


# ============================================================
# Strategy Bias Block
# ============================================================


def build_strategy_bias_block(strategy_bias: dict, action: str) -> str:
    """Build strategy bias block for LLM injection.

    Args:
        strategy_bias: Dict of section → list of rules
        action: "talk", "vote", "attack", "divine", "guard", "witch_act"

    Returns:
        Formatted strategy bias text or empty string.
    """
    if not strategy_bias:
        return ""

    action_sections = {
        "talk": ("speech_policy", "risk_rules"),
        "vote": ("vote_policy", "risk_rules"),
        "attack": ("skill_policy", "risk_rules"),
        "divine": ("skill_policy", "risk_rules"),
        "guard": ("skill_policy", "risk_rules"),
        "witch_act": ("skill_policy", "risk_rules"),
    }

    sections = action_sections.get(action, ("speech_policy", "vote_policy", "skill_policy", "risk_rules"))
    lines = [
        "【本局强制策略规则 — 高优先级，必须严格遵守】",
        "下列规则由本轮策略版本指定，优先级高于你的通用策略直觉。",
        "但它不得覆盖当前可见事实、角色规则、合法目标、信息边界或本角色基本任务；发生冲突时必须按这些硬约束行动。",
        "执行策略时仍要维护角色任务分：先完成本身份的核心职责，再选择具体打法。",
    ]
    for section in sections:
        for item in strategy_bias.get(section, [])[:3]:
            lines.append(f"- [{section}] {item}")

    return "\n".join(lines) if len(lines) > 3 else ""


# ============================================================
# Role Anti-Patterns (derived from MetricsCalculator bad case types)
# ============================================================

_ROLE_ANTI_PATTERNS: dict[str, dict[str, list[str]]] = {
    "Seer": {
        "speech": [
            "提到查验信息时必须只引用自己真实可见的查验结果，不能编造结果",
            "报查验时要说明第几夜查了谁、结果是什么，避免让事实和推断混在一起",
        ],
        "vote": [
            "不能投票给你查验确认是好人的人，除非当前规则限制没有其他合法目标",
            "投票理由必须区分查验事实、公开发言和个人推断",
        ],
        "night": [
            "不要重复查验同一个玩家",
            "查验目标必须来自当前合法目标列表",
        ],
    },
    "Witch": {
        "speech": [
            "不要声称自己拥有未发生或不可见的用药结果",
        ],
        "vote": [
            "不能投票给你用解药救过的人（你的银水）",
            "投票理由必须基于当前可见事实，不能引用隐藏身份",
        ],
        "night": [
            "绝对不能同一晚使用解药和毒药",
            "用药目标必须来自当前合法目标或今晚刀口，不能凭空指定玩家",
        ],
    },
    "Hunter": {
        "speech": [
            "不能直接跳猎人身份，但可以通过积极发言暗示存在感",
        ],
        "vote": [
            "被毒死或炸死时不能开枪",
            "如果当前阶段要求开枪，目标必须来自合法目标列表",
        ],
        "night": [
            "猎人没有夜晚行动能力，等待白天",
        ],
    },
    "Guard": {
        "speech": [
            "不要暴露自己是守卫，隐藏的守卫比暴露的守卫更强大",
        ],
        "vote": [
            "投票理由必须基于公开事实，不能暴露自己不可公开的身份信息",
        ],
        "night": [
            "绝对不能连续两晚守护同一人",
            "同守同救会导致死亡（奶穿），注意女巫可能用解药",
        ],
    },
    "Villager": {
        "speech": [
            "不要乱穿神职的衣服！你是村民就做村民该做的事",
            "没有技能时不要声称自己有夜间结果",
        ],
        "vote": [
            "不能反复投票给好人",
            "不能投票给预言家查验确认的好人",
        ],
        "night": [
            "村民没有夜晚行动能力，等待白天",
        ],
    },
    "Werewolf": {
        "speech": [
            "绝对不能在发言中泄露夜间信息（如刀口、狼队友）",
            "不要用「我们狼人」等暴露身份的措辞",
            "悍跳预言家时要复刻真预言家的查验逻辑和发言风格",
        ],
        "vote": [
            "不能投票给狼队友！除非是做身份的战略性牺牲",
            "投票发言不能泄露狼队友或夜间私聊信息",
        ],
        "night": [
            "狼队友之间要协调一致，不要各自为战",
            "夜间刀人目标必须来自合法目标列表，不能选择狼队友",
        ],
    },
    "WhiteWolfKing": {
        "speech": [
            "绝对不能在发言中泄露夜间信息或狼队友",
            "自爆时机要把握好，带走关键神职",
        ],
        "vote": [
            "不能投票给狼队友",
        ],
        "night": [
            "夜间刀人目标必须来自合法目标列表，不能选择狼队友",
        ],
    },
}


def get_role_anti_patterns(role: str, action: str = "speech") -> str:
    """Return role-specific anti-patterns as a formatted prompt block.

    Derived from BadCase types that MetricsCalculator consistently detects.
    Injects directly into task descriptions to close the Track C feedback loop.
    """
    role_patterns = _ROLE_ANTI_PATTERNS.get(role, {})
    patterns = role_patterns.get(action, [])
    if not patterns:
        patterns = role_patterns.get("speech", [])
    if not patterns:
        return ""

    lines = ["【本角色常见失误 — 务必避免】"]
    for i, p in enumerate(patterns, 1):
        lines.append(f"  {i}. {p}")
    return "\n".join(lines)


# ============================================================
# Playbook Formatting
# ============================================================


def format_playbook_for_prompt(playbook_notes: dict, action: str = "talk") -> str:
    """Format role playbook as prompt hints.

    Args:
        playbook_notes: Dict with public_debate, vote_logic, night_logic, reveal_logic
        action: "talk", "vote", "night"
    """
    if not playbook_notes:
        return ""

    lines = ["=== 角色行动策略 ==="]
    categories = {
        "talk": ["public_debate", "reveal_logic"],
        "vote": ["vote_logic"],
        "night": ["night_logic"],
    }
    for cat in categories.get(action, ["public_debate"]):
        for hint in playbook_notes.get(cat, [])[:2]:
            lines.append(f"  - {hint}")

    return "\n".join(lines) if len(lines) > 1 else ""
