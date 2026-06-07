"""Anthropic-format API Client — for ARK coding endpoint and Anthropic-compatible APIs.

Translates Anthropic Messages API format ↔ OpenAI-compatible format so
the rest of the codebase (LangChainLLM wrapper, AgentLoop) can use
Anthropic-format endpoints without changes.

Usage:
    from backend.llm.anthropic_client import AnthropicClient

    client = AnthropicClient(
        api_key="ark-b2f9...",
        base_url="https://ark.cn-beijing.volces.com/api/coding/v1",
        model="deepseek-v4-pro[1m]",
    )
    response = client.chat_sync([
        {"role": "system", "content": "You are a werewolf player."},
        {"role": "user", "content": "Who do you vote for?"}
    ])
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
import threading
from typing import Any

import httpx

from backend.llm.env import load_env_file

load_env_file()

logger = logging.getLogger(__name__)

# Global token counter (for benchmarking)
_GLOBAL_TOKEN_COUNTER = {"calls": 0, "input": 0, "output": 0}


def reset_global_token_counter():
    _GLOBAL_TOKEN_COUNTER.update({"calls": 0, "input": 0, "output": 0})


def get_global_token_counter() -> dict:
    return dict(_GLOBAL_TOKEN_COUNTER)


DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=120.0, write=30.0, pool=5.0)
DEFAULT_MAX_RETRIES = 1
_RETRYABLE_STATUSES: frozenset[int] = frozenset({408, 409, 429})


def _backoff(attempt: int, cap: float = 8.0, base: float = 1.0) -> float:
    return min(cap, base * (2 ** max(attempt - 1, 0)))


def _jitter(low: float, high: float) -> float:
    return random.uniform(low, high)


class AnthropicClient:
    """Anthropic Messages API client that returns OpenAI-compatible responses.

    Translates between Anthropic request/response format and OpenAI-compatible
    format so LangChainLLM / AgentLoop can use Anthropic endpoints unchanged.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        model: str = "claude-sonnet-4-6",
        max_retries: int | None = None,
        timeout: httpx.Timeout | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.provider = "anthropic"
        self.available = True
        self.call_count = 0
        self._max_retries = max_retries if max_retries is not None else DEFAULT_MAX_RETRIES
        self._timeout = timeout or DEFAULT_TIMEOUT
        self._client: httpx.Client | None = None
        self._client_lock = threading.Lock()

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    self._client = httpx.Client(
                        timeout=self._timeout,
                        limits=httpx.Limits(max_keepalive_connections=5, max_connections=20),
                    )
        return self._client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat_sync(self, messages: list[dict], **kwargs: Any) -> dict[str, Any]:
        """Send request in Anthropic format, return OpenAI-compatible response."""
        self.call_count += 1
        system_prompt, user_messages = self._split_system(messages)

        max_tokens = kwargs.get("max_tokens", 4096)
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": user_messages,
        }
        if system_prompt:
            body["system"] = system_prompt
        if kwargs.get("temperature") is not None:
            body["temperature"] = kwargs["temperature"]

        tools = kwargs.get("tools")
        thinking_disabled = kwargs.get("thinking") is False or kwargs.get("thinking") == "disabled"
        if tools:
            body["tools"] = self._tools_to_anthropic(tools)
            tc = kwargs.get("tool_choice")
            if tc:
                body["tool_choice"] = self._tool_choice_to_anthropic(tc)
            # Thinking mode does not support forced tool_choice — disable it
            body["thinking"] = {"type": "disabled"}
        elif thinking_disabled:
            body["thinking"] = {"type": "disabled"}
        else:
            # DeepSeek V4 Pro has internal reasoning (thinking) — give it budget
            # separate from the visible output so it doesn't starve the response.
            thinking_budget = min(max_tokens // 2, 2048)
            body["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        data = self._request_with_retry("POST", "/v1/messages", headers, body)
        result = self._response_to_openai(data)

        # Update global counter
        usage = data.get("usage", {})
        _GLOBAL_TOKEN_COUNTER["calls"] += 1
        _GLOBAL_TOKEN_COUNTER["input"] += usage.get("input_tokens", 0)
        _GLOBAL_TOKEN_COUNTER["output"] += usage.get("output_tokens", 0)

        return result

    async def chat(self, messages: list[dict], **kwargs: Any) -> dict[str, Any]:
        return self.chat_sync(messages, **kwargs)

    # ------------------------------------------------------------------
    # Retry logic
    # ------------------------------------------------------------------

    def _request_with_retry(self, method: str, path: str, headers: dict, body: dict) -> dict:
        url = f"{self.base_url}{path}"
        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 2):
            try:
                client = self._get_client()
                resp = client.request(method, url, headers=headers, json=body)
                if resp.status_code < 400:
                    return resp.json()
                if resp.status_code in _RETRYABLE_STATUSES:
                    raise httpx.HTTPStatusError(
                        f"Retryable HTTP {resp.status_code}",
                        request=resp.request, response=resp,
                    )
                self._raise_api_error(resp)
            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                if attempt <= self._max_retries:
                    wait = _backoff(attempt) + _jitter(0, 0.5)
                    time.sleep(wait)
                    continue
                raise
            except httpx.HTTPStatusError as exc:
                if attempt <= self._max_retries and exc.response.status_code in _RETRYABLE_STATUSES:
                    last_exc = exc
                    wait = _backoff(attempt) + _jitter(0, 0.5)
                    time.sleep(wait)
                    continue
                raise
        raise last_exc or RuntimeError("AnthropicClient retry exhaustion")

    def _raise_api_error(self, response: httpx.Response) -> None:
        try:
            body = response.json()
        except Exception:
            body = {}
        msg = body.get("error", {}).get("message", response.text)
        raise httpx.HTTPStatusError(
            f"API fatal error {response.status_code}: {msg}",
            request=response.request, response=response,
        )

    # ------------------------------------------------------------------
    # OpenAI → Anthropic format conversion (request)
    # ------------------------------------------------------------------

    @staticmethod
    def _split_system(messages: list[dict]) -> tuple[str, list[dict]]:
        """Extract system message(s) to Anthropic top-level system field.

        Also converts OpenAI-format tool/function messages to Anthropic format.
        Merges consecutive tool_result messages so that a single assistant
        message with N tool_use blocks is immediately followed by ONE user
        message with N tool_result blocks (Anthropic API requirement).
        """
        system_parts = []
        user_msgs = []
        pending_tool_results: list[dict] = []

        def _flush_tool_results():
            if pending_tool_results:
                user_msgs.append({
                    "role": "user",
                    "content": pending_tool_results.copy(),
                })
                pending_tool_results.clear()

        for msg in messages:
            role = str(msg.get("role", "")).lower()
            content = msg.get("content", "")
            if role == "system":
                system_parts.append(str(content))
            elif role == "tool":
                # Accumulate consecutive tool results — they will be flushed
                # together into one user message after the last tool message.
                tool_call_id = msg.get("tool_call_id", "")
                pending_tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": str(content),
                })
            elif role == "function":
                _flush_tool_results()
                name = msg.get("name", "")
                label = f"[function result: {name}] " if name else ""
                user_msgs.append({"role": "user", "content": label + str(content)})
            elif role == "assistant" and msg.get("tool_calls"):
                _flush_tool_results()
                content_blocks: list[dict] = []
                if content:
                    content_blocks.append({"type": "text", "text": str(content)})
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    args = fn.get("arguments", "{}")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except (json.JSONDecodeError, TypeError):
                            args = {}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", f"toolu_{len(content_blocks):04d}"),
                        "name": fn.get("name", ""),
                        "input": args if isinstance(args, dict) else {},
                    })
                user_msgs.append({"role": "assistant", "content": content_blocks})
            else:
                _flush_tool_results()
                user_msgs.append({"role": role, "content": str(content)})

        _flush_tool_results()
        return "\n\n".join(system_parts), user_msgs

    @staticmethod
    def _tools_to_anthropic(tools: list[dict]) -> list[dict]:
        result = []
        for tool in tools:
            fn = tool.get("function", tool)
            result.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {
                    "type": "object", "properties": {}, "required": []
                }),
            })
        return result

    @staticmethod
    def _tool_choice_to_anthropic(tool_choice: Any) -> dict:
        if isinstance(tool_choice, dict):
            fn = tool_choice.get("function", {})
            name = fn.get("name", "")
            if name:
                return {"type": "tool", "name": name}
        if tool_choice in ("any", "required"):
            return {"type": "any"}
        return {"type": "auto"}

    # ------------------------------------------------------------------
    # Anthropic → OpenAI format conversion (response)
    # ------------------------------------------------------------------

    @staticmethod
    def _response_to_openai(data: dict) -> dict[str, Any]:
        content_blocks = data.get("content", [])
        usage = data.get("usage", {})

        text_parts = []
        thinking_parts = []
        tool_calls = []
        for block in content_blocks:
            bt = block.get("type", "")
            if bt == "text":
                text_parts.append(block.get("text", ""))
            elif bt == "thinking":
                thinking_parts.append(block.get("thinking", ""))
            elif bt == "tool_use":
                tool_calls.append({
                    "id": block.get("id", f"toolu_{len(tool_calls):04d}"),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                    },
                })

        stop_reason = data.get("stop_reason", "end_turn")
        finish_map = {"tool_use": "tool_calls", "end_turn": "stop", "max_tokens": "length"}
        openai_finish = finish_map.get(stop_reason, "stop")

        message: dict[str, Any] = {
            "role": "assistant",
            "content": "\n".join(text_parts) if text_parts else None,
        }
        if tool_calls:
            message["tool_calls"] = tool_calls
            message["content"] = message.get("content") or ""

        return {
            "id": data.get("id", ""),
            "choices": [{
                "index": 0,
                "finish_reason": openai_finish,
                "message": message,
            }],
            "usage": {
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            },
            "_latency_ms": 0,
        }
