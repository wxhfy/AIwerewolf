from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


def _channel(match_id: str) -> str:
    return f"matches:{match_id}:updated"


@dataclass
class MatchSubscription:
    client: Any
    pubsub: Any

    async def wait(self, timeout: float) -> bool:
        message = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=timeout)
        return message is not None

    async def close(self) -> None:
        await self.pubsub.unsubscribe()
        await self.pubsub.aclose()
        await self.client.aclose()


class MatchNotificationBus:
    """Redis wake-up signals; PostgreSQL remains the source of truth."""

    def __init__(self, url: str | None = None) -> None:
        self.url = (url if url is not None else os.getenv("REDIS_URL", "")).strip()
        self._publisher: Any = None

    def publish(self, match_id: str, seq: int) -> None:
        if not self.url:
            return
        try:
            if self._publisher is None:
                from redis import Redis

                self._publisher = Redis.from_url(self.url, decode_responses=True)
            self._publisher.publish(_channel(match_id), str(seq))
        except Exception:
            logger.warning("Redis match notification failed for %s seq %s", match_id, seq, exc_info=True)

    async def subscribe(self, match_id: str) -> MatchSubscription | None:
        if not self.url:
            return None
        try:
            from redis.asyncio import Redis

            client = Redis.from_url(self.url, decode_responses=True)
            pubsub = client.pubsub()
            await pubsub.subscribe(_channel(match_id))
            return MatchSubscription(client=client, pubsub=pubsub)
        except Exception:
            logger.warning("Redis match subscription failed for %s", match_id, exc_info=True)
            return None

    def health(self) -> str:
        if not self.url:
            return "disabled"
        try:
            if self._publisher is None:
                from redis import Redis

                self._publisher = Redis.from_url(self.url, decode_responses=True)
            return "ok" if self._publisher.ping() else "error"
        except Exception as exc:
            return f"error: {exc}"


match_notifications = MatchNotificationBus()
