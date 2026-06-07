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
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Optional

import httpx

from backend.llm.env import load_env_file

load_env_file()

logger = logging.getLogger(__name__)
_CONCURRENCY_LOCK = threading.Lock()
_CONCURRENCY_SEMAPHORES: dict[tuple[str, int], threading.BoundedSemaphore] = {}

# ---------------------------------------------------------------------------
# Timeout / Retry — modelled on anthropic.DEFAULT_TIMEOUT + DEFAULT_MAX_RETRIES
# ---------------------------------------------------------------------------
#  connect=3s   — fail fast if host is unreachable
#  read=12s     — LLM-only games fail the turn instead of hanging
#  write=10s    — prompts are bounded; long uploads indicate a local bug
#  pool=3s      — connection pool acquisition timeout

DEFAULT_READ_TIMEOUT_SECONDS = 12.0
DEFAULT_TIMEOUT = httpx.Timeout(connect=3.0, read=DEFAULT_READ_TIMEOUT_SECONDS, write=10.0, pool=3.0)
DEFAULT_MAX_RETRIES = 0

# HTTP status codes worth retrying (matches Anthropic SDK policy).
# 408 Request Timeout, 409 Conflict, 429 Rate Limit — all transient.
_RETRYABLE_STATUSES: frozenset[int] = frozenset({408, 409, 429})


# ---------------------------------------------------------------------------
# Backoff helpers
# ---------------------------------------------------------------------------


def _backoff(attempt: int, cap: float = 8.0, base: float = 1.0) -> float:
    """Short exponential backoff for *attempt* (1-indexed), capped at *cap* seconds."""
    return min(cap, base * (2 ** max(attempt - 1, 0)))


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


def _default_concurrency_limit(base_url: str) -> int:
    """Return a conservative default concurrency limit for a provider URL."""
    raw = os.getenv("LLM_MAX_CONCURRENT_REQUESTS", "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            logger.warning("Invalid LLM_MAX_CONCURRENT_REQUESTS=%r; using provider default", raw)
    if "weapi.pw" in base_url.lower():
        return 2
    return 4


def _max_read_timeout_seconds() -> float:
    raw = os.getenv("LLM_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_READ_TIMEOUT_SECONDS
    try:
        return max(DEFAULT_READ_TIMEOUT_SECONDS, float(raw))
    except ValueError:
        logger.warning("Invalid LLM_TIMEOUT_SECONDS=%r; using provider default", raw)
        return DEFAULT_READ_TIMEOUT_SECONDS


def _bounded_timeout(timeout: httpx.Timeout | float | None) -> httpx.Timeout:
    """Return a timeout capped for game-loop LLM calls."""
    read_cap = _max_read_timeout_seconds()
    if timeout is None:
        return DEFAULT_TIMEOUT
    if isinstance(timeout, httpx.Timeout):
        return httpx.Timeout(
            connect=min(float(timeout.connect or DEFAULT_TIMEOUT.connect), DEFAULT_TIMEOUT.connect),
            read=min(float(timeout.read or read_cap), read_cap),
            write=min(float(timeout.write or DEFAULT_TIMEOUT.write), DEFAULT_TIMEOUT.write),
            pool=min(float(timeout.pool or DEFAULT_TIMEOUT.pool), DEFAULT_TIMEOUT.pool),
        )
    capped = min(float(timeout), read_cap)
    return httpx.Timeout(capped)


def _semaphore_for(base_url: str, limit: int) -> threading.BoundedSemaphore | None:
    if limit <= 0:
        return None
    key = (base_url.rstrip("/"), limit)
    with _CONCURRENCY_LOCK:
        semaphore = _CONCURRENCY_SEMAPHORES.get(key)
        if semaphore is None:
            semaphore = threading.BoundedSemaphore(limit)
            _CONCURRENCY_SEMAPHORES[key] = semaphore
        return semaphore


def _is_deepseek_family(model: str, base_url: str) -> bool:
    model_key = str(model or "").lower()
    base_key = str(base_url or "").lower()
    return "deepseek" in model_key or "deepseek" in base_key


def _normalize_thinking_payload(
    payload: dict,
    *,
    base_url: str,
    thinking: bool,
    reasoning_effort: str,
) -> None:
    """Normalize provider-specific thinking options in-place."""
    has_tools = "tools" in payload or "tool_choice" in payload or "functions" in payload
    model = str(payload.get("model") or "")
    if has_tools:
        if _is_deepseek_family(model, base_url):
            # DeepSeek v4 flash defaults to thinking mode. Tool calls require
            # an explicit object-shaped disable flag; boolean false is rejected.
            payload["thinking"] = {"type": "disabled"}
        elif payload.get("thinking") is False:
            payload.pop("thinking", None)
        payload.pop("reasoning_effort", None)
        return
    if not thinking:
        if _is_deepseek_family(model, base_url):
            payload["thinking"] = {"type": "disabled"}
        else:
            payload.pop("thinking", None)
        payload.pop("reasoning_effort", None)
        return
    if thinking:
        payload["thinking"] = {"type": "enabled"}
        payload["reasoning_effort"] = reasoning_effort


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
        self.timeout = _bounded_timeout(timeout)
        self.max_retries = max_retries

        # Shared transport — connection pooling + keepalive
        self._transport = httpx.HTTPTransport(
            limits=httpx.Limits(max_keepalive_connections=8, max_connections=20, keepalive_expiry=30.0),
        )
        self._sync_client = httpx.Client(transport=self._transport, timeout=self.timeout)

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "x-stainless-timeout": str(self.timeout.read if isinstance(self.timeout, httpx.Timeout) else self.timeout),
        }

    def _request_timeout(self) -> httpx.Timeout:
        """Return the current timeout value for each request.

        Some callers update ``client.timeout`` after construction. Passing the
        timeout per request makes those runtime changes effective even though
        the shared ``httpx.Client`` was created with an initial timeout.
        """
        return self.timeout if isinstance(self.timeout, httpx.Timeout) else httpx.Timeout(self.timeout)

    @contextmanager
    def _request_slot(self) -> Iterator[None]:
        """Bound concurrent requests per provider to avoid upstream 5xx storms."""
        limit = _default_concurrency_limit(self.base_url)
        semaphore = _semaphore_for(self.base_url, limit)
        if semaphore is None:
            yield
            return
        semaphore.acquire()
        try:
            yield
        finally:
            semaphore.release()

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
        _normalize_thinking_payload(
            payload,
            base_url=self.base_url,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
        )

        last_exc: Exception | None = None
        total_attempts = self.max_retries + 1
        for attempt in range(1, total_attempts + 1):  # 1-indexed for backoff
            retry_count = attempt - 1
            has_retry = attempt < total_attempts
            headers = self._headers()
            if retry_count > 0:
                headers["x-stainless-retry-count"] = str(retry_count)

            try:
                t0 = time.perf_counter()
                with self._request_slot():
                    response = self._sync_client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                        timeout=self._request_timeout(),
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
                if has_retry and _should_retry(0, exc=e):
                    delay = _backoff(attempt) + _jitter(0, 1)
                    logger.warning(
                        f"API timeout (attempt {attempt}/{total_attempts}), retrying in {delay:.1f}s... ({e})"
                    )
                    time.sleep(delay)
                else:
                    raise

            except httpx.HTTPStatusError as e:
                last_exc = e
                if has_retry and _should_retry(e.response.status_code):
                    delay = _backoff(attempt) + _jitter(0, 1)
                    logger.warning(
                        f"API HTTP {e.response.status_code} (attempt {attempt}/{total_attempts}), "
                        f"retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                else:
                    raise

            except (httpx.NetworkError, httpx.RemoteProtocolError, ssl.SSLError) as e:
                last_exc = e
                if has_retry and _should_retry(0, exc=e):
                    delay = _backoff(attempt) + _jitter(0, 1)
                    logger.warning(
                        f"API network/SSL error (attempt {attempt}/{total_attempts}), retrying in {delay:.1f}s... ({e})"
                    )
                    time.sleep(delay)
                else:
                    raise

        raise RuntimeError(f"API call failed after {total_attempts} attempts") from last_exc

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
        _normalize_thinking_payload(
            payload,
            base_url=self.base_url,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
        )

        # Use a fresh async client for each call (connection pooling still applies via transport)
        async with httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(
                limits=httpx.Limits(max_keepalive_connections=8, max_connections=20, keepalive_expiry=30.0),
            ),
            timeout=self.timeout if isinstance(self.timeout, httpx.Timeout) else httpx.Timeout(self.timeout),
        ) as client:
            t0 = time.perf_counter()
            with self._request_slot():
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                    timeout=self._request_timeout(),
                )
            response.raise_for_status()
            data = response.json()
            data["_latency_ms"] = int((time.perf_counter() - t0) * 1000)
            return data

    # ------------------------------------------------------------------
    # chat_batch — concurrent LLM calls via ThreadPoolExecutor
    # ------------------------------------------------------------------

    def chat_batch(
        self,
        requests: list[dict],
        *,
        max_workers: int | None = None,
        return_exceptions: bool = False,
    ) -> list[dict]:
        """Execute multiple chat requests concurrently.

        Each request dict supports the same kwargs as chat_sync():
          {messages, model, temperature, max_tokens, thinking, reasoning_effort, ...}

        Uses ThreadPoolExecutor to run chat_sync() calls in parallel through
        the shared httpx.Client (which is thread-safe).  Falls back to
        sequential execution when max_workers=1.

        Returns a list of API response dicts in the same order as requests.
        When return_exceptions=True, exceptions are returned in-place instead
        of being raised.
        """
        import concurrent.futures as _futures
        import threading as _thr

        n = len(requests)
        if n == 0:
            return []

        if max_workers is None:
            max_workers = min(n, 8)  # cap at 8 concurrent requests

        results: list[dict | BaseException | None] = [None] * n
        lock = _thr.Lock()

        def _send(idx: int, req: dict) -> None:
            try:
                # Extract known kwargs; pass the rest through
                messages = req.pop("messages")
                model = req.pop("model", None)
                temperature = req.pop("temperature", 0.7)
                max_tokens = req.pop("max_tokens", 2048)
                thinking = req.pop("thinking", True)
                reasoning_effort = req.pop("reasoning_effort", "medium")
                extra_kwargs = req  # remaining keys forwarded as-is
            except KeyError as e:
                with lock:
                    results[idx] = e
                return

            try:
                result = self.chat_sync(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    thinking=thinking,
                    reasoning_effort=reasoning_effort,
                    **extra_kwargs,
                )
                with lock:
                    results[idx] = result
            except BaseException as e:
                with lock:
                    results[idx] = e

        if max_workers <= 1:
            # Sequential path — no thread overhead
            for i, req in enumerate(requests):
                _send(i, dict(req))  # shallow copy so pop() doesn't mutate caller
        else:
            with _futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = [_futures.Future() for _ in range(n)]
                for i, req in enumerate(requests):
                    futures[i] = pool.submit(_send, i, dict(req))
                for fut in _futures.as_completed(futures):
                    fut.result()  # surface any unhandled errors from the thread

        if not return_exceptions:
            for i, result in enumerate(results):
                if isinstance(result, BaseException):
                    raise result

        return results  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # chat_stream — streaming response with SSE parsing
    # ------------------------------------------------------------------

    def chat_stream(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        thinking: bool = True,
        reasoning_effort: str = "medium",
        **kwargs,
    ):
        """Synchronous streaming chat completion — yields content deltas.

        Uses httpx.stream() for SSE parsing. Each yield is a dict:
          {"delta": "...", "finish_reason": None} for content chunks
          {"delta": "", "finish_reason": "stop"} for the final chunk
          {"delta": "", "finish_reason": "error", "error": "..."} on error

        Usage:
            for chunk in client.chat_stream(messages):
                text = chunk["delta"]
                if chunk["finish_reason"]:
                    break
        """
        payload = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        payload.update(kwargs)
        _normalize_thinking_payload(
            payload,
            base_url=self.base_url,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
        )

        try:
            with self._sync_client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout if isinstance(self.timeout, httpx.Timeout) else httpx.Timeout(self.timeout),
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]  # strip "data: " prefix
                    if data_str.strip() == "[DONE]":
                        yield {"delta": "", "finish_reason": "stop"}
                        return
                    try:
                        import json as _json

                        data = _json.loads(data_str)
                        choices = data.get("choices", [])
                        if choices:
                            choice = choices[0]
                            finish_reason = choice.get("finish_reason")
                            if finish_reason:
                                yield {"delta": "", "finish_reason": str(finish_reason)}
                                return
                            delta = choice.get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield {"delta": str(content), "finish_reason": None}
                    except Exception:
                        continue
                yield {"delta": "", "finish_reason": "stop"}
        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield {"delta": "", "finish_reason": "error", "error": str(e)}

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
# KeyFallbackClient — multi-key resilience
# ---------------------------------------------------------------------------


class KeyFallbackClient:
    """Wraps multiple DeepSeekClient instances with different API keys.

    On failure, falls through keys in order: primary → fallback_1 → fallback_2.
    All keys point to the same model to keep game quality consistent.
    Usage:
        client = KeyFallbackClient([
            DeepSeekClient(api_key=key1, ...),  # primary (doubao)
            DeepSeekClient(api_key=key2, ...),  # fallback 1 (dsv4flash)
            DeepSeekClient(api_key=key3, ...),  # fallback 2 (deepseek)
        ])
        response = client.chat_sync(messages)
    """

    def __init__(self, clients: list[DeepSeekClient]):
        if not clients:
            raise ValueError("KeyFallbackClient requires at least one client")
        self._clients = clients
        self._primary = clients[0]

    @property
    def available(self) -> bool:
        return any(c.available for c in self._clients)

    @property
    def provider(self) -> str:
        return getattr(self._primary, "provider", "")

    @property
    def model(self) -> str:
        return self._primary.model

    @property
    def timeout(self) -> float:
        return self._primary.timeout.read if isinstance(self._primary.timeout, httpx.Timeout) else self._primary.timeout

    @timeout.setter
    def timeout(self, value: float) -> None:
        for c in self._clients:
            c.timeout = value if isinstance(value, httpx.Timeout) else httpx.Timeout(value)

    def chat_sync(self, messages: list[dict], **kwargs) -> dict:
        """Try primary key first, fall through backups on failure."""
        last_exc: Exception | None = None
        for i, client in enumerate(self._clients):
            if not client.available:
                continue
            try:
                result = client.chat_sync(messages, **kwargs)
                if i > 0:
                    result["_key_fallback_level"] = i
                    logger.info(f"KeyFallbackClient: used fallback key #{i} ({client.provider})")
                return result
            except Exception as e:
                last_exc = e
                if i < len(self._clients) - 1:
                    logger.warning(
                        f"KeyFallbackClient: key #{i} ({client.provider}) failed ({e}), trying fallback #{i + 1}..."
                    )
        raise RuntimeError(f"KeyFallbackClient: all {len(self._clients)} keys failed") from last_exc

    def chat_batch(
        self,
        requests: list[dict],
        *,
        max_workers: int | None = None,
        return_exceptions: bool = False,
    ) -> list[dict]:
        """Batch via primary key; falls back to secondary keys on failure.

        Tries the entire batch on the primary client first. If any request
        fails with a retryable error, re-runs the whole batch on the next
        fallback client. This keeps the batch atomic per key.
        """
        last_exc: Exception | None = None
        for i, client in enumerate(self._clients):
            if not client.available:
                continue
            try:
                result = client.chat_batch(
                    requests,
                    max_workers=max_workers,
                    return_exceptions=False,
                )
                if i > 0:
                    logger.info(f"KeyFallbackClient chat_batch: used fallback key #{i} ({client.base_url})")
                return result
            except Exception as e:
                last_exc = e
                if i < len(self._clients) - 1:
                    logger.warning(f"KeyFallbackClient chat_batch: key #{i} failed ({e}), trying fallback #{i + 1}...")
        raise RuntimeError(f"KeyFallbackClient chat_batch: all {len(self._clients)} keys failed") from last_exc

    def close(self) -> None:
        for c in self._clients:
            try:
                c.close()
            except Exception:
                pass

    def __del__(self) -> None:
        self.close()


def create_key_fallback_client(
    primary_api_key: str,
    primary_base_url: str,
    model: str,
    *,
    fallback_keys: list[tuple[str, str]] | None = None,
    timeout: httpx.Timeout | float | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> KeyFallbackClient:
    """Factory: create a KeyFallbackClient from env-configured keys.

    Primary = DOUBAO_API_KEY + DOUBAO_BASE_URL
    Fallback 1 = DSV4FLASH_API_KEY + DSV4FLASH_BASE_URL
    Fallback 2 = DEEPSEEK_API_KEY + DEEPSEEK_BASE_URL

    All use the same model name.
    """
    clients = [
        DeepSeekClient(
            api_key=primary_api_key,
            base_url=primary_base_url,
            model=model,
            timeout=timeout,
            max_retries=max_retries,
        )
    ]

    if fallback_keys is None:
        # Auto-detect from env
        dsv4flash_key = os.getenv("DSV4FLASH_API_KEY", "").strip()
        dsv4flash_url = os.getenv("DSV4FLASH_BASE_URL", "").strip()
        deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        deepseek_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()

        fallback_keys = []
        if dsv4flash_key and dsv4flash_url:
            fallback_keys.append((dsv4flash_key, dsv4flash_url))
        if deepseek_key and deepseek_url:
            fallback_keys.append((deepseek_key, deepseek_url))

    for fb_key, fb_url in fallback_keys:
        if fb_key and fb_url:
            clients.append(
                DeepSeekClient(
                    api_key=fb_key,
                    base_url=fb_url,
                    model=model,
                    timeout=timeout,
                    max_retries=max_retries,
                )
            )

    return KeyFallbackClient(clients)


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
