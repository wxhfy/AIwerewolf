"""LangGraph workflow for the cognitive agent.

Defines the Observe → Think → Act state machine using a simple
sequential flow. Each step calls the LLM with a focused prompt,
and the output feeds into the next step.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda


class CognitiveState:
    """State passed through the cognitive graph."""

    def __init__(self):
        self.observation_text: str = ""
        self.think_result: str = ""
        self.action_result: str = ""
        self.memory_text: str = ""
        self.strategy_hint: str = ""
        self.style_hint: str = ""
        self.action_type: str = ""  # "speech", "vote", "night_action", etc.
        self.extra_info: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_text": self.observation_text,
            "think_result": self.think_result,
            "action_result": self.action_result,
            "memory_text": self.memory_text,
            "strategy_hint": self.strategy_hint,
            "style_hint": self.style_hint,
            "action_type": self.action_type,
            "extra_info": self.extra_info,
        }


def build_observe_node(llm: Any):
    """Build the observation node that calls the LLM."""

    def observe(state: dict[str, Any]) -> dict[str, Any]:
        prompt = state["observation_text"]
        messages = [
            SystemMessage(content="你是一个狼人杀游戏的观察者。仔细观察游戏状态，提取关键信号和事实。不要做判断，只描述观察。"),
            HumanMessage(content=prompt),
        ]
        response = llm.invoke(messages)
        return {**state, "observation_result": response.content}

    return RunnableLambda(observe)


def build_think_node(llm: Any):
    """Build the thinking node that calls the LLM."""

    def think(state: dict[str, Any]) -> dict[str, Any]:
        prompt = state["think_prompt"]
        messages = [
            SystemMessage(content="你是一个狼人杀游戏的分析师。基于观察结果，分析局势，评估每个玩家，给出判断和推荐行动。"),
            HumanMessage(content=prompt),
        ]
        response = llm.invoke(messages)
        return {**state, "think_result": response.content}

    return RunnableLambda(think)


def build_act_node(llm: Any):
    """Build the action node that calls the LLM."""

    def act(state: dict[str, Any]) -> dict[str, Any]:
        prompt = state["act_prompt"]
        messages = [
            SystemMessage(content="你是一个狼人杀游戏玩家。基于分析结果，生成你的具体行动（发言/投票/夜间行动）。"),
            HumanMessage(content=prompt),
        ]
        response = llm.invoke(messages)
        return {**state, "action_result": response.content}

    return RunnableLambda(act)


def build_cognitive_graph(llm: Any):
    """Build the full cognitive graph: Observe → Think → Act.

    This returns a simple sequential chain that can be invoked with
    a state dict containing the prompts for each step.
    """
    observe_node = build_observe_node(llm)
    think_node = build_think_node(llm)
    act_node = build_act_node(llm)

    # Simple sequential chain
    chain = observe_node | think_node | act_node

    return chain
