from __future__ import annotations

import json
import re
from typing import Any

from backend.llm.deepseek import DeepSeekClient
from backend.llm.env import load_env_file

__all__ = ["DeepSeekClient", "create_client", "load_env_file"]


_DEFAULT_DOUBAO_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
_DEFAULT_DOUBAO_MODEL = "ep-20260514115354-k4jz4"
_DEFAULT_ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding/v1"
_DEFAULT_PROVIDER = "dsv4flash"

# Multi-model pool: "provider:model" entries, comma-separated
# Supports: doubao, dsv4flash, ark (generic Ark API), deepseek
# Examples:
#   DOUBAO_MODEL_POOL="deepseek-v4-pro[1m],kimi-k2.6[1m],glm-5.1[1m]"
#   MODEL_POOL="ark:deepseek-v4-pro[1m],ark:kimi-k2.6[1m],doubao:ep-xxx,deepseek:deepseek-v4-flash"


class _UnavailableLLMClient:
    """Unavailable client marker used to fail fast in LLM-only game mode."""

    def __init__(self, provider: str, model: str, base_url: str):
        self.provider = provider
        self.model = model
        self.base_url = base_url
        self.timeout = 300.0  # 5分钟超时
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
        self.timeout = 300.0
        self.available = True
        self.call_count = 0

    def chat_sync(self, messages: list[dict], **kwargs: Any) -> dict[str, Any]:
        self.call_count += 1
        text = "\n".join(str(message.get("content", "")) for message in messages)
        target = self._target_from_prompt(text)
        if "输出 JSON" in text:
            content = json.dumps(
                {"target": target, "reasoning": "fake LLM direct-call decision"},
                ensure_ascii=False,
            )
        elif "【任务：发言】" in text:
            content = "DECISION: " + json.dumps(
                {
                    "speech": f"我先按公开信息发言，重点观察 {target} 的站边和票型。",
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
    def _target_from_prompt(text: str) -> str:
        self_match = re.search(r"你是\s+@?\d+号[:：]([^，,\n]+)", text)
        self_name = self_match.group(1).strip() if self_match else ""
        names = [name.strip() for name in re.findall(r"@?\d+号[:：]([^，,\n]+)", text)]
        for name in names:
            if name and name != self_name:
                return name
        return names[0] if names else "1号"


def create_client(provider: str | None = None, **kwargs) -> Any:
    """Create an LLM client based on LLM_PROVIDER env or explicit provider.

    Supports:
    - doubao: 方舟 doubao-seed 2.0 pro & code (primary)
    - deepseek: DeepSeek v4 Flash (fallback)
    - fake: deterministic local LLM-compatible client for tests
    """
    import os

    load_env_file()
    explicit_model = kwargs.get("model")
    explicit_base_url = kwargs.get("base_url")
    if provider is None:
        if explicit_base_url:
            base_url = str(explicit_base_url).lower()
            if "deepseek" in base_url:
                provider = "deepseek"
            elif "ark." in base_url or "volces" in base_url:
                provider = "doubao"
        if provider is None and explicit_model:
            model_name = str(explicit_model).lower()
            if "deepseek" in model_name:
                provider = "deepseek"
            elif "doubao" in model_name:
                provider = "doubao"
        if provider is None:
            provider = os.getenv("LLM_PROVIDER", _DEFAULT_PROVIDER)

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
        base_url = kwargs.pop("base_url", None) or os.getenv("DSV4FLASH_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding/v1")
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
        api_key = (
            kwargs.pop("api_key", None)
            or os.getenv("DSV4FLASH_API_KEY", "")
            or os.getenv("ARK_API_KEY", "")
        )
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
    else:
        raise ValueError(
            f"Unknown LLM provider: {provider}. "
            f"Supported: doubao, deepseek, dsv4flash, ark, fake"
        )
