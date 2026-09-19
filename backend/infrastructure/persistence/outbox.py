from __future__ import annotations

from datetime import datetime
from datetime import timezone
from typing import Any

from backend.db.database import SessionLocal
from backend.db.models import OutboxEvent


class OutboxRepository:
    """Durable events awaiting publication to Redis/Kafka or another broker."""

    def pending(self, limit: int = 100) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            rows = (
                db.query(OutboxEvent)
                .filter(OutboxEvent.status == "pending", OutboxEvent.available_at <= datetime.now(timezone.utc))
                .order_by(OutboxEvent.created_at.asc())
                .limit(limit)
                .all()
            )
            return [self._to_dict(row) for row in rows]

    def mark_published(self, event_id: str) -> None:
        with SessionLocal.begin() as db:
            row = db.query(OutboxEvent).filter(OutboxEvent.id == event_id).one()
            row.status = "published"
            row.published_at = datetime.now(timezone.utc)

    @staticmethod
    def _to_dict(row: OutboxEvent) -> dict[str, Any]:
        return {
            "id": row.id,
            "aggregate_type": row.aggregate_type,
            "aggregate_id": row.aggregate_id,
            "event_type": row.event_type,
            "payload": dict(row.payload or {}),
            "attempts": row.attempts,
        }
