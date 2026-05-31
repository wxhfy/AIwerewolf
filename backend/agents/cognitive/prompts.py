"""Prompt builder — constructs system and user prompts for each phase.

Single Responsibility: translate game state + character + memory into prompts.
No LLM calls, no game logic — pure string construction.

Depends on:
- Observation (from observe.py)
- Memory (from memory.py)
- Profile (from profiles.py)
"""

from __future__ import annotations

from typing import Optional

from backend.agents.cognitive.memory import Memory
from backend.agents.cognitive.observe import Observation, format_observation
from backend.agents.cognitive.profiles import Profile, get_profile


def build_system_prompt(role: str, profile: Optional[Profile] = None) -> str:
    """Build the system prompt (identity + strategy).

    This is built ONCE at agent initialization and reused for all LLM calls.
    """
    p = profile or get_profile(role)

    parts = [
        f"你是 {p.role}。",
        f"【目标】{p.goal}",
        f"【背景】{p.backstory}",
    ]

    if p.personality:
        parts.append(f"【性格】{', '.join(p.personality)}")
    if p.speech_style:
        parts.append(f"【发言风格】{p.speech_style}")
    if p.table_goal:
        parts.append(f"【桌面目标】{p.table_goal}")
    if p.pressure_style:
        parts.append(f"【被质疑时】{p.pressure_style}")
    if p.reveal_policy:
        parts.append(f"【身份暴露策略】{p.reveal_policy}")
    if p.wolf_disguise and role in ("Werewolf", "WhiteWolfKing"):
        parts.append(f"【伪装方式】{p.wolf_disguise}")

    parts.append("\n你正在参与一局狼人杀游戏。请用中文回答。")
    parts.append("重要：你的推理过程是内部思考，不要在发言中暴露。")

    return "\n".join(parts)


def build_observe_prompt(obs: Observation) -> str:
    """Build prompt for the observation layer."""
    obs_text = format_observation(obs)
    return f"""{obs_text}

请用 2-3 句话总结当前最重要的观察。只描述事实和信号，不做判断。"""


def build_think_prompt(obs: Observation, memory: Memory) -> str:
    """Build prompt for the thinking layer."""
    obs_text = format_observation(obs)
    memory_text = memory.format_for_prompt()

    parts = [
        f"你是 {obs.player_seat}号:{obs.player_name}，身份={obs.player_role}。",
        "",
        "=== 观察 ===",
        obs_text,
    ]

    if memory_text:
        parts.extend(["", "=== 记忆 ===", memory_text])

    parts.extend([
        "",
        "请分析：",
        "1. 当前局势的关键矛盾",
        "2. 每个存活玩家的可疑程度",
        "3. 你最怀疑谁？为什么？",
        "4. 推荐的行动方向",
        "",
        "用 3-5 句话总结。",
    ])

    return "\n".join(parts)


def build_speech_prompt(obs: Observation, think_result: str) -> str:
    """Build prompt for generating a speech."""
    obs_text = format_observation(obs)

    return f"""{obs_text}

=== 分析 ===
{think_result}

现在请你公开发言，像在桌面上对其他玩家说话。
要求：2-3句话，给出明确判断方向+理由，语气自然。
直接输出发言："""


def build_vote_prompt(obs: Observation, think_result: str) -> str:
    """Build prompt for generating a vote."""
    obs_text = format_observation(obs)

    return f"""{obs_text}

=== 分析 ===
{think_result}

请投票。输出 JSON：
{{"reasoning": "理由（1-2句）", "target": "玩家名字"}}"""


def build_night_prompt(obs: Observation, think_result: str, extra: str = "") -> str:
    """Build prompt for a night action."""
    obs_text = format_observation(obs)

    parts = [obs_text]
    if extra:
        parts.extend(["", f"=== 附加信息 ===\n{extra}"])
    parts.extend([
        "",
        f"=== 分析 ===\n{think_result}",
        "",
        "请选择目标。输出 JSON：",
        '{{"reasoning": "理由（1-2句）", "target": "玩家名字"}}',
    ])

    return "\n".join(parts)
