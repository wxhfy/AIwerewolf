from __future__ import annotations

import os  # noqa: F401 — used extensively in create_client()
from typing import Any

from backend.llm.anthropic_client import AnthropicClient
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
_DEFAULT_DEEPSEEK_ANTHROPIC_BASE_URL = "https://api.deepseek.com/anthropic"
_DEFAULT_DEEPSEEK_ANTHROPIC_MODEL = "deepseek-v4-flash"
_DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
_DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"

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


def create_client(provider: str | None = None, **kwargs) -> Any:
    """Create an LLM client based on LLM_PROVIDER env or explicit provider.

    Supports:
    - doubao: 方舟 doubao-seed 2.0 pro & code (primary)
    - deepseek: DeepSeek v4 Flash (fallback)
    - mimo: local OpenAI-compatible endpoint configured by MIMO_BASE_URL
    - weapi: OpenAI-compatible endpoint at https://weapi.pw/v1
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
            elif "anthropic" in base_url:
                provider = "anthropic"
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
        if os.getenv("_TEST_ALLOW_FAKE_LLM") != "true":
            raise RuntimeError(
                "LLM_PROVIDER=fake is not available in production. "
                "Use real API credentials (DOUBAO_API_KEY / DEEPSEEK_API_KEY) for games. "
                "For tests, set _TEST_ALLOW_FAKE_LLM=true."
            )
        from tests.fake_llm import FakeLLMClient  # pragma: no cover — test-only path

        model = kwargs.pop("model", None) or "fake-llm"
        return FakeLLMClient(model=str(model))
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
    elif provider == "anthropic":
        # Anthropic-format API (Messages endpoint). The product settings default
        # to DeepSeek's Anthropic-compatible endpoint, while still accepting the
        # official Anthropic SDK env var for Claude endpoints.
        explicit_api_key = kwargs.pop("api_key", None)
        if explicit_api_key:
            api_key = str(explicit_api_key).strip()
            key_source = "explicit"
        elif os.getenv("ANTHROPIC_AUTH_TOKEN", "").strip():
            api_key = os.getenv("ANTHROPIC_AUTH_TOKEN", "").strip()
            key_source = "ANTHROPIC_AUTH_TOKEN"
        elif os.getenv("ANTHROPIC_API_KEY", "").strip():
            api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
            key_source = "ANTHROPIC_API_KEY"
        else:
            api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
            key_source = "DEEPSEEK_API_KEY" if api_key else ""

        explicit_base_url = kwargs.pop("base_url", None)
        if explicit_base_url:
            base_url = str(explicit_base_url).strip()
        else:
            base_url = (
                os.getenv("ANTHROPIC_BASE_URL", "").strip()
                or os.getenv("DEEPSEEK_ANTHROPIC_BASE_URL", "").strip()
                or (
                    _DEFAULT_ANTHROPIC_BASE_URL
                    if key_source == "ANTHROPIC_API_KEY"
                    else _DEFAULT_DEEPSEEK_ANTHROPIC_BASE_URL
                )
            )

        deepseek_compatible_endpoint = "deepseek" in base_url.lower()
        deepseek_compatible_auth = key_source in {"ANTHROPIC_AUTH_TOKEN", "DEEPSEEK_API_KEY", ""}
        use_deepseek_defaults = deepseek_compatible_endpoint or deepseek_compatible_auth

        explicit_model = kwargs.pop("model", None)
        if explicit_model:
            model = str(explicit_model).strip()
        else:
            model = (
                os.getenv("ANTHROPIC_MODEL", "").strip()
                or (os.getenv("DEEPSEEK_MODEL", "").strip() if use_deepseek_defaults else "")
                or (_DEFAULT_ANTHROPIC_MODEL if not use_deepseek_defaults else _DEFAULT_DEEPSEEK_ANTHROPIC_MODEL)
            )
        if not api_key:
            return _UnavailableLLMClient(provider="anthropic", model=model, base_url=base_url)
        client = AnthropicClient(
            api_key=api_key,
            base_url=base_url,
            model=model,
            **kwargs,
        )
        client.provider = "anthropic"
        return client
    else:
        raise ValueError(
            f"Unknown LLM provider: {provider}. Supported: doubao, deepseek, dsv4flash, ark, mimo, weapi, anthropic"
        )


def _normalize_openai_compatible_base_url(base_url: str) -> str:
    stripped = base_url.rstrip("/")
    if stripped.endswith("/v1"):
        return stripped
    return f"{stripped}/v1"
