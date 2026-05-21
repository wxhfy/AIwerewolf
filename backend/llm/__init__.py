from __future__ import annotations

from backend.llm.deepseek import DeepSeekClient
from backend.llm.env import load_env_file

__all__ = ["DeepSeekClient", "create_client", "load_env_file"]


def create_client(provider: str | None = None, **kwargs) -> DeepSeekClient:
    """Create an LLM client based on LLM_PROVIDER env or explicit provider.

    Supports:
    - doubao: 方舟 doubao-seed 2.0 pro & code (primary)
    - deepseek: DeepSeek v4 Flash (fallback)
    """
    import os

    load_env_file()
    provider = provider or os.getenv("LLM_PROVIDER", "doubao")

    if provider == "doubao":
        return DeepSeekClient(
            api_key=kwargs.pop("api_key", os.getenv("DOUBAO_API_KEY", "")),
            base_url=kwargs.pop("base_url", os.getenv("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")),
            model=kwargs.pop("model", os.getenv("DOUBAO_MODEL", "doubao-seed-2.0-pro")),
            **kwargs,
        )
    elif provider == "deepseek":
        return DeepSeekClient(
            api_key=kwargs.pop("api_key", os.getenv("DEEPSEEK_API_KEY", "")),
            base_url=kwargs.pop("base_url", os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")),
            model=kwargs.pop("model", os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")),
            **kwargs,
        )
    else:
        raise ValueError(f"Unknown LLM provider: {provider}. Supported: doubao, deepseek")
