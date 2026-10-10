from __future__ import annotations

from typing import Any
from typing import Protocol


class ModelCallError(RuntimeError):
    """Provider-neutral model failure with a stable operational category."""

    def __init__(self, category: str, message: str, *, cause_type: str = "") -> None:
        super().__init__(message)
        self.category = category
        self.cause_type = cause_type or category


class ModelClient(Protocol):
    """Provider-neutral completion contract consumed by the harness."""

    provider: str
    model: str
    supports_tool_calling: bool

    def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]: ...


def complete_chat(client: Any, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
    """Call the canonical client API while keeping legacy clients compatible."""
    try:
        complete = getattr(client, "complete", None)
        if callable(complete):
            response = complete(messages, **kwargs)
        else:
            legacy = getattr(client, "chat_sync", None)
            if not callable(legacy):
                raise TypeError("Model client must implement complete() or chat_sync()")
            response = legacy(messages, **kwargs)
        if not isinstance(response, dict):
            raise TypeError("Model client response must be a mapping")
        return response
    except ModelCallError:
        raise
    except Exception as exc:
        raise ModelCallError(
            classify_model_error(exc),
            f"{type(exc).__name__}: {exc}",
            cause_type=type(exc).__name__,
        ) from exc


def classify_model_error(error: BaseException) -> str:
    """Map provider-specific exceptions to stable runtime categories."""
    name = type(error).__name__.lower()
    message = str(error).lower()
    if "timeout" in name or "timeout" in message:
        return "timeout"
    if any(token in name or token in message for token in ("ratelimit", "rate_limit", "429", "throttl")):
        return "rate_limit"
    if any(token in name or token in message for token in ("auth", "permission", "401", "403")):
        return "authentication"
    if any(token in name or token in message for token in ("connection", "connect", "network", "dns")):
        return "transport"
    return "provider_error"


def supports_tool_calling(client: Any) -> bool:
    """Capability declaration; model names are never used as a capability oracle."""
    return bool(getattr(client, "supports_tool_calling", False))
