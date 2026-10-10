from __future__ import annotations

from typing import Any
from typing import Protocol


class ModelClient(Protocol):
    """Provider-neutral completion contract consumed by the harness."""

    provider: str
    model: str
    supports_tool_calling: bool

    def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]: ...


def complete_chat(client: Any, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
    """Call the canonical client API while keeping legacy clients compatible."""
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


def supports_tool_calling(client: Any) -> bool:
    """Capability declaration; model names are never used as a capability oracle."""
    return bool(getattr(client, "supports_tool_calling", False))
