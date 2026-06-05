from __future__ import annotations

"""
DeepSeek API Client

Usage:
    from backend.llm.deepseek import DeepSeekClient

    client = DeepSeekClient()
    response = await client.chat([
        {"role": "system", "content": "You are a werewolf player."},
        {"role": "user", "content": "Who do you vote for?"}
    ])
"""

import os
import time
from typing import Optional

import httpx

from backend.llm.env import load_env_file

load_env_file()


class DeepSeekClient:
    """Async client for DeepSeek Chat Completions API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 300.0,
    ):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
        self.timeout = timeout

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    async def chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        thinking: bool = True,
        reasoning_effort: str = "medium",
        stream: bool = False,
        **kwargs,
    ) -> dict:
        """Send a chat completion request. Extra kwargs pass through to API payload."""
        payload = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        # Forward extra kwargs to API (tools, tool_choice, etc.)
        payload.update(kwargs)
        # Disable thinking when tools are present — some endpoints don't support both
        has_tools = "tools" in payload or "tool_choice" in payload or "functions" in payload
        if thinking and not has_tools:
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = reasoning_effort

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            t0 = time.perf_counter()
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            data["_latency_ms"] = int((time.perf_counter() - t0) * 1000)
            return data

    def chat_sync(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        thinking: bool = True,
        reasoning_effort: str = "medium",
        **kwargs,
    ) -> dict:
        """Synchronous version of chat(). Extra kwargs pass through to API payload."""
        payload = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        # Forward extra kwargs to API (tools, tool_choice, etc.)
        payload.update(kwargs)
        # Disable thinking when tools are present — some endpoints don't support both
        has_tools = "tools" in payload or "tool_choice" in payload or "functions" in payload
        if thinking and not has_tools:
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = reasoning_effort

        with httpx.Client(timeout=self.timeout) as client:
            t0 = time.perf_counter()
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            if response.status_code >= 400:
                # Log error details for debugging
                import logging

                _log = logging.getLogger(__name__)
                try:
                    err = response.json()
                    _log.error(f"API error {response.status_code}: {err}")
                except Exception:
                    _log.error(f"API error {response.status_code}: {response.text[:500]}")
            response.raise_for_status()
            data = response.json()
            data["_latency_ms"] = int((time.perf_counter() - t0) * 1000)
            return data

    def parse_response(self, response: dict) -> str:
        """Extract the assistant's message content from API response."""
        return response["choices"][0]["message"]["content"]

    def parse_thinking(self, response: dict) -> Optional[str]:
        """Extract the thinking/reasoning content from API response."""
        msg = response["choices"][0]["message"]
        return msg.get("reasoning_content", None)


# Quick test function
def test_connection():
    """Test DeepSeek API connection. Run via: python -m backend.llm.deepseek"""
    client = DeepSeekClient()
    print(f"Connecting to {client.base_url} with model {client.model}...")
    try:
        resp = client.chat_sync(
            messages=[{"role": "user", "content": "Hello! 1+1=?"}],
            max_tokens=100,
        )
        print(f"Response: {client.parse_response(resp)}")
        print("Connection OK!")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    test_connection()
