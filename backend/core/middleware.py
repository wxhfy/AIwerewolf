from __future__ import annotations

import asyncio
import logging
import time
import uuid

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.responses import Response

from backend.core.config import Settings

logger = logging.getLogger("aiwerewolf.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id", "").strip()[:128] or str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.2f}"
        logger.info(
            "%s %s -> %s %.2fms request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            request_id,
        )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response


class RequestBodyLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int) -> None:
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next) -> Response:
        content_length = request.headers.get("content-length")
        try:
            too_large = bool(content_length and int(content_length) > self.max_bytes)
        except ValueError:
            too_large = False
        if too_large:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body too large", "code": "request_body_too_large"},
            )
        return await call_next(request)


class RedisRateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window distributed rate limit. Disabled when requests=0 or Redis is absent."""

    def __init__(self, app, *, redis_url: str, requests: int, window_seconds: int) -> None:
        super().__init__(app)
        self.redis_url = redis_url
        self.requests = requests
        self.window_seconds = window_seconds
        self._client = None

    def _consume(self, key: str) -> int:
        if self._client is None:
            import redis

            self._client = redis.Redis.from_url(self.redis_url, decode_responses=True)
        pipeline = self._client.pipeline()
        pipeline.incr(key)
        pipeline.expire(key, self.window_seconds, nx=True)
        count, _ = pipeline.execute()
        return int(count)

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self.redis_url or self.requests <= 0 or request.url.path.startswith("/api/v1/health/"):
            return await call_next(request)
        identity = request.client.host if request.client else "unknown"
        bucket = int(time.time()) // self.window_seconds
        key = f"rate-limit:{identity}:{bucket}"
        try:
            count = await asyncio.to_thread(self._consume, key)
        except Exception:
            logger.warning("Rate limiter unavailable; allowing request", exc_info=True)
            return await call_next(request)
        if count > self.requests:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded", "code": "rate_limit_exceeded"},
                headers={"Retry-After": str(self.window_seconds)},
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.requests)
        response.headers["X-RateLimit-Remaining"] = str(max(0, self.requests - count))
        return response


def install_middleware(app: FastAPI, config: Settings) -> None:
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=config.max_request_body_bytes)
    app.add_middleware(
        RedisRateLimitMiddleware,
        redis_url=config.redis_url,
        requests=config.rate_limit_requests,
        window_seconds=config.rate_limit_window_seconds,
    )
    app.add_middleware(RequestContextMiddleware)
