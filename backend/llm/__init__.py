from __future__ import annotations

from backend.llm.deepseek import DeepSeekClient
from backend.llm.env import load_env_file

__all__ = ["DeepSeekClient", "create_client", "load_env_file"]


_DEFAULT_DOUBAO_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
_DEFAULT_DOUBAO_MODEL = "Doubao-Seed-2.0-pro"
_DEFAULT_PROVIDER = "doubao"


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
            provider = os.getenv("LLM_PROVIDER", _DEFAULT_PROVIDER)

    if provider == "doubao":
        api_key = kwargs.pop("api_key", None) or os.getenv("DOUBAO_API_KEY", "")
        base_url = kwargs.pop("base_url", None) or os.getenv("DOUBAO_BASE_URL", _DEFAULT_DOUBAO_BASE_URL)
        model = (
            kwargs.pop("model", None)
            or os.getenv("DOUBAO_ENDPOINT", "")
            or os.getenv("DOUBAO_MODEL", _DEFAULT_DOUBAO_MODEL)
        )
        if not api_key:
            raise ValueError("DOUBAO_API_KEY not set in env and not provided as argument")
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
