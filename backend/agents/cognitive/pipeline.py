"""Cognitive pipeline — Observe → Think → Act with reflection.

Single Responsibility: orchestrate the LLM calls in the right order.
Each step is a pure function: (state, llm) → result.

The pipeline does NOT know about:
- Game engine internals
- Database
- Agent protocol
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable

from backend.agents.cognitive.memory import Memory
from backend.agents.cognitive.observe import Observation, observe, format_observation
from backend.agents.cognitive.prompts import (
    build_observe_prompt,
    build_think_prompt,
    build_speech_prompt,
    build_vote_prompt,
    build_night_prompt,
    build_system_prompt,
)


class Pipeline:
    """Stateless cognitive pipeline.

    Each invocation makes 3 LLM calls:
    1. Observe: extract key signals (no judgments)
    2. Think: analyze situation, evaluate players
    3. Act: generate concrete action

    The pipeline is STATELESS — all state lives in Memory and Observation.
    """

    def __init__(self, llm: Runnable, system_prompt: str):
        self._llm = llm
        self._system_prompt = system_prompt

    def _call(self, system: str, user: str) -> str:
        """Single LLM call."""
        try:
            resp = self._llm.invoke([
                SystemMessage(content=system),
                HumanMessage(content=user),
            ])
            return resp.content.strip()
        except Exception as e:
            return f"[LLM Error: {e}]"

    def observe(self, obs: Observation) -> str:
        """Stage 1: Extract key signals from observation."""
        prompt = build_observe_prompt(obs)
        return self._call(
            "你是狼人杀观察者。提取关键信号和事实，不做判断。用中文。",
            prompt,
        )

    def think(self, obs: Observation, memory: Memory) -> str:
        """Stage 2: Analyze situation based on observation + memory."""
        prompt = build_think_prompt(obs, memory)
        return self._call(self._system_prompt, prompt)

    def act_speech(self, obs: Observation, think_result: str) -> str:
        """Stage 3a: Generate a speech."""
        prompt = build_speech_prompt(obs, think_result)
        return self._call(self._system_prompt, prompt)

    def act_vote(self, obs: Observation, think_result: str) -> Dict[str, str]:
        """Stage 3b: Generate a vote. Returns {target, reasoning}."""
        prompt = build_vote_prompt(obs, think_result)
        result = self._call(self._system_prompt, prompt)
        return _parse_json_target(result)

    def act_night(self, obs: Observation, think_result: str, extra: str = "") -> Dict[str, str]:
        """Stage 3c: Generate a night action. Returns {target, reasoning}."""
        prompt = build_night_prompt(obs, think_result, extra)
        result = self._call(self._system_prompt, prompt)
        return _parse_json_target(result)

    def run_speech(self, obs: Observation, memory: Memory) -> str:
        """Full pipeline for speech: observe → think → act."""
        obs_result = self.observe(obs)
        think_result = self.think_with_context(obs, memory, obs_result)
        return self.act_speech(obs, think_result)

    def run_vote(self, obs: Observation, memory: Memory) -> Dict[str, str]:
        """Full pipeline for vote: observe → think → act."""
        obs_result = self.observe(obs)
        think_result = self.think_with_context(obs, memory, obs_result)
        return self.act_vote(obs, think_result)

    def run_night(self, obs: Observation, memory: Memory, extra: str = "") -> Dict[str, str]:
        """Full pipeline for night action: observe → think → act."""
        obs_result = self.observe(obs)
        think_result = self.think_with_context(obs, memory, obs_result)
        return self.act_night(obs, think_result, extra)

    def think_with_context(self, obs: Observation, memory: Memory, obs_result: str) -> str:
        """Think stage with pre-computed observation result."""
        memory_text = memory.format_for_prompt()
        parts = [
            f"你是 {obs.player_seat}号:{obs.player_name}，身份={obs.player_role}。",
            "",
            "=== 观察 ===",
            obs_result,
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
        return self._call(self._system_prompt, "\n".join(parts))


def _parse_json_target(text: str) -> Dict[str, str]:
    """Extract target and reasoning from JSON in LLM output."""
    try:
        m = re.search(r'\{[^}]+\}', text)
        if m:
            data = json.loads(m.group())
            return {
                "target": data.get("target", ""),
                "reasoning": data.get("reasoning", ""),
            }
    except (json.JSONDecodeError, KeyError):
        pass
    return {"target": "", "reasoning": text[:100]}
