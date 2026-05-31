"""Observation layer — extracts key signals from game state.

The observation layer doesn't make judgments. It identifies:
1. What facts are established
2. What signals are noteworthy
3. What information is missing
"""

from __future__ import annotations

from backend.agents.cognitive.state import GameObservation


def build_observe_prompt(obs: GameObservation) -> str:
    """Build the observation prompt for the LLM.

    The LLM should output structured observations without making judgments.
    This forces the agent to "see before judging".
    """

    # Build fact sheet
    fact_lines = _build_fact_sheet(obs)

    # Build signal analysis
    signal_lines = _build_signal_analysis(obs)

    # Build information gaps
    gap_lines = _build_info_gaps(obs)

    return f"""你是 {obs.player_seat}号:{obs.player_name}，身份={obs.player_role}，第{obs.day}天 {obs.phase}阶段。

=== 已确认事实 ===
{chr(10).join(fact_lines)}

=== 值得注意的信号 ===
{chr(10).join(signal_lines)}

=== 信息缺口（你不知道的）===
{chr(10).join(gap_lines)}

请用 2-3 句话总结你当前最重要的观察。不要做判断，只描述事实和信号。"""


def _build_fact_sheet(obs: GameObservation) -> list[str]:
    """Build a list of established facts."""
    lines = []

    # Deaths
    if obs.deaths:
        for d in obs.deaths:
            lines.append(f"- 第{d.day}天 {d.player_name}({d.seat}号) 死亡，死因: {d.cause}")

    # Sheriff
    if obs.sheriff_id:
        sheriff = next((p for p in obs.alive_players if p.player_id == obs.sheriff_id), None)
        if sheriff:
            lines.append(f"- 警长是 {sheriff.seat}号:{sheriff.name}")

    # Today's votes (if any)
    if obs.today_votes:
        vote_summary = []
        for v in obs.today_votes:
            vote_summary.append(f"{v.voter_name}->{v.target_name}")
        lines.append(f"- 今日投票: {', '.join(vote_summary)}")

    # Yesterday's votes
    if obs.yesterday_votes:
        vote_summary = []
        for v in obs.yesterday_votes:
            vote_summary.append(f"{v.voter_name}->{v.target_name}")
        lines.append(f"- 昨日投票: {', '.join(vote_summary)}")

    if not lines:
        lines.append("- 暂无确认事实")

    return lines


def _build_signal_analysis(obs: GameObservation) -> list[str]:
    """Analyze noteworthy signals from speeches and behavior."""
    lines = []

    # Check for role claims
    for speech in obs.today_speeches:
        content = speech.content
        if "预言家" in content or "查验" in content:
            lines.append(f"- {speech.player_name}({speech.seat}号) 提到了预言家/查验")
        if "女巫" in content or "解药" in content or "毒药" in content:
            lines.append(f"- {speech.player_name}({speech.seat}号) 提到了女巫/药水")
        if "猎人" in content or "开枪" in content:
            lines.append(f"- {speech.player_name}({speech.seat}号) 提到了猎人/开枪")

    # Check for accusations
    for speech in obs.today_speeches:
        content = speech.content
        if "狼人" in content and ("一定是" in content or "肯定是" in content):
            lines.append(f"- {speech.player_name}({speech.seat}号) 做了确定性指控")

    # Check for contradictions (simple: same player said different things)
    player_speeches: dict[str, list[str]] = {}
    for speech in obs.today_speeches:
        if speech.player_id not in player_speeches:
            player_speeches[speech.player_id] = []
        player_speeches[speech.player_id].append(speech.content)

    for pid, speeches in player_speeches.items():
        if len(speeches) >= 2:
            # Simple contradiction check: if one speech says X is good, another says X is suspicious
            for i, s1 in enumerate(speeches):
                for s2 in speeches[i+1:]:
                    if ("好人" in s1 and "狼人" in s2) or ("狼人" in s1 and "好人" in s2):
                        player_info = next((p for p in obs.alive_players if p.player_id == pid), None)
                        if player_info:
                            lines.append(f"- {player_info.name}({player_info.seat}号) 发言存在矛盾")

    if not lines:
        lines.append("- 暂无特别信号")

    return lines


def _build_info_gaps(obs: GameObservation) -> list[str]:
    """Identify what the agent doesn't know."""
    lines = []

    if obs.player_role != "Seer":
        lines.append("- 你不知道任何玩家的真实身份")

    if obs.player_role == "Villager":
        lines.append("- 你没有任何私有信息")

    if obs.day == 1 and obs.phase == "DAY_SPEECH":
        lines.append("- 第一天信息极少，判断置信度低")

    # How many haven't spoken yet
    spoken_ids = {s.player_id for s in obs.today_speeches}
    unspoken = [p for p in obs.alive_players if p.player_id not in spoken_ids and p.player_id != obs.player_id]
    if unspoken:
        names = ", ".join(f"{p.seat}号:{p.name}" for p in unspoken[:3])
        lines.append(f"- 以下玩家尚未发言: {names}")

    if not lines:
        lines.append("- 信息相对充分")

    return lines
