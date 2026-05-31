"""Prompt builder — constructs system and user prompts for each phase.

Upgraded to wolfcha-style quality: rich game context, personality-aware speech
guidance, structured reasoning, and role-specific strategy injection.

Single Responsibility: translate game state + character + memory into prompts.
No LLM calls, no game logic — pure string construction.
"""

from __future__ import annotations

from typing import List, Optional

from backend.agents.cognitive.memory import Memory
from backend.agents.cognitive.observe import Observation, format_observation
from backend.agents.cognitive.profiles import Profile, get_profile


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

    parts.extend([
        "",
        "请用 3-5 句话总结当前局势最重要的观察。",
        "包括：关键信号、矛盾点、信息差、可疑模式。",
        "只描述事实和推断依据，不做最终判断。",
    ])
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
    strategy bias.
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

    parts.extend([
        "",
        "【推理任务】",
        "请基于以上信息进行分析：",
        "1. 当前局势的关键矛盾是什么？有哪些信息差？",
        "2. 逐一点评每个存活玩家：发言逻辑、投票行为、角色声称是否可信",
        "3. 综合判断：最怀疑谁（按嫌疑度排序 top-2），最信任谁",
        "4. 如果你是有信息的神职（预言家/女巫/守卫），当前最优行动是什么？",
        "5. 如果你没有额外信息（村民/隐狼），当前该站边谁、踩谁？",
        "",
        "用 4-6 句话总结，要具体点名人名，不能泛泛而谈。",
    ])
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
        return (
            "【遗言】你已经出局，发表遗言。交代身份、留下信息、点出最可疑的人。"
        )
    if "BADGE" in str(phase):
        return (
            "【警徽竞选发言】你不是来点评别人的——你是来争取警徽的。"
            "说明为什么想拿警徽、更想看谁、能不能带队。"
        )
    if "PK" in str(phase):
        return (
            "【PK发言】场上已缩到少数焦点位。直接反驳冲你的人，"
            "或解释为什么另一个PK位更该出。"
        )
    if is_first:
        return (
            "【首个发言】第一个发言，不要先解释'信息少'或'先观察'。"
            "直接抛出一个你要抓的方向——行为模式、玩家类型或警徽态度。"
        )
    return (
        "【白天发言】从上一个发言者的观点切入，认同、质疑、补充都可以。"
        "不需要面面俱到，只说此刻最在意的一点。"
    )


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

    return "\n".join([
        game_ctx,
        "",
        f"=== 分析结论 ===\n{think_result}",
        "",
        f"【投票】可投: {alive_names}",
        "请选择你要投票放逐的玩家。输出 JSON：",
        '{"reasoning": "投票理由（1-2句，引用具体发言或行为）", "target": "玩家名字"}',
    ])


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

    parts.extend([
        "",
        f"=== 分析结论 ===\n{think_result}",
        "",
        f"【夜晚行动】可选目标: {alive_names}",
        "请选择目标。输出 JSON：",
        '{"reasoning": "选择理由（1-2句，结合策略分析）", "target": "玩家名字"}',
    ])

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
        "即使你认为某条规则不是最优，也必须按字面意思行动，不要二次判断。",
    ]
    for section in sections:
        for item in strategy_bias.get(section, [])[:3]:
            lines.append(f"- [{section}] {item}")

    return "\n".join(lines) if len(lines) > 3 else ""


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
