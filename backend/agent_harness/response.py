from __future__ import annotations

import json
from typing import Any


class ModelResponseError(RuntimeError):
    """Raised when a provider response cannot be normalized."""


def assistant_message(response: dict[str, Any]) -> dict[str, Any]:
    try:
        message = response["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelResponseError("Model response does not contain an assistant message") from exc
    if not isinstance(message, dict):
        raise ModelResponseError("Model assistant message must be an object")
    return message


def content_text(response: dict[str, Any]) -> str:
    message = assistant_message(response)
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    chunks.append(text)
        return "".join(chunks)
    if content is None:
        return ""
    return str(content)


def tool_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
    calls = assistant_message(response).get("tool_calls") or []
    if not isinstance(calls, list):
        raise ModelResponseError("Model tool_calls must be an array")
    return [call for call in calls if isinstance(call, dict)]


def tool_name(call: dict[str, Any]) -> str:
    function = call.get("function") or {}
    return str(function.get("name") or "") if isinstance(function, dict) else ""


def tool_arguments(call: dict[str, Any]) -> str:
    function = call.get("function") or {}
    if not isinstance(function, dict):
        return "{}"
    arguments = function.get("arguments") or {}
    if isinstance(arguments, str):
        return arguments
    try:
        return json.dumps(arguments, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ModelResponseError("Model tool arguments are not JSON serializable") from exc
