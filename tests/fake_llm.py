"""Fake LLM client for tests ONLY — NOT for production use.

This module is ONLY importable from tests/. The production code paths
(backend/llm/__init__.py, backend/agents/factory.py) no longer accept
provider="fake". Tests that need a deterministic LLM should import
FakeLLMClient directly from here.
"""

from __future__ import annotations

import json
import re
from typing import Any

# NOTE: This class was moved from backend/llm/__init__.py to tests/
# to prevent accidental use of fake LLM in production games or experiments.
# When LLM_PROVIDER=fake is set, the system now raises a clear error
# instead of silently using deterministic fake responses.


class FakeLLMClient:
    """Deterministic local LLM-compatible client for CI and smoke tests.

    Usage in tests:
        from tests.fake_llm import FakeLLMClient
        fake_llm = FakeLLMClient()
    """

    def __init__(self, model: str = "fake-llm"):
        self.provider = "fake"
        self.model = model
        self.base_url = "local://fake-llm"
        self.timeout = 12.0
        self.available = True
        self.call_count = 0

    def chat_sync(self, messages: list[dict], **kwargs: Any) -> dict[str, Any]:
        self.call_count += 1
        text = "\n".join(str(message.get("content", "")) for message in messages)
        target = self._target_from_prompt(text)
        tools = kwargs.get("tools") or []
        tool_choice = kwargs.get("tool_choice")
        forced_tool = self._forced_tool_name(tool_choice)
        tool_names = [
            str((tool.get("function") or {}).get("name") or "")
            for tool in tools
            if isinstance(tool, dict)
        ]
        if forced_tool == "submit_decision" or (
            "submit_decision" in tool_names and tool_names == ["submit_decision"]
        ):
            return self._tool_call_response(
                "submit_decision", self._decision_args(text, target)
            )
        if (
            tools
            and "submit_decision" in tool_names
            and "recall_memory" in tool_names
            and "【任务：发言】" in text
        ):
            return self._tool_call_response(
                "recall_memory", {"filter": "all", "target_player": ""}
            )
        if "=== 复盘任务 ===" in text or '"what_worked"' in text:
            content = json.dumps(
                {
                    "what_worked": ["遵守了当前阶段的合法目标集合，所有行动都有可审计理由。"],
                    "what_failed": ["发言和投票之间的承接还可以更具体，减少泛泛表态。"],
                    "patterns_discovered": ["合法目标约束进入提示后，决策更容易保持规则一致。"],
                    "mistakes_to_avoid": ["不要选择不在合法目标列表中的玩家。"],
                    "key_insight": "后续对局要先确认可见事实和合法目标，再给出角色行动。",
                    "confidence": 0.7,
                },
                ensure_ascii=False,
            )
        elif "输出 JSON" in text:
            content = json.dumps(
                {"target": target, "reasoning": "fake LLM direct-call decision"},
                ensure_ascii=False,
            )
        elif "【任务：发言】" in text:
            seer_target = self._seer_strategy_target(text)
            speech = (
                f"我是预言家，我的查验结果指向 {seer_target} 是狼人，今天先把票压到 {seer_target}。"
                if seer_target
                else f"我先按公开信息发言，重点观察 {target} 的站边和票型。"
            )
            content = "DECISION: " + json.dumps(
                {"speech": speech, "reasoning": "fake LLM speech decision"},
                ensure_ascii=False,
            )
        else:
            content = "DECISION: " + json.dumps(
                {"target": target, "reasoning": "fake LLM target decision"},
                ensure_ascii=False,
            )
        return {
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "_latency_ms": 0,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    async def chat(self, messages: list[dict], **kwargs: Any) -> dict[str, Any]:
        return self.chat_sync(messages, **kwargs)

    @staticmethod
    def _forced_tool_name(tool_choice: Any) -> str:
        if not isinstance(tool_choice, dict):
            return ""
        fn = tool_choice.get("function")
        if isinstance(fn, dict):
            return str(fn.get("name") or "")
        return ""

    @staticmethod
    def _tool_call_response(name: str, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": f"fake_call_{name}",
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": json.dumps(args, ensure_ascii=False),
                                },
                            }
                        ],
                    },
                }
            ],
            "_latency_ms": 0,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    @staticmethod
    def _decision_args(text: str, target: str) -> dict[str, str]:
        if "【任务：发言】" in text:
            seer_target = FakeLLMClient._seer_strategy_target(text)
            speech = (
                f"我是预言家，我的查验结果指向 {seer_target} 是狼人，今天先把票压到 {seer_target}。"
                if seer_target
                else f"我先按公开信息发言，重点观察 {target} 的站边和票型。"
            )
            return {"speech": speech, "reasoning": "fake LLM native-FC speech decision"}
        return {"target": target, "reasoning": "fake LLM native-FC target decision"}

    @staticmethod
    def _target_from_prompt(text: str) -> str:
        self_match = re.search(r"你是\s+@?\d+号[:：]([^，,\n]+)", text)
        self_name = self_match.group(1).strip() if self_match else ""
        seer_target = FakeLLMClient._seer_strategy_target(text)
        legal_matches = re.findall(r"合法目标[:：]\s*([^\n]+)", text)
        if legal_matches:
            legal_names = [
                name.strip()
                for name in re.findall(r"@?\d+号[:：]([^，,\n]+)", legal_matches[-1])
            ]
            if seer_target and seer_target in legal_names:
                return seer_target
            pressure_target = FakeLLMClient._public_pressure_target(text, legal_names)
            if pressure_target:
                return pressure_target
            for name in legal_names:
                if name and name != self_name:
                    return name
            if legal_names:
                return legal_names[0]
        names = [name.strip() for name in re.findall(r"@?\d+号[:：]([^，,\n]+)", text)]
        for name in names:
            if name and name != self_name:
                return name
        return names[0] if names else "1号"

    @staticmethod
    def _seer_strategy_target(text: str) -> str:
        if "【本局强制策略规则" not in text:
            return ""
        if not any(
            token in text
            for token in ("wolf check", "查杀", "查验结果", "confirmed information")
        ):
            return ""
        if not re.search(
            r"is_wolf['\"]?\s*:\s*True|is_wolf['\"]?\s*:\s*true", text
        ):
            return ""
        match = re.search(r"target_name['\"]?\s*:\s*['\"]([^'\"]+)['\"]", text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _public_pressure_target(text: str, legal_names: list[str]) -> str:
        for name in legal_names:
            if not name:
                continue
            escaped = re.escape(name)
            if re.search(rf"(查杀|票压到|归票|指向)\s*{escaped}", text):
                return name
            if re.search(rf"{escaped}\s*(是|为)?\s*狼人", text):
                return name
        return ""
