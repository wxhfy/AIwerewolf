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
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import Runnable

from backend.agents.cognitive.memory import Memory
from backend.agents.cognitive.observe import Observation, format_observation
from backend.agents.cognitive.prompts import (
    build_game_context,
    build_strategy_bias_block,
    get_role_anti_patterns,
)
from backend.agents.cognitive.tools import create_tools

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 3
import threading as _threading
_STRATEGY_LOCK = _threading.Lock()
_TRACK_C_RETRIEVAL_CACHE: dict[tuple[str, str, str], tuple[float, list[dict[str, Any]]]] = {}
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
        },
        "required": ["keywords"],
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
    ):
        self._llm = llm
        self._system_prompt = system_prompt
        self._action_type = action_type
        self._strategy_bias = strategy_bias or {}
        self._temperature = temperature
        # Native function calling via bind_tools is supported by the LLM wrapper
        # but currently disabled by default. Direct API tests confirm tools work,
        # but AgentLoop's message construction triggers a provider-specific edge
        # case with the doubao endpoint. Text-mode tool calling (TOOL: / ARGUMENTS:)
        # is production-reliable across all providers.
        # Set AGENT_USE_NATIVE_FC=1 to enable native function calling.
        import os as _os
        self._supports_bind_tools = (
            hasattr(llm, 'bind_tools')
            and _os.getenv("AGENT_USE_NATIVE_FC", "").strip() == "1"
        )

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
        tools = create_tools(obs, memory)
        tool_schemas = self._tools_to_bind_schemas(tools) if self._supports_bind_tools else None
        context = []  # list of messages for the conversation
        tool_trace: list[dict] = []  # track tool calls for auditing

        # Build initial system prompt
        system_text = self._build_system_text(obs, memory, tools, extra_context, cached_analysis)
        context.append(SystemMessage(content=system_text))

        # Initial user message (triggers the LLM to start thinking)
        init_user = self._build_initial_user(obs, cached_analysis)
        context.append(HumanMessage(content=init_user))

        iteration = 0
        last_tool_results = False
        while iteration < MAX_ITERATIONS:
            iteration += 1

            response = self._call_llm(context, tool_schemas)
            response_text = response.content if hasattr(response, 'content') else str(response)

            # Detect native tool calls for proper ToolMessage handling
            is_native = hasattr(response, 'tool_calls') and response.tool_calls

            # Try to parse tool calls (native → text fallback)
            tool_results = self._parse_tool_calls(response, tools)
            if tool_results:
                logger.info(
                    f"Iter {iteration}/{MAX_ITERATIONS}: {len(tool_results)} tool call(s) "
                    f"({'native' if is_native else 'text'}) - "
                    f"{', '.join(t.split(chr(10))[0][:80] for t in tool_results)}"
                )

                # Record tool trace for auditing
                tool_names = self._extract_tool_names(response, is_native)
                tool_keywords = self._extract_tool_keywords(response, is_native)
                for idx, tr in enumerate(tool_results):
                    tname = tool_names[idx] if idx < len(tool_names) else "unknown"
                    # Extract doc_ids from formatted strategy output
                    doc_ids = re.findall(r'\[([\w\-]+)\s+score=', tr) if tname == 'search_strategies' else []
                    tool_trace.append({
                        "iteration": iteration,
                        "tool": tname,
                        "keywords": tool_keywords.get(tname, []),
                        "doc_ids": doc_ids,
                        "timestamp": time.time(),
                        "result_summary": tr[:200],
                    })
                    # Populate _LAST_RETRIEVED_STRATEGIES for search_strategies tool calls
                    # so _record_strategy_usage() can track which docs were actually retrieved.
                    # Merge with auto-injected entries (if any) rather than overwriting.
                    if tname == 'search_strategies' and doc_ids:
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
                    for i, tr in enumerate(tool_results):
                        tc_id = response.tool_calls[i].get("id", f"call_{i}")
                        context.append(ToolMessage(content=tr, tool_call_id=tc_id))
                else:
                    context.append(HumanMessage(content=response_text))
                    for tr in tool_results:
                        context.append(HumanMessage(content=f"[工具结果]\n{tr}"))

                if iteration >= MAX_ITERATIONS:
                    context.append(HumanMessage(
                        content="(已是最后一轮工具调用，信息已足够，请直接输出 DECISION 做最终决策。)"
                    ))
                    last_tool_results = True
                else:
                    remaining = MAX_ITERATIONS - iteration
                    context.append(HumanMessage(
                        content=f"(工具结果已返回。还剩 {remaining} 轮工具调用额度。"
                        "你可以继续调用其他工具获取更多信息，或直接输出 DECISION 做决策。)"
                    ))
                continue

            # No tool calls — try to parse decision
            decision = self._parse_decision(response_text)
            if decision:
                keys = list(decision.keys())
                logger.info(f"Iter {iteration}/{MAX_ITERATIONS}: DECISION found ({keys})")
                self._inject_tool_trace(decision, tool_trace, obs)
                return decision

            # Neither tool call nor valid decision — ask LLM to be clearer
            preview = response_text[:150].replace('\n', '\\n')
            logger.info(
                f"Iter {iteration}/{MAX_ITERATIONS}: no TOOL or DECISION found. "
                f"Response preview: {preview}..."
            )
            context.append(HumanMessage(content=response_text))
            context.append(HumanMessage(content=(
                "你的回复格式不正确。请严格按以下格式之一回复：\n"
                "1. TOOL: <工具名>\\nARGUMENTS: <JSON>\\n"
                "2. DECISION: <JSON>\\n"
                "不要输出其他内容。"
            )))

        # Tool results were added in the last iteration — give LLM one more
        # chance to see the results and produce a DECISION.
        if last_tool_results:
            response = self._call_llm(context, tool_schemas)
            decision = self._parse_decision(
                response.content if hasattr(response, 'content') else str(response)
            )
            if decision:
                logger.info(f"Final call: DECISION found ({list(decision.keys())})")
                self._inject_tool_trace(decision, tool_trace, obs)
                return decision

        raise RuntimeError(
            f"AgentLoop failed to produce a DECISION after {MAX_ITERATIONS} "
            f"iterations for action={self._action_type}"
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
        blocks.append(self._task_for_action(role))

        track_c_strategy_text = ""
        if _feature_enabled("COGNITIVE_ENABLE_TRACK_C", True):
            track_c_strategy_text = _build_track_c_strategy_block(obs, self._action_type)
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

    def _strategy_action(self) -> str:
        if self._action_type == "speech":
            return "talk"
        if self._action_type == "night":
            return "attack"
        return self._action_type

    def _build_initial_user(self, obs: Observation, cached_analysis: str) -> str:
        """Build the first user message that kicks off the thinking loop."""
        if cached_analysis:
            return (
                f"当前阶段: {obs.phase}。你已有上轮分析结果。"
                "直接输出 DECISION。"
            )
        return (
            f"当前阶段: {obs.phase}。"
            "你可以通过多轮 TOOL 调用收集信息后再做决策。"
            "每轮回复只能选择 TOOL 或 DECISION 之一。"
            "调用工具后系统会返回结果，你可以根据结果继续调用其他工具或直接做决策。"
            f"最多调用 {MAX_ITERATIONS} 轮工具，之后必须输出 DECISION。"
        )

    def _task_for_action(self, role: str = "") -> str:
        """Return the action-specific task description with anti-pattern fallback."""
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
            ),
            "night": (
                "【任务：夜晚行动】\n"
                "选择一个目标执行你的夜晚能力。\n"
                "- 如果当前观察里列出合法目标，只能从合法目标中选择\n"
                "- 指出目标（target）\n"
                "- 给出行动理由（reasoning）\n"
            ),
        }
        base = tasks.get(self._action_type, tasks["speech"])
        # Inject static anti-patterns as fallback (complements DB-backed Track C block)
        if role and _feature_enabled("COGNITIVE_ENABLE_ANTI_PATTERNS", True):
            anti = get_role_anti_patterns(role, self._action_type)
            if anti:
                return base + "\n" + anti
        return base

    def _format_tools(self, tools: Dict[str, Any]) -> str:
        """Format tool descriptions for the system prompt (text fallback mode)."""
        lines = ["【可用工具】", f"你可以最多调用 {MAX_ITERATIONS} 轮工具。需要信息时，用以下格式调用："]
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
        if self._supports_bind_tools:
            fmt = (
                "【输出格式】\n"
                "需要信息时，直接调用可用的 function 工具。\n"
                "收集足够信息后，给出最终决策：\n"
                "  DECISION: <JSON>\n"
            )
        else:
            fmt = (
                "【输出格式】\n"
                "调用工具时:\n"
                "  TOOL: search_strategies\n"
                "  ARGUMENTS: {{\"keywords\": [\"被查杀\", \"表水\"], \"limit\": 3}}\n"
                "\n"
                "给出最终决策时:\n"
                "  DECISION: <JSON>\n"
            )
        if self._action_type == "speech":
            fmt += '  例: DECISION: {"speech": "我分析了一下今天的局势...", "reasoning": "..."}\n'
        else:
            fmt += '  例: DECISION: {"target": "3号", "reasoning": "投票理由..."}\n'
        if self._supports_bind_tools:
            fmt += (
                "\n"
                "注意:\n"
                "- 可以先调用工具收集信息，再输出 DECISION。\n"
                f"- 最多可以调用 {MAX_ITERATIONS} 轮工具。\n"
                f"- 第 {MAX_ITERATIONS} 轮工具结果返回后必须输出 DECISION。"
            )
        else:
            fmt += (
                "\n"
                "注意:\n"
                "- 每次回复只能选择 TOOL 或 DECISION 之一，不要同时输出两者。\n"
                f"- 最多可以调用 {MAX_ITERATIONS} 轮工具，每轮可以调用一个工具。\n"
                f"- 第 {MAX_ITERATIONS} 轮工具结果返回后必须输出 DECISION。"
            )
        return fmt

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
            desc_lines = cfg["description"].strip().split('\n')
            human_lines = []
            for line in desc_lines[1:]:
                stripped = line.strip()
                if not stripped or stripped.startswith('例'):
                    break
                human_lines.append(stripped)
            clean_desc = ' '.join(human_lines) if human_lines else desc_lines[0][:200]

            param_schema = _TOOL_PARAM_SCHEMAS.get(
                name, {"type": "object", "properties": {}}
            )
            schemas.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": clean_desc,
                    "parameters": param_schema,
                },
            })
        return schemas

    # ================================================================
    # LLM Call
    # ================================================================

    def _call_llm(
        self, messages: list, tool_schemas: Optional[List[Dict]] = None
    ):
        """Call the LLM with the message list. Returns AIMessage for full response access.

        When tool_schemas is provided and the LLM supports bind_tools,
        uses native function calling. Otherwise falls back to plain invoke.
        """
        import time as _time
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                if tool_schemas and self._supports_bind_tools:
                    llm = self._llm.bind_tools(tool_schemas)
                else:
                    llm = self._llm
                if self._temperature is not None:
                    resp = llm.invoke(messages, temperature=self._temperature)
                else:
                    resp = llm.invoke(messages)
                # Accept if has tool_calls or reasonable content
                has_tools = hasattr(resp, 'tool_calls') and resp.tool_calls
                has_content = resp.content and len(resp.content.strip()) > 5
                if has_tools or has_content:
                    return resp
                # Empty response — wait and retry
                logger.warning(f"LLM returned empty/short response (attempt {attempt+1}), retrying...")
                _time.sleep(1)
            except Exception as e:
                last_error = e
                logger.warning(f"LLM call failed (attempt {attempt+1}): {e}")
                _time.sleep(1)
        if last_error is not None:
            raise RuntimeError("LLM call failed after 3 attempts") from last_error
        raise RuntimeError("LLM returned empty response after 3 attempts")

    # ================================================================
    # Parsing
    # ================================================================

    def _parse_tool_calls(self, response, tools: Dict[str, Any]) -> List[str]:
        """Parse tool calls from LLM response.

        Priority: native tool_calls → text regex fallback.

        Returns list of tool result strings, or empty list if no tool calls found.
        """
        # 1. Native tool_calls (from bind_tools / function calling)
        if hasattr(response, 'tool_calls') and response.tool_calls:
            results = []
            for tc in response.tool_calls:
                name = tc.get("name", "")
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
        text = response.content if hasattr(response, 'content') else str(response)
        return self._parse_text_tool_calls(text, tools)

    def _parse_text_tool_calls(
        self, response: str, tools: Dict[str, Any]
    ) -> List[str]:
        """Parse text-based tool calls from LLM response (fallback).

        Expected format:
          TOOL: search_strategies
          ARGUMENTS: {"keywords": [...], "limit": 3}

        Returns list of tool result strings, or empty list if no tool calls found.
        """
        pattern = r'TOOL:\s*(\w+)[\s\n]*ARGUMENTS:\s*(\{[^}]*\})'
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

    def _execute_single_tool(
        self, name: str, args: Dict[str, Any], tools: Dict[str, Any]
    ) -> str:
        """Execute a single tool by name and return the result string."""
        if name not in tools:
            return f"未知工具: {name}。可用工具: {', '.join(tools.keys())}"
        try:
            fn = tools[name]["fn"]
            result = fn(**args)
            return f"[{name}]\n{result}"
        except Exception as e:
            return f"[{name}] 执行失败: {e}"

    def _extract_tool_names(self, response, is_native: bool) -> list[str]:
        """Extract tool names from an LLM response (native or text)."""
        if is_native and hasattr(response, 'tool_calls') and response.tool_calls:
            return [tc.get("name", "unknown") for tc in response.tool_calls]
        text = response.content if hasattr(response, 'content') else str(response)
        return [m.group(1) for m in re.finditer(r'TOOL:\s*(\w+)', text, re.IGNORECASE)]

    def _extract_tool_keywords(self, response, is_native: bool) -> dict[str, list[str]]:
        """Extract keywords per tool name from an LLM response."""
        result: dict[str, list[str]] = {}
        if is_native and hasattr(response, 'tool_calls') and response.tool_calls:
            for tc in response.tool_calls:
                name = tc.get("name", "unknown")
                args = tc.get("args", {})
                if isinstance(args, dict):
                    kw = args.get("keywords", [])
                    if isinstance(kw, list):
                        result[name] = [str(k)[:80] for k in kw]
                else:
                    result[name] = []
            return result
        text = response.content if hasattr(response, 'content') else str(response)
        for m in re.finditer(r'TOOL:\s*(\w+)', text, re.IGNORECASE):
            name = m.group(1)
            result[name] = []
        for m in re.finditer(r'ARGUMENTS:\s*(\{[^}]*\})', text, re.IGNORECASE):
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

    @staticmethod
    def _inject_tool_trace(decision: dict, tool_trace: list[dict], obs: Observation) -> None:
        """Inject tool trace and auto-injected strategy IDs into the decision dict."""
        decision["_tool_trace"] = tool_trace
        player_id = str(getattr(obs, "player_id", "") or "")
        with _STRATEGY_LOCK:
            auto_injected = _LAST_RETRIEVED_STRATEGIES.pop(player_id, [])
        decision["_auto_injected_strategies"] = [
            s.get("doc_id", "") for s in auto_injected
        ]
        # Extract tool-called strategy doc_ids from the tool trace and merge
        tool_called_ids: list[str] = []
        for entry in tool_trace:
            if entry.get("tool") == "search_strategies":
                for did in entry.get("doc_ids", []):
                    if did and did not in tool_called_ids:
                        tool_called_ids.append(did)
        merged_ids = list(dict.fromkeys(
            decision["_auto_injected_strategies"] + tool_called_ids
        ))
        with _STRATEGY_LOCK:
            _LAST_LOOP_TRACE[player_id] = {
                "tool_trace": tool_trace,
                "auto_injected_strategies": decision["_auto_injected_strategies"],
                "retrieved_knowledge_ids": merged_ids,
            }

    def _parse_decision(self, response: str) -> Optional[Dict[str, str]]:
        """Parse final decision from LLM response.

        Expected format:
          DECISION: {"speech": "..."}  or  DECISION: {"target": "...", "reasoning": "..."}

        Uses balanced-brace extraction (not regex [^}]*) so that speech content
        containing '}' characters (emoji, punctuation) doesn't truncate the JSON.
        Falls back to salvaging partial text when JSON is truncated by token limits.
        """
        # Find DECISION: marker
        marker_match = re.search(r'DECISION:\s*', response, re.IGNORECASE)
        if not marker_match:
            return None

        start = marker_match.end()
        while start < len(response) and response[start] in ' \t\n\r':
            start += 1
        if start >= len(response) or response[start] != '{':
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
            if ch == '\\':
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
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
                logger.warning(
                    f"Salvaged partial decision JSON (original parse failed). "
                    f"Salvaged {len(salvaged.get('speech', salvaged.get('target', '')))} chars."
                )
                return salvaged
            logger.warning(f"Failed to parse decision JSON: {json_str[:100]}")
            return None

        result: Dict[str, str] = {}
        if self._action_type == "speech":
            result["speech"] = data.get("speech", data.get("content", ""))
            result["reasoning"] = data.get("reasoning", "")
            if not result["speech"]:
                text = response[:marker_match.start()].strip()
                if len(text) > 10:
                    result["speech"] = text[:500]
        else:
            result["target"] = data.get("target", "")
            result["reasoning"] = data.get("reasoning", "")

        return result if any(v for v in result.values()) else None

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
                val = val.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t')
                result[key] = val
        # If we couldn't extract speech but the JSON has content after "speech":
        if not result and '"speech"' in json_str:
            m = re.search(r'"speech"\s*:\s*"(.*)', json_str, re.DOTALL)
            if m:
                raw = m.group(1).rstrip('"').rstrip('\\')
                if len(raw) > 5:
                    result["speech"] = raw[:500]
        return result if result else None


def _build_track_c_strategy_block(obs: Observation, action_type: str) -> str:
    """Format DB-backed Track C lessons for the strategy layer.

    This is intentionally separate from role/persona/task prompts: it may
    contain gameplay advice, but only when the knowledge store returns approved
    lessons from prior reviews.
    """
    lessons = _retrieve_track_c_strategy_lessons(obs, action_type)
    if not lessons:
        return ""

    lines = [
        "【策略层：Track C 复盘知识】",
        "以下内容来自已发布复盘/策略知识库，只能作为一般玩法经验；不能当成本局隐藏身份事实。",
    ]
    for index, item in enumerate(lessons[:3], start=1):
        doc_id = str(item.get("doc_id") or item.get("id") or f"lesson-{index}")
        trigger = str(
            item.get("trigger")
            or item.get("situation_pattern")
            or item.get("trigger_conditions")
            or ""
        ).strip()
        recommendation = str(
            item.get("recommendation")
            or item.get("recommended_action")
            or item.get("strategy")
            or ""
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
            detail_parts.append(f"建议：{recommendation}")
        if avoid:
            detail_parts.append(f"避免：{avoid}")
        if rationale:
            detail_parts.append(f"依据：{rationale}")
        if detail_parts:
            lines.append(f"{index}. [{doc_id}{label_str}{score_text}] " + "；".join(detail_parts))
    return "\n".join(lines) if len(lines) > 2 else ""


def _retrieve_track_c_strategy_lessons(obs: Observation, action_type: str) -> list[dict[str, Any]]:
    """Retrieve Track C lessons without making prompt construction fragile."""
    try:
        from backend.db.persist import list_strategy_knowledge

        phase = str(getattr(obs, "phase", "") or "")
        role = str(getattr(obs, "player_role", "") or "")
        action = _strategy_query_action(action_type)
        cache_ttl = float(os.getenv("TRACK_C_AUTO_RETRIEVAL_CACHE_SECONDS", "120") or 0)
        cache_key = (role, phase, action)
        if cache_ttl > 0:
            cached = _TRACK_C_RETRIEVAL_CACHE.get(cache_key)
            now = time.monotonic()
            if cached and now - cached[0] <= cache_ttl:
                return [dict(row) for row in cached[1]]
        rows = list_strategy_knowledge(role=role, phase=phase, status=None, limit=3)
        if len(rows) < 3:
            seen = {str(row.get("doc_id") or row.get("id") or "") for row in rows}
            for row in list_strategy_knowledge(role=role, status=None, limit=6):
                row_id = str(row.get("doc_id") or row.get("id") or "")
                if row_id and row_id not in seen:
                    rows.append(row)
                    seen.add(row_id)
                if len(rows) >= 3:
                    break
        lessons = [_normalize_strategy_row(row, index) for index, row in enumerate(rows, start=1) if isinstance(row, dict)]
        if cache_ttl > 0:
            _TRACK_C_RETRIEVAL_CACHE[cache_key] = (time.monotonic(), lessons)
        if lessons:
            player_id = str(getattr(obs, "player_id", "") or "")
            _LAST_RETRIEVED_STRATEGIES[player_id] = lessons
        elif os.getenv("REQUIRE_STRATEGY_USAGE_TRACE", "").lower() == "true":
            logger.error("STRICT FAIL: Track C auto-retrieval returned no strategies")
        return lessons
    except Exception as exc:
        logger.debug("Track C strategy retrieval skipped: %s", exc)
        return []


def _strategy_query_action(action_type: str) -> str:
    if action_type == "speech":
        return "talk"
    if action_type == "night":
        return "night_action"
    return action_type


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
    }
