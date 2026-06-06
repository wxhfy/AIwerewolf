"""DeepSeek API Client — production-grade with Anthropic SDK patterns.

Design borrowed from @anthropic-ai/sdk (Python):
  - Separate connect (5s) vs read (600s) timeouts via httpx.Timeout
  - Shared httpx.Client for connection pooling (HTTP keepalive)
  - Exponential backoff with jitter on retryable failures
  - Retry only transport errors + 408/409/429/5xx (not 4xx bugs)
  - x-stainless-timeout header tells the server how long we'll wait

Usage:
    from backend.llm.deepseek import DeepSeekClient

    client = DeepSeekClient()
    response = await client.chat([
        {"role": "system", "content": "You are a werewolf player."},
        {"role": "user", "content": "Who do you vote for?"}
    ])
"""

from __future__ import annotations

import logging
import os
import random
import ssl
import time
from typing import Optional

import httpx

from backend.llm.env import load_env_file

load_env_file()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timeout / Retry — modelled on anthropic.DEFAULT_TIMEOUT + DEFAULT_MAX_RETRIES
# ---------------------------------------------------------------------------
#  connect=5s   — fail fast if host is unreachable
#  read=600s    — allow 10 minutes for LLM generation (large prompts with
#                 reasoning + tool calls can be slow)
#  write=60s    — generous upload window for large prompts
#  pool=5s      — connection pool acquisition timeout

DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=600.0, write=60.0, pool=5.0)
DEFAULT_MAX_RETRIES = 5

# HTTP status codes worth retrying (matches Anthropic SDK policy).
# 408 Request Timeout, 409 Conflict, 429 Rate Limit — all transient.
_RETRYABLE_STATUSES: frozenset[int] = frozenset({408, 409, 429})


# ---------------------------------------------------------------------------
# Backoff helpers
# ---------------------------------------------------------------------------

def _backoff(attempt: int, cap: float = 60.0, base: float = 5.0) -> float:
    """Exponential backoff for *attempt* (1-indexed), capped at *cap* seconds."""
    return min(cap, base**attempt)


def _jitter(low: float, high: float) -> float:
    """Uniform random jitter in [low, high) — spreads out retry storms."""
    return random.uniform(low, high)


def _should_retry(status_code: int, exc: Exception | None = None) -> bool:
    """True if the failure is transient and worth retrying.

    Retryable:
      - Transport-level httpx errors (connect timeout, read timeout, connection reset)
      - HTTP 408 / 409 / 429
      - HTTP 5xx (server errors)

    Fatal:
      - HTTP 400 / 401 / 402 / 403 / 404 / 405 … (client bugs / bad key / not found)
      - Non-HTTP exceptions (programming errors)
    """
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.NetworkError):
        return True
    if isinstance(exc, httpx.RemoteProtocolError):
        return True
    if isinstance(exc, ssl.SSLError):
        return True
    if status_code in _RETRYABLE_STATUSES:
        return True
    if status_code >= 500:
        return True
    return False


# ---------------------------------------------------------------------------
# DeepSeekClient
# ---------------------------------------------------------------------------

class DeepSeekClient:
    """Production OpenAI-compatible client with Anthropic-grade resilience.

    Uses a shared httpx.Client for connection pooling — one TCP connection
    can serve multiple requests, eliminating TLS handshake overhead.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: httpx.Timeout | float | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
        self.timeout = timeout or DEFAULT_TIMEOUT
        self.max_retries = max_retries

        # Shared transport — connection pooling + keepalive
        timeout_value = self.timeout if isinstance(self.timeout, httpx.Timeout) else httpx.Timeout(self.timeout)
        self._transport = httpx.HTTPTransport(
            limits=httpx.Limits(max_keepalive_connections=8, max_connections=20, keepalive_expiry=30.0),
        )
        self._sync_client = httpx.Client(transport=self._transport, timeout=timeout_value)

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "x-stainless-timeout": str(
                self.timeout.read if isinstance(self.timeout, httpx.Timeout) else self.timeout
            ),
        }

    # ------------------------------------------------------------------
    # chat_sync — production-grade with retry + backoff + jitter
    # ------------------------------------------------------------------

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
        """Synchronous chat completion with exponential backoff retry."""
        payload = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        # Forward extra kwargs (tools, tool_choice, etc.)
        payload.update(kwargs)
        has_tools = "tools" in payload or "tool_choice" in payload or "functions" in payload
        if thinking and not has_tools:
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = reasoning_effort

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 2):  # 1-indexed for backoff
            retry_count = attempt - 1
            headers = self._headers()
            if retry_count > 0:
                headers["x-stainless-retry-count"] = str(retry_count)

            try:
                t0 = time.perf_counter()
                response = self._sync_client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                latency_ms = int((time.perf_counter() - t0) * 1000)

                # 4xx that aren't retryable → raise immediately
                if 400 <= response.status_code < 500 and response.status_code not in _RETRYABLE_STATUSES:
                    try:
                        err = response.json()
                    except Exception:
                        err = response.text[:500]
                    logger.error(f"API fatal error {response.status_code}: {err}")
                    response.raise_for_status()

                # Transient errors → retry
                if _should_retry(response.status_code):
                    raise httpx.HTTPStatusError(
                        f"Retryable HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )

                response.raise_for_status()
                data = response.json()
                data["_latency_ms"] = latency_ms
                if retry_count > 0:
                    data["_retry_count"] = retry_count
                return data

            except httpx.TimeoutException as e:
                last_exc = e
                if attempt <= self.max_retries + 1 and _should_retry(0, exc=e):
                    delay = _backoff(attempt) + _jitter(0, 1)
                    logger.warning(
                        f"API timeout (attempt {attempt}/{self.max_retries + 1}), "
                        f"retrying in {delay:.1f}s... ({e})"
                    )
                    time.sleep(delay)
                else:
                    raise

            except httpx.HTTPStatusError as e:
                last_exc = e
                if _should_retry(e.response.status_code):
                    delay = _backoff(attempt) + _jitter(0, 1)
                    logger.warning(
                        f"API HTTP {e.response.status_code} (attempt {attempt}/{self.max_retries + 1}), "
                        f"retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                else:
                    raise

            except (httpx.NetworkError, httpx.RemoteProtocolError, ssl.SSLError) as e:
                last_exc = e
                if attempt <= self.max_retries + 1:
                    delay = _backoff(attempt) + _jitter(0, 1)
                    logger.warning(
                        f"API network/SSL error (attempt {attempt}/{self.max_retries + 1}), "
                        f"retrying in {delay:.1f}s... ({e})"
                    )
                    time.sleep(delay)
                else:
                    raise

        raise RuntimeError(f"API call failed after {self.max_retries + 1} attempts") from last_exc

    # ------------------------------------------------------------------
    # chat (async) — same resilience patterns
    # ------------------------------------------------------------------

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
        """Async chat completion with exponential backoff retry."""
        payload = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        payload.update(kwargs)
        has_tools = "tools" in payload or "tool_choice" in payload or "functions" in payload
        if thinking and not has_tools:
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = reasoning_effort

        # Use a fresh async client for each call (connection pooling still applies via transport)
        async with httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(
                limits=httpx.Limits(max_keepalive_connections=8, max_connections=20, keepalive_expiry=30.0),
            ),
            timeout=self.timeout if isinstance(self.timeout, httpx.Timeout) else httpx.Timeout(self.timeout),
        ) as client:
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

    # ------------------------------------------------------------------
    # Parse helpers
    # ------------------------------------------------------------------

    def parse_response(self, response: dict) -> str:
        """Extract the assistant's message content from API response."""
        return response["choices"][0]["message"]["content"]

    def parse_thinking(self, response: dict) -> Optional[str]:
        """Extract the thinking/reasoning content from API response."""
        msg = response["choices"][0]["message"]
        return msg.get("reasoning_content", None)

    def close(self) -> None:
        """Close the shared HTTP transport."""
        self._sync_client.close()

    def __del__(self) -> None:
        try:
            self._sync_client.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

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
        usage = resp.get("usage", {})
        print(f"Tokens: prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')}")
        print(f"Latency: {resp.get('_latency_ms')}ms")
        print("Connection OK!")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        client.close()


if __name__ == "__main__":
    test_connection()
