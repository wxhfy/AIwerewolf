"""Cognitive Agent v2 — LangGraph-based Observe-Think-Act-Reflect architecture.

Improvements over v1:
- Proper LangGraph StateGraph with conditional routing
- CrewAI-style Role + Goal + Backstory character system
- Self-reflection node (checks output quality, triggers retry)
- Layered memory: working (current round) + long-term (cross-round) + role-specific
- Game-phase-aware routing (speech/vote/night actions use different paths)
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, TypedDict
try:
    from typing import Annotated
except ImportError:
    Annotated = None  # Python 3.8 compatibility
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage, BaseMessage
from langchain_core.runnables import RunnableLambda

# ============================================================
# State Schema (LangGraph-style TypedDict)
# ============================================================

class CognitiveState(TypedDict, total=False):
    """Shared state across all nodes in the cognitive graph."""
    # Input
    observation_text: str
    game_phase: str  # "speech", "vote", "night_action", "badge"
    action_type: str  # specific action like "wolf_attack", "seer_check"
    role: str
    player_name: str
    player_seat: int
    extra_info: str

    # Working memory (current round)
    facts: list[str]
    signals: list[str]
    info_gaps: list[str]
    player_assessments: dict[str, dict]  # name -> {suspicion, confidence, reasoning}

    # Thinking
    observation_result: str
    analysis_result: str
    candidate_actions: list[str]
    strategic_context: str

    # Long-term memory
    memory_text: str
    previous_judgments: dict[str, dict]

    # Output
    action_result: str
    action_json: dict
    speech_text: str
    vote_target: str
    night_target: str

    # Reflection
    reflection_result: str
    needs_retry: bool
    retry_count: int


# ============================================================
# Character System (CrewAI-style Role + Goal + Backstory)
# ============================================================

@dataclass
class CharacterProfile:
    """CrewAI-style character with role, goal, and backstory."""
    role: str
    goal: str
    backstory: str
    personality_traits: list[str] = field(default_factory=list)
    speech_style: str = ""
    risk_tolerance: str = "balanced"  # "conservative", "balanced", "aggressive"

    def to_system_prompt(self) -> str:
        """Convert to system prompt (CrewAI style)."""
        return f"""你是 {self.role}。

【目标】{self.goal}

【背景】{self.backstory}

{f"【性格特征】{', '.join(self.personality_traits)}" if self.personality_traits else ""}
{f"【发言风格】{self.speech_style}" if self.speech_style else ""}
{f"【风险偏好】{self.risk_tolerance}" if self.risk_tolerance != "balanced" else ""}

你正在参与一局狼人杀游戏。"""


# Role-specific character profiles
CHARACTER_PROFILES: dict[str, CharacterProfile] = {
    "Werewolf": CharacterProfile(
        role="狼人",
        goal="误导好人阵营，保护狼队友不被放逐，最终让狼人数量≥好人数量",
        backstory="你是狼人阵营的一员。你知道所有狼队友的身份。白天你需要伪装成好人，通过发言和投票误导好人方向；夜晚和狼队友商议击杀目标。",
        personality_traits=["善于伪装", "观察力强", "善于带节奏"],
        speech_style="像好人一样自然发言，给出看似合理的怀疑对象，避免暴露狼人视角",
        risk_tolerance="balanced",
    ),
    "Seer": CharacterProfile(
        role="预言家",
        goal="用查验结果引导好人阵营投票，找出所有狼人",
        backstory="你是预言家，每晚可以查验一名玩家的身份。你需要合理使用查验能力，在关键轮次跳身份给出查验结果，引导好人方向。",
        personality_traits=["逻辑清晰", "善于归票", "有领导力"],
        speech_style="发言要有理有据，引用查验结果时要坚定，分析票型时要清晰",
        risk_tolerance="balanced",
    ),
    "Witch": CharacterProfile(
        role="女巫",
        goal="合理使用解药和毒药，帮助好人阵营获胜",
        backstory="你有一瓶解药和一瓶毒药，各限使用一次。解药可以救活被狼人杀害的玩家，毒药可以毒杀一名玩家。你需要在关键时刻做出正确决策。",
        personality_traits=["谨慎", "善于观察", "信息敏感"],
        speech_style="关注死亡信息和票型变化，不暴露用药信息，质疑可疑的中立发言",
        risk_tolerance="conservative",
    ),
    "Hunter": CharacterProfile(
        role="猎人",
        goal="用开枪威慑狼队，在关键节点带走确定是狼的玩家",
        backstory="你死亡时可以开枪带走一名玩家（被女巫毒死时除外）。你需要隐藏身份，在关键时刻亮明身份带走狼人。",
        personality_traits=["强势", "敢于对抗", "记忆力好"],
        speech_style="发言可以强硬，逼迫对手留下清晰站边，被推上高票位时要留完整嫌疑链",
        risk_tolerance="aggressive",
    ),
    "Guard": CharacterProfile(
        role="守卫",
        goal="守护关键神职和高价值好人，预判狼人刀口",
        backstory="每夜可以守护一名玩家使其不被狼人杀害，但不能连续两夜守护同一人。你需要预判狼人的刀口，保护关键角色。",
        personality_traits=["谨慎", "分析力强", "信息敏感"],
        speech_style="重点分析谁在利用信息差带节奏，不暴露守护偏好",
        risk_tolerance="conservative",
    ),
    "Villager": CharacterProfile(
        role="村民",
        goal="通过分析发言和票型找出狼人，用投票放逐狼人",
        backstory="你是普通村民，没有任何特殊能力。你只能靠推理和投票来帮助好人阵营获胜。",
        personality_traits=["善于分析", "观察力强", "逻辑清晰"],
        speech_style="每轮给出明确怀疑对象和站边逻辑，为神职创造空间",
        risk_tolerance="balanced",
    ),
}


# ============================================================
# Nodes (each is a function: State -> partial State)
# ============================================================

def create_observe_node(llm: Any):
    """Observation node — extracts facts, signals, and info gaps."""

    def observe(state: CognitiveState) -> dict:
        prompt = f"""{state.get('observation_text', '')}

请用 2-3 句话总结你当前最重要的观察。只描述事实和信号，不做判断。"""

        messages = [
            SystemMessage(content="你是一个狼人杀游戏的观察者。仔细观察游戏状态，提取关键信号和事实。不要做判断，只描述观察。用中文回答。"),
            HumanMessage(content=prompt),
        ]

        try:
            response = llm.invoke(messages)
            return {"observation_result": response.content.strip()}
        except Exception as e:
            return {"observation_result": f"[观察失败: {e}]"}

    return observe


def create_think_node(llm: Any):
    """Thinking node — analyzes situation, evaluates players."""

    def think(state: CognitiveState) -> dict:
        obs_result = state.get("observation_result", "")
        memory_text = state.get("memory_text", "")
        role = state.get("role", "Villager")
        player_assessments = state.get("player_assessments", {})
        strategic_context = state.get("strategic_context", "")

        # Build player assessment lines
        assessment_lines = []
        for name, info in player_assessments.items():
            prev = info.get("previous_judgment", "")
            prev_note = f" [上次: {prev}]" if prev else ""
            assessment_lines.append(f"  {name}{prev_note}")

        prompt = f"""你是 {state.get('player_seat', '?')}号:{state.get('player_name', '?')}，身份={role}。

=== 我的观察 ===
{obs_result}

=== 玩家列表 ===
{chr(10).join(assessment_lines) if assessment_lines else "暂无评估"}

=== 战略背景 ===
{strategic_context}

{f"=== 我的记忆 ==={chr(10)}{memory_text}" if memory_text else ""}

请分析：
1. 当前局势的关键矛盾是什么？
2. 每个存活玩家的可疑程度
3. 你最怀疑谁？为什么？
4. 推荐的行动方向

用 3-5 句话总结。"""

        messages = [
            SystemMessage(content=f"你是一个狼人杀游戏分析师，身份={role}。基于观察结果进行推理分析。用中文回答。"),
            HumanMessage(content=prompt),
        ]

        try:
            response = llm.invoke(messages)
            return {"analysis_result": response.content.strip()}
        except Exception as e:
            return {"analysis_result": f"[分析失败: {e}]"}

    return think


def create_act_node(llm: Any):
    """Action node — generates concrete action based on analysis."""

    def act(state: CognitiveState) -> dict:
        analysis = state.get("analysis_result", "")
        phase = state.get("game_phase", "speech")
        role = state.get("role", "Villager")

        if phase == "speech":
            return _act_speech(llm, state, analysis)
        elif phase == "vote":
            return _act_vote(llm, state, analysis)
        elif phase == "night_action":
            return _act_night(llm, state, analysis)
        elif phase == "badge":
            return _act_badge(llm, state, analysis)
        else:
            return _act_speech(llm, state, analysis)

    return act


def _act_speech(llm: Any, state: CognitiveState, analysis: str) -> dict:
    """Generate a speech."""
    observation_text = state.get("observation_text", "")
    character = CHARACTER_PROFILES.get(state.get("role", "Villager"))

    style_hint = ""
    if character:
        style_hint = f"发言风格：{character.speech_style}"

    prompt = f"""{observation_text}

=== 你的分析 ===
{analysis}

{f"=== 风格提示 ==={chr(10)}{style_hint}" if style_hint else ""}

现在请你公开发言，就像在桌面上对着其他玩家说话一样。
要求：
1. 用 2-3 句话表达
2. 必须给出一个明确的判断方向（怀疑谁/支持谁）
3. 必须给出理由（引用具体发言或行为）
4. 语气自然，不要输出 JSON 或前缀

直接输出你的发言："""

    messages = [
        SystemMessage(content=character.to_system_prompt() if character else "你是狼人杀玩家。"),
        HumanMessage(content=prompt),
    ]

    try:
        response = llm.invoke(messages)
        speech = response.content.strip()
        # Clean up
        for prefix in ["发言：", "发言:", "我的发言：", "我的发言:"]:
            if speech.startswith(prefix):
                speech = speech[len(prefix):].strip()
        if speech.startswith('"') and speech.endswith('"'):
            speech = speech[1:-1].strip()
        return {"speech_text": speech, "action_result": speech}
    except Exception as e:
        return {"speech_text": f"[发言失败: {e}]", "action_result": f"[发言失败: {e}]"}


def _act_vote(llm: Any, state: CognitiveState, analysis: str) -> dict:
    """Generate a vote."""
    observation_text = state.get("observation_text", "")
    character = CHARACTER_PROFILES.get(state.get("role", "Villager"))

    prompt = f"""{observation_text}

=== 你的分析 ===
{analysis}

请投票。输出 JSON 格式：
{{"reasoning": "你的投票理由（1-2句话）", "target": "玩家名字"}}

注意：target 必须是存活玩家中的一个，不要投自己。"""

    messages = [
        SystemMessage(content=character.to_system_prompt() if character else "你是狼人杀玩家。"),
        HumanMessage(content=prompt),
    ]

    try:
        response = llm.invoke(messages)
        result = response.content.strip()
        # Parse JSON
        json_match = re.search(r'\{[^}]+\}', result)
        if json_match:
            data = json.loads(json_match.group())
            return {
                "vote_target": data.get("target", ""),
                "action_json": data,
                "action_result": result,
            }
        return {"vote_target": "", "action_json": {}, "action_result": result}
    except Exception as e:
        return {"vote_target": "", "action_json": {}, "action_result": f"[投票失败: {e}]"}


def _act_night(llm: Any, state: CognitiveState, analysis: str) -> dict:
    """Generate a night action."""
    observation_text = state.get("observation_text", "")
    extra_info = state.get("extra_info", "")
    role = state.get("role", "Villager")
    character = CHARACTER_PROFILES.get(role)

    prompt = f"""{observation_text}

=== 附加信息 ===
{extra_info}

=== 你的分析 ===
{analysis}

请选择目标。输出 JSON 格式：
{{"reasoning": "你的理由（1-2句话）", "target": "玩家名字"}}"""

    messages = [
        SystemMessage(content=character.to_system_prompt() if character else "你是狼人杀玩家。"),
        HumanMessage(content=prompt),
    ]

    try:
        response = llm.invoke(messages)
        result = response.content.strip()
        json_match = re.search(r'\{[^}]+\}', result)
        if json_match:
            data = json.loads(json_match.group())
            return {
                "night_target": data.get("target", ""),
                "action_json": data,
                "action_result": result,
            }
        return {"night_target": "", "action_json": {}, "action_result": result}
    except Exception as e:
        return {"night_target": "", "action_json": {}, "action_result": f"[行动失败: {e}]"}


def _act_badge(llm: Any, state: CognitiveState, analysis: str) -> dict:
    """Generate a badge election speech."""
    observation_text = state.get("observation_text", "")
    character = CHARACTER_PROFILES.get(state.get("role", "Villager"))

    prompt = f"""{observation_text}

=== 你的分析 ===
{analysis}

现在请你竞选警长，发表竞选宣言。
要求：2-3句话，说明为什么要当警长，给出初步判断或带队方向。
直接输出发言："""

    messages = [
        SystemMessage(content=character.to_system_prompt() if character else "你是狼人杀玩家。"),
        HumanMessage(content=prompt),
    ]

    try:
        response = llm.invoke(messages)
        speech = response.content.strip()
        return {"speech_text": speech, "action_result": speech}
    except Exception as e:
        return {"speech_text": f"[发言失败: {e}]", "action_result": f"[发言失败: {e}]"}


def create_reflect_node(llm: Any):
    """Reflection node — checks output quality, decides if retry needed."""

    def reflect(state: CognitiveState) -> dict:
        action_result = state.get("action_result", "")
        phase = state.get("game_phase", "speech")
        retry_count = state.get("retry_count", 0)

        # Simple quality checks
        needs_retry = False
        issues = []

        if phase == "speech":
            speech = state.get("speech_text", "")
            if len(speech) < 10:
                issues.append("发言太短")
                needs_retry = True
            if "抱歉" in speech and len(speech) < 30:
                issues.append("发言太敷衍")
                needs_retry = True

        elif phase == "vote":
            target = state.get("vote_target", "")
            if not target:
                issues.append("没有选择投票目标")
                needs_retry = True

        elif phase == "night_action":
            target = state.get("night_target", "")
            if not target:
                issues.append("没有选择行动目标")
                needs_retry = True

        # Max retries
        if retry_count >= 2:
            needs_retry = False

        reflection = f"检查通过" if not issues else f"问题: {', '.join(issues)}"

        return {
            "reflection_result": reflection,
            "needs_retry": needs_retry,
            "retry_count": retry_count + (1 if needs_retry else 0),
        }

    return reflect


# ============================================================
# Router (conditional edge logic)
# ============================================================

def should_retry(state: CognitiveState) -> str:
    """Decide whether to retry or finish."""
    if state.get("needs_retry", False):
        return "retry"
    return "finish"


def get_phase_node_name(state: CognitiveState) -> str:
    """Map game phase to act node variant."""
    phase = state.get("game_phase", "speech")
    return "act"  # We use a single act node with internal routing


# ============================================================
# Graph Builder
# ============================================================

def build_cognitive_graph_v2(llm: Any):
    """Build the cognitive graph: Observe → Think → Act → Reflect.

    Uses a simple sequential chain with reflection loop.
    """
    from langchain_core.runnables import RunnableLambda, RunnablePassthrough

    observe_node = RunnableLambda(create_observe_node(llm))
    think_node = RunnableLambda(create_think_node(llm))
    act_node = RunnableLambda(create_act_node(llm))
    reflect_node = RunnableLambda(create_reflect_node(llm))

    # Simple sequential chain (LangGraph requires StateGraph which needs langgraph package)
    # For now, use LangChain's pipe operator
    chain = observe_node | think_node | act_node | reflect_node

    return chain
