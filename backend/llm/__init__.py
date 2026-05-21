from __future__ import annotations

from backend.llm.deepseek import DeepSeekClient
from backend.llm.env import load_env_file

__all__ = ["DeepSeekClient", "create_client", "load_env_file"]


HARDCODED_DOUBAO_API_KEY = "ark-4126af52-1fda-4c17-8561-8db89e066502-95563"
HARDCODED_DOUBAO_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
HARDCODED_DOUBAO_ENDPOINT = "ep-20260514115354-k4jz4"
HARDCODED_DOUBAO_MODEL = "Doubao-Seed-2.0-pro"
HARDCODED_LLM_PROVIDER = "doubao"


def create_client(provider: str | None = None, **kwargs) -> DeepSeekClient:
    """Create an LLM client based on LLM_PROVIDER env or explicit provider.

    Supports:
    - doubao: 方舟 doubao-seed 2.0 pro & code (primary)
    - deepseek: DeepSeek v4 Flash (fallback)
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
            provider = os.getenv("LLM_PROVIDER", HARDCODED_LLM_PROVIDER)

    if provider == "doubao":
        api_key = kwargs.pop("api_key", None) or os.getenv("DOUBAO_API_KEY") or HARDCODED_DOUBAO_API_KEY
        base_url = kwargs.pop("base_url", None) or os.getenv("DOUBAO_BASE_URL") or HARDCODED_DOUBAO_BASE_URL
        model = (
            kwargs.pop("model", None)
            or os.getenv("DOUBAO_ENDPOINT")
            or HARDCODED_DOUBAO_ENDPOINT
            or os.getenv("DOUBAO_MODEL")
            or HARDCODED_DOUBAO_MODEL
        )
        return DeepSeekClient(
            api_key=api_key,
            base_url=base_url,
            model=model,
            **kwargs,
        )
    elif provider == "deepseek":
        api_key = kwargs.pop("api_key", None) or os.getenv("DEEPSEEK_API_KEY", "")
        base_url = kwargs.pop("base_url", None) or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        model = kwargs.pop("model", None) or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
        return DeepSeekClient(
            api_key=api_key,
            base_url=base_url,
            model=model,
            **kwargs,
        )
    else:
        raise ValueError(f"Unknown LLM provider: {provider}. Supported: doubao, deepseek")
