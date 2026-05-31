"""Thinking layer — analyzes observations and generates judgments.

The thinking layer takes observations and:
1. Analyzes the situation from the agent's role perspective
2. Evaluates each player's likelihood of being wolf/good
3. Considers strategic implications
4. Generates candidate actions with risk/benefit analysis
"""

from __future__ import annotations

from backend.agents.cognitive.memory import AgentMemory
from backend.agents.cognitive.state import GameObservation


def build_think_prompt(
    obs: GameObservation,
    memory: AgentMemory,
    strategy_hint: str = "",
) -> str:
    """Build the thinking prompt for the LLM.

    The LLM should output structured analysis:
    - Player-by-player assessment
    - Strategic situation analysis
    - Candidate actions with reasoning
    """

    # Build player assessment table
    player_lines = _build_player_assessment(obs, memory)

    # Build strategic context
    strategy_lines = _build_strategy_context(obs)

    # Build candidate actions
    candidate_lines = _build_candidate_actions(obs)

    # Memory context
    memory_text = memory.format_for_prompt()

    parts = [
        f"你是 {obs.player_seat}号:{obs.player_name}，身份={obs.player_role}，第{obs.day}天 {obs.phase}阶段。",
        "",
        "=== 玩家评估 ===",
        *player_lines,
        "",
        "=== 战略分析 ===",
        *strategy_lines,
        "",
    ]

    if memory_text:
        parts.extend(["=== 我的记忆 ===", memory_text, ""])

    if strategy_hint:
        parts.extend(["=== 策略提示 ===", strategy_hint, ""])

    parts.extend([
        "=== 候选行动 ===",
        *candidate_lines,
        "",
        "请分析当前局势，给出你对每个存活玩家的判断（好人/狼人/不确定），",
        "以及你推荐的行动和理由。用 3-5 句话表达。"
    ])

    return "\n".join(parts)


def _build_player_assessment(obs: GameObservation, memory: AgentMemory) -> list[str]:
    """Build player-by-player assessment."""
    lines = []

    for p in obs.alive_players:
        if p.player_id == obs.player_id:
            lines.append(f"  {p.seat}号:{p.name} = 你自己（{obs.player_role}）")
            continue

        # Check memory for previous judgment
        prev = memory.get_player_judgment(p.name)
        prev_note = f" [上次判断: {prev.judgment}({prev.confidence:.0%})]" if prev else ""

        # Simple heuristic signals
        signals = []
        for speech in obs.today_speeches:
            if speech.player_id == p.player_id:
                content = speech.content
                if "预言家" in content:
                    signals.append("跳预言家")
                if "狼人" in content and ("一定" in content or "肯定" in content):
                    signals.append("强指狼")
                if len(content) < 20:
                    signals.append("发言极短")

        signal_str = f" 信号: {', '.join(signals)}" if signals else ""
        lines.append(f"  {p.seat}号:{p.name}{prev_note}{signal_str}")

    return lines


def _build_strategy_context(obs: GameObservation) -> list[str]:
    """Build strategic context analysis."""
    lines = []
    alive_count = len(obs.alive_players)
    dead_count = len(obs.dead_players)

    # Estimate wolf count
    # In 7-player game: 2 wolves, 5 good
    # In 9-player game: 3 wolves, 6 good
    total = alive_count + dead_count
    if total <= 7:
        total_wolves = 2
    elif total <= 9:
        total_wolves = 3
    else:
        total_wolves = 4

    lines.append(f"存活 {alive_count} 人，已死亡 {dead_count} 人")
    lines.append(f"预计总狼人 {total_wolves} 人")

    # Day-specific strategy
    if obs.day == 1:
        lines.append("第一天：信息极少，以收集信息为主，不应急于定论")
    elif obs.day == 2:
        lines.append("第二天：有第一天的投票和死亡信息，可以开始形成初步判断")
    else:
        lines.append(f"第{obs.day}天：中后期，需要明确站边，推动出狼")

    # Phase-specific
    if "SPEECH" in obs.phase:
        lines.append("当前是发言阶段：需要给出你的判断方向和理由")
    elif "VOTE" in obs.phase:
        lines.append("当前是投票阶段：需要做出最终投票决定")
    elif "NIGHT" in obs.phase:
        lines.append("当前是夜间：需要执行角色技能")

    return lines


def _build_candidate_actions(obs: GameObservation) -> list[str]:
    """Build candidate actions based on phase."""
    lines = []

    if "SPEECH" in obs.phase:
        lines.append("A. 给出一个主怀疑对象，攻击其发言矛盾")
        lines.append("B. 回应被点名的质疑，澄清自己的立场")
        lines.append("C. 分析票型，指出可疑的投票行为")
        lines.append("D. 支持某个你认为是好人的玩家")
        lines.append("E. 提出新信息或新角度")

    elif "VOTE" in obs.phase:
        lines.append("A. 投票给你最怀疑的玩家")
        lines.append("B. 跟票大流（如果不确定）")
        lines.append("C. 投票给被多人怀疑的目标（归票）")

    elif "NIGHT_WOLF" in obs.phase:
        lines.append("A. 刀掉最可能的神职")
        lines.append("B. 刀掉对你威胁最大的好人")
        lines.append("C. 和狼队友统一意见")

    elif "NIGHT_SEER" in obs.phase:
        lines.append("A. 查验最可疑的玩家")
        lines.append("B. 查验高影响力玩家（警长、强势带队位）")
        lines.append("C. 查验尚未有信息的玩家")

    elif "NIGHT_WITCH" in obs.phase:
        lines.append("A. 救人（如果是关键神职或好人）")
        lines.append("B. 不救（保留解药）")
        lines.append("C. 毒人（如果有高置信度的狼人判断）")

    elif "NIGHT_GUARD" in obs.phase:
        lines.append("A. 守护最可能被刀的神职")
        lines.append("B. 守护警长")
        lines.append("C. 守护你认为是好人且有威胁的玩家")

    return lines
