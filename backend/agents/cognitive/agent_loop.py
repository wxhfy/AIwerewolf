"""Agent Loop — tool-calling cognitive loop with self-termination.

Replaces the fixed 3-step Chain (Observe→Think→Act) with an autonomous
agent loop where the LLM decides:
  - Whether to call tools (search_strategies, recall_memory, etc.)
  - In what order
  - When it has enough information → output Decision

Based on Anthropic's "Building Effective Agents" pattern:
  while not ready: think → maybe call tools → think again → decide

No LangGraph dependency — just a Python while-loop. Radical simplicity.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable

from backend.agents.cognitive.memory import Memory
from backend.agents.cognitive.observe import Observation, format_observation
from backend.agents.cognitive.prompts import build_game_context
from backend.agents.cognitive.tools import create_tools

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 3


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
    ):
        self._llm = llm
        self._system_prompt = system_prompt
        self._action_type = action_type
        self._strategy_bias = strategy_bias or {}

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
        context = []  # list of (role, content) for the conversation

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

            response = self._call_llm(context)

            # Try to parse tool calls first
            tool_results = self._parse_tool_calls(response, tools)
            if tool_results:
                logger.info(
                    f"Iter {iteration}/{MAX_ITERATIONS}: {len(tool_results)} tool call(s) - "
                    f"{', '.join(t.split(chr(10))[0][:80] for t in tool_results)}"
                )
                # Append assistant response + tool results to context
                context.append(HumanMessage(content=response))
                for tr in tool_results:
                    context.append(HumanMessage(content=f"[工具结果]\n{tr}"))
                context.append(HumanMessage(
                    content="(工具结果已返回。请继续分析，或输出 DECISION 做最终决策。)"
                ))
                if iteration >= MAX_ITERATIONS:
                    last_tool_results = True
                continue

            # No tool calls — try to parse decision
            decision = self._parse_decision(response)
            if decision:
                keys = list(decision.keys())
                logger.info(f"Iter {iteration}/{MAX_ITERATIONS}: DECISION found ({keys})")
                return decision

            # Neither tool call nor valid decision — ask LLM to be clearer
            preview = response[:150].replace('\n', '\\n')
            logger.info(
                f"Iter {iteration}/{MAX_ITERATIONS}: no TOOL or DECISION found. "
                f"Response preview: {preview}..."
            )
            context.append(HumanMessage(content=response))
            context.append(HumanMessage(content=(
                "请明确选择：调用 TOOL 获取更多信息，或输出 DECISION 做最终决策。"
                "工具: search_strategies, recall_memory, check_rules, analyze_votes"
            )))

        # Tool results were added in the last iteration — give LLM one more
        # chance to see the results and produce a DECISION.
        if last_tool_results:
            response = self._call_llm(context)
            decision = self._parse_decision(response)
            if decision:
                logger.info(f"Final call: DECISION found ({list(decision.keys())})")
                return decision

        # Max iterations reached — parse best-effort decision
        logger.warning(f"AgentLoop hit max iterations ({MAX_ITERATIONS}), forcing decision")
        if self._action_type == "speech":
            return {"reasoning": "达到最大思考轮次", "speech": "我选择跳过。"}
        else:
            return {"reasoning": "达到最大思考轮次", "target": ""}

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

        # Action task
        blocks.append(self._task_for_action())

        # ═══════════════════════════════════════════════════════
        # LAYER 3: Strategy — on-demand tools
        # ═══════════════════════════════════════════════════════
        blocks.append(self._format_tools(tools))

        # Output format
        blocks.append(self._output_format())

        return "\n\n".join(blocks)

    def _build_initial_user(self, obs: Observation, cached_analysis: str) -> str:
        """Build the first user message that kicks off the thinking loop."""
        if cached_analysis:
            return (
                f"当前阶段: {obs.phase}。你已有上轮分析结果。"
                "如需补充信息可以调用工具，否则直接输出 DECISION。"
            )
        return (
            f"当前阶段: {obs.phase}。"
            "请分析局势，需要时调用工具获取策略/记忆/规则信息，准备好后输出 DECISION。"
        )

    def _task_for_action(self) -> str:
        """Return the action-specific task description."""
        tasks = {
            "speech": (
                "【任务：发言】\n"
                "生成一段自然、有策略的狼人杀发言。\n"
                "- 用中文发言\n"
                "- 用「X号」称呼玩家，不要说「X号玩家」\n"
                "- 不要当主持人报幕，直接以玩家身份发言\n"
                "- 可以分析局势、带节奏、表水或隐藏身份（根据你的角色决定）\n"
            ),
            "vote": (
                "【任务：投票】\n"
                "选择一个存活玩家投票放逐。\n"
                "- 指出你要投谁（target）\n"
                "- 给出简短的投票理由（reasoning）\n"
            ),
            "night": (
                "【任务：夜晚行动】\n"
                "选择一个目标执行你的夜晚能力。\n"
                "- 指出目标（target）\n"
                "- 给出行动理由（reasoning）\n"
            ),
        }
        return tasks.get(self._action_type, tasks["speech"])

    def _format_tools(self, tools: Dict[str, Any]) -> str:
        """Format tool descriptions for the system prompt."""
        lines = ["【可用工具】", "需要更多信息时，用以下格式调用工具："]
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
        fmt += (
            "\n"
            "注意: 每次回复只能选择 TOOL 或 DECISION 之一，不要同时输出两者。\n"
            f"最多 {MAX_ITERATIONS} 轮工具调用后必须输出 DECISION。"
        )
        return fmt

    # ================================================================
    # LLM Call
    # ================================================================

    def _call_llm(self, messages: list) -> str:
        """Call the LLM with the message list. Simple retry on failure."""
        for attempt in range(2):
            try:
                resp = self._llm.invoke(messages)
                content = resp.content.strip()
                if content and len(content) > 5:
                    return content
            except Exception as e:
                logger.warning(f"LLM call failed (attempt {attempt+1}): {e}")
        return "[LLM error: no response]"

    # ================================================================
    # Parsing
    # ================================================================

    def _parse_tool_calls(self, response: str, tools: Dict[str, Any]) -> List[str]:
        """Parse tool calls from LLM response.

        Expected format:
          TOOL: search_strategies
          ARGUMENTS: {"keywords": [...], "limit": 3}

        Returns list of tool result strings, or empty list if no tool calls found.
        """
        # Match TOOL: <name> ... ARGUMENTS: <json>
        # [^}]* allows empty JSON objects like {}
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

            if tool_name not in tools:
                results.append(f"未知工具: {tool_name}。可用工具: {', '.join(tools.keys())}")
                continue

            try:
                fn = tools[tool_name]["fn"]
                result = fn(**args)
                results.append(f"[{tool_name}]\n{result}")
            except Exception as e:
                results.append(f"[{tool_name}] 执行失败: {e}")

        return results

    def _parse_decision(self, response: str) -> Optional[Dict[str, str]]:
        """Parse final decision from LLM response.

        Expected format:
          DECISION: {"speech": "..."}  or  DECISION: {"target": "...", "reasoning": "..."}

        Returns decision dict or None.
        """
        m = re.search(r'DECISION:\s*(\{[^}]*\})', response, re.IGNORECASE)
        if not m:
            return None

        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse decision JSON: {m.group(1)[:100]}")
            return None

        result: Dict[str, str] = {}
        if self._action_type == "speech":
            result["speech"] = data.get("speech", data.get("content", ""))
            result["reasoning"] = data.get("reasoning", "")
            if not result["speech"]:
                # Try to extract speech from surrounding text
                text = response.replace(m.group(0), "").strip()
                if len(text) > 10:
                    result["speech"] = text[:500]
        else:
            result["target"] = data.get("target", "")
            result["reasoning"] = data.get("reasoning", "")

        return result if any(v for v in result.values()) else None
