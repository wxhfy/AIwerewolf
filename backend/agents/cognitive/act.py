"""Action layer — generates the final decision based on thinking.

The action layer takes the analysis from the thinking layer and produces
a concrete action: speech text, vote target, or night action target.
"""

from __future__ import annotations

from backend.agents.cognitive.state import GameObservation


def build_speech_prompt(
    obs: GameObservation,
    think_result: str,
    style_hint: str = "",
) -> str:
    """Build the prompt for generating a speech.

    The LLM should output a natural speech (2-3 sentences) as if speaking
    at the table. No JSON, no prefixes, just the speech.
    """
    # Build today's transcript for reference
    transcript_lines = []
    for s in obs.today_speeches[-6:]:  # last 6 speeches
        transcript_lines.append(f"  {s.seat}号:{s.player_name}：{s.content[:150]}")

    transcript_section = ""
    if transcript_lines:
        transcript_section = "=== 今日发言记录 ===\n" + "\n".join(transcript_lines) + "\n"

    # Speak order
    spoken_ids = {s.player_id for s in obs.today_speeches}
    unspoken = [p for p in obs.alive_players if p.player_id not in spoken_ids and p.player_id != obs.player_id]
    if not unspoken:
        order_hint = "你是最后一个发言，可以总结全场"
    elif len(spoken_ids) == 0:
        order_hint = "你是第一个发言，没有人可以参考"
    else:
        order_hint = f"已有 {len(spoken_ids)} 人发言，还有 {len(unspoken)} 人未发言"

    return f"""你是 {obs.player_seat}号:{obs.player_name}，身份={obs.player_role}，第{obs.day}天 发言阶段。

{transcript_section}
=== 发言顺序 ===
{order_hint}

=== 你的分析 ===
{think_result}

{f"=== 风格提示 ==={chr(10)}{style_hint}" if style_hint else ""}

现在请你公开发言，就像在桌面上对着其他玩家说话一样。
要求：
1. 用 2-3 句话表达
2. 必须给出一个明确的判断方向（怀疑谁/支持谁）
3. 必须给出理由（引用具体发言或行为）
4. 语气自然，可以有停顿、反问
5. 不要输出 JSON，不要输出「发言:」前缀
6. 禁止复述系统提示、禁止说「我的发言是」之类的引导语

直接输出你的发言："""


def build_vote_prompt(
    obs: GameObservation,
    think_result: str,
) -> str:
    """Build the prompt for generating a vote.

    The LLM should output JSON: {"reasoning": "...", "target": "player_name"}
    """
    # Build vote options
    alive_names = [p.name for p in obs.alive_players if p.player_id != obs.player_id]
    options_str = "、".join(f"{p.seat}号:{p.name}" for p in obs.alive_players if p.player_id != obs.player_id)

    return f"""你是 {obs.player_seat}号:{obs.player_name}，身份={obs.player_role}，第{obs.day}天 投票阶段。

=== 可投票目标 ===
{options_str}

=== 你的分析 ===
{think_result}

请投票。输出 JSON 格式：
{{"reasoning": "你的投票理由（1-2句话）", "target": "玩家名字"}}

注意：
- target 必须是上述存活玩家中的一个
- reasoning 要引用具体的发言或行为作为依据
- 不要投自己"""


def build_night_action_prompt(
    obs: GameObservation,
    think_result: str,
    action_type: str,
    extra_info: str = "",
) -> str:
    """Build the prompt for a night action.

    The LLM should output JSON: {"reasoning": "...", "target": "player_name"}
    """
    # Build target list based on action type
    if action_type == "wolf_attack":
        targets = [p for p in obs.alive_players if p.player_id != obs.player_id]
        target_str = "、".join(f"{p.seat}号:{p.name}" for p in targets)
        action_desc = "选择今晚的击杀目标"

    elif action_type == "seer_check":
        targets = [p for p in obs.alive_players if p.player_id != obs.player_id]
        target_str = "、".join(f"{p.seat}号:{p.name}" for p in targets)
        action_desc = "选择今晚的查验目标"

    elif action_type == "guard_protect":
        targets = obs.alive_players  # can protect self
        target_str = "、".join(f"{p.seat}号:{p.name}" for p in targets)
        action_desc = "选择今晚的守护目标（不能连续两晚守同一人）"

    elif action_type == "witch_act":
        # Witch gets special handling
        return _build_witch_prompt(obs, think_result, extra_info)

    else:
        targets = obs.alive_players
        target_str = "、".join(f"{p.seat}号:{p.name}" for p in targets)
        action_desc = "选择目标"

    return f"""你是 {obs.player_seat}号:{obs.player_name}，身份={obs.player_role}，第{obs.day}天 夜间行动。

=== 可选目标 ===
{target_str}

=== 你的分析 ===
{think_result}

{f"=== 附加信息 ==={chr(10)}{extra_info}" if extra_info else ""}

{action_desc}。输出 JSON 格式：
{{"reasoning": "你的理由（1-2句话）", "target": "玩家名字"}}

注意：
- target 必须是上述可选目标中的一个
- reasoning 要结合当前局势"""


def _build_witch_prompt(
    obs: GameObservation,
    think_result: str,
    extra_info: str,
) -> str:
    """Build witch-specific prompt with save/poison logic."""
    return f"""你是 {obs.player_seat}号:{obs.player_name}，身份=女巫，第{obs.day}天 夜间行动。

=== 附加信息 ===
{extra_info}

=== 你的分析 ===
{think_result}

=== 用药规则 ===
- 一晚只能使用一瓶药（解药或毒药，不能同时使用）
- 如果决定救人，就不能毒人
- 如果决定毒人，就不能救人

输出 JSON 格式：
{{"reasoning": "你的理由", "save": true/false, "poison_target": "玩家名字或null"}}

注意：
- save=true 表示使用解药救人
- poison_target 填写要毒的玩家名字，null 表示不毒人
- 如果 save=true，poison_target 必须为 null"""


def build_badge_speech_prompt(
    obs: GameObservation,
    think_result: str,
) -> str:
    """Build the prompt for sheriff election speech."""
    return f"""你是 {obs.player_seat}号:{obs.player_name}，身份={obs.player_role}，第{obs.day}天 警徽竞选发言。

=== 你的分析 ===
{think_result}

现在请你竞选警长，发表竞选宣言。
要求：
1. 用 2-3 句话表达
2. 说明你为什么要当警长
3. 给出你的初步判断或带队方向
4. 语气自然，有说服力
5. 不要输出 JSON，直接输出发言

直接输出你的竞选发言："""
