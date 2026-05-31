from __future__ import annotations

import os
import time
from typing import Optional

import httpx

from backend.llm.env import load_env_file

load_env_file()


class AnthropicClient:
    """Thin client for Anthropic Messages API (used by Volces Ark /api/coding endpoint).

    Exposes the same interface as DeepSeekClient (chat_sync, parse_response,
    parse_thinking) so it's a drop-in replacement for the LLM agent.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 120.0,
    ):
        self.api_key = api_key or os.getenv("DSV4FLASH_API_KEY", "")
        self.base_url = base_url or os.getenv("DSV4FLASH_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding")
        self.model = model or os.getenv("DSV4FLASH_MODEL", "deepseek-v4-flash")
        self.timeout = timeout

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

    def _build_payload(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        thinking: bool = True,
    ) -> dict:
        # Anthropic API separates system message from the messages array
        system_prompt = ""
        chat_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_prompt = str(msg.get("content", ""))
            else:
                chat_messages.append({"role": msg["role"], "content": msg.get("content", "")})

        payload: dict = {
            "model": model or self.model,
            "messages": chat_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            payload["system"] = system_prompt

        if thinking:
            payload["thinking"] = {"type": "enabled", "budget_tokens": min(max_tokens // 2, 1024)}

        return payload

    async def chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        thinking: bool = True,
        reasoning_effort: str = "medium",
        stream: bool = False,
    ) -> dict:
        payload = self._build_payload(messages, model, temperature, max_tokens, thinking)
        payload["stream"] = stream

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            t0 = time.perf_counter()
            response = await client.post(
                f"{self.base_url}/v1/messages",
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
    ) -> dict:
        payload = self._build_payload(messages, model, temperature, max_tokens, thinking)

        with httpx.Client(timeout=self.timeout) as client:
            t0 = time.perf_counter()
            response = client.post(
                f"{self.base_url}/v1/messages",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            data["_latency_ms"] = int((time.perf_counter() - t0) * 1000)
            return data

    def parse_response(self, response: dict) -> str:
        """Extract text content from Anthropic Messages API response."""
        for block in response.get("content", []):
            if block.get("type") == "text":
                return block.get("text", "")
        return ""

    def parse_thinking(self, response: dict) -> Optional[str]:
        """Extract thinking/reasoning content from the response."""
        for block in response.get("content", []):
            if block.get("type") == "thinking":
                return block.get("thinking", "")
        return None
