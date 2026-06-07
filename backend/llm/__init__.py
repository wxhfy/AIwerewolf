from __future__ import annotations

import json
import os
import re
from typing import Any

from backend.llm.deepseek import DeepSeekClient
from backend.llm.deepseek import KeyFallbackClient
from backend.llm.deepseek import create_key_fallback_client
from backend.llm.env import load_env_file

__all__ = [
    "DeepSeekClient",
    "KeyFallbackClient",
    "create_client",
    "create_key_fallback_client",
    "load_env_file",
]


_DEFAULT_DOUBAO_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
_DEFAULT_DOUBAO_MODEL = "Doubao-Seed-2.0-pro"
_DEFAULT_ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding/v1"
_DEFAULT_PROVIDER = "dsv4flash"
_DEFAULT_WEAPI_BASE_URL = "https://weapi.pw/v1"

# Multi-model pool: "provider:model" entries, comma-separated
# Supports: doubao, dsv4flash, ark (generic Ark API), deepseek, mimo
# Examples:
#   DOUBAO_MODEL_POOL="deepseek-v4-pro[1m],kimi-k2.6[1m],glm-5.1[1m]"
#   MODEL_POOL="ark:deepseek-v4-pro[1m],ark:kimi-k2.6[1m],doubao:ep-xxx,deepseek:deepseek-v4-flash,mimo:mimo-local"


class _UnavailableLLMClient:
    """Unavailable client marker used to fail fast in LLM-only game mode."""

    def __init__(self, provider: str, model: str, base_url: str):
        self.provider = provider
        self.model = model
        self.base_url = base_url
        self.timeout = 12.0
        self.available = False

    def chat_sync(self, *args, **kwargs):
        raise RuntimeError(f"{self.provider} client unavailable: missing API key")

    async def chat(self, *args, **kwargs):
        raise RuntimeError(f"{self.provider} client unavailable: missing API key")


class _FakeLLMClient:
    """Deterministic local LLM-compatible client for CI and smoke tests."""

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
                {
                    "speech": speech,
                    "reasoning": "fake LLM speech decision",
                },
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
            seer_target = _FakeLLMClient._seer_strategy_target(text)
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
        seer_target = _FakeLLMClient._seer_strategy_target(text)
        legal_matches = re.findall(r"合法目标[:：]\s*([^\n]+)", text)
        if legal_matches:
            # AgentLoop prompts can contain cached analysis plus the current
            # observation. Use the latest legal-target block so a PK re-vote
            # cannot be polluted by stale regular-vote context.
            legal_names = [name.strip() for name in re.findall(r"@?\d+号[:：]([^，,\n]+)", legal_matches[-1])]
            if seer_target and seer_target in legal_names:
                return seer_target
            pressure_target = _FakeLLMClient._public_pressure_target(text, legal_names)
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
        if not any(token in text for token in ("wolf check", "查杀", "查验结果", "confirmed information")):
            return ""
        if not re.search(r"is_wolf['\"]?\s*:\s*True|is_wolf['\"]?\s*:\s*true", text):
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


def create_client(provider: str | None = None, **kwargs) -> Any:
    """Create an LLM client based on LLM_PROVIDER env or explicit provider.

    Supports:
    - doubao: 方舟 doubao-seed 2.0 pro & code (primary)
    - deepseek: DeepSeek v4 Flash (fallback)
    - mimo: local OpenAI-compatible endpoint configured by MIMO_BASE_URL
    - weapi: OpenAI-compatible endpoint at https://weapi.pw/v1
    - fake: deterministic local LLM-compatible client for tests
    """
    import os

    load_env_file()
    kwargs = dict(kwargs)
    if "max_retries" not in kwargs:
        max_retries_raw = os.getenv("LLM_MAX_RETRIES", "").strip()
        if max_retries_raw:
            try:
                kwargs["max_retries"] = max(0, int(max_retries_raw))
            except ValueError:
                pass
    if "timeout" not in kwargs:
        timeout_raw = os.getenv("LLM_TIMEOUT_SECONDS", "").strip()
        if timeout_raw:
            try:
                kwargs["timeout"] = max(0.1, float(timeout_raw))
            except ValueError:
                pass
    explicit_model = kwargs.get("model")
    explicit_base_url = kwargs.get("base_url")
    if provider is None:
        if explicit_base_url:
            base_url = str(explicit_base_url).lower()
            if "weapi" in base_url:
                provider = "weapi"
            elif "deepseek" in base_url:
                provider = "deepseek"
            elif "mimo" in base_url:
                provider = "mimo"
            elif "ark." in base_url or "volces" in base_url:
                provider = "doubao"
        if provider is None and explicit_model:
            model_name = str(explicit_model).lower()
            if model_name.startswith("gpt-5.5") or model_name == "gpt-5.5":
                provider = "weapi"
            elif "deepseek" in model_name:
                provider = "deepseek"
            elif "mimo" in model_name:
                provider = "mimo"
            elif "doubao" in model_name:
                provider = "doubao"
        if provider is None:
            provider = os.getenv("LLM_PROVIDER", _DEFAULT_PROVIDER)
    provider = str(provider).strip().lower()

    if provider in {"fake", "fake_llm", "offline_llm"}:
        model = kwargs.pop("model", None) or os.getenv("FAKE_LLM_MODEL", "fake-llm")
        return _FakeLLMClient(model=str(model))
    if provider == "doubao":
        api_key = (
            kwargs.pop("api_key", None)
            or os.getenv("DOUBAO_API_KEY", "")
            or os.getenv("ARK_API_KEY", "")
            or os.getenv("ANTHROPIC_AUTH_TOKEN", "")
        )
        base_url = (
            kwargs.pop("base_url", None)
            or os.getenv("DOUBAO_BASE_URL", "")
            or os.getenv("ARK_BASE_URL", "")
            or os.getenv("ANTHROPIC_BASE_URL", "")
            or _DEFAULT_DOUBAO_BASE_URL
        )
        model = (
            kwargs.pop("model", None)
            or os.getenv("DOUBAO_ENDPOINT", "")
            or os.getenv("DOUBAO_MODEL", "")
            or os.getenv("ANTHROPIC_MODEL", "")
            or _DEFAULT_DOUBAO_MODEL
        )
        if not api_key:
            return _UnavailableLLMClient(provider="doubao", model=model, base_url=base_url)
        client = DeepSeekClient(
            api_key=api_key,
            base_url=base_url,
            model=model,
            **kwargs,
        )
        client.provider = "doubao"
        return client
    elif provider == "deepseek":
        api_key = kwargs.pop("api_key", None) or os.getenv("DEEPSEEK_API_KEY", "")
        base_url = kwargs.pop("base_url", None) or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        model = kwargs.pop("model", None) or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
        if not api_key:
            return _UnavailableLLMClient(provider="deepseek", model=model, base_url=base_url)
        client = DeepSeekClient(
            api_key=api_key,
            base_url=base_url,
            model=model,
            **kwargs,
        )
        client.provider = "deepseek"
        return client
    elif provider == "dsv4flash":
        # DeepSeek V4 Flash via 火山引擎 Ark (dedicated endpoint)
        api_key = kwargs.pop("api_key", None) or os.getenv("DSV4FLASH_API_KEY", "")
        base_url = kwargs.pop("base_url", None) or os.getenv(
            "DSV4FLASH_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v1"
        )
        model = kwargs.pop("model", None) or os.getenv("DSV4FLASH_MODEL", "deepseek-v4-flash")
        if not api_key:
            return _UnavailableLLMClient(provider="dsv4flash", model=model, base_url=base_url)
        client = DeepSeekClient(
            api_key=api_key,
            base_url=base_url,
            model=model,
            **kwargs,
        )
        client.provider = "dsv4flash"
        return client
    elif provider == "ark":
        # Generic Ark API (火山引擎) — supports any model deployed on Ark
        # Uses DSV4FLASH_API_KEY + DSV4FLASH_BASE_URL as defaults
        api_key = kwargs.pop("api_key", None) or os.getenv("DSV4FLASH_API_KEY", "") or os.getenv("ARK_API_KEY", "")
        base_url = (
            kwargs.pop("base_url", None)
            or os.getenv("DSV4FLASH_BASE_URL", "")
            or os.getenv("ARK_BASE_URL", "")
            or _DEFAULT_ARK_BASE_URL
        )
        model = kwargs.pop("model", None) or os.getenv("ANTHROPIC_MODEL", "deepseek-v4-pro")
        if not api_key:
            return _UnavailableLLMClient(provider="ark", model=model, base_url=base_url)
        client = DeepSeekClient(
            api_key=api_key,
            base_url=base_url,
            model=model,
            **kwargs,
        )
        client.provider = "ark"
        return client
    elif provider in {"mimo", "local_mimo"}:
        base_url = kwargs.pop("base_url", None) or os.getenv("MIMO_BASE_URL", "")
        model = kwargs.pop("model", None) or os.getenv("MIMO_MODEL", "mimo-local")
        api_key = kwargs.pop("api_key", None) or os.getenv("MIMO_API_KEY", "local")
        if not base_url:
            return _UnavailableLLMClient(provider="mimo", model=model, base_url="")
        client = DeepSeekClient(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            model=model,
            **kwargs,
        )
        client.provider = "mimo"
        return client
    elif provider in {"weapi", "weapi_pw"}:
        api_key = kwargs.pop("api_key", None) or os.getenv("WEAPI_API_KEY", "")
        raw_base_url = kwargs.pop("base_url", None) or os.getenv("WEAPI_BASE_URL", _DEFAULT_WEAPI_BASE_URL)
        base_url = _normalize_openai_compatible_base_url(str(raw_base_url))
        model = kwargs.pop("model", None) or os.getenv("WEAPI_MODEL", "gpt-5.5")
        if not api_key:
            return _UnavailableLLMClient(provider="weapi", model=model, base_url=base_url)
        client = DeepSeekClient(
            api_key=api_key,
            base_url=base_url,
            model=model,
            **kwargs,
        )
        client.provider = "weapi"
        return client
    else:
        raise ValueError(
            f"Unknown LLM provider: {provider}. Supported: doubao, deepseek, dsv4flash, ark, mimo, weapi, fake"
        )


def _normalize_openai_compatible_base_url(base_url: str) -> str:
    stripped = base_url.rstrip("/")
    if stripped.endswith("/v1"):
        return stripped
    return f"{stripped}/v1"
