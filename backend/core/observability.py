"""Small, bounded process metrics and correlation-safe structured events."""

from __future__ import annotations

import json
import logging
import threading
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_context: ContextVar[dict[str, str | None] | None] = ContextVar("operation_context", default=None)
_counts: Counter[str] = Counter()
_lock = threading.Lock()


@contextmanager
def operation_context(*, request_id: str | None = None, match_id: str | None = None, room_id: str | None = None):
    token = _context.set({"request_id": request_id, "match_id": match_id, "room_id": room_id})
    try:
        yield
    finally:
        _context.reset(token)


def count(name: str, amount: int = 1) -> None:
    """Callers supply fixed metric names, never IDs or user-provided labels."""
    with _lock:
        _counts[name] += amount


def metrics_snapshot() -> dict[str, Any]:
    with _lock:
        return {"scope": "process", "counters": dict(sorted(_counts.items()))}


def log_event(logger: logging.Logger, event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    # Deliberately do not include headers, bodies, query strings or exception text.
    payload = {
        "event": event,
        "request_id": None,
        "match_id": None,
        "room_id": None,
        **(_context.get() or {}),
        **fields,
    }
    logger.log(level, json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True))
