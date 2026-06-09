from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import HumanMessage

from backend.agents.cognitive.factory import create_llm_from_client
from backend.agents.factory import _create_llm_runnable
from backend.agents.factory import _resolve_pool_specs
from backend.agents.factory import create_agents
from backend.engine.models import Alignment
from backend.engine.models import Player
from backend.engine.models import Role
from backend.llm import create_client
from backend.llm.anthropic_client import AnthropicClient
from backend.llm.deepseek import DeepSeekClient

ROOT = Path(__file__).resolve().parent.parent


def test_makefile_defaults_to_venv_python_for_test_targets() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "PYTHON  ?= .venv/bin/python3" in makefile
    assert "$(PYTHON) -m pytest tests/" in makefile


def test_create_client_infers_deepseek_from_model() -> None:
    client = create_client(provider=None, model="deepseek-v4-flash")
    assert client.base_url == "https://api.deepseek.com"
    assert client.model == "deepseek-v4-flash"


def test_create_client_defaults_to_dsv4flash(monkeypatch) -> None:
    # Stub load_env_file so the test exercises the in-code defaults rather
    # than the user's .env.
    monkeypatch.setattr("backend.llm.load_env_file", lambda *a, **k: None)
    for var in (
        "LLM_PROVIDER",
        "DSV4FLASH_API_KEY",
        "DSV4FLASH_BASE_URL",
        "DSV4FLASH_MODEL",
        "DOUBAO_API_KEY",
        "ARK_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "DOUBAO_ENDPOINT",
        "DOUBAO_MODEL",
        "ANTHROPIC_MODEL",
        "DOUBAO_BASE_URL",
        "ARK_BASE_URL",
        "ANTHROPIC_BASE_URL",
        "MIMO_BASE_URL",
        "MIMO_MODEL",
        "MIMO_API_KEY",
        "WEAPI_API_KEY",
        "WEAPI_BASE_URL",
        "WEAPI_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DSV4FLASH_API_KEY", "test-key")
    client = create_client(provider=None)
    assert client.provider == "dsv4flash"
    assert client.model == "deepseek-v4-flash"


def test_create_client_mimo_requires_base_url(monkeypatch) -> None:
    monkeypatch.setattr("backend.llm.load_env_file", lambda *a, **k: None)
    monkeypatch.delenv("MIMO_BASE_URL", raising=False)
    client = create_client(provider="mimo")

    assert client.provider == "mimo"
    assert client.available is False


def test_create_client_mimo_uses_openai_compatible_endpoint(monkeypatch) -> None:
    monkeypatch.setattr("backend.llm.load_env_file", lambda *a, **k: None)
    monkeypatch.setenv("MIMO_BASE_URL", "http://127.0.0.1:8001/v1")
    monkeypatch.setenv("MIMO_MODEL", "mimo-test")
    monkeypatch.delenv("MIMO_API_KEY", raising=False)

    client = create_client(provider="mimo")

    assert client.provider == "mimo"
    assert client.base_url == "http://127.0.0.1:8001/v1"
    assert client.model == "mimo-test"
    assert client.api_key == "local"


def test_create_client_weapi_normalizes_endpoint_and_model(monkeypatch) -> None:
    monkeypatch.setattr("backend.llm.load_env_file", lambda *a, **k: None)
    monkeypatch.setenv("WEAPI_API_KEY", "test-key")
    monkeypatch.setenv("WEAPI_BASE_URL", "https://weapi.pw/")
    monkeypatch.setenv("WEAPI_MODEL", "gpt-5.5")

    client = create_client(provider="weapi")

    assert client.provider == "weapi"
    assert client.base_url == "https://weapi.pw/v1"
    assert client.model == "gpt-5.5"


def test_create_client_infers_weapi_from_model(monkeypatch) -> None:
    monkeypatch.setattr("backend.llm.load_env_file", lambda *a, **k: None)
    monkeypatch.setenv("WEAPI_API_KEY", "test-key")

    client = create_client(provider=None, model="gpt-5.5")

    assert client.provider == "weapi"
    assert client.base_url == "https://weapi.pw/v1"


def test_create_client_infers_weapi_from_base_url(monkeypatch) -> None:
    monkeypatch.setattr("backend.llm.load_env_file", lambda *a, **k: None)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    client = create_client(
        provider=None,
        api_key="test-key",
        base_url="https://weapi.pw",
        model="gpt-5.5",
    )

    assert client.provider == "weapi"
    assert client.base_url == "https://weapi.pw/v1"
    assert client.model == "gpt-5.5"


def test_create_client_infers_anthropic_messages_from_deepseek_anthropic_url(monkeypatch) -> None:
    monkeypatch.setattr("backend.llm.load_env_file", lambda *a, **k: None)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    client = create_client(
        provider=None,
        api_key="test-key",
        base_url="https://api.deepseek.com/anthropic",
        model="deepseek-v4-flash",
    )

    assert client.provider == "anthropic"
    assert client.base_url == "https://api.deepseek.com/anthropic"
    assert client.model == "deepseek-v4-flash"
    assert client.api_key == "test-key"


def test_create_client_anthropic_defaults_to_deepseek_compatible_settings(monkeypatch) -> None:
    monkeypatch.setattr("backend.llm.load_env_file", lambda *a, **k: None)
    for var in (
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_MODEL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_ANTHROPIC_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "deepseek-compatible-token")

    client = create_client(provider="anthropic")

    assert client.provider == "anthropic"
    assert client.api_key == "deepseek-compatible-token"
    assert client.base_url == "https://api.deepseek.com/anthropic"
    assert client.model == "deepseek-v4-flash"


def test_anthropic_client_normalizes_coding_v1_base_url() -> None:
    client = AnthropicClient(
        api_key="test-key",
        base_url="https://ark.cn-beijing.volces.com/api/coding/v1",
        model="deepseek-v4-flash[1m]",
    )

    assert client.base_url == "https://ark.cn-beijing.volces.com/api/coding"


def test_create_client_anthropic_accepts_official_anthropic_api_key(monkeypatch) -> None:
    monkeypatch.setattr("backend.llm.load_env_file", lambda *a, **k: None)
    for var in (
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_MODEL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_ANTHROPIC_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "official-anthropic-key")

    client = create_client(provider="anthropic")

    assert client.provider == "anthropic"
    assert client.api_key == "official-anthropic-key"
    assert client.base_url == "https://api.anthropic.com"
    assert client.model == "claude-sonnet-4-6"


def test_create_client_anthropic_uses_deepseek_api_key_as_fallback(monkeypatch) -> None:
    monkeypatch.setattr("backend.llm.load_env_file", lambda *a, **k: None)
    for var in (
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_MODEL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_ANTHROPIC_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-api-key")

    client = create_client(provider="anthropic")

    assert client.provider == "anthropic"
    assert client.api_key == "deepseek-api-key"
    assert client.base_url == "https://api.deepseek.com/anthropic"
    assert client.model == "deepseek-v4-flash"


def test_model_pool_anthropic_uses_deepseek_compatible_defaults(monkeypatch) -> None:
    for var in (
        "MODEL_POOL",
        "DOUBAO_MODEL_POOL",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "ANTHROPIC_BASE_URL",
        "DEEPSEEK_ANTHROPIC_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MODEL_POOL", "anthropic:deepseek-v4-flash")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "deepseek-compatible-token")

    specs = _resolve_pool_specs({})

    assert specs == [
        {
            "provider": "anthropic",
            "api_key": "deepseek-compatible-token",
            "base_url": "https://api.deepseek.com/anthropic",
            "model": "deepseek-v4-flash",
        }
    ]


def test_create_client_env_timeout_and_retries_are_applied(monkeypatch) -> None:
    monkeypatch.setattr("backend.llm.load_env_file", lambda *a, **k: None)
    monkeypatch.setenv("DSV4FLASH_API_KEY", "test-key")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("LLM_MAX_RETRIES", "4")

    client = create_client(provider="dsv4flash")

    assert client.max_retries == 4
    assert client.timeout.read == 60


def test_create_llm_runnable_applies_explicit_timeout_and_retries(monkeypatch) -> None:
    monkeypatch.setattr("backend.llm.load_env_file", lambda *a, **k: None)
    monkeypatch.setenv("WEAPI_API_KEY", "test-key")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("LLM_MAX_RETRIES", "3")

    runnable = _create_llm_runnable(
        provider="weapi",
        model="gpt-5.5",
        api_key=None,
        base_url="https://weapi.pw",
    )
    client = runnable._client

    assert client.max_retries == 3
    assert client.timeout.read == 45
    assert client._sync_client.timeout.read == 45


def test_tool_calling_runnable_forces_submit_decision_and_disables_thinking() -> None:
    class RecordingClient:
        provider = "test"
        model = "test-model"

        def __init__(self) -> None:
            self.payloads: list[dict] = []

        def chat_sync(self, **kwargs):
            self.payloads.append(kwargs)
            return {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_decision",
                                    "type": "function",
                                    "function": {
                                        "name": "submit_decision",
                                        "arguments": '{"target": "Bob", "reasoning": "forced"}',
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "_latency_ms": 3,
            }

    schema = {
        "type": "function",
        "function": {
            "name": "submit_decision",
            "description": "submit",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    client = RecordingClient()
    runnable = create_llm_from_client(client).bind_tools([schema])

    response = runnable.invoke([HumanMessage(content="vote")], force_tool_name="submit_decision", max_tokens=123)

    assert response.tool_calls[0]["name"] == "submit_decision"
    payload = client.payloads[0]
    assert payload["max_tokens"] == 123
    assert payload["thinking"] is False
    assert payload["tool_choice"] == {"type": "function", "function": {"name": "submit_decision"}}
    assert payload["tools"] == [schema]


def test_tool_calling_runnable_disables_thinking_without_tools() -> None:
    class RecordingClient:
        provider = "test"
        model = "test-model"

        def __init__(self) -> None:
            self.payloads: list[dict] = []

        def chat_sync(self, **kwargs):
            self.payloads.append(kwargs)
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": 'DECISION: {"target": "Bob", "reasoning": "text mode"}',
                        },
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "_latency_ms": 3,
            }

    client = RecordingClient()
    runnable = create_llm_from_client(client)

    response = runnable.invoke([HumanMessage(content="vote")], max_tokens=123)

    assert response.content
    payload = client.payloads[0]
    assert payload["max_tokens"] == 123
    assert payload["thinking"] is False
    assert "tools" not in payload
    assert "tool_choice" not in payload


def test_deepseek_tool_calling_sends_disabled_thinking_object() -> None:
    class CapturePostClient:
        timeout = httpx.Timeout(1.0)

        def __init__(self) -> None:
            self.payload: dict | None = None

        def post(self, url: str, **kwargs):
            self.payload = kwargs["json"]
            request = httpx.Request("POST", url)
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [],
                            }
                        }
                    ]
                },
                request=request,
            )

    tool = {
        "type": "function",
        "function": {
            "name": "submit_decision",
            "description": "submit",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    client = DeepSeekClient(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        max_retries=0,
    )
    capture = CapturePostClient()
    client._sync_client = capture

    client.chat_sync(
        [{"role": "user", "content": "call tool"}],
        tools=[tool],
        tool_choice={"type": "function", "function": {"name": "submit_decision"}},
        thinking=False,
    )

    assert capture.payload is not None
    assert capture.payload["thinking"] == {"type": "disabled"}
    assert capture.payload["tool_choice"] == {"type": "function", "function": {"name": "submit_decision"}}


def test_deepseek_text_mode_sends_disabled_thinking_object() -> None:
    class CapturePostClient:
        timeout = httpx.Timeout(1.0)

        def __init__(self) -> None:
            self.payload: dict | None = None

        def post(self, url: str, **kwargs):
            self.payload = kwargs["json"]
            request = httpx.Request("POST", url)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
                request=request,
            )

    client = DeepSeekClient(
        api_key="test-key",
        base_url="https://ark.cn-beijing.volces.com/api/coding/v1",
        model="deepseek-v4-flash",
        max_retries=0,
    )
    capture = CapturePostClient()
    client._sync_client = capture

    client.chat_sync(
        [{"role": "user", "content": "return content"}],
        thinking=False,
    )

    assert capture.payload is not None
    assert capture.payload["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in capture.payload


def test_deepseek_max_retries_zero_does_not_sleep_on_timeout(monkeypatch) -> None:
    class TimeoutPostClient:
        timeout = httpx.Timeout(1.0)

        def post(self, *args, **kwargs):
            raise httpx.TimeoutException("boom")

    slept: list[float] = []
    client = DeepSeekClient(api_key="test-key", base_url="https://example.invalid/v1", model="test", max_retries=0)
    client._sync_client = TimeoutPostClient()
    monkeypatch.setattr("backend.llm.deepseek.time.sleep", lambda seconds: slept.append(seconds))

    with pytest.raises(httpx.TimeoutException):
        client.chat_sync([{"role": "user", "content": "x"}], max_tokens=1)

    assert slept == []


def test_fake_llm_uses_public_pressure_when_target_is_legal() -> None:
    client = create_client(provider="fake")
    prompt = (
        "=== 当前状态 ===\n"
        "你是 3号:Carol，身份=Villager\n"
        "合法目标：1号:Alice，2号:Bob，4号:Dave\n"
        "=== 今日发言 ===\n"
        "1号:Alice：我是预言家，查杀 Bob，今天归票 Bob。\n"
        "【任务：投票】\n"
        "选择一个存活玩家投票放逐。\n"
    )

    response = client.chat_sync([{"role": "user", "content": prompt}])

    content = response["choices"][0]["message"]["content"]
    assert '"target": "Bob"' in content


def test_fake_llm_uses_latest_legal_targets_for_pk_revote() -> None:
    client = create_client(provider="fake")
    prompt = (
        "=== 当前状态 ===\n"
        "你是 3号:Carol，身份=Villager\n"
        "合法目标：1号:Alice，2号:Bob，4号:Dave\n"
        "【上一轮分析】\n"
        "上一轮认为 Dave 有压力。\n"
        "=== 当前状态 ===\n"
        "第1天 / DAY_VOTE阶段\n"
        "合法目标：1号:Alice，2号:Bob\n"
        "【任务：投票】\n"
        "选择一个存活玩家投票放逐。\n"
    )

    response = client.chat_sync([{"role": "user", "content": prompt}])

    content = response["choices"][0]["message"]["content"]
    assert '"target": "Alice"' in content
    assert "Dave" not in content


def test_fake_llm_strategy_bias_avoids_checked_good_target() -> None:
    client = create_client(provider="fake")
    prompt = (
        "=== 当前状态 ===\n"
        "你是 3号:Carol，身份=Villager\n"
        "合法目标：1号:Alice，2号:Bob，4号:Dave\n"
        "=== 今日发言 ===\n"
        "1号:Alice：Bob 是金水，Dave 的票型更可疑。\n"
        "【任务：投票】\n"
        "选择一个存活玩家投票放逐。\n"
        "【本局强制策略规则 — 高优先级，必须严格遵守】\n"
        "- [vote_policy] 禁止投自己已查的好人\n"
    )

    response = client.chat_sync([{"role": "user", "content": prompt}])

    content = response["choices"][0]["message"]["content"]
    assert '"target": "Dave"' in content
    assert "strategy-aware" in content


def test_fake_llm_strategy_bias_skips_pressure_target_when_checked_good() -> None:
    client = create_client(provider="fake")
    prompt = (
        "=== 当前状态 ===\n"
        "你是 3号:Carol，身份=Villager\n"
        "合法目标：1号:Alice，2号:Bob，4号:Dave\n"
        "=== 今日发言 ===\n"
        "1号:Alice：Bob 是金水，但也有人在归票 Bob。\n"
        "【任务：投票】\n"
        "选择一个存活玩家投票放逐。\n"
        "【本局强制策略规则 — 高优先级，必须严格遵守】\n"
        "- [vote_policy] 禁止投自己已查的好人\n"
    )

    response = client.chat_sync([{"role": "user", "content": prompt}])

    content = response["choices"][0]["message"]["content"]
    assert '"target": "Bob"' not in content
    assert "Bob" not in content


def test_fake_llm_baseline_avoids_checked_good_target() -> None:
    client = create_client(provider="fake")
    prompt = (
        "=== 当前状态 ===\n"
        "你是 3号:Carol，身份=Villager\n"
        "合法目标：1号:Alice，2号:Bob，4号:Dave\n"
        "=== 今日发言 ===\n"
        "1号:Alice：Bob 是金水，但也有人在归票 Bob。\n"
        "【任务：投票】\n"
        "选择一个存活玩家投票放逐。\n"
    )

    response = client.chat_sync([{"role": "user", "content": prompt}])

    content = response["choices"][0]["message"]["content"]
    payload = json.loads(content.replace("DECISION: ", "", 1))
    assert payload["target"] in {"Alice", "Dave"}
    assert payload["target"] != "Bob"


def test_fake_llm_werewolf_strategy_avoids_teammate_target() -> None:
    client = create_client(provider="fake")
    prompt = (
        "=== 当前状态 ===\n"
        "你是 3号:WolfA，身份=Werewolf\n"
        "存活：1号:SeerA，2号:GuardA，3号:WolfA，4号:WolfB\n"
        "合法目标：1号:SeerA，2号:GuardA，4号:WolfB\n"
        "狼队友: WolfB\n"
        "【任务：夜晚行动】\n"
        "选择一个目标执行你的夜晚能力。\n"
        "【本局强制策略规则 — 高优先级，必须严格遵守】\n"
        "- [skill_policy] 夜里必须优先刀关键身份(预言家/猎人/女巫)\n"
        "- [vote_policy] 禁止投自己的狼队友\n"
    )

    response = client.chat_sync([{"role": "user", "content": prompt}])

    content = response["choices"][0]["message"]["content"]
    assert '"target": "SeerA"' in content
    assert "WolfB" not in content


def test_fake_llm_werewolf_night_strategy_prefers_visible_villager_endgame_target() -> None:
    client = create_client(provider="fake")
    prompt = (
        "=== 当前状态 ===\n"
        "你是 1号:WolfA，身份=Werewolf\n"
        "存活：1号:WolfA，2号:WolfB，3号:VillagerA，4号:SeerA，5号:WitchA\n"
        "合法目标：3号:VillagerA，4号:SeerA，5号:WitchA\n"
        "狼队友: WolfB\n"
        "【任务：夜晚行动】\n"
        "选择一个目标执行你的夜晚能力。\n"
        "【本局强制策略规则 — 高优先级，必须严格遵守】\n"
        "- [skill_policy] 夜里必须优先刀关键身份(预言家/猎人/女巫)\n"
        "- [risk_rules] 终结局优先选择能推进胜利条件的目标\n"
    )

    response = client.chat_sync([{"role": "user", "content": prompt}])

    content = response["choices"][0]["message"]["content"]
    assert '"target": "VillagerA"' in content
    assert "WolfB" not in content


def test_fake_llm_werewolf_strategy_uses_private_known_wolves_line() -> None:
    client = create_client(provider="fake")
    prompt = (
        "=== 当前状态 ===\n"
        "你是 3号:WolfA，身份=Werewolf\n"
        "存活：1号:SeerA，2号:GuardA，3号:WolfA，4号:WolfB\n"
        "合法目标：1号:SeerA，2号:GuardA，4号:WolfB\n"
        "=== 私有信息 ===\n"
        "  known_wolves: ['3号:WolfA', '4号:WolfB']\n"
        "=== 今日发言 ===\n"
        "1号:SeerA：今天可以归票 WolfB。\n"
        "【任务：投票】\n"
        "选择一个存活玩家投票放逐。\n"
        "【本局强制策略规则 — 高优先级，必须严格遵守】\n"
        "- [vote_policy] 禁止投自己的狼队友\n"
    )

    response = client.chat_sync([{"role": "user", "content": prompt}])

    content = response["choices"][0]["message"]["content"]
    assert '"target": "SeerA"' in content
    assert "WolfB" not in content


def test_fake_llm_werewolf_speech_strategy_avoids_teammate_without_legal_targets() -> None:
    client = create_client(provider="fake")
    prompt = (
        "=== 当前状态 ===\n"
        "你是 1号:WolfA，身份=Werewolf\n"
        "存活：1号:WolfA，2号:WolfB，3号:VillagerA，4号:SeerA\n"
        "=== 私有信息 ===\n"
        "  known_wolves: ['1号:WolfA', '2号:WolfB']\n"
        "【任务：发言】\n"
        "请发表白天发言。\n"
        "【本局强制策略规则 — 高优先级，必须严格遵守】\n"
        "- [speech_policy] 白天必须积极发言伪装好人\n"
        "- [vote_policy] 禁止投自己的狼队友\n"
    )

    response = client.chat_sync([{"role": "user", "content": prompt}])

    content = response["choices"][0]["message"]["content"]
    assert "WolfB" not in content
    assert "VillagerA" in content or "SeerA" in content
    assert "归票" in content


def test_fake_llm_guard_strategy_prefers_stable_legal_target() -> None:
    client = create_client(provider="fake")
    prompt = (
        "=== 当前状态 ===\n"
        "你是 5号:GuardA，身份=Guard\n"
        "合法目标：1号:SeerA，2号:WitchA，5号:GuardA\n"
        "【任务：夜晚行动】\n"
        "选择一个目标执行你的夜晚能力。\n"
        "【本局强制策略规则 — 高优先级，必须严格遵守】\n"
        "- [skill_policy] 必须优先守预言家/女巫/猎人\n"
    )

    response = client.chat_sync([{"role": "user", "content": prompt}])

    content = response["choices"][0]["message"]["content"]
    assert '"target": "GuardA"' in content
    assert "strategy-aware" in content


def test_fake_llm_witch_strategy_saves_visible_night_victim() -> None:
    client = create_client(provider="fake")
    prompt = (
        "=== 当前状态 ===\n"
        "你是 4号:WitchA，身份=Witch\n"
        "合法目标：1号:SeerA，2号:WolfA\n"
        "【本局强制策略规则 — 高优先级，必须严格遵守】\n"
        "- [skill_policy] 解药必须留给关键身份(预言家/猎人/守卫)\n"
        "解药可用\n"
        "毒药可用\n"
        "今晚被刀的是: 1号:SeerA\n"
        "你是女巫，请决定本晚是否用药。\n"
        '只输出 JSON 对象：{"reasoning": "理由", "save": false, "poison_target": null}\n'
    )

    response = client.chat_sync([{"role": "user", "content": prompt}])

    payload = json.loads(response["choices"][0]["message"]["content"])
    assert payload["save"] is True
    assert payload["poison_target"] is None
    assert "role-task" in payload["reasoning"]


def test_create_agents_applies_role_model_overrides() -> None:
    from backend.agents.cognitive.agent import CognitiveAgent

    players = [
        Player(id="p1", seat=1, name="P1", role=Role.WEREWOLF, alignment=Alignment.WOLF),
        Player(id="p2", seat=2, name="P2", role=Role.SEER, alignment=Alignment.VILLAGE),
        Player(id="p3", seat=3, name="P3", role=Role.VILLAGER, alignment=Alignment.VILLAGE),
    ]

    agents = create_agents(
        players,
        {
            "type": "llm",
            "provider": "fake",
            "model": "doubao-default",
            "role_models": {
                "Werewolf": {"provider": "fake", "model": "deepseek-v4-pro[1m]"},
                "SEER": {"provider": "fake", "model": "deepseek-v4-flash"},
                "Villager": {"provider": "fake", "model": "glm-5.1[1m]"},
            },
        },
    )

    # P1 (Werewolf): CognitiveAgent with role model override
    assert isinstance(agents["p1"], CognitiveAgent)
    assert players[0].model_name == "deepseek-v4-pro[1m]"
    # P2 (Seer): CognitiveAgent with provider+model override
    assert isinstance(agents["p2"], CognitiveAgent)
    assert players[1].model_name == "deepseek-v4-flash"
    # P3 (Villager): still LLM-backed, with role model override
    assert isinstance(agents["p3"], CognitiveAgent)
    assert players[2].model_name == "glm-5.1[1m]"
    assert players[2].agent_type == "llm"


def test_create_agents_explicit_provider_ignores_env_model_pool(monkeypatch) -> None:
    """Pinned provider/client config must not be mixed with MODEL_POOL specs."""
    from backend.agents.cognitive.agent import CognitiveAgent

    monkeypatch.setenv("MODEL_POOL", "deepseek:deepseek-v4-flash")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "pool-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    players = [
        Player(id="p1", seat=1, name="P1", role=Role.VILLAGER, alignment=Alignment.VILLAGE),
    ]

    agents = create_agents(players, {"type": "llm", "provider": "fake"})

    assert isinstance(agents["p1"], CognitiveAgent)
    assert getattr(agents["p1"]._llm, "provider", "") == "fake"
    assert getattr(agents["p1"]._llm, "model", "") == "fake-llm"
    assert players[0].model_name == ""


def test_create_agents_rejects_heuristic_override() -> None:
    players = [
        Player(id="p1", seat=1, name="P1", role=Role.VILLAGER, alignment=Alignment.VILLAGE),
    ]

    with pytest.raises(ValueError, match="heuristic agents are disabled"):
        create_agents(
            players,
            {
                "type": "llm",
                "provider": "fake",
                "role_models": {"Villager": {"type": "heuristic"}},
            },
        )
