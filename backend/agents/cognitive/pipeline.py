"""Cognitive pipeline — Agent Loop with tool-calling and self-termination.

Replaced the fixed 3-step Chain with an autonomous agent loop:
  Agent thinks → optionally calls tools → thinks more → self-terminates → Decision

Supports both:
  - AgentLoop (new default): LLM decides when to call tools, when to output
  - Legacy 3-step Chain: Observe → Think → Act (use_agent_loop=False)

Single Responsibility: orchestrate the LLM calls in the right order.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable

from backend.agents.cognitive.agent_loop import AgentLoop
from backend.agents.cognitive.memory import Memory
from backend.agents.cognitive.observe import Observation, observe, format_observation
from backend.agents.cognitive.prompts import (
    build_observe_prompt,
    build_think_prompt,
    build_speech_prompt,
    build_vote_prompt,
    build_night_prompt,
    build_system_prompt,
    build_game_context,
    build_strategy_bias_block,
    format_playbook_for_prompt,
)
from backend.agents.cognitive.retrieval import retrieve_strategies as retrieve_strategies_tfidf
from backend.agents.cognitive.retrieval import format_strategies_for_prompt
from backend.agents.cognitive.retrieval_prod import retrieve_strategies_prod


class Pipeline:
    """Cognitive pipeline with autonomous agent loop + legacy fallback.

    Each invocation of run_speech / run_vote / run_night executes an
    autonomous agent loop where the LLM decides whether to call tools
    (search_strategies, recall_memory, check_rules, analyze_votes) and
    when it has enough information to produce a final decision.

    Between-turn analysis caching: when vote() follows talk() in the same
    turn, the analysis from talk() is reused to skip redundant thinking.
    """

    def __init__(
        self,
        llm: Runnable,
        system_prompt: str,
        strategy_bias: Optional[Dict[str, List[str]]] = None,
        persona_mbti: str = "",
        persona_style: str = "",
        use_agent_loop: bool = True,
    ):
        self._llm = llm
        self._system_prompt = system_prompt
        self._strategy_bias = strategy_bias or {}
        self._persona_mbti = persona_mbti
        self._persona_style = persona_style
        self._use_agent_loop = use_agent_loop
        self._cached_analysis: str = ""

    # ================================================================
    # Public API (called by CognitiveAgent)
    # ================================================================

    def run_speech(
        self,
        obs: Observation,
        memory: Memory,
        is_first_speaker: bool = False,
        is_last_words: bool = False,
    ) -> str:
        """Generate speech via agent loop (or legacy chain)."""
        if self._use_agent_loop:
            return self._run_loop_speech(obs, memory, is_first_speaker, is_last_words)
        return self._run_legacy_speech(obs, memory, is_first_speaker, is_last_words)

    def run_vote(self, obs: Observation, memory: Memory) -> Dict[str, str]:
        """Generate vote via agent loop (or legacy chain)."""
        if self._use_agent_loop:
            return self._run_loop_vote(obs, memory)
        return self._run_legacy_vote(obs, memory)

    def run_night(self, obs: Observation, memory: Memory, extra: str = "") -> Dict[str, str]:
        """Generate night action via agent loop (or legacy chain)."""
        if self._use_agent_loop:
            return self._run_loop_night(obs, memory, extra)
        return self._run_legacy_night(obs, memory, extra)

    def direct_call(self, user_prompt: str, max_tokens: int = 500) -> str:
        """Single LLM call for special actions (shoot, boom, badge transfer)."""
        return self._call_legacy(self._system_prompt, user_prompt, max_tokens=max_tokens)

    # ================================================================
    # Agent Loop (new)
    # ================================================================

    def _run_loop_speech(
        self, obs: Observation, memory: Memory,
        is_first: bool, is_last: bool,
    ) -> str:
        extra_parts = []
        if is_first: extra_parts.append("你是本阶段第一个发言的人")
        if is_last: extra_parts.append("这是你的遗言")
        extra = "; ".join(extra_parts) if extra_parts else ""

        loop = AgentLoop(self._llm, self._system_prompt, "speech", self._strategy_bias)
        result = loop.run(obs, memory, extra_context=extra)
        speech = result.get("speech", "")
        self._cached_analysis = result.get("reasoning", "")
        return speech

    def _run_loop_vote(self, obs: Observation, memory: Memory) -> Dict[str, str]:
        loop = AgentLoop(self._llm, self._system_prompt, "vote", self._strategy_bias)
        result = loop.run(obs, memory, cached_analysis=self._cached_analysis)
        self._cached_analysis = ""
        return {"target": result.get("target", ""), "reasoning": result.get("reasoning", "")}

    def _run_loop_night(self, obs: Observation, memory: Memory, extra: str) -> Dict[str, str]:
        loop = AgentLoop(self._llm, self._system_prompt, "night", self._strategy_bias)
        result = loop.run(obs, memory, extra_context=extra)
        return {"target": result.get("target", ""), "reasoning": result.get("reasoning", "")}

    # ================================================================
    # Legacy 3-step Chain (fallback, use_agent_loop=False)
    # ================================================================

    def _run_legacy_speech(
        self, obs: Observation, memory: Memory,
        is_first: bool, is_last: bool,
    ) -> str:
        obs_result = self._legacy_observe(obs)
        think_result = self._legacy_think(obs, memory, obs_result)
        return self._legacy_act_speech(obs, think_result, memory, is_first, is_last)

    def _run_legacy_vote(self, obs: Observation, memory: Memory) -> Dict[str, str]:
        obs_result = self._legacy_observe(obs)
        think_result = self._legacy_think(obs, memory, obs_result)
        return self._legacy_act_vote(obs, think_result)

    def _run_legacy_night(self, obs: Observation, memory: Memory, extra: str) -> Dict[str, str]:
        obs_result = self._legacy_observe(obs)
        think_result = self._legacy_think(obs, memory, obs_result)
        return self._legacy_act_night(obs, think_result, extra)

    def _legacy_observe(self, obs: Observation) -> str:
        prompt = build_observe_prompt(obs)
        return self._call_legacy(
            "你是狼人杀观察者。提取关键信号和事实，不做最终判断。用中文。",
            prompt, max_tokens=400,
        )

    def _legacy_think(self, obs: Observation, memory: Memory, obs_result: str) -> str:
        strategies = retrieve_strategies_prod(obs.player_role, obs.phase, situation=obs_result, limit=3)
        if not strategies:
            strategies = retrieve_strategies_tfidf(
                obs.player_role, obs.phase, situation=obs_result,
                persona_mbti=self._persona_mbti, persona_style=self._persona_style,
            )
        strategy_text = format_strategies_for_prompt(strategies)
        bias_text = build_strategy_bias_block(self._strategy_bias, "talk")
        prompt = build_think_prompt(obs, memory, strategy_text, bias_text)
        return self._call_legacy(self._system_prompt, prompt, max_tokens=600)

    def _legacy_act_speech(
        self, obs: Observation, think_result: str, memory: Memory,
        is_first: bool, is_last: bool,
    ) -> str:
        prompt = build_speech_prompt(obs, think_result, memory, is_first, is_last)
        return self._call_legacy(self._system_prompt, prompt, max_tokens=800)

    def _legacy_act_vote(self, obs: Observation, think_result: str) -> Dict[str, str]:
        prompt = build_vote_prompt(obs, think_result)
        result = self._call_legacy(self._system_prompt, prompt, max_tokens=300)
        return _parse_json_target(result)

    def _legacy_act_night(self, obs: Observation, think_result: str, extra: str) -> Dict[str, str]:
        prompt = build_night_prompt(obs, think_result, extra)
        result = self._call_legacy(self._system_prompt, prompt, max_tokens=300)
        return _parse_json_target(result)

    def _call_legacy(
        self, system: str, user: str, max_tokens: int = 500, max_retries: int = 2,
    ) -> str:
        for attempt in range(max_retries + 1):
            try:
                resp = self._llm.invoke([
                    SystemMessage(content=system),
                    HumanMessage(content=user),
                ])
                content = resp.content.strip()
                if content and len(content) > 10:
                    return content
            except Exception:
                pass
        return "[LLM: no response]"


# ============================================================
# Helpers
# ============================================================

def parse_json_target(text: str) -> Dict[str, str]:
    try:
        m = re.search(r'\{[^}]+\}', text)
        if m:
            data = json.loads(m.group())
            return {"target": data.get("target", ""), "reasoning": data.get("reasoning", "")}
    except (json.JSONDecodeError, KeyError):
        pass
    return {"target": "", "reasoning": text[:100]}


def parse_json_array(text: str) -> List[str]:
    try:
        m = re.search(r'\[.*?\]', text, re.DOTALL)
        if m:
            data = json.loads(m.group())
            if isinstance(data, list):
                return [str(item) for item in data if item]
        return [text.strip()]
    except (json.JSONDecodeError, KeyError):
        quoted = re.findall(r'"([^"]*)"', text)
        if quoted:
            return quoted
        return [text.strip()]
