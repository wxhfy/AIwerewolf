from __future__ import annotations

import json
import re
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from backend.agents.characters import Character
from backend.agents.characters import Persona
from backend.agents.characters import PlayerMind
from backend.agents.cognitive import agent_loop
from backend.agents.cognitive import trace_keys
from backend.agents.cognitive.agent import CognitiveAgent
from backend.agents.cognitive.agent_loop import AgentLoop
from backend.agents.cognitive.factory import create_cognitive_agent_with_character
from backend.agents.cognitive.memory import ActionRecord
from backend.agents.cognitive.memory import Memory
from backend.agents.cognitive.observe import Contradiction
from backend.agents.cognitive.observe import Observation
from backend.agents.cognitive.observe import PlayerInfo
from backend.agents.cognitive.observe import RoleClaim
from backend.agents.cognitive.observe import SpeechInfo
from backend.agents.cognitive.observe import observe
from backend.agents.cognitive.profiles import get_profile
from backend.agents.cognitive.reflect import Reflector
from backend.agents.cognitive.reflect import reflections_to_knowledge_docs
from backend.agents.cognitive.repository import _profile_from_role_card_row
from backend.agents.cognitive.repository import _profiles_from_role_rows
from backend.agents.cognitive.repository import _role_goal_from_row
from backend.agents.cognitive.repository import load_profile_from_db
from backend.agents.cognitive.repository import load_profiles_from_db
from backend.engine.game import WerewolfGame
from backend.engine.models import ActionType
from backend.engine.models import EventType
from backend.engine.models import Phase
from backend.engine.rules import build_players
from backend.engine.rules import get_role_configuration
from backend.engine.visibility import PlayerView


class DeterministicCognitiveLLM:
    """Tiny fake LLM that exercises AgentLoop parsing without external APIs."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def invoke(self, messages):
        text = "\n".join(str(getattr(message, "content", message)) for message in messages)
        self.calls.append(text)
        target = self._target_from_prompt(text)

        if "输出 JSON" in text:
            return AIMessage(
                content=json.dumps(
                    {
                        "target": target,
                        "reasoning": "offline direct-call decision",
                    },
                    ensure_ascii=False,
                )
            )

        if "【任务：发言】" in text:
            return AIMessage(
                content="DECISION: "
                + json.dumps(
                    {
                        "speech": f"我先按公开信息发言，重点观察 {target} 的站边和票型。",
                        "reasoning": "offline cognitive speech",
                    },
                    ensure_ascii=False,
                )
            )

        return AIMessage(
            content="DECISION: "
            + json.dumps(
                {
                    "target": target,
                    "reasoning": "offline cognitive target",
                },
                ensure_ascii=False,
            )
        )

    @staticmethod
    def _target_from_prompt(text: str) -> str:
        self_match = re.search(r"你是\s+\d+号:([^，\n]+)", text)
        self_name = self_match.group(1).strip() if self_match else ""
        legal_match = re.search(r"合法目标[:：]\s*([^\n]+)", text)
        if legal_match:
            legal_names = [name.strip() for name in re.findall(r"\d+号:([^，\n]+)", legal_match.group(1))]
            for name in legal_names:
                if name and name != self_name:
                    return name
            if legal_names:
                return legal_names[0]
        names = [name.strip() for name in re.findall(r"\d+号:([^，\n]+)", text)]
        for name in names:
            if name and name != self_name:
                return name
        return names[0] if names else "P1"


class _FakeProfileCursor:
    def __init__(self, rows) -> None:
        self.closed = False
        self.executed = ""
        self._rows = rows

    def execute(self, query: str) -> None:
        self.executed = query

    def fetchall(self):
        return self._rows

    def close(self) -> None:
        self.closed = True


class _FakeProfileConnection:
    def __init__(self, rows) -> None:
        self.closed = False
        self.cursor_obj = _FakeProfileCursor(rows)

    def cursor(self) -> _FakeProfileCursor:
        return self.cursor_obj

    def close(self) -> None:
        self.closed = True


def _install_fake_profile_db(monkeypatch: pytest.MonkeyPatch, rows) -> _FakeProfileConnection:
    fake_conn = _FakeProfileConnection(rows)
    monkeypatch.setitem(sys.modules, "psycopg2", SimpleNamespace(connect=lambda _: fake_conn))
    return fake_conn


class ProviderModelLLM:
    provider = "unit-provider"
    model = "unit-model"

    def invoke(self, messages, **kwargs):
        return AIMessage(content='DECISION: {"target": "Bob", "reasoning": "provider model fake"}')


class NonDecisionLLM:
    def invoke(self, messages):
        return AIMessage(content="我还需要继续想想，但没有按格式输出。")


class BadWitchLLM:
    def invoke(self, messages, **kwargs):
        return AIMessage(content="今晚我再想想，不输出结构化 JSON。")


class UsedAntidoteThenSkipWitchLLM:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(content='{"reasoning": "I want to save again", "save": true, "poison_target": null}')
        return AIMessage(
            content='{"reasoning": "antidote already used, skip tonight", "save": false, "poison_target": null}'
        )


class EmptySpeechLLM:
    def invoke(self, messages, **kwargs):
        return AIMessage(content='DECISION: {"speech": "", "reasoning": "empty speech"}')


class InvalidDirectTargetLLM:
    def invoke(self, messages, **kwargs):
        return AIMessage(content='{"target": "不存在的玩家", "reasoning": "invalid target"}')


class SkipThenValidShootLLM:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(content='{"target": "无", "reasoning": "initially tried to skip"}')
        return AIMessage(content='{"target": "Bob", "reasoning": "repair selects a legal target"}')


class InvalidNightTargetLLM:
    def invoke(self, messages, **kwargs):
        return AIMessage(content='DECISION: {"target": "狼人队友", "reasoning": "invalid wolf target"}')


class SkipNightTargetLLM:
    def invoke(self, messages, **kwargs):
        return AIMessage(content='DECISION: {"target": "跳过", "reasoning": "skip required target"}')


class EmptyThenValidNightTargetLLM:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(content='DECISION: {"target": "", "reasoning": "no target selected"}')
        return AIMessage(content='{"target": "Bob", "reasoning": "repair selects a legal night target"}')


class EmptyThenTextNightTargetLLM:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(content='DECISION: {"target": "", "reasoning": "no target selected"}')
        return AIMessage(content="我重新选择 2号:Bob，因为这是当前合法目标。")


class EmptyThenDelayedValidNightTargetLLM:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, messages, **kwargs):
        self.calls += 1
        if self.calls < 4:
            return AIMessage(content='DECISION: {"target": "", "reasoning": "still no target"}')
        return AIMessage(content='{"target": "Bob", "reasoning": "delayed repair selects legal target"}')


class InvalidThenValidBadgeLLM:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(content='{"target": "0号", "reasoning": "invalid badge target"}')
        return AIMessage(content='{"target": "Bob", "reasoning": "repair transfers badge to candidate"}')


class NativeDecisionLLM:
    """Fake native function-calling LLM that records bound tools and choices."""

    def __init__(self, bound_tools: list[dict] | None = None, calls: list[dict] | None = None) -> None:
        self.bound_tools = bound_tools or []
        self.calls = calls if calls is not None else []

    def bind_tools(self, tool_schemas: list[dict]) -> "NativeDecisionLLM":
        return NativeDecisionLLM(tool_schemas, self.calls)

    def invoke(self, messages, **kwargs):
        text = "\n".join(str(getattr(message, "content", message)) for message in messages)
        tool_names = [
            str((schema.get("function") or {}).get("name") or "")
            for schema in self.bound_tools
            if isinstance(schema, dict)
        ]
        self.calls.append(
            {
                "tool_names": tool_names,
                "force_tool_name": kwargs.get("force_tool_name"),
                "max_tokens": kwargs.get("max_tokens"),
                "text": text,
            }
        )

        if kwargs.get("force_tool_name") == "submit_decision" or tool_names == ["submit_decision"]:
            if "【任务：发言】" in text:
                args = {"speech": "我先按公开信息发言，重点观察2号的站边。", "reasoning": "native final speech"}
            else:
                args = {"target": "Bob", "reasoning": "native final target"}
            return AIMessage(
                content="",
                tool_calls=[{"id": "call_decision", "name": "submit_decision", "args": args}],
            )

        assert "recall_memory" in tool_names
        return AIMessage(
            content="",
            tool_calls=[{"id": "call_memory", "name": "recall_memory", "args": {"filter": "all"}}],
        )


class EmptyNativeThenTextDecisionLLM:
    """Native function-call attempt returns empty, then text repair succeeds."""

    def __init__(self, bound_tools: list[dict] | None = None, calls: list[dict] | None = None) -> None:
        self.bound_tools = bound_tools or []
        self.calls = calls if calls is not None else []

    def bind_tools(self, tool_schemas: list[dict]) -> "EmptyNativeThenTextDecisionLLM":
        return EmptyNativeThenTextDecisionLLM(tool_schemas, self.calls)

    def invoke(self, messages, **kwargs):
        text = "\n".join(str(getattr(message, "content", message)) for message in messages)
        tool_names = [
            str((schema.get("function") or {}).get("name") or "")
            for schema in self.bound_tools
            if isinstance(schema, dict)
        ]
        self.calls.append(
            {
                "tool_names": tool_names,
                "force_tool_name": kwargs.get("force_tool_name"),
                "text": text,
            }
        )
        if kwargs.get("force_tool_name") == "submit_decision":
            return AIMessage(content="")
        return AIMessage(content='DECISION: {"target": "Bob", "reasoning": "text repair target"}')


class PlainNativeTextThenTextDecisionLLM:
    """Native submit_decision echoes an instruction as text, then repair succeeds."""

    def __init__(self, bound_tools: list[dict] | None = None, calls: list[dict] | None = None) -> None:
        self.bound_tools = bound_tools or []
        self.calls = calls if calls is not None else []

    def bind_tools(self, tool_schemas: list[dict]) -> "PlainNativeTextThenTextDecisionLLM":
        return PlainNativeTextThenTextDecisionLLM(tool_schemas, self.calls)

    def invoke(self, messages, **kwargs):
        text = "\n".join(str(getattr(message, "content", message)) for message in messages)
        tool_names = [
            str((schema.get("function") or {}).get("name") or "")
            for schema in self.bound_tools
            if isinstance(schema, dict)
        ]
        self.calls.append(
            {
                "tool_names": tool_names,
                "force_tool_name": kwargs.get("force_tool_name"),
                "text": text,
            }
        )
        if kwargs.get("force_tool_name") == "submit_decision":
            return AIMessage(
                content="信息已足够。现在不要调用任何信息工具，只调用 submit_decision，参数必须包含 target 和 reasoning。"
            )
        return AIMessage(content='DECISION: {"target": "Bob", "reasoning": "plain text native repair target"}')


class IllegalNativeTargetThenTextDecisionLLM:
    """Native submit_decision returns a visible but illegal target, then repair succeeds."""

    def __init__(self, bound_tools: list[dict] | None = None, calls: list[dict] | None = None) -> None:
        self.bound_tools = bound_tools or []
        self.calls = calls if calls is not None else []

    def bind_tools(self, tool_schemas: list[dict]) -> "IllegalNativeTargetThenTextDecisionLLM":
        return IllegalNativeTargetThenTextDecisionLLM(tool_schemas, self.calls)

    def invoke(self, messages, **kwargs):
        text = "\n".join(str(getattr(message, "content", message)) for message in messages)
        tool_names = [
            str((schema.get("function") or {}).get("name") or "")
            for schema in self.bound_tools
            if isinstance(schema, dict)
        ]
        self.calls.append(
            {
                "tool_names": tool_names,
                "force_tool_name": kwargs.get("force_tool_name"),
                "text": text,
            }
        )
        if kwargs.get("force_tool_name") == "submit_decision":
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_illegal",
                        "name": "submit_decision",
                        "args": {"target": "6号:WolfB", "reasoning": "native picked a teammate"},
                    }
                ],
            )
        return AIMessage(content='DECISION: {"target": "Bob", "reasoning": "repair selects legal villager"}')


class NativeSpeechWithoutReasoningLLM:
    """Native submit_decision provides speech but omits reasoning."""

    def __init__(self, bound_tools: list[dict] | None = None, calls: list[dict] | None = None) -> None:
        self.bound_tools = bound_tools or []
        self.calls = calls if calls is not None else []

    def bind_tools(self, tool_schemas: list[dict]) -> "NativeSpeechWithoutReasoningLLM":
        return NativeSpeechWithoutReasoningLLM(tool_schemas, self.calls)

    def invoke(self, messages, **kwargs):
        text = "\n".join(str(getattr(message, "content", message)) for message in messages)
        tool_names = [
            str((schema.get("function") or {}).get("name") or "")
            for schema in self.bound_tools
            if isinstance(schema, dict)
        ]
        self.calls.append(
            {
                "tool_names": tool_names,
                "force_tool_name": kwargs.get("force_tool_name"),
                "text": text,
            }
        )
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call_speech_without_reasoning",
                    "name": "submit_decision",
                    "args": {"speech": "我按公开信息发言，今天先观察票型。"},
                }
            ],
        )


class InvalidNativeArgsThenTextDecisionLLM:
    """Native submit_decision has missing args, then text repair succeeds."""

    def __init__(self, bound_tools: list[dict] | None = None, calls: list[dict] | None = None) -> None:
        self.bound_tools = bound_tools or []
        self.calls = calls if calls is not None else []

    def bind_tools(self, tool_schemas: list[dict]) -> "InvalidNativeArgsThenTextDecisionLLM":
        return InvalidNativeArgsThenTextDecisionLLM(tool_schemas, self.calls)

    def invoke(self, messages, **kwargs):
        text = "\n".join(str(getattr(message, "content", message)) for message in messages)
        tool_names = [
            str((schema.get("function") or {}).get("name") or "")
            for schema in self.bound_tools
            if isinstance(schema, dict)
        ]
        self.calls.append(
            {
                "tool_names": tool_names,
                "force_tool_name": kwargs.get("force_tool_name"),
                "text": text,
            }
        )
        if kwargs.get("force_tool_name") == "submit_decision" or "submit_decision" in tool_names:
            return AIMessage(
                content="",
                tool_calls=[{"id": "call_bad", "name": "submit_decision", "args": {"speech": ""}}],
            )
        return AIMessage(
            content='DECISION: {"speech": "我用文本格式补交最终发言。", "reasoning": "text repair speech"}'
        )


class InvalidNativeArgsThenEmptyTextLLM:
    """Native submit_decision is invalid; text repair also returns no decision."""

    def __init__(self, bound_tools: list[dict] | None = None, calls: list[dict] | None = None) -> None:
        self.bound_tools = bound_tools or []
        self.calls = calls if calls is not None else []

    def bind_tools(self, tool_schemas: list[dict]) -> "InvalidNativeArgsThenEmptyTextLLM":
        return InvalidNativeArgsThenEmptyTextLLM(tool_schemas, self.calls)

    def invoke(self, messages, **kwargs):
        tool_names = [
            str((schema.get("function") or {}).get("name") or "")
            for schema in self.bound_tools
            if isinstance(schema, dict)
        ]
        self.calls.append(
            {
                "tool_names": tool_names,
                "force_tool_name": kwargs.get("force_tool_name"),
            }
        )
        if kwargs.get("force_tool_name") == "submit_decision" or "submit_decision" in tool_names:
            return AIMessage(
                content="",
                tool_calls=[{"id": "call_bad", "name": "submit_decision", "args": {"speech": ""}}],
            )
        return AIMessage(content="")


class EmptyTextRepairThenDecisionLLM:
    def __init__(self, bound_tools: list[dict] | None = None, calls: list[dict] | None = None) -> None:
        self.bound_tools = bound_tools or []
        self.calls = calls if calls is not None else []

    def bind_tools(self, tool_schemas: list[dict]) -> "EmptyTextRepairThenDecisionLLM":
        return EmptyTextRepairThenDecisionLLM(tool_schemas, self.calls)

    def invoke(self, messages, **kwargs):
        tool_names = [
            str((schema.get("function") or {}).get("name") or "")
            for schema in self.bound_tools
            if isinstance(schema, dict)
        ]
        self.calls.append({"tool_names": tool_names, "force_tool_name": kwargs.get("force_tool_name")})
        if len(self.calls) <= 2:
            return AIMessage(content="")
        return AIMessage(content='DECISION: {"speech": "我补充最终发言。", "reasoning": "empty response repair"}')


class ReasoningOnlyTargetDecisionLLM:
    """Text decision has reasoning but no target; it must not be accepted."""

    def invoke(self, messages, **kwargs):
        return AIMessage(content='DECISION: {"reasoning": "I considered guarding but did not choose a player."}')


class PartialSpeechJsonLLM:
    def invoke(self, messages, **kwargs):
        return AIMessage(content='DECISION: {"speech": "这是一段被截断但仍然可用的发言内容')


def test_trace_keys_helpers_preserve_loop_audit_contract() -> None:
    source = {
        "speech": "ignored source speech",
        trace_keys.TOOL_TRACE: [{"tool": "recall_memory"}],
        trace_keys.AUTO_INJECTED_STRATEGIES: ["auto-doc"],
        trace_keys.RETRIEVED_KNOWLEDGE_IDS: ["auto-doc", "tool-doc"],
        trace_keys.USAGE: {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
    }
    result = {"speech": "final speech", "reasoning": "final reasoning"}

    copied = trace_keys.copy_loop_result_keys(source, result)
    payload = trace_keys.compat_loop_trace_payload(
        tool_trace=source[trace_keys.TOOL_TRACE],
        auto_injected=source[trace_keys.AUTO_INJECTED_STRATEGIES],
        retrieved_ids=source[trace_keys.RETRIEVED_KNOWLEDGE_IDS],
        usage=source[trace_keys.USAGE],
    )
    usage = trace_keys.usage_metadata(source[trace_keys.USAGE])
    metadata = trace_keys.loop_metadata_from_result(source, {"speech": "final speech", "segment_count": 1})
    compat_metadata = {"speech": "compat speech"}
    compat_retrieved = trace_keys.compat_metadata_from_trace(compat_metadata, payload)
    string_metadata = {}
    string_retrieved = trace_keys.compat_metadata_from_trace(
        string_metadata,
        {
            trace_keys.COMPAT_RETRIEVED_KNOWLEDGE_IDS: "single-doc",
        },
    )
    string_auto_metadata = {}
    string_auto_retrieved = trace_keys.compat_metadata_from_trace(
        string_auto_metadata,
        {
            trace_keys.COMPAT_AUTO_INJECTED_STRATEGIES: "auto-single-doc",
        },
    )
    direct_string_auto_metadata = trace_keys.loop_metadata_from_result(
        {
            trace_keys.AUTO_INJECTED_STRATEGIES: "direct-auto-doc",
        },
    )
    direct_tool_only_metadata = trace_keys.loop_metadata_from_result(
        {
            trace_keys.RETRIEVED_KNOWLEDGE_IDS: ["tool-only-doc"],
        },
    )
    direct_ids = trace_keys.knowledge_id_list(["doc-a", "", None, "doc-b"])
    direct_string_id = trace_keys.knowledge_id_list("doc-c")

    assert copied is result
    assert copied["speech"] == "final speech"
    assert copied[trace_keys.TOOL_TRACE] == [{"tool": "recall_memory"}]
    assert copied[trace_keys.AUTO_INJECTED_STRATEGIES] == ["auto-doc"]
    assert copied[trace_keys.RETRIEVED_KNOWLEDGE_IDS] == ["auto-doc", "tool-doc"]
    assert copied[trace_keys.USAGE]["total_tokens"] == 7
    assert payload == {
        trace_keys.COMPAT_TOOL_TRACE: [{"tool": "recall_memory"}],
        trace_keys.COMPAT_AUTO_INJECTED_STRATEGIES: ["auto-doc"],
        trace_keys.COMPAT_RETRIEVED_KNOWLEDGE_IDS: ["auto-doc", "tool-doc"],
        trace_keys.COMPAT_USAGE: {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
    }
    assert usage == {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}
    assert metadata["speech"] == "final speech"
    assert metadata["segment_count"] == 1
    assert metadata[trace_keys.TOOL_TRACE] == [{"tool": "recall_memory"}]
    assert metadata[trace_keys.AUTO_INJECTED_STRATEGIES] == ["auto-doc"]
    assert metadata[trace_keys.DECISION_RETRIEVAL_USED] is True
    assert metadata[trace_keys.DECISION_RETRIEVED_KNOWLEDGE_IDS] == ["auto-doc", "tool-doc"]
    assert metadata[trace_keys.DECISION_USAGE] == {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}
    assert compat_retrieved == ["auto-doc", "tool-doc"]
    assert compat_metadata["speech"] == "compat speech"
    assert compat_metadata[trace_keys.TOOL_TRACE] == [{"tool": "recall_memory"}]
    assert compat_metadata[trace_keys.AUTO_INJECTED_STRATEGIES] == ["auto-doc"]
    assert compat_metadata[trace_keys.DECISION_RETRIEVAL_USED] is True
    assert compat_metadata[trace_keys.DECISION_RETRIEVED_KNOWLEDGE_IDS] == ["auto-doc", "tool-doc"]
    assert compat_metadata[trace_keys.DECISION_USAGE] == {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}
    assert string_retrieved == ["single-doc"]
    assert string_metadata[trace_keys.DECISION_RETRIEVED_KNOWLEDGE_IDS] == ["single-doc"]
    assert string_auto_retrieved == ["auto-single-doc"]
    assert string_auto_metadata[trace_keys.AUTO_INJECTED_STRATEGIES] == ["auto-single-doc"]
    assert string_auto_metadata[trace_keys.DECISION_RETRIEVAL_USED] is True
    assert string_auto_metadata[trace_keys.DECISION_RETRIEVED_KNOWLEDGE_IDS] == ["auto-single-doc"]
    assert direct_string_auto_metadata[trace_keys.AUTO_INJECTED_STRATEGIES] == ["direct-auto-doc"]
    assert direct_string_auto_metadata[trace_keys.DECISION_RETRIEVAL_USED] is True
    assert direct_tool_only_metadata[trace_keys.DECISION_RETRIEVED_KNOWLEDGE_IDS] == ["tool-only-doc"]
    assert direct_tool_only_metadata[trace_keys.DECISION_RETRIEVAL_USED] is True
    assert direct_ids == ["doc-a", "doc-b"]
    assert direct_string_id == ["doc-c"]


def test_cognitive_agent_base_decision_metadata_preserves_defaults_and_overrides() -> None:
    default_agent = CognitiveAgent("P1", "Villager", DeterministicCognitiveLLM())
    provider_agent = CognitiveAgent("P1", "Villager", ProviderModelLLM())

    assert default_agent._base_decision_metadata() == {
        "source": "llm",
        "provider": "",
        "model": "cognitive",
        "fallback": False,
    }
    assert provider_agent._base_decision_metadata() == {
        "source": "llm",
        "provider": "unit-provider",
        "model": "unit-model",
        "fallback": False,
    }

    decision = provider_agent._decision(
        ActionType.SKIP,
        reasoning="metadata merge",
        metadata={"model": "metadata-model", "custom": "value"},
    )

    assert decision.metadata["source"] == "llm"
    assert decision.metadata["provider"] == "unit-provider"
    assert decision.metadata["model"] == "metadata-model"
    assert decision.metadata["fallback"] is False
    assert decision.metadata["custom"] == "value"


def test_cognitive_agent_merge_compat_loop_trace_metadata_preserves_legacy_trace_path() -> None:
    agent = CognitiveAgent("P1", "Villager", DeterministicCognitiveLLM())
    meta = agent._base_decision_metadata()
    with agent_loop._STRATEGY_LOCK:
        agent_loop._LAST_LOOP_TRACE["P1"] = {
            "tool_trace": [{"tool": "legacy_tool"}],
            "auto_injected_strategies": ["legacy-doc"],
            "retrieved_knowledge_ids": ["legacy-doc"],
            "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        }

    agent._merge_compat_loop_trace_metadata(meta)

    assert meta[trace_keys.TOOL_TRACE] == [{"tool": "legacy_tool"}]
    assert meta[trace_keys.AUTO_INJECTED_STRATEGIES] == ["legacy-doc"]
    assert meta[trace_keys.DECISION_RETRIEVAL_USED] is True
    assert meta[trace_keys.DECISION_RETRIEVED_KNOWLEDGE_IDS] == ["legacy-doc"]
    assert meta[trace_keys.DECISION_USAGE] == {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}


def test_cognitive_agent_merge_compat_loop_trace_metadata_keeps_per_decision_trace_authoritative() -> None:
    agent = CognitiveAgent("P1", "Villager", DeterministicCognitiveLLM())
    meta = agent._base_decision_metadata()
    meta[trace_keys.TOOL_TRACE] = [{"tool": "decision_tool"}]
    with agent_loop._STRATEGY_LOCK:
        agent_loop._LAST_LOOP_TRACE["P1"] = {
            "tool_trace": [{"tool": "legacy_tool"}],
            "retrieved_knowledge_ids": ["legacy-doc"],
        }

    agent._merge_compat_loop_trace_metadata(meta)

    assert meta[trace_keys.TOOL_TRACE] == [{"tool": "decision_tool"}]
    assert trace_keys.DECISION_RETRIEVED_KNOWLEDGE_IDS not in meta


def test_cognitive_agent_single_legal_target_preserves_distinct_id_semantics() -> None:
    single = PlayerInfo(id="P2", name="Bob", seat=2, alive=True)
    duplicate = PlayerInfo(id="P2", name="Bob duplicate", seat=22, alive=True)
    other = PlayerInfo(id="P3", name="Carol", seat=3, alive=True)

    empty_obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Villager",
        day=1,
        phase="DAY_VOTE",
    )
    single_obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Villager",
        day=1,
        phase="DAY_VOTE",
        legal_targets=[single],
    )
    duplicate_obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Villager",
        day=1,
        phase="DAY_VOTE",
        legal_targets=[single, duplicate],
    )
    multiple_obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Villager",
        day=1,
        phase="DAY_VOTE",
        legal_targets=[single, other],
    )

    assert CognitiveAgent._single_legal_target(empty_obs) is None
    assert CognitiveAgent._single_legal_target(single_obs) is single
    assert CognitiveAgent._single_legal_target(duplicate_obs) is single
    assert CognitiveAgent._single_legal_target(multiple_obs) is None


def test_cognitive_agent_boom_skip_target_preserves_keyword_scope() -> None:
    for target in ["", "   ", "不爆", "不自爆", "放弃", "不炸", "跳过"]:
        assert CognitiveAgent._is_boom_skip_target(target) is True

    for target in ["skip", "pass", "none", "null", "Bob", "2号:Bob"]:
        assert CognitiveAgent._is_boom_skip_target(target) is False


def test_cognitive_agent_parsed_target_text_normalizes_missing_values() -> None:
    assert CognitiveAgent._parsed_target_text({}) == ""
    assert CognitiveAgent._parsed_target_text({"target": None}) == ""
    assert CognitiveAgent._parsed_target_text({"target": "  Bob  "}) == "Bob"


def test_cognitive_agent_target_matches_player_preserves_resolution_rules() -> None:
    player = {"id": "P2", "name": "Bob", "seat": 2}

    for candidate in ["bob", "p2", "2", "2号", "vote bob now", "请选择2号"]:
        assert CognitiveAgent._target_matches_player(candidate, player) is True

    for candidate in ["", "bo", "p", "22", "carol"]:
        assert CognitiveAgent._target_matches_player(candidate, player) is False


def test_cognitive_agent_candidate_players_for_target_resolution_preserves_merge_order() -> None:
    view = PlayerView(
        player_id="P1",
        day=1,
        phase="DAY_VOTE",
        self_player={"id": "P1", "name": "Alice", "seat": 1, "role": "Villager", "alive": True},
        players=[
            {"id": "P1", "name": "Alice", "seat": 1, "alive": True},
            {"id": "P2", "name": "VisibleBob", "seat": 2, "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[],
        observations=[],
        legal_targets=[
            {"id": "P2", "name": "LegalBob", "seat": 22, "alive": True},
            {"id": "P3", "name": "Carol", "seat": 3, "alive": True},
        ],
    )
    agent = CognitiveAgent("P1", "Villager", DeterministicCognitiveLLM())
    agent.initialize(view, {})

    candidates = agent._candidate_players_for_target_resolution()

    assert candidates == [
        {"id": "P1", "name": "Alice", "seat": 1, "alive": True},
        {"id": "P2", "name": "VisibleBob", "seat": 2, "alive": True},
        {"id": "P3", "name": "Carol", "seat": 3, "alive": True},
    ]
    assert agent._resolve_target("VisibleBob") == "P2"
    assert agent._resolve_target("LegalBob") is None
    assert agent._resolve_target("Carol") == "P3"


def test_cognitive_agent_required_target_text_matches_player_preserves_regex_rules() -> None:
    assert CognitiveAgent._required_target_text_matches_player("我选择 Bob。", "Bob", "2") is True
    assert CognitiveAgent._required_target_text_matches_player("我重新选择 2号，因为合法。", "Bob", "2") is True
    assert CognitiveAgent._required_target_text_matches_player("I choose seat 2 now.", "Bob", "2") is True
    assert CognitiveAgent._required_target_text_matches_player("I choose SEAT 2 now.", "Bob", "2") is True

    assert CognitiveAgent._required_target_text_matches_player("我选择 12号。", "Bob", "2") is False
    assert CognitiveAgent._required_target_text_matches_player("I choose seat 23 now.", "Bob", "2") is False
    assert CognitiveAgent._required_target_text_matches_player("No matching player.", "Bob", "2") is False


def test_cognitive_agent_json_for_prompt_preserves_non_ascii_payload() -> None:
    payload = {"target": "2号:鲍勃", "reasoning": "保持中文可读"}

    assert CognitiveAgent._json_for_prompt(payload) == '{"target": "2号:鲍勃", "reasoning": "保持中文可读"}'


def test_cognitive_agent_witch_decision_flags_preserve_existing_coercions() -> None:
    agent = CognitiveAgent("P1", "Witch", DeterministicCognitiveLLM())

    assert agent._witch_decision_flags({"save": 1, "poison_target": "  Bob  "}) == (True, "Bob", False)
    assert agent._witch_decision_flags({"save": 0, "poison_target": None}) == (False, "", True)
    assert agent._witch_decision_flags({"save": False, "poison_target": " 不毒 "}) == (False, "不毒", True)


def test_cognitive_agent_player_name_and_seat_supports_dict_and_playerinfo() -> None:
    assert CognitiveAgent._player_name_and_seat(PlayerInfo(id="P2", name="Bob", seat=2, alive=True)) == ("Bob", "2")
    assert CognitiveAgent._player_name_and_seat({"id": "P3", "name": "Carol", "seat": 3}) == ("Carol", "3")
    assert CognitiveAgent._player_name_and_seat({}) == ("", "")


def test_cognitive_agent_player_info_label_matches_prompt_format() -> None:
    assert CognitiveAgent._player_info_label(PlayerInfo(id="P2", name="Bob", seat=2, alive=True)) == "2号:Bob"


def test_cognitive_agent_player_dict_label_matches_prompt_format() -> None:
    assert CognitiveAgent._player_dict_label({"id": "P2", "name": "Bob", "seat": 2}) == "2号:Bob"
    assert CognitiveAgent._player_dict_label({}) == "?号:"


def test_cognitive_agent_player_label_dispatches_without_changing_prompt_format() -> None:
    player_info = PlayerInfo(id="P2", name="Bob", seat=2, alive=True)
    player_dict = {"id": "P3", "name": "Carol", "seat": 3}

    assert CognitiveAgent._player_label(player_info) == CognitiveAgent._player_info_label(player_info)
    assert CognitiveAgent._player_label(player_dict) == CognitiveAgent._player_dict_label(player_dict)
    assert CognitiveAgent._player_labels([player_info, player_dict]) == ["2号:Bob", "3号:Carol"]


def test_cognitive_agent_marks_active_intent_by_target_phase_tokens() -> None:
    agent = CognitiveAgent("P1", "Villager", DeterministicCognitiveLLM())
    agent.memory.update_round(1, "DAY_VOTE")
    agent.memory.planner.set_intent("vote_with_plan", "DAY_VOTE", day=1, phase="DAY_SPEECH")

    agent._mark_active_intent_executed_if_target_phase_contains("VOTE")

    active = agent.memory.planner.get_active(1, "DAY_VOTE")
    assert active is None
    assert agent.memory.planner.intents[-1].resolved is True
    assert agent.memory.planner.intents[-1].resolution_note == "executed"

    agent.memory.planner.set_intent("wolf_night_plan", "NIGHT_WOLF_ACTION", day=1, phase="DAY_VOTE")
    agent.memory.update_round(1, "NIGHT_WOLF_ACTION")

    agent._mark_active_intent_executed_if_target_phase_contains("NIGHT", "WOLF")

    assert agent.memory.planner.get_active(1, "NIGHT_WOLF_ACTION") is None
    assert agent.memory.planner.intents[-1].resolved is True
    assert agent.memory.planner.intents[-1].resolution_note == "executed"


def test_cognitive_agent_does_not_mark_intent_when_target_phase_token_missing() -> None:
    agent = CognitiveAgent("P1", "Werewolf", DeterministicCognitiveLLM())
    agent.memory.update_round(1, "NIGHT_SEER_ACTION")
    agent.memory.planner.set_intent("non_wolf_night_plan", "NIGHT_SEER_ACTION", day=1, phase="DAY_VOTE")

    agent._mark_active_intent_executed_if_target_phase_contains("NIGHT", "WOLF")

    active = agent.memory.planner.get_active(1, "NIGHT_SEER_ACTION")
    assert active is agent.memory.planner.intents[-1]
    assert active.resolved is False


def test_cognitive_agent_record_vote_followups_preserves_vote_memory_and_intent_marking() -> None:
    agent = CognitiveAgent("P1", "Villager", DeterministicCognitiveLLM())
    agent.memory.update_round(1, "DAY_VOTE")
    agent.memory.planner.set_intent("vote_with_plan", "DAY_VOTE", day=1, phase="DAY_SPEECH")

    agent._record_vote_followups("P2", "Bob", "vote reasoning")

    action = agent.memory.actions[-1]
    assert action.action_type == "vote"
    assert action.target == "P2"
    assert action.content == "投Bob"
    assert action.reasoning == "vote reasoning"
    assert agent.memory.last_vote_target == "P2"
    assert agent.memory.planner.intents[-1].resolved is True
    assert agent.memory.planner.intents[-1].resolution_note == "executed"


def test_cognitive_agent_action_method_mapping_preserves_supported_actions_and_error() -> None:
    agent = CognitiveAgent("P1", "Villager", DeterministicCognitiveLLM())

    expected_methods = {
        "talk": agent.talk,
        "vote": agent.vote,
        "attack": agent.attack,
        "divine": agent.divine,
        "guard": agent.guard,
        "shoot": agent.shoot,
        "boom": agent.boom,
        "witch_act": agent.witch_act,
        "transfer_badge": agent.transfer_badge,
    }

    for action_type, method in expected_methods.items():
        assert agent._cognitive_action_method(action_type) == method

    with pytest.raises(ValueError, match="Unknown action_type: unknown"):
        agent._cognitive_action_method("unknown")


def test_cognitive_agent_fallback_metadata_preserves_contract() -> None:
    assert CognitiveAgent._fallback_metadata("heuristic", "reason text") == {
        "fallback_used": True,
        "fallback_from": "cognitive",
        "fallback_to": "heuristic",
        "fallback_reason": "reason text",
    }
    assert CognitiveAgent._fallback_metadata("pass", "all fallbacks exhausted") == {
        "fallback_used": True,
        "fallback_from": "cognitive",
        "fallback_to": "pass",
        "fallback_reason": "all fallbacks exhausted",
    }


def test_cognitive_agent_keyword_helpers_preserve_social_signal_terms() -> None:
    assert CognitiveAgent._has_keyword("这人像狼，建议出。", CognitiveAgent._SPEECH_ACCUSATION_KEYWORDS) is True
    assert CognitiveAgent._has_keyword("我跳预言家，昨晚查验。", CognitiveAgent._ROLE_CLAIM_KEYWORDS) is True
    assert CognitiveAgent._has_keyword("Alice是狼，建议投。", CognitiveAgent._SELF_ACCUSATION_KEYWORDS) is True
    assert CognitiveAgent._has_keyword("白狼王自爆了。", CognitiveAgent._MAJOR_EVENT_KEYWORDS) is True
    assert CognitiveAgent._has_keyword("只是普通发言。", CognitiveAgent._ROLE_CLAIM_KEYWORDS) is False


def test_cognitive_agent_speech_accuses_player_preserves_phrase_templates() -> None:
    for speech in ["今天投Bob。", "建议出Bob。", "Bob是狼。", "我怀疑Bob。", "预言家查杀Bob。"]:
        assert CognitiveAgent._speech_accuses_player(speech, "Bob") is True

    assert CognitiveAgent._speech_accuses_player("Bob发言比较正常。", "Bob") is False


def test_cognitive_agent_voter_self_match_helpers_preserve_name_and_id_rules() -> None:
    agent = CognitiveAgent("P1", "Villager", DeterministicCognitiveLLM(), player_name="Alice")

    assert agent._voter_identity_matches_self("Alice", "P9") is True
    assert agent._voter_identity_matches_self("Other", "P1") is True
    assert agent._voter_identity_matches_self("Other", "P9") is False

    assert agent._voter_label_matches_self("Alice") is True
    assert agent._voter_label_matches_self("P1") is True
    assert agent._voter_label_matches_self("Other") is False


def test_cognitive_agent_speech_accuses_self_preserves_name_and_keyword_gate() -> None:
    agent = CognitiveAgent("P1", "Villager", DeterministicCognitiveLLM(), player_name="Alice")

    assert agent._speech_accuses_self("alice是狼，建议投。") is True
    assert agent._speech_accuses_self("alice刚才发言比较完整。") is False
    assert agent._speech_accuses_self("Bob是狼，建议投。") is False


def test_cognitive_agent_speech_from_other_accuses_self_preserves_public_trust_gate() -> None:
    agent = CognitiveAgent("P1", "Villager", DeterministicCognitiveLLM(), player_name="Alice")

    assert (
        agent._speech_from_other_accuses_self(
            SpeechInfo(player_id="P2", player_name="Bob", seat=2, content="Alice像狼，建议出。")
        )
        is True
    )
    assert (
        agent._speech_from_other_accuses_self(
            SpeechInfo(player_id="P1", player_name="Alice", seat=1, content="Alice像狼，建议出。")
        )
        is False
    )
    assert (
        agent._speech_from_other_accuses_self(
            SpeechInfo(player_id="P2", player_name="Bob", seat=2, content="Alice发言比较完整。")
        )
        is False
    )
    assert (
        agent._speech_from_other_accuses_self(
            SpeechInfo(player_id="P2", player_name="Bob", seat=2, content="alice像狼，建议出。")
        )
        is False
    )


def test_cognitive_agent_role_claim_requires_vote_rethink_preserves_seer_only_gate() -> None:
    agent = CognitiveAgent("P1", "Villager", DeterministicCognitiveLLM(), player_name="Alice")

    assert (
        agent._role_claim_requires_vote_rethink(
            RoleClaim(
                player_name="Bob",
                player_id="P2",
                seat=2,
                claimed_role="预言家",
                day=1,
                context="day_speech",
            )
        )
        is True
    )
    assert (
        agent._role_claim_requires_vote_rethink(
            RoleClaim(
                player_name="Alice",
                player_id="P1",
                seat=1,
                claimed_role="预言家",
                day=1,
                context="day_speech",
            )
        )
        is False
    )
    assert (
        agent._role_claim_requires_vote_rethink(
            RoleClaim(
                player_name="Bob",
                player_id="P2",
                seat=2,
                claimed_role="女巫",
                day=1,
                context="day_speech",
            )
        )
        is False
    )


def test_cognitive_agent_public_event_description_preserves_reflection_formats() -> None:
    assert (
        CognitiveAgent._public_event_description(
            {"type": "CHAT_MESSAGE", "payload": {"actor_name": "Alice", "speech": "今天先看票型。"}}
        )
        == "Alice: 今天先看票型。"
    )
    assert (
        CognitiveAgent._public_event_description(
            {"type": "CHAT_MESSAGE", "payload": {"speaker": "Bob", "speech": "我补充一句。"}}
        )
        == "Bob: 我补充一句。"
    )
    assert (
        CognitiveAgent._public_event_description(
            {"type": "VOTE_CAST", "payload": {"voter_name": "Alice", "target_name": "Bob"}}
        )
        == "Alice 投票给 Bob"
    )
    assert (
        CognitiveAgent._public_event_description(
            {"type": "PLAYER_DIED", "payload": {"player_name": "Carol", "cause": "vote"}}
        )
        == "Carol 死亡(vote)"
    )
    assert (
        CognitiveAgent._public_event_description(
            {"type": "PLAYER_DIED", "payload": {"player_name": "Carol", "reason": "witch"}}
        )
        == "Carol 死亡(witch)"
    )
    assert len(CognitiveAgent._public_event_description({"type": "UNKNOWN", "payload": {"text": "x" * 200}})) == 120


def test_cognitive_agent_private_event_reflection_entry_preserves_reflection_formats() -> None:
    assert CognitiveAgent._private_event_reflection_entry(
        {"day": 1, "payload": {"kind": "seer_result", "target_name": "Bob", "is_wolf": True}}
    ) == {"type": "PRIVATE_SEER", "day": 1, "description": "查验 Bob: 狼人"}
    assert CognitiveAgent._private_event_reflection_entry(
        {"day": 2, "payload": {"kind": "seer_result", "target_name": "Carol", "is_wolf": False}}
    ) == {"type": "PRIVATE_SEER", "day": 2, "description": "查验 Carol: 好人"}
    assert CognitiveAgent._private_event_reflection_entry(
        {"day": 3, "payload": {"kind": "witch_save", "target_name": "Alice"}}
    ) == {"type": "PRIVATE_WITCH", "day": 3, "description": "解药救人: Alice"}
    assert CognitiveAgent._private_event_reflection_entry({"payload": {"kind": "witch_save"}}) == {
        "type": "PRIVATE_WITCH",
        "day": 0,
        "description": "解药救人: ?",
    }
    assert CognitiveAgent._private_event_reflection_entry({"day": 1, "payload": {"kind": "ignored"}}) is None


def test_cognitive_agent_contradiction_reflection_entry_preserves_reflection_format() -> None:
    contradiction = Contradiction(
        role="预言家",
        claimants=["Alice", "Bob"],
        description="Alice, Bob 冲突声称是预言家",
    )

    assert CognitiveAgent._contradiction_reflection_entry(contradiction, 2) == {
        "type": "CONTRADICTION",
        "day": 2,
        "description": "Alice, Bob 冲突声称是预言家",
    }


def test_cognitive_agent_decision_reflection_entry_preserves_action_record_fields() -> None:
    assert CognitiveAgent._decision_reflection_entry(
        ActionRecord(
            action_type="vote",
            target="P2",
            content="投Bob",
            reasoning="reason",
            day=2,
            phase="DAY_VOTE",
        )
    ) == {
        "action_type": "vote",
        "target": "P2",
        "speech": "投Bob",
        "day": 2,
        "phase": "DAY_VOTE",
    }
    assert (
        CognitiveAgent._decision_reflection_entry(
            ActionRecord(
                action_type="speech",
                target=None,
                content="我先观察。",
                reasoning="reason",
                day=1,
                phase="DAY_SPEECH",
            )
        )["target"]
        == ""
    )


def test_cognitive_agent_did_agent_win_preserves_alignment_mapping() -> None:
    wolf = CognitiveAgent("P1", "Werewolf", DeterministicCognitiveLLM())
    villager = CognitiveAgent("P2", "Villager", DeterministicCognitiveLLM())
    no_profile = CognitiveAgent("P3", "Villager", DeterministicCognitiveLLM())
    no_profile._profile = None

    assert wolf._did_agent_win("wolf") is True
    assert wolf._did_agent_win("village") is False
    assert villager._did_agent_win("village") is True
    assert villager._did_agent_win("wolf") is False
    assert villager._did_agent_win(None) is False
    assert no_profile._did_agent_win("village") is False


def test_cognitive_agent_reflection_agent_state_preserves_payload_shape() -> None:
    agent = CognitiveAgent("P1", "Villager", DeterministicCognitiveLLM(), player_name="Alice")
    decisions = [{"action_type": "vote", "target": "P2"}]
    game_events = [{"type": "VOTE_CAST", "description": "Alice 投票给 Bob"}]

    state = agent._reflection_agent_state(True, decisions, game_events)

    assert state == {
        "player_id": "P1",
        "player_name": "Alice",
        "role": "Villager",
        "persona": agent._profile.persona,
        "mind": agent._profile.mind,
        "won": True,
        "decisions": decisions,
        "game_events": game_events,
    }

    agent._profile = None
    state_without_profile = agent._reflection_agent_state(False, decisions, game_events)

    assert state_without_profile["persona"] is None
    assert state_without_profile["mind"] is None
    assert state_without_profile["won"] is False


def test_cognitive_agent_profile_mbti_label_preserves_log_fallbacks() -> None:
    agent = CognitiveAgent("P1", "Villager", DeterministicCognitiveLLM(), player_name="Alice")
    mbti = agent._profile.persona.mbti

    assert agent._profile_mbti_label() == mbti

    agent._profile = replace(agent._profile, persona=None)
    assert agent._profile_mbti_label() == "?"

    agent._profile = None
    assert agent._profile_mbti_label() == "?"


def test_cognitive_agent_reflection_success_log_message_preserves_text() -> None:
    agent = CognitiveAgent("P1", "Villager", DeterministicCognitiveLLM(), player_name="Alice")
    mbti = agent._profile.persona.mbti

    assert agent._reflection_success_log_message(3) == (
        f"Agent Alice(Villager, MBTI={mbti}) reflection: 3 knowledge docs saved to PostgreSQL"
    )

    agent._profile = replace(agent._profile, persona=None)
    assert agent._reflection_success_log_message(0) == (
        "Agent Alice(Villager, MBTI=?) reflection: 0 knowledge docs saved to PostgreSQL"
    )


def test_get_profile_returns_isolated_instances_for_agent_mutation() -> None:
    profile = get_profile("Villager")
    default_mbti = profile.persona.mbti

    profile.persona.mbti = "ENFP"
    profile.personality.append("测试污染")

    fresh = get_profile("Villager")

    assert fresh is not profile
    assert fresh.persona is not profile.persona
    assert fresh.mind is not profile.mind
    assert fresh.persona.mbti == default_mbti
    assert "测试污染" not in fresh.personality


def test_character_profile_injection_does_not_pollute_default_role_profile() -> None:
    character = Character(
        persona=Persona(
            mbti="ENFP",
            gender="female",
            age=29,
            name="Injected",
            basic_info="test character",
            style_label="expressive",
        ),
        mind=PlayerMind(
            courage="bold",
            memory_bias="recent",
            suspicion_threshold="low",
            self_protection="aggressive",
            logic_depth="moderate",
            table_presence="dominant",
        ),
    )

    injected = create_cognitive_agent_with_character(
        player_id="P1",
        role="Villager",
        llm=DeterministicCognitiveLLM(),
        player_name="Injected",
        player_seat=1,
        character=character,
    )
    default_agent = create_cognitive_agent_with_character(
        player_id="P2",
        role="Villager",
        llm=DeterministicCognitiveLLM(),
        player_name="Default",
        player_seat=2,
        character=None,
    )

    assert injected._profile.persona.mbti == "ENFP"
    assert default_agent._profile.persona.mbti == get_profile("Villager").persona.mbti
    assert default_agent._profile.persona.mbti != injected._profile.persona.mbti


def test_load_profiles_from_db_closes_resources_and_returns_isolated_profiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_conn = _install_fake_profile_db(monkeypatch, [("Villager", "DB goal")])

    profiles = load_profiles_from_db("postgresql://unit-test")
    profile = profiles["Villager"]

    assert fake_conn.closed is True
    assert fake_conn.cursor_obj.closed is True
    assert "FROM role_strategy_cards" in fake_conn.cursor_obj.executed
    assert "speech_policy" not in fake_conn.cursor_obj.executed
    assert profile.goal == "DB goal"

    profile.persona.mbti = "ENFP"
    assert (
        load_profiles_from_db("postgresql://unit-test")["Villager"].persona.mbti == get_profile("Villager").persona.mbti
    )


def test_profile_from_role_card_row_preserves_base_fields_and_goal_override() -> None:
    default_profile = get_profile("Villager")

    db_profile = _profile_from_role_card_row("Villager", "DB goal")
    fallback_profile = _profile_from_role_card_row("Villager", "")
    unknown_role_profile = _profile_from_role_card_row("UnknownRole", "")

    assert db_profile.goal == "DB goal"
    assert fallback_profile.goal == default_profile.goal
    assert unknown_role_profile.goal == default_profile.goal
    assert db_profile.role == default_profile.role
    assert db_profile.backstory == default_profile.backstory
    assert db_profile.speech_style == default_profile.speech_style
    assert db_profile.table_goal == default_profile.table_goal
    assert db_profile.reveal_policy == default_profile.reveal_policy
    assert db_profile.persona.mbti == default_profile.persona.mbti
    assert db_profile.mind.logic_depth == default_profile.mind.logic_depth

    db_profile.personality.append("测试污染")
    assert "测试污染" not in _profile_from_role_card_row("Villager", "DB goal").personality


def test_role_goal_from_row_accepts_tuple_and_dict_rows() -> None:
    assert _role_goal_from_row(("Villager", "DB goal")) == ("Villager", "DB goal")
    assert _role_goal_from_row(("Villager", "DB goal", "ignored")) == ("Villager", "DB goal")
    assert _role_goal_from_row(("Villager",)) == ("Villager", None)
    assert _role_goal_from_row({"role": "Seer", "goal": "DB seer goal"}) == ("Seer", "DB seer goal")
    assert _role_goal_from_row({"role": "  ", "goal": "ignored"}) is None
    assert _role_goal_from_row({}) is None
    assert _role_goal_from_row(()) is None
    assert _role_goal_from_row(None) is None


def test_profiles_from_role_rows_skips_invalid_rows_and_returns_isolated_profiles() -> None:
    profiles = _profiles_from_role_rows(
        [
            {},
            (),
            ("Villager", "DB goal"),
            {"role": "Seer", "goal": "DB seer goal"},
        ]
    )

    assert set(profiles) == {"Villager", "Seer"}
    assert profiles["Villager"].goal == "DB goal"
    assert profiles["Seer"].goal == "DB seer goal"

    profiles["Villager"].persona.mbti = "ENFP"
    fresh_profiles = _profiles_from_role_rows([("Villager", "DB goal")])
    assert fresh_profiles["Villager"].persona.mbti == get_profile("Villager").persona.mbti


def test_load_profiles_from_db_skips_unparseable_rows_and_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_conn = _install_fake_profile_db(monkeypatch, [{}, ()])

    profiles = load_profiles_from_db("postgresql://unit-test")

    assert profiles["Villager"].goal == get_profile("Villager").goal
    assert "" not in profiles
    assert fake_conn.closed is True
    assert fake_conn.cursor_obj.closed is True


def test_load_profile_from_db_fallback_preserves_unknown_role_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "psycopg2",
        SimpleNamespace(connect=lambda _: (_ for _ in ()).throw(RuntimeError("db unavailable"))),
    )

    profile = load_profile_from_db("UnknownRole", conn_str="postgresql://unit-test")
    default_profile = get_profile("UnknownRole")

    assert profile.goal == default_profile.goal
    assert profile.persona.mbti == default_profile.persona.mbti

    profile.persona.mbti = "ENFP"
    assert (
        load_profile_from_db("UnknownRole", conn_str="postgresql://unit-test").persona.mbti
        == default_profile.persona.mbti
    )


def test_cognitive_agent_reflection_game_id_preserves_unknown_fallback() -> None:
    agent = CognitiveAgent("P1", "Villager", DeterministicCognitiveLLM())

    agent._game_id = "game-1"
    assert agent._reflection_game_id() == "game-1"

    agent._game_id = ""
    assert agent._reflection_game_id() == "unknown"

    agent._game_id = None
    assert agent._reflection_game_id() == "unknown"


def test_cognitive_agent_reflection_enabled_preserves_env_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COGNITIVE_ENABLE_REFLECTION", raising=False)
    assert CognitiveAgent._reflection_enabled() is True

    for disabled in ["0", "false", "no", "off", " FALSE "]:
        monkeypatch.setenv("COGNITIVE_ENABLE_REFLECTION", disabled)
        assert CognitiveAgent._reflection_enabled() is False

    for enabled in ["1", "true", "yes", "on", "anything"]:
        monkeypatch.setenv("COGNITIVE_ENABLE_REFLECTION", enabled)
        assert CognitiveAgent._reflection_enabled() is True


def test_cognitive_agent_require_knowledge_write_preserves_strict_true_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REQUIRE_KNOWLEDGE_WRITE", raising=False)
    assert CognitiveAgent._require_knowledge_write() is False

    for enabled in ["true", "TRUE", "True"]:
        monkeypatch.setenv("REQUIRE_KNOWLEDGE_WRITE", enabled)
        assert CognitiveAgent._require_knowledge_write() is True

    for disabled in ["", "false", "1", "yes", " true "]:
        monkeypatch.setenv("REQUIRE_KNOWLEDGE_WRITE", disabled)
        assert CognitiveAgent._require_knowledge_write() is False


def test_cognitive_agent_required_night_target_status_preserves_repair_reasons() -> None:
    view = PlayerView(
        player_id="P1",
        day=1,
        phase="NIGHT_WOLF_ACTION",
        self_player={"id": "P1", "name": "WolfA", "seat": 1, "role": "Werewolf", "alive": True},
        players=[
            {"id": "P1", "name": "WolfA", "seat": 1, "role": "Werewolf", "alive": True},
            {"id": "P2", "name": "Bob", "seat": 2, "alive": True},
            {"id": "P3", "name": "Carol", "seat": 3, "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[],
        observations=[],
        legal_targets=[{"id": "P2", "name": "Bob", "seat": 2, "alive": True}],
    )
    agent = create_cognitive_agent_with_character(
        player_id="P1",
        role="Werewolf",
        llm=DeterministicCognitiveLLM(),
        player_name="WolfA",
        player_seat=1,
        character=None,
    )
    agent.initialize(view, {})

    assert agent._required_night_target_status({"target": "跳过", "reasoning": "skip"}) == (
        None,
        "skip keyword or empty required target",
    )
    assert agent._required_night_target_status({"target": "", "reasoning": "今晚不刀"}) == (
        None,
        "skip keyword or empty required target",
    )
    assert agent._required_night_target_status({"target": "Nobody", "reasoning": "missing"}) == (
        None,
        "unresolved required target",
    )
    assert agent._required_night_target_status({"target": "Carol", "reasoning": "illegal visible target"}) == (
        "P3",
        "target outside legal target set",
    )
    assert agent._required_night_target_status({"target": "Bob", "reasoning": "legal target"}) == ("P2", "")


class MalformedReflectionLLM:
    def invoke(self, messages):
        return AIMessage(content='DECISION: {"target": "2号", "reasoning": "not a reflection"}')


def test_agent_loop_raises_when_llm_never_outputs_decision() -> None:
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Villager",
        day=1,
        phase="DAY_VOTE",
        alive=[
            PlayerInfo(id="P1", name="Alice", seat=1, alive=True),
            PlayerInfo(id="P2", name="Bob", seat=2, alive=True),
        ],
    )
    loop = AgentLoop(NonDecisionLLM(), "system prompt", action_type="vote")

    with pytest.raises(RuntimeError, match="failed to produce a structured decision"):
        loop.run(obs, Memory("P1", "Villager"))


def test_agent_loop_native_fc_uses_info_tool_then_forces_submit_decision() -> None:
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Villager",
        day=1,
        phase="DAY_SPEECH",
        alive=[
            PlayerInfo(id="P1", name="Alice", seat=1, alive=True),
            PlayerInfo(id="P2", name="Bob", seat=2, alive=True),
        ],
    )
    llm = NativeDecisionLLM()
    loop = AgentLoop(llm, "system prompt", action_type="speech", player_id="P1")

    decision = loop.run(obs, Memory("P1", "Villager"))

    assert decision["speech"]
    assert decision["reasoning"] == "native final speech"
    assert len(llm.calls) == 2
    assert "recall_memory" in llm.calls[0]["tool_names"]
    assert "submit_decision" in llm.calls[0]["tool_names"]
    assert llm.calls[0]["force_tool_name"] is None
    assert llm.calls[1]["tool_names"] == ["submit_decision"]
    assert llm.calls[1]["force_tool_name"] == "submit_decision"
    assert decision[trace_keys.TOOL_TRACE][0]["tool"] == "recall_memory"


def test_agent_loop_feature_flags_override_global_track_c(monkeypatch: pytest.MonkeyPatch) -> None:
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Villager",
        day=1,
        phase="DAY_SPEECH",
        alive=[
            PlayerInfo(id="P1", name="Alice", seat=1, alive=True),
            PlayerInfo(id="P2", name="Bob", seat=2, alive=True),
        ],
    )

    calls: list[str] = []

    def fake_track_c_block(*args, **kwargs) -> str:
        calls.append("called")
        return "TRACK_C_BLOCK"

    monkeypatch.setattr(agent_loop, "_build_track_c_strategy_block", fake_track_c_block)
    monkeypatch.setenv("COGNITIVE_ENABLE_TRACK_C", "1")
    disabled_loop = AgentLoop(
        DeterministicCognitiveLLM(),
        "system prompt",
        action_type="speech",
        player_id="P1",
        feature_flags={"COGNITIVE_ENABLE_TRACK_C": False},
    )
    disabled_loop._build_dynamic_context(obs, Memory("P1", "Villager"), "", "")
    assert calls == []

    monkeypatch.setenv("COGNITIVE_ENABLE_TRACK_C", "0")
    enabled_loop = AgentLoop(
        DeterministicCognitiveLLM(),
        "system prompt",
        action_type="speech",
        player_id="P1",
        feature_flags={"COGNITIVE_ENABLE_TRACK_C": True},
    )
    context = enabled_loop._build_dynamic_context(obs, Memory("P1", "Villager"), "", "")
    assert calls == ["called"]
    assert "TRACK_C_BLOCK" in context


@pytest.mark.parametrize("action_type,phase", [("vote", "DAY_VOTE"), ("night", "NIGHT_WOLF_ACTION")])
def test_agent_loop_vote_and_night_default_directly_force_submit_decision(action_type: str, phase: str) -> None:
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Werewolf" if action_type == "night" else "Villager",
        day=1,
        phase=phase,
        alive=[
            PlayerInfo(id="P1", name="Alice", seat=1, alive=True),
            PlayerInfo(id="P2", name="Bob", seat=2, alive=True),
        ],
    )
    llm = NativeDecisionLLM()
    loop = AgentLoop(llm, "system prompt", action_type=action_type, player_id="P1")

    decision = loop.run(obs, Memory("P1", obs.player_role))

    assert decision["target"] == "Bob"
    assert decision["reasoning"] == "native final target"
    assert len(llm.calls) == 1
    assert llm.calls[0]["tool_names"] == ["submit_decision"]
    assert llm.calls[0]["force_tool_name"] == "submit_decision"


def test_agent_loop_decision_schema_restricts_target_to_legal_targets() -> None:
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Werewolf",
        day=1,
        phase="NIGHT_WOLF_ACTION",
        alive=[
            PlayerInfo(id="P1", name="Alice", seat=1, alive=True),
            PlayerInfo(id="P2", name="WolfB", seat=2, alive=True),
            PlayerInfo(id="P3", name="Bob", seat=3, alive=True),
        ],
        legal_targets=[PlayerInfo(id="P3", name="Bob", seat=3, alive=True)],
    )
    loop = AgentLoop(NativeDecisionLLM(), "system prompt", action_type="night", player_id="P1")

    schema = loop._decision_tool_schema(obs)

    target_schema = schema["function"]["parameters"]["properties"]["target"]
    assert target_schema["enum"] == ["3号", "3号:Bob", "Bob", "P3"]
    assert "2号" not in target_schema["description"]
    assert "3号:Bob" in target_schema["description"]


def test_agent_loop_wolf_night_fallback_excludes_visible_wolf_teammates() -> None:
    obs = Observation(
        player_id="P1",
        player_name="WolfA",
        player_seat=1,
        player_role="Werewolf",
        day=1,
        phase="NIGHT_WOLF_ACTION",
        alive=[
            PlayerInfo(id="P1", name="WolfA", seat=1, alive=True, role="Werewolf"),
            PlayerInfo(id="P2", name="Bob", seat=2, alive=True),
            PlayerInfo(id="P3", name="WolfB", seat=3, alive=True, role="Werewolf"),
        ],
    )
    loop = AgentLoop(NativeDecisionLLM(), "system prompt", action_type="night", player_id="P1")

    schema = loop._decision_tool_schema(obs)

    target_schema = schema["function"]["parameters"]["properties"]["target"]
    assert target_schema["enum"] == ["2号", "2号:Bob", "Bob", "P2"]
    assert "WolfB" not in target_schema["description"]


def test_agent_loop_repairs_empty_native_submit_decision_with_text_decision() -> None:
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Villager",
        day=1,
        phase="DAY_VOTE",
        alive=[
            PlayerInfo(id="P1", name="Alice", seat=1, alive=True),
            PlayerInfo(id="P2", name="Bob", seat=2, alive=True),
        ],
    )
    llm = EmptyNativeThenTextDecisionLLM()
    loop = AgentLoop(llm, "system prompt", action_type="vote", player_id="P1")

    decision = loop.run(obs, Memory("P1", "Villager"))

    assert decision["target"] == "Bob"
    assert decision["reasoning"] == "text repair target"
    assert len(llm.calls) == 2
    assert llm.calls[0]["force_tool_name"] == "submit_decision"
    assert llm.calls[1]["force_tool_name"] is None
    assert llm.calls[1]["tool_names"] == []


def test_agent_loop_repairs_plain_native_text_with_text_decision() -> None:
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Villager",
        day=1,
        phase="DAY_VOTE",
        alive=[
            PlayerInfo(id="P1", name="Alice", seat=1, alive=True),
            PlayerInfo(id="P2", name="Bob", seat=2, alive=True),
        ],
    )
    llm = PlainNativeTextThenTextDecisionLLM()
    loop = AgentLoop(llm, "system prompt", action_type="vote", player_id="P1")

    decision = loop.run(obs, Memory("P1", "Villager"))

    assert decision["target"] == "Bob"
    assert decision["reasoning"] == "plain text native repair target"
    assert len(llm.calls) == 2
    assert llm.calls[0]["force_tool_name"] == "submit_decision"
    assert llm.calls[1]["force_tool_name"] is None
    assert llm.calls[1]["tool_names"] == []
    assert "未调用 submit_decision function" in llm.calls[1]["text"]
    assert "合法目标只能" in llm.calls[1]["text"]


def test_agent_loop_repairs_illegal_native_target_with_text_decision() -> None:
    obs = Observation(
        player_id="P1",
        player_name="WolfA",
        player_seat=1,
        player_role="Werewolf",
        day=1,
        phase="NIGHT_WOLF_ACTION",
        alive=[
            PlayerInfo(id="P1", name="WolfA", seat=1, alive=True, role="Werewolf"),
            PlayerInfo(id="P2", name="Bob", seat=2, alive=True),
            PlayerInfo(id="P3", name="WolfB", seat=3, alive=True, role="Werewolf"),
        ],
        legal_targets=[PlayerInfo(id="P2", name="Bob", seat=2, alive=True)],
    )
    llm = IllegalNativeTargetThenTextDecisionLLM()
    loop = AgentLoop(llm, "system prompt", action_type="night", player_id="P1")

    decision = loop.run(obs, Memory("P1", "Werewolf"))

    assert decision["target"] == "Bob"
    assert decision["reasoning"] == "repair selects legal villager"
    assert len(llm.calls) == 2
    assert llm.calls[0]["force_tool_name"] == "submit_decision"
    assert llm.calls[1]["force_tool_name"] is None
    assert llm.calls[1]["tool_names"] == []
    assert "target 不在合法目标中" in llm.calls[1]["text"]
    assert "合法目标只能从这些值中选一个：2号、2号:Bob、Bob、P2" in llm.calls[1]["text"]


def test_agent_loop_accepts_native_speech_without_reasoning_with_audit_marker() -> None:
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Villager",
        day=1,
        phase="DAY_SPEECH",
        alive=[
            PlayerInfo(id="P1", name="Alice", seat=1, alive=True),
            PlayerInfo(id="P2", name="Bob", seat=2, alive=True),
        ],
    )
    llm = NativeSpeechWithoutReasoningLLM()
    loop = AgentLoop(llm, "system prompt", action_type="speech", player_id="P1")

    decision = loop.run(obs, Memory("P1", "Villager"))

    assert decision["speech"] == "我按公开信息发言，今天先观察票型。"
    assert decision["reasoning"] == "submit_decision_reasoning_missing"
    assert len(llm.calls) == 1
    assert llm.calls[0]["force_tool_name"] is None
    assert "submit_decision" in llm.calls[0]["tool_names"]


def test_agent_loop_repairs_invalid_native_submit_args_with_text_decision() -> None:
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Villager",
        day=1,
        phase="DAY_SPEECH",
        alive=[
            PlayerInfo(id="P1", name="Alice", seat=1, alive=True),
            PlayerInfo(id="P2", name="Bob", seat=2, alive=True),
        ],
    )
    llm = InvalidNativeArgsThenTextDecisionLLM()
    loop = AgentLoop(llm, "system prompt", action_type="speech", player_id="P1")

    decision = loop.run(obs, Memory("P1", "Villager"))

    assert decision["speech"] == "我用文本格式补交最终发言。"
    assert decision["reasoning"] == "text repair speech"
    assert len(llm.calls) == 3
    assert llm.calls[-1]["force_tool_name"] is None
    assert llm.calls[-1]["tool_names"] == []


def test_agent_loop_exits_when_text_repair_after_invalid_native_args_is_empty() -> None:
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Villager",
        day=1,
        phase="DAY_SPEECH",
        alive=[
            PlayerInfo(id="P1", name="Alice", seat=1, alive=True),
            PlayerInfo(id="P2", name="Bob", seat=2, alive=True),
        ],
    )
    llm = InvalidNativeArgsThenEmptyTextLLM()
    loop = AgentLoop(llm, "system prompt", action_type="speech", player_id="P1")

    with pytest.raises(RuntimeError, match="failed to produce a structured decision"):
        loop.run(obs, Memory("P1", "Villager"))

    assert len(llm.calls) == 5


def test_agent_loop_rejects_reasoning_only_target_decision() -> None:
    obs = Observation(
        player_id="P1",
        player_name="Guard",
        player_seat=1,
        player_role="Guard",
        day=1,
        phase="NIGHT_GUARD_ACTION",
        alive=[
            PlayerInfo(id="P1", name="Guard", seat=1, alive=True),
            PlayerInfo(id="P2", name="Bob", seat=2, alive=True),
        ],
        legal_targets=[
            PlayerInfo(id="P1", name="Guard", seat=1, alive=True),
            PlayerInfo(id="P2", name="Bob", seat=2, alive=True),
        ],
    )
    loop = AgentLoop(ReasoningOnlyTargetDecisionLLM(), "system prompt", action_type="night", player_id="P1")

    with pytest.raises(RuntimeError, match="failed to produce a structured decision"):
        loop.run(obs, Memory("P1", "Guard"))


def test_agent_loop_repairs_empty_text_response_with_second_text_decision() -> None:
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Villager",
        day=1,
        phase="DAY_LAST_WORDS",
        alive=[
            PlayerInfo(id="P1", name="Alice", seat=1, alive=True),
            PlayerInfo(id="P2", name="Bob", seat=2, alive=True),
        ],
    )
    llm = EmptyTextRepairThenDecisionLLM()
    loop = AgentLoop(llm, "system prompt", action_type="speech", player_id="P1")

    result = loop.run(obs, Memory("P1", "Villager"))

    assert result["speech"] == "我补充最终发言。"
    assert result["reasoning"] == "empty response repair"
    assert len(llm.calls) == 3


def test_agent_loop_salvages_partial_speech_json_with_audit_reasoning() -> None:
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Villager",
        day=1,
        phase="DAY_SPEECH",
        alive=[
            PlayerInfo(id="P1", name="Alice", seat=1, alive=True),
            PlayerInfo(id="P2", name="Bob", seat=2, alive=True),
        ],
    )
    loop = AgentLoop(PartialSpeechJsonLLM(), "system prompt", action_type="speech", player_id="P1")

    result = loop.run(obs, Memory("P1", "Villager"))

    assert result["speech"] == "这是一段被截断但仍然可用的发言内容"
    assert result["reasoning"] == "partial_json_reasoning_missing"


def test_cognitive_agent_talk_preserves_native_fc_reasoning() -> None:
    view = PlayerView(
        player_id="P1",
        day=1,
        phase="DAY_SPEECH",
        self_player={"id": "P1", "name": "Alice", "seat": 1, "role": "Villager", "alive": True},
        players=[
            {"id": "P1", "name": "Alice", "seat": 1, "role": "Villager", "alive": True},
            {"id": "P2", "name": "Bob", "seat": 2, "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[],
        observations=[],
    )
    agent = create_cognitive_agent_with_character(
        player_id="P1",
        role="Villager",
        llm=NativeDecisionLLM(),
        player_name="Alice",
        player_seat=1,
        character=None,
    )
    agent.initialize(view, {})
    agent.update(view, "TALK")

    decision = agent.talk()

    assert decision.action_type == ActionType.TALK
    assert decision.speech
    assert decision.reasoning == "native final speech"
    assert agent.memory.actions[-1].reasoning == "native final speech"


def test_cognitive_agent_prefers_per_decision_loop_trace_over_global_compat_trace() -> None:
    view = PlayerView(
        player_id="P1",
        day=1,
        phase="DAY_SPEECH",
        self_player={"id": "P1", "name": "Alice", "seat": 1, "role": "Villager", "alive": True},
        players=[
            {"id": "P1", "name": "Alice", "seat": 1, "role": "Villager", "alive": True},
            {"id": "P2", "name": "Bob", "seat": 2, "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[],
        observations=[],
    )
    agent = create_cognitive_agent_with_character(
        player_id="P1",
        role="Villager",
        llm=NativeDecisionLLM(),
        player_name="Alice",
        player_seat=1,
        character=None,
    )
    agent.initialize(view, {})
    agent.update(view, "TALK")
    with agent_loop._STRATEGY_LOCK:
        agent_loop._LAST_LOOP_TRACE["P1"] = {
            "tool_trace": [{"tool": "stale_global_trace"}],
            "auto_injected_strategies": ["stale-doc"],
            "retrieved_knowledge_ids": ["stale-doc"],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    decision = agent.talk()

    assert decision.action_type == ActionType.TALK
    assert decision.metadata[trace_keys.TOOL_TRACE][0]["tool"] == "recall_memory"
    assert decision.metadata[trace_keys.TOOL_TRACE][0]["tool"] != "stale_global_trace"
    assert decision.metadata.get("usage") != {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
    assert agent_loop.get_last_loop_trace("P1") == {}


def test_agent_loop_injects_tool_retrieved_ids_into_current_decision() -> None:
    obs = Observation(
        player_id="P1",
        player_name="Alice",
        player_seat=1,
        player_role="Villager",
        day=1,
        phase="DAY_SPEECH",
    )
    decision = {"speech": "我会结合策略发言。", "reasoning": "tool retrieval was useful"}
    tool_trace = [
        {
            "tool": "search_strategies",
            "doc_ids": ["tool-doc", "auto-doc", "tool-doc"],
        }
    ]
    loop = AgentLoop(NativeDecisionLLM(), "system prompt", action_type="speech", player_id="P1")
    with agent_loop._STRATEGY_LOCK:
        agent_loop._LAST_RETRIEVED_STRATEGIES["P1"] = [{"doc_id": "auto-doc"}]
        agent_loop._LAST_LOOP_TRACE.pop("P1", None)

    loop._inject_tool_trace(decision, tool_trace, obs)

    assert decision[trace_keys.AUTO_INJECTED_STRATEGIES] == ["auto-doc"]
    assert decision[trace_keys.RETRIEVED_KNOWLEDGE_IDS] == ["auto-doc", "tool-doc"]
    assert agent_loop.get_last_loop_trace("P1")[trace_keys.COMPAT_RETRIEVED_KNOWLEDGE_IDS] == [
        "auto-doc",
        "tool-doc",
    ]


def test_cognitive_agent_empty_speech_raises_in_strict_mode() -> None:
    view = PlayerView(
        player_id="P1",
        day=1,
        phase="DAY_SPEECH",
        self_player={"id": "P1", "name": "Alice", "seat": 1, "role": "Villager", "alive": True},
        players=[
            {"id": "P1", "name": "Alice", "seat": 1, "role": "Villager", "alive": True},
            {"id": "P2", "name": "Bob", "seat": 2, "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[],
        observations=[],
    )
    agent = create_cognitive_agent_with_character(
        player_id="P1",
        role="Villager",
        llm=EmptySpeechLLM(),
        player_name="Alice",
        player_seat=1,
        character=None,
    )
    agent.initialize(view, {})
    agent.update(view, "TALK")

    with pytest.raises(RuntimeError, match="speech response is empty or too short"):
        agent.talk()


def test_cognitive_agent_required_night_skip_raises_in_strict_mode() -> None:
    view = PlayerView(
        player_id="P1",
        day=1,
        phase="NIGHT_GUARD_ACTION",
        self_player={"id": "P1", "name": "Guard", "seat": 1, "role": "Guard", "alive": True},
        players=[
            {"id": "P1", "name": "Guard", "seat": 1, "role": "Guard", "alive": True},
            {"id": "P2", "name": "Bob", "seat": 2, "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[],
        observations=[],
        legal_targets=[
            {"id": "P1", "name": "Guard", "seat": 1, "alive": True},
            {"id": "P2", "name": "Bob", "seat": 2, "alive": True},
        ],
    )
    agent = create_cognitive_agent_with_character(
        player_id="P1",
        role="Guard",
        llm=SkipNightTargetLLM(),
        player_name="Guard",
        player_seat=1,
        character=None,
    )
    agent.initialize(view, {})
    agent.update(view, "GUARD")

    with pytest.raises(RuntimeError, match="skip keyword"):
        agent.guard()


def test_cognitive_agent_repairs_required_night_empty_target_with_llm_target() -> None:
    view = PlayerView(
        player_id="P1",
        day=1,
        phase="NIGHT_GUARD_ACTION",
        self_player={"id": "P1", "name": "Guard", "seat": 1, "role": "Guard", "alive": True},
        players=[
            {"id": "P1", "name": "Guard", "seat": 1, "role": "Guard", "alive": True},
            {"id": "P2", "name": "Bob", "seat": 2, "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[],
        observations=[],
        legal_targets=[
            {"id": "P1", "name": "Guard", "seat": 1, "alive": True},
            {"id": "P2", "name": "Bob", "seat": 2, "alive": True},
        ],
    )
    llm = EmptyThenValidNightTargetLLM()
    agent = create_cognitive_agent_with_character(
        player_id="P1",
        role="Guard",
        llm=llm,
        player_name="Guard",
        player_seat=1,
        character=None,
    )
    agent.initialize(view, {})
    agent.update(view, "GUARD")

    decision = agent.guard()

    assert decision.action_type == ActionType.GUARD
    assert decision.target_id == "P2"
    assert decision.reasoning == "repair selects a legal night target"
    assert llm.calls == 2
    assert agent.memory.role_state["protections"] == ["D1: P2"]


def test_cognitive_agent_repairs_required_night_text_target_with_llm_target() -> None:
    view = PlayerView(
        player_id="P1",
        day=1,
        phase="NIGHT_GUARD_ACTION",
        self_player={"id": "P1", "name": "Guard", "seat": 1, "role": "Guard", "alive": True},
        players=[
            {"id": "P1", "name": "Guard", "seat": 1, "role": "Guard", "alive": True},
            {"id": "P2", "name": "Bob", "seat": 2, "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[],
        observations=[],
        legal_targets=[
            {"id": "P1", "name": "Guard", "seat": 1, "alive": True},
            {"id": "P2", "name": "Bob", "seat": 2, "alive": True},
        ],
    )
    llm = EmptyThenTextNightTargetLLM()
    agent = create_cognitive_agent_with_character(
        player_id="P1",
        role="Guard",
        llm=llm,
        player_name="Guard",
        player_seat=1,
        character=None,
    )
    agent.initialize(view, {})
    agent.update(view, "GUARD")

    decision = agent.guard()

    assert decision.action_type == ActionType.GUARD
    assert decision.target_id == "P2"
    assert "2号:Bob" in decision.reasoning
    assert llm.calls == 2


def test_cognitive_agent_repairs_required_night_target_after_multiple_llm_attempts() -> None:
    view = PlayerView(
        player_id="P1",
        day=1,
        phase="NIGHT_GUARD_ACTION",
        self_player={"id": "P1", "name": "Guard", "seat": 1, "role": "Guard", "alive": True},
        players=[
            {"id": "P1", "name": "Guard", "seat": 1, "role": "Guard", "alive": True},
            {"id": "P2", "name": "Bob", "seat": 2, "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[],
        observations=[],
        legal_targets=[
            {"id": "P1", "name": "Guard", "seat": 1, "alive": True},
            {"id": "P2", "name": "Bob", "seat": 2, "alive": True},
        ],
    )
    llm = EmptyThenDelayedValidNightTargetLLM()
    agent = create_cognitive_agent_with_character(
        player_id="P1",
        role="Guard",
        llm=llm,
        player_name="Guard",
        player_seat=1,
        character=None,
    )
    agent.initialize(view, {})
    agent.update(view, "GUARD")

    decision = agent.guard()

    assert decision.action_type == ActionType.GUARD
    assert decision.target_id == "P2"
    assert decision.reasoning == "delayed repair selects legal target"
    assert llm.calls == 4


def test_cognitive_agent_required_night_illegal_target_raises_in_strict_mode() -> None:
    view = PlayerView(
        player_id="P1",
        day=1,
        phase="NIGHT_WOLF_ACTION",
        self_player={"id": "P1", "name": "WolfA", "seat": 1, "role": "Werewolf", "alive": True},
        players=[
            {"id": "P1", "name": "WolfA", "seat": 1, "role": "Werewolf", "alive": True},
            {"id": "P2", "name": "狼人队友", "seat": 2, "role": "Werewolf", "alive": True},
            {"id": "P3", "name": "Villager", "seat": 3, "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[{"id": "P2", "name": "狼人队友", "seat": 2, "role": "Werewolf", "alive": True}],
        observations=[],
        legal_targets=[
            {"id": "P3", "name": "Villager", "seat": 3, "alive": True},
            {"id": "P4", "name": "Guard", "seat": 4, "alive": True},
        ],
    )
    agent = create_cognitive_agent_with_character(
        player_id="P1",
        role="Werewolf",
        llm=InvalidNightTargetLLM(),
        player_name="WolfA",
        player_seat=1,
        character=None,
    )
    agent.initialize(view, {})
    agent.update(view, "ATTACK")

    with pytest.raises(RuntimeError, match="illegal attack target"):
        agent.attack()


def test_cognitive_agent_night_decision_repairs_resolved_illegal_target() -> None:
    view = PlayerView(
        player_id="P1",
        day=1,
        phase="NIGHT_WOLF_ACTION",
        self_player={"id": "P1", "name": "WolfA", "seat": 1, "role": "Werewolf", "alive": True},
        players=[
            {"id": "P1", "name": "WolfA", "seat": 1, "role": "Werewolf", "alive": True},
            {"id": "P2", "name": "狼人队友", "seat": 2, "role": "Werewolf", "alive": True},
            {"id": "P3", "name": "Villager", "seat": 3, "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[{"id": "P2", "name": "狼人队友", "seat": 2, "role": "Werewolf", "alive": True}],
        observations=[],
        legal_targets=[{"id": "P3", "name": "Villager", "seat": 3, "alive": True}],
    )
    agent = create_cognitive_agent_with_character(
        player_id="P1",
        role="Werewolf",
        llm=DeterministicCognitiveLLM(),
        player_name="WolfA",
        player_seat=1,
        character=None,
    )
    agent.initialize(view, {})
    agent.update(view, "ATTACK")

    decision = agent._night_decision({"target": "狼人队友", "reasoning": "illegal teammate target"}, ActionType.ATTACK)

    assert decision.action_type == ActionType.ATTACK
    assert decision.target_id == "P3"
    assert decision.reasoning == "offline direct-call decision"


def test_cognitive_agent_repairs_invalid_badge_transfer_target_with_llm_candidate() -> None:
    view = PlayerView(
        player_id="P1",
        day=2,
        phase="BADGE_TRANSFER",
        self_player={"id": "P1", "name": "Sheriff", "seat": 1, "role": "Seer", "alive": False},
        players=[
            {"id": "P1", "name": "Sheriff", "seat": 1, "role": "Seer", "alive": False},
            {"id": "P2", "name": "Bob", "seat": 2, "alive": True},
            {"id": "P3", "name": "Carol", "seat": 3, "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[],
        observations=[],
        legal_targets=[
            {"id": "P2", "name": "Bob", "seat": 2, "alive": True},
            {"id": "P3", "name": "Carol", "seat": 3, "alive": True},
        ],
    )
    llm = InvalidThenValidBadgeLLM()
    agent = create_cognitive_agent_with_character(
        player_id="P1",
        role="Seer",
        llm=llm,
        player_name="Sheriff",
        player_seat=1,
        character=None,
    )
    agent.initialize(view, {})
    agent.update(view, "BADGE_TRANSFER")

    decision = agent.transfer_badge(["P2", "P3"])

    assert decision.action_type == ActionType.VOTE
    assert decision.target_id == "P2"
    assert decision.reasoning == "repair transfers badge to candidate"
    assert llm.calls == 2


def test_cognitive_agent_witch_invalid_json_raises_in_strict_mode() -> None:
    view = PlayerView(
        player_id="P1",
        day=1,
        phase="NIGHT_WITCH_ACTION",
        self_player={"id": "P1", "name": "Witch", "seat": 1, "role": "Witch", "alive": True},
        players=[
            {"id": "P1", "name": "Witch", "seat": 1, "role": "Witch", "alive": True},
            {"id": "P2", "name": "Victim", "seat": 2, "alive": True},
            {"id": "P3", "name": "Target", "seat": 3, "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[],
        observations=[],
        legal_targets=[{"id": "P2", "name": "Victim", "seat": 2, "alive": True}],
    )
    agent = create_cognitive_agent_with_character(
        player_id="P1",
        role="Witch",
        llm=BadWitchLLM(),
        player_name="Witch",
        player_seat=1,
        character=None,
    )
    agent.initialize(view, {})
    agent.update(view, "WITCH")

    with pytest.raises(ValueError, match="did not contain JSON"):
        agent.witch_act("P2")


def test_cognitive_agent_repairs_already_used_antidote_to_skip() -> None:
    view = PlayerView(
        player_id="P1",
        day=2,
        phase="NIGHT_WITCH_ACTION",
        self_player={"id": "P1", "name": "Witch", "seat": 1, "role": "Witch", "alive": True},
        players=[
            {"id": "P1", "name": "Witch", "seat": 1, "role": "Witch", "alive": True},
            {"id": "P2", "name": "Victim", "seat": 2, "alive": True},
            {"id": "P3", "name": "Target", "seat": 3, "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[],
        observations=[],
        legal_targets=[{"id": "P2", "name": "Victim", "seat": 2, "alive": True}],
    )
    llm = UsedAntidoteThenSkipWitchLLM()
    agent = create_cognitive_agent_with_character(
        player_id="P1",
        role="Witch",
        llm=llm,
        player_name="Witch",
        player_seat=1,
        character=None,
    )
    agent.initialize(view, {})
    agent.update(view, "WITCH")
    agent._witch_save_used = True

    decisions = agent.witch_act("P2")

    assert len(decisions) == 1
    assert decisions[0].action_type == ActionType.SKIP
    assert decisions[0].reasoning == "antidote already used, skip tonight"
    assert llm.calls == 2


def test_cognitive_agent_direct_action_invalid_target_raises_in_strict_mode() -> None:
    view = PlayerView(
        player_id="P1",
        day=1,
        phase="HUNTER_SHOOT",
        self_player={"id": "P1", "name": "Hunter", "seat": 1, "role": "Hunter", "alive": False},
        players=[
            {"id": "P1", "name": "Hunter", "seat": 1, "role": "Hunter", "alive": False},
            {"id": "P2", "name": "Bob", "seat": 2, "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[],
        observations=[],
        legal_targets=[{"id": "P2", "name": "Bob", "seat": 2, "alive": True}],
    )
    agent = create_cognitive_agent_with_character(
        player_id="P1",
        role="Hunter",
        llm=InvalidDirectTargetLLM(),
        player_name="Hunter",
        player_seat=1,
        character=None,
    )
    agent.initialize(view, {})
    agent.update(view, "SHOOT")

    with pytest.raises(RuntimeError, match="invalid shoot target"):
        agent.shoot()


def test_cognitive_agent_repairs_required_shoot_skip_with_llm_target() -> None:
    view = PlayerView(
        player_id="P1",
        day=1,
        phase="HUNTER_SHOOT",
        self_player={"id": "P1", "name": "Hunter", "seat": 1, "role": "Hunter", "alive": False},
        players=[
            {"id": "P1", "name": "Hunter", "seat": 1, "role": "Hunter", "alive": False},
            {"id": "P2", "name": "Bob", "seat": 2, "alive": True},
        ],
        public_events=[],
        private_events=[],
        known_wolves=[],
        observations=[],
        legal_targets=[{"id": "P2", "name": "Bob", "seat": 2, "alive": True}],
    )
    llm = SkipThenValidShootLLM()
    agent = create_cognitive_agent_with_character(
        player_id="P1",
        role="Hunter",
        llm=llm,
        player_name="Hunter",
        player_seat=1,
        character=None,
    )
    agent.initialize(view, {})
    agent.update(view, "SHOOT")

    decision = agent.shoot()

    assert llm.calls == 2
    assert decision.action_type == ActionType.SHOOT
    assert decision.target_id == "P2"
    assert decision.reasoning == "repair selects a legal target"


def test_reflector_malformed_output_still_produces_knowledge_docs() -> None:
    reflections = Reflector(MalformedReflectionLLM()).reflect_game(
        "game-reflect-1",
        [
            {
                "player_id": "P1",
                "player_name": "Alice",
                "role": "Seer",
                "persona": {"mbti": "INTJ"},
                "won": False,
                "decisions": [{"action_type": "vote", "target": "Bob", "speech": ""}],
                "game_events": [{"type": "VOTE_CAST", "description": "Alice voted Bob"}],
            }
        ],
    )
    docs = reflections_to_knowledge_docs(reflections, "game-reflect-1")

    assert reflections[0].confidence == 0.35
    assert docs
    assert all(doc["doc_type"] == "reflection" for doc in docs)
    assert all(doc["source_report_ids"] == ["game-reflect-1"] for doc in docs)


def test_observe_keeps_engine_seer_result_private_info() -> None:
    view = PlayerView(
        player_id="P1",
        day=1,
        phase="DAY_SPEECH",
        self_player={"id": "P1", "name": "Alice", "seat": 1, "role": "Seer", "alive": True},
        players=[
            {"id": "P1", "name": "Alice", "seat": 1, "role": "Seer", "alive": True},
            {"id": "P2", "name": "Bob", "seat": 2, "alive": True},
        ],
        public_events=[],
        private_events=[
            {
                "type": "PRIVATE_INFO",
                "day": 1,
                "payload": {
                    "kind": "seer_result",
                    "target_id": "P2",
                    "target_name": "Bob",
                    "is_wolf": True,
                    "message": "Seer check: Bob is wolf.",
                },
            }
        ],
        known_wolves=[],
        observations=[],
    )

    obs = observe(view, "Seer")

    assert obs.private["seer_check"]["target_name"] == "Bob"
    assert obs.private["seer_check"]["is_wolf"] is True


def test_cognitive_agents_complete_offline_game_and_emit_decisions() -> None:
    seed = 42
    roles = get_role_configuration(7)
    players = build_players(roles, seed=seed)
    fake_llm = DeterministicCognitiveLLM()
    cognitive_agents = {
        player.id: create_cognitive_agent_with_character(
            player_id=player.id,
            role=player.role.value,
            llm=fake_llm,
            player_name=player.name,
            player_seat=player.seat,
            character=None,
        )
        for player in players
    }
    for player in players:
        player.agent_type = "llm"
    game = WerewolfGame(players=players, agents=cognitive_agents, seed=seed, max_days=3)

    state = game.play()

    assert state.phase == Phase.GAME_END
    assert state.winner is not None
    assert len(state.players) == 7
    assert any(event.type == EventType.CHAT_MESSAGE for event in state.events)
    assert any(event.type == EventType.VOTE_CAST for event in state.events)
    assert any(event.type == EventType.NIGHT_ACTION for event in state.events)
    assert fake_llm.calls
    assert any("【任务：发言】" in call for call in fake_llm.calls)
    assert any("【任务：投票】" in call for call in fake_llm.calls)
    assert any("【任务：夜晚行动】" in call for call in fake_llm.calls)
    assert state.decision_records
    assert all(record.parsed_action for record in state.decision_records)
