from __future__ import annotations

from typing import Any

from backend.db.database import SessionLocal
from backend.db.models import Game
from backend.db.models import GameEvent
from backend.db.models import GameSnapshot


class MatchFeedRepository:
    """Read model used by event queries and SSE delivery."""

    def list_events(
        self,
        match_id: str,
        *,
        after_seq: int = 0,
        limit: int = 200,
        include_private: bool = False,
    ) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            query = db.query(GameEvent).filter(
                GameEvent.game_id == match_id,
                GameEvent.seq > max(0, after_seq),
            )
            if not include_private:
                query = query.filter(GameEvent.visibility == "public")
            rows = query.order_by(GameEvent.seq.asc()).limit(max(1, min(limit, 1000))).all()
            return [
                {
                    "id": row.id,
                    "match_id": row.game_id,
                    "seq": row.seq,
                    "ts": row.ts,
                    "day": row.day,
                    "phase": row.phase,
                    "type": row.event_type,
                    "actor_id": row.actor_id,
                    "target_id": row.target_id,
                    "visibility": row.visibility,
                    "payload": row.content or {},
                }
                for row in rows
            ]

    def list_snapshots(
        self,
        match_id: str,
        *,
        after_seq: int = 0,
        limit: int = 100,
        moderator: bool = False,
    ) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            rows = (
                db.query(GameSnapshot)
                .filter(
                    GameSnapshot.game_id == match_id,
                    GameSnapshot.seq > max(0, after_seq),
                )
                .order_by(GameSnapshot.seq.asc())
                .limit(max(1, min(limit, 500)))
                .all()
            )
            return [dict(row.truth_state if moderator else row.public_state) for row in rows]

    def match_status(self, match_id: str) -> str | None:
        with SessionLocal() as db:
            row = db.query(Game.status).filter(Game.id == match_id).first()
            return str(row[0]) if row else None

    def latest_snapshot(self, match_id: str, *, moderator: bool = False) -> dict[str, Any] | None:
        with SessionLocal() as db:
            row = (
                db.query(GameSnapshot)
                .filter(GameSnapshot.game_id == match_id)
                .order_by(GameSnapshot.seq.desc())
                .first()
            )
            if row is None:
                return None
            return dict(row.truth_state if moderator else row.public_state)
