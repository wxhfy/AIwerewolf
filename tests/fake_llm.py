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
        tool_names = [str((tool.get("function") or {}).get("name") or "") for tool in tools if isinstance(tool, dict)]
        if forced_tool == "submit_decision" or ("submit_decision" in tool_names and tool_names == ["submit_decision"]):
            return self._tool_call_response("submit_decision", self._decision_args(text, target))
        if tools and "submit_decision" in tool_names and "recall_memory" in tool_names and "【任务：发言】" in text:
            return self._tool_call_response("recall_memory", {"filter": "all", "target_player": ""})
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
        elif self._is_witch_decision_prompt(text):
            content = json.dumps(self._witch_decision(text, target), ensure_ascii=False)
        elif "输出 JSON" in text:
            content = json.dumps(
                {"target": target, "reasoning": self._reasoning(text, target, "direct-call")},
                ensure_ascii=False,
            )
        elif "【任务：发言】" in text:
            seer_target = self._seer_strategy_target(text)
            speech = self._speech_decision(text, target, seer_target)
            content = "DECISION: " + json.dumps(
                {"speech": speech, "reasoning": self._reasoning(text, target, "speech")},
                ensure_ascii=False,
            )
        else:
            content = "DECISION: " + json.dumps(
                {"target": target, "reasoning": self._reasoning(text, target, "target")},
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
            speech = FakeLLMClient._speech_decision(text, target, seer_target)
            args = {
                "speech": speech,
                "reasoning": FakeLLMClient._reasoning(text, target, "native-FC speech"),
            }
            tentative = FakeLLMClient._strategy_target(text, FakeLLMClient._legal_names(text))
            if tentative:
                args["tentative_vote"] = tentative
            return args
        return {"target": target, "reasoning": FakeLLMClient._reasoning(text, target, "native-FC target")}

    @staticmethod
    def _target_from_prompt(text: str) -> str:
        self_match = re.search(r"你是\s+@?\d+号[:：]([^，,\n]+)", text)
        self_name = self_match.group(1).strip() if self_match else ""
        seer_target = FakeLLMClient._seer_strategy_target(text)
        legal_matches = re.findall(r"合法目标[:：]\s*([^\n]+)", text)
        if legal_matches:
            legal_names = FakeLLMClient._legal_names(text)
            role = FakeLLMClient._self_role(text)
            checked_good = FakeLLMClient._checked_good_names(text, legal_names) if role != "Werewolf" else set()
            available = [name for name in legal_names if name not in checked_good]
            if seer_target and seer_target in available:
                return seer_target
            strategy_target = FakeLLMClient._strategy_target(text, legal_names)
            if strategy_target:
                return strategy_target
            pressure_target = FakeLLMClient._public_pressure_target(text, available or legal_names)
            if pressure_target:
                return pressure_target
            if checked_good and available:
                return available[-1]
            for name in available or legal_names:
                if name and name != self_name:
                    return name
            if legal_names:
                return legal_names[0]
        names = [name.strip() for name in re.findall(r"@?\d+号[:：]([^，,\n]+)", text)]
        strategy_names = FakeLLMClient._alive_names(text) or names
        if strategy_names:
            strategy_target = FakeLLMClient._strategy_target(text, strategy_names)
            if strategy_target and strategy_target != self_name:
                return strategy_target
        for name in names:
            if name and name != self_name:
                return name
        return names[0] if names else "1号"

    @staticmethod
    def _seer_strategy_target(text: str) -> str:
        if "【本局强制策略规则" not in text:
            return ""
        if not any(token in text for token in ("wolf check", "查杀", "查验结果", "confirmed information")):
            return ""
        if not re.search(r"is_wolf['\"]?\s*:\s*True|is_wolf['\"]?\s*:\s*true", text):
            return ""
        match = re.search(r"target_name['\"]?\s*:\s*['\"]([^'\"]+)['\"]", text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _has_strategy_bias(text: str) -> bool:
        return "【本局强制策略规则" in text

    @staticmethod
    def _self_role(text: str) -> str:
        match = re.search(r"你是\s+@?\d+号[:：][^，,\n]+，身份=([A-Za-z_]+)", text)
        return match.group(1) if match else ""

    @staticmethod
    def _legal_names(text: str) -> list[str]:
        legal_matches = re.findall(r"合法目标[:：]\s*([^\n]+)", text)
        if not legal_matches:
            return []
        return [name.strip() for name in re.findall(r"@?\d+号[:：]([^，,\n]+)", legal_matches[-1]) if name.strip()]

    @staticmethod
    def _alive_names(text: str) -> list[str]:
        matches = re.findall(r"存活[:：]\s*([^\n]+)", text)
        if not matches:
            return []
        return [name.strip() for name in re.findall(r"@?\d+号[:：]([^，,\n]+)", matches[-1]) if name.strip()]

    @staticmethod
    def _checked_good_names(text: str, legal_names: list[str]) -> set[str]:
        checked: set[str] = set()
        for name in legal_names:
            escaped = re.escape(name)
            good_terms = r"金水|已查的好人|已验好人|确认好人|confirmed good|checked-good"
            # Use restricted character class to avoid matching across clause boundaries
            # (，、：) which would create false positives like "Alice：Bob 是金水"
            if re.search(rf"{escaped}[^。，、：\n]*({good_terms})", text):
                checked.add(name)
            if re.search(rf"({good_terms})[^。，、：\n]*{escaped}", text):
                checked.add(name)
            if re.search(
                rf"target_name['\"]?\s*:\s*['\"]{escaped}['\"][^}}\n]*is_wolf['\"]?\s*:\s*(False|false)",
                text,
            ):
                checked.add(name)
            if re.search(
                rf"is_wolf['\"]?\s*:\s*(False|false)[^}}\n]*target_name['\"]?\s*:\s*['\"]{escaped}['\"]",
                text,
            ):
                checked.add(name)
        return checked

    @staticmethod
    def _wolf_teammate_names(text: str, legal_names: list[str]) -> set[str]:
        teammates: set[str] = set()
        teammate_lines = re.findall(r"(?:狼队友|known_wolves)[:：]\s*([^\n]+)", text)
        if not teammate_lines:
            return teammates
        teammate_line = " ".join(teammate_lines)
        for name in legal_names:
            if name and name in teammate_line:
                teammates.add(name)
        return teammates

    @staticmethod
    def _role_claim_targets(text: str, legal_names: list[str]) -> list[str]:
        claimed: list[str] = []
        for line in text.splitlines():
            speaker = re.match(r"\s*@?\d+号[:：]([^：:，,\n]+)[：:](.*)", line)
            if not speaker:
                continue
            name = speaker.group(1).strip()
            speech = speaker.group(2)
            if name in legal_names and any(role in speech for role in ("预言家", "女巫", "猎人", "守卫")):
                claimed.append(name)
        return claimed

    @staticmethod
    def _named_power_targets(legal_names: list[str]) -> list[str]:
        power_tokens = ("Seer", "预言", "Witch", "女巫", "Hunter", "猎人", "Guard", "守卫")
        return [name for name in legal_names if any(token in name for token in power_tokens)]

    @staticmethod
    def _plain_villager_targets(legal_names: list[str]) -> list[str]:
        power_tokens = ("Seer", "预言", "Witch", "女巫", "Hunter", "猎人", "Guard", "守卫")
        return [name for name in legal_names if not any(token in name for token in power_tokens)]

    @staticmethod
    def _strategy_target(text: str, legal_names: list[str]) -> str:
        if not FakeLLMClient._has_strategy_bias(text) or not legal_names:
            return ""
        role = FakeLLMClient._self_role(text)
        checked_good = FakeLLMClient._checked_good_names(text, legal_names)
        teammates = FakeLLMClient._wolf_teammate_names(text, legal_names) if role == "Werewolf" else set()
        available = [name for name in legal_names if name not in checked_good]
        if teammates:
            available = [name for name in available if name not in teammates]

        pressure_target = FakeLLMClient._public_pressure_target(text, legal_names)
        if pressure_target and pressure_target not in checked_good and pressure_target not in teammates:
            return pressure_target

        is_night = "【任务：夜晚行动】" in text

        if role == "Seer":
            if is_night and available:
                # Check unverified players first (strategic: prefer unchecked over checked-good)
                unchecked = [n for n in available if n not in checked_good]
                return unchecked[0] if unchecked else available[0]
            if available:
                return available[0]
        elif role == "Werewolf":
            if is_night:
                plain = FakeLLMClient._plain_villager_targets(available)
                if plain:
                    return plain[0]
            claimed = [name for name in FakeLLMClient._role_claim_targets(text, legal_names) if name not in teammates]
            if claimed:
                return claimed[0]
            named_power = [name for name in FakeLLMClient._named_power_targets(legal_names) if name not in teammates]
            if named_power:
                return named_power[0]
        elif role == "Guard":
            return available[-1] if available else legal_names[-1]
        elif role == "Witch":
            claimed = FakeLLMClient._role_claim_targets(text, legal_names)
            if claimed:
                return claimed[0]
            if available:
                return available[0]
        elif role == "Hunter":
            if available:
                return available[0]
        if available:
            return available[-1]
        return legal_names[-1]

    @staticmethod
    def _speech_decision(text: str, target: str, seer_target: str = "") -> str:
        if seer_target:
            return f"我是预言家，我的查验结果指向 {seer_target} 是狼人，今天先把票压到 {seer_target}。"
        if FakeLLMClient._has_strategy_bias(text):
            role = FakeLLMClient._self_role(text)
            if role == "Werewolf":
                return f"我从公开票型看，{target} 的站边最容易带乱好人，今天建议归票 {target}。"
            return f"我按公开发言和票型判断，{target} 的嫌疑最高，今天建议归票 {target}。"
        return f"我先按公开信息发言，重点观察 {target} 的站边和票型。"

    @staticmethod
    def _reasoning(text: str, target: str, source: str) -> str:
        if FakeLLMClient._has_strategy_bias(text):
            return f"fake LLM {source} strategy-aware decision targeting {target}"
        return f"fake LLM {source} decision"

    @staticmethod
    def _is_witch_decision_prompt(text: str) -> bool:
        return "你是女巫" in text and "poison_target" in text and "save" in text

    @staticmethod
    def _witch_decision(text: str, target: str) -> dict[str, Any]:
        if "今晚被刀的是:" in text and "解药可用" in text:
            return {
                "reasoning": "fake LLM witch role-task strategy saves the visible night victim",
                "save": True,
                "poison_target": None,
            }
        if not FakeLLMClient._has_strategy_bias(text):
            return {"reasoning": "fake LLM witch baseline holds potions", "save": False, "poison_target": None}
        if "毒药可用" in text and target:
            return {
                "reasoning": f"fake LLM witch strategy poisons public pressure target {target}",
                "save": False,
                "poison_target": target,
            }
        return {
            "reasoning": "fake LLM witch strategy holds potions without a legal target",
            "save": False,
            "poison_target": None,
        }

    @staticmethod
    def _public_pressure_target(text: str, legal_names: list[str]) -> str:
        for name in legal_names:
            if not name:
                continue
            escaped = re.escape(name)
            if re.search(rf"(查杀|票压到|归票|指向|狼坑|投\s*{escaped})\s*{escaped}", text):
                return name
            if re.search(rf"{escaped}\s*(是|为)?\s*狼人", text):
                return name
            if re.search(rf"{escaped}[^。，、：\n]*?(嫌疑|可疑|像狼|铁狼|标狼)", text):
                return name
        return ""
