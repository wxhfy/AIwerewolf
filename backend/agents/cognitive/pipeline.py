"""Cognitive pipeline — Observe → Think → Act with full LLMAgent-quality prompts.

Upgraded three-stage pipeline:
  1. Observe: Rich game context + signal extraction
  2. Think: Memory + humanization + strategy + bias → analysis
  3. Act: Wolfcha-style speech / vote / night action

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
import os
from typing import Any, Dict, List, Optional

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
    build_game_context,
    build_strategy_bias_block,
    format_playbook_for_prompt,
)
from backend.agents.cognitive.retrieval import retrieve_strategies, format_strategies_for_prompt


class Pipeline:
    """Stateless cognitive pipeline (upgraded with LLMAgent-quality prompts).

    Each invocation makes 3 LLM calls:
    1. Observe: extract key signals (no judgments)
    2. Think: analyze situation, evaluate players
    3. Act: generate concrete action

    The pipeline is STATELESS — all state lives in Memory and Observation.
    """

    def __init__(
        self,
        llm: Runnable,
        system_prompt: str,
        strategy_bias: Optional[Dict[str, List[str]]] = None,
        persona_mbti: str = "",
        persona_style: str = "",
    ):
        self._llm = llm
        self._system_prompt = system_prompt
        self._strategy_bias = strategy_bias or {}
        self._persona_mbti = persona_mbti
        self._persona_style = persona_style

    # ---- LLM call wrapper with retry ----

    def _call(
        self,
        system: str,
        user: str,
        max_tokens: int = 500,
        max_retries: int = 2,
    ) -> str:
        """Single LLM call with retry.

        On error, retries with slightly lower temperature behavior.
        """
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                resp = self._llm.invoke([
                    SystemMessage(content=system),
                    HumanMessage(content=user),
                ])
                content = resp.content.strip()
                # If we got a reasonable response, return it
                if content and len(content) > 10:
                    return content
                # Empty/short response: retry
                last_error = f"Short response: {content[:50]}"
            except Exception as e:
                last_error = str(e)

        # All retries failed
        if last_error:
            return f"[LLM Error after {max_retries + 1} attempts: {last_error}]"
        return "[LLM: no response]"

    # ---- Stage 1: Observe ----

    def observe(self, obs: Observation) -> str:
        """Stage 1: Extract key signals from observation.

        Uses rich game context + contradiction/voting pattern analysis.
        """
        prompt = build_observe_prompt(obs)
        return self._call(
            "你是狼人杀观察者。提取关键信号和事实，不做最终判断。用中文。",
            prompt,
            max_tokens=400,
        )

    # ---- Stage 2: Think (core analysis) ----

    def think(
        self,
        obs: Observation,
        memory: Memory,
        obs_result: str = "",
    ) -> str:
        """Stage 2: Analyze situation based on observation + memory + strategy.

        Injects: memory (with humanization), strategy retrieval results,
        strategy bias, and observation analysis.
        """
        # Strategy retrieval from knowledge base (with persona scope)
        strategies = retrieve_strategies(
            obs.player_role, obs.phase,
            situation=obs_result,
            persona_mbti=self._persona_mbti,
            persona_style=self._persona_style,
        )
        strategy_text = format_strategies_for_prompt(strategies)

        # Strategy bias (forced policy for A/B testing)
        bias_text = build_strategy_bias_block(self._strategy_bias, "talk")

        # Build think prompt with full context
        prompt = build_think_prompt(obs, memory, strategy_text, bias_text)
        return self._call(self._system_prompt, prompt, max_tokens=600)

    # ---- Stage 3a: Act — Speech ----

    def act_speech(
        self,
        obs: Observation,
        think_result: str,
        memory: Memory,
        is_first_speaker: bool = False,
        is_last_words: bool = False,
    ) -> str:
        """Stage 3a: Generate a speech — wolfcha-style multi-bubble output.

        Produces a JSON array of message bubbles.
        """
        prompt = build_speech_prompt(obs, think_result, memory, is_first_speaker, is_last_words)
        result = self._call(self._system_prompt, prompt, max_tokens=800)
        return result

    # ---- Stage 3b: Act — Vote ----

    def act_vote(self, obs: Observation, think_result: str) -> Dict[str, str]:
        """Stage 3b: Generate a vote. Returns {target, reasoning}."""
        prompt = build_vote_prompt(obs, think_result)
        result = self._call(self._system_prompt, prompt, max_tokens=300)
        return _parse_json_target(result)

    # ---- Stage 3c: Act — Night ----

    def act_night(self, obs: Observation, think_result: str, extra: str = "") -> Dict[str, str]:
        """Stage 3c: Generate a night action. Returns {target, reasoning}."""
        prompt = build_night_prompt(obs, think_result, extra)
        result = self._call(self._system_prompt, prompt, max_tokens=300)
        return _parse_json_target(result)

    # ---- Full pipeline runners ----

    def run_speech(
        self,
        obs: Observation,
        memory: Memory,
        is_first_speaker: bool = False,
        is_last_words: bool = False,
    ) -> str:
        """Full pipeline for speech: observe → think → act."""
        obs_result = self.observe(obs)
        think_result = self.think(obs, memory, obs_result)
        return self.act_speech(obs, think_result, memory, is_first_speaker, is_last_words)

    def run_vote(self, obs: Observation, memory: Memory) -> Dict[str, str]:
        """Full pipeline for vote: observe → think → act."""
        obs_result = self.observe(obs)
        think_result = self.think(obs, memory, obs_result)
        return self.act_vote(obs, think_result)

    def run_night(self, obs: Observation, memory: Memory, extra: str = "") -> Dict[str, str]:
        """Full pipeline for night action: observe → think → act."""
        obs_result = self.observe(obs)
        think_result = self.think(obs, memory, obs_result)
        return self.act_night(obs, think_result, extra)

    # ---- Direct call (for legacy compatibility) ----

    def direct_call(self, user_prompt: str, max_tokens: int = 500) -> str:
        """Single LLM call with system prompt. For special actions (shoot, boom, etc.)."""
        return self._call(self._system_prompt, user_prompt, max_tokens=max_tokens)


# ============================================================
# Helpers
# ============================================================

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


def _parse_json_array(text: str) -> List[str]:
    """Parse a JSON string array from LLM output. Returns list of strings."""
    try:
        # Try to extract JSON array
        m = re.search(r'\[.*?\]', text, re.DOTALL)
        if m:
            data = json.loads(m.group())
            if isinstance(data, list):
                return [str(item) for item in data if item]
        # If no array found, treat as single string
        return [text.strip()]
    except (json.JSONDecodeError, KeyError):
        # Fallback: split by quoted segments
        quoted = re.findall(r'"([^"]*)"', text)
        if quoted:
            return quoted
        return [text.strip()]
