"""Agent Loop — tool-calling cognitive loop with self-termination.

Replaces the fixed 3-step Chain (Observe→Think→Act) with an autonomous
agent loop where the LLM decides:
  - Whether to call tools (search_strategies, recall_memory, etc.)
  - In what order
  - When it has enough information → output Decision

Based on Anthropic's "Building Effective Agents" pattern:
  while not ready: think → maybe call tools → think again → decide

No LangGraph dependency — just a Python while-loop. Radical simplicity.

Supports native function calling via bind_tools when LLM supports it,
with text regex parsing as fallback.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.messages import ToolMessage
from langchain_core.runnables import Runnable

from backend.agents.cognitive import trace_keys
from backend.agents.cognitive.memory import Memory
from backend.agents.cognitive.observe import Observation
from backend.agents.cognitive.observe import format_observation
from backend.agents.cognitive.prompts import build_game_context
from backend.agents.cognitive.prompts import build_strategy_bias_block
from backend.agents.cognitive.prompts import get_role_anti_patterns
from backend.agents.cognitive.retrieval_prod import RetrievalPolicy
from backend.agents.cognitive.tools import create_tools

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS_BY_ACTION: dict[str, int] = {
    "speech": 1,
    "vote": 0,
    "night": 0,
}
MAX_FORMAT_REPAIR_ROUNDS = 1
MAX_EMPTY_RESPONSE_REPAIR_ROUNDS = 2
DECISION_TOOL_NAME = "submit_decision"
import threading as _threading

_STRATEGY_LOCK = _threading.Lock()
_TRACK_C_RETRIEVAL_CACHE: dict[tuple[str, str, str, str, str, str, int, float], tuple[float, list[dict[str, Any]]]] = {}
_LAST_RETRIEVED_STRATEGIES: dict = {}
_LAST_LOOP_TRACE: dict = {}


def get_last_loop_trace(player_id: str) -> dict:
    """Return the last agent-loop trace for a player, then clear it."""
    return _LAST_LOOP_TRACE.pop(player_id, {})


def _feature_enabled(env_var: str, default: bool = True) -> bool:
    """Check if a feature flag is enabled via environment variable."""
    val = os.getenv(env_var, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")


def _feature_value_from_config(config: dict[str, bool] | None, env_var: str, default: bool = True) -> bool:
    """Resolve a feature flag from agent config first, then environment."""
    if config and env_var in config:
        return bool(config[env_var])
    return _feature_enabled(env_var, default)


# JSON Schema parameter definitions for each tool (used by bind_tools)
_TOOL_PARAM_SCHEMAS: Dict[str, Dict] = {
    "search_strategies": {
        "type": "object",
        "properties": {
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "搜索关键词列表，使用精准的领域术语如「被查杀」「警徽流」「表水」",
            },
            "limit": {
                "type": "integer",
                "description": "返回结果数量上限，默认3",
            },
            "include_reflections": {
                "type": "boolean",
                "description": "是否包含对局反思文档",
            },
            "mode": {
                "type": "string",
                "enum": ["count", "overview", "content"],
                "description": "返回模式：count 只统计，overview 只看摘要，content 返回完整策略",
            },
            "use_regex": {
                "type": "boolean",
                "description": "是否将 keywords 作为 Python 正则表达式处理",
            },
            "retrieval_policy": {
                "type": "string",
                "enum": [policy.value for policy in RetrievalPolicy],
                "description": "检索策略范围；未传时使用 Agent 配置的默认策略",
            },
        },
        "required": ["keywords"],
    },
    "submit_decision": {
        "type": "object",
        "properties": {
            "speech": {
                "type": "string",
                "description": "发言动作的最终发言；非发言动作留空",
            },
            "target": {
                "type": "string",
                "description": "投票或夜间动作的最终目标，使用可见的玩家名或座位号；发言动作留空",
            },
            "reasoning": {
                "type": "string",
                "description": "简短说明做出该决策的依据",
            },
        },
        "required": ["reasoning"],
    },
    "recall_memory": {
        "type": "object",
        "properties": {
            "filter": {
                "type": "string",
                "enum": ["all", "judgments", "suspicious", "trusted", "recent_actions", "role_state"],
                "description": "记忆筛选类型",
            },
            "target_player": {
                "type": "string",
                "description": "指定玩家名，空字符串表示不筛选",
            },
        },
    },
    "check_rules": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "要查询的规则问题",
            },
        },
        "required": ["question"],
    },
    "set_strategic_intent": {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "description": "计划目标（简短描述，如 fake_claim_seer, frame_player_3）",
            },
            "target_phase": {
                "type": "string",
                "description": "执行阶段（DAY_SPEECH, DAY_VOTE, NIGHT_WOLF_ACTION, NIGHT_SEER_ACTION 等）",
            },
            "conditions": {
                "type": "string",
                "description": "分号分隔的前置条件，如 'no_other_seer_claim;still_alive'",
            },
            "fallback": {
                "type": "string",
                "description": "条件不满足时的备选方案",
            },
        },
        "required": ["objective", "target_phase"],
    },
    "analyze_votes": {
        "type": "object",
        "properties": {},
    },
}


_WOLF_ROLES_LOOP = {"Werewolf", "WhiteWolfKing", "BigBadWolf", "WolfCub", "AlphaWolf"}


def _derive_alignment(role: str) -> str:
    """Derive alignment from role name. Returns 'wolf' or 'village'."""
    if not role:
        return ""
    return "wolf" if role.strip() in _WOLF_ROLES_LOOP else "village"


def _target_candidate_players(obs: Observation | None) -> list[Any]:
    if obs is None:
        return []
    explicit_targets = list(getattr(obs, "legal_targets", None) or [])
    if explicit_targets:
        return explicit_targets

    phase = str(getattr(obs, "phase", "") or "").upper()
    current_player_id = str(getattr(obs, "player_id", "") or "")
    alive_players = list(getattr(obs, "alive", []) or [])
    if phase == "NIGHT_WOLF_ACTION":
        return [
            player
            for player in alive_players
            if str(getattr(player, "id", "") or "") != current_player_id
            and _derive_alignment(str(getattr(player, "role", "") or "")) != "wolf"
        ]
    if phase == "NIGHT_GUARD_ACTION":
        return alive_players
    return [player for player in alive_players if str(getattr(player, "id", "") or "") != current_player_id]


def _legal_target_labels(obs: Observation | None) -> list[str]:
    source_players = _target_candidate_players(obs)
    labels: list[str] = []
    seen: set[str] = set()
    for player in source_players:
        seat = str(getattr(player, "seat", "") or "").strip()
        name = str(getattr(player, "name", "") or "").strip()
        player_id = str(getattr(player, "id", "") or "").strip()
        candidates = []
        if seat:
            candidates.append(f"{seat}号")
        if seat and name:
            candidates.append(f"{seat}号:{name}")
        if name:
            candidates.append(name)
        if player_id:
            candidates.append(player_id)
        for candidate in candidates:
            if candidate and candidate not in seen:
                seen.add(candidate)
                labels.append(candidate)
    return labels


def _format_legal_target_instruction(obs: Observation | None) -> str:
    labels = _legal_target_labels(obs)
    if not labels:
        return ""
    return "- 本次合法目标仅限：" + "、".join(labels) + "\n"


class AgentLoop:
    """Autonomous tool-calling agent loop for AI Werewolf.

    Usage:
        loop = AgentLoop(llm, system_prompt, action_type="speech")
        result = loop.run(observation, memory, extra_context="is_first_speaker=true")
        # → {"speech": "...", "reasoning": "..."}
    """

    def __init__(
        self,
        llm: Runnable,
        system_prompt: str,
        action_type: str = "speech",
        strategy_bias: Optional[Dict[str, List[str]]] = None,
        temperature: Optional[float] = None,
        mbti: str = "",
        player_id: str = "",
        retrieval_policy: str = "",
        feature_flags: dict[str, bool] | None = None,
    ):
        self._llm = llm
        self._system_prompt = system_prompt
        self._action_type = action_type
        self._strategy_bias = strategy_bias or {}
        self._mbti = mbti
        self._player_id = player_id
        self._retrieval_policy = retrieval_policy
        self._feature_flags = dict(feature_flags or {})
        self._temperature = temperature
        self._accumulated_usage: Dict[str, int] = {}
        self._current_obs: Observation | None = None
        # Native function calling via llm.bind_tools().
        # DeepSeek models (dsv4flash provider) support OpenAI-compatible tool calling.
        # Set AGENT_USE_NATIVE_FC=0 to disable and fall back to text-mode parsing.
        import os as _os

        _native_fc_env = _os.getenv("AGENT_USE_NATIVE_FC", "").strip()
        _native_fc_disabled = _native_fc_env == "0" or _native_fc_env.lower() == "false"
        self._supports_bind_tools = hasattr(llm, "bind_tools") and not _native_fc_disabled

    # ================================================================
    # Run
    # ================================================================

    def run(
        self,
        obs: Observation,
        memory: Memory,
        extra_context: str = "",
        cached_analysis: str = "",
    ) -> Dict[str, str]:
        """Execute the agent loop and return a decision dict.

        Args:
            obs: Current observation (game state).
            memory: Agent's working memory.
            extra_context: Additional phase-specific info (e.g., "is_first_speaker=true").
            cached_analysis: Reusable analysis from a previous call in the same turn.

        Returns:
            Dict with keys depending on action_type:
              speech: {"speech": str, "reasoning": str}
              vote:   {"target": str, "reasoning": str}
              night:  {"target": str, "reasoning": str}
        """
        self._current_obs = obs
        all_tools = create_tools(
            obs,
            memory,
            mbti=self._mbti,
            alignment=_derive_alignment(obs.player_role),
            player_id=self._player_id,
            default_retrieval_policy=self._retrieval_policy,
        )
        max_tool_rounds = self._max_tool_rounds(cached_analysis)
        tools = self._select_tools(all_tools, obs) if max_tool_rounds > 0 else {}
        info_tool_schemas = self._tools_to_bind_schemas(tools) if self._supports_bind_tools and tools else []
        decision_schema = self._decision_tool_schema(obs)
        context = []  # list of messages for the conversation
        tool_trace: list[dict] = []  # track tool calls for auditing

        # ── Prompt Cache Optimisation ──
        # Split into static SystemMessage (cacheable) + dynamic HumanMessage.
        # DeepSeek hashes the SystemMessage to decide cache hits — keeping it
        # identical across calls lets the API skip re-processing 60-80% of
        # prompt tokens. This matches what Anthropic SDK / Claude Code does.
        static_system = self._build_static_system_text(obs, tools)
        dynamic_context = self._build_dynamic_context(obs, memory, extra_context, cached_analysis)
        context.append(SystemMessage(content=static_system))
        context.append(HumanMessage(content=dynamic_context))

        call_count = 0
        tool_rounds_used = 0
        repair_rounds_used = 0
        empty_response_repairs_used = 0
        last_response_preview = ""
        self._accumulated_usage = {}
        active_schemas: list[dict] = []
        force_tool_name: str | None = None
        text_repair_mode = False
        if self._supports_bind_tools:
            active_schemas = info_tool_schemas + [decision_schema]
            if not info_tool_schemas:
                force_tool_name = DECISION_TOOL_NAME
        elif tools:
            active_schemas = info_tool_schemas

        while True:
            call_count += 1
            response = self._call_llm(context, active_schemas or None, force_tool_name=force_tool_name)
            response_text = response.content if hasattr(response, "content") else str(response)
            last_response_preview = response_text[:500].replace("\n", "\\n")

            # Detect native tool calls for proper ToolMessage handling
            is_native = hasattr(response, "tool_calls") and response.tool_calls

            decision_error = ""
            if self._supports_bind_tools and not text_repair_mode:
                decision, decision_error = self._parse_submit_decision(response)
                if decision:
                    logger.info("Call %s: submit_decision found (%s)", call_count, list(decision.keys()))
                    self._inject_tool_trace(decision, tool_trace, obs)
                    return decision

            # Try to parse tool calls (native → text fallback)
            tool_results = self._parse_tool_calls(response, tools)
            if tool_results and tool_rounds_used < max_tool_rounds:
                tool_rounds_used += 1
                logger.info(
                    f"Call {call_count}: {len(tool_results)} info tool call(s) "
                    f"({'native' if is_native else 'text'}) - "
                    f"{', '.join(t.split(chr(10))[0][:80] for t in tool_results)}"
                )

                # Record tool trace for auditing
                tool_names = self._extract_tool_names(response, is_native, allowed_tool_names=set(tools))
                tool_keywords = self._extract_tool_keywords(response, is_native, allowed_tool_names=set(tools))
                for idx, tr in enumerate(tool_results):
                    tname = tool_names[idx] if idx < len(tool_names) else "unknown"
                    # Extract doc_ids from formatted strategy output
                    doc_ids = re.findall(r"\[([\w\-]+)\s+score=", tr) if tname == "search_strategies" else []
                    tool_trace.append(
                        {
                            "iteration": tool_rounds_used,
                            "tool": tname,
                            "keywords": tool_keywords.get(tname, []),
                            "doc_ids": doc_ids,
                            "timestamp": time.time(),
                            "result_summary": tr[:200],
                            "policy": self._retrieval_policy,
                            "mbti": self._mbti,
                            "role": obs.player_role,
                        }
                    )
                    # Populate _LAST_RETRIEVED_STRATEGIES for search_strategies tool calls
                    # so _record_strategy_usage() can track which docs were actually retrieved.
                    # Merge with auto-injected entries (if any) rather than overwriting.
                    if tname == "search_strategies" and doc_ids:
                        player_id = str(getattr(obs, "player_id", "") or "")
                        with _STRATEGY_LOCK:
                            existing = _LAST_RETRIEVED_STRATEGIES.get(player_id, [])
                            existing_ids = {s.get("doc_id", "") for s in existing}
                            for d in doc_ids:
                                if d and d not in existing_ids:
                                    existing.append({"doc_id": d})
                            _LAST_RETRIEVED_STRATEGIES[player_id] = existing

                # Add assistant response + tool results to context
                if is_native:
                    context.append(response)
                    tool_call_ids = self._extract_tool_call_ids(response, allowed_tool_names=set(tools))
                    for i, tr in enumerate(tool_results):
                        tc_id = tool_call_ids[i] if i < len(tool_call_ids) else f"call_{i}"
                        context.append(ToolMessage(content=tr, tool_call_id=tc_id))
                else:
                    context.append(HumanMessage(content=response_text))
                    for tr in tool_results:
                        context.append(HumanMessage(content=f"[工具结果]\n{tr}"))

                context.append(HumanMessage(content=self._final_decision_instruction()))
                if self._supports_bind_tools:
                    active_schemas = [decision_schema]
                    force_tool_name = DECISION_TOOL_NAME
                else:
                    active_schemas = []
                    force_tool_name = None
                continue

            if not self._supports_bind_tools or not active_schemas or response_text.strip():
                decision = self._parse_decision(response_text, obs)
                if not decision and not self._looks_like_structured_decision_response(response_text):
                    decision = self._parse_freeform_decision(response_text, obs)
                if decision:
                    keys = list(decision.keys())
                    logger.info(f"Call {call_count}: DECISION found ({keys})")
                    self._inject_tool_trace(decision, tool_trace, obs)
                    return decision

            # Neither info tool call nor valid final decision — ask once for the structured final call.
            preview = response_text[:150].replace("\n", "\\n")
            logger.info(f"Call {call_count}: no usable final decision found. Response preview: {preview}...")
            if (
                self._supports_bind_tools
                and force_tool_name == DECISION_TOOL_NAME
                and repair_rounds_used < MAX_FORMAT_REPAIR_ROUNDS
            ):
                repair_error = decision_error or "未调用 submit_decision function"
                if not response_text.strip() and not decision_error:
                    repair_error = "返回为空"
                repair_rounds_used += 1
                active_schemas = []
                force_tool_name = None
                text_repair_mode = True
                context.append(
                    HumanMessage(
                        content=(
                            f"上一次 function call 无法形成有效决策：{repair_error}。"
                            "现在改用纯文本输出最终决策，不要调用工具。"
                            f"{self._text_decision_instruction(obs, repair_error)}"
                        )
                    )
                )
                continue
            if text_repair_mode and repair_rounds_used >= MAX_FORMAT_REPAIR_ROUNDS:
                if not response_text.strip() and empty_response_repairs_used < MAX_EMPTY_RESPONSE_REPAIR_ROUNDS:
                    empty_response_repairs_used += 1
                    context.append(
                        HumanMessage(
                            content=(
                                "上一次回复为空。现在必须用纯文本输出最终决策，不要调用工具。"
                                f"{self._text_decision_instruction(obs, '返回为空')}"
                            )
                        )
                    )
                    continue
                break
            if response_text:
                context.append(HumanMessage(content=response_text))
            if repair_rounds_used >= MAX_FORMAT_REPAIR_ROUNDS and not text_repair_mode:
                break
            context.append(HumanMessage(content=self._final_decision_instruction(decision_error)))
            if self._supports_bind_tools:
                active_schemas = [decision_schema]
                force_tool_name = DECISION_TOOL_NAME
            else:
                active_schemas = []
                force_tool_name = None
                repair_rounds_used += 1
            continue

        raise RuntimeError(
            "AgentLoop failed to produce a structured decision "
            f"after {call_count} LLM call(s), tool_rounds={tool_rounds_used}, "
            f"action={self._action_type}, last_response={last_response_preview!r}"
        )

    # ================================================================
    # Prompt Building
    # ================================================================

    def _build_system_text(
        self,
        obs: Observation,
        memory: Memory,
        tools: Dict[str, Any],
        extra_context: str,
        cached_analysis: str,
    ) -> str:
        """Build the full system prompt with clear 3-layer hierarchy.

        Layer 1 (底层): MBTI — cognitive operating system, baked into system_prompt
        Layer 2 (中层): Role — game identity + game state + memory
        Layer 3 (顶层): Strategy — on-demand TOOL calls
        """
        blocks = []

        # ═══════════════════════════════════════════════════════
        # LAYER 1+2: MBTI + Role (from Profile.to_system_intro())
        # ═══════════════════════════════════════════════════════
        blocks.append(self._system_prompt)

        # ═══════════════════════════════════════════════════════
        # Game state + Memory (context for this turn)
        # ═══════════════════════════════════════════════════════
        blocks.append(build_game_context(obs))
        blocks.append(format_observation(obs))

        memory_text = memory.format_for_prompt()
        if memory_text:
            blocks.append(memory_text)

        # Extra context (phase-specific: first_speaker, last_words, etc.)
        if extra_context:
            blocks.append(f"【额外上下文】\n{extra_context}")

        # Cached analysis (reuse from talk() → vote() in same turn)
        if cached_analysis:
            blocks.append(
                f"【上一轮分析】\n{cached_analysis}\n"
                "(你刚分析过这个局势，直接基于已有判断做决策。如需补充信息可以调用工具。)"
            )

        # Action task with role-specific anti-patterns (static fallback)
        # Gameplay advice from Track C goes in the strategy layer below.
        role = str(getattr(obs, "player_role", "") or "")
        blocks.append(self._task_for_action(role, obs))

        track_c_strategy_text = ""
        if self._feature_enabled("COGNITIVE_ENABLE_TRACK_C", True):
            track_c_strategy_text = _build_track_c_strategy_block(
                obs,
                self._action_type,
                mbti=self._mbti,
                alignment=_derive_alignment(role),
                retrieval_policy=self._retrieval_policy,
            )
        if track_c_strategy_text:
            blocks.append(track_c_strategy_text)

        strategy_bias_text = build_strategy_bias_block(self._strategy_bias, self._strategy_action())
        if strategy_bias_text:
            blocks.append(strategy_bias_text)

        # ═══════════════════════════════════════════════════════
        # LAYER 3: Strategy — on-demand tools
        # ═══════════════════════════════════════════════════════
        if not self._supports_bind_tools:
            # Only include text tool descriptions when NOT using native
            # function calling (native FC has its own schema mechanism)
            blocks.append(self._format_tools(tools))

        # Output format
        blocks.append(self._output_format())

        return "\n\n".join(blocks)

    def _build_static_system_text(self, obs: Observation, tools: dict) -> str:
        """Cacheable system prompt — same across all calls in a game.

        Only includes content that NEVER changes between calls:
        - MBTI persona + role identity (from Profile)
        - Tool descriptions
        - Output format
        - Strategy bias (fixed per game)
        """
        blocks = [
            self._system_prompt,
            self._task_for_action(str(getattr(obs, "player_role", "") or "")),
        ]
        if not self._supports_bind_tools:
            blocks.append(self._format_tools(tools))
        blocks.append(self._output_format())
        strategy_bias_text = build_strategy_bias_block(self._strategy_bias, self._strategy_action())
        if strategy_bias_text:
            blocks.append(strategy_bias_text)
        return "\n\n".join(blocks)

    def _build_dynamic_context(
        self,
        obs: Observation,
        memory: Memory,
        extra_context: str,
        cached_analysis: str,
    ) -> str:
        """Dynamic context — changes every call, goes in HumanMessage.

        Game state, observation, memory, and extra context change each turn.
        Putting them here (not in SystemMessage) allows the static system
        prompt to be cached by the API.
        """
        blocks = [
            build_game_context(obs),
            format_observation(obs),
        ]
        memory_text = memory.format_for_prompt()
        if memory_text:
            blocks.append(memory_text)
        if extra_context:
            blocks.append(f"【额外上下文】\n{extra_context}")
        if cached_analysis:
            blocks.append(
                f"【上一轮分析】\n{cached_analysis}\n"
                "(你刚分析过这个局势，直接基于已有判断做决策。如需补充信息可以调用工具。)"
            )
        legal_target_text = _format_legal_target_instruction(obs)
        if legal_target_text and self._action_type in {"vote", "night"}:
            blocks.append("【本次合法目标约束】\n" + legal_target_text.strip())
        track_c_strategy_text = ""
        if self._feature_enabled("COGNITIVE_ENABLE_TRACK_C", True):
            track_c_strategy_text = _build_track_c_strategy_block(
                obs,
                self._action_type,
                mbti=self._mbti,
                alignment=_derive_alignment(str(getattr(obs, "player_role", "") or "")),
                retrieval_policy=self._retrieval_policy,
            )
        if track_c_strategy_text:
            blocks.append(track_c_strategy_text)
        return "\n\n".join(blocks)

    def _strategy_action(self) -> str:
        if self._action_type == "speech":
            return "talk"
        if self._action_type == "night":
            return "attack"
        return self._action_type

    def _build_initial_user(self, obs: Observation, cached_analysis: str) -> str:
        """Build the first user message that kicks off the thinking loop."""
        if cached_analysis:
            return f"当前阶段: {obs.phase}。你已有上轮分析结果。直接提交最终决策。"
        max_tool_rounds = self._max_tool_rounds(cached_analysis)
        if self._supports_bind_tools:
            return (
                f"当前阶段: {obs.phase}。"
                f"最多调用 {max_tool_rounds} 轮信息工具；信息足够时调用 {DECISION_TOOL_NAME} 提交最终决策。"
            )
        return (
            f"当前阶段: {obs.phase}。"
            "你可以通过多轮 TOOL 调用收集信息后再做决策。"
            "每轮回复只能选择 TOOL 或 DECISION 之一。"
            "调用工具后系统会返回结果，你可以根据结果继续调用其他工具或直接做决策。"
            f"最多调用 {max_tool_rounds} 轮工具，之后必须输出 DECISION。"
        )

    def _task_for_action(self, role: str = "", obs: Observation | None = None) -> str:
        """Return the action-specific task description with anti-pattern guardrails."""
        legal_hint = _format_legal_target_instruction(obs) if obs is not None else ""
        tasks = {
            "speech": (
                "【任务：发言】\n"
                "生成一段自然的狼人杀玩家发言。\n"
                "- 用中文发言\n"
                "- 用「X号」称呼玩家，不要说「X号玩家」\n"
                "- 不要当主持人报幕，直接以玩家身份发言\n"
                "- 只基于当前可见信息、你的角色能力边界和已有记忆表达\n"
            ),
            "vote": (
                "【任务：投票】\n"
                "选择一个存活玩家投票放逐。\n"
                "- 如果当前观察里列出合法目标，只能从合法目标中选择\n"
                "- 指出你要投谁（target）\n"
                "- 给出简短的投票理由（reasoning）\n"
                f"{legal_hint}"
            ),
            "night": (
                "【任务：夜晚行动】\n"
                "选择一个目标执行你的夜晚能力。\n"
                "- 如果当前观察里列出合法目标，只能从合法目标中选择\n"
                "- 指出目标（target）\n"
                "- 给出行动理由（reasoning）\n"
                f"{legal_hint}"
            ),
        }
        base = tasks.get(self._action_type, tasks["speech"])
        if role and self._feature_enabled("COGNITIVE_ENABLE_ANTI_PATTERNS", True):
            anti_patterns = get_role_anti_patterns(role, self._action_type)
            if anti_patterns:
                return base + "\n" + anti_patterns
        return base

    def _feature_enabled(self, env_var: str, default: bool = True) -> bool:
        return _feature_value_from_config(self._feature_flags, env_var, default)

    def _format_tools(self, tools: Dict[str, Any]) -> str:
        """Format tool descriptions for the system prompt (text fallback mode)."""
        max_tool_rounds = self._max_tool_rounds("")
        if not tools or max_tool_rounds <= 0:
            return "【可用工具】\n本动作不暴露信息工具，请直接输出 DECISION。"
        lines = ["【可用工具】", f"你可以最多调用 {max_tool_rounds} 轮工具。需要信息时，用以下格式调用："]
        lines.append("TOOL: <工具名>")
        lines.append("ARGUMENTS: <JSON>")
        lines.append("")
        for name, cfg in tools.items():
            lines.append(f"### {name}")
            lines.append(cfg["description"])
            lines.append("")
        return "\n".join(lines)

    def _output_format(self) -> str:
        """Return the output format instruction block."""
        max_tool_rounds = self._max_tool_rounds("")
        if self._supports_bind_tools:
            fmt = (
                "【输出格式】\n"
                "需要信息时，调用可用的信息 function 工具。\n"
                f"最终决策必须调用 {DECISION_TOOL_NAME} function，不要把最终决策写成普通文本。\n"
            )
        else:
            fmt = (
                "【输出格式】\n"
                "调用工具时:\n"
                "  TOOL: search_strategies\n"
                '  ARGUMENTS: {{"keywords": ["被查杀", "表水"], "limit": 3}}\n'
                "\n"
                "给出最终决策时:\n"
                "  DECISION: <JSON>\n"
            )
        if self._action_type == "speech":
            if self._supports_bind_tools:
                fmt += f'  {DECISION_TOOL_NAME} 参数例: {{"speech": "我分析了一下今天的局势...", "reasoning": "..."}}\n'
            else:
                fmt += '  例: DECISION: {"speech": "我分析了一下今天的局势...", "reasoning": "..."}\n'
        else:
            if self._supports_bind_tools:
                fmt += f'  {DECISION_TOOL_NAME} 参数例: {{"target": "3号", "reasoning": "投票理由..."}}\n'
            else:
                fmt += '  例: DECISION: {"target": "3号", "reasoning": "投票理由..."}\n'
        if self._supports_bind_tools:
            fmt += (
                "\n"
                "注意:\n"
                "- 信息工具只用于补充缺失事实，不要为了形式调用工具。\n"
                f"- 最多可以调用 {max_tool_rounds} 轮信息工具。\n"
                f"- 工具结果返回后或无需工具时，必须调用 {DECISION_TOOL_NAME}。"
            )
        else:
            fmt += (
                "\n"
                "注意:\n"
                "- 每次回复只能选择 TOOL 或 DECISION 之一，不要同时输出两者。\n"
                f"- 最多可以调用 {max_tool_rounds} 轮工具，每轮可以调用一个工具。\n"
                f"- 第 {max_tool_rounds} 轮工具结果返回后必须输出 DECISION。"
            )
        return fmt

    def _max_tool_rounds(self, cached_analysis: str) -> int:
        """Return how many information-tool rounds this action may use."""
        if cached_analysis:
            return 0
        default = MAX_TOOL_ROUNDS_BY_ACTION.get(self._action_type, 0)
        env_name = f"AGENT_MAX_TOOL_ROUNDS_{self._action_type.upper()}"
        raw = os.getenv(env_name, "").strip()
        if raw:
            try:
                return max(0, int(raw))
            except ValueError:
                logger.warning("Invalid %s=%r; using default %s", env_name, raw, default)
        return max(0, default)

    def _select_tools(self, all_tools: Dict[str, Any], obs: Observation) -> Dict[str, Any]:
        """Select a narrow information-tool set for the current action.

        Final decisions are submitted through submit_decision, which is not an
        information tool and is added separately to the native FC schema.
        """
        phase = str(getattr(obs, "phase", "") or "").upper()
        if self._action_type == "speech":
            names = ["recall_memory", "get_social_info", "search_strategies", "set_strategic_intent"]
        elif self._action_type == "vote":
            names = ["recall_memory", "analyze_votes", "get_social_info"]
        elif self._action_type == "night":
            names = ["recall_memory"]
            if "GUARD" in phase or "WITCH" in phase:
                names.append("check_rules")
        else:
            names = []
        return {name: all_tools[name] for name in names if name in all_tools}

    def _decision_tool_schema(self, obs: Observation | None = None) -> Dict[str, Any]:
        """Return the native function schema used for final decisions."""
        if self._action_type == "speech":
            properties = {
                "speech": {
                    "type": "string",
                    "description": "最终发言内容，使用中文，直接以玩家身份发言。",
                },
                "reasoning": {
                    "type": "string",
                    "description": "简短说明发言重点和依据。",
                },
                "tentative_vote": {
                    "type": "string",
                    "description": "你目前倾向投票放逐谁？用'X号:名字'格式。如果发言中提到了明确的投票倾向就填，否则留空。仅用于加速后续投票，投票阶段可以改。",
                },
            }
            required = ["speech", "reasoning"]
            description = "提交本次发言的最终决策。可选给出暂定投票倾向。"
        else:
            legal_targets = _legal_target_labels(obs)
            target_description = "最终目标，必须是当前可见且合法的玩家名或座位号。"
            if legal_targets:
                target_description += " 只能从以下值中选择：" + "、".join(legal_targets) + "。"
            properties = {
                "target": {
                    "type": "string",
                    "description": target_description,
                },
                "reasoning": {
                    "type": "string",
                    "description": "简短说明选择该目标的依据。",
                },
            }
            required = ["target", "reasoning"]
            description = "提交本次投票或夜晚行动的最终决策。"
            if legal_targets:
                properties["target"]["enum"] = legal_targets
                description += " target 必须严格使用合法目标枚举中的一个值。"
        return {
            "type": "function",
            "function": {
                "name": DECISION_TOOL_NAME,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            },
        }

    # ================================================================
    # Tool Schema Conversion
    # ================================================================

    def _tools_to_bind_schemas(self, tools: Dict[str, Any]) -> List[Dict]:
        """Convert tool definitions to OpenAI-compatible function schemas.

        Used with llm.bind_tools() for native function calling.
        """
        schemas = []
        for name, cfg in tools.items():
            # Extract clean description (skip function signature line)
            desc_lines = cfg["description"].strip().split("\n")
            human_lines = []
            for line in desc_lines[1:]:
                stripped = line.strip()
                if not stripped or stripped.startswith("例"):
                    break
                human_lines.append(stripped)
            clean_desc = " ".join(human_lines) if human_lines else desc_lines[0][:200]

            param_schema = _TOOL_PARAM_SCHEMAS.get(name, {"type": "object", "properties": {}})
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": clean_desc,
                        "parameters": param_schema,
                    },
                }
            )
        return schemas

    # ================================================================
    # LLM Call
    # ================================================================

    def _call_llm(
        self,
        messages: list,
        tool_schemas: Optional[List[Dict]] = None,
        *,
        force_tool_name: str | None = None,
    ):
        """Call the LLM with the message list. Returns AIMessage for full response access.

        When tool_schemas is provided and the LLM supports bind_tools,
        uses native function calling. Otherwise falls back to plain invoke.

        No retry loop here — DeepSeekClient handles retries with exponential
        backoff internally. We just make one call and return the result.
        """
        if tool_schemas and self._supports_bind_tools:
            llm = self._llm.bind_tools(tool_schemas)
        else:
            llm = self._llm
        kwargs: dict[str, Any] = {}
        if force_tool_name:
            kwargs["force_tool_name"] = force_tool_name
        kwargs["max_tokens"] = self._max_tokens(force_tool_name)
        if self._temperature is not None:
            kwargs["temperature"] = self._temperature
        try:
            resp = llm.invoke(messages, **kwargs)
        except TypeError:
            try:
                if self._temperature is not None:
                    resp = llm.invoke(messages, temperature=self._temperature)
                else:
                    resp = llm.invoke(messages)
            except TypeError:
                resp = llm.invoke(messages)

        # Accumulate token usage from response_metadata
        self._accumulate_usage(resp)
        return resp

    def _max_tokens(self, force_tool_name: str | None) -> int:
        """Bound completion tokens tightly for faster decisions."""
        if self._action_type == "speech":
            default = 768
            env_name = "AGENT_SPEECH_MAX_TOKENS"
        else:
            default = 384 if force_tool_name == DECISION_TOOL_NAME else 512
            env_name = "AGENT_DECISION_MAX_TOKENS"
        raw = os.getenv(env_name, "").strip()
        if raw:
            try:
                return max(64, int(raw))
            except ValueError:
                logger.warning("Invalid %s=%r; using default %s", env_name, raw, default)
        return default

    def _accumulate_usage(self, resp: Any) -> None:
        """Accumulate token usage from AIMessage.response_metadata across loop iterations."""
        meta = getattr(resp, "response_metadata", None) or {}
        token_usage = meta.get("token_usage", {})
        if token_usage:
            current = getattr(self, "_accumulated_usage", None) or {}
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                val = token_usage.get(key)
                if isinstance(val, (int, float)):
                    current[key] = current.get(key, 0) + int(val)
            self._accumulated_usage = current

    # ================================================================
    # Parsing
    # ================================================================

    def _parse_tool_calls(self, response, tools: Dict[str, Any]) -> List[str]:
        """Parse tool calls from LLM response.

        Priority: native tool_calls → text regex fallback.

        Returns list of tool result strings, or empty list if no tool calls found.
        """
        # 1. Native tool_calls (from bind_tools / function calling)
        if hasattr(response, "tool_calls") and response.tool_calls:
            results = []
            for tc in response.tool_calls:
                name = tc.get("name", "")
                if name == DECISION_TOOL_NAME or name not in tools:
                    continue
                if isinstance(tc.get("args"), dict):
                    args = tc["args"]
                else:
                    # args might be a JSON string in some formats
                    args_str = tc.get("args", "{}")
                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else {}
                    except json.JSONDecodeError:
                        args = {}
                results.append(self._execute_single_tool(name, args, tools))
            return results

        # 2. Text regex fallback
        text = response.content if hasattr(response, "content") else str(response)
        return self._parse_text_tool_calls(text, tools)

    def _parse_text_tool_calls(self, response: str, tools: Dict[str, Any]) -> List[str]:
        """Parse text-based tool calls from LLM response (fallback).

        Expected format:
          TOOL: search_strategies
          ARGUMENTS: {"keywords": [...], "limit": 3}

        Returns list of tool result strings, or empty list if no tool calls found.
        """
        pattern = r"TOOL:\s*(\w+)[\s\n]*ARGUMENTS:\s*(\{[^}]*\})"
        matches = re.findall(pattern, response, re.IGNORECASE)

        if not matches:
            return []

        results = []
        for tool_name, args_str in matches:
            tool_name = tool_name.strip()
            try:
                args = json.loads(args_str)
            except json.JSONDecodeError:
                results.append(f"工具调用参数解析失败: {args_str[:100]}")
                continue
            results.append(self._execute_single_tool(tool_name, args, tools))

        return results

    def _execute_single_tool(self, name: str, args: Dict[str, Any], tools: Dict[str, Any]) -> str:
        """Execute a single tool by name and return the result string."""
        if name not in tools:
            return f"未知工具: {name}。可用工具: {', '.join(tools.keys())}"
        try:
            fn = tools[name]["fn"]
            result = fn(**args)
            return f"[{name}]\n{result}"
        except Exception as e:
            return f"[{name}] 执行失败: {e}"

    def _extract_tool_names(
        self,
        response,
        is_native: bool,
        allowed_tool_names: set[str] | None = None,
    ) -> list[str]:
        """Extract tool names from an LLM response (native or text)."""
        if is_native and hasattr(response, "tool_calls") and response.tool_calls:
            return [
                tc.get("name", "unknown")
                for tc in response.tool_calls
                if not allowed_tool_names or tc.get("name", "") in allowed_tool_names
            ]
        text = response.content if hasattr(response, "content") else str(response)
        return [m.group(1) for m in re.finditer(r"TOOL:\s*(\w+)", text, re.IGNORECASE)]

    def _extract_tool_call_ids(self, response, allowed_tool_names: set[str] | None = None) -> list[str]:
        """Extract native tool call IDs matching executable information tools."""
        if not hasattr(response, "tool_calls") or not response.tool_calls:
            return []
        ids: list[str] = []
        for tc in response.tool_calls:
            if allowed_tool_names and tc.get("name", "") not in allowed_tool_names:
                continue
            ids.append(tc.get("id", f"call_{len(ids)}"))
        return ids

    def _extract_tool_keywords(
        self,
        response,
        is_native: bool,
        allowed_tool_names: set[str] | None = None,
    ) -> dict[str, list[str]]:
        """Extract keywords per tool name from an LLM response."""
        result: dict[str, list[str]] = {}
        if is_native and hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                name = tc.get("name", "unknown")
                if allowed_tool_names and name not in allowed_tool_names:
                    continue
                args = tc.get("args", {})
                if isinstance(args, dict):
                    kw = args.get("keywords", [])
                    if isinstance(kw, list):
                        result[name] = [str(k)[:80] for k in kw]
                else:
                    result[name] = []
            return result
        text = response.content if hasattr(response, "content") else str(response)
        for m in re.finditer(r"TOOL:\s*(\w+)", text, re.IGNORECASE):
            name = m.group(1)
            result[name] = []
        for m in re.finditer(r"ARGUMENTS:\s*(\{[^}]*\})", text, re.IGNORECASE):
            try:
                args = json.loads(m.group(1))
                kw = args.get("keywords", [])
                if isinstance(kw, list):
                    for name in result:
                        result[name] = [str(k)[:80] for k in kw]
                        break
            except json.JSONDecodeError:
                pass
        return result

    def _parse_submit_decision(self, response: Any) -> tuple[Optional[Dict[str, str]], str]:
        """Parse final decision from native submit_decision tool calls."""
        if not hasattr(response, "tool_calls") or not response.tool_calls:
            return None, ""
        for tc in response.tool_calls:
            if tc.get("name") != DECISION_TOOL_NAME:
                continue
            args = tc.get("args", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    logger.warning("submit_decision arguments are not valid JSON")
                    return None, "submit_decision 的 arguments 不是合法 JSON。"
            if not isinstance(args, dict):
                return None, "submit_decision 的 arguments 必须是 JSON object。"
            reasoning = str(args.get("reasoning", "")).strip()
            if self._action_type == "speech":
                speech = str(args.get("speech", "")).strip()
                if speech and not reasoning:
                    reasoning = "submit_decision_reasoning_missing"
                if speech and reasoning:
                    return {"speech": speech, "reasoning": reasoning}, ""
                logger.warning("submit_decision missing speech/reasoning for speech action")
                missing = []
                if not speech:
                    missing.append("speech")
                if not reasoning:
                    missing.append("reasoning")
                return None, f"submit_decision 缺少必填字段: {', '.join(missing)}。"
            target = str(args.get("target", "")).strip()
            if target and self._current_obs is not None:
                target_text = target + "\n" + json.dumps(args, ensure_ascii=False)
                resolved_target = self._extract_named_legal_target(target_text, self._current_obs)
                if not resolved_target:
                    return None, f"submit_decision target 不在合法目标中: {target}。"
                target = resolved_target
            if target and reasoning:
                return {"target": target, "reasoning": reasoning}, ""
            logger.warning("submit_decision missing target/reasoning for %s action", self._action_type)
            missing = []
            if not target:
                missing.append("target")
            if not reasoning:
                missing.append("reasoning")
            return None, f"submit_decision 缺少必填字段: {', '.join(missing)}。"
        return None, ""

    def _final_decision_instruction(self, previous_error: str = "") -> str:
        """Instruction used after tool results or format repair."""
        prefix = f"上一次最终决策格式无效：{previous_error}\n" if previous_error else ""
        if self._supports_bind_tools:
            if self._action_type == "speech":
                return (
                    prefix + f"信息已足够。现在不要调用任何信息工具，只调用 {DECISION_TOOL_NAME}，"
                    "参数必须包含 speech 和 reasoning。"
                )
            return (
                prefix + f"信息已足够。现在不要调用任何信息工具，只调用 {DECISION_TOOL_NAME}，"
                "参数必须包含 target 和 reasoning。"
            )
        if self._action_type == "speech":
            return prefix + '请直接输出最终决策，格式必须是：DECISION: {"speech": "...", "reasoning": "..."}'
        return prefix + '请直接输出最终决策，格式必须是：DECISION: {"target": "...", "reasoning": "..."}'

    def _text_decision_instruction(self, obs: Observation | None = None, previous_error: str = "") -> str:
        """Pure-text repair instruction used after native function-call failure."""

        prefix = f"上一次最终决策格式无效：{previous_error}\n" if previous_error else ""
        if self._action_type == "speech":
            return prefix + '请只输出一行：DECISION: {"speech": "你的最终发言", "reasoning": "发言依据"}'
        legal_targets = _legal_target_labels(obs)
        legal_text = f" 合法目标只能从这些值中选一个：{'、'.join(legal_targets)}。" if legal_targets else ""
        return (
            prefix
            + "请只输出一行："
            + 'DECISION: {"target": "目标玩家名或座位号", "reasoning": "选择该目标的依据"}'
            + legal_text
        )

    def _inject_tool_trace(self, decision: dict, tool_trace: list[dict], obs: Observation) -> None:
        """Inject tool trace and auto-injected strategy IDs into the decision dict."""
        decision[trace_keys.TOOL_TRACE] = tool_trace
        player_id = str(getattr(obs, "player_id", "") or "")
        with _STRATEGY_LOCK:
            auto_injected = _LAST_RETRIEVED_STRATEGIES.pop(player_id, [])
        decision[trace_keys.AUTO_INJECTED_STRATEGIES] = [s.get("doc_id", "") for s in auto_injected]
        # Extract tool-called strategy doc_ids from the tool trace and merge
        tool_called_ids: list[str] = []
        for entry in tool_trace:
            if entry.get("tool") == "search_strategies":
                for did in entry.get("doc_ids", []):
                    if did and did not in tool_called_ids:
                        tool_called_ids.append(did)
        merged_ids = list(dict.fromkeys(decision[trace_keys.AUTO_INJECTED_STRATEGIES] + tool_called_ids))
        decision[trace_keys.RETRIEVED_KNOWLEDGE_IDS] = merged_ids
        # Inject accumulated token usage
        usage = getattr(self, "_accumulated_usage", None) or {}
        if usage:
            decision[trace_keys.USAGE] = dict(usage)

        with _STRATEGY_LOCK:
            _LAST_LOOP_TRACE[player_id] = trace_keys.compat_loop_trace_payload(
                tool_trace=tool_trace,
                auto_injected=decision[trace_keys.AUTO_INJECTED_STRATEGIES],
                retrieved_ids=merged_ids,
                usage=usage,
            )

    def _parse_decision(self, response: str, obs: Observation | None = None) -> Optional[Dict[str, str]]:
        """Parse final decision from LLM response.

        Expected format:
          DECISION: {"speech": "..."}  or  DECISION: {"target": "...", "reasoning": "..."}

        Uses balanced-brace extraction (not regex [^}]*) so that speech content
        containing '}' characters (emoji, punctuation) doesn't truncate the JSON.
        Falls back to salvaging partial text when JSON is truncated by token limits.
        """
        # Find DECISION: marker
        marker_match = re.search(r"DECISION:\s*", response, re.IGNORECASE)
        if not marker_match:
            # Fallback: LLM often outputs JSON directly without DECISION: prefix.
            # Try to find any top-level JSON object that looks like a decision.
            json_match = re.search(r'\{\s*"(?:speech|target|reasoning)"\s*:', response)
            if json_match:
                marker_match = json_match
                # Pretend marker was at position 0 so the JSON parsing works
                # — we just need the JSON starting from the first brace.
                brace_start = response.rfind("{", 0, json_match.start() + 1)
                if brace_start < 0:
                    brace_start = json_match.start()
                # We'll set start manually below instead of using marker_match
                start = brace_start
                # Skip DECISION prefix logic, go straight to JSON extraction
                # Check for balanced braces
                depth = 0
                in_string = False
                escape = False
                end = start
                for i in range(start, len(response)):
                    ch = response[i]
                    if escape:
                        escape = False
                        continue
                    if ch == "\\":
                        escape = True
                        continue
                    if ch == '"':
                        in_string = not in_string
                        continue
                    if in_string:
                        continue
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                json_str = response[start:end] if depth == 0 else response[start:]
                try:
                    data = json.loads(json_str)
                    if isinstance(data, dict) and self._looks_like_decision_data(data):
                        result = self._decision_from_data(data, response, obs)
                        if self._is_valid_decision(result):
                            logger.info(f"No DECISION: marker, but found JSON directly: {list(result.keys())}")
                            return result
                except json.JSONDecodeError:
                    pass
            return None

        start = marker_match.end()
        while start < len(response) and response[start] in " \t\n\r":
            start += 1
        if start >= len(response) or response[start] != "{":
            return None

        # Balanced brace extraction
        depth = 0
        in_string = False
        escape = False
        end = start
        for i in range(start, len(response)):
            ch = response[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break

        json_str = response[start:end] if depth == 0 else response[start:]

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # JSON is malformed (likely truncated by token limit).
            # Try to salvage the speech text from the partial JSON.
            salvaged = self._salvage_partial_json(json_str)
            if salvaged:
                if salvaged.get("speech") and not str(salvaged.get("reasoning", "") or "").strip():
                    salvaged["reasoning"] = "partial_json_reasoning_missing"
                logger.warning(
                    f"Salvaged partial decision JSON (original parse failed). "
                    f"Salvaged {len(salvaged.get('speech', salvaged.get('target', '')))} chars."
                )
                return salvaged
            logger.warning(f"Failed to parse decision JSON: {json_str[:100]}")
            return None

        result: Dict[str, str] = {}
        result = self._decision_from_data(data, response, obs, marker_start=marker_match.start())
        return result if self._is_valid_decision(result) else None

    def _is_valid_decision(self, decision: dict[str, str]) -> bool:
        if self._action_type == "speech":
            return "speech" in decision
        return "target" in decision

    def _looks_like_decision_data(self, data: dict[str, Any]) -> bool:
        keys = {
            "speech",
            "content",
            "message",
            "utterance",
            "target",
            "target_name",
            "target_player",
            "player",
            "player_name",
            "vote",
            "choice",
            "selected",
            "reasoning",
            "reason",
        }
        return any(key in data for key in keys)

    def _looks_like_structured_decision_response(self, response: str) -> bool:
        if re.search(r"DECISION:\s*", response, re.IGNORECASE):
            return True
        return bool(re.search(r'\{\s*"(?:speech|target|reasoning|reason)"\s*:', response))

    def _decision_from_data(
        self,
        data: dict[str, Any],
        source_text: str,
        obs: Observation | None,
        *,
        marker_start: int | None = None,
    ) -> Dict[str, str]:
        result: Dict[str, str] = {}
        if self._action_type == "speech":
            speech_keys = ("speech", "content", "message", "utterance")
            has_speech_field = any(key in data for key in speech_keys)
            speech_value = next((data.get(key) for key in speech_keys if key in data), "")
            if has_speech_field:
                result["speech"] = str(speech_value or "")
            result["reasoning"] = str(data.get("reasoning") or data.get("reason") or "")
            if result.get("speech") and not result["reasoning"].strip():
                result["reasoning"] = "decision_json_reasoning_missing"
            if "speech" not in result:
                text = source_text[:marker_start].strip() if marker_start is not None else source_text.strip()
                if len(text) > 10:
                    result["speech"] = text[:500]
                    if not result["reasoning"].strip():
                        result["reasoning"] = "speech_extracted_from_response_prefix"
        else:
            target_keys = (
                "target",
                "target_name",
                "target_player",
                "player",
                "player_name",
                "vote",
                "choice",
                "selected",
            )
            has_target_field = any(key in data for key in target_keys)
            raw_target = next((data.get(key) for key in target_keys if key in data), "")
            if has_target_field:
                result["target"] = str(raw_target or "")
            if obs is not None and result.get("target"):
                target_text = f"{result['target']}\n{json.dumps(data, ensure_ascii=False)}"
                legal_target = self._extract_named_legal_target(target_text, obs)
                result["target"] = legal_target
            result["reasoning"] = str(data.get("reasoning") or data.get("reason") or "")
        return result

    def _parse_freeform_decision(self, response: str, obs: Observation) -> Optional[Dict[str, str]]:
        """Parse a usable decision from real LLM free-form text.

        This is not a heuristic fallback decision. It only converts the model's
        own text into the strict internal schema, and target actions must name
        one of the legal targets from the current observation.
        """
        text = response.strip()
        if not text:
            return None
        if self._action_type == "speech":
            cleaned = self._strip_format_noise(text)
            if len(cleaned) < 4:
                return None
            return {"speech": cleaned[:500], "reasoning": "model_freeform_speech"}

        target = self._extract_named_legal_target(text, obs)
        if not target:
            return None
        reasoning = self._strip_format_noise(text)
        return {"target": target, "reasoning": reasoning[:300] or "model_freeform_target"}

    @staticmethod
    def _strip_format_noise(text: str) -> str:
        cleaned = re.sub(r"^\s*(DECISION|ANSWER|最终决策|发言|理由)\s*[:：]\s*", "", text.strip(), flags=re.I)
        cleaned = re.sub(r"```(?:json)?", "", cleaned).replace("```", "").strip()
        return cleaned

    @staticmethod
    def _extract_named_legal_target(text: str, obs: Observation) -> str:
        candidates = _target_candidate_players(obs)
        lowered = text.lower()
        for player in candidates:
            name = str(player.name)
            seat = str(player.seat)
            patterns = [
                rf"(?<!\d){re.escape(seat)}\s*号",
                re.escape(name),
            ]
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    return name
            if name and name.lower() in lowered:
                return name
        return ""

    @staticmethod
    def _salvage_partial_json(json_str: str) -> Optional[Dict[str, str]]:
        """Attempt to extract usable content from a truncated/malformed JSON.

        Handles the common case where max_tokens truncates a speech JSON
        mid-string, e.g. {"speech": "long text here... (truncated)
        """
        result: Dict[str, str] = {}
        # Try to extract "speech" value even from truncated JSON
        for key in ("speech", "target", "reasoning"):
            # Match "key": "value" where value might be unterminated
            m = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"?', json_str)
            if m:
                val = m.group(1)
                # Unescape common escape sequences
                val = val.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t")
                result[key] = val
        # If we couldn't extract speech but the JSON has content after "speech":
        if not result and '"speech"' in json_str:
            m = re.search(r'"speech"\s*:\s*"(.*)', json_str, re.DOTALL)
            if m:
                raw = m.group(1).rstrip('"').rstrip("\\")
                if len(raw) > 5:
                    result["speech"] = raw[:500]
        return result if result else None


def _build_track_c_strategy_block(
    obs: Observation,
    action_type: str,
    *,
    mbti: str = "",
    alignment: str = "",
    retrieval_policy: str = "",
) -> str:
    """Format DB-backed Track C lessons for the strategy layer.

    This is intentionally separate from role/persona/task prompts: it may
    contain gameplay advice, but only when the knowledge store returns approved
    lessons from prior reviews.
    """
    lessons = _retrieve_track_c_strategy_lessons(
        obs,
        action_type,
        mbti=mbti,
        alignment=alignment,
        retrieval_policy=retrieval_policy,
    )
    if not lessons:
        return ""

    lines = [
        "【策略层：Track C 复盘知识】",
        "以下内容来自已发布复盘/策略知识库，并已通过运行时安全过滤；仅作为高置信可选参考。",
        "如果它与当前可见事实、角色规则、合法目标或任务约束冲突，必须忽略；不能把历史复盘当作本局隐藏身份事实。",
        "执行策略时必须保持本角色基本职责不退化，例如预言家查验并释放可信信息、守卫避免连守且保护关键好人、猎人开枪只瞄准高疑似狼人、村民基于公开事实投票。",
    ]
    for index, item in enumerate(lessons[:3], start=1):
        doc_id = str(item.get("doc_id") or item.get("id") or f"lesson-{index}")
        trigger = str(
            item.get("trigger") or item.get("situation_pattern") or item.get("trigger_conditions") or ""
        ).strip()
        recommendation = str(
            item.get("recommendation") or item.get("recommended_action") or item.get("strategy") or ""
        ).strip()
        avoid = str(item.get("avoid_action") or "").strip()
        rationale = str(item.get("rationale") or item.get("evidence_summary") or "").strip()
        score = item.get("score", item.get("quality_score", ""))
        score_text = f" score={float(score):.2f}" if isinstance(score, (int, float)) else ""
        doc_type = str(item.get("doc_type", ""))
        status = str(item.get("status", ""))
        label_parts = []
        if doc_type == "reflection":
            label_parts.append("反思经验")
        if status == "candidate":
            label_parts.append("候选/未验证")
        label_str = f" [{'/'.join(label_parts)}]" if label_parts else ""

        detail_parts = []
        if trigger:
            detail_parts.append(f"触发：{trigger}")
        if recommendation:
            detail_parts.append(f"可参考做法：{recommendation}")
        if avoid:
            detail_parts.append(f"避免：{avoid}")
        if rationale:
            detail_parts.append(f"依据：{rationale}")
        if detail_parts:
            lines.append(f"{index}. [{doc_id}{label_str}{score_text}] " + "；".join(detail_parts))
    return "\n".join(lines) if len(lines) > 2 else ""


def _retrieve_track_c_strategy_lessons(
    obs: Observation,
    action_type: str,
    *,
    mbti: str = "",
    alignment: str = "",
    retrieval_policy: str = "",
) -> list[dict[str, Any]]:
    """Retrieve Track C lessons without making prompt construction fragile."""
    try:
        from backend.agents.cognitive.retrieval_prod import RetrievalPolicy
        from backend.agents.cognitive.retrieval_prod import retrieve_strategies_prod

        phase = str(getattr(obs, "phase", "") or "")
        role = str(getattr(obs, "player_role", "") or "")
        player_id = str(getattr(obs, "player_id", "") or "")
        action = _strategy_query_action(action_type)
        mbti_key = _normalize_mbti(mbti)
        alignment_key = (alignment or _derive_alignment(role)).lower().strip()
        policy_raw = (
            os.getenv("TRACK_C_AUTO_RETRIEVAL_POLICY", "").strip() or retrieval_policy or "hybrid_role_alignment_phase"
        )
        try:
            policy = RetrievalPolicy(policy_raw)
        except ValueError:
            policy = RetrievalPolicy.HYBRID_ROLE_ALIGNMENT_PHASE
        cache_ttl = float(os.getenv("TRACK_C_AUTO_RETRIEVAL_CACHE_SECONDS", "120") or 0)
        limit = _track_c_env_int("TRACK_C_AUTO_RETRIEVAL_LIMIT", 1, minimum=0)
        min_quality = _track_c_env_float("TRACK_C_RUNTIME_MIN_QUALITY", 0.82)
        if limit <= 0:
            if player_id:
                with _STRATEGY_LOCK:
                    _LAST_RETRIEVED_STRATEGIES.pop(player_id, None)
            return []
        fetch_limit = _track_c_env_int("TRACK_C_AUTO_RETRIEVAL_FETCH_LIMIT", max(limit * 24, 24), minimum=limit)
        cache_key = (role, phase, action, mbti_key, alignment_key, policy.value, limit, min_quality)
        if cache_ttl > 0:
            cached = _TRACK_C_RETRIEVAL_CACHE.get(cache_key)
            now = time.monotonic()
            if cached and now - cached[0] <= cache_ttl:
                return [dict(row) for row in cached[1]]
        keywords = _track_c_auto_keywords(role, phase, action)
        rows = retrieve_strategies_prod(
            role=role,
            phase=phase,
            keywords=keywords,
            limit=fetch_limit,
            output_mode="content",
            retrieval_policy=policy,
            mbti=mbti_key,
            alignment=alignment_key,
            player_id=player_id,
            action_type=action,
        )
        if not rows and _feature_enabled("TRACK_C_LEGACY_AUTO_INJECT_FALLBACK", False):
            from backend.db.persist import list_strategy_knowledge

            rows = list_strategy_knowledge(
                role=role,
                phase=phase,
                status="active",
                limit=fetch_limit,
            )
        rows = [
            row
            for row in rows
            if isinstance(row, dict)
            and _track_c_row_safe_for_runtime(
                row,
                role,
                mbti_key,
                alignment_key,
                phase=phase,
                action=action,
                min_quality=min_quality,
            )
        ][:limit]
        lessons = [
            _normalize_strategy_row(row, index) for index, row in enumerate(rows, start=1) if isinstance(row, dict)
        ]
        if cache_ttl > 0:
            _TRACK_C_RETRIEVAL_CACHE[cache_key] = (time.monotonic(), lessons)
        if lessons:
            player_id = str(getattr(obs, "player_id", "") or "")
            with _STRATEGY_LOCK:
                _LAST_RETRIEVED_STRATEGIES[player_id] = lessons
        else:
            if player_id:
                with _STRATEGY_LOCK:
                    _LAST_RETRIEVED_STRATEGIES.pop(player_id, None)
            if os.getenv("REQUIRE_STRATEGY_USAGE_TRACE", "").lower() == "true":
                logger.error("STRICT FAIL: Track C auto-retrieval returned no strategies")
        return lessons
    except Exception as exc:
        logger.debug("Track C strategy retrieval skipped: %s", exc)
        return []


_UNOBSERVABLE_TRACK_C_PATTERNS = (
    "眼神",
    "表情",
    "肢体",
    "手势",
    "语气变化",
    "声音颤抖",
    "情绪温度",
    "氛围",
    "微表情",
    "现实桌游",
    "场外",
    "私下交流",
    "座位姿态",
    "深层动机",
    "eye contact",
    "facial expression",
    "body language",
    "micro-expression",
    "nonverbal",
    "offline cue",
    "out-of-game",
)
_ABSOLUTE_TRACK_C_PATTERNS = (
    "永远",
    "无论如何",
    "无论任何",
    "固定投",
    "must always",
    "always vote",
    "never reveal",
)
_HISTORICAL_IDENTIFIER_PATTERN = re.compile(
    r"(?<!\d)(?:\d{1,2}\s*号|P\d+\b|[A-Za-z0-9_-]*-[0-9a-f]{4,})",
    re.IGNORECASE,
)


def _track_c_env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        logger.warning("Invalid %s=%r; using default %s", name, raw, default)
        return default


def _track_c_env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using default %s", name, raw, default)
        return default


def _track_c_row_safe_for_runtime(
    row: dict[str, Any],
    role: str,
    mbti: str,
    alignment: str,
    *,
    phase: str = "",
    action: str = "",
    min_quality: float | None = None,
) -> bool:
    """Final safety gate before auto-injecting Track C knowledge into prompts."""
    status = str(row.get("status", "active") or "active").lower().strip()
    if status != "active":
        return False

    doc_type = str(row.get("doc_type", "") or "").lower().strip()
    if doc_type.startswith("reflection") and not _feature_enabled("TRACK_C_RUNTIME_ALLOW_REFLECTIONS", False):
        return False

    quality = _track_c_row_quality(row)
    min_quality = min_quality if min_quality is not None else _track_c_env_float("TRACK_C_RUNTIME_MIN_QUALITY", 0.82)
    if doc_type.startswith("reflection"):
        min_quality = max(min_quality, 0.85)
    if quality is not None and quality < min_quality:
        return False

    if bool(row.get("contains_current_game_private_info", False)):
        return False

    visibility_scope = str(row.get("visibility_scope", "") or "").lower().strip()
    if visibility_scope in {"private", "hidden", "god", "omniscient"}:
        return False
    if visibility_scope in {"wolf", "wolf_team", "wolves"} and alignment != "wolf":
        return False

    row_mbti = _extract_track_c_mbti_scope(row)
    if row_mbti and row_mbti != mbti:
        return False

    row_role = _extract_track_c_role_scope(row)
    role_key = role.lower().strip()
    if row_role and row_role not in {"global", "any"} and role_key and row_role != role_key:
        return False

    if not _track_c_phase_safe_for_runtime(row, phase, action):
        return False

    text = " ".join(
        str(row.get(key, "") or "")
        for key in (
            "trigger",
            "situation",
            "situation_pattern",
            "recommendation",
            "strategy",
            "recommended_action",
            "avoid_action",
            "rationale",
            "evidence_summary",
        )
    ).lower()
    if any(pattern in text for pattern in _UNOBSERVABLE_TRACK_C_PATTERNS):
        return False
    if any(pattern in text for pattern in _ABSOLUTE_TRACK_C_PATTERNS):
        return False
    if _HISTORICAL_IDENTIFIER_PATTERN.search(text):
        return False

    return True


def _track_c_row_quality(row: dict[str, Any]) -> float | None:
    for key in ("quality_score", "quality", "score"):
        raw = row.get(key)
        if raw in (None, ""):
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def _track_c_phase_safe_for_runtime(row: dict[str, Any], phase: str, action: str) -> bool:
    """Avoid injecting stale phase advice into unrelated decisions."""
    if not _feature_enabled("TRACK_C_RUNTIME_REQUIRE_PHASE_MATCH", True):
        return True
    phase_key = str(phase or "").upper().strip()
    action_key = str(action or "").lower().strip()
    scopes = {
        str(row.get(key, "") or "").upper().strip()
        for key in ("phase_scope", "phase", "applicability_phase")
        if str(row.get(key, "") or "").strip()
    }
    scopes.discard("GLOBAL")
    scopes.discard("ANY")
    if scopes:
        return phase_key in scopes or any(
            _track_c_phase_action_compatible(scope, phase_key, action_key) for scope in scopes
        )
    return _feature_enabled("TRACK_C_RUNTIME_ALLOW_GLOBAL_PHASE", action_key == "talk")


def _track_c_phase_action_compatible(scope: str, phase: str, action: str) -> bool:
    if not scope:
        return False
    if scope == phase:
        return True
    if action == "talk":
        return "SPEECH" in scope or "BADGE" in scope
    if action == "vote":
        return "VOTE" in scope or "RESOLVE" in scope
    if action == "night_action":
        if "NIGHT" in phase and "NIGHT" in scope:
            return True
        role_markers = ("WOLF", "SEER", "WITCH", "GUARD", "HUNTER")
        return any(marker in phase and marker in scope for marker in role_markers)
    return False


def _normalize_mbti(mbti: str) -> str:
    value = str(mbti or "").upper().strip()
    return value if re.fullmatch(r"[IE][NS][FT][JP]", value) else ""


def _extract_track_c_mbti_scope(row: dict[str, Any]) -> str:
    raw = str(row.get("mbti_scope", "") or "").upper().strip()
    if re.fullmatch(r"[IE][NS][FT][JP]", raw):
        return raw
    persona_scope = str(row.get("persona_scope", "") or "")
    match = re.search(r"mbti:([A-Za-z]{4})", persona_scope)
    if match:
        return _normalize_mbti(match.group(1))
    return _normalize_mbti(persona_scope)


def _extract_track_c_role_scope(row: dict[str, Any]) -> str:
    raw = str(row.get("role_scope") or row.get("role") or "").lower().strip()
    if raw:
        return raw
    persona_scope = str(row.get("persona_scope", "") or "")
    match = re.search(r"role:([A-Za-z_]+)", persona_scope)
    return match.group(1).lower().strip() if match else ""


def _strategy_query_action(action_type: str) -> str:
    if action_type == "speech":
        return "talk"
    if action_type == "night":
        return "night_action"
    return action_type


def _track_c_auto_keywords(role: str, phase: str, action: str) -> list[str]:
    role_terms = {
        "Werewolf": ["狼人", "伪装", "带节奏", "刀人"],
        "WhiteWolfKing": ["白狼王", "自爆", "带走", "伪装"],
        "Seer": ["预言家", "查验", "警徽流", "信息释放"],
        "Witch": ["女巫", "解药", "毒药", "用药"],
        "Hunter": ["猎人", "开枪", "带人", "藏身份"],
        "Guard": ["守卫", "守护", "保护", "连续守"],
        "Villager": ["平民", "发言", "投票", "站边"],
    }
    phase_terms = {
        "DAY_BADGE_SPEECH": ["警徽", "上警", "警徽流"],
        "DAY_SPEECH": ["发言", "表水", "分析"],
        "DAY_VOTE": ["投票", "归票", "放逐"],
        "NIGHT_WOLF_ACTION": ["刀人", "击杀", "目标"],
        "NIGHT_SEER_ACTION": ["查验", "验人", "预言家"],
        "NIGHT_WITCH_ACTION": ["女巫", "解药", "毒药"],
        "NIGHT_GUARD_ACTION": ["守卫", "守护", "保护"],
        "HUNTER_SHOOT": ["猎人", "开枪", "带人"],
    }
    action_terms = {
        "talk": ["发言", "表达", "信息"],
        "vote": ["投票", "归票", "票型"],
        "night_action": ["夜晚", "技能", "目标"],
    }
    seen: set[str] = set()
    keywords: list[str] = []
    for term in role_terms.get(role, [role]) + phase_terms.get(phase, [phase]) + action_terms.get(action, [action]):
        clean = str(term).strip()
        if clean and clean not in seen:
            seen.add(clean)
            keywords.append(clean)
    return keywords[:6]


def _normalize_strategy_row(row: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "doc_id": row.get("doc_id") or row.get("id") or row.get("doc_type") or f"strategy-{index}",
        "trigger": row.get("trigger") or row.get("situation") or row.get("situation_pattern") or "",
        "recommendation": row.get("recommendation") or row.get("strategy") or row.get("recommended_action") or "",
        "avoid_action": row.get("avoid_action") or "",
        "rationale": row.get("rationale") or row.get("evidence_summary") or "",
        "score": row.get("score", row.get("quality", row.get("quality_score", ""))),
        "doc_type": row.get("doc_type", ""),
        "status": row.get("status", ""),
        "quality_score": row.get("quality_score", row.get("quality", "")),
        "bucket": row.get("bucket", ""),
        "retrieval_policy": row.get("retrieval_policy", ""),
        "persona_scope": row.get("persona_scope", ""),
        "mbti_scope": row.get("mbti_scope", ""),
        "role_scope": row.get("role_scope", row.get("role", "")),
        "alignment_scope": row.get("alignment_scope", ""),
        "phase_scope": row.get("phase_scope", row.get("phase", "")),
    }
