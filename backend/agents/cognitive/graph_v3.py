"""Cognitive Agent v3 — Pure LangChain StateGraph implementation.

No langgraph dependency. Implements the StateGraph pattern using
LangChain's Runnable protocol for maximum compatibility with Python 3.8.

Architecture: Observe → Think → Act → Reflect (with retry loop)

Key design decisions:
- Each node is a focused LLM call with a single responsibility
- State flows through nodes as a dict (TypedDict for type hints)
- Reflection node checks output quality and can trigger retry
- Character system (CrewAI-style) shapes agent personality
- Phase-aware routing: different actions use different prompts
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable, RunnableLambda, RunnablePassthrough


# ============================================================
# Character System (CrewAI-style Role + Goal + Backstory)
# ============================================================

@dataclass
class CharacterProfile:
    """CrewAI-style character with role, goal, and backstory."""
    role: str
    goal: str
    backstory: str
    personality_traits: List[str] = field(default_factory=list)
    speech_style: str = ""
    risk_tolerance: str = "balanced"

    def system_prompt(self) -> str:
        parts = [f"你是 {self.role}。", f"【目标】{self.goal}", f"【背景】{self.backstory}"]
        if self.personality_traits:
            parts.append(f"【性格】{', '.join(self.personality_traits)}")
        if self.speech_style:
            parts.append(f"【发言风格】{self.speech_style}")
        parts.append("你正在参与一局狼人杀游戏。请用中文回答。")
        return "\n".join(parts)


CHARACTERS: Dict[str, CharacterProfile] = {
    "Werewolf": CharacterProfile(
        role="狼人", goal="误导好人，保护狼队友，让狼人阵营获胜",
        backstory="你知道所有狼队友的身份。白天伪装好人，夜晚商议击杀。",
        personality_traits=["善于伪装", "观察力强"], speech_style="像好人一样自然发言",
    ),
    "Seer": CharacterProfile(
        role="预言家", goal="用查验结果引导好人投票，找出所有狼人",
        backstory="每晚查验一名玩家身份。在关键轮次跳身份报查验。",
        personality_traits=["逻辑清晰", "有领导力"], speech_style="有理有据，引用查验结果时要坚定",
    ),
    "Witch": CharacterProfile(
        role="女巫", goal="合理使用解药和毒药，帮助好人获胜",
        backstory="有解药和毒药各一瓶。解药救人，毒药杀人，一晚只能用一瓶。",
        personality_traits=["谨慎", "信息敏感"], speech_style="关注死亡信息，不暴露用药情况",
    ),
    "Hunter": CharacterProfile(
        role="猎人", goal="用开枪威慑狼队，关键节点带走狼人",
        backstory="死亡时可开枪带走一人（被毒死除外）。隐藏身份，关键时刻亮明。",
        personality_traits=["强势", "记忆力好"], speech_style="发言强硬，逼迫对手站边",
    ),
    "Guard": CharacterProfile(
        role="守卫", goal="守护关键神职，预判狼人刀口",
        backstory="每晚守护一人免受狼刀，不能连续两晚守同一人。",
        personality_traits=["谨慎", "分析力强"], speech_style="分析信息差，不暴露守护偏好",
    ),
    "Villager": CharacterProfile(
        role="村民", goal="通过分析发言和票型找出狼人",
        backstory="没有特殊能力，只能靠推理和投票帮助好人。",
        personality_traits=["善于分析"], speech_style="给出明确怀疑对象和站边逻辑",
    ),
}


# ============================================================
# State Schema
# ============================================================

class GameState(dict):
    """Typed state flowing through the cognitive graph."""
    # Input
    observation_text: str
    game_phase: str  # "speech", "vote", "night", "badge"
    role: str
    player_name: str
    player_seat: int
    extra_info: str

    # Intermediate
    observe_result: str
    think_result: str
    action_result: str

    # Output
    speech_text: str
    vote_target: str
    night_target: str
    action_json: dict

    # Reflection
    needs_retry: bool
    retry_count: int

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            return ""


# ============================================================
# Node Factories
# ============================================================

def make_observe_node(llm: Runnable) -> Callable:
    """Observation: extract facts, signals, info gaps. No judgments."""

    def node(state: GameState) -> GameState:
        obs_text = state.get("observation_text", "")
        prompt = f"""{obs_text}

请用 2-3 句话总结当前最重要的观察。只描述事实和信号，不做判断。"""

        try:
            resp = llm.invoke([
                SystemMessage(content="你是狼人杀观察者。提取关键信号和事实，不做判断。用中文。"),
                HumanMessage(content=prompt),
            ])
            state["observe_result"] = resp.content.strip()
        except Exception as e:
            state["observe_result"] = f"[观察失败: {e}]"
        return state

    return node


def make_think_node(llm: Runnable) -> Callable:
    """Thinking: analyze situation, evaluate players, consider strategy."""

    def node(state: GameState) -> GameState:
        obs = state.get("observe_result", "")
        memory = state.get("memory_text", "")
        role = state.get("role", "Villager")
        seat = state.get("player_seat", "?")
        name = state.get("player_name", "?")

        prompt = f"""你是 {seat}号:{name}，身份={role}。

=== 我的观察 ===
{obs}

{f"=== 我的记忆 ==={chr(10)}{memory}" if memory else ""}

请分析：
1. 当前局势的关键矛盾
2. 每个存活玩家的可疑程度
3. 你最怀疑谁？为什么？
4. 推荐的行动方向

用 3-5 句话总结。"""

        try:
            resp = llm.invoke([
                SystemMessage(content=f"你是狼人杀分析师，身份={role}。基于观察进行推理。用中文。"),
                HumanMessage(content=prompt),
            ])
            state["think_result"] = resp.content.strip()
        except Exception as e:
            state["think_result"] = f"[分析失败: {e}]"
        return state

    return node


def make_act_node(llm: Runnable) -> Callable:
    """Action: generate concrete action based on analysis."""

    def node(state: GameState) -> GameState:
        phase = state.get("game_phase", "speech")
        role = state.get("role", "Villager")
        character = CHARACTERS.get(role, CHARACTERS["Villager"])

        if phase == "speech":
            return _do_speech(llm, state, character)
        elif phase == "vote":
            return _do_vote(llm, state, character)
        elif phase == "night":
            return _do_night(llm, state, character)
        elif phase == "badge":
            return _do_badge(llm, state, character)
        else:
            return _do_speech(llm, state, character)

    return node


def _do_speech(llm: Runnable, state: GameState, char: CharacterProfile) -> GameState:
    obs_text = state.get("observation_text", "")
    think = state.get("think_result", "")

    prompt = f"""{obs_text}

=== 你的分析 ===
{think}

现在请你公开发言，像在桌面上对其他玩家说话。
要求：2-3句话，给出明确判断方向+理由，语气自然。
直接输出发言："""

    try:
        resp = llm.invoke([
            SystemMessage(content=char.system_prompt()),
            HumanMessage(content=prompt),
        ])
        speech = resp.content.strip()
        # Clean prefixes
        for p in ["发言：", "发言:", "我的发言："]:
            if speech.startswith(p):
                speech = speech[len(p):].strip()
        state["speech_text"] = speech
        state["action_result"] = speech
    except Exception as e:
        state["speech_text"] = f"[发言失败: {e}]"
        state["action_result"] = f"[发言失败: {e}]"
    return state


def _do_vote(llm: Runnable, state: GameState, char: CharacterProfile) -> GameState:
    obs_text = state.get("observation_text", "")
    think = state.get("think_result", "")

    prompt = f"""{obs_text}

=== 你的分析 ===
{think}

请投票。输出 JSON：
{{"reasoning": "理由（1-2句）", "target": "玩家名字"}}"""

    try:
        resp = llm.invoke([
            SystemMessage(content=char.system_prompt()),
            HumanMessage(content=prompt),
        ])
        result = resp.content.strip()
        m = re.search(r'\{[^}]+\}', result)
        if m:
            data = json.loads(m.group())
            state["vote_target"] = data.get("target", "")
            state["action_json"] = data
        state["action_result"] = result
    except Exception as e:
        state["action_result"] = f"[投票失败: {e}]"
    return state


def _do_night(llm: Runnable, state: GameState, char: CharacterProfile) -> GameState:
    obs_text = state.get("observation_text", "")
    think = state.get("think_result", "")
    extra = state.get("extra_info", "")

    prompt = f"""{obs_text}

{f"=== 附加信息 ==={chr(10)}{extra}" if extra else ""}

=== 你的分析 ===
{think}

请选择目标。输出 JSON：
{{"reasoning": "理由（1-2句）", "target": "玩家名字"}}"""

    try:
        resp = llm.invoke([
            SystemMessage(content=char.system_prompt()),
            HumanMessage(content=prompt),
        ])
        result = resp.content.strip()
        m = re.search(r'\{[^}]+\}', result)
        if m:
            data = json.loads(m.group())
            state["night_target"] = data.get("target", "")
            state["action_json"] = data
        state["action_result"] = result
    except Exception as e:
        state["action_result"] = f"[行动失败: {e}]"
    return state


def _do_badge(llm: Runnable, state: GameState, char: CharacterProfile) -> GameState:
    obs_text = state.get("observation_text", "")
    think = state.get("think_result", "")

    prompt = f"""{obs_text}

=== 你的分析 ===
{think}

竞选警长，2-3句话说明为什么要当警长+带队方向。直接输出："""

    try:
        resp = llm.invoke([
            SystemMessage(content=char.system_prompt()),
            HumanMessage(content=prompt),
        ])
        speech = resp.content.strip()
        state["speech_text"] = speech
        state["action_result"] = speech
    except Exception as e:
        state["speech_text"] = f"[发言失败: {e}]"
        state["action_result"] = f"[发言失败: {e}]"
    return state


def make_reflect_node() -> Callable:
    """Reflection: check output quality, decide if retry needed."""

    def node(state: GameState) -> GameState:
        phase = state.get("game_phase", "speech")
        retry = state.get("retry_count", 0)
        issues = []

        if phase == "speech":
            s = state.get("speech_text", "")
            if len(s) < 10:
                issues.append("发言太短")
        elif phase == "vote":
            if not state.get("vote_target"):
                issues.append("没有投票目标")
        elif phase == "night":
            if not state.get("night_target"):
                issues.append("没有行动目标")

        state["needs_retry"] = bool(issues) and retry < 2
        state["retry_count"] = retry + (1 if issues else 0)
        return state

    return node


# ============================================================
# Graph: Observe → Think → Act → Reflect
# ============================================================

class CognitiveGraph:
    """Stateless cognitive graph. Invoke with a GameState dict.

    Implements Observe → Think → Act → Reflect with retry loop.
    Each invocation makes 3-4 LLM calls.
    """

    def __init__(self, llm: Runnable):
        self.llm = llm
        self.observe = make_observe_node(llm)
        self.think = make_think_node(llm)
        self.act = make_act_node(llm)
        self.reflect = make_reflect_node()

    def invoke(self, state: GameState) -> GameState:
        """Run the full cognitive pipeline."""
        # Observe
        state = self.observe(state)

        # Think
        state = self.think(state)

        # Act
        state = self.act(state)

        # Reflect (may trigger retry)
        state = self.reflect(state)

        # Retry loop if needed
        while state.get("needs_retry", False):
            state = self.act(state)
            state = self.reflect(state)

        return state


# ============================================================
# Public API
# ============================================================

def build_cognitive_graph(llm: Runnable) -> CognitiveGraph:
    """Build and return a CognitiveGraph instance."""
    return CognitiveGraph(llm)
